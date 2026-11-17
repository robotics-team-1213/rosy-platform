#!/usr/bin/env python3
"""Wrist-Camera Finger-Anchored Coordinate Frame and PCA/OBB Metric Self-Scaling."""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from cell_camera_invariant_top import (
    CONTAINER_LENGTH_MM,
    CONTAINER_WIDTH_MM,
    MM_PER_PX_MAX,
    MM_PER_PX_MIN,
    detect_top_containers_invariant,
    orange_dual_band_mask,
    wrap_half_turn_deg,
)

def detect_wrist_fingers_anchor(
    wrist_img: np.ndarray,
    *,
    finger_color: str = "auto",
) -> dict[str, Any]:
    """Detect the left and right gripper finger inner edges in `y = 0.55*H .. 1.0*H` of `wrist_img`.
    Establishes a camera-mount-invariant grasp origin `(finger_mid_x, finger_apex_y)` and closing axis `u_close`."""
    import cv2

    if wrist_img is None or not hasattr(wrist_img, "shape") or wrist_img.size == 0:
        return {"found": False, "reason": "empty_wrist_img"}
    h, w = wrist_img.shape[:2]
    y0 = int(h * 0.55)
    roi_bgr = wrist_img[y0:]
    roi_hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)

    b_ch = roi_bgr[..., 0].astype(np.int16)
    g_ch = roi_bgr[..., 1].astype(np.int16)
    r_ch = roi_bgr[..., 2].astype(np.int16)
    cool_white_finger = (
        (roi_hsv[..., 0] >= 95)
        & (roi_hsv[..., 0] <= 138)
        & (roi_hsv[..., 1] >= 36)
        & (roi_hsv[..., 1] <= 170)
        & (roi_hsv[..., 2] >= 130)
        & ((b_ch - g_ch) >= 10)
        & ((b_ch - r_ch) >= 22)
    )
    pure_neutral_white = (
        (roi_hsv[..., 2] >= 210)
        & (roi_hsv[..., 1] <= 25)
        & (np.abs(b_ch - g_ch) <= 10)
        & (np.abs(g_ch - r_ch) <= 10)
    )
    white_mask = (cool_white_finger | pure_neutral_white).astype(np.uint8) * 255

    dark_mask = (
        (cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY) < 62) & (roi_hsv[..., 1] <= 95)
    ).astype(np.uint8) * 255

    def _extract_pair(mask_u8: np.ndarray, polarity: str) -> dict[str, Any] | None:
        mask_work = mask_u8.copy()
        n0, labels0, stats0, cents0 = cv2.connectedComponentsWithStats(mask_work)
        min_bot = int(h * 0.86) - y0
        if polarity == "white":
            # If the two closed white fingers touch at their base (forming one wide blob >= 120px in the center),
            # split that blob along its upper-pinch vertical valley
            for i in range(1, n0):
                area0 = int(stats0[i, cv2.CC_STAT_AREA])
                bot0 = int(stats0[i, cv2.CC_STAT_TOP] + stats0[i, cv2.CC_STAT_HEIGHT])
                w0 = int(stats0[i, cv2.CC_STAT_WIDTH])
                l0 = int(stats0[i, cv2.CC_STAT_LEFT])
                cx0 = float(cents0[i][0])
                if area0 >= 4000 and bot0 >= min_bot and w0 >= 120 and (0.30 * w <= cx0 <= 0.72 * w):
                    x_a = l0 + int(0.25 * w0)
                    x_b = l0 + int(0.75 * w0)
                    y_top_band = max(0, int(stats0[i, cv2.CC_STAT_TOP]))
                    y_mid_band = min(mask_work.shape[0], y_top_band + max(10, int(0.60 * stats0[i, cv2.CC_STAT_HEIGHT])))
                    col_profile = (labels0[y_top_band:y_mid_band, x_a:x_b] == i).sum(axis=0)
                    if len(col_profile) > 6:
                        x_seam = x_a + int(np.argmin(col_profile))
                        mask_work[:, max(0, x_seam - 2): min(w, x_seam + 3)] = 0

        n, labels, stats, cents = cv2.connectedComponentsWithStats(mask_work)
        min_area = 150 if polarity == "white" else 900
        candidates = []
        for i in range(1, n):
            area = int(stats[i, cv2.CC_STAT_AREA])
            top_y = int(stats[i, cv2.CC_STAT_TOP])
            bot = int(top_y + stats[i, cv2.CC_STAT_HEIGHT])
            cx = float(cents[i][0])
            if area < min_area or bot < min_bot:
                continue
            # Reject pallet/tray side walls running down the far left/right border from top of ROI
            if polarity == "white" and top_y <= 4 and (cx < 0.22 * w or cx > 0.85 * w):
                continue
            if 0.08 * w <= cx <= 0.92 * w:
                candidates.append(i)
        if len(candidates) < 2:
            return None
        top_pair = sorted(candidates, key=lambda idx: -int(stats[idx, cv2.CC_STAT_AREA]))[:2]
        li, ri = sorted(top_pair, key=lambda idx: float(cents[idx][0]))

        y_pinch_lo = max(0, int(h * 0.68) - y0)
        y_pinch_hi = min(mask_work.shape[0], int(h * (0.98 if polarity == "white" else 0.94)) - y0)
        l_pts, r_pts = [], []
        for ry in range(y_pinch_lo, y_pinch_hi):
            lx = np.where(labels[ry] == li)[0]
            rx = np.where(labels[ry] == ri)[0]
            if len(lx) > 0:
                l_pts.append([float(lx.max()), float(ry + y0)])
            if len(rx) > 0:
                r_pts.append([float(rx.min()), float(ry + y0)])
        min_rows = 4 if polarity == "white" else 6
        if len(l_pts) < min_rows or len(r_pts) < min_rows:
            return None
        l_arr = np.asarray(l_pts, dtype=np.float64)
        r_arr = np.asarray(r_pts, dtype=np.float64)
        p_left = np.median(l_arr, axis=0)
        p_right = np.median(r_arr, axis=0)
        gap_px = float(np.linalg.norm(p_right - p_left))
        mid = 0.5 * (p_left + p_right)
        min_gap = 6.0 if polarity == "white" else 12.0
        if (
            gap_px < min_gap
            or gap_px > 0.58 * w
            or p_left[0] < 0.12 * w
            or p_right[0] > 0.88 * w
            or not (0.38 * w <= mid[0] <= 0.66 * w)
        ):
            return None
        u_close = (p_right - p_left) / gap_px
        u_approach = np.array([-u_close[1], u_close[0]], dtype=np.float64)
        if u_approach[1] > 0:
            u_approach = -u_approach
        return {
            "found": True,
            "finger_color": polarity,
            "left_inner_px": [round(float(p_left[0]), 2), round(float(p_left[1]), 2)],
            "right_inner_px": [round(float(p_right[0]), 2), round(float(p_right[1]), 2)],
            "finger_mid_x": round(float(mid[0]), 2),
            "finger_apex_y": round(float(mid[1]), 2),
            "gap_px": round(gap_px, 2),
            "u_close": [round(float(u_close[0]), 5), round(float(u_close[1]), 5)],
            "u_approach": [round(float(u_approach[0]), 5), round(float(u_approach[1]), 5)],
            "finger_angle_deg": round(float(np.degrees(np.arctan2(u_close[1], u_close[0]))), 2),
        }

    if finger_color == "white":
        res = _extract_pair(white_mask, "white")
    elif finger_color == "dark":
        res = _extract_pair(dark_mask, "dark")
    else:
        res = _extract_pair(white_mask, "white") or _extract_pair(dark_mask, "dark")
    return res if res is not None else {"found": False, "reason": "fingers_not_segmented"}


