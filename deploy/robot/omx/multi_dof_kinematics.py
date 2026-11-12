#!/usr/bin/env python3
"""Unified 5-DOF, 6-DOF (SE(3)), and 7-DOF (Redundant Null-Space) Kinematics & IK (`multi_dof_kinematics.py`).

Supports:
  - 5-DOF (`dof=5`): `[shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll]` (4D top-down + yaw).
  - 6-DOF (`dof=6`): Adds `wrist_yaw` (`[pan, lift, elbow_flex, wrist_flex, wrist_yaw, wrist_roll]`) for full
    spatial SE(3) pose `(x, y, z, roll, pitch, yaw)` on tilted trays/containers via Damped Least-Squares IK.
  - 7-DOF (`dof=7`): Adds redundant `elbow_roll` (`[pan, lift, elbow_roll, elbow_flex, wrist_flex, wrist_yaw, wrist_roll]`)
    with Null-Space Projection `(I - J^+ J) z_0` optimizing joint-limit centering, elbow-swivel `psi` clearance,
    and manipulability `sqrt(det(J J^T))` without disturbing the end-effector SE(3) pose.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np

JOINT_NAMES_BY_DOF: dict[int, tuple[str, ...]] = {
    5: ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"),
    6: ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_yaw", "wrist_roll"),
    7: ("shoulder_pan", "shoulder_lift", "elbow_roll", "elbow_flex", "wrist_flex", "wrist_yaw", "wrist_roll"),
}

DEFAULT_LIMITS_RAD: dict[int, tuple[tuple[float, float], ...]] = {
    5: ((-2.6, 2.6), (-1.9, 1.9), (-1.9, 1.9), (-1.9, 1.9), (-2.8, 2.8)),
    6: ((-2.8, 2.8), (-2.0, 2.0), (-2.1, 2.1), (-2.0, 2.0), (-2.2, 2.2), (-3.0, 3.0)),
    7: ((-2.8, 2.8), (-2.0, 2.0), (-2.6, 2.6), (-2.2, 2.2), (-2.0, 2.0), (-2.2, 2.2), (-3.0, 3.0)),
}


def _rot_x(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]], dtype=float)


def _rot_y(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]], dtype=float)


def _rot_z(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]], dtype=float)


def rpy_to_matrix(roll: float, pitch: float, yaw: float) -> np.ndarray:
    """Intrinsic ZYX (yaw-pitch-roll) rotation matrix from radians."""
    return _rot_z(yaw) @ _rot_y(pitch) @ _rot_x(roll)


def matrix_to_rpy(r: np.ndarray) -> tuple[float, float, float]:
    """Extract (roll, pitch, yaw) in radians from a 3x3 rotation matrix."""
    sy = max(-1.0, min(1.0, float(-r[2, 0])))
    pitch = math.asin(sy)
    if abs(math.cos(pitch)) > 1e-6:
        roll = math.atan2(float(r[2, 1]), float(r[2, 2]))
        yaw = math.atan2(float(r[1, 0]), float(r[0, 0]))
    else:
        roll = 0.0
        yaw = math.atan2(float(-r[0, 1]), float(r[1, 1]))
    return roll, pitch, yaw


def fk_se3(q: Sequence[float], *, dof: int = 6, tcp_x_m: float = 0.0885) -> dict[str, Any]:
    """Forward kinematics for 5-DOF, 6-DOF, or 7-DOF serial arm chain.
    Returns TCP `xyz_m`, `rpy_rad`, `rotation` (3x3), and `elbow_xyz_m` (for 7-DOF swivel clearance)."""
    if dof not in (5, 6, 7):
        raise ValueError(f"unsupported dof={dof}; expected 5, 6, or 7")
    qv = [float(v) for v in q[:dof]]
    if len(qv) != dof:
        raise ValueError(f"expected {dof} joint angles, got {len(qv)}")

    # Link geometry compatible with OMX cell scale (shoulder z=0.078m, upper arm l1=0.130m, forearm l2=0.124m)
    p = np.array([0.0, 0.0, 0.078], dtype=float)
    r = _rot_z(qv[0]) @ _rot_y(qv[1])
    p_shoulder = p + r @ np.array([0.012, 0.0, 0.0])

    if dof == 7:
        # 7-DOF: q[2] is upper-arm roll (elbow swivel psi), q[3] is elbow_flex, q[4] is wrist_flex, q[5] is wrist_yaw, q[6] is wrist_roll
        r_upper = r @ _rot_x(qv[2])
        p_elbow = p_shoulder + r_upper @ np.array([0.130, 0.0, 0.0])
        r_fore = r_upper @ _rot_y(qv[3])
        p_wrist = p_elbow + r_fore @ np.array([0.124, 0.0, 0.0])
        r_tcp = r_fore @ _rot_y(qv[4]) @ _rot_z(qv[5]) @ _rot_x(qv[6])
    elif dof == 6:
        # 6-DOF: q[2] is elbow_flex, q[3] is wrist_flex, q[4] is wrist_yaw, q[5] is wrist_roll
        p_elbow = p_shoulder + r @ np.array([0.130, 0.0, 0.0])
        r_fore = r @ _rot_y(qv[2])
        p_wrist = p_elbow + r_fore @ np.array([0.124, 0.0, 0.0])
        r_tcp = r_fore @ _rot_y(qv[3]) @ _rot_z(qv[4]) @ _rot_x(qv[5])
    else:
        # 5-DOF: q[2] is elbow_flex, q[3] is wrist_flex, q[4] is wrist_roll
        p_elbow = p_shoulder + r @ np.array([0.130, 0.0, 0.0])
        r_fore = r @ _rot_y(qv[2])
        p_wrist = p_elbow + r_fore @ np.array([0.124, 0.0, 0.0])
        r_tcp = r_fore @ _rot_y(qv[3]) @ _rot_x(qv[4])

    p_tcp = p_wrist + r_tcp @ np.array([float(tcp_x_m), 0.0, 0.0])
    rpy = matrix_to_rpy(r_tcp)
    return {
        "dof": dof,
        "xyz_m": [round(float(v), 6) for v in p_tcp],
        "rpy_rad": [round(float(v), 6) for v in rpy],
        "rotation": r_tcp,
        "elbow_xyz_m": [round(float(v), 6) for v in p_elbow],
        "wrist_xyz_m": [round(float(v), 6) for v in p_wrist],
    }


def pose_error(current_fk: dict[str, Any], target_xyz_m: Sequence[float], target_rot: np.ndarray) -> np.ndarray:
    """6D spatial twist error `[dx, dy, dz, wx, wy, wz]` between `current_fk` and `(target_xyz_m, target_rot)`."""
    dp = np.asarray(target_xyz_m, dtype=float) - np.asarray(current_fk["xyz_m"], dtype=float)
    r_cur = np.asarray(current_fk["rotation"], dtype=float)
    r_err = target_rot @ r_cur.T
    trace = max(-1.0, min(3.0, float(np.trace(r_err))))
    angle = math.acos(max(-1.0, min(1.0, (trace - 1.0) * 0.5)))
    if abs(angle) < 1e-6:
        w = np.zeros(3, dtype=float)
    else:
        axis = np.array([r_err[2, 1] - r_err[1, 2], r_err[0, 2] - r_err[2, 0], r_err[1, 0] - r_err[0, 1]], dtype=float)
        w = (0.5 * angle / math.sin(angle)) * axis
    return np.concatenate([dp, w])


def numerical_jacobian(q: Sequence[float], *, dof: int = 6, tcp_x_m: float = 0.0885, eps: float = 1e-5) -> np.ndarray:
    """Compute the 6xN geometric Jacobian `J(q)` via central finite differences in SE(3)."""
    qv = np.asarray(q[:dof], dtype=float)
    j_mat = np.zeros((6, dof), dtype=float)
    base_fk = fk_se3(qv, dof=dof, tcp_x_m=tcp_x_m)
    for i in range(dof):
        dq = np.zeros(dof, dtype=float)
        dq[i] = eps
        fk_plus = fk_se3(qv + dq, dof=dof, tcp_x_m=tcp_x_m)
        err = pose_error(base_fk, fk_plus["xyz_m"], fk_plus["rotation"])
        j_mat[:, i] = err / eps
    return j_mat


def manipulability_index(jacobian: np.ndarray) -> float:
    """Yoshikawa manipulability measure `sqrt(max(0, det(J J^T)))`."""
    jjt = jacobian @ jacobian.T
    det = float(np.linalg.det(jjt))
    return round(math.sqrt(max(0.0, det)), 6)


def nullspace_velocity(
    q: Sequence[float],
    jacobian: np.ndarray,
    limits: Sequence[tuple[float, float]] | None = None,
    *,
    psi_target_rad: float | None = None,
    obstacle_xy_m: tuple[float, float] | None = None,
    center_weight: float = 0.35,
    swivel_weight: float = 0.85,
    damping: float = 0.04,
) -> dict[str, Any]:
    """Compute the 7-DOF null-space projector `(I - J^+ J)` and secondary joint velocity `qdot_null`
    that centers joints within limits and drives the redundant elbow swivel (`q[2]`) toward `psi_target_rad`
    or away from `obstacle_xy_m` without altering the end-effector SE(3) pose."""
    dof = len(q)
    qv = np.asarray(q[:dof], dtype=float)
    lims = limits or DEFAULT_LIMITS_RAD.get(dof, DEFAULT_LIMITS_RAD[7])
    jjt = jacobian @ jacobian.T + (damping**2) * np.eye(jacobian.shape[0])
    j_pinv = jacobian.T @ np.linalg.inv(jjt)
    p_null = np.eye(dof) - j_pinv @ jacobian

    z0 = np.zeros(dof, dtype=float)
    for i, (lo, hi) in enumerate(lims[:dof]):
        mid = 0.5 * (lo + hi)
        span = max(1e-3, hi - lo)
        z0[i] = -center_weight * ((qv[i] - mid) / span)

    if dof == 7:
        if psi_target_rad is not None:
            z0[2] += swivel_weight * (float(psi_target_rad) - qv[2])
        elif obstacle_xy_m is not None:
            fk_cur = fk_se3(qv, dof=7)
            ex, ey, _ = fk_cur["elbow_xyz_m"]
            obs_dy = ey - float(obstacle_xy_m[1])
            swivel_dir = 0.45 if obs_dy >= 0.0 else -0.45
            z0[2] += swivel_weight * (swivel_dir - qv[2])

    qdot_null = p_null @ z0
    return {
        "qdot_secondary": qdot_null,
        "nullspace_projector": p_null,
        "manipulability": manipulability_index(jacobian),
    }


def solve_se3_ik(
    target_xyz_m: Sequence[float],
    target_rpy_deg: Sequence[float] = (0.0, 88.0, -85.0),
    *,
    dof: int = 6,
    q0: Sequence[float] | None = None,
    psi_target_rad: float | None = None,
    obstacle_xy_m: tuple[float, float] | None = None,
    tcp_x_m: float = 0.0885,
    damping: float = 0.04,
    max_steps: int = 90,
    pos_tol_m: float = 1.2e-3,
    rot_tol_rad: float = 1.5e-2,
) -> dict[str, Any]:
    """Solve 5-DOF, 6-DOF, or 7-DOF inverse kinematics in SE(3) using Damped Least-Squares (Levenberg-Marquardt)
    with 7-DOF Null-Space redundancy resolution (`(I - J^+ J) z_0`)."""
    from cell_control_core import rad_to_norm

    if dof not in (5, 6, 7):
        raise ValueError(f"unsupported dof={dof}; expected 5, 6, or 7")
    lims = DEFAULT_LIMITS_RAD[dof]
    if q0 is not None and len(q0) >= dof:
        q = np.asarray(q0[:dof], dtype=float)
    else:
        pan0 = math.atan2(float(target_xyz_m[1]), max(0.04, float(target_xyz_m[0])))
        if dof == 7:
            q = np.array([pan0, -0.45, float(psi_target_rad or 0.0), 0.85, 0.95, 0.0, 0.0], dtype=float)
        elif dof == 6:
            q = np.array([pan0, -0.45, 0.85, 0.95, 0.0, 0.0], dtype=float)
        else:
            q = np.array([pan0, -0.45, 0.85, 0.95, 0.0], dtype=float)

    t_rpy_rad = [math.radians(float(a)) for a in target_rpy_deg]
    target_rot = rpy_to_matrix(*t_rpy_rad)
    active_rows = slice(0, 6) if dof >= 6 else [0, 1, 2, 4, 5]

    for step in range(1, max_steps + 1):
        cur_fk = fk_se3(q, dof=dof, tcp_x_m=tcp_x_m)
        err6 = pose_error(cur_fk, target_xyz_m, target_rot)
        pos_err = float(np.linalg.norm(err6[:3]))
        rot_err = float(np.linalg.norm(err6[3:])) if dof >= 6 else float(math.hypot(err6[4], err6[5]))
        if pos_err <= pos_tol_m and rot_err <= rot_tol_rad:
            j_full = numerical_jacobian(q, dof=dof, tcp_x_m=tcp_x_m)
            return {
                "ok": True,
                "dof": dof,
                "joints_rad": [round(float(v), 5) for v in q],
                "joints_norm": [round(rad_to_norm(float(v)), 3) for v in q],
                "pos_error_mm": round(pos_err * 1000.0, 3),
                "rot_error_deg": round(math.degrees(rot_err), 3),
                "manipulability": manipulability_index(j_full),
                "elbow_xyz_m": cur_fk["elbow_xyz_m"],
                "iterations": step,
            }
        j_full = numerical_jacobian(q, dof=dof, tcp_x_m=tcp_x_m)
        j_act = j_full[active_rows, :]
        e_act = err6[active_rows]
        jjt = j_act @ j_act.T + (damping**2) * np.eye(j_act.shape[0])
        dq_task = j_act.T @ np.linalg.solve(jjt, e_act)
        if dof == 7:
            ns = nullspace_velocity(q, j_act, lims, psi_target_rad=psi_target_rad, obstacle_xy_m=obstacle_xy_m)
            dq = dq_task + 0.35 * ns["qdot_secondary"]
        else:
            dq = dq_task
        step_norm = float(np.max(np.abs(dq)))
        if step_norm > 0.22:
            dq = dq * (0.22 / step_norm)
        q = np.array([max(lo, min(hi, float(v + dv))) for v, dv, (lo, hi) in zip(q, dq, lims)], dtype=float)

    cur_fk = fk_se3(q, dof=dof, tcp_x_m=tcp_x_m)
    err6 = pose_error(cur_fk, target_xyz_m, target_rot)
    pos_err = float(np.linalg.norm(err6[:3]))
    rot_err = float(np.linalg.norm(err6[3:])) if dof >= 6 else float(math.hypot(err6[4], err6[5]))
    j_full = numerical_jacobian(q, dof=dof, tcp_x_m=tcp_x_m)
    return {
        "ok": bool(pos_err <= pos_tol_m * 2.0 and rot_err <= rot_tol_rad * 2.0),
        "dof": dof,
        "joints_rad": [round(float(v), 5) for v in q],
        "joints_norm": [round(rad_to_norm(float(v)), 3) for v in q],
        "pos_error_mm": round(pos_err * 1000.0, 3),
        "rot_error_deg": round(math.degrees(rot_err), 3),
        "manipulability": manipulability_index(j_full),
        "elbow_xyz_m": cur_fk["elbow_xyz_m"],
        "iterations": max_steps,
    }


def plan_se3_chunk(
    start_xyz_m: Sequence[float],
    end_xyz_m: Sequence[float],
    *,
    rpy_deg: Sequence[float] = (0.0, 88.0, -85.0),
    dof: int = 6,
    grip: float = 48.8,
    steps: int = 12,
    psi_target_rad: float | None = None,
    obstacle_xy_m: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """Generate an N-DOF (`dof in {5, 6, 7}`) trajectory chunk of `(dof + 1)`-element frames `[q_1..q_dof, grip]`."""
    frames: list[list[float]] = []
    q_prev: list[float] | None = None
    p0, p1 = np.asarray(start_xyz_m, dtype=float), np.asarray(end_xyz_m, dtype=float)
    n = max(2, int(steps))
    last_ik = None
    for k in range(n):
        alpha = 0.5 * (1.0 - math.cos(math.pi * k / (n - 1)))
        pt = (1.0 - alpha) * p0 + alpha * p1
        ik = solve_se3_ik(
            pt,
            rpy_deg,
            dof=dof,
            q0=q_prev,
            psi_target_rad=psi_target_rad,
            obstacle_xy_m=obstacle_xy_m,
        )
        if not ik["ok"]:
            return {"ok": False, "dof": dof, "failed_step": k, "ik": ik, "frames": frames}
        q_prev = ik["joints_rad"]
        frames.append([*ik["joints_norm"], round(float(grip), 3)])
        last_ik = ik
    return {"ok": True, "dof": dof, "frames": frames, "last_ik": last_ik}
