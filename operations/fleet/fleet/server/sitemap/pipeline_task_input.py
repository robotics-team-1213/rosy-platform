"""Validate cell task input before it changes the Fleet ledger in memory."""
from __future__ import annotations

import json
import math

from fastapi import HTTPException


def finite_json_value(value) -> bool:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        return False
    return True


def checked_json_value(value) -> None:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        raise HTTPException(422, detail={"code": "INVALID_PIPELINE_NUMBER"}) from None


def checked_finite_float(value) -> float:
    try:
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("nonfinite number")
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(422, detail={"code": "INVALID_PIPELINE_NUMBER"}) from None
    return result


def checked_task_pose(spec: dict, station) -> tuple[int, dict[str, float]]:
    try:
        json.dumps(spec, allow_nan=False)
        if spec.get("cell_id") == "cell_ab" and "tier" not in spec:
            raise ValueError("missing cell_ab tier")
        tier = spec.get("tier", 1)
        if type(tier) is not int or tier not in (1, 2, 3):
            raise ValueError("invalid cell task tier")
        pose = {key: float(spec.get(key, default)) for key, default in (
            ("x", station.station_xy[0]), ("y", station.station_xy[1]), ("yaw", 0.0),
        )}
        if not all(math.isfinite(value) for value in pose.values()):
            raise ValueError("nonfinite task pose")
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(422, detail={"code": "INVALID_CELL_TASK_INPUT"}) from None
    return tier, pose
