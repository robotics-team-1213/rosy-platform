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


def _rx3(a: float):
    c, s = math.cos(a), math.sin(a)
    return ((1.0, 0.0, 0.0), (0.0, c, -s), (0.0, s, c))


def _ry3(a: float):
    c, s = math.cos(a), math.sin(a)
    return ((c, 0.0, s), (0.0, 1.0, 0.0), (-s, 0.0, c))


def _rz3(a: float):
    c, s = math.cos(a), math.sin(a)
    return ((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0))


def _mm3(a, b):
    a0, a1, a2 = a
    b0, b1, b2 = b
    return (
        (a0[0] * b0[0] + a0[1] * b1[0] + a0[2] * b2[0], a0[0] * b0[1] + a0[1] * b1[1] + a0[2] * b2[1], a0[0] * b0[2] + a0[1] * b1[2] + a0[2] * b2[2]),
        (a1[0] * b0[0] + a1[1] * b1[0] + a1[2] * b2[0], a1[0] * b0[1] + a1[1] * b1[1] + a1[2] * b2[1], a1[0] * b0[2] + a1[1] * b1[2] + a1[2] * b2[2]),
        (a2[0] * b0[0] + a2[1] * b1[0] + a2[2] * b2[0], a2[0] * b0[1] + a2[1] * b1[1] + a2[2] * b2[1], a2[0] * b0[2] + a2[1] * b1[2] + a2[2] * b2[2]),
    )


def _fk_raw(qv: Sequence[float], dof: int, tcp_x_m: float):
    r = _mm3(_rz3(qv[0]), _ry3(qv[1]))
    sx, sy, sz = r[0][0] * 0.012, r[1][0] * 0.012, 0.078 + r[2][0] * 0.012
    if dof == 7:
        r_upper = _mm3(r, _rx3(qv[2]))
        ex, ey, ez = sx + r_upper[0][0] * 0.130, sy + r_upper[1][0] * 0.130, sz + r_upper[2][0] * 0.130
        r_fore = _mm3(r_upper, _ry3(qv[3]))
        wx, wy, wz = ex + r_fore[0][0] * 0.124, ey + r_fore[1][0] * 0.124, ez + r_fore[2][0] * 0.124
        r_tcp = _mm3(_mm3(_mm3(r_fore, _ry3(qv[4])), _rz3(qv[5])), _rx3(qv[6]))
    elif dof == 6:
        ex, ey, ez = sx + r[0][0] * 0.130, sy + r[1][0] * 0.130, sz + r[2][0] * 0.130
        r_fore = _mm3(r, _ry3(qv[2]))
        wx, wy, wz = ex + r_fore[0][0] * 0.124, ey + r_fore[1][0] * 0.124, ez + r_fore[2][0] * 0.124
        r_tcp = _mm3(_mm3(_mm3(r_fore, _ry3(qv[3])), _rz3(qv[4])), _rx3(qv[5]))
    else:
        ex, ey, ez = sx + r[0][0] * 0.130, sy + r[1][0] * 0.130, sz + r[2][0] * 0.130
        r_fore = _mm3(r, _ry3(qv[2]))
        wx, wy, wz = ex + r_fore[0][0] * 0.124, ey + r_fore[1][0] * 0.124, ez + r_fore[2][0] * 0.124
        r_tcp = _mm3(_mm3(r_fore, _ry3(qv[3])), _rx3(qv[4]))
    tx = float(tcp_x_m)
    p_tcp = (wx + r_tcp[0][0] * tx, wy + r_tcp[1][0] * tx, wz + r_tcp[2][0] * tx)
    return p_tcp, r_tcp, (ex, ey, ez), (wx, wy, wz)


def rpy_to_matrix(roll: float, pitch: float, yaw: float) -> np.ndarray:
    """Intrinsic ZYX (yaw-pitch-roll) rotation matrix from radians."""
    return np.array(_mm3(_mm3(_rz3(yaw), _ry3(pitch)), _rx3(roll)), dtype=float)


def matrix_to_rpy(r: np.ndarray) -> tuple[float, float, float]:
    """Extract (roll, pitch, yaw) in radians from a 3x3 rotation matrix."""
    sy = max(-1.0, min(1.0, float(-r[2][0])))
    pitch = math.asin(sy)
    if abs(math.cos(pitch)) > 1e-6:
        roll = math.atan2(float(r[2][1]), float(r[2][2]))
        yaw = math.atan2(float(r[1][0]), float(r[0][0]))
    else:
        roll = 0.0
        yaw = math.atan2(float(-r[0][1]), float(r[1][1]))
    return roll, pitch, yaw


