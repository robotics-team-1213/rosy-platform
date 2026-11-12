#!/usr/bin/env python3
"""Pre-pick Visual Zone Alignment & Hover Settle (`cell_area_vision_align.py`).

Single Responsibility:
  - Settle boom jitter and verify gripper opening (`state[-1]` across 5/6/7-DOF) at `above_pick` (`settle_above_pick_jaws`).
  - Refine pick `(x, y)` using Side-View column zone snap and multi-sample Wrist-View servo offset (`refine_pick_pose_at_hover`).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from cell_area_zones import measure_side_gripper_zone_offset
from cell_control_core import apply_wrist_xy_step, plan_library_from_directive
import cell_fingers


def _jaw_pos(state: list[Any] | tuple[Any, ...] | None) -> float | None:
    """Extract gripper position from a 5/6/7-DOF state vector (`len >= 6`, last element is gripper)."""
    if state and len(state) >= 6 and state[-1] is not None:
        return float(state[-1])
    return None


def settle_above_pick_jaws(
    r_above: dict[str, Any],
    plan: dict[str, Any],
    run_cmd: Callable[[str], dict[str, Any]],
    steps_log: list[dict[str, Any]],
) -> bool:
    """Ensure jaws have finished opening to `grip_open` at `above_pick` and boom jitter has settled."""
    above_state = r_above.get("state") or []
    above_shaking = bool((r_above.get("jitter") or {}).get("shaking"))
    jaw = _jaw_pos(above_state)
    if above_shaking or (jaw is not None and jaw < float(plan["grip_open"]) - 1.0):
        r_settle = run_cmd("run above_pick")
        s_jaw = _jaw_pos(r_settle.get("state") or [])
        if (
            steps_log
            and steps_log[-1].get("t") is not None
            and s_jaw is not None
            and s_jaw < float(plan["grip_open"]) - 0.8
        ):
            import time as _time

            run_cmd(f"grip {float(plan['grip_open']):.2f}")
            _time.sleep(min(1.05, max(0.55, (float(plan["grip_open"]) - s_jaw) / 4.0)))
    return above_shaking


def refine_pick_pose_at_hover(
    *,
    cur_directive: dict[str, Any],
    base_plan: dict[str, Any],
    lib: dict[str, Any],
    plan: dict[str, Any],
    cal: dict[str, Any],
    lib_path: Path,
    work_dir: Path,
    kinematics_root: Path | None,
    arm_id: str,
    exec_cfg: dict[str, Any],
    frame_fn: Callable[[str], Any] | None,
    before_side: Any,
    above_shaking: bool,
    run_cmd: Callable[[str], dict[str, Any]],
    wrist_log: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any] | None, bool]:
    """Run Side-View zone snap and Wrist-View servo alignment at `above_pick`."""
    last_wrist_obs = None
    vision_refined_xy = False
    if not (exec_cfg.get("vision_refine", False) and frame_fn is not None):
        return lib, plan, cal, last_wrist_obs, vision_refined_xy

    col = int(cur_directive["pick"].get("col") or 3)
    p_xyz_cur = list(cur_directive["pick"]["effective_xyz_m"])
    canonical_col_x = {1: 0.1280, 2: 0.1580, 3: 0.1935}.get(col, 0.1580)
    if (
        exec_cfg.get("side_zone_snap", True)
        and p_xyz_cur[0] >= 0.118
        and abs(float(plan["pick"].get("yaw_deg", -90.0)) + 90.0) <= 5.0
        and abs(p_xyz_cur[0] - canonical_col_x) <= 0.008
    ):
        s_img = frame_fn("side")
        side_obs = measure_side_gripper_zone_offset(s_img, before_side, col, tol_u_px=10.0)
        if side_obs.get("found") and not side_obs.get("within_zone"):
            p_xyz = list(cur_directive["pick"]["effective_xyz_m"])
            p_xyz[0] = round(max(0.118, min(0.205, p_xyz[0] + float(side_obs["dx_m"]))), 5)
            cur_directive["pick"]["effective_xyz_m"] = p_xyz
            cur_directive["pick"]["x"] = p_xyz[0]
            lib, plan, cal = plan_library_from_directive(
                cur_directive, base_plan, work_dir=work_dir, kinematics_root=kinematics_root
            )
            lib_path.write_text(json.dumps(lib), encoding="utf-8")
            run_cmd(f"load {lib_path}")
            run_cmd("goto above_pick")

    n_wrist = max(1, int(exec_cfg.get("wrist_samples", 3 if above_shaking else 1)))
    w_img = frame_fn("wrist")
    if w_img is not None:
        w_obs_list = [
            cell_fingers.resolve_wrist_servo_offset(
                w_img if w_i == 0 else (frame_fn("wrist") or w_img),
                cal,
                prefer_structural=bool(exec_cfg.get("structural_wrist")),
            )
            for w_i in range(n_wrist)
        ]
        found_w = [o for o in w_obs_list if o.get("found")]
        obs = (
            sorted(found_w, key=lambda o: float(o.get("along_mm", 0.0)))[len(found_w) // 2]
            if len(found_w) > 1
            else w_obs_list[0]
        )
        last_wrist_obs = obs
        wrist_log.append(obs)
        max_wrist_mm = float(exec_cfg.get("max_wrist_shift_mm", 24.0 if obs.get("clipped_border") else 8.5))
        if obs.get("found") and 1.5 < abs(float(obs.get("along_mm", 0.0))) <= max_wrist_mm:
            p_xyz = apply_wrist_xy_step(
                list(cur_directive["pick"]["effective_xyz_m"]),
                obs,
                arm_id=arm_id,
                cal=cal,
                yaw_deg=float(plan["pick"].get("yaw_deg", -90.0)),
                gain_along=0.60,
            )
            cur_directive["pick"]["effective_xyz_m"] = p_xyz
            cur_directive["pick"]["x"] = p_xyz[0]
            cur_directive["pick"]["y"] = p_xyz[1]
            vision_refined_xy = True
            lib, plan, cal = plan_library_from_directive(
                cur_directive, base_plan, work_dir=work_dir, kinematics_root=kinematics_root
            )
            lib_path.write_text(json.dumps(lib), encoding="utf-8")
            run_cmd(f"load {lib_path}")
            r_above2 = run_cmd("goto above_pick")
            s2_jaw = _jaw_pos(r_above2.get("state") or [])
            if s2_jaw is not None and s2_jaw < float(plan["grip_open"]) - 1.2:
                import time as _time

                run_cmd(f"grip {float(plan['grip_open']):.2f}")
                _time.sleep(0.22)
    return lib, plan, cal, last_wrist_obs, vision_refined_xy
