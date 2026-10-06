"""analyze_session writes candidate records even with non-finite uncertainty (review open question)."""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

AS = pytest.importorskip("analyze_session")
from core_common.calibration_store import CalibrationStore  # noqa: E402


def test_store_candidates_tolerates_nan_and_inf(tmp_path):
    nan = float("nan")
    cand = {
        "sessions": ["s1"],
        "odometry": {"wheel_radius": {"mean": 0.0271, "ci95": nan},
                     "wheel_separation": {"mean": 0.0968, "ci95": float("inf")},
                     "right_to_left_ratio": {"mean": nan}, "gains": {"pivot": {"mean": 0.936, "sd": nan}}},
        "lidar_yaw_offset_check": {"configured_deg": 190.0, "from_motion_deg": {"mean": 181.9, "ci95": nan}},
        "camera": {"width": 320, "height": 240, "fx": 281.6, "cx": 160.0, "cy": 120.0, "pitch_rad": 0.195,
                   "height_m": 0.0575, "x_offset_m": 0.034, "roll_rad": nan,
                   "across_runs": {"pitch_rad": {"mean": 11.2, "ci95": nan}}, "uncertainty": {"pitch_deg": nan}},
    }
    ids = AS.store_candidates(CalibrationStore(tmp_path), "rosy-x", cand)
    assert set(ids) == {"wheel_odometry", "lidar_mount", "camera_profile"}
    rec = CalibrationStore(tmp_path).load("rosy-x", "wheel_odometry", ids["wheel_odometry"])
    assert rec["intervals"]["wheel_radius"] == [None, None]
    cam = CalibrationStore(tmp_path).load("rosy-x", "camera_profile", ids["camera_profile"])
    assert cam["values"]["roll_rad"] is None and math.isclose(cam["values"]["pitch_rad"], 0.195)


def _cam_run(pitch_deg, roll_deg, height_m, bands, wall_points=500):
    return {"session": f"s{pitch_deg}", "device": "rosy-x", "straights_only": True,
            "records": [], "odometry": {},
            "camera": {"pitch_rad": math.radians(pitch_deg), "roll_rad": math.radians(roll_deg),
                       "height_m": height_m, "height_source": "fit", "score": 30.0, "score_at_base": 1.0,
                       "wall_points": wall_points, "uncertainty": bands, "fit_step": AS.CE.PC_FINE_STEPS,
                       "recommended": True, "why": "fit beats the base profile"}}


def _combine(runs, monkeypatch):
    monkeypatch.setattr(AS, "nominal_wheels", lambda: (0.028, 0.0971))
    return AS.combine("rosy-x", runs, 181.9, AS.load_profile())


def test_camera_interval_is_the_larger_of_score_band_and_across_run_ci95(monkeypatch):
    # Three runs agree to 0.1 deg in roll but spread 1 deg in pitch: pitch takes the ci95,
    # roll and height keep the widest run's score half-band (not the best run's).
    runs = [_cam_run(10.7, -1.4, 0.0600, {"pitch_deg": 0.2, "roll_deg": 0.3, "height_m": 0.002}, 900),
            _cam_run(11.2, -1.5, 0.0601, {"pitch_deg": 0.2, "roll_deg": 0.2, "height_m": 0.003}),
            _cam_run(11.7, -1.5, 0.0599, {"pitch_deg": 0.2, "roll_deg": 0.2, "height_m": 0.002})]
    cam = _combine(runs, monkeypatch)["camera"]
    across = cam["across_runs"]
    assert cam["uncertainty"]["pitch_deg"] == pytest.approx(across["pitch_rad"]["ci95"])
    assert across["pitch_rad"]["ci95"] > 0.2
    assert cam["uncertainty"]["roll_deg"] == pytest.approx(0.3)
    assert cam["uncertainty"]["height_m"] == pytest.approx(0.003)
    assert cam["fit_step"] == AS.CE.PC_FINE_STEPS


def _base(run):
    run["camera"]["height_source"] = "base"
    return run


def test_a_kept_base_height_keeps_no_height_band(monkeypatch):
    run = _base(_cam_run(11.2, -1.5, 0.06343, {"pitch_deg": 0.2, "roll_deg": 0.2, "height_m": None}))
    cam = _combine([run], monkeypatch)["camera"]
    assert cam["uncertainty"]["height_m"] is None
    assert cam["height_source"] == "base"


def test_only_fitted_heights_are_averaged_and_banded(monkeypatch):
    # The best run kept the base height; two others fitted it. The height is the fitted
    # runs' mean and its band the widest fitted run's (or their ci95), never None.
    runs = [_base(_cam_run(11.2, -1.5, 0.06343, {"pitch_deg": 0.2, "roll_deg": 0.2, "height_m": 0.0125}, 900)),
            _cam_run(11.3, -1.5, 0.0600, {"pitch_deg": 0.2, "roll_deg": 0.2, "height_m": 0.002}),
            _cam_run(11.1, -1.5, 0.0602, {"pitch_deg": 0.2, "roll_deg": 0.2, "height_m": 0.003})]
    cam = _combine(runs, monkeypatch)["camera"]
    assert cam["height_m"] == pytest.approx(0.0601, abs=1e-6)
    assert cam["height_source"] == "fit"
    ci95 = cam["across_runs"]["height_m"]["ci95"]
    assert cam["across_runs"]["height_m"]["n"] == 2
    assert cam["uncertainty"]["height_m"] == pytest.approx(max(0.003, ci95))


def test_store_records_the_fit_step_and_the_pc_fit_uses_pc_steps(tmp_path):
    assert AS.CAMERA_FIT_STEPS == AS.CE.PC_FINE_STEPS
    cand = {"sessions": ["s1"], "odometry": {"wheel_radius": None, "wheel_separation": None},
            "lidar_yaw_offset_check": {"configured_deg": 181.9, "from_motion_deg": None},
            "camera": {"pitch_rad": 0.195, "height_m": 0.06, "roll_rad": -0.02,
                       "uncertainty": {"pitch_deg": 0.3, "roll_deg": 0.2, "height_m": 0.002},
                       "fit_step": AS.CE.PC_FINE_STEPS, "across_runs": None}}
    ids = AS.store_candidates(CalibrationStore(tmp_path), "rosy-x", cand)
    rec = CalibrationStore(tmp_path).load("rosy-x", "camera_profile", ids["camera_profile"])
    assert rec["intervals"]["fit_step"] == AS.CE.PC_FINE_STEPS
