#!/usr/bin/env python3
"""Camera-Pose and Camera-Angle Invariant Visual Perception and IBVS Self-Calibration."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np

from cell_camera_invariant_top import (  # noqa: F401
    BROYDEN_DAMPING_MM,
    BROYDEN_MAX_ROT_RAD,
    BROYDEN_MAX_SCALE,
    BROYDEN_MAX_STEP_MM,
    BROYDEN_MIN_SCALE,
    BROYDEN_MIN_STEP_MM,
    CONTAINER_LENGTH_MM,
    CONTAINER_WIDTH_MM,
    LM_DAMPING_PX_PER_MM,
    MAX_WRIST_ROLL_STEP_RAD,
    MM_PER_PX_MAX,
    MM_PER_PX_MIN,
    TopExtrinsicCalibrator,
    WRIST_ROLL_DEADBAND_RAD,
    detect_belt_coordinate_frame,
    detect_top_containers_invariant,
    is_arm_clear_of_belt,
    orange_dual_band_mask,
    update_top_extrinsic_offset,
    wrap_half_pi,
    wrap_half_turn_deg,
)
from cell_camera_invariant_wrist import (  # noqa: F401
    detect_workspace_containers_invariant,
    detect_wrist_container_obb,
    detect_wrist_fingers_anchor,
    estimate_container_z_from_wrist_obb,
    pca_major_axis_angle_deg,
    resolve_wrist_camera_mount_config,
)
from cell_control_core import norm_to_rad, rad_to_norm

@dataclass
class BroydenWristServoState:
    """State for uncalibrated / Broyden-updated Eye-in-Hand IBVS + closed-loop wrist_roll alignment."""

    j_hat: np.ndarray               # (2, 2) interaction matrix mapping [dx_mm, dy_mm] -> [de_u_px, de_v_px]
    j_0: np.ndarray                 # (2, 2) nominal kinematic-optical Jacobian
    mm_per_px: float
    closing_rad: float
    arm_id: str = "arm_s"
    roll_sign: float = 1.0
    prev_xy_mm: np.ndarray | None = None
    prev_e_px: np.ndarray | None = None
    prev_e_psi_rad: float | None = None
    prev_dq5_rad: float = 0.0
    iterations: int = 0
    last_update_status: str = "init"


def init_wrist_jacobian(
    minor_axis_px: float,
    shoulder_pan_rad: float,
    wrist_roll_rad: float,
    *,
    arm_id: str | None = None,
    closing_theory_deg: float = 0.0,
    sign_along: float | None = None,
    sign_across: float = 1.0,
    wrist_camera_mount_mode: str | None = None,
) -> BroydenWristServoState:
    """Initialize the nominal 2x2 kinematic-optical interaction matrix J_0 from the 30mm container width
    and the kinematic jaw yaw (shoulder_pan - wrist_roll) across `arm_a`, `arm_b`, and `arm_s`."""
    mount = resolve_wrist_camera_mount_config(arm_id or "arm_s")
    mode = wrist_camera_mount_mode or (mount["wrist_camera_mount_mode"] if arm_id is not None else "standard")
    eff_sign_along = float(mount["sign_along"] if sign_along is None else sign_along)
    mm_per_px = max(MM_PER_PX_MIN, min(MM_PER_PX_MAX, CONTAINER_WIDTH_MM / max(float(minor_axis_px), 120.0)))
    closing_rad = (shoulder_pan_rad - wrist_roll_rad) + math.radians(closing_theory_deg)
    c, s = math.cos(closing_rad), math.sin(closing_rad)
    if mode == "arm_s":
        j_0 = -(1.0 / mm_per_px) * np.array([[s, -c], [-c, -s]], dtype=np.float64)
    elif mode in ("arm_ab", "arm_a", "arm_b"):
        su = -1.0 if eff_sign_along < 0 else 1.0
        sv = -1.0 if sign_across < 0 else 1.0
        j_0 = -(1.0 / mm_per_px) * np.array([[su * c, su * s], [-sv * s, sv * c]], dtype=np.float64)
    else:
        su = -1.0 if eff_sign_along < 0 else 1.0
        sv = -1.0 if sign_across < 0 else 1.0
        j_0 = -(1.0 / mm_per_px) * np.array([[su * c, su * s], [-sv * s, sv * c]], dtype=np.float64)
    return BroydenWristServoState(
        j_hat=j_0.copy(),
        j_0=j_0,
        mm_per_px=mm_per_px,
        closing_rad=closing_rad,
        arm_id=str(arm_id or "arm_s"),
    )


def update_broyden_jacobian(
    state: BroydenWristServoState,
    delta_xy_mm: tuple[float, float] | list[float] | np.ndarray,
    delta_e_px: tuple[float, float] | list[float] | np.ndarray,
    *,
    beta: float = 0.65,
    conformal_weight: float = 0.55,
    allow_remount_snap: bool = False,
) -> np.ndarray:
    """Update J_hat online from observed (Delta_xy_mm, Delta_e_px) with Agent C's step-norm gate
    `3.0 mm <= ||Delta_xy|| <= 40.0 mm` and conformal SO(2)xR+ clamp (`[-35 deg, +35 deg]`, `[0.6, 1.6]`).
    When `allow_remount_snap=True` and a valid step shows a large camera remount rotation (`|dphi_raw| > 45 deg`),
    rotates the nominal basis `J_0` onto the empirically observed camera orientation."""
    dp = np.asarray(delta_xy_mm, dtype=np.float64).reshape(2)
    de = np.asarray(delta_e_px, dtype=np.float64).reshape(2)
    dp_norm = float(np.hypot(dp[0], dp[1]))
    if dp_norm < BROYDEN_MIN_STEP_MM or dp_norm > BROYDEN_MAX_STEP_MM:
        state.last_update_status = "rejected_step_norm"
        return state.j_hat

    pred_nom = state.j_0 @ dp
    nom_norm = float(np.hypot(pred_nom[0], pred_nom[1]))
    de_norm = float(np.hypot(de[0], de[1]))
    if nom_norm < 1e-3 or de_norm < 1e-3:
        state.last_update_status = "rejected_zero_shift"
        return state.j_hat

    # Measure empirical rotation offset and scale factor relative to nominal J_0
    dphi_raw = math.atan2(
        float(pred_nom[0] * de[1] - pred_nom[1] * de[0]),
        float(np.dot(pred_nom, de)),
    )
    rho_raw = de_norm / nom_norm

    if allow_remount_snap and dp_norm >= 4.0 and abs(dphi_raw) > math.radians(45.0):
        c_snap, s_snap = math.cos(dphi_raw), math.sin(dphi_raw)
        rho_snap = max(BROYDEN_MIN_SCALE, min(BROYDEN_MAX_SCALE, rho_raw))
        state.j_0 = np.array([[c_snap, -s_snap], [s_snap, c_snap]], dtype=np.float64) @ state.j_0
        state.j_hat = rho_snap * state.j_0.copy()
        state.last_update_status = "snapped_remount_so2"
        return state.j_hat

    dphi_clamped = max(-BROYDEN_MAX_ROT_RAD, min(BROYDEN_MAX_ROT_RAD, dphi_raw))
    rho_clamped = max(BROYDEN_MIN_SCALE, min(BROYDEN_MAX_SCALE, rho_raw))
    c, s = math.cos(dphi_clamped), math.sin(dphi_clamped)
    j_conf = rho_clamped * (np.array([[c, -s], [s, c]], dtype=np.float64) @ state.j_0)

    dp_norm2 = dp_norm * dp_norm
    pred_de = state.j_hat @ dp
    j_broyden = state.j_hat + (beta / (dp_norm2 + BROYDEN_DAMPING_MM ** 2)) * np.outer(de - pred_de, dp)

    # Blend Broyden with clamped conformal transform, and enforce polar clamp relative to J_0
    j_cand = (1.0 - conformal_weight) * j_broyden + conformal_weight * j_conf
    rel = j_cand @ np.linalg.inv(state.j_0)
    u_svd, s_svd, vt_svd = np.linalg.svd(rel)
    r_polar = u_svd @ vt_svd
    if np.linalg.det(r_polar) < 0:
        state.last_update_status = "rejected_det_flip"
        return state.j_hat
    phi_polar = math.atan2(float(r_polar[1, 0]), float(r_polar[0, 0]))
    phi_clamped = max(-BROYDEN_MAX_ROT_RAD, min(BROYDEN_MAX_ROT_RAD, phi_polar))
    scale_clamped = max(BROYDEN_MIN_SCALE, min(BROYDEN_MAX_SCALE, float(np.mean(s_svd))))
    cp, sp = math.cos(phi_clamped), math.sin(phi_clamped)
    j_bounded = scale_clamped * (np.array([[cp, -sp], [sp, cp]], dtype=np.float64) @ state.j_0)

    if float(np.linalg.cond(j_bounded)) <= 3.5:
        state.j_hat = j_bounded
        state.last_update_status = "updated"
    else:
        state.last_update_status = "rejected_cond"
    return state.j_hat


def compute_ibvs_step(
    state: BroydenWristServoState,
    e_px: tuple[float, float] | list[float] | np.ndarray,
    container_angle_deg: float,
    *,
    pad_axis_deg: float = 0.0,
    roll_reliable: bool = True,
    gain_xy: float = 0.80,
    gain_roll: float = 0.65,
    max_step_mm: float = 8.0,
    max_roll_step_rad: float = MAX_WRIST_ROLL_STEP_RAD,
    allow_remount_snap: bool = True,
) -> dict[str, Any]:
    """Compute one camera-angle-invariant IBVS step `(dx_mm, dy_mm, dq5_rad, dq5_norm, dyaw_deg)`
    with damped Levenberg-Marquardt inversion and Motor 15 strain-safe `wrist_roll` alignment."""
    err_px = np.asarray(e_px, dtype=np.float64).reshape(2)
    if state.prev_xy_mm is not None and state.prev_e_px is not None:
        prev_norm = float(np.hypot(state.prev_e_px[0], state.prev_e_px[1]))
        cur_norm = float(np.hypot(err_px[0], err_px[1]))
        diverged = cur_norm > prev_norm + 3.0
        can_snap = bool(
            allow_remount_snap
            and diverged
            and state.iterations <= 2
            and state.last_update_status not in ("updated", "snapped_remount_so2")
        )
        update_broyden_jacobian(
            state,
            state.prev_xy_mm,
            err_px - state.prev_e_px,
            allow_remount_snap=can_snap,
        )

    j = state.j_hat
    jt_j = j.T @ j + (LM_DAMPING_PX_PER_MM ** 2) * np.eye(2, dtype=np.float64)
    lam = min(gain_xy, 0.75) if state.iterations == 0 else gain_xy
    step_xy = -lam * np.linalg.solve(jt_j, j.T @ err_px)
    step_norm = float(np.hypot(step_xy[0], step_xy[1]))
    if step_norm > max_step_mm:
        step_xy = step_xy * (max_step_mm / step_norm)

    e_psi = wrap_half_pi(math.radians((float(container_angle_deg) - float(pad_axis_deg)) - 90.0))
    if not roll_reliable:
        dq5_rad = 0.0
    else:
        if state.prev_e_psi_rad is not None and abs(state.prev_dq5_rad) >= 0.015:
            if abs(e_psi) > abs(state.prev_e_psi_rad) + math.radians(1.0):
                state.roll_sign = -state.roll_sign
        if abs(e_psi) <= WRIST_ROLL_DEADBAND_RAD:
            dq5_rad = 0.0
        else:
            safe_cap = min(float(max_roll_step_rad), MAX_WRIST_ROLL_STEP_RAD)
            dq5_rad = max(-safe_cap, min(safe_cap, gain_roll * state.roll_sign * e_psi))

    state.prev_xy_mm = step_xy.copy()
    state.prev_e_px = err_px.copy()
    state.prev_e_psi_rad = e_psi if roll_reliable else None
    state.prev_dq5_rad = dq5_rad
    state.iterations += 1

    return {
        "dx_mm": round(float(step_xy[0]), 2),
        "dy_mm": round(float(step_xy[1]), 2),
        "dq5_rad": round(float(dq5_rad), 4),
        "dq5_norm": round(float(rad_to_norm(dq5_rad)), 3),
        "dyaw_deg": round(-math.degrees(dq5_rad), 2),
        "e_psi_deg": round(math.degrees(e_psi), 2),
        "mm_per_px": round(state.mm_per_px, 4),
        "jacobian_status": state.last_update_status,
    }


def compute_r2s_s2r_sync_packet(
    *,
    arm_id: str,
    top_img: np.ndarray | None,
    wrist_img: np.ndarray | None,
    q_real_norm: list[float] | tuple[float, ...],
    q_sim_norm: list[float] | tuple[float, ...] | None = None,
    hover_xyz_m: list[float] | tuple[float, ...] = (0.130, 0.0, 0.086),
    broyden_state: BroydenWristServoState | None = None,
) -> dict[str, Any]:
    """Closed-loop R2S (Real-to-Sim) -> S2R (Sim/Model-to-Real) synchronization packet for `arm_a`, `arm_b`, or `arm_s`."""
    mount = resolve_wrist_camera_mount_config(arm_id)
    q_real = [round(float(v), 3) for v in q_real_norm[:6]]
    q_sim = [round(float(v), 3) for v in (q_sim_norm[:6] if q_sim_norm is not None else q_real)]
    joint_residual_norm = [round(r - s, 3) for r, s in zip(q_real, q_sim)]
    max_joint_err_norm = round(max((abs(v) for v in joint_residual_norm[:5]), default=0.0), 3)

    top_ws = (
        detect_workspace_containers_invariant(top_img, arm_id=arm_id, joint_state_norm=q_real)
        if top_img is not None
        else {"found": False, "total_count": 0, "workspace_containers": []}
    )

    f_anc = (
        detect_wrist_fingers_anchor(wrist_img, finger_color=mount["finger_color"])
        if wrist_img is not None
        else {"found": False}
    )
    obb = (
        detect_wrist_container_obb(wrist_img, f_anc, gap_mm=mount["gap_mm"])
        if wrist_img is not None
        else {"found": False}
    )
    z_est = estimate_container_z_from_wrist_obb(
        obb,
        z_hover_m=float(hover_xyz_m[2]),
        x_cur_m=float(hover_xyz_m[0]),
    )

    if broyden_state is None:
        minor_px = float(obb.get("minor_axis_px") or 250.0) if obb.get("found") else 250.0
        broyden_state = init_wrist_jacobian(
            minor_px,
            norm_to_rad(q_real[0]),
            norm_to_rad(q_real[4]),
            arm_id=arm_id,
        )

    ibvs_cmd = None
    s2r_target_xyz_m = [round(float(v), 4) for v in hover_xyz_m[:3]]
    s2r_target_q5_norm = round(float(q_real[4]), 3)
    z_est_reliable = bool(
        z_est.get("valid")
        and obb.get("found")
        and not obb.get("clipped_border", False)
        and abs(float(obb.get("along_mm", 0.0))) <= 12.0
    )
    if obb.get("found"):
        if f_anc.get("found"):
            o_finger = np.array([float(f_anc["finger_mid_x"]), float(f_anc["finger_apex_y"])], dtype=np.float64)
            u_close = np.array(f_anc["u_close"], dtype=np.float64)
            u_approach = np.array(f_anc["u_approach"], dtype=np.float64)
        else:
            o_finger = np.array([362.0, 380.0], dtype=np.float64)
            u_close = np.array([1.0, 0.0], dtype=np.float64)
            u_approach = np.array([0.0, -1.0], dtype=np.float64)
        o_pinch = o_finger + 55.0 * u_approach
        e_along_px = float((np.asarray(obb["center_px"], dtype=np.float64) - o_pinch) @ u_close)
        e_across_px = float((np.asarray(obb["front_px"], dtype=np.float64) - o_pinch) @ u_approach)
        e_px = [e_along_px, e_across_px]
        ibvs_cmd = compute_ibvs_step(
            broyden_state,
            e_px,
            float(obb["theta_container_deg"]),
            pad_axis_deg=float(obb.get("finger_angle_deg", 0.0)),
            roll_reliable=bool(obb.get("roll_reliable", False)),
            max_step_mm=10.0,
        )
        s2r_target_xyz_m[0] = round(s2r_target_xyz_m[0] + ibvs_cmd["dx_mm"] / 1000.0, 4)
        s2r_target_xyz_m[1] = round(s2r_target_xyz_m[1] + ibvs_cmd["dy_mm"] / 1000.0, 4)
        s2r_target_q5_norm = round(float(q_real[4]) + float(ibvs_cmd["dq5_norm"]), 3)
        if z_est_reliable:
            s2r_target_xyz_m[2] = float(z_est["z_pick_m"])
            if z_est.get("recommended_x_m") is not None:
                s2r_target_xyz_m[0] = max(s2r_target_xyz_m[0], float(z_est["recommended_x_m"]))
        if broyden_state.prev_xy_mm is not None:
            broyden_state.prev_xy_mm[0] = (s2r_target_xyz_m[0] - float(hover_xyz_m[0])) * 1000.0
            broyden_state.prev_xy_mm[1] = (s2r_target_xyz_m[1] - float(hover_xyz_m[1])) * 1000.0

    return {
        "arm_id": mount["arm_id"],
        "r2s_synced": max_joint_err_norm <= 2.2,
        "q_real_norm": q_real,
        "q_sim_norm": q_sim,
        "joint_residual_norm": joint_residual_norm,
        "max_joint_err_norm": max_joint_err_norm,
        "top_workspace_count": int(top_ws.get("total_count", 0)),
        "wrist_finger_anchor": f_anc,
        "wrist_obb": {k: v for k, v in obb.items() if k != "finger_anchor"},
        "z_est": z_est,
        "z_est_reliable": z_est_reliable,
        "ibvs_cmd": ibvs_cmd,
        "s2r_target_xyz_m": s2r_target_xyz_m,
        "s2r_target_q5_norm": s2r_target_q5_norm,
    }
