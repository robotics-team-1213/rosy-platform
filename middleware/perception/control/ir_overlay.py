"""Per-robot overlays for line_observer_node (D-344 §12). Pure, ROS-free.

Two partial ROS parameter files under /etc/rosy, which a payload release never
replaces (D-388 sync refuses etc/rosy/), are layered after the release's
line_follow.yaml:

* the IR calibration overlay, holding only the observer's IR calibration keys;
* the operator override overlay (D-344 §12 addendum 2026-10-03), holding only
  an allowlist of camera lane keys: the bench setting that used to be edited
  into the release's line_follow.yaml and was lost on every update.

A malformed file must never crash-loop the observer (it still owes CORE camera
line evidence), so launch validates each here and skips it with a message
instead of handing it to the node.
"""

from __future__ import annotations

import math
import os
from typing import Optional

import yaml

#: Distinct from /etc/rosy/line_follow.yaml, which is a full config for the
#: navigation-graph line_follow launch.
IR_CALIBRATION_OVERLAY = "/etc/rosy/ir_calibration.yaml"
NODE_KEY = "/**/line_observer_node"
_FLOAT_KEYS = ("ir_min_span", "ir_min_white", "ir_min_contrast")
ALLOWED_KEYS = frozenset(("ir_calibration_enabled", "ir_black", "ir_white") + _FLOAT_KEYS)


def overlay_problem(data) -> Optional[str]:
    """None when `data` is a usable observer overlay, else why not."""
    params, problem = _observer_params(data)
    if problem is not None:
        return problem
    unknown = set(params) - ALLOWED_KEYS
    if unknown:
        return f"only IR calibration keys are allowed, got {sorted(unknown)}"
    if "ir_calibration_enabled" in params and type(params["ir_calibration_enabled"]) is not bool:
        return "ir_calibration_enabled must be true or false"
    for key in ("ir_black", "ir_white"):
        if key in params:
            value = params[key]
            if (not isinstance(value, list) or len(value) != 3
                    or any(type(item) is not float or not math.isfinite(item) for item in value)):
                return f"{key} must be three decimal numbers like [1200.0, 1150.0, 1250.0]"
    for key in _FLOAT_KEYS:
        if key in params and (type(params[key]) is not float or not math.isfinite(params[key])):
            return f"{key} must be a decimal number like 100.0"
    if params.get("ir_calibration_enabled"):
        if "ir_black" not in params or "ir_white" not in params:
            return "enabled calibration needs ir_black and ir_white"
        try:
            # Lazy: lane.py pulls in cv2/numpy. A broken import must skip the overlay,
            # never abort the camera launch.
            from control.sensing.perception.lane import IRLineCalibration
        except ImportError as exc:
            return f"cannot check the calibration ({exc})"
        try:
            IRLineCalibration(black=tuple(params["ir_black"]), white=tuple(params["ir_white"]),
                              min_span=params.get("ir_min_span", 100.0))
        except ValueError as exc:
            return f"calibration rejected: {exc}"
    return None


def usable_overlay(path: str = IR_CALIBRATION_OVERLAY) -> tuple[Optional[str], str]:
    """(path to load or None, message for the launch log)."""
    return _usable(path, overlay_problem, "IR calibration stays as packaged")


#: Operator overrides of the observer's camera lane settings (bench keep/NOMINAL).
OPERATOR_OVERLAY = "/etc/rosy/line_observer_overrides.yaml"
#: Modes that need no key outside this allowlist (route_* need a lane graph and route).
OPERATOR_LANE_MODES = ("line", "between", "lane", "edge_left", "centre", "keep")
#: A robot has no Gazebo ground; GAZEBO stays a sim launch setting.
OPERATOR_GROUND_SOURCES = ("PINKY", "NOMINAL")
#: D-397 operator layer, same physical range as calibration_store.check_values camera_profile.
OPERATOR_RANGES = {"camera_pitch_rad_override": (-0.2, 0.6),
                   "camera_height_m_override": (0.02, 0.2)}
#: Same values as paint_worker.TARGETS (kept literal: this module must import without numpy/cv2).
LEARNED_PAINT_TARGETS = ("lane_marking", "drivable")
OPERATOR_KEYS = frozenset(("camera_lane_mode", "camera_ground_source", "allow_nominal_ground",
                           "nominal_camera_profile_path", "debug_overlay", "paint_source",
                           "learned_lane_pointer", "learned_paint_every_n", "learned_paint_threads",
                           "learned_paint_motion_compensation", "learned_paint_target")
                          + tuple(OPERATOR_RANGES))


