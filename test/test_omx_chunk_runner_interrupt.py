"""SIGINT/SIGTERM on chunk_runner: fold home and read it back before torque OFF, else hold torque ON (pipeline-gate-1120)."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys

import pytest

OMX = Path(__file__).parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    spec = importlib.util.spec_from_file_location("chunk_runner", OMX / "chunk_runner.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    import chunk_runner_interrupt as ci
finally:
    sys.path.remove(str(OMX))

HOME = [0.0, -60.0, 50.0, 45.0, 10.0, 46.6]
RELEASE = 12  # SIGUSR2 on Linux; Windows has none


class Robot:
    """Follows each action at once; joints in `blocked` stay put; `fail_after` sends raise like a guard stop."""

    def __init__(self, blocked=(), fail_after=None, block_from=0):
        self.pos, self.sent, self.blocked, self.fail_after = list(HOME), [], blocked, fail_after
        self.block_from = block_from

    def send_action(self, action):
        if self.fail_after is not None and len(self.sent) >= self.fail_after:
            raise ValueError("shoulder_lift: following error >5 motor degrees")
        self.sent.append(action)
        for i, name in enumerate(m.NAMES):
            if i not in self.blocked or len(self.sent) <= self.block_from:
                self.pos[i] = action[name]

    def get_observation(self):
        return dict(zip(m.NAMES, self.pos))


def library():
    reach = [[k * 2.0, -60.0 + k, 50.0 - k, 45.0, 10.0, 46.6] for k in range(25)]  # pan 48, lift out, elbow in
    return {"schema": m.SCHEMA, "names": m.NAMES, "gripper_closed": 46.6,
            "chunks": {"reach": reach, "home": [HOME]}}


def drive(robot, *, signal_after, release_after=None, commands=("run reach",), limit_s=600):
    """Signal SIGINT `signal_after` ticks into the run, the operator release `release_after` s after the HOLD."""
    status, clock, queue, ticks, held_at = [], [0.0], list(commands), [0], []
    r = m.Runner(robot, library(), fps=30, status=status.append, clock=lambda: clock[0],
                 sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))
    r.signals = []

    def lines():
        ticks[0] += 1
        if ticks[0] == signal_after:
            r.signals.append(signal.SIGINT)
        if not held_at and any(row.get("hold") for row in status):
            held_at.append(clock[0])
        if release_after is not None and held_at and clock[0] >= held_at[0] + release_after and RELEASE not in r.signals:
            r.signals.append(RELEASE)
        if clock[0] > limit_s:
            raise TimeoutError("the runner neither ended nor held")
        return [queue.pop(0)] if queue and not r.chunk and not r.signals else []

    r.run(lines)
    return r, status, clock[0], held_at


def interrupts(status):
    return [row for row in status if row["command"] == "interrupt"]


@pytest.fixture(autouse=True)
def release_signal(monkeypatch):
    monkeypatch.setattr(ci, "OPERATOR_RELEASE", RELEASE)


def test_an_interrupt_while_extended_parks_then_ends_only_after_the_fold_reads_home():
    robot = Robot()
    r, status, _, held = drive(robot, signal_after=20)  # mid-chunk, pan near 38, lift and elbow out
    folding, done = next(row for row in interrupts(status) if row.get("folding")), interrupts(status)[-1]
    assert interrupts(status)[0]["verifying"] and not held
    assert max(abs(a - b) for a, b in zip(folding["state"][:5], HOME[:5])) > 10  # it really was out
    park = [row for row in status if row["command"] == "run park"]
    assert park and park[-1]["settled"]
    assert done["ok"] and done["folded"] and robot.pos[:5] == pytest.approx(HOME[:5], abs=ci.SETTLE_TOL)
    assert not r.human_hold_latched  # run returned: chunk_runner.main turns torque OFF only now


def test_an_interrupt_while_folded_ends_after_a_few_still_readings():
    robot = Robot()
    r, status, _, _ = drive(robot, signal_after=2, commands=())
    assert interrupts(status)[-1]["reason"] == "already folded and still, torque goes OFF"
    assert interrupts(status)[-1]["still_ticks"] >= ci.VERIFY_TICKS
    assert not [row for row in status if row["command"] == "run park"] and len(robot.sent) <= ci.VERIFY_TICKS + 3


def test_an_arm_moving_near_home_is_stopped_and_verified_not_switched_off_at_once():
    robot = Robot()
    r, status, _, _ = drive(robot, signal_after=3)  # the reach chunk has just left home: within 3 units, moving
    first = interrupts(status)[0]
    assert first["verifying"] and max(abs(a - b) for a, b in zip(first["state"][:5], HOME[:5])) <= ci.SETTLE_TOL
    frozen = robot.sent[-1]
    assert all(a == frozen for a in robot.sent[-ci.VERIFY_TICKS:])  # the chunk's frames stopped at the signal
    assert interrupts(status)[-1]["still_ticks"] >= ci.VERIFY_TICKS


def test_an_arm_near_home_that_never_stills_is_held_not_switched_off():
    class Shaking(Robot):
        def get_observation(self):
            self.pos[0] = 0.5 if len(self.sent) % 2 else -0.5  # within 3 units of home, never still
            return super().get_observation()

    r, status, _, held = drive(Shaking(), signal_after=2, commands=(), release_after=1.0)
    hold = next(row for row in interrupts(status) if row.get("hold"))
    assert "never still" in hold["error"] and not any(row.get("folded") for row in interrupts(status))


@pytest.mark.parametrize("robot", [Robot(blocked=(0,), block_from=19), Robot(fail_after=30)], ids=["blocked-pan", "tick-error"])
def test_a_fold_that_cannot_finish_holds_torque_on_until_a_person_releases_it(robot):
    r, status, ended, held = drive(robot, signal_after=20, release_after=60.0)
    hold = next(row for row in interrupts(status) if row.get("hold"))
    assert hold["ok"] is False and hold["person_needed"] and "HOLD" in hold["error"]
    assert r.human_hold_latched and r.torque_hold_commanded == (robot.fail_after is None)  # a dead guard sends nothing
    assert ended >= held[0] + 60.0  # the run did not end (no close_device, no torque OFF) until the release
    assert not any(row.get("folded") for row in interrupts(status))
    assert interrupts(status)[-1]["released"] is True


def test_a_further_sigterm_during_a_hold_only_repeats_the_hold():
    robot = Robot(blocked=(0,), block_from=19)
    status, clock = [], [0.0]
    r = m.Runner(robot, library(), fps=30, status=status.append, clock=lambda: clock[0],
                 sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))
    r.signals, queue, n = [], ["run reach"], [0]

    def lines():
        n[0] += 1
        if n[0] == 20:
            r.signals.append(signal.SIGINT)
        if any(row.get("hold") for row in status) and signal.SIGTERM not in r.signals:
            r.signals.append(signal.SIGTERM)
        if sum(1 for row in interrupts(status) if row.get("hold")) >= 2:
            r.signals.append(RELEASE)
        if clock[0] > 600:
            raise TimeoutError
        return [queue.pop(0)] if queue and not r.chunk and not r.signals else []

    r.run(lines)
    holds = [row for row in interrupts(status) if row.get("hold")]
    assert len(holds) >= 2 and holds[1]["error"] == "HOLD: still holding, torque ON"


def test_a_fold_past_its_bound_holds(monkeypatch):
    monkeypatch.setattr(ci, "INTERRUPT_PARK_S", 0.5)
    r, status, _, held = drive(Robot(), signal_after=20, release_after=1.0)
    assert held and "did not finish within" in next(row for row in interrupts(status) if row.get("hold"))["error"]


def test_the_live_state_says_hold():
    rows = []
    robot = Robot(blocked=(0,), block_from=19)
    status, clock = [], [0.0]
    r = m.Runner(robot, library(), fps=30, status=status.append, clock=lambda: clock[0], live=rows.append,
                 sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))
    r.signals, queue, n = [], ["run reach"], [0]

    def lines():
        n[0] += 1
        if n[0] == 20:
            r.signals.append(signal.SIGINT)
        if rows and rows[-1].get("interrupt") == "hold":
            r.signals.append(RELEASE)
        if clock[0] > 600:
            raise TimeoutError
        return [queue.pop(0)] if queue and not r.chunk and not r.signals else []

    r.run(lines)
    assert rows[-1]["interrupt"] == "hold" and rows[-1]["human_hold_latched"]


def test_an_interrupt_before_the_guard_tracks_does_not_move_an_extended_arm():
    robot = Robot()
    robot.pos = [30.0, -40.0, 30.0, 45.0, 10.0, 46.6]
    robot.motion = type("Motion", (), {"tracking": False, "held": None})()
    status, clock = [], [0.0]
    r = m.Runner(robot, library(), fps=30, status=status.append, clock=lambda: clock[0],
                 sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))
    r.signals, n = [signal.SIGTERM], [0]

    def lines():
        n[0] += 1
        if n[0] > 30:
            r.signals.append(RELEASE)
        return []

    r.run(lines)
    hold = next(row for row in interrupts(status) if row.get("hold"))
    assert "not tracking" in hold["error"] and all(a["shoulder_pan.pos"] == 30.0 for a in robot.sent)


class GuardRobot(Robot):
    """Like NativeJointMotion.send: past `fail_after` it marks itself failed, tries torque OFF (`off_works`), raises."""

    def __init__(self, fail_after, off_works=True, partial=False):
        super().__init__()
        self.limit, self.off_works, self.torque = fail_after, off_works, dict.fromkeys(m.NAMES, 1)
        self.partial, self.attempts = partial, 0
        self.motion = type("Motion", (), {"failed": False, "held": None})()
        robot = self

        class Bus:
            def sync_read(self, name, normalize=True, num_retry=0):
                if name != "Torque_Enable":  # the runner's motor-health read
                    return dict.fromkeys(m.MOTORS, 35 if name == "Present_Temperature" else 0)
                assert normalize is False
                return dict(robot.torque)

        self.bus = Bus()

    def send_action(self, action):
        if self.motion.failed or len(self.sent) >= self.limit:
            self.attempts += 1  # each failed send tries torque OFF again, as NativeJointMotion.send does
            self.motion.failed = True
            if self.partial and self.attempts == 1:
                self.torque["elbow_flex.pos"] = 0  # the first attempt reaches one motor only
            elif self.off_works:
                self.torque = dict.fromkeys(m.NAMES, 0)
            raise ValueError("shoulder_lift: following error >5 motor degrees")
        super().send_action(action)


def test_a_guard_stop_during_the_fold_reports_guard_stopped_with_the_torque_readback_and_ends():
    robot = GuardRobot(fail_after=30)
    r, status, _, held = drive(robot, signal_after=20)
    done = interrupts(status)[-1]
    assert done["guard_stopped"] and "GUARD_STOPPED torque off" in done["error"] and set(done["torque"].values()) == {0}
    assert not held and not any(row.get("hold") for row in interrupts(status))


def test_a_guard_stop_whose_torque_still_reads_on_is_a_hold():
    robot = GuardRobot(fail_after=30, off_works=False)
    r, status, _, held = drive(robot, signal_after=20, release_after=5.0)
    hold = next(row for row in interrupts(status) if row.get("hold"))
    assert "guard stopped, torque reads" in hold["error"] and held


def test_a_release_sent_before_the_hold_is_ignored_and_only_a_new_one_releases():
    robot = Robot(blocked=(0,), block_from=19)
    status, clock = [], [0.0]
    r = m.Runner(robot, library(), fps=30, status=status.append, clock=lambda: clock[0],
                 sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))
    r.signals, queue, n, sent = [], ["run reach"], [0], []

    def lines():
        n[0] += 1
        holds = [row for row in interrupts(status) if row.get("hold")]
        if n[0] == 20:
            r.signals.append(signal.SIGINT)
        if n[0] == 25:
            r.signals.append(RELEASE)  # during the fold: too early
        if holds and "sigterm" not in sent:
            sent.append("sigterm")
            r.signals.append(signal.SIGTERM)  # e.g. PDEATHSIG after record_session exits 75
        if len(holds) >= 2 and "release" not in sent:
            sent.append("release")
            r.signals.append(RELEASE)
        if clock[0] > 600:
            raise TimeoutError
        return [queue.pop(0)] if queue and not r.chunk and not r.signals else []

    r.run(lines)
    rows = interrupts(status)
    released = next(i for i, row in enumerate(rows) if row.get("released"))
    assert sum(1 for row in rows[:released] if row.get("hold")) >= 2  # the SIGTERM only repeated the HOLD


def test_an_unreadable_pose_during_the_fold_holds_instead_of_ending():
    class Blind(Robot):
        def get_observation(self):
            if len(self.sent) > 30:
                raise ConnectionError("Failed to sync read 'Present_Position'")
            return super().get_observation()

    r, status, _, held = drive(Blind(), signal_after=20, release_after=3.0)
    assert held and r.human_hold_latched
    assert interrupts(status)[-1]["released"]


def test_a_status_write_that_fails_keeps_the_hold(tmp_path):
    robot = Robot(blocked=(0,), block_from=19)
    rows, clock = [], [0.0]

    def status(row):
        if row.get("hold"):
            raise OSError(28, "No space left on device")
        rows.append(row)

    r = m.Runner(robot, library(), fps=30, status=status, clock=lambda: clock[0],
                 sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))
    r.signals, r.hold_file, queue, n = [], tmp_path / "hold.json", ["run reach"], [0]

    def lines():
        n[0] += 1
        if n[0] == 20:
            r.signals.append(signal.SIGINT)
        if r.human_hold_latched and n[0] > 400 and RELEASE not in r.signals:
            r.signals.append(RELEASE)
        if clock[0] > 600:
            raise TimeoutError
        return [queue.pop(0)] if queue and not r.chunk and not r.signals else []

    r.run(lines)  # never raised: the failed write went to stderr, the hold stayed until the release
    hold = json.loads((tmp_path / "hold.json").read_text())
    assert hold["hold"] and hold["pid"] == os.getpid() and n[0] > 400


@pytest.mark.parametrize("settled, ends", [(True, True), (False, False)])
def test_a_fold_ends_with_torque_off_only_when_settled_and_home(settled, ends):
    robot = Robot()
    r = m.Runner(robot, library(), fps=30, status=lambda row: None, clock=lambda: 0.0, sleep=lambda s: None)
    r.target, r.signals = list(HOME), [signal.SIGINT]
    r._interrupt = {"signal": signal.SIGINT, "phase": "park", "seen": 1, "deadline": 99.0}
    r._stopped, r._park_settled = True, settled  # the park ended within 3 units of home, settled or out of time
    assert ci.interrupt_step(r) is ends and r.human_hold_latched is (not ends)


def test_a_partial_guard_stop_is_reported_and_the_failed_guard_is_never_called_again():
    robot = GuardRobot(fail_after=30, partial=True)
    r, status, _, held = drive(robot, signal_after=20, release_after=5.0)
    partial = next(row for row in interrupts(status) if row.get("hold"))
    assert partial["error"].startswith("PARTIAL_GUARD_STOP") and partial["partial_guard_stop"]
    assert robot.attempts == 1  # no second send: a second torque OFF attempt would have dropped the rest
    assert robot.torque["shoulder_lift.pos"] == 1 and interrupts(status)[-1]["released"]


def test_a_guard_readback_that_later_reads_all_off_is_reported_as_guard_stopped():
    robot = GuardRobot(fail_after=30, off_works=False)
    status, clock = [], [0.0]
    r = m.Runner(robot, library(), fps=30, status=status.append, clock=lambda: clock[0],
                 sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))
    r.signals, queue, n = [], ["run reach"], [0]

    def lines():
        n[0] += 1
        if n[0] == 20:
            r.signals.append(signal.SIGINT)
        if any(row.get("hold") for row in status):
            robot.torque = dict.fromkeys(m.NAMES, 0)  # e.g. the motors' own overload shutdown
        if clock[0] > 600:
            raise TimeoutError
        return [queue.pop(0)] if queue and not r.chunk and not r.signals else []

    r.run(lines)
    assert interrupts(status)[-1]["guard_stopped"] and robot.attempts == 1


def test_a_fifo_human_hold_during_an_interrupt_is_dropped_and_an_unread_pose_never_ends_the_run():
    class Blind(Robot):
        def get_observation(self):
            if len(self.sent) > 22:
                raise ConnectionError("Failed to sync read 'Present_Position'")
            return super().get_observation()

    robot = Blind(blocked=(0,), block_from=19)
    status, clock = [], [0.0]
    r = m.Runner(robot, library(), fps=30, status=status.append, clock=lambda: clock[0],
                 sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))
    r.signals, queue, n = [], ["run reach"], [0]

    def lines():
        n[0] += 1
        if n[0] == 20:
            r.signals.append(signal.SIGINT)
            return ["human-hold"]  # arrives with the interrupt: the interrupt goes first
        if r.human_hold_latched and n[0] % 50 == 0 and n[0] < 400:
            return ["human-hold"]
        if n[0] >= 400:
            r.signals.append(RELEASE)
        if clock[0] > 600:
            raise TimeoutError
        return [queue.pop(0)] if queue and not r.chunk and not r.signals else []

    r.run(lines)
    assert not [row for row in status if row["command"] == "human-hold"]  # never executed from the FIFO
    assert interrupts(status)[-1]["released"] and n[0] >= 400


def test_a_human_hold_whose_pose_read_fails_holds_the_last_known_pose():
    class Blind(Robot):
        def get_observation(self):
            raise ConnectionError("Failed to sync read 'Present_Position'")

    r = m.Runner(Blind(), library(), fps=30, status=lambda row: None, clock=lambda: 0.0, sleep=lambda s: None)
    r.target, r.last_present = list(HOME), list(HOME)
    assert r.command("human-hold") is True and r.human_hold_latched and r.target[:5] == HOME[:5]


def test_a_signal_during_a_tick_whose_pose_read_fails_holds_instead_of_ending():
    status, clock, holder = [], [0.0], {}

    class Racing(Robot):
        def get_observation(self):
            if len(self.sent) == 25 and not holder.get("raised"):
                holder["raised"] = True
                holder["runner"].signals.append(signal.SIGTERM)  # the handler ran inside this tick
                raise OSError(5, "Input/output error")
            return super().get_observation()

    robot = Racing()
    r = m.Runner(robot, library(), fps=30, status=status.append, clock=lambda: clock[0],
                 sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))
    holder["runner"], r.signals, queue = r, [], ["run reach"]

    def lines():
        if r.human_hold_latched and clock[0] > 10 and RELEASE not in r.signals:
            r.signals.append(RELEASE)
        if clock[0] > 600:
            raise TimeoutError
        return [queue.pop(0)] if queue and not r.chunk and not r.signals else []

    r.run(lines)  # no exception reached the caller (chunk_runner.main would have called close_device)
    hold = next(row for row in interrupts(status) if row.get("hold"))
    assert "OSError" in hold["error"] and interrupts(status)[-1]["released"]


def test_a_hold_keeps_counting_ticks_and_publishing_live_json():
    rows, status, clock = [], [], [0.0]
    robot = Robot(blocked=(0,), block_from=19)
    r = m.Runner(robot, library(), fps=30, status=status.append, clock=lambda: clock[0], live=rows.append,
                 sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))
    r.signals, queue, n, mark = [], ["run reach"], [0], []

    def lines():
        n[0] += 1
        if n[0] == 20:
            r.signals.append(signal.SIGINT)
        if r.human_hold_latched and not mark:
            mark.append((clock[0], len(rows)))
        if mark and clock[0] > mark[0][0] + 5:
            r.signals.append(RELEASE)
        if clock[0] > 600:
            raise TimeoutError
        return [queue.pop(0)] if queue and not r.chunk and not r.signals else []

    r.run(lines)
    published = rows[mark[0][1]:]
    assert len(published) >= 5 * 10 * 0.9 and published[-1]["interrupt"] == "hold"  # ~10 Hz for the 5 s held


def test_a_run_loop_that_raises_after_an_interrupt_waits_for_a_person_before_torque_off(tmp_path):
    signals, slept = [signal.SIGINT], []
    r = type("R", (), {"hold_file": tmp_path / "hold.json"})()

    def sleep(s):
        slept.append(s)
        if len(slept) == 3:
            signals.append(signal.SIGTERM)  # not a release
        if len(slept) == 6:
            signals.append(RELEASE)

    ci.last_resort_hold(r, signals, RuntimeError("live.json"), sleep=sleep)
    assert len(slept) == 6 and json.loads((tmp_path / "hold.json").read_text())["last_resort"]


def test_an_interrupt_at_the_idle_stop_deadline_is_not_ended_by_the_idle_stop():
    """Folded by a park (home_since set), then pushed 10 units off home; SIGTERM lands on the tick the idle stop
    would end the session: the interrupt's verify, fold or hold decides, never the idle stop."""
    robot = Robot(blocked=(0,), block_from=10 ** 9)
    status, clock, queue, signalled = [], [0.0], ["park"], []
    r = m.Runner(robot, library(), fps=30, status=status.append, clock=lambda: clock[0],
                 sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))
    r.signals = []

    def lines():
        if r.home_since is not None and not signalled and robot.block_from > len(robot.sent):
            robot.block_from, robot.pos[0] = len(robot.sent), 10.0  # pushed: pan stays 10 units off home
        if r.home_since is not None and not signalled and clock[0] >= r.home_since + m.IDLE_STOP_S - 1 / 30:
            signalled.append(clock[0])
            r.signals.append(signal.SIGTERM)
        if r.human_hold_latched and RELEASE not in r.signals:
            r.signals.append(RELEASE)
        if clock[0] > signalled[0] + 600 if signalled else clock[0] > 6000:
            raise TimeoutError
        return [queue.pop(0)] if queue and not r.chunk and not r.signals else []

    r.run(lines)
    assert signalled
    assert not [row for row in status if row["command"] == "stop" and "no command" in row.get("reason", "")]
    rows = interrupts(status)
    assert rows[0]["verifying"] and not any(row.get("folded") for row in rows)
    assert any(row.get("hold") for row in rows) and rows[-1]["released"]  # pan blocked: the fold cannot finish


