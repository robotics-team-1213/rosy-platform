"""Chunks play in order with torque held between them; the judge gets settled state and grasp outcome."""
import importlib.util
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
    risen = next(i for i, f in enumerate(path) if f[1] == pytest.approx(-27.0) and f[2] == pytest.approx(18.0))
    turned = next(i for i, f in enumerate(path) if f[0] == pytest.approx(HOME[0]) and f[4] == pytest.approx(HOME[4]))
    assert closed < risen < turned  # never turn while low with open jaws (the head scraped the table)
    assert all(f[0] == start[0] for f in path[:risen + 1])  # no pan until risen
    assert path[-1][:5] == pytest.approx(HOME[:5])


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


def test_the_library_contract_is_enforced(tmp_path):
    import json
    bad = library()
    bad["chunks"]["grasp_pinky"][0][1] = 130.0
    path = tmp_path / "lib.json"
    path.write_text(json.dumps(bad))
    with pytest.raises(SystemExit, match="within"):
        m.load_library(path)
