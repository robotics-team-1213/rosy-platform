"""D-143 sensor adapters: IR and camera produce the same lane evidence."""

import numpy as np
import pytest

from control.sensing.perception.lane import (
    IRLineCalibration,
    detect_ir_line,
    detect_lane_error,
    line_observation_payload,
)


def calibration(**changes):
    values = dict(black=(500.0, 500.0, 500.0), white=(3000.0, 3000.0, 3000.0))
    values.update(changes)
    return IRLineCalibration(**values)


def camera_frame(value=230, offset=0):
    frame = np.full((120, 160, 3), 40, dtype=np.uint8)
    centre = frame.shape[1] // 2 + offset
    frame[:, centre - 4:centre + 4] = value
    return frame


def test_ir_white_line_uses_robot_left_centre_right_order():
    centred = detect_ir_line((550, 2900, 600), calibration())
    right = detect_ir_line((520, 650, 2950), calibration())
    left = detect_ir_line((2900, 650, 520), calibration())

    assert centred is not None
    assert centred.error == pytest.approx(0.0, abs=0.05)
    assert right is not None and right.error > 0.7
    assert left is not None and left.error < -0.7


def test_ir_calibration_expresses_reverse_polarity_without_a_boolean_guess():
    reversed_profile = calibration(
        black=(3000.0, 3000.0, 3000.0),
        white=(500.0, 500.0, 500.0),
    )
    observation = detect_ir_line((2900, 600, 2850), reversed_profile)

    assert observation is not None
    assert observation.error == pytest.approx(0.0, abs=0.05)


@pytest.mark.parametrize("profile", [
    dict(black=(500, 500, 500), white=(510, 3000, 3000)),
    dict(black=(500, 500), white=(3000, 3000)),
    dict(black=(500, 500, 500), white=(3000, float("nan"), 3000)),
])
def test_ir_calibration_rejects_unmeasured_or_malformed_endpoints(profile):
    with pytest.raises(ValueError):
        IRLineCalibration(**profile)


def test_ir_background_is_not_invented_as_a_line():
    assert detect_ir_line((550, 560, 540), calibration()) is None


def test_ir_two_bands_over_a_dark_centre_are_not_one_line():
    # 260919 crosswalk stripes run along the lane 40 mm apart: on a centred
    # drive left and right sit on stripes, the centre on the floor between.
    # Their centroid (error 0) would read as a line under the centre sensor,
    # which the D-344 §12 guard treats as a lane crossing.
    assert detect_ir_line((2900, 550, 2850), calibration()) is None
    assert detect_ir_line((2400, 1200, 2500), calibration()) is None
    # Polarity-agnostic: the rule runs on normalised strengths.
    reversed_profile = calibration(black=(3000.0, 3000.0, 3000.0),
                                   white=(500.0, 500.0, 500.0))
    assert detect_ir_line((600, 2900, 650), reversed_profile) is None


def test_ir_two_band_rule_edges_follow_the_detector_thresholds():
    # Normalised (s - 500) / 2500: 1875 -> 0.55 (min_white), 1500 -> 0.40.
    assert detect_ir_line((1875, 1500, 1875), calibration()) is None
    # One outer side under min_white is a single band, not two.
    weak = detect_ir_line((3000, 500, 1850), calibration())
    assert weak is not None and weak.error < 0.0
    # Centre not darker than the dimmer outer side by min_contrast: one band
    # fading to the right (normalised 1.0, 0.84, 0.70), still a line.
    wide = detect_ir_line((3000, 2600, 2250), calibration())
    assert wide is not None and -0.3 < wide.error < 0.0


def test_ir_one_band_across_two_sensors_is_still_a_line():
    # A 25-28 mm boundary line can cover the centre and one side at once.
    left_centre = detect_ir_line((2900, 2800, 550), calibration())
    assert left_centre is not None and left_centre.error < -0.3


def test_camera_threshold_and_roi_are_tunable_with_bounded_inputs():
    dim = camera_frame(value=165)
    assert detect_lane_error(dim) is None
    observation = detect_lane_error(
        dim,
        bright_threshold=150,
        roi_top_fraction=0.5,
        washed_fraction=0.5,
        min_pixels=40,
    )
    assert observation is not None
    assert observation.error == pytest.approx(0.0, abs=0.03)

    with pytest.raises(ValueError):
        detect_lane_error(dim, roi_top_fraction=1.0)
    with pytest.raises(ValueError):
        detect_lane_error(dim, bright_threshold=300)


def test_common_payload_marks_missing_line_as_not_visible():
    missing = line_observation_payload("CAMERA_LINE", 12.5, None)
    ir_calibration = calibration()
    present = line_observation_payload(
        "IR_LINE", 12.6, detect_ir_line((500, 2900, 500), ir_calibration),
        ir_calibrated=True, calibration_revision=ir_calibration.revision)

    assert missing == {
        "source": "CAMERA_LINE",
        "stamp": 12.5,
        "visible": False,
        "error": None,
        "confidence": 0.0,
    }
    assert present["visible"] is True
    assert present["error"] == pytest.approx(0.0, abs=0.05)
    assert 0.0 < present["confidence"] <= 1.0
    assert present["ir_calibrated"] is True
    assert present["calibration_revision"] == ir_calibration.revision