def _closed_after_gate(r, signals, tmp_path, release_after=3):
    """What chunk_runner.main does last: final_gate, then close_device. Returns (sleeps before close, hold.json)."""
    slept, closed = [], []

    def sleep(s):
        slept.append(s)
        if len(slept) == release_after:
            signals.append(RELEASE)

    ci.final_gate(r, signals, tmp_path / "hold.json", sleep=sleep)
    closed.append(len(slept))
    hold = tmp_path / "hold.json"
    return closed[0], (json.loads(hold.read_text()) if hold.exists() else None)


def test_final_gate_holds_when_sigterm_lands_while_the_idle_stop_row_is_written(tmp_path):
    status, clock = [], [0.0]
    r = m.Runner(Robot(), library(), fps=30, status=lambda row: (
        r.signals.append(signal.SIGTERM) if row["command"] == "stop" and "no command" in row.get("reason", "") else None,
        status.append(row)), clock=lambda: clock[0], sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))
    r.signals, queue = [], ["park"]
    r.hold_file = tmp_path / "hold.json"
    r.run(lambda: [queue.pop(0)] if queue and not r.chunk else [])  # the idle stop returned during its own status row
    assert r.signals == [signal.SIGTERM] and not getattr(r, "_off_approved", None)
    sleeps, hold = _closed_after_gate(r, r.signals, tmp_path)
    assert sleeps == 3 and hold["last_resort"]  # close_device only after the person's SIGUSR2


