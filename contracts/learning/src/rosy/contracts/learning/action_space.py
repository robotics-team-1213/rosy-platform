"""D-854 OMX action space: declared units and versioned pure converters shared by curation and the policy runner.

Formulas follow lerobot 0.4.4 ``motors_bus._normalize``/``_unnormalize`` for ``omx_follower`` recorded with
``use_degrees: false``. ``dynamixel_rad_v1`` is Present Position ticks around 2048 (raw * 2pi/4096 - pi);
``ros_joint_rad`` (D-864) is the ROS joint radian of joint1..5 and gripper_joint_1, the unit of CORE, Gazebo and
Isaac Sim. Converting to or from it needs a passing D-864 joint map verdict for the same register state as the
calibration, because only that ties a recorded arm's motor radians to ROS joint radians. lerobot 0.4.4's
``DynamixelMotorsBus`` sets ``apply_drive_mode = False``, so ``drive_mode`` never changes OMX values and is not read.
"""

from __future__ import annotations

import math
import re

from .artifacts import seal

NORM = "lerobot_norm_v1"
RAD = "dynamixel_rad_v1"
ROS = "ros_joint_rad"
UNITS = frozenset({NORM, RAD, ROS})
#: lerobot 0.4.4 omx_follower motor order = observation.state/action column order.
MOTORS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
GRIPPER = "gripper"
#: ROS joints in the same order (open_manipulator omx_f, motor IDs 11..16).
ROS_JOINTS = ("joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1")
MOTOR_IDS = (11, 12, 13, 14, 15, 16)
TICKS = 4096
EPS = 1e-6  # float round trips land a few ulps past a range edge; that is not a clip


def validate_calibration(calibration):
    """Copy of the ranges the converters read for MOTORS; refuses missing motors or empty ranges."""
    if not isinstance(calibration, dict) or set(MOTORS) - set(calibration):
        raise ValueError("calibration must name every omx_follower motor")
    out = {}
    for motor in MOTORS:
        entry = calibration[motor]
        if not isinstance(entry, dict):
            raise ValueError(f"invalid calibration entry for {motor}")
        lo, hi = entry.get("range_min"), entry.get("range_max")
        if type(lo) is not int or type(hi) is not int or not 0 <= lo < hi <= TICKS - 1:
            raise ValueError(f"invalid calibration range for {motor}")
        out[motor] = {"range_min": lo, "range_max": hi}
    return out


def calibration_sha256(calibration):
    """Digest over the fields the converters read, so unrelated calibration keys do not change it."""
    return seal(validate_calibration(calibration))["revision"]


def validate_declaration(declaration):
    """The action space every dataset and policy must carry; returns a copy.

    ``lerobot_norm_v1``/``dynamixel_rad_v1``: ``{unit, motor_order, calibration_sha256}``.
    ``ros_joint_rad`` adds ``joint_map_revision``. Both are null only for SIM data, which has no motors; data
    converted from a recorded arm names the calibration and the joint map verdict it was converted with.
    """
    unit = declaration.get("unit") if isinstance(declaration, dict) else None
    keys = {"unit", "motor_order", "calibration_sha256"} | ({"joint_map_revision"} if unit == ROS else set())
    if not isinstance(declaration, dict) or set(declaration) != keys:
        raise ValueError(f"action space needs exactly {sorted(keys)}")
    if unit not in UNITS:
        raise ValueError("unknown action space unit")
    order = ROS_JOINTS if unit == ROS else MOTORS
    if list(declaration["motor_order"]) != list(order):
        raise ValueError(f"motor order must be {'the ROS joint' if unit == ROS else 'the omx_follower'} order")
    digests = [declaration[k] for k in sorted(keys - {"unit", "motor_order"})]
    hexes = [isinstance(d, str) and re.fullmatch(r"[0-9a-f]{64}", d) is not None for d in digests]
    simulated = unit == ROS and all(d is None for d in digests)
    if not simulated and not all(hexes):
        raise ValueError("calibration sha256 (and for converted ROS data the joint map revision) required")
    return {k: (list(order) if k == "motor_order" else declaration[k]) for k in keys}


def ros_declaration(calibration, verdict, rig_revision):
    """Declaration for data converted to ros_joint_rad from a recorded arm, after the joint map gate."""
    return {"unit": ROS, "motor_order": list(ROS_JOINTS), "calibration_sha256": calibration_sha256(calibration),
            "joint_map_revision": validate_joint_map(verdict, calibration, rig_revision)}


