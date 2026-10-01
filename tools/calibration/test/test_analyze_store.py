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
