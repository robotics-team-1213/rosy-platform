"""D-854 OMX action space: declared units and versioned pure converters shared by curation and the policy runner.

Formulas follow lerobot 0.4.4 ``motors_bus._normalize``/``_unnormalize`` for ``omx_follower`` recorded with
``use_degrees: false``. ``dynamixel_rad_v1`` is Present Position ticks around 2048 (raw * 2pi/4096 - pi);
its equality with ROS joint radians of a given install is not asserted here.
"""

from __future__ import annotations

import math
import re

from .artifacts import seal

NORM = "lerobot_norm_v1"
RAD = "dynamixel_rad_v1"
UNITS = frozenset({NORM, RAD})
#: lerobot 0.4.4 omx_follower motor order = observation.state/action column order.
MOTORS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
GRIPPER = "gripper"
TICKS = 4096
EPS = 1e-6  # float round trips land a few ulps past a range edge; that is not a clip


def validate_calibration(calibration):
    """Copy of the LeRobot calibration entries for MOTORS; refuses missing motors or empty ranges."""
    if not isinstance(calibration, dict) or set(MOTORS) - set(calibration):
        raise ValueError("calibration must name every omx_follower motor")
    out = {}
    for motor in MOTORS:
        entry = calibration[motor]
        lo, hi, mode = entry.get("range_min"), entry.get("range_max"), entry.get("drive_mode")
        if (type(lo) is not int or type(hi) is not int or not 0 <= lo < hi <= TICKS - 1
                or mode not in (0, 1) or type(mode) is not int):
            raise ValueError(f"invalid calibration range for {motor}")
        out[motor] = {"range_min": lo, "range_max": hi, "drive_mode": mode}
    return out


def calibration_sha256(calibration):
    """Digest over the fields the converters read, so unrelated calibration keys do not change it."""
    return seal(validate_calibration(calibration))["revision"]


def validate_declaration(declaration):
    """``{unit, motor_order, calibration_sha256}`` every dataset and policy must carry; returns a copy."""
    if not isinstance(declaration, dict) or set(declaration) != {"unit", "motor_order", "calibration_sha256"}:
        raise ValueError("action space needs exactly unit, motor_order and calibration_sha256")
    if declaration["unit"] not in UNITS:
        raise ValueError("unknown action space unit")
    if list(declaration["motor_order"]) != list(MOTORS):
        raise ValueError("motor order must be the omx_follower order")
    if not re.fullmatch(r"[0-9a-f]{64}", str(declaration["calibration_sha256"])):
        raise ValueError("calibration sha256 required")
    return {"unit": declaration["unit"], "motor_order": list(MOTORS),
            "calibration_sha256": declaration["calibration_sha256"]}


def _finite(values):
    values = [float(v) for v in values]
    if len(values) != len(MOTORS) or not all(math.isfinite(v) for v in values):
        raise ValueError(f"{len(MOTORS)} finite values in omx_follower order required")
    return values


def _rad_to_norm(values, calibration):
    out, clipped = [], 0
    for motor, rad in zip(MOTORS, values):
        c = calibration[motor]
        lo, hi = c["range_min"], c["range_max"]
        raw = (rad + math.pi) * TICKS / (2 * math.pi)
        bounded = min(hi, max(lo, raw))
        clipped += abs(bounded - raw) > EPS
        if motor == GRIPPER:
            n = (bounded - lo) / (hi - lo) * 100
            out.append(100 - n if c["drive_mode"] else n)
        else:
            n = (bounded - lo) / (hi - lo) * 200 - 100
            out.append(-n if c["drive_mode"] else n)
    return out, clipped


def _norm_to_rad(values, calibration):
    out, clipped = [], 0
    for motor, norm in zip(MOTORS, values):
        c = calibration[motor]
        lo, hi = c["range_min"], c["range_max"]
        if motor == GRIPPER:
            v = 100 - norm if c["drive_mode"] else norm
            bounded = min(100.0, max(0.0, v))
            raw = bounded / 100 * (hi - lo) + lo
        else:
            v = -norm if c["drive_mode"] else norm
            bounded = min(100.0, max(-100.0, v))
            raw = (bounded + 100) / 200 * (hi - lo) + lo
        clipped += abs(bounded - v) > EPS
        out.append(raw * 2 * math.pi / TICKS - math.pi)
    return out, clipped


#: (from_unit, to_unit) -> (converter version, pure function). A changed formula gets a new version.
CONVERTERS = {(RAD, NORM): (1, _rad_to_norm), (NORM, RAD): (1, _norm_to_rad)}


def convert(values, from_unit, to_unit, calibration):
    """One frame in omx_follower order -> (values, clipped count, converter version). Never silent: count clips."""
    values = _finite(values)
    if from_unit == to_unit and from_unit in UNITS:
        return values, 0, 0
    if (from_unit, to_unit) not in CONVERTERS:
        raise ValueError(f"no converter {from_unit} -> {to_unit}")
    version, fn = CONVERTERS[(from_unit, to_unit)]
    out, clipped = fn(values, validate_calibration(calibration))
    return out, clipped, version