def pca_major_axis_angle_deg(points_xy: np.ndarray) -> tuple[float, np.ndarray, np.ndarray, float]:
    """Compute unambiguous PCA major-axis angle in degrees `[-90, +90]`, unit eigenvectors
    `(u_major, u_minor)`, and eigenvalue aspect ratio `sqrt(lambda_1 / lambda_2)`."""
    pts = np.asarray(points_xy, dtype=np.float64).reshape(-1, 2)
    if len(pts) < 5:
        return 90.0, np.array([0.0, 1.0]), np.array([1.0, 0.0]), 1.0
    mean = pts.mean(axis=0)
    centered = pts - mean
    cov = (centered.T @ centered) / max(1, len(pts))
    eigvals, eigvecs = np.linalg.eigh(cov)
    idx_maj = int(np.argmax(eigvals))
    idx_min = 1 - idx_maj
    lam_maj = max(1e-6, float(eigvals[idx_maj]))
    lam_min = max(1e-6, float(eigvals[idx_min]))
    u_major = eigvecs[:, idx_maj].astype(np.float64)
    # Canonicalize into upper/right half-plane so pi-periodicity is continuous without 90-deg minAreaRect jumps
    if u_major[1] < 0 or (abs(u_major[1]) < 1e-6 and u_major[0] < 0):
        u_major = -u_major
    u_minor = np.array([u_major[1], -u_major[0]], dtype=np.float64)
    if u_minor[0] < 0:
        u_minor = -u_minor
    theta_deg = float(np.degrees(np.arctan2(u_major[1], u_major[0])))
    pca_aspect = math.sqrt(lam_maj / lam_min)
    return theta_deg, u_major, u_minor, pca_aspect


