#!/usr/bin/env python3
"""Top-Camera Scene-Anchored Conveyor Belt Coordinate Frame and Online Eye-to-Hand Self-Calibration."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

import numpy as np

CONTAINER_WIDTH_MM, CONTAINER_LENGTH_MM = 30.0, 90.0
MM_PER_PX_MIN, MM_PER_PX_MAX = 0.065, 0.250
# Motor 15 (wrist_roll) strain-safe limit: 0.045 rad == 1.432 norm units < ROLL_BLOCK_LAG (1.5) < STRAIN_LAG (2.2)
MAX_WRIST_ROLL_STEP_RAD: float = 0.045
WRIST_ROLL_DEADBAND_RAD: float = math.radians(2.0)
BROYDEN_MIN_STEP_MM, BROYDEN_MAX_STEP_MM, BROYDEN_DAMPING_MM = 3.0, 40.0, 1.5
BROYDEN_MAX_ROT_RAD: float = math.radians(35.0)
BROYDEN_MIN_SCALE, BROYDEN_MAX_SCALE, LM_DAMPING_PX_PER_MM = 0.60, 1.60, 0.15


def wrap_half_turn_deg(angle_deg: float) -> float:
    """Wrap angle in degrees into (-90.0, +90.0] for 180-deg symmetric parallel-jaw grippers."""
    wrapped = (float(angle_deg) + 90.0) % 180.0 - 90.0
    return 90.0 if wrapped <= -90.0 else round(wrapped, 2)


def wrap_half_pi(angle_rad: float) -> float:
    """Wrap angle in radians into [-pi/2, +pi/2]."""
    return (float(angle_rad) + 0.5 * math.pi) % math.pi - 0.5 * math.pi


def is_arm_clear_of_belt(
    joint_state_norm: list[float] | tuple[float, ...] | None, *,
    standby_pose: tuple[float, ...] = (0.0, -27.0, 18.0, 46.0, -5.0),
    home_pose: tuple[float, ...] = (0.0, -58.0, 50.0, 50.0, -5.0), tol_units: float = 2.5,
) -> bool:
    """Check whether `arm_s` is retracted at `standby` or `home` so the arm boom does not occlude the belt."""
    if joint_state_norm is None or len(joint_state_norm) < 5:
        return True
    q5 = [float(x) for x in joint_state_norm[:5]]
    near_standby = max(abs(a - b) for a, b in zip(q5, standby_pose)) <= tol_units
    near_home = max(abs(a - b) for a, b in zip(q5, home_pose)) <= tol_units
    return bool(near_standby or near_home or (q5[1] <= -24.5 and abs(q5[0]) <= 3.5))


def orange_dual_band_mask(
    bgr_img: np.ndarray, hsv_range: tuple[list[int], list[int]] | None = None, *, reject_yellow_table: bool = True,
) -> np.ndarray:
    """Return uint8 binary mask (0 or 255) of red-orange containers across Hue wrap [0..28] U [168..180],
    rejecting yellow worktable glare via CIE Lab a* redness threshold."""
    import cv2

    hsv_img = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2HSV)
    if hsv_range is not None and len(hsv_range) == 2 and hsv_range[0] is not None:
        lo, hi = np.asarray(hsv_range[0], dtype=np.uint8), np.asarray(hsv_range[1], dtype=np.uint8)
        s_min, v_min, hi_h = max(52, int(lo[1]) - 35), max(60, int(lo[2]) - 35), min(28, max(22, int(hi[0])))
    else:
        s_min, v_min, hi_h = 55, 65, 28

    lo1, hi1 = np.array([0, s_min, v_min], dtype=np.uint8), np.array([hi_h, 255, 255], dtype=np.uint8)
    lo2 = np.array([168, max(50, s_min - 10), max(60, v_min - 5)], dtype=np.uint8)
    hi2 = np.array([180, 255, 255], dtype=np.uint8)
    mask = cv2.bitwise_or(cv2.inRange(hsv_img, lo1, hi1), cv2.inRange(hsv_img, lo2, hi2))

    b_ch, g_ch, r_ch = bgr_img[..., 0].astype(np.int16), bgr_img[..., 1].astype(np.int16), bgr_img[..., 2].astype(np.int16)
    rb = r_ch - b_ch
    rgb_orange = ((r_ch >= 105) & (4 * rb >= r_ch) & ((r_ch - g_ch) >= 22) & (25 * (g_ch - b_ch) <= 14 * rb)).astype(np.uint8) * 255
    mask = cv2.bitwise_or(mask, rgb_orange)

    if reject_yellow_table:
        lab_img = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2LAB)
        a_star_delta = lab_img[..., 1].astype(np.int16) - 128
        yellow_hue = (hsv_img[..., 0] >= 15) & (hsv_img[..., 0] <= 45)
        mask[(yellow_hue & (a_star_delta < 22)) | (a_star_delta < 16)] = 0

    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))


def detect_belt_coordinate_frame(
    top_img: np.ndarray, *, belt_length_m: float = 0.42, belt_width_m: float = 0.115,
    joint_state_norm: list[float] | tuple[float, ...] | None = None, require_arm_clear: bool = False,
) -> dict[str, Any]:
    """Segment the dark conveyor belt strip in `top_img` to establish a camera-pose-invariant
    normalized belt coordinate frame `(u_along_belt, v_across_belt) in [0, 1]^2`."""
    import cv2

    if top_img is None or not hasattr(top_img, "shape") or top_img.size == 0:
        return {"found": False, "reason": "empty_top_img"}
    arm_clear = is_arm_clear_of_belt(joint_state_norm)
    if require_arm_clear and not arm_clear:
        return {"found": False, "reason": "arm_occluding_belt", "arm_clear": False}

    h, w = top_img.shape[:2]
    hsv = cv2.cvtColor(top_img, cv2.COLOR_BGR2HSV)
    lab = cv2.cvtColor(top_img, cv2.COLOR_BGR2LAB)

    dark_belt = (
        (hsv[..., 2] >= 12)
        & (hsv[..., 2] <= 105)
        & (hsv[..., 1] <= 165)
        & (np.abs(lab[..., 1].astype(np.int16) - 128) <= 16)
        & (np.abs(lab[..., 2].astype(np.int16) - 128) <= 26)
    )
    # Use the yellow worktable top boundary (if present) and white lane tape to isolate the conveyor belt strip
    yellow_table = (
        (hsv[..., 0] >= 15)
        & (hsv[..., 0] <= 40)
        & (hsv[..., 1] >= 35)
        & (hsv[..., 2] >= 120)
        & ((lab[..., 1].astype(np.int16) - 128) < 10)
    )
    pts_rail: list[tuple[float, float]] = []
    for x in range(int(w * 0.30), int(w * 0.96)):
        ys = np.where(yellow_table[:, x])[0]
        if len(ys) >= 35:
            y_top = float(np.percentile(ys, 3))
            if y_top < 0.55 * h:
                pts_rail.append((float(x), y_top))
    if len(pts_rail) >= 18:
        arr = np.asarray(pts_rail, dtype=np.float64)
        slope, intercept = np.polyfit(arr[:, 0], arr[:, 1], 1)
        yy, xx = np.indices((h, w))
        above_table = yy < (slope * xx + intercept - 10.0)
        dark_belt = dark_belt & above_table
    else:
        above_table = np.ones((h, w), dtype=bool)
        above_table[int(h * 0.55):, :] = False
        dark_belt = dark_belt & above_table

    white_lane = (hsv[: int(h * 0.5), : int(w * 0.55), 2] >= 180) & (
        hsv[: int(h * 0.5), : int(w * 0.55), 1] <= 105
    )
    xs_w = np.where(white_lane.sum(axis=0) > int(h * 0.14))[0]
    if len(xs_w) > 0:
        x_cut = int(xs_w.max())
        dark_belt[:, :x_cut] = False
        above_table[:, :x_cut] = False

    orange_mask = orange_dual_band_mask(top_img)
    orange_on_belt = np.where(above_table, orange_mask, 0).astype(np.uint8)
    combined = cv2.bitwise_or(dark_belt.astype(np.uint8) * 255, orange_on_belt)

    k_close = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 17))
    k_open = cv2.getStructuringElement(cv2.MORPH_RECT, (11, 11))
    belt_mask = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, k_close)
    belt_mask = cv2.morphologyEx(belt_mask, cv2.MORPH_OPEN, k_open)

    contours, _ = cv2.findContours(belt_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = 0.025 * float(h * w)
    best_rect = None
    best_score = -1.0
    for cnt in contours:
        area = float(cv2.contourArea(cnt))
        if area < min_area:
            continue
        rect = cv2.minAreaRect(cnt)
        (cx, cy), (rw, rh), ang = rect
        major = max(rw, rh)
        minor = max(1.0, min(rw, rh))
        aspect = major / minor
        if aspect < 1.35:
            continue
        pts_c = cnt.reshape(-1, 2).astype(np.float64)
        cov_c = np.cov((pts_c - pts_c.mean(axis=0)).T) if len(pts_c) >= 5 else np.eye(2)
        ev_w, ev_v = np.linalg.eigh(cov_c)
        u_c = ev_v[:, int(np.argmax(ev_w))]
        if u_c[0] < 0:
            u_c = -u_c
        ang_c = abs(float(np.degrees(np.arctan2(u_c[1], u_c[0]))))
        if ang_c > 45.0:
            continue
        fill = area / max(1.0, major * minor)
        score = area * min(aspect, 5.0) * max(0.3, fill)
        if score > best_score:
            best_score = score
            best_rect = (cnt, (cx, cy), (rw, rh), ang)

    if best_rect is None:
        return {"found": False, "reason": "belt_contour_not_found", "arm_clear": arm_clear}

    cnt, (cx, cy), (rw, rh), _ = best_rect
    length_px = float(max(rw, rh))
    width_px = float(max(1.0, min(rw, rh)))

    pts = cnt.reshape(-1, 2).astype(np.float64)
    mean = pts.mean(axis=0)
    cov = np.cov((pts - mean).T) if len(pts) >= 5 else np.eye(2)
    eigvals, eigvecs = np.linalg.eigh(cov)
    e_along = eigvecs[:, int(np.argmax(eigvals))]
    if e_along[0] < 0:
        e_along = -e_along
    e_across = np.array([-e_along[1], e_along[0]], dtype=np.float64)
    if e_across[1] < 0:
        e_across = -e_across

    angle_deg = float(np.degrees(np.arctan2(e_along[1], e_along[0])))
    box_pts = cv2.boxPoints(best_rect[1:]).tolist()
    return {
        "found": True, "arm_clear": arm_clear, "center_px": [round(float(cx), 2), round(float(cy), 2)],
        "length_px": round(length_px, 2), "width_px": round(width_px, 2), "angle_deg": round(angle_deg, 2),
        "e_along": [round(float(e_along[0]), 5), round(float(e_along[1]), 5)],
        "e_across": [round(float(e_across[0]), 5), round(float(e_across[1]), 5)],
        "mm_per_px_along": round((belt_length_m * 1000.0) / length_px, 4),
        "mm_per_px_across": round((belt_width_m * 1000.0) / width_px, 4),
        "box_points_px": [[round(float(p[0]), 1), round(float(p[1]), 1)] for p in box_pts],
    }

def detect_top_containers_invariant(
    top_img: np.ndarray,
    belt_frame: dict[str, Any] | None = None,
    *,
    slot_u_centers: dict[str, float] | None = None,
    requested_slot: str | None = None,
    hsv_range: tuple[list[int], list[int]] | None = None,
    joint_state_norm: list[float] | tuple[float, ...] | None = None,
    require_arm_clear: bool = False,
    min_area_px: float = 250.0,
    max_area_px: float = 28000.0,
    max_aspect_ratio: float = 4.5,
) -> dict[str, Any]:
    """Detect all red-orange containers in `top_img` and project into normalized belt coordinates
    `(u_along_belt, v_across_belt) in [0, 1]^2` without fixed pixel ROI boxes."""
    import cv2

    if top_img is None or not hasattr(top_img, "shape") or top_img.size == 0:
        return {"found": False, "containers": [], "floor_containers": [], "verdict": "no_top_frame"}
    if require_arm_clear and not is_arm_clear_of_belt(joint_state_norm):
        return {"found": False, "containers": [], "floor_containers": [], "verdict": "arm_occluding_belt", "arm_clear": False}
    if belt_frame is None or not belt_frame.get("found"):
        belt_frame = detect_belt_coordinate_frame(
            top_img,
            joint_state_norm=joint_state_norm,
            require_arm_clear=require_arm_clear,
        )

    mask = orange_dual_band_mask(top_img, hsv_range=hsv_range, reject_yellow_table=True)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    slot_map = slot_u_centers or {"b_shifted": 0.25, "b_near": 0.45, "b_far": 0.72}

    has_belt = bool(belt_frame.get("found"))
    if has_belt:
        c_belt = np.array(belt_frame["center_px"], dtype=np.float64)
        e_u = np.array(belt_frame["e_along"], dtype=np.float64)
        e_v = np.array(belt_frame["e_across"], dtype=np.float64)
        l_px = max(1.0, float(belt_frame["length_px"]))
        w_px = max(1.0, float(belt_frame["width_px"]))
    else:
        h, w = top_img.shape[:2]
        c_belt = np.array([0.5 * w, 0.5 * h], dtype=np.float64)
        e_u, e_v = np.array([1.0, 0.0]), np.array([0.0, 1.0])
        l_px, w_px = float(w), float(h)

    on_belt: list[dict[str, Any]] = []
    on_floor: list[dict[str, Any]] = []
    for cnt in contours:
        area = float(cv2.contourArea(cnt))
        if area < min_area_px or area > max_area_px:
            continue
        (cx, cy), (rw, rh), _ = cv2.minAreaRect(cnt)
        major_px = float(max(rw, rh))
        minor_px = float(max(1.0, min(rw, rh)))
        aspect = major_px / minor_px
        if aspect > max_aspect_ratio:
            continue

        pts = cnt.reshape(-1, 2).astype(np.float64)
        cov = np.cov((pts - pts.mean(axis=0)).T) if len(pts) >= 5 else np.eye(2)
        eigvals, eigvecs = np.linalg.eigh(cov)
        u_maj = eigvecs[:, int(np.argmax(eigvals))]
        if u_maj[0] < 0:
            u_maj = -u_maj
        theta_box = float(np.degrees(np.arctan2(u_maj[1], u_maj[0])))

        # Automatically split packed side-by-side containers (e.g. 2 or 3 containers touching in ship pallet)
        span_x = float(pts[:, 0].max() - pts[:, 0].min())
        span_y = float(pts[:, 1].max() - pts[:, 1].min())
        n_packed = 1
        if area >= 6800.0 and minor_px >= 68.0 and major_px <= 165.0:
            n_packed = max(2, min(3, int(round(max(span_x, span_y) / 44.0))))

        if n_packed > 1:
            # In a 2- or 3-wide packed row on the ship pallet, containers sit side-by-side along X
            pack_along_x = span_x >= 0.85 * span_y
            u_pack = np.array([1.0, 0.0], dtype=np.float64) if pack_along_x else np.array([0.0, 1.0], dtype=np.float64)
            span_pack = span_x if pack_along_x else span_y
            box_len_px = span_y if pack_along_x else span_x
            single_w_px = max(24.0, span_pack / float(n_packed))
            sub_theta = 90.0 if pack_along_x else 0.0
            sub_centers = [
                np.array([cx, cy], dtype=np.float64) + ((k - 0.5 * (n_packed - 1)) * single_w_px) * u_pack
                for k in range(n_packed)
            ]
            sub_specs = [(sc[0], sc[1], box_len_px, single_w_px, sub_theta, area / n_packed) for sc in sub_centers]
        else:
            sub_specs = [(cx, cy, major_px, minor_px, theta_box, area)]

        for scx, scy, smaj, smin, stheta, sarea in sub_specs:
            rel_yaw_deg = wrap_half_turn_deg(stheta - float(belt_frame.get("angle_deg", 0.0)))
            dp = np.array([scx, scy], dtype=np.float64) - c_belt
            u_val = float((dp @ e_u) / l_px + 0.5)
            v_val = float((dp @ e_v) / w_px + 0.5)
            nearest_slot = min(slot_map, key=lambda k: abs(u_val - float(slot_map[k])))
            entry = {
                "centroid_px": [round(float(scx), 1), round(float(scy), 1)], "u_along_belt": round(u_val, 4), "v_across_belt": round(v_val, 4),
                "major_px": round(float(smaj), 1), "minor_px": round(float(smin), 1), "aspect_ratio": round(float(smaj) / max(1.0, float(smin)), 2),
                "mm_per_px": round(CONTAINER_WIDTH_MM / max(1.0, float(smin)), 4), "theta_img_deg": round(float(stheta), 2),
                "yaw_rel_belt_deg": rel_yaw_deg, "area_px": round(float(sarea), 1), "slot": nearest_slot, "packed_group_size": n_packed,
            }
            if -0.05 <= u_val <= 1.05 and 0.02 <= v_val <= 0.78:
                on_belt.append(entry)
            else:
                on_floor.append(entry)

    on_belt.sort(key=lambda d: d["u_along_belt"])
    return {"found": len(on_belt) > 0, "arm_clear": True, "belt_frame": belt_frame, "containers": on_belt, "floor_containers": on_floor, "requested_slot": requested_slot}

@dataclass
class TopExtrinsicCalibrator:
    """Online Eye-to-Hand active anchor self-calibrator (Top Camera UV <-> Robot Base FK XY)."""

    affine_2x2: np.ndarray  # shape (2, 2), m per px
    offset_xy: np.ndarray   # shape (2,), datum offset in robot base frame (m)
    alpha: float = 0.45
    max_step_m: float = 0.018
    outlier_gate_m: float = 0.045
    anchors: list[tuple[np.ndarray, np.ndarray]] = field(default_factory=list)

    def map_top_px_to_robot_xy(self, top_uv: tuple[float, float] | list[float]) -> tuple[float, float]:
        u = np.asarray(top_uv, dtype=np.float64).reshape(2)
        p = self.affine_2x2 @ u + self.offset_xy
        return round(float(p[0]), 4), round(float(p[1]), 4)

def update_top_extrinsic_offset(
    cal: TopExtrinsicCalibrator,
    top_uv: tuple[float, float] | list[float],
    robot_xy_m: tuple[float, float] | list[float],
) -> dict[str, Any]:
    """Apply an online rank-1 datum offset correction (and optional 2-anchor Procrustes rotation)
    to the top camera's belt-to-robot mapping using a wrist-locked or FK-verified robot XY anchor."""
    u = np.asarray(top_uv, dtype=np.float64).reshape(2)
    p_true = np.asarray(robot_xy_m, dtype=np.float64).reshape(2)
    p_pred = cal.affine_2x2 @ u + cal.offset_xy
    residual = p_true - p_pred
    res_norm = float(np.hypot(residual[0], residual[1]))
    if res_norm > cal.outlier_gate_m:
        return {"updated": False, "residual_m": round(res_norm, 4), "reason": "outlier_rejected"}

    step = residual * min(1.0, cal.max_step_m / max(res_norm, 1e-9))
    cal.offset_xy = cal.offset_xy + cal.alpha * step
    cal.anchors = (cal.anchors + [(u, p_true)])[-6:]
    rot_deg = 0.0
    if len(cal.anchors) >= 2:
        u0, p0 = cal.anchors[0]
        dp = p_true - p0
        if float(np.hypot(dp[0], dp[1])) >= 0.035:
            dp_hat = cal.affine_2x2 @ (u - u0)
            if float(np.hypot(dp_hat[0], dp_hat[1])) >= 0.020:
                dtheta = math.atan2(
                    float(dp_hat[0] * dp[1] - dp_hat[1] * dp[0]),
                    float(np.dot(dp_hat, dp)),
                )
                dtheta = max(-math.radians(20.0), min(math.radians(20.0), 0.35 * dtheta))
                c, s = math.cos(dtheta), math.sin(dtheta)
                r_mat = np.array([[c, -s], [s, c]], dtype=np.float64)
                cal.affine_2x2 = r_mat @ cal.affine_2x2
                rot_deg = round(math.degrees(dtheta), 2)
    return {
        "updated": True,
        "residual_m": round(res_norm, 4),
        "offset_xy_m": [round(float(cal.offset_xy[0]), 4), round(float(cal.offset_xy[1]), 4)],
        "rot_correction_deg": rot_deg,
    }