def validate_joint_map(verdict, calibration, rig_revision):
    """A passing D-864 joint map verdict for this arm and calibration; returns the verdict's revision.

    The verdict's ``arm`` is the rig_revision the arm's datasets are reviewed under and must equal the data's.
    Full-range calibrations are identical across arms, so the range digest alone cannot tell arms apart; it still
    must match, and the calibration's own homing offset and drive mode must be zero as found on the motors.
    """
    if not isinstance(rig_revision, str) or not rig_revision.strip():
        raise ValueError("the data's rig revision is required")
    try:
        return _joint_map(verdict, calibration, rig_revision)
    except (AttributeError, TypeError, KeyError) as exc:
        raise ValueError("malformed joint map verdict or calibration") from exc


def _joint_map(verdict, calibration, rig_revision):
    if (not isinstance(verdict, dict) or verdict.get("schema") != "rosy.omx-joint-map-check/3"
            or verdict.get("holds") is not True or not isinstance(verdict.get("probes"), int) or verdict["probes"] < 2):
        raise ValueError("a passing joint map verdict over two or more probes is required")
    joints = verdict.get("joints")
    if (not isinstance(joints, list) or [(j.get("motor_id"), j.get("joint")) for j in joints]
            != list(zip(MOTOR_IDS, ROS_JOINTS))
            or any(j.get("holds") is not True or j.get("homing_offset_raw") != 0
                   or type(j.get("drive_mode")) is not int or j["drive_mode"] & 1 for j in joints)):
        raise ValueError("joint map verdict must hold for motors 11..16 in ROS joint order")
    if verdict.get("arm") != rig_revision:
        raise ValueError("joint map verdict was made for another arm")
    if verdict.get("calibration_sha256") != calibration_sha256(calibration):
        raise ValueError("joint map verdict was made for another calibration")
    for motor, motor_id in zip(MOTORS, MOTOR_IDS):
        entry = calibration[motor]
        if entry.get("id") != motor_id or entry.get("homing_offset") != 0 or entry.get("drive_mode") != 0:
            raise ValueError(f"calibration register state for {motor} differs from the joint map verdict")
    return seal(verdict)["revision"]


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
            out.append((bounded - lo) / (hi - lo) * 100)
        else:
            out.append((bounded - lo) / (hi - lo) * 200 - 100)
    return out, clipped


def _norm_to_rad(values, calibration):
    out, clipped = [], 0
    for motor, norm in zip(MOTORS, values):
        c = calibration[motor]
        lo, hi = c["range_min"], c["range_max"]
        if motor == GRIPPER:
            bounded = min(100.0, max(0.0, norm))
            raw = bounded / 100 * (hi - lo) + lo
        else:
            bounded = min(100.0, max(-100.0, norm))
            raw = (bounded + 100) / 200 * (hi - lo) + lo
        clipped += abs(bounded - norm) > EPS
        out.append(raw * 2 * math.pi / TICKS - math.pi)
    return out, clipped


def _identity(values, calibration):
    return list(values), 0


#: (from_unit, to_unit) -> (converter version, pure function). A changed formula gets a new version.
#: ros_joint_rad equals dynamixel_rad_v1 per joint once a joint map verdict holds (D-864 §2).
CONVERTERS = {(RAD, NORM): (1, _rad_to_norm), (NORM, RAD): (1, _norm_to_rad),
              (ROS, NORM): (1, _rad_to_norm), (NORM, ROS): (1, _norm_to_rad),
              (ROS, RAD): (1, _identity), (RAD, ROS): (1, _identity)}


def convert(values, from_unit, to_unit, calibration, joint_map=None, rig_revision=None):
    """One frame in declared order -> (values, clipped count, converter version). Never silent: count clips.

    A conversion to or from ros_joint_rad needs ``joint_map``, a passing verdict for this ``rig_revision`` and
    ``calibration``.
    """
    values = _finite(values)
    if from_unit == to_unit and from_unit in UNITS:
        return values, 0, 0
    if (from_unit, to_unit) not in CONVERTERS:
        raise ValueError(f"no converter {from_unit} -> {to_unit}")
    if ROS in (from_unit, to_unit):
        validate_joint_map(joint_map, calibration, rig_revision)
    version, fn = CONVERTERS[(from_unit, to_unit)]
    out, clipped = fn(values, validate_calibration(calibration))
    return out, clipped, version
