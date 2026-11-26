"""The stop receipt retains signed, JSON-serializable feedback from the triggering tick."""
import json

import pytest

from test_omx_chunk_runner import Straining, by_command, goto_library, m, run_with


def test_a_blocked_wrist_roll_holds_at_low_pwm_before_the_guard_drops_the_arm():
    # arm_a 2026-11-01 23:19: the roll stopped dead at PWM 82 of 300 while its command ran on, 1.8 -> 4.6 deg in 1 s
    import numpy as np

    robot = Straining(lambda n: min(2.8, max(0.0, 0.05 * (n - 30))), pwm=np.int64(82), joint=4)
    robot.motion.pwm_limits["wrist_roll"] = np.int64(300)
    status = run_with(robot, goto_library(), ["goto approach_pinky", "park", "stop"])
    held = by_command(status, "run goto approach_pinky")[0]
    assert held["ok"] is False and held["contact"] is True and "wrist_roll" in held["fault"]
    assert "shoulder_pan" in held["fault"]  # the other joints' lags travel with it
    sample = json.loads(json.dumps(held))["strain_sample"]
    assert sample["pwm_limit"] == 300
    assert sample["joint"] == "wrist_roll" and sample["pwm"] == -82
    assert abs(sample["sent"] - sample["present"]) == pytest.approx(sample["lag_units"])
    lag = float(held["fault"].split("lag rose to ")[1].split()[0])
    assert m.ROLL_BLOCK_LAG <= lag < 2.7  # held well short of the guard's 5 degrees (~2.8 units)
