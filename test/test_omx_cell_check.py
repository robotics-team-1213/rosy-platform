"""The one-arm cell check reports each 2026-10-24 blocker with its fix and never reads a missing board."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).parents[1]
NOW = 10**18


def module(name="cell_check"):
    directory = ROOT / "deploy/robot/omx"
    sys.path.insert(0, str(directory))
    try:
        spec = importlib.util.spec_from_file_location(name, directory / f"{name}.py")
        result = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(result)
        return result
    finally:
        sys.path.remove(str(directory))


m = module()


def test_library_preflight_reports_exact_limit_and_recovery_command(tmp_path):
    from cell_preflight import check_library
    from chunk_runner import NAMES

    home = [0.8, -62.2, 53.1, 51.6, 45.2, 50.0]
    bad = [*home[:4], -33.32, home[5]]
    library = tmp_path / "test library.json"
    library.write_text(json.dumps({"names": list(NAMES), "chunks": {"home": [home], "unused": [home, bad]}}))
    config_path = tmp_path / "arm a.json"
    config = {"arm_id": "arm_a", "joint_min": {"wrist_roll.pos": -31}, "played_chunks": ["home"]}
    state = {"ok": True, "state": [*home[:4], -49.3, home[5]]}
    failures = check_library(config, config_path, library, state)
    assert len(failures) == 2
    name, ok, why = failures[0]
    assert not ok and all(part in why for part in ("arm_a", "unused", "frame 1", "wrist_roll.pos", "-33.32", "-31"))
    name, ok, why = failures[1]
    assert name == "recovery_required" and not ok
    assert "--stage home" in why and "--person-at-switch" in why and "test library.json'" in why
    assert "automatically lifts" in why


def test_library_preflight_accepts_any_chunk_start_at_direct_start_limit(tmp_path):
    from cell_preflight import check_library
    from chunk_runner import JOG_MAX, NAMES

    home = [0.0, -62.2, 53.1, 51.6, 45.2, 50.0]
    other = [30.0, *home[1:]]
    library = tmp_path / "library.json"
    library.write_text(json.dumps({"names": list(NAMES), "chunks": {"home": [home], "pick": [other]}}))
    config = {"joint_min": {"wrist_roll.pos": -31}}
    measured = [other[0] + 2 * JOG_MAX, *other[1:5], -99]
    assert all(ok for _, ok, _ in check_library(config, tmp_path / "config", library, {"ok": True, "state": measured}))


def rows(pwm=20, current=50):
    return [dict(id=i, torque_enabled=0, hardware_error=0, voltage_raw=116 if i < 14 else 60,
                 min_voltage_raw=60 if i < 14 else 35, max_voltage_raw=140 if i < 14 else 70,
                 pwm_limit_raw=pwm, current_limit_raw=None if i < 14 else current) for i in range(11, 17)]


def readiness_state(path, state="READY", photometric=True, expires=NOW + 750_000_000):
    path.write_text(json.dumps({"state": state, "photometric_ready": photometric, "expires_ns": expires}))


@pytest.fixture
def cell(tmp_path):
    follower, leader = tmp_path / "follower", tmp_path / "leader"
    follower.touch()
    leader.touch()
    readiness = tmp_path / "readiness.json"
    readiness_state(readiness)
    return str(follower), str(leader), readiness


def check(follower, leader, readiness, read=lambda device: rows()):
    return m.check(follower, leader, readiness, read=read, now_ns=lambda: NOW)


def failed(report):
    return {c["name"]: c for c in report["checks"] if not c["ok"]}


def test_a_resting_cell_with_ready_cameras_passes(cell):
    report = check(*cell)
    assert report["ok"] and not failed(report)
    assert report["motion_admitted"] is False


def test_caps_left_raised_and_a_stopped_camera_each_name_their_fix(cell):
    follower, leader, readiness = cell
    readiness_state(readiness, "STOPPED", False, 0)
    bad = failed(check(follower, leader, readiness, read=lambda device: rows(pwm=300, current=500)))
    assert {f"follower {i} caps" for i in range(11, 17)} | {"camera readiness"} == set(bad)
    for i in range(11, 17):
        assert f"--device {follower} --baseline" in bad[f"follower {i} caps"]["fix"]
    assert bad["follower 14 caps"]["detail"] == {"pwm_limit_raw": 300, "current_limit_raw": 500}
    assert bad["follower 11 caps"]["detail"] == {"pwm_limit_raw": 300}  # XL430 has no Current Limit
    # after three failed starts the unit is start-limit-hit; a bare restart would be refused
    assert "reset-failed rosy-omx-camera-readiness" in bad["camera readiness"]["fix"]


@pytest.mark.parametrize("state,photometric,expires,detail", [
    ("READY", True, NOW - 1, "READY but expired"),  # a killed run left READY; the next boot refused before writing
    ("READY", True, None, "READY but expired"),
    ("READY", False, NOW + 1, "READY"),
])
def test_only_a_fresh_photometric_ready_counts(cell, state, photometric, expires, detail):
    follower, leader, readiness = cell
    readiness_state(readiness, state, photometric, expires)
    bad = failed(check(follower, leader, readiness))
    assert set(bad) == {"camera readiness"} and bad["camera readiness"]["detail"] == detail


def test_torque_on_hardware_error_and_low_voltage_fail_the_motor(cell):
    state = rows()
    state[0]["torque_enabled"] = 1
    state[1]["hardware_error"] = 1
    state[3]["voltage_raw"] = 32
    bad = failed(check(*cell, read=lambda device: state))
    assert set(bad) == {"follower 11 state", "follower 12 state", "follower 14 state"}
    assert "voltage 3.2 V" in bad["follower 14 state"]["detail"]


@pytest.mark.parametrize("role", ["follower", "leader"])
def test_a_missing_board_is_reported_without_opening_it(cell, tmp_path, role):
    follower, leader, readiness = cell
    missing = str(tmp_path / "unplugged")
    boards = (missing, leader) if role == "follower" else (follower, missing)
    read = (lambda device: pytest.fail("read a missing board")) if role == "follower" else (lambda device: rows())
    bad = failed(check(*boards, readiness, read=read))
    assert set(bad) == {f"{role} board"} and "fix" in bad[f"{role} board"]


@pytest.mark.parametrize("error,hint", [
    ("Serial device is busy or its ownership could not be checked", "holding the bus"),
    ("Motor 13: ping failed (0, 128)", "hardware error"),  # read_motors without allow_fault
])
def test_a_bus_that_cannot_be_read_is_a_failure_with_the_matching_fix(cell, error, hint):
    def read(device):
        raise RuntimeError(error)
    bad = failed(check(*cell, read=read))
    assert bad["follower registers"]["detail"] == error and hint in bad["follower registers"]["fix"]


def test_unreadable_readiness_state_fails_closed(cell, tmp_path):
    follower, leader, _ = cell
    assert set(failed(check(follower, leader, tmp_path / "absent.json"))) == {"camera readiness"}


def test_resting_caps_match_the_tools_that_refuse_raised_caps():
    cl = module("commissioning_limits")
    assert {k: cl.BASELINE[k] for k in m.RESTING} == m.RESTING
    source = (ROOT / "deploy/robot/omx/joint_tune.py").read_text()
    assert 'BASELINE = {"pwm_limit": 20, "current_limit": 50}' in source
