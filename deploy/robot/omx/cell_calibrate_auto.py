#!/usr/bin/env python3
"""Online Self-Calibration & Place-and-Look Bias Learning (`cell_calibrate_auto.py`).

Single Responsibility:
  - Select clear pivot points on the live top view (`clear_point`, `auto_pivot_point`, `over_target`, `pivot_near_yaws`).
  - Run online self-calibration before an auto-pick (`self_calibrate`, `carried`).
  - Learn map bias from top-camera place verification (`learn_bias`).
"""
from __future__ import annotations

import math
from pathlib import Path
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_params as prm  # noqa: E402
import cell_pivot  # noqa: E402


def _parent_attr(name: str, default):
    mod = sys.modules.get("cell_calibrate")
    if mod is not None and hasattr(mod, name):
        return getattr(mod, name)
    return default


_CLEAR_GRID_CACHE: dict[float, list[tuple[float, float, float]]] = {}


def _clear_offsets(max_mm: float) -> list[tuple[float, float, float]]:
    cached = _CLEAR_GRID_CACHE.get(max_mm)
    if cached is not None:
        return cached
    out = sorted(
        (math.hypot(float(dx), float(dy)), float(dx), float(dy))
        for dx in np.arange(-max_mm, max_mm + 1, 5.0)
        for dy in np.arange(-max_mm, max_mm + 1, 5.0)
        if math.hypot(float(dx), float(dy)) <= max_mm
    )
    _CLEAR_GRID_CACHE[max_mm] = out
    return out


def clear_point(
    near_xy, mask, roi, inside, to_px, radius_px: int = 36, max_mm: float = 72.0, reach_m: float = 0.23
):
    """The nearest arm point to near_xy whose pivot circle (radius_px around its pixel) is empty in the mask and fully
    on the surface (inside: full-image 0/1 array), within max_mm and reach. None when there is none."""
    nx, ny = float(near_xy[0]), float(near_xy[1])
    rx0, ry0, rx1, ry1 = roi[0], roi[1], roi[2], roi[3]
    r = radius_px
    r1 = r - 1
    reach_sq = reach_m * reach_m
    for _, dx, dy in _clear_offsets(float(max_mm)):
        px_m, py_m = nx + dx * 0.001, ny + dy * 0.001
        if px_m * px_m + py_m * py_m > reach_sq:
            continue
        px = to_px((px_m, py_m))
        if px is None:
            continue
        x, y = int(round(px[0])), int(round(px[1]))
        if x - r < rx0 or y - r < ry0 or x + r >= rx1 or y + r >= ry1:
            continue
        if not (inside[y - r, x - r] and inside[y - r, x + r1] and inside[y + r1, x - r] and inside[y + r1, x + r1]):
            continue
        my, mx = y - ry0, x - rx0
        if (
            mask[my, mx]
            or mask[my - r, mx - r]
            or mask[my - r, mx + r1]
            or mask[my + r1, mx - r]
            or mask[my + r1, mx + r1]
            or mask[my - r, mx]
            or mask[my + r1, mx]
            or mask[my, mx - r]
            or mask[my, mx + r1]
        ):
            continue
        if not mask[my - r : my + r, mx - r : mx + r].any() and inside[y - r : y + r, x - r : x + r].min() == 1:
            return [round(px_m, 4), round(py_m, 4)]
    return None


def map_agrees(record: dict, params=None) -> bool:
    """Marks that disagree fit a map that misses by centimetres: such a map is never saved."""
    return record["loo_error_mm"]["max"] <= prm.get(params, "calibrate.max_loo_mm")


def auto_pivot_point(cell, config, calibration, site, target_xy):
    """clear_point on the live top view: empty of objects, on the site's surface, near the target."""
    import cv2
    import cell_objects
    from cell_observe import predicted_pixel

    img = cell.frame("top")
    roi = tuple(config["sites"][site].get("auto_roi") or (0, 0, img.shape[1], img.shape[0]))
    big = (max(0, roi[0] - 60), max(0, roi[1] - 60), min(img.shape[1], roi[2] + 60), min(img.shape[0], roi[3] + 60))
    site_cfg = config["sites"][site]
    mask = cell_objects.foreground(
        img, big, params=config.get("params"), surface_px=site_cfg.get("surface_px"), surface_lab=site_cfg.get("surface_lab")
    )
    inside = np.zeros(img.shape[:2], np.uint8)
    poly = config["sites"][site].get("surface_px") or [
        [0, 0],
        [img.shape[1] - 1, 0],
        [img.shape[1] - 1, img.shape[0] - 1],
        [0, img.shape[0] - 1],
    ]
    cv2.fillPoly(inside, [np.asarray(poly, np.int32)], 1)
    cp_fn = _parent_attr("clear_point", clear_point)
    return cp_fn(target_xy, mask, big, inside, lambda q: predicted_pixel(config, calibration, site, q))


