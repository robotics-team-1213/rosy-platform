#!/usr/bin/env python3
"""Reach limits of an auto-pick candidate (moved from cell_auto_pick_plan.py, which re-exports them): the plan's joint1
pan limit, the park reach, and the vehicle move that would bring an object within the park reach."""
from __future__ import annotations

import math


def past_pan_limit(config: dict, point_m) -> float | None:
    """The pan (deg) to a point outside the plan's joint1 limit, else None. 2026-11-13 arm_s: a box at -161 deg (limit 149) was
    refused as packed and the push meant for packed boxes could never reach it either.
    shortcut: the pan alone, from the base axis; radius and height are left to the planner's IK, which runs later."""
    limits = (config.get("plan") or {}).get("limits", {}).get("joints_rad", {}).get("joint1")
    if not limits:
        return None
    pan = math.atan2(point_m[1], point_m[0])
    return None if limits[0] <= pan <= limits[1] else round(math.degrees(pan), 1)


def past_park_reach(config: dict, point_m) -> float | None:
    """The reach (mm) to a point past the plan's park reach, else None. 2026-11-14 arm_s, measured in free air at pan 120:
    the park from above_pick folded at 120-186 mm and failed at 192 mm every time (shoulder_lift contact, the arm then
    sagging onto what it hovered over); a slow lift first and then the park folded it."""
    limit = (config.get("plan") or {}).get("limits", {}).get("park_reach_m")
    reach = math.hypot(point_m[0], point_m[1])
    return round(reach * 1000) if limit and reach > limit else None


def reach_fix(config: dict, raw_m, reach_mm: int) -> dict:
    """What the vehicle must do to fit the object within the park reach: move it toward the arm base (arm frame)."""
    limit = round(config["plan"]["limits"]["park_reach_m"] * 1000)
    length = (reach_mm - limit + 30) / 1000  # 30 mm margin past the limit
    r = math.hypot(raw_m[0], raw_m[1])
    return {"object_arm_xy_m": [raw_m[0], raw_m[1]], "reach_mm": reach_mm, "limit_mm": limit,
            "need_arm_dxdy_m": [round(-raw_m[0] / r * length, 4), round(-raw_m[1] / r * length, 4)]}


def reach_fix_of(refused: list) -> dict:
    """{"reach_fix": ...} of the first refusal, only when every catalogue object was refused for reach alone."""
    seen = [r for r in refused if r.get("object")]
    fixes = [r["reach_fix"] for r in seen if "reach_fix" in r]
    return {"reach_fix": fixes[0]} if seen and len(fixes) == len(seen) else {}
