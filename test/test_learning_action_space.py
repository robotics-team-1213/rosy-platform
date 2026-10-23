"""D-854 OMX action space: declaration, golden values against the lerobot 0.4.4 formula, round trip, clip counts."""
import math
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "contracts/learning/src"))
from rosy.contracts.learning.action_space import (
    MOTORS, NORM, RAD, calibration_sha256, convert, validate_calibration, validate_declaration)

CAL = {m: {"id": i + 11, "homing_offset": 0, "range_min": 1024, "range_max": 3072, "drive_mode": 0}
       for i, m in enumerate(MOTORS)}
CAL["wrist_roll"]["drive_mode"] = 1
CAL["gripper"] = {"id": 16, "homing_offset": 0, "range_min": 2000, "range_max": 3000, "drive_mode": 1}


def rad(raw):
    return raw * 2 * math.pi / 4096 - math.pi


def test_golden_values_match_lerobot_normalize():
    # raw 2048 -> 0, raw 3072 -> +100, raw 1024 -> -100; drive_mode negates body, flips gripper (100 - n).
    values = [rad(2048), rad(3072), rad(1024), rad(1536), rad(3072), rad(2250)]
    out, clipped, version = convert(values, RAD, NORM, CAL)
    assert (clipped, version) == (0, 1)
    assert out == pytest.approx([0.0, 100.0, -100.0, -50.0, -100.0, 75.0])


def test_round_trip_inside_range():
    norm = [-87.5, -10.0, 0.0, 33.3, 99.0, 12.5]
    back, clipped, _ = convert(convert(norm, NORM, RAD, CAL)[0], RAD, NORM, CAL)
    assert clipped == 0 and back == pytest.approx(norm, abs=1e-9)


def test_out_of_range_is_clipped_and_counted():
    out, clipped, _ = convert([rad(4000), 0.0, 0.0, 0.0, 0.0, rad(1000)], RAD, NORM, CAL)
    assert clipped == 2 and out[0] == pytest.approx(100.0) and out[5] == pytest.approx(100.0)
    _, clipped, _ = convert([150.0, 0, 0, 0, 0, -5.0], NORM, RAD, CAL)
    assert clipped == 2


def test_refuses_bad_input():
    with pytest.raises(ValueError):
        convert([0.0] * 5, RAD, NORM, CAL)
    with pytest.raises(ValueError):
        convert([0.0, 0, 0, 0, 0, float("nan")], RAD, NORM, CAL)
    with pytest.raises(ValueError):
        convert([0.0] * 6, RAD, "degrees", CAL)
    with pytest.raises(ValueError):
        validate_calibration({m: CAL[m] for m in MOTORS[:-1]})
    with pytest.raises(ValueError):
        validate_calibration({**CAL, "gripper": {**CAL["gripper"], "range_min": 3000}})


def test_calibration_digest_ignores_unread_fields():
    other = {m: {**v, "id": 99, "homing_offset": 7} for m, v in CAL.items()}
    assert calibration_sha256(other) == calibration_sha256(CAL)
    changed = {**CAL, "elbow_flex": {**CAL["elbow_flex"], "range_max": 3000}}
    assert calibration_sha256(changed) != calibration_sha256(CAL)


def test_declaration_is_exact():
    good = {"unit": NORM, "motor_order": list(MOTORS), "calibration_sha256": calibration_sha256(CAL)}
    assert validate_declaration(good) == good
    for bad in ({**good, "unit": "normalized_-100_100"}, {**good, "motor_order": list(reversed(MOTORS))},
                {**good, "calibration_sha256": "x"}, {k: v for k, v in good.items() if k != "unit"},
                {**good, "fps": 30}):
        with pytest.raises(ValueError):
            validate_declaration(bad)
