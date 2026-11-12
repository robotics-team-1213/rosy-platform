#!/usr/bin/env python3
"""Canonical OMX robot control primitives shared across `grasp_planner`, `cell_area_xyz`,
`cell_area_zones`, `vla_handover_broker`, and `cell_fleet_pipeline`.

Single Responsibility:
  1. Path & adapter bootstrap (`ensure_omx_paths`, `HERE`, `ADAPTER_ROOT`)
  2. LeRobot unit conversion & 5/6/7-DOF guarded action clamping (`rad_to_norm`, `norm_to_rad`,
     `clamp_lerobot_norm_action`, `infer_frame_dof`)
  3. Per-arm Cartesian workspace clamping, wrist vision offset projection, moving-belt intercept,
     and tactile seating compliance (`arm_workspace_xy_bounds`, `clamp_workspace_xy`,
     `project_wrist_offset_xy_m`, `apply_wrist_xy_step`, `compute_stud_release_residual`,
     `predict_moving_belt_intercept`, `evaluate_tactile_place_compliance`)
  - `AreaXYZ` directive compilation (`cell_directive_compiler.py`) and multi-DOF kinematics
    (`multi_dof_kinematics.py`) are re-exported here unchanged.
"""
from __future__ import annotations

import math
from pathlib import Path
import sys
from typing import Any, Sequence

HERE = Path(__file__).resolve().parent
ADAPTER_ROOT = HERE.parents[2] / "middleware/devices/omx/adapter"


def ensure_omx_paths() -> tuple[Path, Path]:
    """Ensure `deploy/robot/omx` and `middleware/devices/omx/adapter` are on `sys.path`."""
    for p in (HERE, ADAPTER_ROOT):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)
    return HERE, ADAPTER_ROOT


ensure_omx_paths()

TICKS = 4096
GUARD_UNITS_PER_S = 5.0
BODY_LIMIT = (-100.0, 100.0)
GRIPPER_LIMIT = (0.0, 100.0)
MAX_RELEASE_RESIDUAL_XY_M = 0.008  # ±8mm bound matching learning/envs/isaac/release_corrector.py
MAX_RELEASE_RESIDUAL_YAW_DEG = 6.87  # 0.12 rad


def rad_to_norm(rad: float, lo: float = 0, hi: float = 4095) -> float:
    """LeRobot body-joint normalization (RANGE_M100_100) of a Dynamixel angle, tick 2048 = 0 rad."""
    raw = (rad + math.pi) * TICKS / (2 * math.pi)
    return (min(max(raw, lo), hi) - lo) / (hi - lo) * 200 - 100


def norm_to_rad(norm: float, lo: float = 0, hi: float = 4095) -> float:
    """Inverse of `rad_to_norm`: convert LeRobot normalized body units [-100, 100] to radians."""
    raw = (norm + 100) / 200 * (hi - lo) + lo
    return raw * 2 * math.pi / TICKS - math.pi


def clamp_lerobot_norm_action(
    action: list[float],
    current_state: list[float] | None = None,
    *,
    dt_s: float = 1.0 / 30.0,
    max_units_per_s: float = GUARD_UNITS_PER_S,
    max_joint_step_norm: float | None = None,
    max_grip_step_norm: float | None = None,
) -> list[float]:
    """Enforces D-854 `lerobot_norm_v1` bounds (`[-100, 100]` body, `[0, 100]` gripper) and rate guard
    across 5-DOF (len 6), 6-DOF (len 7), and 7-DOF (len 8) arm action vectors."""
    n = len(action)
    if n not in (6, 7, 8):
        raise ValueError(f"Expected 5/6/7-DOF OMX action vector (len 6, 7, or 8), got {n}")
    default_step = max_units_per_s * max(dt_s, 1e-3)
    joint_step = default_step if max_joint_step_norm is None else float(max_joint_step_norm)
    grip_step = default_step if max_grip_step_norm is None else float(max_grip_step_norm)
    grip_idx = n - 1
    out: list[float] = []
    for idx, val in enumerate(action):
        v = float(val)
        step = grip_step if idx == grip_idx else joint_step
        if current_state is not None and len(current_state) == n:
            cur = float(current_state[idx])
            if abs(v - cur) > step:
                v = cur + (step if v > cur else -step)
        lo, hi = GRIPPER_LIMIT if idx == grip_idx else BODY_LIMIT
        out.append(round(min(max(v, lo), hi), 4))
    return out


