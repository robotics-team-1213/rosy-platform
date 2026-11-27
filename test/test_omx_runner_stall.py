"""A stalled lift holds before the motor's overload shutdown: the 2026-11-27 arm_a 15:13 PWM series (session-arm_a-151338.log 172-213)."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "middleware/devices/omx/adapter"))
import runner_strain as rs  # noqa: E402
from omx_adapter.chunk_library import NAMES  # noqa: E402


def _runner(pwm_lift):
    motion = SimpleNamespace(effort_pwm={"shoulder_lift": pwm_lift}, pwm_limits={"shoulder_lift": 600})
    return SimpleNamespace(trend=[], robot=SimpleNamespace(motion=motion), plan_check=None)


def test_the_1513_lift_stall_holds_well_before_the_pwm_cap():
    runner, fired = _runner(-107), None
    present_lift, target_lift = 15.07, 15.07
    for tick in range(90):  # 3 s at 30 Hz: the target rises at RISE_SPEED 2 units/s, the joint creeps 1 unit in all
        pwm = -107 - (600 - 107) * min(1.0, tick / 60)  # -107 -> -600 over 2 s, as logged
        runner.robot.motion.effort_pwm["shoulder_lift"] = pwm
        target_lift -= 2.0 / 30
        present_lift = 15.07 - 0.98 * tick / 89
        present = [0.0, present_lift, 7.0, 35.0, 29.0, 56.0]
        sent = dict(zip(NAMES, [0.0, target_lift, 7.0, 35.0, 29.0, 56.0]))
        if (hit := rs.strained(runner, sent, present)) is not None:
            fired = (tick, hit[0], pwm)
            break
    assert fired is not None and fired[1] == "shoulder_lift"
    assert abs(fired[2]) < 0.9 * 600 and fired[0] < 50  # held below 90 % of the cap, before the cap at 2 s where ID 12 latched


def test_a_slow_park_that_keeps_moving_is_not_a_stall():
    runner = _runner(-350)
    present_lift = target_lift = 15.0
    for _ in range(60):  # park-slow: target and joint both move 0.3 units/s, a heavy lift at 58 % of the cap
        target_lift -= 0.3 / 30
        present_lift -= 0.3 / 30
        sent = dict(zip(NAMES, [0.0, target_lift - 0.9, 7.0, 35.0, 29.0, 56.0]))
        assert rs.strained(runner, sent, [0.0, present_lift, 7.0, 35.0, 29.0, 56.0]) is None
