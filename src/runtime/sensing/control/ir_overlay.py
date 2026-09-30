"""Per-robot IR calibration overlay for line_observer_node (D-344 §12). Pure, ROS-free.

The overlay is a partial ROS parameter file holding only the observer's IR
calibration keys. A malformed file must never crash-loop the observer (it
still owes CORE camera line evidence), so launch validates it here and skips
it with a message instead of handing it to the node.
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
    if not isinstance(data, dict) or set(data) != {NODE_KEY}:
        return f"top level must be exactly {NODE_KEY!r}"
    node = data[NODE_KEY]
    if not isinstance(node, dict) or set(node) != {"ros__parameters"}:
        return "node block must hold only ros__parameters"
    params = node["ros__parameters"]
    if not isinstance(params, dict) or not params:
        return "ros__parameters must be a non-empty mapping"
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
    if not os.path.isfile(path):
        return None, f"{path} absent; IR calibration stays as packaged"
    try:
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        return None, f"{path} unreadable, skipped: {exc}"
    problem = overlay_problem(data)
    if problem is not None:
        return None, f"{path} skipped: {problem}"
    return path, f"{path} loaded"