def detect_wrist_container_obb(
    wrist_img: np.ndarray,
    finger_anchor: dict[str, Any] | None = None,
    *,
    hsv_range: tuple[list[int], list[int]] | None = None,
    gap_mm: float = 44.0,
    border_margin_px: int = 6,
    min_aspect_for_roll: float = 1.45,
) -> dict[str, Any]:
    """Detect the orange container OBB in `wrist_img`, compute self-calibrated metric scale
    `mm_per_px = 30.0 / minor_axis_px`, finger-referenced `(along_mm, across_mm)`, and
    `delta_wrist_roll_deg` with Agent C's translate-first border-clipping and aspect-ratio gates."""
    import cv2

    if wrist_img is None or not hasattr(wrist_img, "shape") or wrist_img.size == 0:
        return {"found": False, "reason": "empty_wrist_img"}
    h, w = wrist_img.shape[:2]
    if finger_anchor is None or not finger_anchor.get("found"):
        finger_anchor = detect_wrist_fingers_anchor(wrist_img)

    mask = orange_dual_band_mask(wrist_img, hsv_range=hsv_range, reject_yellow_table=True)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    valid = [c for c in contours if cv2.contourArea(c) >= 600.0]
    if not valid:
        return {"found": False, "reason": "no_orange_container_contour", "finger_anchor": finger_anchor}

    cnt = max(valid, key=cv2.contourArea)
    (cx, cy), (rw, rh), _ = cv2.minAreaRect(cnt)
    minor_px = float(max(1.0, min(rw, rh)))
    major_px = float(max(rw, rh))
    box_aspect = major_px / minor_px

    pts = cnt.reshape(-1, 2).astype(np.float64)
    x_min_px, y_min_px = pts.min(axis=0)
    x_max_px, y_max_px = pts.max(axis=0)
    clipped_x = bool(x_min_px <= border_margin_px or x_max_px >= (w - border_margin_px))
    clipped_y = bool(y_min_px <= border_margin_px or y_max_px >= (h - border_margin_px))
    clipped_border = bool(clipped_x or clipped_y)

    # PCA principal axes on all mask points inside contour for unambiguous orientation
    cnt_mask = np.zeros((h, w), dtype=np.uint8)
    cv2.drawContours(cnt_mask, [cnt], -1, 255, thickness=-1)
    ys, xs = np.where(cnt_mask > 0)
    mask_pts = np.column_stack([xs, ys]) if len(xs) >= 10 else pts
    theta_container_deg, u_major, u_minor, pca_aspect = pca_major_axis_angle_deg(mask_pts)
    aspect_ratio = max(box_aspect, pca_aspect)

    if finger_anchor.get("found"):
        finger_scale = float(gap_mm) / max(1.0, float(finger_anchor["gap_px"]))
        eff_minor_px = max(minor_px, CONTAINER_WIDTH_MM / finger_scale) if clipped_x else minor_px
        u_close = np.array(finger_anchor["u_close"], dtype=np.float64)
        u_approach = np.array(finger_anchor["u_approach"], dtype=np.float64)
        origin = np.array([finger_anchor["finger_mid_x"], finger_anchor["finger_apex_y"]], dtype=np.float64)
        finger_angle_deg = float(finger_anchor["finger_angle_deg"])
    else:
        eff_minor_px = max(minor_px, 140.0) if clipped_x else minor_px
        u_close = np.array([1.0, 0.0], dtype=np.float64)
        u_approach = np.array([0.0, -1.0], dtype=np.float64)
        origin = np.array([325.0, 205.0], dtype=np.float64)
        finger_angle_deg = 0.0

    mm_per_px = max(MM_PER_PX_MIN, min(MM_PER_PX_MAX, CONTAINER_WIDTH_MM / max(1.0, eff_minor_px)))

    proj_major = (pts - np.array([cx, cy])) @ u_major
    front_offset_px = float(np.percentile(proj_major, 95))
    front_pt = np.array([cx, cy], dtype=np.float64) + front_offset_px * u_major

    delta_center = np.array([cx, cy], dtype=np.float64) - origin
    along_mm = float((delta_center @ u_close) * mm_per_px)
    across_mm = float((delta_center @ u_approach) * mm_per_px)

    # Agent C Invariant: Translate-first when laterally clipped by image border or aspect_ratio < min_aspect_for_roll
    raw_roll_err_deg = wrap_half_turn_deg((theta_container_deg - finger_angle_deg) - 90.0)
    roll_reliable = (not clipped_x) and (aspect_ratio >= min_aspect_for_roll)
    delta_wrist_roll_deg = raw_roll_err_deg if roll_reliable else 0.0

    return {
        "found": True,
        "center_px": [round(float(cx), 2), round(float(cy), 2)],
        "front_px": [round(float(front_pt[0]), 2), round(float(front_pt[1]), 2)],
        "minor_axis_px": round(minor_px, 2),
        "major_axis_px": round(major_px, 2),
        "eff_minor_axis_px": round(eff_minor_px, 2),
        "aspect_ratio": round(aspect_ratio, 2),
        "mm_per_px": round(mm_per_px, 4),
        "clipped_border": clipped_border,
        "roll_reliable": roll_reliable,
        "theta_container_deg": round(theta_container_deg, 2),
        "finger_angle_deg": round(finger_angle_deg, 2),
        "raw_delta_wrist_roll_deg": raw_roll_err_deg,
        "delta_wrist_roll_deg": delta_wrist_roll_deg,
        "along_mm": round(along_mm, 2),
        "across_mm": round(across_mm, 2),
        "finger_anchor": finger_anchor,
    }