def operator_overlay_problem(data) -> Optional[str]:
    """None when `data` is a usable operator override overlay, else why not."""
    params, problem = _observer_params(data)
    if problem is not None:
        return problem
    unknown = set(params) - OPERATOR_KEYS
    if unknown:
        return f"only {sorted(OPERATOR_KEYS)} are allowed, got {sorted(unknown)}"
    if "camera_lane_mode" in params and params["camera_lane_mode"] not in OPERATOR_LANE_MODES:
        return f"camera_lane_mode must be one of {list(OPERATOR_LANE_MODES)}"
    if ("camera_ground_source" in params
            and params["camera_ground_source"] not in OPERATOR_GROUND_SOURCES):
        return f"camera_ground_source must be one of {list(OPERATOR_GROUND_SOURCES)}"
    for key in ("allow_nominal_ground", "debug_overlay", "learned_paint_motion_compensation"):
        if key in params and type(params[key]) is not bool:
            return f"{key} must be true or false"
    if "nominal_camera_profile_path" in params:
        value = params["nominal_camera_profile_path"]
        if not isinstance(value, str) or not value.startswith("/") or not value.endswith(".yaml"):
            return "nominal_camera_profile_path must be an absolute path to a .yaml file"
    for key, (low, high) in OPERATOR_RANGES.items():
        if key in params:
            value = params[key]
            if type(value) is not float or not math.isfinite(value) or not low <= value <= high:
                return f"{key} must be a decimal number in [{low}, {high}]"
    if params.get("camera_ground_source") == "NOMINAL" and not (
            params.get("allow_nominal_ground") is True and params.get("nominal_camera_profile_path")):
        return "NOMINAL ground needs allow_nominal_ground: true and nominal_camera_profile_path"
    if params.get("allow_nominal_ground") is True and params.get("camera_ground_source") != "NOMINAL":
        # Arming NOMINAL here while the ground source comes from elsewhere would leave a
        # half-switched observer that a later edit of another layer silently completes.
        return "allow_nominal_ground: true needs camera_ground_source: NOMINAL in the same file"
    if "paint_source" in params:
        if params["paint_source"] not in ("threshold", "denoise", "learned"):
            return "paint_source must be threshold, denoise or learned"
        if params["paint_source"] != "threshold" and params.get("camera_lane_mode") != "keep":
            return "denoise/learned paint requires camera_lane_mode: keep"
    # D-597: inert unless paint_source is learned, so a later switch back to threshold
    # (Host Agent lane_perception.set keeps the other keys) still leaves a valid file.
    if "learned_paint_target" in params and params["learned_paint_target"] not in LEARNED_PAINT_TARGETS:
        return f"learned_paint_target must be one of {list(LEARNED_PAINT_TARGETS)}"
    if "learned_lane_pointer" in params:
        value = params["learned_lane_pointer"]
        if not isinstance(value, str) or not value.startswith("/"):
            return "learned_lane_pointer must be an absolute path"
    if params.get("paint_source") == "learned" and not params.get("learned_lane_pointer"):
        return "learned paint needs learned_lane_pointer in the same file"
    # every_n up to 4: measured Pi 5 lane-seg inference is ~240-300 ms, about
    # 2.4 frames at 8 Hz, so every_n 2 never serves a mask (0/84 live, 9dfk).
    # Threads stay at 2: a Pi has four cores and CORE/IO must retain capacity.
    for key, high in (("learned_paint_every_n", 4), ("learned_paint_threads", 2)):
        if key in params and (type(params[key]) is not int or not 1 <= params[key] <= high):
            return f"{key} must be an integer in [1, {high}]"
    return None


def usable_operator_overlay(path: str = OPERATOR_OVERLAY) -> tuple[Optional[str], str]:
    """(path to load or None, message for the launch log)."""
    return _usable(path, operator_overlay_problem, "camera lane settings stay as packaged")


def _observer_params(data):
    if not isinstance(data, dict) or set(data) != {NODE_KEY}:
        return None, f"top level must be exactly {NODE_KEY!r}"
    node = data[NODE_KEY]
    if not isinstance(node, dict) or set(node) != {"ros__parameters"}:
        return None, "node block must hold only ros__parameters"
    params = node["ros__parameters"]
    if not isinstance(params, dict) or not params:
        return None, "ros__parameters must be a non-empty mapping"
    return params, None


def _usable(path, problem_of, absent_note):
    if not os.path.isfile(path):
        return None, f"{path} absent; {absent_note}"
    try:
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        return None, f"{path} unreadable, skipped: {exc}"
    problem = problem_of(data)
    if problem is not None:
        return None, f"{path} skipped: {problem}"
    return path, f"{path} loaded"
