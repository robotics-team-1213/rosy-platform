"""Tests for OMX compensation feedback, non-silent bias coverage, arm_cal gap_mm_per_unit, and look/finger fallbacks."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))

import cell_arm_cal as ac  # noqa: E402
import cell_calibrate_auto as ca  # noqa: E402
import cell_diagnose as cd  # noqa: E402
import cell_fingers as cf  # noqa: E402
import cell_hooks as ch  # noqa: E402


def test_apply_to_config_propagates_gap_mm_per_unit(tmp_path):
    cal_path = tmp_path / "arm-cal-arm_b.json"
    cal_path.write_text(json.dumps({
        "schema": ac.SCHEMA,
        "arm_id": "arm_b",
        "samples": 12,
        "held_30mm": 53.38,
        "jaw_margin_mm": 12.0,
        "gap_mm_per_unit": 3.0,
        "hold_current_ma": 88,
        "grip_open_30mm": 61.38,
        "grip_release_30mm": 60.5,
    }))
    cfg = {
        "arm_id": "arm_b",
        "work_dir": str(tmp_path),
        "arm_calibration_path": str(cal_path),
        "params": {"gripper.gap_mm_per_unit": 10.4},
        "plan": {},
        "wrist": {},
    }
    ac.apply_to_config(cfg)
    assert cfg["params"]["gripper.held_30mm"] == 53.38
    assert cfg["params"]["gripper.gap_mm_per_unit"] == 3.0
    assert cfg["params"]["auto.jaw_margin_mm"] == 12.0


def test_learn_bias_does_not_pass_without_matching_region(tmp_path, monkeypatch):
    import cell_calibrate as cc

    monkeypatch.setattr(cc, "auto_pivot_point", lambda *a, **kw: None)
    monkeypatch.setattr(ca, "auto_pivot_point", lambda *a, **kw: None)
    monkeypatch.setattr(cc, "map_agrees", lambda *a, **kw: True)
    monkeypatch.setattr(ca, "map_agrees", lambda *a, **kw: True)
    cfg = {
        "params": {"pivot.bias_reach_mm": 120.0},
        "sites": {"beltend": {"yaw_deg": 0.0, "surface_z": -0.07}},
    }
    cal = {
        "sites": {
            "beltend": {
                "loo_error_mm": 1.2,
                "points": [{"arm_m": [0.15, 0.14]}],
                "model": "homography",
            }
        }
    }
    _, err = ca.self_calibrate(
        object(), cfg, cal, tmp_path / "cal.json", "beltend", (0.15, 0.14), [], tmp_path, {"regions": []},
        lambda *a: None, lambda *a: None,
    )
    assert err == "no clear pivot point within reach of the object"


def test_finger_servo_uses_structural_fallback_and_spec_parallax(monkeypatch):
    np = pytest.importorskip("numpy")
    calls = {}
    monkeypatch.setattr(cf, "finger_offset_mm", lambda *a, **kw: (calls.update(kw) or {"found": False, "why": "no container"}))
    monkeypatch.setattr(
        cf,
        "resolve_wrist_servo_offset",
        lambda *a, **kw: {"found": True, "along_mm": 1.0, "across_mm": 0.5, "mode": "structural"},
    )

    class Cell:
        def frame(self, camera):
            return np.zeros((10, 10, 3), np.uint8)

        def act(self, cmd):
            return {"ok": True}

    out = cf.finger_servo(
        Cell(), "wrist", ([0, 90, 90], [25, 255, 255]), 0.0, 50.0, lambda dx, dy: "lib.json",
        {"wrist.tol_mm": 4.5, "wrist.servo_iter": 2}, parallax_px=-13.4,
    )
    assert out["verdict"] == "pass"
    assert calls["parallax_px"] == -13.4


def test_compensation_feedback_flags_jaw_bias_and_wrist_issues():
    fb = cd.compensation_feedback(
        "stopped: misaligned",
        tried={
            "wrist": "disabled or uncalibrated",
            "auto": {"bias_mm": [0.0, 0.0]},
            "diagnosis": {"cause": "empty"},
        },
        grip_open=54.9,
        calibrated_grip_open=61.4,
    )
    assert fb["ok"] is False
    assert fb["stale_bias"] is True
    assert fb["jaw_underopen"] is True
    assert set(fb["actions"]) >= {"widen_jaw_open", "enable_wrist_servo", "run_local_pivot", "shift_xy_offset"}
