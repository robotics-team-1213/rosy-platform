#!/usr/bin/env python3
"""Pre-pick Visual Zone Alignment & Hover Settle (`cell_area_vision_align.py`).

Single Responsibility:
  - Settle boom jitter and verify gripper opening (`state[-1]` across 5/6/7-DOF) at `above_pick` (`settle_above_pick_jaws`).
  - Refine pick `(x, y)` using Side-View column zone snap and multi-sample Wrist-View servo offset (`refine_pick_pose_at_hover`).
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable

import cell_arm_cal
from cell_area_zones import measure_side_gripper_zone_offset
from cell_control_core import apply_wrist_xy_step, plan_library_from_directive
import cell_fingers


class RefinementCommandFailed(RuntimeError):
    pass


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
        if not r_settle.get("ok"):
            raise RefinementCommandFailed("above_pick_settle_failed")
        s_jaw = _jaw_pos(r_settle.get("state") or [])
        if (
            steps_log
            and steps_log[-1].get("t") is not None
            and s_jaw is not None
            and s_jaw < float(plan["grip_open"]) - 0.8
        ):
            import time as _time

            if not run_cmd(f"grip {float(plan['grip_open']):.2f}").get("ok"):
                raise RefinementCommandFailed("above_pick_grip_failed")
            _time.sleep(min(0.30, max(0.12, (float(plan["grip_open"]) - s_jaw) / 8.0)))
    return above_shaking


def _replan_and_hover(
    cur_directive: dict[str, Any],
    p_xyz: list[float],
    base_plan: dict[str, Any],
    work_dir: Path,
    kinematics_root: Path | None,
    lib_path: Path,
    run_cmd: Callable[[str], dict[str, Any]],
    fail_prefix: str = "refined",
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    cur_directive["pick"].update(x=p_xyz[0], y=p_xyz[1], effective_xyz_m=list(p_xyz))
    lib, plan, cal = plan_library_from_directive(
        cur_directive, base_plan, work_dir=work_dir, kinematics_root=kinematics_root
    )
    lib_path.write_text(json.dumps(lib), encoding="utf-8")
    if not run_cmd(f"load {lib_path}").get("ok"):
        raise RefinementCommandFailed(f"{fail_prefix}_library_load_failed")
    r_above = run_cmd("goto above_pick")
    if not r_above.get("ok"):
        raise RefinementCommandFailed(f"{fail_prefix}_above_pick_failed")
    return lib, plan, cal, r_above


def _persist_wrist_signs(work_dir: Path, arm_id: str, cal: dict[str, Any], obs: dict[str, Any]) -> None:
    try:
        fc = obs.get("finger_color") or cal.get("finger_color")
        cell_arm_cal.record_wrist_observation(
            work_dir,
            arm_id=arm_id,
            finger_color=fc if fc in ("dark", "white") else None,
            finger_sign=cal.get("finger_sign"),
        )
    except OSError:
        pass


def _wrist_err(obs: dict[str, Any], gain_across: float) -> float:
    return math.hypot(float(obs.get("along_mm", 0.0)), float(obs.get("across_mm", 0.0)) if gain_across > 0.0 else 0.0)


def _apply_wrist_sanity(wo: dict[str, Any]) -> dict[str, Any]:
    gpx, mpx = wo.get("gap_px"), wo.get("mm_per_px")
    if wo.get("found") and ((gpx is not None and float(gpx) < 32.0) or (mpx is not None and not (0.06 <= float(mpx) <= 0.35))
                            or abs(float(wo.get("along_mm") or 0.0)) > 35.0 or abs(float(wo.get("across_mm") or 0.0)) > 55.0):
        wo.update(found=False, why="wrist_sanity_rejected")
    return wo


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

    default_across = 0.0 if str(arm_id) == "arm_s" else 0.60
    gain_across = float(exec_cfg.get("wrist_gain_across", 0.60 if exec_cfg.get("wrist_servo_across") else default_across))
    col = int(cur_directive["pick"].get("col") or 3)
    p_xyz_cur = list(cur_directive["pick"]["effective_xyz_m"])
    canonical_col_x = {1: 0.1280, 2: 0.1580, 3: 0.1935}.get(col, 0.1580)
    p_xyz = list(p_xyz_cur)
    need_replan = False
    wrist_shifted = False
    if (
        exec_cfg.get("side_zone_snap", True)
        and p_xyz_cur[0] >= 0.118
        and abs(float(plan["pick"].get("yaw_deg", -90.0)) + 90.0) <= 5.0
        and abs(p_xyz_cur[0] - canonical_col_x) <= 0.008
    ):
        s_img = frame_fn("side")
        if s_img is not None:
            side_obs = measure_side_gripper_zone_offset(s_img, before_side, col, tol_u_px=10.0)
            if side_obs.get("found") and side_obs.get("within_zone") and abs(float(side_obs.get("dx_m", 0.0))) >= 0.0018:
                p_xyz[0] = round(max(0.08, min(0.245, p_xyz[0] + float(side_obs["dx_m"]))), 4)
                need_replan = True

    pre_wrist_xyz = list(p_xyz)
    first_obs: dict[str, Any] | None = None
    err0: float | None = None
    n_wrist = max(1, int(exec_cfg.get("wrist_samples", 3 if above_shaking else 1)))
    w_img = frame_fn("wrist")
    if w_img is not None:
        w_obs_list = [
            _apply_wrist_sanity(cell_fingers.resolve_wrist_servo_offset(
                w_img if w_i == 0 else (frame_fn("wrist") or w_img),
                cal,
                prefer_structural=bool(exec_cfg.get("structural_wrist")),
            ))
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
        obs_active_mm = max(abs(float(obs.get("along_mm", 0.0))), abs(float(obs.get("across_mm", 0.0))) if gain_across > 0.0 else 0.0)
        if obs.get("found") and 1.5 < obs_active_mm <= max_wrist_mm:
            first_obs = obs
            err0 = _wrist_err(obs, gain_across)
            p_xyz = apply_wrist_xy_step(
                p_xyz, obs, arm_id=arm_id, cal=cal, yaw_deg=float(plan["pick"].get("yaw_deg", -90.0)), gain_along=0.60, gain_across=gain_across,
            )
            need_replan = True
            wrist_shifted = True
    if need_replan:
        vision_refined_xy = True
        lib, plan, cal, r_above2 = _replan_and_hover(
            cur_directive, p_xyz, base_plan, work_dir, kinematics_root, lib_path, run_cmd, "refined",
        )
        s2_jaw = _jaw_pos(r_above2.get("state") or [])
        if s2_jaw is not None and s2_jaw < float(plan["grip_open"]) - 1.2:
            import time as _time

            if not run_cmd(f"grip {float(plan['grip_open']):.2f}").get("ok"):
                raise RefinementCommandFailed("refined_grip_failed")
            _time.sleep(0.22)
    for pass_idx in range(1, max(1, int(exec_cfg.get("wrist_passes", 1))) if wrist_shifted else 1):
        w_img = frame_fn("wrist")
        if w_img is None:
            break
        obs = _apply_wrist_sanity(cell_fingers.resolve_wrist_servo_offset(w_img, cal, prefer_structural=bool(exec_cfg.get("structural_wrist"))))
        last_wrist_obs = obs
        wrist_log.append(obs)
        err1 = _wrist_err(obs, gain_across) if obs.get("found") else None
        if pass_idx == 1 and first_obs is not None and err0 is not None:
            if err1 is not None and err1 > err0 + 1.0:
                flipped = dict(cal.get("finger_sign") or {"along": 1.0, "across": 1.0})
                flip_a = abs(float(obs.get("along_mm", 0.0))) > abs(float(first_obs.get("along_mm", 0.0))) + 0.5
                flip_c = gain_across > 0.0 and abs(float(obs.get("across_mm", 0.0))) > abs(float(first_obs.get("across_mm", 0.0))) + 0.5
                if flip_a or not flip_c:
                    flipped["along"] = -float(flipped.get("along", 1.0))
                if flip_c:
                    flipped["across"] = -float(flipped.get("across", 1.0))
                cal = dict(cal, finger_sign=flipped)
                flipped_xyz = apply_wrist_xy_step(
                    pre_wrist_xyz, first_obs, arm_id=arm_id, cal=cal, yaw_deg=float(plan["pick"].get("yaw_deg", -90.0)), gain_along=0.60, gain_across=gain_across,
                )
                lib, plan, new_cal, _ = _replan_and_hover(
                    cur_directive, flipped_xyz, base_plan, work_dir, kinematics_root, lib_path, run_cmd, "refined",
                )
                cal = dict(new_cal, finger_sign=flipped)
                w_flip = frame_fn("wrist")
                obs_flip = _apply_wrist_sanity(cell_fingers.resolve_wrist_servo_offset(w_flip, cal, prefer_structural=bool(exec_cfg.get("structural_wrist")))) if w_flip is not None else None
                err_flip = _wrist_err(obs_flip, gain_across) if (obs_flip and obs_flip.get("found")) else None
                if obs_flip and err_flip is not None and err_flip < err0:
                    p_xyz = flipped_xyz
                    tagged = {**obs_flip, "sign_flipped": True, "finger_sign": dict(flipped)}
                    wrist_log.append(tagged)
                    last_wrist_obs = tagged
                    _persist_wrist_signs(work_dir, arm_id, cal, tagged)
                    break
                p_xyz = list(pre_wrist_xyz)
                lib, plan, cal, _ = _replan_and_hover(
                    cur_directive, p_xyz, base_plan, work_dir, kinematics_root, lib_path, run_cmd, "refined",
                )
                vision_refined_xy = False
                rev_obs = {**obs, "found": False, "reverted": True}
                wrist_log[-1] = rev_obs
                last_wrist_obs = rev_obs
                break
            if err1 is not None and err1 < err0 - 1.0 and int(cal.get("samples", 0)) == 0:
                _persist_wrist_signs(work_dir, arm_id, cal, obs)
        max_wrist_mm = float(exec_cfg.get("max_wrist_shift_mm", 24.0 if obs.get("clipped_border") else 8.5))
        obs_active_mm = max(abs(float(obs.get("along_mm", 0.0))), abs(float(obs.get("across_mm", 0.0))) if gain_across > 0.0 else 0.0)
        if not obs.get("found") or not 1.5 < obs_active_mm <= max_wrist_mm:
            break
        p_xyz = apply_wrist_xy_step(p_xyz, obs, arm_id=arm_id, cal=cal, yaw_deg=float(plan["pick"].get("yaw_deg", -90.0)), gain_along=0.60, gain_across=gain_across)
        lib, plan, cal, _ = _replan_and_hover(
            cur_directive, p_xyz, base_plan, work_dir, kinematics_root, lib_path, run_cmd, "refined",
        )
    return lib, plan, cal, last_wrist_obs, vision_refined_xy
