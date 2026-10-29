"""Chunks play in order with torque held between them; the judge gets settled state and grasp outcome."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

OMX = Path(__file__).parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    spec = importlib.util.spec_from_file_location("chunk_runner", OMX / "chunk_runner.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
finally:
    sys.path.remove(str(OMX))

HOME = [0.0, -60.0, 50.0, 45.0, 10.0, 46.6]


class Robot:
    """Follows each action at once, except the gripper stops at `object_at` (an object between the jaws)
    and joints listed in `blocked` stay put."""

    def __init__(self, object_at=None, blocked=()):
        self.pos, self.sent, self.object_at, self.blocked = list(HOME), [], object_at, blocked

    def send_action(self, action):
        self.sent.append(action)
        for i, name in enumerate(m.NAMES):
            if i in self.blocked:
                continue
            value = action[name]
            if i == 5 and self.object_at is not None:
                value = max(value, self.object_at)
            self.pos[i] = value

    def get_observation(self):
        return dict(zip(m.NAMES, self.pos))


def library():
    approach = [[k * 2.0, -60.0, 50.0, 45.0, 10.0, 46.6 + k] for k in range(10)]  # pan 0 -> 18, jaws open
    grasp = [[18.0, -60.0, 50.0, 45.0, 10.0, 55.6 - k] for k in range(10)]        # jaws close to 46.6
    return {"schema": m.SCHEMA, "names": m.NAMES, "gripper_closed": 46.6,
            "chunks": {"approach_pinky": approach, "grasp_pinky": grasp}}


def runner(robot, commands):
    status, clock = [], [0.0]
    queue = list(commands)

    def lines():
        return [queue.pop(0)] if queue and not r.chunk else []

    def sleep(seconds):
        clock[0] += 1 / 30

    r = m.Runner(robot, library(), fps=30, status=status.append, clock=lambda: clock[0], sleep=sleep)
    r.run(lines)
    return status


def by_command(status, command):
    return [s for s in status if s["command"] == command]


def test_checked_commands_bind_the_session_and_library_at_the_motion_boundary():
    robot, status = Robot(), []
    r = m.Runner(robot, library(), fps=30, status=status.append,
                 operating_context={"scope": "simulation", "sha256": "a" * 64, "session_id": "current"})
    r.target = list(HOME)
    reviewed = m.digest(r.library)
    r.command(f"checked other {reviewed} run approach_pinky")
    assert not status[-1]["ok"] and "session" in status[-1]["error"]
    r.library = {**r.library, "gripper_closed": 48.0}
    r.command(f"checked current {reviewed} run approach_pinky")
    assert not status[-1]["ok"] and "library" in status[-1]["error"]
    assert not r.queue and not robot.sent


def test_checked_load_validates_content_before_replacing_the_library(tmp_path):
    import json

    status = []
    r = m.Runner(Robot(), library(), fps=30, status=status.append,
                 operating_context={"session_id": "current"})
    r.target = list(HOME)
    original = r.library
    candidate = {**library(), "fps": 30, "chunks": {"home": [HOME]}}
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(candidate))
    r.command(f"checked current {'0' * 64} load {path}")
    assert not status[-1]["ok"] and r.library is original
    r.command(f"checked current {m.digest(candidate)} load {path}")
    assert status[-1]["ok"] and r.library == candidate


def test_manual_intervention_invalidates_the_automatic_command_chain():
    status = []
    r = m.Runner(Robot(), library(), fps=30, status=status.append,
                 operating_context={"session_id": "current"})
    r.target = list(HOME)
    reviewed = m.digest(r.library)
    r.command("grip 50")
    assert r.operating_context["session_id"] != "current"
    r.command(f"checked current {reviewed} run approach_pinky")
    assert not status[-1]["ok"] and not r.queue


def test_a_chunk_plays_then_holds_and_reports_the_settled_state():
    robot = Robot()
    status = runner(robot, ["run approach_pinky", "state", "state", "state", "stop"])
    done = by_command(status, "run approach_pinky")[0]
    assert done["ok"] and done["settled"] and done["state"][0] == 18.0
    assert by_command(status, "state")[0]["state"][0] == 18.0  # held after the chunk, not dropped
    assert all(a["shoulder_pan.pos"] == 18.0 for a in robot.sent[-3:])


@pytest.mark.parametrize("object_at, holding", [(None, False), (51.0, True)])
def test_a_grasp_reports_whether_anything_is_between_the_jaws(object_at, holding):
    status = runner(Robot(object_at=object_at), ["run approach_pinky", "run grasp_pinky", "stop"])
    assert by_command(status, "run grasp_pinky")[0]["holding"] is holding


def test_a_chunk_out_of_order_and_a_large_jog_are_refused_without_motion():
    robot = Robot()
    status = runner(robot, ["run grasp_pinky", "jog shoulder_pan.pos 9", "jog nonsense 1", "stop"])
    assert [s["ok"] for s in status[1:4]] == [False, False, False]
    assert "starts" in status[1]["error"] and "limited" in status[2]["error"]
    assert all(a["shoulder_pan.pos"] == 0.0 for a in robot.sent)


def test_a_relative_chunk_keeps_the_judges_correction_and_a_huge_one_is_refused():
    robot = Robot()
    status = runner(robot, ["run approach_pinky", "jog shoulder_pan.pos -5", "jog shoulder_pan.pos -5",
                            "run grasp_pinky rel", "stop"])
    done = by_command(status, "run grasp_pinky")[0]  # status names the chunk
    assert done["ok"] and done["state"][0] == 8.0 and done["state"][5] == 46.6  # pan 18 - 10, jaws not shifted
    lib = library()
    lib["chunks"]["grasp_pinky"] = [[f[0] + 40, *f[1:]] for f in lib["chunks"]["grasp_pinky"]]
    clock, out, queue = [0.0], [], ["run grasp_pinky rel", "stop"]
    r = m.Runner(Robot(), lib, fps=30, status=out.append, clock=lambda: clock[0],
                 sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))
    r.run(lambda: [queue.pop(0)] if queue and not r.chunk else [])
    assert out[1]["ok"] is False and "exceeds" in out[1]["error"]


def test_a_coordinated_jog_moves_its_joints_together_or_not_at_all():
    robot = Robot()
    runner(robot, ["jog shoulder_lift.pos 3 elbow_flex.pos -3 wrist_flex.pos 2", "stop"])
    assert robot.pos[1:4] == [-57.0, 47.0, 47.0]
    robot = Robot()
    status = runner(robot, ["jog shoulder_lift.pos 3 elbow_flex.pos -9", "jog shoulder_lift.pos 1 shoulder_lift.pos 1",
                            "stop"])
    assert [s["ok"] for s in status[1:3]] == [False, False]
    assert robot.pos == HOME  # the valid lift step was not applied alone


def test_park_closes_rises_turns_then_descends_slowly():
    start = [35.0, -30.0, 29.0, 41.0, 71.0, 56.0]
    path = m.park_path(start, HOME, 46.6, fps=30)
    step = m.PARK_SPEED / 30 + 1e-9
    assert all(max(abs(b - a) for a, b in zip(p, q)) <= step for p, q in zip([start] + path, path))
    closed = next(i for i, f in enumerate(path) if f[5] == pytest.approx(46.6))
    turning = next(i for i, f in enumerate(path) if abs(f[0] - start[0]) > 1e-6)
    turned = next(i for i, f in enumerate(path) if f[0] == pytest.approx(HOME[0]) and f[4] == pytest.approx(HOME[4]))
    assert closed < turning < turned  # the jaws close before anything turns
    # never turn while low (the head scraped the table on 2026-10-24): the turn may begin only as the rise
    # ends, with lift and elbow within a unit of the transit height (the blended corner)
    assert all(f[1] >= -28.0 and f[2] <= 19.0 for f in path[turning:turned + 1])
    assert path[-1][:5] == pytest.approx(HOME[:5])


def test_slower_transit_speed_rises_at_that_fraction_and_bad_values_are_refused(tmp_path):
    start = [35.0, -10.0, 9.0, 41.0, 71.0, 46.6]  # reached out low: the rise is a long shoulder move
    fast, slow = m.park_path(start, HOME, 46.6, fps=30), m.park_path(start, HOME, 46.6, fps=30, speed=0.4)
    step = 0.4 * m.PARK_SPEED / 30 + 1e-9
    assert all(max(abs(b - a) for a, b in zip(p, q)) <= step for p, q in zip([start] + slow, slow))
    assert len(slow) > 1.8 * len(fast) and slow[-1][:5] == pytest.approx(HOME[:5])
    for bad in (0.95, 0, "slow", True):
        path = tmp_path / "lib.json"
        path.write_text(json.dumps(dict(library(), fps=30, chunks={"home": [HOME]}, transit_speed=bad)))
        with pytest.raises(SystemExit, match="transit_speed"):
            m.load_library(path)


def test_goto_reaches_a_chunk_start_by_rising_turning_and_descending():
    goal = [-3.0, -16.0, 9.0, 48.0, 5.0, 55.0]  # over the belt, jaws open
    path = m.transit_path(HOME, goal, 46.6, fps=30)
    turning = next(i for i, f in enumerate(path) if abs(f[0] - HOME[0]) > 1e-6)
    assert path[turning][1] >= -28.0 and path[turning][2] <= 19.0  # no turn while low: only as the rise ends
    arrived = next(f for f in path if f[:5] == pytest.approx(goal[:5]))
    # jaws open only at the goal (sampled at 30 fps, the arrival frame may hold the opening's first 0.001)
    assert arrived[5] == pytest.approx(46.6, abs=0.01) and path[-1] == pytest.approx(goal)
    lib = library()
    status = run_with(Robot(), lib, ["goto grasp_pinky", "run grasp_pinky", "stop"])
    assert by_command(status, "run goto grasp_pinky")[0]["settled"]
    assert by_command(status, "run grasp_pinky")[0]["ok"] is True  # starts where goto left the arm


def test_park_runs_through_the_runner_and_needs_a_home_chunk():
    lib = library()
    lib["chunks"]["home"] = [HOME]
    robot, status, clock, queue = Robot(), [], [0.0], ["run approach_pinky", "park", "stop"]
    r = m.Runner(robot, lib, fps=30, status=status.append, clock=lambda: clock[0],
                 sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))
    r.run(lambda: [queue.pop(0)] if queue and not r.chunk else [])
    done = by_command(status, "run park")[0]
    assert done["settled"] and done["state"][:5] == pytest.approx(HOME[:5])
    refused = runner(Robot(), ["park", "stop"])  # library() has no home chunk
    assert refused[1]["ok"] is False and "home chunk" in refused[1]["error"]


def test_a_session_nobody_talks_to_folds_home_then_ends_so_torque_goes_off():
    lib = library()
    lib["chunks"]["home"] = [HOME]
    robot, status, clock, queue = Robot(), [], [0.0], ["run approach_pinky"]  # then the link is lost
    r = m.Runner(robot, lib, fps=30, status=status.append, clock=lambda: clock[0],
                 sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))
    r.run(lambda: [queue.pop(0)] if queue and not r.chunk else [])  # returns: the session ends by itself
    park, end = by_command(status, "run park")[0], status[-1]
    assert park["ok"] and park["state"][:5] == pytest.approx(HOME[:5])
    assert end["command"] == "stop" and "no command" in end["reason"]
    assert clock[0] >= m.IDLE_PARK_S + m.IDLE_STOP_S


def test_a_caller_that_keeps_asking_for_state_keeps_the_arm_where_it_is():
    lib = library()
    lib["chunks"]["home"] = [HOME]
    status, clock, sent = [], [0.0], []

    def lines():  # a `state` every 100 s for 10 minutes, then stop
        due = int(clock[0] // 100)
        if due > len(sent):
            sent.append(due)
            return ["stop"] if clock[0] > 600 else ["state"]
        return ["run approach_pinky"] if not sent and clock[0] < 1 / 30 else []

    r = m.Runner(Robot(), lib, fps=30, status=status.append, clock=lambda: clock[0],
                 sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))
    r.run(lines)
    assert not by_command(status, "run park") and status[-1]["command"] == "stop" and "reason" not in status[-1]


class Bus:
    """Present_PWM / Present_Current / Present_Temperature per motor name, raw like the Dynamixel bus."""

    def __init__(self, pwm=None, current=None, temp=None):
        names = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
        self.values = {"Present_PWM": dict.fromkeys(names, 0), "Present_Current": dict.fromkeys(names, 0),
                       "Present_Temperature": dict.fromkeys(names, 35)}
        for key, extra in (("Present_PWM", pwm), ("Present_Current", current), ("Present_Temperature", temp)):
            self.values[key].update(extra or {})
        self.reads = 0

    def sync_read(self, name):
        self.reads += 1
        return dict(self.values[name])


def run_with(robot, lib, commands):
    status, clock, queue = [], [0.0], list(commands)
    r = m.Runner(robot, lib, fps=30, status=status.append, clock=lambda: clock[0],
                 sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))
    r.run(lambda: [queue.pop(0)] if queue and not r.chunk else [])
    return status


def lifting_library():
    lib = library()
    lib["chunks"]["home"] = [HOME]
    lib["chunks"]["approach_pinky"] = [[0.0, -60.0 + k, 50.0, 45.0, 10.0, 46.6] for k in range(12)]  # lift rises
    return lib


@pytest.mark.parametrize("blocked, bus, reason", [
    ((1,), Bus(pwm={"shoulder_lift": 290}), "stalled"),
    ((1,), Bus(pwm={"shoulder_lift": 65536 - 290}), "stalled"),  # negative raw reads as a large unsigned value
    ((), Bus(temp={"elbow_flex": 66}), "temperature"),
])
def test_a_stalled_or_hot_arm_stops_where_it_is_and_only_parks(blocked, bus, reason):
    robot = Robot(blocked=blocked)
    robot.bus = bus
    # a still-blocked joint cannot park (the following-error stop would end the run), so park only when free
    # health is sampled once a second: hold long enough for a sample before the next chunk
    commands = ["run approach_pinky"] + ["state"] * 40 + ["run grasp_pinky"] + ([] if blocked else ["park"]) + ["stop"]
    status = run_with(robot, lifting_library(), commands)
    fault = next(s for s in status if s["ok"] is False and reason in s.get("error", ""))
    assert fault["fault"] and fault["health"]
    refused = next(s for s in status if s["command"] == "run grasp_pinky" and s is not fault)
    assert refused["ok"] is False and "only park" in refused["error"]
    if not blocked:
        assert by_command(status, "run park")[0]["ok"] is True


def test_pushing_at_the_cap_while_following_is_normal():
    robot = Robot()  # the elbow saturates while lifting out of home, yet the arm keeps up
    robot.bus = Bus(pwm={"elbow_flex": 300, "shoulder_lift": 300})
    status = run_with(robot, lifting_library(), ["run approach_pinky", "stop"])
    assert by_command(status, "run approach_pinky")[0]["ok"] is True and not any(s.get("fault") for s in status)


@pytest.mark.parametrize("current, holding", [(120, True), (20, False)])
def test_a_measured_hold_current_must_agree_with_the_jaw_position(current, holding):
    robot = Robot(object_at=51.0)  # jaws stop short: position alone says holding
    robot.bus = Bus(current={"gripper": current})
    lib = library()
    lib["hold_current_ma"] = 80
    status = run_with(robot, lib, ["run approach_pinky", "run grasp_pinky", "stop"])
    done = by_command(status, "run grasp_pinky")[0]
    assert done["holding"] is holding and done["gripper_current_ma"] == current


def test_the_live_state_is_published_about_twice_a_second():
    rows, clock, queue = [], [0.0], ["run approach_pinky", "state", "stop"]
    r = m.Runner(Robot(), library(), fps=10, status=lambda row: None, clock=lambda: clock[0],
                 sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 10), live=rows.append)
    r.run(lambda: [queue.pop(0)] if queue and not r.chunk else [])
    assert rows and set(rows[-1]) == {"t", "state", "target", "chunk", "fault", "health"}
    assert rows[-1]["state"][0] == 18.0  # held at the end of the approach chunk


def test_a_small_jog_and_grip_move_only_their_joint():
    robot = Robot()
    runner(robot, ["jog wrist_flex.pos -4", "grip 55", "stop"])
    assert robot.pos[3] == 41.0 and robot.pos[5] == 55.0 and robot.pos[:3] == HOME[:3]


def test_an_empty_grasp_is_judged_after_the_slow_jaws_stop():
    class SlowJaws(Robot):  # the real gripper closes over many ticks after its last target
        def send_action(self, action):
            target = action["gripper.pos"]
            super().send_action({**action, "gripper.pos": self.pos[5]})
            self.pos[5] += max(-0.5, min(0.5, target - self.pos[5]))

    status = runner(SlowJaws(), ["run approach_pinky", "run grasp_pinky", "stop"])
    done = by_command(status, "run grasp_pinky")[0]
    assert done["holding"] is False and done["state"][5] == pytest.approx(46.6)


def test_a_burst_of_jogs_against_a_joint_that_does_not_follow_is_refused():
    robot = Robot(blocked=(1,))
    status, clock = [], [0.0]
    burst = [["jog shoulder_lift.pos 5", "jog shoulder_lift.pos 5", "jog shoulder_lift.pos 5", "stop"]]
    r = m.Runner(robot, library(), fps=30, status=status.append, clock=lambda: clock[0],
                 sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))
    r.run(lambda: burst.pop() if burst else [])  # all four lines arrive in one read
    assert [s["ok"] for s in status[1:4]] == [True, False, False]
    assert max(a["shoulder_lift.pos"] for a in robot.sent) == -55.0


def test_a_blocked_arm_stops_the_runner():
    far = library()
    far["chunks"]["approach_pinky"] = [[k * 3.0, -60.0, 50.0, 45.0, 10.0, 46.6] for k in range(20)]
    robot = Robot(blocked=(0,))
    status, clock = [], [0.0]
    queue = ["run approach_pinky"]
    r = m.Runner(robot, far, fps=30, status=status.append, clock=lambda: clock[0],
                 sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))
    with pytest.raises(RuntimeError, match="following error"):
        r.run(lambda: [queue.pop(0)] if queue else [])


class GuardStops(Robot):
    """The guard raises in the middle of a chunk (following error), or the bus dies and reads fail too."""

    def __init__(self, after, bus_dead=False):
        super().__init__()
        self.after, self.bus_dead, self.dead = after, bus_dead, False

    def send_action(self, action):
        if len(self.sent) >= self.after:
            self.dead = self.bus_dead
            raise ValueError("wrist_flex: following error >5 motor degrees; command=3344, current=3287")
        super().send_action(action)

    def get_observation(self):
        if self.dead:
            raise ConnectionError("Failed to sync read 'Present_Position'")
        return super().get_observation()


@pytest.mark.parametrize("bus_dead", [False, True])
def test_a_session_that_ends_mid_chunk_says_so_in_its_last_status(bus_dead):
    status, clock, queue = [], [0.0], ["run approach_pinky"]
    r = m.Runner(GuardStops(after=4, bus_dead=bus_dead), library(), fps=30, status=status.append,
                 clock=lambda: clock[0], sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))
    with pytest.raises(ValueError, match="following error"):  # the stop itself is untouched
        r.run(lambda: [queue.pop(0)] if queue else [])
    last = status[-1]
    assert last["command"] == "run approach_pinky" and last["ok"] is False
    assert last["fault"].startswith("session ended: ValueError: wrist_flex: following error")


class SlowWrist(Robot):
    """wrist_flex follows at most `rate` units a tick, and the guard stops past 2.78 units (5 motor degrees)."""

    def __init__(self, rate=0.1):
        super().__init__()
        self.rate, self.worst = rate, 0.0

    def send_action(self, action):
        self.sent.append(action)
        for i, name in enumerate(m.NAMES):
            step = action[name] - self.pos[i]
            self.pos[i] += max(-self.rate, min(self.rate, step)) if i == 3 else step
        self.worst = max(self.worst, abs(action["wrist_flex.pos"] - self.pos[3]))
        if self.worst > 2.78:
            raise ValueError("wrist_flex: following error >5 motor degrees")
        return action


def test_pacing_and_idle_thresholds_come_from_the_params_a_runner_is_given():
    lift = library()
    lift["chunks"]["approach_pinky"] = [[0.0, -60.0, 50.0, 45.0 + 0.15 * k, 10.0, 46.6] for k in range(1, 101)]
    robot, status, clock, queue = SlowWrist(), [], [0.0], ["run approach_pinky", "stop"]
    r = m.Runner(robot, lift, fps=30, status=status.append, clock=lambda: clock[0], params={"runner.pace_lag": 99.0},
                 sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))
    with pytest.raises(ValueError, match="following error"):  # the same run the PACE_LAG patch below lets fail
        r.run(lambda: [queue.pop(0)] if queue and not r.chunk else [])
    lib = library()
    lib["chunks"]["home"] = [HOME]
    status, clock, queue = [], [0.0], ["run approach_pinky"]
    r = m.Runner(Robot(), lib, fps=30, status=status.append, clock=lambda: clock[0],
                 sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30), params={"runner.idle_park_s": 7.0, "runner.idle_stop_s": 9.0})
    r.run(lambda: [queue.pop(0)] if queue and not r.chunk else [])
    assert 16.0 <= clock[0] < 100.0 and status[-1]["command"] == "stop"  # not the 360 s of the built-in values


@pytest.mark.parametrize("paced", [True, False])
def test_a_lagging_joint_holds_the_next_frame_until_it_catches_up_before_the_guard_stops(monkeypatch, paced):
    if not paced:
        monkeypatch.setattr(m, "PACE_LAG", 99.0)
    lift = library()
    lift["chunks"]["approach_pinky"] = [[0.0, -60.0, 50.0, 45.0 + 0.15 * k, 10.0, 46.6] for k in range(1, 101)]
    robot, status, clock, queue = SlowWrist(), [], [0.0], ["run approach_pinky", "stop"]
    r = m.Runner(robot, lift, fps=30, status=status.append, clock=lambda: clock[0],
                 sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))
    if not paced:  # the wrist falls 0.05 units a tick further behind and the guard turns torque off
        with pytest.raises(ValueError, match="following error"):
            r.run(lambda: [queue.pop(0)] if queue and not r.chunk else [])
        return
    r.run(lambda: [queue.pop(0)] if queue and not r.chunk else [])
    done = by_command(status, "run approach_pinky")[0]
    assert done["ok"] and done["settled"] and done["paced_ticks"] > 0
    assert 60.0 - done["state"][3] <= m.PACE_LAG + 0.2  # the whole chunk played; settled within the runner's tolerance
    assert robot.worst < m.PACE_LAG + 0.2  # held near the pace bound, far from the guard's


class DroopingWrist(SlowWrist):
    """Reached out, the wrist sits `droop` units under its command even at rest (2.08 over the conveyor)."""

    def __init__(self, droop=2.0):
        super().__init__(rate=1.0)
        self.droop = droop

    def send_action(self, action):
        self.sent.append(action)
        for i, name in enumerate(m.NAMES):
            self.pos[i] = action[name] - (self.droop if i == 3 else 0.0)
        self.worst = max(self.worst, abs(action["wrist_flex.pos"] - self.pos[3]))
        return action


def test_a_steady_droop_is_not_waited_out_frame_by_frame():
    lift = library()
    lift["chunks"]["approach_pinky"] = [[0.0, -60.0, 50.0, 45.0 + 0.15 * k, 10.0, 46.6] for k in range(1, 101)]
    status, clock, queue = [], [0.0], ["run approach_pinky", "stop"]
    r = m.Runner(DroopingWrist(), lift, fps=30, status=status.append, clock=lambda: clock[0],
                 sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))
    r.run(lambda: [queue.pop(0)] if queue and not r.chunk else [])
    done = by_command(status, "run approach_pinky")[0]
    assert done["ok"] and done["paced_ticks"] <= 3  # one look at a lag that does not shrink, then on
    assert clock[0] < 100 / 30 + m.SETTLE_S + 1  # 2026-10-28: one frame per 3 s took a park past 300 s


def test_the_library_contract_is_enforced(tmp_path):
    import json
    bad = {**library(), "fps": 2}  # 2 units per frame is within the guard speed at 2 fps
    bad["chunks"]["grasp_pinky"][0][1] = 130.0
    path = tmp_path / "lib.json"
    path.write_text(json.dumps(bad))
    with pytest.raises(SystemExit, match="within"):
        m.load_library(path)


def test_a_library_faster_than_the_guard_streams_is_refused(tmp_path):
    import json
    path = tmp_path / "lib.json"
    path.write_text(json.dumps({**library(), "fps": 30}))  # 2 units per frame at 30 fps = 60 units/s
    with pytest.raises(SystemExit, match="faster than the guard"):
        m.load_library(path)
    path.write_text(json.dumps({**library(), "fps": 2}))
    assert m.load_library(path)["fps"] == 2


def test_the_runner_reads_motor_health_about_once_a_second_beside_the_guard():
    robot = Robot()
    robot.bus = Bus()
    status = run_with(robot, library(), ["run approach_pinky"] + ["state"] * 90 + ["stop"])
    ticks = len(robot.sent)
    assert ticks >= 90 and 3 <= robot.bus.reads <= 3 * (ticks // 30 + 1)  # three registers a second, not every 3rd tick
    assert status[-1]["command"] == "stop"


def test_a_new_library_loads_while_the_arm_holds_and_a_bad_one_is_refused(tmp_path):
    import json
    good = {**library(), "fps": 30}
    good["chunks"] = {"approach_pinky": [[0.0, -60.0, 50.0, 45.0, 10.0, 46.6 + k * 0.1] for k in range(5)]}
    fast = {**library(), "fps": 30}  # 2 units per frame: faster than the guard streams
    other_fps = {**good, "fps": 10}
    paths = {}
    for name, lib in (("good", good), ("fast", fast), ("other_fps", other_fps)):
        paths[name] = tmp_path / f"{name}.json"
        paths[name].write_text(json.dumps(lib))
    status = runner(Robot(), [f"load {paths['fast']}", f"load {paths['other_fps']}", f"load {paths['good']}",
                              "run approach_pinky", "stop"])
    loads = by_command(status, f"load {paths['fast']}") + by_command(status, f"load {paths['other_fps']}")
    assert [s["ok"] for s in loads] == [False, False]
    assert "faster than the guard" in loads[0]["error"] and "fps" in loads[1]["error"]
    assert by_command(status, f"load {paths['good']}")[0]["ok"] is True
    assert by_command(status, "run approach_pinky")[0]["ok"] is True  # the loaded library's chunk


def test_a_grip_below_the_taught_closed_value_is_held_at_closed():
    status = runner(Robot(), ["grip 40", "state", "stop"])
    assert by_command(status, "grip 40")[0]["target"][5] == 46.6  # past the stop the jaws would only push


class Pressing(Robot):
    """Reports the commanded pose like the guard does; after `after` actions the lift joint stops following
    (the box under the jaws), so the present pose lags the command."""

    def __init__(self, after, **kw):
        super().__init__(**kw)
        self.after, self.count, self.stuck = after, 0, None

    def send_action(self, action):
        self.count += 1
        if self.count == self.after:
            self.stuck = self.pos[1]
        super().send_action(action)
        if self.stuck is not None:
            self.pos[1] = self.stuck
        return dict(action)


def descend_library():
    lib = library()
    lib["chunks"]["descend_pick"] = [[0.0, -60.0 + k * 0.5, 50.0, 45.0, 10.0, 46.6] for k in range(20)]
    lib["chunks"]["home"] = [HOME]
    return lib


def test_a_soft_contact_holds_with_torque_on_then_retreats_along_its_path_and_parks():
    robot = Pressing(after=8)
    status, clock, queue = [], [0.0], ["run descend_pick", "retreat", "park", "run descend_pick", "stop"]
    r = m.Runner(robot, descend_library(), fps=30, status=status.append, clock=lambda: clock[0],
                 sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))

    def lines():
        if queue and not r.chunk:
            if queue[0] == "retreat":
                robot.stuck = None  # backing up the same path leaves the obstacle: the joint follows again
            return [queue.pop(0)]
        return []

    r.run(lines)
    contact = by_command(status, "run descend_pick")[0]
    assert contact["ok"] is False and contact["contact"] is True and "contact" in contact["fault"]
    assert abs(contact["target"][1] - contact["state"][1]) < 0.01  # held where it stopped, not pushed on
    assert by_command(status, "run retreat")[0]["ok"] is True
    assert by_command(status, "run park")[0]["ok"] is True and by_command(status, "run park")[0]["fault"] is None
    assert by_command(status, "run descend_pick")[1]["ok"] is True  # after park the next attempt may start


def test_normal_following_lag_is_not_a_contact():
    robot = Pressing(after=10**9)  # never stuck: the arm follows
    status = run_with(robot, descend_library(), ["run descend_pick", "stop"])
    assert by_command(status, "run descend_pick")[0]["ok"] is True


def test_contact_limits_never_rise_for_an_unloaded_joint_and_stay_under_the_guard_for_a_loaded_one():
    assert m.contact_limits([0.0, 0.3, 0.8, 0.4, 0.1]) == [1.5] * 5  # unloaded: exactly the old limit (incident 23:59)
    loaded = m.contact_limits([0.4, 0.2, 2.0, 0.3, 0.1])  # a held box: the elbow starts 2.0 behind
    assert loaded[2] == pytest.approx(2.2) and loaded[:2] + loaded[3:] == [1.5] * 4
    assert max(m.contact_limits([2.6] * 5)) <= 2.2 < 2.8  # never toward the guard's ~2.8 units