def fk_se3(q: Sequence[float], *, dof: int = 6, tcp_x_m: float = 0.0885) -> dict[str, Any]:
    """Forward kinematics for 5-DOF, 6-DOF, or 7-DOF serial arm chain.
    Returns TCP `xyz_m`, `rpy_rad`, `rotation` (3x3), and `elbow_xyz_m` (for 7-DOF swivel clearance)."""
    if dof not in (5, 6, 7):
        raise ValueError(f"unsupported dof={dof}; expected 5, 6, or 7")
    qv = [float(v) for v in q[:dof]]
    if len(qv) != dof:
        raise ValueError(f"expected {dof} joint angles, got {len(qv)}")

    p_tcp, r_tcp, p_elbow, p_wrist = _fk_raw(qv, dof, tcp_x_m)
    rpy = matrix_to_rpy(r_tcp)
    return {
        "dof": dof,
        "xyz_m": [round(v, 6) for v in p_tcp],
        "rpy_rad": [round(v, 6) for v in rpy],
        "rotation": np.array(r_tcp, dtype=float),
        "elbow_xyz_m": [round(v, 6) for v in p_elbow],
        "wrist_xyz_m": [round(v, 6) for v in p_wrist],
    }


def _pose_error_raw(cur_xyz, r_cur, target_xyz, target_rot) -> tuple[float, float, float, float, float, float]:
    dx = float(target_xyz[0]) - float(cur_xyz[0])
    dy = float(target_xyz[1]) - float(cur_xyz[1])
    dz = float(target_xyz[2]) - float(cur_xyz[2])
    t0, t1, t2 = target_rot[0], target_rot[1], target_rot[2]
    c0, c1, c2 = r_cur[0], r_cur[1], r_cur[2]
    r00 = t0[0] * c0[0] + t0[1] * c0[1] + t0[2] * c0[2]
    r01 = t0[0] * c1[0] + t0[1] * c1[1] + t0[2] * c1[2]
    r02 = t0[0] * c2[0] + t0[1] * c2[1] + t0[2] * c2[2]
    r10 = t1[0] * c0[0] + t1[1] * c0[1] + t1[2] * c0[2]
    r11 = t1[0] * c1[0] + t1[1] * c1[1] + t1[2] * c1[2]
    r12 = t1[0] * c2[0] + t1[1] * c2[1] + t1[2] * c2[2]
    r20 = t2[0] * c0[0] + t2[1] * c0[1] + t2[2] * c0[2]
    r21 = t2[0] * c1[0] + t2[1] * c1[1] + t2[2] * c1[2]
    r22 = t2[0] * c2[0] + t2[1] * c2[1] + t2[2] * c2[2]
    trace = max(-1.0, min(3.0, float(r00 + r11 + r22)))
    angle = math.acos(max(-1.0, min(1.0, (trace - 1.0) * 0.5)))
    if abs(angle) < 1e-6:
        return dx, dy, dz, 0.0, 0.0, 0.0
    scale = 0.5 * angle / math.sin(angle)
    return (
        dx,
        dy,
        dz,
        scale * float(r21 - r12),
        scale * float(r02 - r20),
        scale * float(r10 - r01),
    )


def pose_error(current_fk: dict[str, Any], target_xyz_m: Sequence[float], target_rot: np.ndarray) -> np.ndarray:
    """6D spatial twist error `[dx, dy, dz, wx, wy, wz]` between `current_fk` and `(target_xyz_m, target_rot)`."""
    return np.array(_pose_error_raw(current_fk["xyz_m"], current_fk["rotation"], target_xyz_m, target_rot), dtype=float)