def test_final_gate_holds_when_sigterm_lands_while_the_start_alignment_stop_row_is_written(tmp_path):
    robot = Robot()
    robot.pos = [30.0, -40.0, 30.0, 45.0, 10.0, 46.6]  # out on its reach
    robot.motion = type("Motion", (), {"tracking": False, "held": None})()
    clock = [0.0]

    def status(row):
        if row["command"] == "stop":
            r.signals.append(signal.SIGTERM)

    r = m.Runner(robot, library(), fps=30, status=status, clock=lambda: clock[0],
                 sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))
    r.signals, queue, r.hold_file = [], ["stop"], tmp_path / "hold.json"
    r.run(lambda: [queue.pop(0)] if queue else [])
    assert r.signals == [signal.SIGTERM]
    sleeps, hold = _closed_after_gate(r, r.signals, tmp_path)
    assert sleeps == 3 and hold["hold"]


@pytest.mark.parametrize("approved", [None, "park settled and home", "operator release (SIGUSR2)",
                                      "guard stopped, every motor reads torque 0", "folded and still"])
@pytest.mark.parametrize("recorded", [[], [signal.SIGTERM], [signal.SIGINT, signal.SIGTERM], [RELEASE]])
def test_final_gate_lets_close_device_run_only_without_an_interrupt_or_with_an_approved_end(tmp_path, approved,
                                                                                            recorded):
    """Whatever path returned from run(): an interrupt on record and no approved end -> no close_device until SIGUSR2."""
    r = type("R", (), {"hold_file": tmp_path / "hold.json", "_off_approved": approved})()
    signals = list(recorded)
    sleeps, hold = _closed_after_gate(r, signals, tmp_path)
    interrupted = any(s != RELEASE for s in recorded)
    assert (sleeps > 0) == (interrupted and approved is None)
    assert (hold is not None) == (interrupted and approved is None)


