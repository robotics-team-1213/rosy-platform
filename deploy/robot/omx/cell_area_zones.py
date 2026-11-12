#!/usr/bin/env python3
"""Pre-defined target zones, Z-mm stack outcome verification, and deterministic zone checks for `cell_area_xyz` (D-1014).

Single Responsibility:
  - Side/Top/TempPlate ROI tables (`SIDE_ROI_BY_COL_TIER`, `TOP_ROI_BY_COL_ROW`, `TEMP_PLATE_TOP_ROI_BY_LANE`).
  - Isaac-Sim-style zone evaluation (`evaluate_zone`, `classify_container_orientation`, `normalize_pick_yaw_deg`).
  - Side-view gripper offset (`measure_side_gripper_zone_offset`) and stack outcome verification
    (`verify_stack_outcome`, `verify_stack_outcome_z_mm`).
  - Closed-loop pick recovery and live top/side perception live in `cell_area_recovery.py` and are re-exported here.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from omx_adapter.z_profile import (
    TIER_GRASP_Z_MM, TIER_MID_Z_MM, TIER_TOP_Z_MM, SideViewZProfile, evaluate_signed_tier_residual_mm,
)
from cell_spec_recovery_fsm import evaluate_execution_gate, select_recovery_skill
from cell_z_profile import (
    SIDE_COL_U_BOUNDS, detect_side_self_profile_landmarks, measure_side_gripper_pose_mm, perceive_slot_z_mm,
)

SIDE_ROI_BY_COL_TIER: dict[tuple[int, int], tuple[int, int, int, int]] = {
    (1, 1): (175, 252, 225, 315),
    (1, 2): (175, 190, 225, 252),
    (1, 3): (175, 120, 225, 190),
    (2, 1): (226, 252, 296, 315),
    (2, 2): (226, 190, 296, 252),
    (2, 3): (226, 120, 296, 195),
    (3, 1): (295, 252, 365, 315),
    (3, 2): (295, 190, 365, 252),
    (3, 3): (295, 120, 365, 190),
}

SIDE_COL_CENTER_U: dict[int, float] = {1: 205.0, 2: 254.0, 3: 300.0}
SIDE_M_PER_PX: float = 0.00070

TOP_ROI_BY_COL_ROW: dict[tuple[int, int], tuple[int, int, int, int]] = {
    (1, 1): (315, 165, 368, 270),
    (2, 1): (370, 165, 420, 270),
    (3, 1): (425, 165, 480, 270),
    (1, 2): (315, 271, 368, 380),
    (2, 2): (370, 271, 420, 380),
    (3, 2): (425, 271, 480, 380),
}

TEMP_PLATE_TOP_ROI_BY_LANE: dict[int, tuple[int, int, int, int]] = {
    1: (240, 365, 292, 433),
    2: (182, 372, 234, 440),
    3: (124, 362, 176, 430),
}


def classify_container_orientation(xs: np.ndarray, ys: np.ndarray) -> dict[str, Any]:
    """Classify 2D container pixel distribution into vertical (`세로`, N-S), horizontal (`가로`, E-W), or diagonal (`대각선`)."""
    if len(xs) < 10:
        return {"span_u_px": 0.0, "span_v_px": 0.0, "aspect_u_over_v": 1.0, "long_axis_deg": -90.0, "orientation_class": "unknown"}
    u5, u95 = np.percentile(xs, [5, 95])
    v5, v95 = np.percentile(ys, [5, 95])
    span_u = round(max(1.0, float(u95 - u5)), 1)
    span_v = round(max(1.0, float(v95 - v5)), 1)
    aspect = round(span_u / span_v, 3)

    xf = xs.astype(np.float64)
    yf = -ys.astype(np.float64)
    dx, dy = xf - xf.mean(), yf - yf.mean()
    sxx, syy, sxy = float(np.dot(dx, dx)), float(np.dot(dy, dy)), float(np.dot(dx, dy))
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
        "span_u_px": span_u, "span_v_px": span_v, "aspect_u_over_v": aspect,
        "long_axis_deg": long_axis_deg, "orientation_class": oclass,
    }


def normalize_pick_yaw_deg(yaw_deg: float, x_m: float = 0.15, y_m: float = 0.0) -> float:
    """Resolve 180-degree parallel-jaw symmetry so wrist_roll stays safely inside [10.0, 85.0] units."""
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
    """Deterministic zone check (Isaac-Sim style): measure warm container fill ratio, centroid deviation, and orientation."""
    x0, y0, x1, y1 = roi
    u_center, v_center = 0.5 * (x0 + x1), 0.5 * (y0 + y1)
    empty = {"roi": list(roi), "fill_ratio": 0.0, "centroid_px": None, "offset_px": None, "within_zone": False, "orientation_ok": False}
    if img is None or not hasattr(img, "shape") or len(img.shape) < 3:
        return empty
    import cv2

    h, w = img.shape[:2]
    crop = img[max(0, y0):min(h, y1), max(0, x0):min(w, x1)]
    if crop.size == 0:
        return empty
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    orange_or_top_yellow = ((hue <= 38) | (hue >= 158)) & (sat >= 65) & (val >= 90)
    side_yellow = (hue >= 35) & (hue <= 75) & (sat >= 16) & (sat <= 115) & (val >= 140) & (val <= 228)
    warm = orange_or_top_yellow | side_yellow
    fill = round(float(warm.mean()), 3)
    ys, xs = np.where(warm)
    if len(xs) == 0:
        return {**empty, "fill_ratio": fill, "orientation_class": "unknown"}
    uc, vc = round(float(x0 + xs.mean()), 1), round(float(y0 + ys.mean()), 1)
    du, dv = round(uc - u_center, 1), round(vc - v_center, 1)
    orient = classify_container_orientation(xs, ys)
    orientation_ok = True
    if expected_orientation == "vertical_ns":
        orientation_ok = orient["orientation_class"] != "horizontal_ew" and orient["aspect_u_over_v"] <= 1.20
    elif expected_orientation == "horizontal_ew":
        orientation_ok = orient["orientation_class"] == "horizontal_ew"
    within = bool(fill >= min_fill and abs(du) <= tol_u_px and abs(dv) <= tol_v_px and orientation_ok)
    auto_pts = detect_side_self_profile_landmarks(img)
    side_prof = SideViewZProfile.fit_from_landmarks(auto_pts) if len(auto_pts) >= 2 else SideViewZProfile()
    v_top = round(float(y0 + np.percentile(ys, 5)), 1)
    z_centroid_mm = side_prof.v_to_z_mm(vc)
    z_top_mm = side_prof.v_to_z_mm(v_top)
    z_target_mid_mm = side_prof.v_to_z_mm(v_center)
    return {
        "roi": list(roi), "fill_ratio": fill, "centroid_px": [uc, vc], "top_edge_v_px": v_top,
        "offset_px": [du, dv], "tol_px": [tol_u_px, tol_v_px], "centroid_z_mm": z_centroid_mm,
        "top_z_mm": z_top_mm, "target_mid_z_mm": z_target_mid_mm,
        "dz_mm": round(z_centroid_mm - z_target_mid_mm, 2), "within_zone": within,
        "orientation_ok": orientation_ok, **orient,
    }


def measure_side_gripper_zone_offset(
    side_img: np.ndarray | None,
    before_side: np.ndarray | None,
    col: int,
    *,
    tol_u_px: float = 12.0,
    expected_z_mm: float | None = None,
    joint_state_deg: list[float] | None = None,
    z_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Measure the horizontal (`u_gripper -> dx_m/dx_mm`) and vertical (`v_gripper -> gripper_z_mm, dz_mm`) gripper pose."""
    target_u = float(SIDE_COL_CENTER_U.get(col, 326.9))
    return measure_side_gripper_pose_mm(
        side_img, before_side, col, target_u_px=target_u, u_m_per_px=SIDE_M_PER_PX,
        expected_z_mm=expected_z_mm, joint_state_deg=joint_state_deg, z_profile=z_profile, tol_u_px=tol_u_px,
    )


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
            "verified": True, "recovery_mode": None, "basis": "telemetry_only",
            "reason": "no side camera frame provided; verified by runner grasp/release telemetry",
        }
    pick_area = str(pick.get("area") or pick.get("area_id") or "pallet").strip().lower()
    place_area = str(place.get("area") or place.get("area_id") or "pallet").strip().lower()
    pick_is_temp = pick_area.startswith("temp_plate") or pick_area.startswith("tmp-")
    place_is_temp = place_area.startswith("temp_plate") or place_area.startswith("tmp-")
    pick_col, pick_row, pick_tier = int(pick.get("col") or 3), int(pick.get("row") or 1), int(pick.get("tier") or 2)
    place_col, place_row, place_tier = int(place.get("col") or 2), int(place.get("row") or 1), int(place.get("tier") or 3)
    same_slot = bool(pick_area == place_area and pick_col == place_col and pick_row == place_row and pick_tier == place_tier)
    same_side_band = bool(pick_area == place_area and pick_col == place_col and pick_tier == place_tier and pick_row != place_row)

    pick_roi = SIDE_ROI_BY_COL_TIER.get((pick_col, pick_tier), (295, 190, 365, 255))
    place_roi = SIDE_ROI_BY_COL_TIER.get((place_col, place_tier), (226, 120, 292, 195))
    auto_landmarks = detect_side_self_profile_landmarks(after_side)
    if len(auto_landmarks) >= 2:
        live_prof = SideViewZProfile.fit_from_landmarks(auto_landmarks)
        p_band, q_band = live_prof.tier_band_mm(pick_tier), live_prof.tier_band_mm(place_tier)
        pu0, pu1 = SIDE_COL_U_BOUNDS.get(pick_col, (239, 305))
        qu0, qu1 = SIDE_COL_U_BOUNDS.get(place_col, (239, 305))
        pick_roi = (pu0, int(p_band["v_top_px"]) - 4, pu1, int(p_band["v_bottom_px"]) + 4)
        place_roi = (qu0, int(q_band["v_top_px"]) - 4, qu1, int(q_band["v_bottom_px"]) + 4)

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
                after_place_zone, before_place_zone = dyn_after, dyn_before

    before_pick_fill = before_pick_zone.get("fill_ratio")
    after_pick_fill = float(after_pick_zone["fill_ratio"])
    before_place_fill = float(before_place_zone.get("fill_ratio") or 0.0)
    after_place_fill = float(after_place_zone["fill_ratio"])

    target_present = bool(after_place_zone["within_zone"]) if same_slot else bool(after_place_zone["within_zone"] and (after_place_fill - before_place_fill) >= 0.20)
    source_vacated = True if same_slot else (after_pick_fill <= 0.35 or (before_pick_fill is not None and (before_pick_fill - after_pick_fill) >= 0.25))
    if not source_vacated and after_top is not None:
        pick_top_roi = (355, 40, 415, 160) if pick_area == "belt" else (TEMP_PLATE_TOP_ROI_BY_LANE.get(pick_col) if pick_is_temp else TOP_ROI_BY_COL_ROW.get((pick_col, pick_row)))
        if pick_top_roi is not None:
            b_pt = evaluate_zone(before_top, pick_top_roi)["fill_ratio"] if before_top is not None else None
            a_pt = evaluate_zone(after_top, pick_top_roi)["fill_ratio"]
            if a_pt <= 0.25 or (b_pt is not None and (b_pt - a_pt) >= 0.15):
                source_vacated = True

    top_zone_info = None
    top_orientation_ok = True
    expected_orient = "vertical_ns" if (not place_is_temp and abs(float(place.get("yaw_deg", -90.0)) + 90.0) <= 25.0) else None
    if after_top is not None:
        top_roi = TEMP_PLATE_TOP_ROI_BY_LANE.get(place_col, (182, 372, 234, 440)) if place_is_temp else TOP_ROI_BY_COL_ROW.get((place_col, place_row), (316, 160, 374, 270))
        top_zone_info = evaluate_zone(after_top, top_roi, tol_u_px=24.0, tol_v_px=40.0, min_fill=0.15, expected_orientation=expected_orient)
        if (same_side_band or pick_is_temp or place_is_temp) and before_top is not None:
            b_q_top = evaluate_zone(before_top, top_roi, min_fill=0.15)
            if top_zone_info["within_zone"] and (float(top_zone_info["fill_ratio"]) - float(b_q_top["fill_ratio"])) >= 0.15:
                target_present = True
        if not top_zone_info["within_zone"] and not place_is_temp:
            live_base_top = perceive_live_base(after_top, after_side, preferred_col=place_col)
            dyn_top_roi = live_base_top.get("top_roi")
            if dyn_top_roi is not None:
                dyn_top_info = evaluate_zone(after_top, dyn_top_roi, tol_u_px=24.0, tol_v_px=40.0, min_fill=0.15, expected_orientation=expected_orient)
                if dyn_top_info["within_zone"] or dyn_top_info.get("fill_ratio", 0.0) > top_zone_info.get("fill_ratio", 0.0):
                    top_zone_info = dyn_top_info
        if not top_zone_info["within_zone"] and top_zone_info.get("fill_ratio", 0.0) < 0.15:
            alt_top_zone = evaluate_zone(after_top, place_roi, tol_u_px=24.0, tol_v_px=30.0, min_fill=0.20, expected_orientation=expected_orient)
            if alt_top_zone["within_zone"] or alt_top_zone.get("fill_ratio", 0.0) >= 0.20:
                top_zone_info = alt_top_zone
        if top_zone_info and top_zone_info.get("fill_ratio", 0.0) >= 0.15:
            top_orientation_ok = bool(top_zone_info.get("orientation_ok", True))

    verified = bool(target_present and source_vacated and top_orientation_ok)
    recovery_mode = None if verified else ("re_pick_and_re_place" if not source_vacated else ("re_orient_and_re_place" if not top_orientation_ok else "re_align_place_zone"))
    return {
        "verified": verified, "recovery_mode": recovery_mode, "basis": "predefined_side_and_top_target_zones",
        "pick_slot": {"col": pick_col, "tier": pick_tier, "zone": after_pick_zone, "before_fill": before_pick_fill, "after_fill": after_pick_fill, "vacated": source_vacated},
        "place_slot": {
            "col": place_col, "tier": place_tier, "zone": after_place_zone, "top_zone": top_zone_info,
            "before_fill": before_place_fill, "after_fill": after_place_fill, "present": target_present,
            "expected_top_z_mm": TIER_TOP_Z_MM.get(place_tier, 30.0), "expected_mid_z_mm": TIER_MID_Z_MM.get(place_tier, 15.0),
            "expected_grasp_z_mm": TIER_GRASP_Z_MM.get(place_tier, 7.4), "measured_top_z_mm": after_place_zone.get("top_z_mm"),
            "measured_centroid_z_mm": after_place_zone.get("centroid_z_mm"), "dz_mm": after_place_zone.get("dz_mm"),
        },
        "reason": (
            f"verified tier={place_tier} stack inside target zone col={place_col} (fill {before_place_fill:.2f} -> {after_place_fill:.2f}, offset_px={after_place_zone.get('offset_px')}) and vacated source col={pick_col} tier={pick_tier} (fill -> {after_pick_fill:.2f})"
            if verified
            else f"target zone check failed (recovery_mode={recovery_mode}): place col={place_col} tier={place_tier} fill={after_place_fill:.2f} within_zone={after_place_zone['within_zone']} offset_px={after_place_zone.get('offset_px')}, pick col={pick_col} tier={pick_tier} fill={after_pick_fill:.2f} vacated={source_vacated}"
        ),
    }


