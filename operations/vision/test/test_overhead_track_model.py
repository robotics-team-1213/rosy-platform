"""D-457 3: tracking constants come from the Pinky URDF NOMINAL; Calibration refuses bad input."""

from pathlib import Path

import pytest
import yaml

from rosy_vision.track.model import (
    FOOTPRINT_MAX_M, FOOTPRINT_MIN_M, ROBOT_TOP_HEIGHT_M, ROTATION_RADIUS_M, Calibration,
)

GEOMETRY = Path(__file__).resolve().parents[3] / "middleware/apps/device/pinky/profile/config/geometry.yaml"


def test_robot_constants_follow_the_urdf_nominal():
    nominal = yaml.safe_load(GEOMETRY.read_text(encoding="utf-8"))
    assert ROBOT_TOP_HEIGHT_M == nominal["lidar"]["height_m"]
    assert ROTATION_RADIUS_M == nominal["footprint"]["rotation_radius_m"]
    assert FOOTPRINT_MIN_M < 2 * ROTATION_RADIUS_M < FOOTPRINT_MAX_M


def _calibration(**changes):
    args = dict(source_id="ceiling_north", map_id="map_v2_fleet", revision="paint-3f9a1c2b7d40",
                image_to_map=(0.01, 0.0, 0.0, 0.0, -0.01, 3.6, 0.0, 0.0, 1.0),
                image_size=(640, 360), track_bounds_m=(0.0, 0.0, 6.4, 3.6))
    args.update(changes)
    return Calibration(**args)


def test_a_valid_calibration_is_kept_as_given():
    calibration = _calibration(hfov_deg=66.9)
    assert calibration.image_size == (640, 360) and calibration.hfov_deg == 66.9


@pytest.mark.parametrize("changes", [
    {"image_to_map": (1.0,) * 8},
    {"image_to_map": (1.0,) * 9},
    {"image_to_map": (1e-8, 0.0, 0.0, 0.0, 1e-8, 0.0, 0.0, 0.0, 1e-8)},
    {"image_to_map": (1.0, 0.0, 0.0, 0.0, 1e-13, 0.0, 0.0, 0.0, 1.0)},
    {"image_size": (640.0, 360)},
    {"image_size": (True, 360)},
    {"source_id": 5},
    {"hfov_deg": 0.0},
    {"hfov_deg": 180.0},
    {"hfov_deg": float("nan")},
    {"image_to_map": (float("inf"),) + (1.0,) * 8},
    {"image_size": (0, 360)},
    {"track_bounds_m": (0.0, 0.0, 0.0, 3.6)},
    {"revision": " "},
])
def test_bad_calibrations_are_refused(changes):
    with pytest.raises(ValueError):
        _calibration(**changes)