def test_gated_close_for_a_runner_that_never_started_closes_after_the_release(tmp_path):
    closed, signals = [], [signal.SIGTERM]

    def sleep(s):
        if not closed and RELEASE not in signals:
            signals.append(RELEASE)

    ci.gated_close(None, signals, tmp_path / "hold.json", lambda: closed.append("off"), sleep=sleep)
    assert closed == ["off"] and json.loads((tmp_path / "hold.json").read_text())["last_resort"]


def test_final_gate_covers_a_runner_that_never_started(tmp_path):
    sleeps, hold = _closed_after_gate(None, [signal.SIGTERM], tmp_path)
    assert sleeps == 3 and hold["hold"]


def test_every_approved_end_of_an_interrupted_run_is_recorded_for_the_gate():
    r, status, _, _ = drive(Robot(), signal_after=20)  # extended -> park -> folded
    assert r._off_approved == "park settled and home"
    r2, _, _, _ = drive(Robot(), signal_after=2, commands=())
    assert r2._off_approved == "folded and still"
    r3, _, _, _ = drive(Robot(blocked=(0,), block_from=19), signal_after=20, release_after=1.0)
    assert r3._off_approved == "operator release (SIGUSR2)"
    r4, _, _, _ = drive(GuardRobot(fail_after=30), signal_after=20)
    assert r4._off_approved == "guard stopped, every motor reads torque 0"


