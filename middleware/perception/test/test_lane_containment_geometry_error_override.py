"""D-491 amendment 2026-10-10: an operator override of pitch/height may state the accepted record's
bands; without them the override states no error."""
from control.sensing.perception.lane_containment import geometry_error

PROFILE = {"pitch_uncertainty_rad": 0.066, "height_uncertainty_m": 0.011, "roll_uncertainty_rad": 0.047,
           "detector_lateral_px": 3.0}


def test_override_without_bands_states_no_error():
    assert geometry_error(PROFILE, None, overridden={"pitch_rad": 0.2}) is None


def test_override_with_bands_uses_them():
    error = geometry_error(PROFILE, None, overridden={"pitch_rad": 0.2},
                           override_bounds={"pitch_uncertainty_rad": 0.0044, "height_uncertainty_m": 0.005})
    assert error == (0.0044, 0.005, 0.047, 3.0)
