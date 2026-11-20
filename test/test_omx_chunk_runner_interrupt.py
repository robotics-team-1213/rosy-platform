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
    folding, done = interrupts(status)[0], interrupts(status)[-1]
    assert folding["folding"] and not held
    assert max(abs(a - b) for a, b in zip(folding["state"][:5], HOME[:5])) > 10  # it really was out
    park = [row for row in status if row["command"] == "run park"]
    assert park and park[-1]["settled"]
    assert done["ok"] and done["folded"] and robot.pos[:5] == pytest.approx(HOME[:5], abs=ci.SETTLE_TOL)
    assert not r.human_hold_latched  # run returned: chunk_runner.main turns torque OFF only now


def test_an_interrupt_while_folded_ends_at_once():
    robot = Robot()
    r, status, _, _ = drive(robot, signal_after=2, commands=())
    assert [row["reason"] for row in interrupts(status)] == ["already folded, torque goes OFF"]
    assert not [row for row in status if row["command"] == "run park"] and len(robot.sent) <= 2


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

    def __init__(self, fail_after, off_works=True):
        super().__init__()
        self.limit, self.off_works, self.torque = fail_after, off_works, dict.fromkeys(m.NAMES, 1)
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
            self.motion.failed = True
            if self.off_works:
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