def numerical_jacobian(
    q: Sequence[float],
    *,
    dof: int = 6,
    tcp_x_m: float = 0.0885,
    eps: float = 1e-5,
    base_fk: dict[str, Any] | None = None,
) -> np.ndarray:
    """Compute the 6xN geometric Jacobian `J(q)` via forward finite differences in SE(3)."""
    qv = [float(v) for v in q[:dof]]
    j_mat = np.zeros((6, dof), dtype=float)
    if base_fk is not None:
        b_xyz, b_rot = base_fk["xyz_m"], base_fk["rotation"]
    else:
        b_xyz_raw, b_rot, _, _ = _fk_raw(qv, dof, tcp_x_m)
        b_xyz = (round(b_xyz_raw[0], 6), round(b_xyz_raw[1], 6), round(b_xyz_raw[2], 6))
    inv_eps = 1.0 / eps
    for i in range(dof):
        orig = qv[i]
        qv[i] = orig + eps
        p_plus, r_plus, _, _ = _fk_raw(qv, dof, tcp_x_m)
        qv[i] = orig
        p_round = (round(p_plus[0], 6), round(p_plus[1], 6), round(p_plus[2], 6))
        err = _pose_error_raw(b_xyz, b_rot, p_round, r_plus)
        j_mat[0, i] = err[0] * inv_eps
        j_mat[1, i] = err[1] * inv_eps
        j_mat[2, i] = err[2] * inv_eps
        j_mat[3, i] = err[3] * inv_eps
        j_mat[4, i] = err[4] * inv_eps
        j_mat[5, i] = err[5] * inv_eps
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
    elbow_xyz_m: Sequence[float] | None = None,
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
    p_null = np.eye(dof) - jacobian.T @ np.linalg.solve(jjt, jacobian)

    z0 = np.zeros(dof, dtype=float)
    for i, (lo, hi) in enumerate(lims[:dof]):
        mid = 0.5 * (lo + hi)
        span = max(1e-3, hi - lo)
        z0[i] = -center_weight * ((qv[i] - mid) / span)

    if dof == 7:
        if psi_target_rad is not None:
            z0[2] += swivel_weight * (float(psi_target_rad) - qv[2])
        elif obstacle_xy_m is not None:
            if elbow_xyz_m is None:
                _, _, elbow_xyz_m, _ = _fk_raw(qv, 7, 0.0885)
            obs_dy = float(elbow_xyz_m[1]) - float(obstacle_xy_m[1])
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
        pos_err = math.sqrt(float(err6[0] * err6[0] + err6[1] * err6[1] + err6[2] * err6[2]))
        rot_err = (
            math.sqrt(float(err6[3] * err6[3] + err6[4] * err6[4] + err6[5] * err6[5]))
            if dof >= 6
            else float(math.hypot(err6[4], err6[5]))
        )
        if pos_err <= pos_tol_m and rot_err <= rot_tol_rad:
            j_full = numerical_jacobian(q, dof=dof, tcp_x_m=tcp_x_m, base_fk=cur_fk)
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
        j_full = numerical_jacobian(q, dof=dof, tcp_x_m=tcp_x_m, base_fk=cur_fk)
        j_act = j_full[active_rows, :]
        e_act = err6[active_rows]
        jjt = j_act @ j_act.T + (damping**2) * np.eye(j_act.shape[0])
        dq_task = j_act.T @ np.linalg.solve(jjt, e_act)
        if dof == 7:
            ns = nullspace_velocity(
                q,
                j_act,
                lims,
                psi_target_rad=psi_target_rad,
                obstacle_xy_m=obstacle_xy_m,
                elbow_xyz_m=cur_fk["elbow_xyz_m"],
            )
            dq = dq_task + 0.35 * ns["qdot_secondary"]
        else:
            dq = dq_task
        step_norm = float(np.max(np.abs(dq)))
        if step_norm > 0.22:
            dq = dq * (0.22 / step_norm)
        q = np.array([max(lo, min(hi, float(v + dv))) for v, dv, (lo, hi) in zip(q, dq, lims)], dtype=float)

    cur_fk = fk_se3(q, dof=dof, tcp_x_m=tcp_x_m)
    err6 = pose_error(cur_fk, target_xyz_m, target_rot)
    pos_err = math.sqrt(float(err6[0] * err6[0] + err6[1] * err6[1] + err6[2] * err6[2]))
    rot_err = (
        math.sqrt(float(err6[3] * err6[3] + err6[4] * err6[4] + err6[5] * err6[5]))
        if dof >= 6
        else float(math.hypot(err6[4], err6[5]))
    )
    j_full = numerical_jacobian(q, dof=dof, tcp_x_m=tcp_x_m, base_fk=cur_fk)
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
