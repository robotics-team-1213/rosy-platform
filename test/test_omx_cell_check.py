"""The one-arm cell check reports each 2026-10-24 blocker with its fix and never reads a missing board."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).parents[1]


def module():
    directory = ROOT / "deploy/robot/omx"
    sys.path.insert(0, str(directory))
    try:
        spec = importlib.util.spec_from_file_location("cell_check", directory / "cell_check.py")
        result = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(result)
        return result
    finally:
        sys.path.remove(str(directory))


m = module()


def rows(pwm=20, current=50):
    return [dict(id=i, torque_enabled=0, hardware_error=0, voltage_raw=116 if i < 14 else 60,
                 min_voltage_raw=60 if i < 14 else 35, max_voltage_raw=140 if i < 14 else 70,
                 pwm_limit_raw=pwm, current_limit_raw=None if i < 14 else current) for i in range(11, 17)]


@pytest.fixture
def cell(tmp_path):
    follower, leader = tmp_path / "follower", tmp_path / "leader"
    follower.touch()
    leader.touch()
    readiness = tmp_path / "readiness.json"
    readiness.write_text(json.dumps({"state": "READY", "photometric_ready": True}))
    return str(follower), str(leader), readiness


def failed(report):
    return {c["name"]: c for c in report["checks"] if not c["ok"]}


def test_a_resting_cell_with_ready_cameras_passes(cell):
    report = m.check(*cell, read=lambda device: rows())
    assert report["ok"] and not failed(report)
    assert report["motion_admitted"] is False


def test_caps_left_raised_and_a_stopped_camera_each_name_their_fix(cell):
    follower, leader, readiness = cell
    readiness.write_text(json.dumps({"state": "STOPPED", "photometric_ready": False}))
    bad = failed(m.check(follower, leader, readiness, read=lambda device: rows(pwm=300, current=500)))
    assert {f"follower {i} caps" for i in range(11, 17)} | {"camera readiness"} == set(bad)
    assert "--baseline" in bad["follower 14 caps"]["fix"] and follower in bad["follower 14 caps"]["fix"]
    assert bad["follower 14 caps"]["detail"] == {"pwm_limit_raw": 300, "current_limit_raw": 500}
    assert bad["follower 11 caps"]["detail"] == {"pwm_limit_raw": 300}  # XL430 has no Current Limit
    assert "restart rosy-omx-camera-readiness" in bad["camera readiness"]["fix"]


def test_torque_on_hardware_error_and_low_voltage_fail_the_motor(cell):
    state = rows()
    state[0]["torque_enabled"] = 1
    state[1]["hardware_error"] = 1
    state[3]["voltage_raw"] = 32
    bad = failed(m.check(*cell, read=lambda device: state))
    assert set(bad) == {"follower 11 state", "follower 12 state", "follower 14 state"}
    assert "voltage 3.2 V" in bad["follower 14 state"]["detail"]


def test_a_missing_follower_board_is_reported_without_opening_it(cell, tmp_path):
    _, leader, readiness = cell
    missing = str(tmp_path / "unplugged")
    bad = failed(m.check(missing, leader, readiness, read=lambda device: pytest.fail("read a missing board")))
    assert set(bad) == {"follower board"} and "fix" in bad["follower board"]


def test_a_busy_or_incomplete_bus_is_a_failure_not_a_crash(cell):
    def busy(device):
        raise RuntimeError("Serial device is busy or its ownership could not be checked")
    bad = failed(m.check(*cell, read=busy))
    assert "busy" in bad["follower registers"]["detail"]


def test_unreadable_readiness_state_fails_closed(cell, tmp_path):
    follower, leader, _ = cell
    bad = failed(m.check(follower, leader, tmp_path / "absent.json", read=lambda device: rows()))
    assert set(bad) == {"camera readiness"}


def test_resting_caps_match_the_tools_that_refuse_raised_caps():
    limits = importlib.util.spec_from_file_location("cl", ROOT / "deploy/robot/omx/commissioning_limits.py")
    sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
    try:
        cl = importlib.util.module_from_spec(limits)
        limits.loader.exec_module(cl)
    finally:
        sys.path.remove(str(ROOT / "deploy/robot/omx"))
    assert {k: cl.BASELINE[k] for k in m.RESTING} == m.RESTING
    source = (ROOT / "deploy/robot/omx/joint_tune.py").read_text()
    assert 'BASELINE = {"pwm_limit": 20, "current_limit": 50}' in source