def test_gated_close_closes_once_when_allowed_and_only_after_a_release_when_not(tmp_path):
    closed, slept = [], []
    allowed = type("R", (), {"hold_file": tmp_path / "a.json", "_off_approved": "park settled and home"})()
    ci.gated_close(allowed, [signal.SIGTERM], None, lambda: closed.append("off"))
    assert closed == ["off"]
    refused, signals = type("R", (), {"hold_file": tmp_path / "b.json"})(), [signal.SIGTERM]

    def sleep(s):
        slept.append(s)
        assert not closed[1:]  # no torque OFF while held
        if len(slept) == 2:
            signals.append(RELEASE)

    ci.gated_close(refused, signals, None, lambda: closed.append("off"), sleep=sleep)
    assert closed == ["off", "off"] and len(slept) == 2


GATE_PROBE = r"""
import json, os, signal, sys, threading, time
from pathlib import Path
sys.path[:0] = sys.argv[3:]
import main_thread_signals as mts
mts.route()  # as chunk_runner.py: every later Python thread starts with the interrupts blocked
import chunk_runner_interrupt as ci
mts.unblock_main()
stop = threading.Event()
threading.Thread(target=stop.wait, name="boundary-watch", daemon=True).start()  # as guarded_native_watch
approved, hold = sys.argv[1] == "approved", Path(sys.argv[2])
ci.OPERATOR_RELEASE = signal.SIGUSR2
signals, rounds = [], []
ci.install(signals)
for _ in range(20):
    signals.clear()
    seen, released = [], []
    if not approved:
        signals.append(signal.SIGINT)  # an interrupt already on record: the gate refuses

    def close():  # disable_torque would run here: give a stray delivery every chance to run the handler
        os.kill(os.getpid(), signal.SIGTERM)
        deadline = time.monotonic() + 0.05
        while time.monotonic() < deadline:
            sum(range(200))
        seen.append(list(signals))

    def sleep(s):
        time.sleep(0.01)
        if not released:
            released.append(True)
            os.kill(os.getpid(), signal.SIGUSR2)

    r = type("R", (), {"hold_file": hold, "_off_approved": "park settled and home" if approved else None})()
    ci.gated_close(r, signals, None, close, sleep=sleep)
    for _ in range(100):
        if signal.SIGTERM in signals:
            break
        time.sleep(0.01)
    rounds.append({"during_close": seen, "after": signal.SIGTERM in signals})
print(json.dumps({"unrouted": mts.unrouted_threads(), "rounds": rounds}))
stop.set()
"""


@pytest.mark.skipif(not hasattr(signal, "pthread_sigmask") or not Path("/proc/self/task").is_dir(),
                    reason="Linux only: pthread_sigmask and /proc/self/task")
@pytest.mark.parametrize("approved", [True, False])
def test_a_sigterm_between_the_gate_and_torque_off_waits_until_the_verdict_has_been_carried_out(tmp_path, approved):
    """Codex round 6: SIGTERM sent inside the close, after the verdict. A fresh interpreter routed as chunk_runner.py
    with a worker thread: pytest-xdist's own threads accept signals, so in-process the outcome was luck (CI 11-27)."""
    import subprocess

    adapter = Path(__file__).parents[1] / "middleware/devices/omx/adapter"
    done = subprocess.run([sys.executable, "-c", GATE_PROBE, "approved" if approved else "refused",
                           str(tmp_path / "hold.json"), str(OMX), str(adapter)],
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["unrouted"] == []
    # every round: the handler did not run between the verdict and disable_torque; it ran after, the verdict carried out
    want = [[] if approved else [signal.SIGINT, signal.SIGUSR2]]
    assert out["rounds"] == [{"during_close": want, "after": True}] * 20


@pytest.mark.parametrize("hold_at,sig", [(20, signal.SIGINT), (22, signal.SIGTERM)])
def test_fifo_human_hold_with_concurrent_shutdown_signal_latches_hold_without_folding(hold_at, sig):
    status, clock, queue, ticks = [], [0.0], ["run reach"], [0]
    r = m.Runner(Robot(), library(), fps=30, status=status.append, clock=lambda: clock[0],
                 sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))
    r.signals = []

    def lines():
        ticks[0] += 1
        out = []
        if ticks[0] == 20:
            r.signals.append(sig)
        if ticks[0] == hold_at:
            out.append("human-hold")
        if r.human_hold_latched and clock[0] > 5 and RELEASE not in r.signals:
            r.signals.append(RELEASE)
        if clock[0] > 60:
            raise TimeoutError
        return out or ([queue.pop(0)] if queue and not r.chunk and not r.signals else [])

    r.run(lines)
    assert r.human_hold_latched is True and any(row.get("hold") for row in interrupts(status))
    assert interrupts(status)[-1]["released"] is True
    assert not any(row.get("folding") or row.get("command") == "run park" for row in status)
    assert not [row for row in status if row["command"] == "human-hold"]


def test_fifo_human_hold_during_active_interrupt_fold_sends_zero_further_park_ticks():
    robot, status, clock, queue, ticks, sent = Robot(), [], [0.0], ["run reach"], [0], {}
    r = m.Runner(robot, library(), fps=30, status=status.append, clock=lambda: clock[0],
                 sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))
    r.signals = []

    def lines():
        ticks[0] += 1
        if ticks[0] == 20:
            r.signals.append(signal.SIGINT)
        if "before" not in sent and getattr(r, "_interrupt", None) and r._interrupt["phase"] == "park" and r.chunk == "park" and len(r.queue) > 2:
            sent["before"], sent["pose"] = len(robot.sent), list(robot.pos[:5])
            return ["human-hold"]
        if r.human_hold_latched and "held_at" not in sent:
            sent["held_at"] = clock[0]
        if "held_at" in sent and clock[0] >= sent["held_at"] + 2.0 and RELEASE not in r.signals:
            r.signals.append(RELEASE)
        if clock[0] > 60:
            raise TimeoutError
        return [queue.pop(0)] if queue and not r.chunk and not r.signals else []

    r.run(lines)
    assert r.human_hold_latched is True and r._interrupt["phase"] == "hold" and len(robot.sent) > sent["before"]
    for action in robot.sent[sent["before"]:]:
        assert [action[n] for n in m.NAMES[:5]] == pytest.approx(sent["pose"])
    assert interrupts(status)[-1]["released"] is True
    assert not [row for row in status if row["command"] == "human-hold"]


