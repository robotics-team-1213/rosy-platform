"""D-579 capture goal: an existing map goal, or a refusal.

The caller supplies the front-camera status, the localization snapshot, and the
operator point. This module does not read a camera, write a pose, or send a command.
"""
from __future__ import annotations

import math
from typing import Mapping

CAMERA_OFFLINE = "CAMERA_OFFLINE"
NOT_LOCALIZED = "NOT_LOCALIZED"
GOAL_POINT_MISSING = "GOAL_POINT_MISSING"


def capture_goal(*, camera: Mapping, localization, x, y, yaw=0.0) -> dict:
    """Return the existing ``{x, y, yaw}`` goal, or a refusal and no goal body."""
    if not isinstance(camera, Mapping) or not camera.get("available") or camera.get("stale"):
        return _refuse(CAMERA_OFFLINE)
    if not _localized(localization):
        return _refuse(NOT_LOCALIZED)
    if not _finite(x) or not _finite(y) or not _finite(yaw):
        return _refuse(GOAL_POINT_MISSING)
    return {
        "ok": True,
        "refusal": None,
        "goal": {"x": float(x), "y": float(y), "yaw": float(yaw)},
    }


def _localized(localization) -> bool:
    if not isinstance(localization, Mapping):
        return False
    return localization.get("state") == "LOCALIZED" and localization.get("pose_frame") == "map"


def _finite(value) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number)


def _refuse(code: str) -> dict:
    return {"ok": False, "refusal": code, "goal": None}