def arm_workspace_xy_bounds(arm_id: str = "arm_b") -> tuple[float, float, float]:
    """Return `(x_lo_m, x_hi_m, y_abs_limit_m)` for `arm_s` (includes Pinky AMR tray) vs `arm_a`/`arm_b`."""
    if str(arm_id) == "arm_s":
        return 0.025, 0.232, 0.220
    return 0.055, 0.232, 0.155


def clamp_workspace_xy(
    x_m: float,
    y_m: float,
    arm_id: str = "arm_b",
    *,
    x_hi: float | None = None,
) -> tuple[float, float]:
    """Clamp `(x_m, y_m)` to the safe Cartesian reach envelope of `arm_id`."""
    x_lo, default_x_hi, y_lim = arm_workspace_xy_bounds(arm_id)
    hi = default_x_hi if x_hi is None else float(x_hi)
    return (
        round(max(x_lo, min(hi, float(x_m))), 5),
        round(max(-y_lim, min(y_lim, float(y_m))), 5),
    )


def project_wrist_offset_xy_m(
    obs: dict[str, Any] | None,
    *,
    arm_id: str = "arm_b",
    yaw_deg: float = -90.0,
    cal: dict[str, Any] | None = None,
    gain_along: float = 0.60,
    gain_across: float = 0.0,
) -> tuple[float, float]:
    """Convert wrist camera offset (`along_mm`/`across_mm` or `dx_mm`/`dy_mm`) into cell-frame `(dx_m, dy_m)`."""
    if not obs:
        return 0.0, 0.0
    along_mm = float(obs.get("along_mm") if obs.get("along_mm") is not None else (obs.get("dx_mm") or 0.0))
    across_mm = float(obs.get("across_mm") if obs.get("across_mm") is not None else (obs.get("dy_mm") or 0.0))
    cal_dict = cal or {}
    default_sign = 1.0 if str(arm_id) == "arm_s" else -1.0
    finger_sign_map = cal_dict.get("finger_sign") or {}
    sign_along = float(finger_sign_map.get("along", default_sign))
    sign_across = float(finger_sign_map.get("across", 1.0))
    step_along_m = gain_along * sign_along * along_mm / 1000.0
    step_across_m = gain_across * sign_across * across_mm / 1000.0
    closing_rad = math.radians(float(yaw_deg) + 90.0)
    dx_m = step_along_m * math.cos(closing_rad) - step_across_m * math.sin(closing_rad)
    dy_m = step_along_m * math.sin(closing_rad) + step_across_m * math.cos(closing_rad)
    return round(dx_m, 6), round(dy_m, 6)