def verify_stack_outcome_z_mm(
    *,
    before_side: np.ndarray | None,
    after_side: np.ndarray | None,
    before_top: np.ndarray | None = None,
    after_top: np.ndarray | None = None,
    after_depth: np.ndarray | None = None,
    pick: dict[str, Any],
    place: dict[str, Any],
    spec_id: str | None = None,
    z_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`ContainerSpec`-aware Z-mm stack outcome verification with signed residual `r_k` and `post_release` interlock gate."""
    base_out = verify_stack_outcome(
        before_side=before_side, after_side=after_side, before_top=before_top, after_top=after_top, pick=pick, place=place,
    )
    place_col = int(place.get("col") or 2)
    place_row = int(place.get("row") or 1)
    place_tier = int(place.get("tier") or 3)
    resolved_spec = str(spec_id or place.get("spec_id") or pick.get("spec_id") or place.get("object_id") or "C3")
    slot_obs = perceive_slot_z_mm(
        after_side, after_top, after_depth, col=place_col, row=place_row, tier=place_tier, z_profile=z_profile, spec_id=resolved_spec,
    )
    meas_top_mm = float(slot_obs.get("measured_top_z_mm") or base_out.get("place_slot", {}).get("measured_top_z_mm") or TIER_TOP_Z_MM.get(place_tier, 30.0))
    z_gate = slot_obs.get("spec_gate") or evaluate_signed_tier_residual_mm(meas_top_mm, expected_tier=place_tier, spec_id=resolved_spec)
    if after_side is not None or after_top is not None or after_depth is not None:
        from cell_subzone_3d import evaluate_multiview_subzones
        base_out["subzone_3d"] = evaluate_multiview_subzones(
            after_side, after_top, after_depth, col=place_col, row=place_row, tier=place_tier, spec_id=resolved_spec, mode="adaptive_hybrid", z_profile=z_profile,
        )
    post_gate = evaluate_execution_gate("post_release", z_gate=z_gate)
    rec_skill = select_recovery_skill(str(post_gate.get("failure_code") or "S6_UNSEATED_CONE"), r_k_mm=float(z_gate.get("r_k_mm") or 0.0)) if not post_gate["ok"] else None
    base_out["z_gate"] = z_gate
    base_out["post_release_gate"] = post_gate
    base_out["recovery_skill"] = rec_skill
    if isinstance(base_out.get("place_slot"), dict):
        base_out["place_slot"]["r_k_mm"] = z_gate.get("r_k_mm")
        base_out["place_slot"]["spec_id"] = z_gate.get("spec_id", resolved_spec)
    if not post_gate["ok"]:
        base_out["verified"] = False
        base_out["recovery_mode"] = rec_skill["skill"] if rec_skill else "seat_nudge"
    return base_out


from cell_area_recovery import (  # noqa: E402,F401  (re-exported: existing importers are unchanged)
    diagnose_and_recover_pick,
    perceive_live_base,
    perceive_live_pick_candidates,
    top_pixel_to_arm_xy_vanishing,
)