def resolve_wrist_camera_mount_config(arm_id: str = "arm_s") -> dict[str, Any]:
    """Return canonical wrist-camera mount & finger geometry priors for `arm_a`, `arm_b`, and `arm_s`."""
    aid = str(arm_id or "arm_s").strip().lower()
    if aid == "arm_s":
        return {
            "arm_id": "arm_s",
            "finger_color": "dark",
            "gap_mm": 36.0,
            "wrist_camera_mount_mode": "arm_s",
            "sign_along": 1.0,
            "sign_across": 1.0,
            "top_camera": "arm_s_top",
            "wrist_camera": "arm_s_wrist",
        }
    return {
        "arm_id": aid if aid in ("arm_a", "arm_b") else "arm_b",
        "finger_color": "white",
        "gap_mm": 44.0,
        "wrist_camera_mount_mode": "arm_ab",
        "sign_along": -1.0,
        "sign_across": 1.0,
        "top_camera": "top",
        "side_camera": "side",
        "wrist_camera": f"{aid}_wrist" if aid in ("arm_a", "arm_b") else "arm_b_wrist",
    }


def estimate_container_z_from_wrist_obb(
    wrist_obb: dict[str, Any] | None,
    z_hover_m: float = 0.086,
    *,
    f_px: float = 1360.0,
    camera_to_tcp_dz_m: float = 0.108,
    container_height_m: float = 0.030,
    x_cur_m: float | None = None,
) -> dict[str, Any]:
    """Estimate physical container pick height `z_pick_m` from monocular 30mm container width
    (`minor_axis_px` in wrist view at known TCP hover height `z_hover_m`), and compute an
    anti-saturation forward reach `recommended_x_m` when picking from the low worktable/floor."""
    if not wrist_obb or not wrist_obb.get("found"):
        return {
            "valid": False,
            "z_pick_m": 0.048,
            "surface_class": "unknown",
            "recommended_x_m": x_cur_m,
        }
    minor_px = float(wrist_obb.get("eff_minor_axis_px") or wrist_obb.get("minor_axis_px") or 260.0)
    minor_px = max(120.0, min(420.0, minor_px))
    optical_dist_m = (float(f_px) * (CONTAINER_WIDTH_MM / 1000.0)) / minor_px
    z_cam_m = float(z_hover_m) + float(camera_to_tcp_dz_m)
    z_top_m = z_cam_m - optical_dist_m
    z_pick_raw_m = z_top_m - 0.50 * float(container_height_m)
    z_pick_m = round(max(0.005, min(0.085, z_pick_raw_m)), 4)

    if z_pick_m <= 0.018:
        surface_class = "floor_or_worktable"
    elif z_pick_m <= 0.056:
        surface_class = "conveyor_belt_or_tier1"
    else:
        surface_class = "stacked_tier2_plus"

    rec_x = x_cur_m
    if x_cur_m is not None and z_pick_m <= 0.018 and float(x_cur_m) < 0.116:
        # Prevent elbow_flex saturation against shoulder_lift when descending to z <= 0.018m near base
        rec_x = 0.116

    return {
        "valid": True,
        "minor_axis_px": round(minor_px, 2),
        "optical_dist_m": round(optical_dist_m, 4),
        "z_top_est_m": round(z_top_m, 4),
        "z_pick_m": z_pick_m,
        "surface_class": surface_class,
        "recommended_x_m": None if rec_x is None else round(float(rec_x), 4),
    }


