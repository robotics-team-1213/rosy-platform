#!/usr/bin/env python3
"""Pre-defined target zones and deterministic zone checks for `cell_area_xyz` (D-1014).

Split out of `cell_area_xyz.py` at its 600-line cap (D-766 2, the
`runner_strain.py` precedent): the side/top ROI tables, the Isaac-Sim-style
zone evaluation, the side-view gripper offset, and task outcome verification.
Closed-loop pick recovery and live top/side perception live in `cell_area_recovery.py`
and are re-exported here unchanged.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

# Pre-defined deterministic 2D target zones (x0, y0, x1, y1) in Side View (640x480) and Top View (640x480)
# modelled after Isaac Sim target volume checks: if fill_ratio or centroid offset exceeds tolerance, mark as
# failure (`verified = False`) and enter `recovery_mode`.
SIDE_ROI_BY_COL_TIER: dict[tuple[int, int], tuple[int, int, int, int]] = {
    (1, 1): (160, 232, 224, 265),
    (1, 2): (160, 175, 224, 232),
    (1, 3): (160, 115, 224, 175),
    (2, 1): (224, 241, 294, 275),
    (2, 2): (224, 176, 294, 240),
    (2, 3): (224, 112, 294, 180),
    (3, 1): (330, 248, 415, 315),
    (3, 2): (330, 185, 415, 248),
    (3, 3): (330, 120, 415, 185),
}

SIDE_COL_CENTER_U: dict[int, float] = {1: 205.0, 2: 254.0, 3: 330.0}
SIDE_M_PER_PX: float = 0.00070  # Measured 3-point calibration on rosy-arm-cell side camera (u=190->0.1280m, u=232->0.1551m, u=264->0.1796m)

TOP_ROI_BY_COL_ROW: dict[tuple[int, int], tuple[int, int, int, int]] = {
    (1, 1): (315, 165, 368, 270),
    (2, 1): (370, 165, 420, 270),
    (3, 1): (425, 165, 480, 270),
    (1, 2): (315, 271, 368, 380),
    (2, 2): (370, 271, 420, 380),
    (3, 2): (425, 271, 480, 380),
}


def classify_container_orientation(xs: np.ndarray, ys: np.ndarray) -> dict[str, Any]:
    """Classify 2D container pixel distribution into vertical (`세로`, N-S), horizontal (`가로`, E-W), or diagonal (`대각선`)."""
    if len(xs) < 10:
        return {
            "span_u_px": 0.0,
            "span_v_px": 0.0,
            "aspect_u_over_v": 1.0,
            "long_axis_deg": -90.0,
            "orientation_class": "unknown",
        }
    u5, u95 = np.percentile(xs, [5, 95])
    v5, v95 = np.percentile(ys, [5, 95])
    span_u = round(max(1.0, float(u95 - u5)), 1)
    span_v = round(max(1.0, float(v95 - v5)), 1)
    aspect = round(span_u / span_v, 3)

    xf = xs.astype(np.float64)
    yf = -ys.astype(np.float64)
    dx = xf - xf.mean()
    dy = yf - yf.mean()
    sxx = float(np.dot(dx, dx))
    syy = float(np.dot(dy, dy))
    sxy = float(np.dot(dx, dy))
    raw_deg = math.degrees(0.5 * math.atan2(2.0 * sxy, sxx - syy))
    if raw_deg > 0.0:
        raw_deg -= 180.0
    long_axis_deg = round(raw_deg, 1)

    if aspect <= 0.80:
        oclass = "vertical_ns"
    elif aspect >= 1.25:
        oclass = "horizontal_ew"
    elif abs(abs(long_axis_deg) - 45.0) <= 22.0 or abs(abs(long_axis_deg) - 135.0) <= 22.0:
        oclass = "diagonal"
    else:
        oclass = "vertical_ns" if span_v >= span_u else "horizontal_ew"

    return {
        "span_u_px": span_u,
        "span_v_px": span_v,
        "aspect_u_over_v": aspect,
        "long_axis_deg": long_axis_deg,
        "orientation_class": oclass,
    }


def normalize_pick_yaw_deg(yaw_deg: float, x_m: float = 0.15, y_m: float = 0.0) -> float:
    """Resolve 180-degree parallel-jaw symmetry so wrist_roll stays safely inside [10.0, 85.0] units (>= 5.0 cable limit)
    while aligning the jaws across the container's 30 mm short side (vertical `세로`, horizontal `가로`, or diagonal `대각선`)."""
    pan_deg = float(np.degrees(np.arctan2(y_m, max(0.04, x_m))))
    candidates = [float(yaw_deg), float(yaw_deg) - 180.0, float(yaw_deg) + 180.0]
    best_yaw = float(yaw_deg)
    best_cost = 1e9
    for cand in candidates:
        rel_deg = pan_deg - cand
        while rel_deg > 180.0:
            rel_deg -= 360.0
        while rel_deg < -180.0:
            rel_deg += 360.0
        est_wrist_roll = rel_deg * (100.0 / 180.0)
        if 8.0 <= est_wrist_roll <= 88.0:
            cost = abs(est_wrist_roll - 48.1)
            if cost < best_cost:
                best_cost = cost
                best_yaw = cand
    while best_yaw > 180.0:
        best_yaw -= 360.0
    while best_yaw <= -180.0:
        best_yaw += 360.0
    return round(best_yaw, 1)