def test_startup_alignment_concurrent_signal_and_fifo_human_hold_latches_hold_even_when_folded():
    robot, status, clock, ticks = Robot(), [], [0.0], [0]
    robot.motion = type("M", (), {"tracking": False, "failed": False, "held": None})()
    r = m.Runner(robot, library(), fps=30, status=status.append, clock=lambda: clock[0],
                 sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))
    r.signals = []

    def lines():
        ticks[0] += 1
        if ticks[0] == 1:
            r.signals.append(signal.SIGINT)
            return ["human-hold"]
        if r.human_hold_latched and clock[0] > 3.0 and RELEASE not in r.signals:
            r.signals.append(RELEASE)
        if clock[0] > 60:
            raise TimeoutError
        return []

    r.run(lines)
    assert r.human_hold_latched is True and any(row.get("hold") for row in interrupts(status))
    assert not any(row.get("folded") for row in interrupts(status))
    assert interrupts(status)[-1]["released"] is True
    assert not [row for row in status if row["command"] == "human-hold"]


def test_concurrent_premature_sigusr2_and_fifo_human_hold_sends_zero_post_intake_motion_and_requires_fresh_release():
    robot, status, clock, queue, ticks, intake = Robot(), [], [0.0], ["run reach"], [0], {}
    r = m.Runner(robot, library(), fps=30, status=status.append, clock=lambda: clock[0],
                 sleep=lambda s: clock.__setitem__(0, clock[0] + 1 / 30))
    r.signals = []

    def lines():
        ticks[0] += 1
        if ticks[0] == 11:
            intake.update(before=len(robot.sent), pose=list(robot.pos[:5]), t=clock[0])
            r.signals.append(RELEASE)
            return ["human-hold"]
        if r.human_hold_latched and clock[0] >= intake["t"] + 2.0 and not r.signals:
            r.signals.append(RELEASE)
        if clock[0] > 60:
            raise TimeoutError
        return [queue.pop(0)] if queue and not r.chunk else []

    r.run(lines)
    assert r.human_hold_latched is True and clock[0] >= intake["t"] + 2.0 and len(robot.sent) > intake["before"]
    for action in robot.sent[intake["before"]:]:
        assert [action[n] for n in m.NAMES[:5]] == pytest.approx(intake["pose"])
    hold_rows = [row for row in status if row["command"] == "human-hold"]
    assert any(row.get("ok") and row.get("human_hold_latched") and row.get("torque_hold_commanded") for row in hold_rows)
    assert hold_rows[-1].get("released") is True