def detect_workspace_containers_invariant(
    top_img: np.ndarray,
    *,
    arm_id: str = "arm_s",
    hsv_range: tuple[list[int], list[int]] | None = None,
    joint_state_norm: list[float] | tuple[float, ...] | None = None,
) -> dict[str, Any]:
    """Unified camera-invariant top-view container discovery for `arm_s` (`arm_s_top`),
    `arm_a`, and `arm_b` (`top` shared overhead RealSense D435)."""
    mount = resolve_wrist_camera_mount_config(arm_id)
    base_res = detect_top_containers_invariant(
        top_img,
        hsv_range=hsv_range,
        joint_state_norm=joint_state_norm,
        require_arm_clear=False,
    )
    all_boxes = list(base_res.get("containers") or []) + list(base_res.get("floor_containers") or [])
    all_boxes.sort(key=lambda c: (float(c["centroid_px"][1]), float(c["centroid_px"][0])))
    return {
        "arm_id": mount["arm_id"],
        "top_camera": mount["top_camera"],
        "wrist_camera": mount["wrist_camera"],
        "found": len(all_boxes) > 0,
        "belt_found": bool((base_res.get("belt_frame") or {}).get("found")),
        "belt_frame": base_res.get("belt_frame"),
        "belt_containers": base_res.get("containers") or [],
        "workspace_containers": all_boxes,
        "total_count": len(all_boxes),
    }