def apply_wrist_xy_step(
    xyz_m: list[float],
    obs: dict[str, Any] | None,
    *,
    arm_id: str = "arm_b",
    yaw_deg: float | None = None,
    pick_yaw_deg: float | None = None,
    cal: dict[str, Any] | None = None,
    gain_along: float | None = None,
    along_gain: float | None = None,
    gain_across: float = 0.0,
    use_direct_structural_gain: bool = False,
) -> list[float]:
    """Project `obs` wrist offset onto `xyz_m` and clamp within `arm_id`'s Cartesian workspace."""
    if use_direct_structural_gain and obs:
        dx_m = -0.50 * float(obs.get("dy_mm") or obs.get("across_mm") or 0.0) / 1000.0
        dy_m = -0.65 * float(obs.get("dx_mm") or obs.get("along_mm") or 0.0) / 1000.0
    else:
        eff_yaw = float(pick_yaw_deg if pick_yaw_deg is not None else (yaw_deg if yaw_deg is not None else -90.0))
        eff_gain = float(along_gain if along_gain is not None else (gain_along if gain_along is not None else 0.60))
        dx_m, dy_m = project_wrist_offset_xy_m(
            obs, arm_id=arm_id, yaw_deg=eff_yaw, cal=cal, gain_along=eff_gain, gain_across=gain_across
        )
    nx, ny = clamp_workspace_xy(float(xyz_m[0]) + dx_m, float(xyz_m[1]) + dy_m, arm_id=arm_id)
    return [nx, ny, round(float(xyz_m[2]), 5)]


def compute_stud_release_residual(
    wrist_obs: dict[str, Any] | None = None,
    *,
    tier: int = 3,
    retry_count: int = 0,
) -> dict[str, float]:
    """Compute last-millimeter TCP release correction `(dx_m, dy_m, dyaw_deg)` before seating,
    bounded by `MAX_RELEASE_RESIDUAL_XY_M` (±8mm) and `MAX_RELEASE_RESIDUAL_YAW_DEG` (±6.87 deg)."""
    obs = wrist_obs or {}
    along_mm = float(obs.get("along_mm") or 0.0)
    across_mm = float(obs.get("across_mm") or 0.0)
    skew_deg = float(obs.get("skew_deg") or 0.0)

    gain = 0.75 if int(tier) >= 3 else 0.85
    dx_m = -gain * (along_mm / 1000.0)
    dy_m = -gain * (across_mm / 1000.0)
    dyaw_deg = -0.8 * skew_deg

    wiggle_offsets = ((0.0, 0.0), (0.0012, -0.0008), (-0.0012, 0.0008), (0.0008, 0.0012))
    wx, wy = wiggle_offsets[int(retry_count) % len(wiggle_offsets)]
    dx_m = min(max(dx_m + wx, -MAX_RELEASE_RESIDUAL_XY_M), MAX_RELEASE_RESIDUAL_XY_M)
    dy_m = min(max(dy_m + wy, -MAX_RELEASE_RESIDUAL_XY_M), MAX_RELEASE_RESIDUAL_XY_M)
    dyaw_deg = min(max(dyaw_deg, -MAX_RELEASE_RESIDUAL_YAW_DEG), MAX_RELEASE_RESIDUAL_YAW_DEG)
    return {"dx_m": round(dx_m, 5), "dy_m": round(dy_m, 5), "dyaw_deg": round(dyaw_deg, 3)}