def evaluate_zone(
    img: np.ndarray | None,
    roi: tuple[int, int, int, int],
    *,
    tol_u_px: float = 20.0,
    tol_v_px: float = 22.0,
    min_fill: float = 0.30,
    expected_orientation: str | None = None,
) -> dict[str, Any]:
    """Deterministic zone check (Isaac-Sim style): measure warm container fill ratio, centroid deviation, and orientation
    (`vertical_ns` 세로 vs `horizontal_ew` 가로 vs `diagonal` 대각선) inside pre-defined target zone `roi = (x0, y0, x1, y1)`."""
    x0, y0, x1, y1 = roi
    u_center = 0.5 * (x0 + x1)
    v_center = 0.5 * (y0 + y1)
    if img is None or not hasattr(img, "shape") or len(img.shape) < 3:
        return {
            "roi": list(roi),
            "fill_ratio": 0.0,
            "centroid_px": None,
            "offset_px": None,
            "within_zone": False,
            "orientation_ok": False,
        }
    import cv2

    h, w = img.shape[:2]
    crop = img[max(0, y0):min(h, y1), max(0, x0):min(w, x1)]
    if crop.size == 0:
        return {"roi": list(roi), "fill_ratio": 0.0, "centroid_px": None, "offset_px": None, "within_zone": False, "orientation_ok": False}
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    orange_or_top_yellow = ((hue <= 38) | (hue >= 158)) & (sat >= 65) & (val >= 90)
    side_yellow = (hue >= 35) & (hue <= 75) & (sat >= 16) & (sat <= 115) & (val >= 140) & (val <= 228)
    warm = orange_or_top_yellow | side_yellow
    fill = round(float(warm.mean()), 3)
    ys, xs = np.where(warm)
    if len(xs) == 0:
        return {
            "roi": list(roi),
            "fill_ratio": fill,
            "centroid_px": None,
            "offset_px": None,
            "within_zone": False,
            "orientation_ok": False,
            "orientation_class": "unknown",
        }
    uc = round(float(x0 + xs.mean()), 1)
    vc = round(float(y0 + ys.mean()), 1)
    du = round(uc - u_center, 1)
    dv = round(vc - v_center, 1)
    orient = classify_container_orientation(xs, ys)
    orientation_ok = True
    if expected_orientation == "vertical_ns":
        orientation_ok = orient["orientation_class"] != "horizontal_ew" and orient["aspect_u_over_v"] <= 1.20
    elif expected_orientation == "horizontal_ew":
        orientation_ok = orient["orientation_class"] == "horizontal_ew"
    within = bool(fill >= min_fill and abs(du) <= tol_u_px and abs(dv) <= tol_v_px and orientation_ok)
    return {
        "roi": list(roi),
        "fill_ratio": fill,
        "centroid_px": [uc, vc],
        "offset_px": [du, dv],
        "tol_px": [tol_u_px, tol_v_px],
        "within_zone": within,
        "orientation_ok": orientation_ok,
        **orient,
    }


