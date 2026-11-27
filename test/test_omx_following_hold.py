"""A chunk-runner following error holds the arm with torque ON (once); other sessions and a second error still cut torque."""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
from test_omx_policy_timing import _make_guard_bus  # noqa: E402

POSE = [-20.0, 10.0, 7.0, 35.0, 29.0, 56.0]  # real5 arm_a near the fault


def _tracking_motion():
    from guarded_device import normalized
    from guarded_native import NativeJointMotion
    from omx_adapter.chunk_library import NAMES

    now, bus = [10.0], _make_guard_bus(POSE)
    motion = NativeJointMotion(bus, None, teacher=True, clock=lambda: now[0])
    action = dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES]))
    motion.send(action)
    motion.tracking, motion.aligned_since = True, 0.0
    return motion, bus, now, action


def test_runner_following_error_freezes_goal_at_present_and_keeps_torque_on():
    from guarded_device import BODY, normalized
    from guarded_native import GoalRejected
    from omx_adapter.chunk_library import NAMES

    motion, bus, now, action = _tracking_motion()
    jaw_goal = bus.goals["gripper"]
    bus.raw["gripper"] += 40  # jaws stopped on a box
    bus.raw["shoulder_lift"] += 70  # 6.2 degrees past the command (real5: command 2202, current 2272)
    now[0] += 1 / 30
    motion.hold_on_following = True  # as chunk_runner.Guarded sets it
    with pytest.raises(GoalRejected, match="following-error hold") as held:
        motion.send(action)
    assert held.value.can_send_hold and not motion.failed
    assert all(v == 1 for v in bus.torque.values()) and not any(e[0] == "off" for e in bus.events)
    assert all(bus.goals[n] == bus.raw[n] for n in BODY)  # the body servos no longer push
    assert bus.goals["gripper"] == jaw_goal  # the jaws keep their goal: a squeezed box is not let go
    here = dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES]))
    for _ in range(3):  # the runner's hold at the measured pose is accepted
        now[0] += 1 / 30
        motion.send(here, hold_on_read_error=True, allow_stale_hold=True)
    assert not motion.failed and all(v == 1 for v in bus.torque.values())

    bus.raw["shoulder_lift"] += 70  # still coasting 0.13 s after the hold: frozen again where it stands
    now[0] += 1 / 30
    with pytest.raises(GoalRejected, match="following-error hold"):
        motion.send(here)
    assert not motion.failed and all(v == 1 for v in bus.torque.values()) and bus.goals["shoulder_lift"] == bus.raw["shoulder_lift"]
    here = dict(zip(NAMES, [normalized(bus, bus.raw)[n] for n in NAMES]))
    now[0] += 1.0
    motion.send(here, hold_on_read_error=True, allow_stale_hold=True)
    bus.raw["elbow_flex"] += 70  # a following error after the re-hold window: torque off as before
    now[0] += 1 / 30
    with pytest.raises(ValueError, match="following error") as second:
        motion.send(here)
    assert not isinstance(second.value, GoalRejected)
    assert motion.failed and not any(bus.torque.values())


def test_other_sessions_still_cut_torque_on_a_following_error():
    from guarded_native import GoalRejected

    motion, bus, now, action = _tracking_motion()
    bus.raw["shoulder_lift"] += 70
    now[0] += 1 / 30
    with pytest.raises(ValueError, match="following error") as error:
        motion.send(action)  # hold_on_following unset: a teleop or recording session
    assert not isinstance(error.value, GoalRejected)
    assert motion.failed and not any(bus.torque.values())


def test_runner_playback_turns_the_hold_into_a_human_hold_on_an_unprotected_send():
    from chunk_policy_playback import send_with_jaw_gate
    from chunk_runner import Guarded

    motion, bus, now, action = _tracking_motion()
    reports = []

    def hold(present, reason, *, human=False, **_kw):
        runner.target, runner.human_hold_latched, runner.fault = list(present), True, reason

    runner = SimpleNamespace(
        robot=Guarded(SimpleNamespace(bus=bus), motion), human_hold_latched=False, target=list(action.values()),
        chunk="policy", holding=False, _committed_grip=None, last_present=None, hold=hold,
        report=lambda **kw: reports.append(kw), policy_playback=None, jaw_gate=None, _trailing_jaw_gate=None,
        _stop_after_park=None, _recovery_active=False, played=[], jog_path=[],
    )
    bus.raw["shoulder_lift"] += 70
    now[0] += 1 / 30
    sent, committed = send_with_jaw_gate(runner, dict(action), None, None, list(action.values()))
    assert not committed and runner.human_hold_latched
    assert reports and "following-error hold" in reports[-1]["policy_stop"]
    assert not motion.failed and all(v == 1 for v in bus.torque.values())