def over_target(config, site) -> bool:
    """The jaws may be marked right over the target when the pivot height clears the tallest top there."""
    p, s_z = config.get("params"), config["sites"][site].get("surface_z")
    return (
        bool(prm.get(p, "pivot.over_target"))
        and s_z is not None
        and (
            1000 * (cell_pivot.pivot_z_view(config, site) - s_z) - prm.get(p, "pivot.over_top_mm")
            >= prm.get(p, "pivot.over_clear_mm")
        )
    )


def pivot_near_yaws(config, site) -> list:
    """Yaws for a pivot near or over a target."""
    base = config["sites"][site]["yaw_deg"]
    ot_fn = _parent_attr("over_target", over_target)
    offsets = range(-60, 61, 20) if ot_fn(config, site) else (-80, -40, 0, 40, 80, 120)
    return [base + d for d in offsets]


def carried(region: dict) -> bool:
    """A region copied from another site or point, never measured where it stands."""
    return bool(region.get("carried_from")) or str(region.get("source", "")).startswith("carried")


def self_calibrate(
    cell, config, calibration, calibration_path, site, target_xy, objects, work, bias_data, sleep, log
):
    """The bias region near `target_xy`: saved, or a pivot circle at a clear configured point (not in dry runs)."""
    p = config.get("params")
    bias_data = {**bias_data, "regions": [r for r in bias_data["regions"] if not carried(r)]}
    if cell_pivot.bias_at(bias_data, site, target_xy, reach_mm=prm.get(p, "calibrate.bias_near_mm"), params=p):
        return bias_data, None
    pivot = config.get("pivot", {})
    clear_mm, base = pivot.get("clear_mm", prm.get(p, "auto.clear_mm")), config["sites"][site]["yaw_deg"]
    points = [
        q
        for q in pivot.get("points", [])
        if 1000 * math.dist(q, target_xy) <= 0.9 * prm.get(p, "pivot.bias_reach_mm", cell_pivot.BIAS_REACH_MM)
        and all(1000 * math.dist(q, o["raw_m"]) >= clear_mm for o in objects)
    ]
    ot_fn = _parent_attr("over_target", over_target)
    if cell is not None and ot_fn(config, site):
        points = [tuple(target_xy)]
    if not points and cell is not None:
        ap_fn = _parent_attr("auto_pivot_point", auto_pivot_point)
        found = ap_fn(cell, config, calibration, site, target_xy)
        have = cell_pivot.bias_at(bias_data, site, target_xy, params=p)
        if found and have and math.dist(have["point_m"], target_xy) <= math.dist(found, target_xy) + 0.005:
            return bias_data, None
        points = [found] if found else []
    if not points:
        if cell_pivot.bias_at(bias_data, site, target_xy, params=p):
            return bias_data, None
        rec = cell_pivot.map_record(calibration, site) or {}
        ma_fn = _parent_attr("map_agrees", map_agrees)
        if rec.get("loo_error_mm") and ma_fn(rec, p):
            inliers = [tuple(pt["arm_m"]) for pt in (rec.get("points") or [])]
            if inliers and 1000 * min(math.dist(q, target_xy) for q in inliers) <= prm.get(
                p, "pivot.bias_reach_mm", cell_pivot.BIAS_REACH_MM
            ):
                return bias_data, None
        return bias_data, "no clear pivot point within reach of the object"
    chosen = min(points, key=lambda q: math.dist(q, target_xy))
    if any(r["site"] == site and math.dist(r["point_m"], chosen) <= 0.010 for r in bias_data["regions"]):
        return bias_data, None
    if cell is None:
        return bias_data, f"needs a pivot at {chosen}"
    yaws = pivot.get("yaws", [base + d for d in (-80, -40, 0, 40, 80, 120)])
    result = cell_pivot.pivot_calibrate(cell, config, chosen, yaws, calibration, site, work, sleep, log)
    if result["result"] != "calibrated":
        return bias_data, f"pivot: {result['result']}"
    cell_pivot.save_bias(cell_pivot.bias_path(calibration_path), result["bias"], p)
    return cell_pivot.load_bias(cell_pivot.bias_path(calibration_path), p), None


def learn_bias(config: dict, calibration_path, site: str, place_xy, verify: dict) -> dict | None:
    """Learn map bias from top-camera place verification."""
    p = config.get("params")
    if not prm.get(p, "auto.bias_from_place") or not verify.get("found") or "seen_bias_mm" not in verify:
        return None
    seen, used = verify["seen_bias_mm"], verify["used_bias_mm"]
    try:
        for value in (seen, used):
            cell_pivot.validate_bias({"point_m": place_xy, "bias_mm": value}, p)
    except ValueError:
        return None
    if math.dist(seen, used) > prm.get(p, "auto.bias_learn_max_mm"):
        return None
    region = {
        "site": site,
        "point_m": list(place_xy),
        "bias_mm": seen,
        "measured": time.strftime("%Y-%m-%d"),
        "source": "place-and-look: the arm set the box here and the top camera saw it",
    }
    cell_pivot.save_bias(cell_pivot.bias_path(calibration_path), region, p)
    return region
