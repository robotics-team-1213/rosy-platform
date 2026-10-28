"""Validate the D-496 measured document; never authorize or configure hardware."""
from __future__ import annotations

from datetime import date
import math
from pathlib import PurePosixPath

import yaml


def _fields(value, names, label):
    if not isinstance(value, dict) or set(value) != set(names.split()):
        raise ValueError(f"{label}: expected fields {names}")
    return value


def _number(value, label, *, positive=False):
    try:
        finite = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError(f"{label}: expected finite numeric measurement")
    if positive and value <= 0:
        raise ValueError(f"{label}: measurement outside allowed range")
    return value


def _vector(value, size, label):
    if not isinstance(value, list) or len(value) != size:
        raise ValueError(f"{label}: expected {size} measurements")
    return [_number(item, label) for item in value]


def _range(value, label):
    low, high = _vector(value, 2, label)
    if low >= high:
        raise ValueError(f"{label}: minimum must be below maximum")
    return low, high


def validate_profile(data):
    """Check a document's consistency, without trusting its evidence claims."""
    _fields(data, "schema profile measured serial joints gripper workspace owner power", "profile")
    if data["schema"] != "rosy.omx-hardware-profile.v1" or data["profile"] != "hardware":
        raise ValueError("expected D-496 hardware profile; simulation is not a measurement")
    measured = _fields(data["measured"], "date revision evidence", "measured")
    for key, value in measured.items():
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise ValueError(f"measured.{key}: expected non-empty string")
    measurement_date = date.fromisoformat(measured["date"])
    if measurement_date.isoformat() != measured["date"]:
        raise ValueError("measured.date: expected YYYY-MM-DD")
    evidence = measured["evidence"]
    prefix = f"docs/validation/omx-hardware-{measured['date']}/"
    if (not evidence.startswith(prefix) or not evidence[len(prefix):]
            or "\\" in evidence or ".." in PurePosixPath(evidence).parts):
        raise ValueError("measured.evidence: expected matching dated validation path")
    serial = _fields(data["serial"], "by_id baudrate", "serial")
    by_id = serial["by_id"]
    if (not isinstance(by_id, str) or not by_id.startswith("/dev/serial/by-id/")
            or by_id.rsplit("/", 1)[-1] in {"", ".", ".."}
            or len(PurePosixPath(by_id).parts) != 5 or any(c.isspace() for c in by_id)):
        raise ValueError("serial.by_id: expected a single persistent by-id entry")
    if type(serial["baudrate"]) is not int or serial["baudrate"] != 1000000:
        raise ValueError("serial.baudrate: expected the pinned 1000000 baud contract")
    names = [f"joint{i}" for i in range(1, 6)]
    joints = _fields(data["joints"], " ".join(names), "joints")
    if list(joints) != names:
        raise ValueError("joints: expected ordered joint1 through joint5 in radians")
    for name, joint in joints.items():
        _fields(joint, "position velocity acceleration", name)
        _range(joint["position"], f"{name}.position")
        for key in ("velocity", "acceleration"):
            _number(joint[key], f"{name}.{key}", positive=True)
    gripper = _fields(data["gripper"], "joint position open closed preload jaw", "gripper")
    if gripper["joint"] != "gripper_joint_1":
        raise ValueError("gripper.joint: expected gripper_joint_1")
    low, high = _range(gripper["position"], "gripper.position")
    opened = _number(gripper["open"], "gripper.open")
    closed = _number(gripper["closed"], "gripper.closed")
    preload = _number(gripper["preload"], "gripper.preload", positive=True)
    if not low <= closed < opened <= high or closed - preload < low or preload >= opened - closed:
        raise ValueError("gripper: open, closed and preload must fit measured position range")
    jaw = _fields(gripper["jaw"], "pivot_y_m contact_point_m squeeze_m min_grasp_width_m "
                  "max_grasp_width_m release_clearance_m", "gripper.jaw")
    pivot_a, pivot_b = _vector(jaw["pivot_y_m"], 2, "jaw.pivot_y_m")
    contact_x, _ = _vector(jaw["contact_point_m"], 2, "jaw.contact_point_m")
    if pivot_a <= pivot_b or contact_x <= 0:
        raise ValueError("jaw: expected ordered pivots and contact point ahead of pivot")
    for key in ("squeeze_m", "min_grasp_width_m", "max_grasp_width_m", "release_clearance_m"):
        _number(jaw[key], f"jaw.{key}", positive=True)
    if jaw["min_grasp_width_m"] >= jaw["max_grasp_width_m"] or jaw["squeeze_m"] >= jaw["min_grasp_width_m"]:
        raise ValueError("jaw: invalid grasp width or squeeze range")
    workspace = _fields(data["workspace"], "min_m max_m", "workspace")
    minimum = _vector(workspace["min_m"], 3, "workspace.min_m")
    maximum = _vector(workspace["max_m"], 3, "workspace.max_m")
    if any(lo >= hi for lo, hi in zip(minimum, maximum)):
        raise ValueError("workspace: minimum must be below maximum on every axis")
    owner = _fields(data["owner"], "max_joint_state_age_s action_timeout_s wall_clock_bound_factor", "owner")
    power = _fields(data["power"], "supply_v noted_load_a", "power")
    for label, values in (("owner", owner), ("power", power)):
        for key, value in values.items():
            _number(value, f"{label}.{key}", positive=True)
    if owner["wall_clock_bound_factor"] < 1:
        raise ValueError("owner.wall_clock_bound_factor: must be at least one")
    return {"profile_document_valid": True, "motion_admitted": False, "joint_names": names,
            "unverified": ["physical_identity", "measurement_authenticity", "independent_stop",
                           "calibration", "payload", "recovery", "runtime_binding"]}


class _UniqueLoader(yaml.SafeLoader):
    """Reject duplicates instead of silently replacing a measured limit."""

    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise ValueError("profile YAML requires unique string keys")
            result[key] = self.construct_object(value_node, deep=deep)
        return result