def measure_side_gripper_zone_offset(
    side_img: np.ndarray | None,
    before_side: np.ndarray | None,
    col: int,
    *,
    tol_u_px: float = 12.0,
) -> dict[str, Any]:
    """Measure the horizontal gripper position `u_gripper` in the side view upper band (`v in [70, 165]`) against the
    pre-defined column center `SIDE_COL_CENTER_U[col]`."""
    target_u = float(SIDE_COL_CENTER_U.get(col, 326.9))
    if side_img is None or before_side is None or not hasattr(side_img, "shape") or side_img.shape != before_side.shape:
        return {"found": False, "target_u_px": target_u}
    d = side_img[70:165, 160:390].astype(np.int32) - before_side[70:165, 160:390].astype(np.int32)
    diff = d[:, :, 0] * d[:, :, 0] + d[:, :, 1] * d[:, :, 1] + d[:, :, 2] * d[:, :, 2] > 1024
    ys, xs = np.where(diff)
    if len(xs) < 40:
        return {"found": False, "target_u_px": target_u}
    n = len(xs)
    mid = n >> 1
    med_x = float(np.partition(xs, mid)[mid]) if (n & 1) else 0.5 * float(np.partition(xs, (mid - 1, mid))[mid - 1] + np.partition(xs, (mid - 1, mid))[mid])
    u_gripper = round(160.0 + med_x, 1)
    du_px = round(target_u - u_gripper, 1)
    dx_m = round(du_px * SIDE_M_PER_PX, 5)
    return {
        "found": True,
        "gripper_u_px": u_gripper,
        "target_u_px": target_u,
        "du_px": du_px,
        "dx_m": dx_m,
        "within_zone": abs(du_px) <= tol_u_px,
    }


def warm_container_ratio(img: np.ndarray | None, roi: tuple[int, int, int, int]) -> float:
    """Fraction of pixels inside `roi` (x0, y0, x1, y1) matching warm orange/yellow container HSV."""
    return float(evaluate_zone(img, roi)["fill_ratio"])