def predict_moving_belt_intercept(
    obs_t0: dict[str, float],
    obs_t1: dict[str, float],
    lead_time_s: float,
    *,
    arm_id: str = "arm_a",
    max_speed_m_s: float = 0.12,
    deadband_m: float = 0.0010,
    max_lateral_drift_m: float = 0.045,
) -> dict[str, Any]:
    """Predict dynamic belt intercept `(x, y)` from 2-frame top-camera observations `obs_t0` -> `obs_t1`."""
    t0, x0, y0 = float(obs_t0.get("t", 0.0)), float(obs_t0.get("x", 0.0)), float(obs_t0.get("y", 0.0))
    t1, x1, y1 = float(obs_t1.get("t", 0.0)), float(obs_t1.get("x", 0.0)), float(obs_t1.get("y", 0.0))
    lead = max(0.0, float(lead_time_s))
    dt = t1 - t0
    if not all(math.isfinite(v) for v in (t0, x0, y0, t1, x1, y1, lead)) or dt <= 1e-4:
        cx, cy = clamp_workspace_xy(x1, y1, arm_id=arm_id)
        return {
            "ok": False,
            "intercept_xy_m": (cx, cy),
            "velocity_xy_m_s": (0.0, 0.0),
            "speed_m_s": 0.0,
            "clamped": (cx, cy) != (round(x1, 4), round(y1, 4)),
            "abort_reason": "invalid_timestamps",
        }
    dx, dy = x1 - x0, y1 - y0
    dist = math.hypot(dx, dy)
    if dist < float(deadband_m):
        vx, vy, raw_speed = 0.0, 0.0, 0.0
    else:
        raw_speed = dist / dt
        scale = min(1.0, float(max_speed_m_s) / raw_speed) if raw_speed > 0.0 else 1.0
        vx, vy = (dx / dt) * scale, (dy / dt) * scale
    raw_px, raw_py = x1 + vx * lead, y1 + vy * lead
    lateral_drift = math.hypot(raw_px - x1, raw_py - y1)
    cx, cy = clamp_workspace_xy(raw_px, raw_py, arm_id=arm_id)
    clamped = abs(cx - raw_px) > 1e-4 or abs(cy - raw_py) > 1e-4
    abort_reason = None
    if raw_speed > float(max_speed_m_s):
        abort_reason = "belt_speed_exceeds_limit"
    elif lateral_drift > float(max_lateral_drift_m):
        abort_reason = "lateral_drift_exceeds_capture_window"
    return {
        "ok": abort_reason is None,
        "intercept_xy_m": (cx, cy),
        "velocity_xy_m_s": (round(vx, 4), round(vy, 4)),
        "speed_m_s": round(math.hypot(vx, vy), 4),
        "clamped": clamped,
        "abort_reason": abort_reason,
    }


def evaluate_tactile_place_compliance(
    r_desc_place: dict[str, Any],
    target_z_m: float,
    current_z_m: float | None = None,
    *,
    holding: bool = True,
    seating_band_m: float = 0.0025,
) -> dict[str, Any]:
    """Evaluate whether `run descend_place` completed cleanly or achieved compliant early tactile seating."""
    if bool(r_desc_place.get("ok")):
        return {
            "compliant": True,
            "early_touchdown": False,
            "z_error_mm": 0.0 if current_z_m is None else round((float(current_z_m) - float(target_z_m)) * 1000.0, 2),
            "reason": "full_descent_completed",
        }
    err_str = str(r_desc_place.get("error") or "")
    is_place_contact = ("contact in descend_place" in err_str) or bool(r_desc_place.get("soft_contact"))
    z_err_m = 0.0 if current_z_m is None else abs(float(current_z_m) - float(target_z_m))
    in_seating_band = z_err_m <= float(seating_band_m)
    if bool(holding) and is_place_contact and in_seating_band:
        return {
            "compliant": True,
            "early_touchdown": True,
            "z_error_mm": round(z_err_m * 1000.0, 2),
            "reason": "tactile_seating_band_touchdown",
        }
    return {
        "compliant": False,
        "early_touchdown": False,
        "z_error_mm": round(z_err_m * 1000.0, 2),
        "reason": "unsafe_high_collision_or_lost_hold",
    }


def infer_frame_dof(frame: Sequence[float]) -> int:
    """Infer arm degrees of freedom (`5`, `6`, or `7`) from a `(dof + 1)` frame ending with the gripper."""
    n = len(frame) - 1
    if n not in (5, 6, 7):
        raise ValueError(f"frame length {len(frame)} does not correspond to a 5/6/7-DOF arm + gripper")
    return n


from cell_directive_compiler import (  # noqa: E402, F401
    build_plan_from_directive,
    plan_library_from_directive,
    sim_precheck_and_optimize_directive,
)
from multi_dof_kinematics import (  # noqa: E402, F401
    DEFAULT_LIMITS_RAD,
    JOINT_NAMES_BY_DOF,
    fk_se3,
    manipulability_index,
    nullspace_velocity,
    numerical_jacobian,
    plan_se3_chunk,
    pose_error,
    solve_se3_ik,
)