def test_interrupt_hold_overload_keeps_torque_ack_and_blocks_fifo_live_fallback(tmp_path, monkeypatch):
    import time

    sys.path.insert(0, str(OMX))
    try:
        import cell_pipeline_io as cpio
        from cell_pipeline_io import FifoCell
        from cell_policy_timing import hold_ack_ok
    finally:
        sys.path.remove(str(OMX))

    robot, status = Robot(), []
    robot.motion = type("M", (), {"held": {"wrist_flex": 1.0}, "failed": False, "last_effort_time": False})()
    r = m.Runner(robot, library(), fps=30, status=status.append, clock=lambda: 1.0)
    r.target, r.signals = list(HOME), [signal.SIGINT]
    r.human_hold_latched, r._human_hold_ack_pending, r.torque_hold_commanded = True, True, True
    r._interrupt = {"signal": signal.SIGINT, "phase": "hold", "seen": 1, "may_move": False, "since": 0.0,
                    "still": 0, "last": None, "deadline": 60.0, "release_from": 1}

    assert ci._hold_tick(r) is False  # the hold pose went out with torque ON: the ack stands under the shed (2026-11-26)
    assert r.torque_hold_commanded is True and r._human_hold_ack_pending is False
    assert not any(row.get("command") == "human-hold" and row.get("ok") is False for row in status)
    assert ci._hold_tick(r) is False
    assert status[-1]["command"] == "human-hold" and status[-1]["ok"] is True and status[-1]["person_needed"] is True
    assert status[-1]["overload_shed"] == ["wrist_flex"] and r.torque_hold_commanded is True

    io_dir = tmp_path / "io"
    io_dir.mkdir()
    (io_dir / "chunk-cmd").write_bytes(b"")
    (io_dir / "chunk-status.jsonl").mkdir()  # force unreadable status file -> FifoCell relies on live fallback
    live_path = io_dir / "live.json"
    live_path.write_text(json.dumps({"t": time.time(), "state": list(HOME), "human_hold_latched": r.human_hold_latched,
                                     "torque_hold_commanded": r.torque_hold_commanded, "fault": r.fault}))
    cell = FifoCell(io_dir, {}, 0.08)
    reply = cell.act("human-hold")
    assert reply["ok"] is False and hold_ack_ok(reply) is False and "no status within" in reply["error"]

    for pre_offset in (-0.005, 0.0004, 0.05):
        live_path.write_text(json.dumps({"t": time.time() + pre_offset, "state": list(HOME), "human_hold_latched": True,
                                         "torque_hold_commanded": True}))
        assert hold_ack_ok(cell.act("human-hold")) is False

    live_path.write_text(json.dumps({"t": 10**400, "state": list(HOME), "human_hold_latched": True, "torque_hold_commanded": True}))
    real_open, real_close, sink_fd, live_vals = cpio.os.open, cpio.os.close, [None], [(0.1, "wrong-req"), (None, None), (0.1, None)]
    hold_sink = tmp_path / "hold-sink"
    with monkeypatch.context() as mp:
        def _open_live(path, flags):
            if Path(path) == io_dir / "chunk-cmd":
                sink_fd[0] = real_open(hold_sink, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                return sink_fd[0]
            return real_open(path, flags)

        def _close_with_live(fd):
            real_close(fd)
            if fd == sink_fd[0]:
                offset, forced_req = live_vals.pop(0)
                t_val = 10**400 if offset is None else time.time() + offset
                req = forced_req or hold_sink.read_text().strip().split()[1]
                live_path.write_text(json.dumps({"t": t_val, "state": list(HOME), "human_hold_latched": True,
                                                 "torque_hold_commanded": True, "hold_req": req}))

        mp.setattr(cpio.os, "open", _open_live)
        mp.setattr(cpio.os, "close", _close_with_live)
        assert hold_ack_ok(cell.act("human-hold")) is False
        assert hold_sink.read_text().startswith("human-hold ")
        assert hold_ack_ok(cell.act("human-hold")) is False
        assert hold_ack_ok(cell.act("human-hold")) is True

    r._human_hold_ack_pending = True  # FIFO retry on an already-overloaded hold: acked again, never left pending
    assert ci._hold_tick(r) is False
    assert r.torque_hold_commanded is True and r._human_hold_ack_pending is False

    robot2, status2 = Robot(), []
    robot2.motion = type("M", (), {"failed": True})()
    robot2.bus = type("B", (), {"sync_read": lambda *a, **kw: {n: (0 if i == 0 else 1) for i, n in enumerate(m.NAMES)}})()
    r2 = m.Runner(robot2, library(), fps=30, status=status2.append, clock=lambda: 1.0)
    r2.target, r2.human_hold_latched, r2._human_hold_ack_pending, r2.torque_hold_commanded = list(HOME), True, True, True
    assert ci.emergency_hold(r2, RuntimeError("guard stop")) is False
    assert r2._interrupt["guard_kind"] == "partial"
    assert r2.torque_hold_commanded is False and r2._human_hold_ack_pending is False
    r2._human_hold_ack_pending, r2.torque_hold_commanded = True, True
    assert ci._guard_verdict(r2, robot2.bus.sync_read(), "repeat") is False
    assert r2.torque_hold_commanded is False and r2._human_hold_ack_pending is False
    live_path.write_text(json.dumps({"t": time.time(), "state": list(HOME), "human_hold_latched": r2.human_hold_latched,
                                     "torque_hold_commanded": r2.torque_hold_commanded, "fault": r2.fault}))
    assert hold_ack_ok(cell.act("human-hold")) is False


def test_fifo_human_hold_ignores_pre_dispatch_status_row_and_reads_post_dispatch_overload(tmp_path, monkeypatch):
    sys.path.insert(0, str(OMX))
    try:
        import cell_pipeline_io as cpio
        from cell_policy_timing import hold_ack_ok, send_hold
    finally:
        sys.path.remove(str(OMX))

    io_dir = tmp_path / "io"
    io_dir.mkdir()
    (io_dir / "chunk-cmd").write_bytes(b"")
    status_path = io_dir / "chunk-status.jsonl"
    status_path.write_text("", encoding="utf-8")
    now, mono = [100.05], [0.0]
    real_open, real_close, sink_fd = cpio.os.open, cpio.os.close, [None]
    open_rows, close_rows, live_row = [], [], [None]

    def _open_race(path, flags):
        if Path(path) == io_dir / "chunk-cmd":
            if open_rows:
                with status_path.open("a", encoding="utf-8") as stream:
                    for row in open_rows:
                        stream.write(json.dumps(row) + "\n")
            sink_fd[0] = real_open(tmp_path / "cmd-sink", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            return sink_fd[0]
        return real_open(path, flags)

    def _close_race(fd):
        real_close(fd)
        if fd == sink_fd[0] and (close_rows or live_row[0]):
            req = (tmp_path / "cmd-sink").read_text(encoding="utf-8").strip().split()[1]
            if live_row[0]:
                (io_dir / "live.json").write_text(json.dumps(dict(live_row[0], hold_req=req)), encoding="utf-8")
            with status_path.open("ab") as stream:
                for row in close_rows:
                    if isinstance(row, bytes):
                        stream.write(row)
                    elif isinstance(row, str):
                        stream.write((row + "\n").encode("utf-8"))
                    else:
                        out = dict(row, hold_req=req) if row.get("hold_req") == "{req}" else row
                        stream.write((json.dumps(out) + "\n").encode("utf-8"))

    with monkeypatch.context() as mp:
        mp.setattr(cpio.time, "time", lambda: now[0])
        mp.setattr(cpio.time, "monotonic", lambda: mono[0])
        mp.setattr(cpio.time, "sleep", lambda dt: mono.__setitem__(0, mono[0] + dt))
        mp.setattr(cpio.os, "open", _open_race)
        mp.setattr(cpio.os, "close", _close_race)
        cell = cpio.FifoCell(io_dir, {}, 0.08)

        open_rows[:] = [
            {"command": "human-hold", "ok": True, "human_hold_latched": True, "torque_hold_commanded": True, "t": 100.02},
            {"command": "human-hold", "ok": True, "human_hold_latched": True, "torque_hold_commanded": True, "t": 100.05},
            {"command": "human-hold", "ok": True, "human_hold_latched": True, "torque_hold_commanded": True},
            {"command": "human-hold", "ok": True, "human_hold_latched": True, "torque_hold_commanded": True, "t": 10**400},
        ]
        close_rows[:] = [
            {"command": "human-hold", "ok": True, "human_hold_latched": True, "torque_hold_commanded": True, "hold_req": "{req}", "t": 10**400},
            {"command": "human-hold", "ok": False, "human_hold_latched": True, "torque_hold_commanded": False,
             "person_needed": True, "error": "guard overload during human hold; person needed", "hold_req": "{req}", "t": 100.06},
        ]
        reply = cell.act("human-hold")
        assert reply["ok"] is False and hold_ack_ok(reply) is False and "guard overload" in reply["error"]

        mono[0] = 0.0
        open_rows[:] = [{"command": "human-hold", "ok": True, "human_hold_latched": True, "torque_hold_commanded": True, "t": 100.02}]
        close_rows[:] = []
        assert cell.act("human-hold")["ok"] is False
        with pytest.raises(OSError):
            send_hold(cell, attempts=2, delay_s=0.0)

        mono[0] = 0.0
        open_rows[:] = []
        close_rows[:] = [{"command": "human-hold", "ok": True, "human_hold_latched": True, "torque_hold_commanded": True, "hold_req": "{req}", "t": 100.06}]
        assert hold_ack_ok(send_hold(cell, attempts=1, delay_s=0.0)) is True

        # Case 4 (r28 P2 retry ordering): post-dispatch previous-request ok=True + current-request overload -> skips stale req, returns current overload; previous-only times out.
        mono[0] = 0.0
        open_rows[:] = []
        close_rows[:] = [
            {"command": "human-hold", "ok": True, "human_hold_latched": True, "torque_hold_commanded": True, "hold_req": "prev-req-1", "t": 100.06},
            {"command": "human-hold", "ok": False, "human_hold_latched": True, "torque_hold_commanded": False,
             "person_needed": True, "error": "guard overload during human hold; person needed", "hold_req": "{req}", "t": 100.07},
        ]
        r_retry = cell.act("human-hold")
        assert r_retry["ok"] is False and r_retry["hold_req"] != "prev-req-1" and "guard overload" in r_retry["error"]

        mono[0] = 0.0
        close_rows[:] = [{"command": "human-hold", "ok": True, "human_hold_latched": True, "torque_hold_commanded": True, "hold_req": "prev-req-1", "t": 100.06}]
        with pytest.raises(OSError):
            send_hold(cell, attempts=2, delay_s=0.0)

        # Case 5: same-request superseded ok=True followed in the same poll buffer by ok=False overload returns overload.
        mono[0] = 0.0
        close_rows[:] = [
            {"command": "human-hold", "ok": True, "human_hold_latched": True, "torque_hold_commanded": True, "hold_req": "{req}", "t": 100.06},
            {"command": "human-hold", "ok": False, "human_hold_latched": True, "torque_hold_commanded": False,
             "person_needed": True, "error": "guard overload during human hold; person needed", "hold_req": "{req}", "t": 100.07},
        ]
        r_sup = cell.act("human-hold")
        assert r_sup["ok"] is False and hold_ack_ok(r_sup) is False and "guard overload" in r_sup["error"]

        # Case 5b (r32/r33): preceding/trailing invalid UTF-8 bytes or corrupt JSON after matching overload never discard matched_hold into live.json fallback.
        mono[0] = 0.0
        live_row[0] = {"t": 100.06, "state": list(HOME), "human_hold_latched": True, "torque_hold_commanded": True}
        close_rows[:] = [
            b"\xff\n",
            {"command": "human-hold", "ok": False, "human_hold_latched": True, "torque_hold_commanded": False,
             "person_needed": True, "error": "guard overload during human hold; person needed", "hold_req": "{req}", "t": 100.06},
            "{corrupt",
            b"\xff\n",
            b"\x80",
        ]
        r_corrupt = cell.act("human-hold")
        assert r_corrupt["ok"] is False and hold_ack_ok(r_corrupt) is False and "guard overload" in r_corrupt["error"]
        live_row[0] = None

    # Case 6: real Runner echoes hold_req for ok and retry overload reports.
    robot3, status3 = Robot(), []
    r3 = m.Runner(robot3, library(), fps=30, status=status3.append, clock=lambda: 1.0)
    r3.target = list(HOME)
    assert r3.command("human-hold req1") is True
    r3.tick()
    ack1 = [row for row in status3 if row.get("command") == "human-hold"][-1]
    assert ack1["ok"] is True and ack1["hold_req"] == "req1" and r3.torque_hold_commanded is True
    robot3.motion = type("M", (), {"held": {"wrist_flex": 1.0}, "failed": False, "last_effort_time": False})()
    assert r3.command("human-hold req2") is True
    r3.tick()
    ack2 = [row for row in status3 if row.get("command") == "human-hold"][-1]
    # 2026-11-26: the hold pose streams with torque ON under the shed, so the ack stands and the shed is its own field
    assert ack2["ok"] is True and ack2["hold_req"] == "req2" and ack2["person_needed"] is True and r3.torque_hold_commanded is True
    assert ack2["overload_shed"] == ["wrist_flex"]


def test_pr2_guard_stopped_clears_port_and_retries_per_motor():
    from types import SimpleNamespace

    cleared = []

    class _FlakyBus:
        def __init__(self, mode: str):
            self.mode = mode
            self.sync_calls = 0
            self.port_handler = SimpleNamespace(clearPort=lambda: cleared.append(True))

        def sync_read(self, reg, normalize=False, num_retry=0):
            self.sync_calls += 1
            if self.mode == "retry_ok":
                if self.sync_calls == 1:
                    raise ConnectionError("stale rx")
                return {mot: 0 for mot in ci.MOTORS}
            raise ConnectionError("sync down")

        def read(self, reg, motor, normalize=False, num_retry=0):
            if self.mode == "per_motor_partial":
                return 0 if motor != ci.MOTORS[0] else 1
            if self.mode == "per_motor_all_off":
                return 0
            raise ConnectionError("bus down")

    class _FakeRunner:
        def __init__(self, mode: str):
            self.robot = SimpleNamespace(motion=SimpleNamespace(failed=True), bus=_FlakyBus(mode))
            self._interrupt = {"signal": None, "guard_kind": None, "phase": "park"}
            self.last_present = list(HOME)
            self.target = list(HOME)
            self.human_hold_latched = False
            self.signals = []
            self.rows = []

        def report(self, **kw):
            self.rows.append(kw)

        def hold(self, present, why, human=True):
            self.human_hold_latched = True

    r_retry = _FakeRunner("retry_ok")
    t1 = ci._guard_stopped(r_retry)
    assert len(cleared) == 1 and ci._torque_complete(t1)
    assert ci._guard_verdict(r_retry, t1, "err") is True

    r_part = _FakeRunner("per_motor_partial")
    t2 = ci._guard_stopped(r_part)
    assert ci._torque_complete(t2) and t2[ci.MOTORS[0]] == 1
    assert ci._guard_verdict(r_part, t2, "err") is False and r_part.human_hold_latched is True

    r_off = _FakeRunner("per_motor_all_off")
    t3 = ci._guard_stopped(r_off)
    assert ci._guard_verdict(r_off, t3, "err") is True

    r_err = _FakeRunner("all_fail")
    t4 = ci._guard_stopped(r_err)
    assert "error" in t4 and ci._guard_verdict(r_err, t4, "err") is False and r_err.human_hold_latched is True


def test_guard_stopped_drains_rx_and_retries_when_torque_read_has_write_ack_bytes():
    robot = GuardRobot(fail_after=30)
    cleared, calls = [], []
    robot.bus.port_handler = type("P", (), {"clearPort": lambda self: cleared.append("clear")})()
    orig_sync = robot.bus.sync_read

    def flaky_sync(name, normalize=True, num_retry=0):
        if name == "Torque_Enable":
            calls.append(len(calls) + 1)
            if len(calls) == 1:
                return dict(zip(m.MOTORS, (145, 250, 129, 9, 114, 89)))
            return dict.fromkeys(m.MOTORS, 0)
        return orig_sync(name, normalize=normalize, num_retry=num_retry)

    robot.bus.sync_read = flaky_sync
    robot.motion.failed = True
    r = m.Runner(robot, library(), fps=30, status=lambda _row: None, clock=lambda: 0.0, sleep=lambda _s: None)
    res = ci._guard_stopped(r)
    assert cleared == ["clear"]
    assert calls == [1, 2]
    assert set(res.values()) == {0}


def test_idle_parks_twice_latches_human_hold_without_deadlock():
    lib = library()
    lib["chunks"]["home"] = [HOME]
    robot, status, clock = Robot(), [], [0.0]
    r = m.Runner(robot, lib, fps=30, status=status.append, clock=lambda: clock[0],
                 params={"runner.idle_park_s": 1.0, "runner.idle_retry_s": 1.0})
    r.target = [18.0, -30.0, 20.0, 40.0, 10.0, 46.6]
    r.idle_parks = 2
    assert r.idle() is False
    assert r.idle_parks == 3 and r.human_hold_latched is True and r._human_hold_ack_pending is True
    assert status[-1]["person_needed"] is True and "idle fold held twice" in status[-1]["error"]