def verify_stack_outcome(
    *,
    before_side: np.ndarray | None,
    after_side: np.ndarray | None,
    before_top: np.ndarray | None = None,
    after_top: np.ndarray | None = None,
    pick: dict[str, Any],
    place: dict[str, Any],
) -> dict[str, Any]:
    """Deterministic zone-based task outcome verification (Isaac-Sim style) using pre-defined `side` and `top` target zones."""
    if after_side is None:
        return {
            "verified": True,
            "recovery_mode": None,
            "basis": "telemetry_only",
            "reason": "no side camera frame provided; verified by runner grasp/release telemetry",
        }
    pick_col = int(pick.get("col") or 3)
    pick_tier = int(pick.get("tier") or 2)
    place_col = int(place.get("col") or 2)
    place_tier = int(place.get("tier") or 3)
    place_row = int(place.get("row") or 1)

    pick_roi = SIDE_ROI_BY_COL_TIER.get((pick_col, pick_tier), (295, 190, 365, 255))
    place_roi = SIDE_ROI_BY_COL_TIER.get((place_col, place_tier), (226, 120, 292, 195))

    before_pick_zone = evaluate_zone(before_side, pick_roi) if before_side is not None else {"fill_ratio": None}
    after_pick_zone = evaluate_zone(after_side, pick_roi)
    before_place_zone = evaluate_zone(before_side, place_roi) if before_side is not None else {"fill_ratio": 0.0}
    after_place_zone = evaluate_zone(after_side, place_roi, tol_u_px=20.0, tol_v_px=24.0, min_fill=0.30)

    if not after_place_zone["within_zone"] and after_side is not None and place_tier >= 2:
        live_base = perceive_live_base(before_top if before_top is not None else after_top, before_side if before_side is not None else after_side, preferred_col=place_col)
        dyn_side_roi = (live_base.get("side_roi_by_tier") or {}).get(place_tier)
        if dyn_side_roi is not None:
            dyn_after = evaluate_zone(after_side, dyn_side_roi, tol_u_px=22.0, tol_v_px=24.0, min_fill=0.28)
            dyn_before = evaluate_zone(before_side, dyn_side_roi) if before_side is not None else {"fill_ratio": 0.0}
            if dyn_after["within_zone"] or dyn_after["fill_ratio"] > after_place_zone["fill_ratio"]:
                after_place_zone = dyn_after
                before_place_zone = dyn_before

    before_pick_fill = before_pick_zone.get("fill_ratio")
    after_pick_fill = float(after_pick_zone["fill_ratio"])
    before_place_fill = float(before_place_zone.get("fill_ratio") or 0.0)
    after_place_fill = float(after_place_zone["fill_ratio"])

    target_present = bool(after_place_zone["within_zone"] and (after_place_fill - before_place_fill) >= 0.20)
    source_vacated = after_pick_fill <= 0.35 or (before_pick_fill is not None and (before_pick_fill - after_pick_fill) >= 0.25)
    if not source_vacated and after_top is not None:
        pick_row = int(pick.get("row") or 1)
        pick_top_roi = (
            (355, 40, 415, 160)
            if str(pick.get("area_id") or "") == "belt"
            else TOP_ROI_BY_COL_ROW.get((pick_col, pick_row))
        )
        if pick_top_roi is not None:
            before_pick_top = evaluate_zone(before_top, pick_top_roi)["fill_ratio"] if before_top is not None else None
            after_pick_top = evaluate_zone(after_top, pick_top_roi)["fill_ratio"]
            if after_pick_top <= 0.25 or (before_pick_top is not None and (before_pick_top - after_pick_top) >= 0.18):
                source_vacated = True

    top_zone_info = None
    top_orientation_ok = True
    expected_orient = "vertical_ns" if abs(float(place.get("yaw_deg", -90.0)) + 90.0) <= 25.0 else None
    if after_top is not None:
        top_roi = TOP_ROI_BY_COL_ROW.get((place_col, place_row), (316, 160, 374, 270))
        top_zone_info = evaluate_zone(
            after_top,
            top_roi,
            tol_u_px=24.0,
            tol_v_px=40.0,
            min_fill=0.15,
            expected_orientation=expected_orient,
        )
        if not top_zone_info["within_zone"]:
            live_base_top = perceive_live_base(after_top, after_side, preferred_col=place_col)
            dyn_top_roi = live_base_top.get("top_roi")
            if dyn_top_roi is not None:
                dyn_top_info = evaluate_zone(after_top, dyn_top_roi, tol_u_px=24.0, tol_v_px=40.0, min_fill=0.15, expected_orientation=expected_orient)
                if dyn_top_info["within_zone"] or dyn_top_info.get("fill_ratio", 0.0) > top_zone_info.get("fill_ratio", 0.0):
                    top_zone_info = dyn_top_info
        if not top_zone_info["within_zone"] and top_zone_info.get("fill_ratio", 0.0) < 0.15:
            alt_top_zone = evaluate_zone(
                after_top,
                place_roi,
                tol_u_px=24.0,
                tol_v_px=30.0,
                min_fill=0.20,
                expected_orientation=expected_orient,
            )
            if alt_top_zone["within_zone"] or alt_top_zone.get("fill_ratio", 0.0) >= 0.20:
                top_zone_info = alt_top_zone
        if top_zone_info and top_zone_info.get("fill_ratio", 0.0) >= 0.15:
            top_orientation_ok = bool(top_zone_info.get("orientation_ok", True))

    verified = bool(target_present and source_vacated and top_orientation_ok)
    if verified:
        recovery_mode = None
    elif not source_vacated:
        recovery_mode = "re_pick_and_re_place"
    elif not top_orientation_ok:
        recovery_mode = "re_orient_and_re_place"
    else:
        recovery_mode = "re_align_place_zone"

    return {
        "verified": verified,
        "recovery_mode": recovery_mode,
        "basis": "predefined_side_and_top_target_zones",
        "pick_slot": {
            "col": pick_col,
            "tier": pick_tier,
            "zone": after_pick_zone,
            "before_fill": before_pick_fill,
            "after_fill": after_pick_fill,
            "vacated": source_vacated,
        },
        "place_slot": {
            "col": place_col,
            "tier": place_tier,
            "zone": after_place_zone,
            "top_zone": top_zone_info,
            "before_fill": before_place_fill,
            "after_fill": after_place_fill,
            "present": target_present,
        },
        "reason": (
            f"verified tier={place_tier} stack inside target zone col={place_col} (fill {before_place_fill:.2f} -> {after_place_fill:.2f}, offset_px={after_place_zone.get('offset_px')}) and vacated source col={pick_col} tier={pick_tier} (fill -> {after_pick_fill:.2f})"
            if verified
            else f"target zone check failed (recovery_mode={recovery_mode}): place col={place_col} tier={place_tier} fill={after_place_fill:.2f} within_zone={after_place_zone['within_zone']} offset_px={after_place_zone.get('offset_px')}, pick col={pick_col} tier={pick_tier} fill={after_pick_fill:.2f} vacated={source_vacated}"
        ),
    }


from cell_area_recovery import (  # noqa: E402,F401  (re-exported: existing importers are unchanged)
    diagnose_and_recover_pick,
    perceive_live_base,
    perceive_live_pick_candidates,
    top_pixel_to_arm_xy_vanishing,
)
