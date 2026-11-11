#!/usr/bin/env python3
"""`rosy-cell` executor for unified `AreaXYZ` directives from ROSY middleware (D-1014), with closed-loop grasp failure
recovery and multi-view (`top` + `side`) post-place task outcome verification.

Receives a `rosy.omx-cell-area-xyz-directive.v1` payload (constructed by `omx_adapter.area_xyz.build_directive`),
applies the per-arm calibration profile (`cell_arm_cal.py`, `arm-cal-<arm_id>.json`), plans top-down guarded chunks
via `grasp_planner.Planner`, executes closed-loop recovery when a grasp misses or is skewed (`diagnose_and_recover_pick`
+ `cell_grasp_debate.py`), and verifies physical task completion (`verify_stack_outcome`) on `top` and `side` camera
frames before reporting success.

The pre-defined target zones and their checks live in `cell_area_zones.py` (split at the 600-line cap, D-766 2)
and are re-exported here unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from cell_control_core import (  # noqa: F401  (re-exported: existing importers are unchanged)
    ADAPTER_ROOT,
    HERE,
    apply_wrist_xy_step,
    build_plan_from_directive,
    ensure_omx_paths,
    plan_library_from_directive,
    sim_precheck_and_optimize_directive,
)

ensure_omx_paths()

from omx_adapter.area_xyz import DIRECTIVE_SCHEMA, coerce_area_xyz  # noqa: E402
import cell_arm_cal  # noqa: E402
import cell_fingers  # noqa: E402
from cell_fleet_pipeline import execute_task_plan  # noqa: E402,F401  (re-exported)
import cell_grasp_debate as cgd  # noqa: E402
import cell_problem_pipeline as cpp  # noqa: E402
import grasp_planner  # noqa: E402,F401
from cell_area_zones import (  # noqa: E402,F401  (re-exported: existing importers are unchanged)
    SIDE_COL_CENTER_U,
    SIDE_M_PER_PX,
    SIDE_ROI_BY_COL_TIER,
    TOP_ROI_BY_COL_ROW,
    classify_container_orientation,
    diagnose_and_recover_pick,
    evaluate_zone,
    measure_side_gripper_zone_offset,
    normalize_pick_yaw_deg,
    verify_stack_outcome,
    warm_container_ratio,
)



def execute_directive(
    directive: dict[str, Any],
    *,
    base_plan: dict[str, Any],
    work_dir: Path,
    act_fn: Callable[[str], dict[str, Any]],
    frame_fn: Callable[[str], Any] | None = None,
    kinematics_root: Path | None = None,
    max_attempts: int = 3,
) -> dict[str, Any]:
    """Execute a `rosy.omx-cell-area-xyz-directive.v1` directive on `rosy-cell`, recovering from missed/skewed grasps and
    verifying physical task completion via `verify_stack_outcome`."""
    work_dir.mkdir(parents=True, exist_ok=True)
    arm_id = str(directive.get("arm_id") or "arm_b")
    cur_directive = json.loads(json.dumps(directive))
    cur_directive["pick"] = coerce_area_xyz(cur_directive["pick"])
    cur_directive["place"] = coerce_area_xyz(cur_directive["place"])
    orig_pick_xyz = list(cur_directive["pick"]["effective_xyz_m"])
    exec_cfg = dict(cur_directive.get("execution") or {})
    steps_log: list[dict[str, Any]] = []
    wrist_log: list[dict[str, Any]] = []
    debate_log: list[dict[str, Any]] = []
    recovery_log: list[dict[str, Any]] = []
    tried_xs: list[float] = []

    before_side = frame_fn("side") if frame_fn is not None else None
    before_top = frame_fn("top") if frame_fn is not None else None

    def _run_cmd(cmd: str) -> dict[str, Any]:
        r = dict(act_fn(cmd) or {})
        steps_log.append({"command": cmd, **r})
        return r

    def _safe_recover_hover(grip_open_val: float, *, park_after: bool = False) -> None:
        _run_cmd("retreat")
        _run_cmd(f"grip {min(57.85, float(grip_open_val)):.2f}")
        if steps_log and steps_log[-1].get("t") is not None:
            import time as _time
            _time.sleep(0.55)
        r_ab = _run_cmd("goto above_pick")
        if park_after or not r_ab.get("ok"):
            if steps_log and steps_log[-1].get("t") is not None:
                import time as _time
                _run_cmd("grip 55.80")
                _time.sleep(0.35)
            _run_cmd("park")

    for attempt in range(max_attempts):
        lib, plan, cal = plan_library_from_directive(cur_directive, base_plan, work_dir=work_dir, kinematics_root=kinematics_root)
        lib_path = work_dir / f"area-xyz-{cur_directive.get('directive_id', 'run')}-a{attempt}.library.json"
        lib_path.write_text(json.dumps(lib), encoding="utf-8")

        r_load = _run_cmd(f"load {lib_path}")
        if not r_load.get("ok"):
            _run_cmd("park")
            r_load = _run_cmd(f"load {lib_path}")
            if not r_load.get("ok"):
                return {"directive_id": cur_directive.get("directive_id"), "result": "fault", "at": "load", "pick": cur_directive["pick"], "place": cur_directive["place"], "steps": steps_log}

        r_above = _run_cmd("goto above_pick")
        if not r_above.get("ok"):
            _run_cmd("park")
            r_above = _run_cmd("goto above_pick")
            if not r_above.get("ok"):
                return {"directive_id": cur_directive.get("directive_id"), "result": "contact", "at": "goto above_pick", "pick": cur_directive["pick"], "place": cur_directive["place"], "steps": steps_log}

        # Ensure jaws have finished opening to grip_open at above_pick and any boom jitter has settled before descending
        above_state = r_above.get("state") or []
        above_shaking = bool((r_above.get("jitter") or {}).get("shaking"))
        if above_shaking or (len(above_state) >= 6 and above_state[5] is not None and float(above_state[5]) < float(plan["grip_open"]) - 1.0):
            r_settle = _run_cmd("run above_pick")
            s_state = r_settle.get("state") or []
            if steps_log and steps_log[-1].get("t") is not None and len(s_state) >= 6 and s_state[5] is not None and float(s_state[5]) < float(plan["grip_open"]) - 0.8:
                import time as _time
                _run_cmd(f"grip {float(plan['grip_open']):.2f}")
                _time.sleep(min(1.05, max(0.55, (float(plan["grip_open"]) - float(s_state[5])) / 4.0)))

        # Pre-pick target zone alignment using Side View + Wrist View
        last_wrist_obs = None
        vision_refined_xy = False
        if exec_cfg.get("vision_refine", False) and frame_fn is not None:
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
                    lib, plan, cal = plan_library_from_directive(cur_directive, base_plan, work_dir=work_dir, kinematics_root=kinematics_root)
                    lib_path.write_text(json.dumps(lib), encoding="utf-8")
                    _run_cmd(f"load {lib_path}")
                    _run_cmd("goto above_pick")

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
                obs = sorted(found_w, key=lambda o: float(o.get("along_mm", 0.0)))[len(found_w) // 2] if len(found_w) > 1 else w_obs_list[0]
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
                    lib, plan, cal = plan_library_from_directive(cur_directive, base_plan, work_dir=work_dir, kinematics_root=kinematics_root)
                    lib_path.write_text(json.dumps(lib), encoding="utf-8")
                    _run_cmd(f"load {lib_path}")
                    r_above2 = _run_cmd("goto above_pick")
                    s2 = r_above2.get("state") or []
                    if len(s2) >= 6 and s2[5] is not None and float(s2[5]) < float(plan["grip_open"]) - 1.2:
                        import time as _time
                        _run_cmd(f"grip {float(plan['grip_open']):.2f}")
                        _time.sleep(0.22)

        r_desc = _run_cmd("run descend_pick")
        if not r_desc.get("ok"):
            if attempt + 1 < max_attempts:
                _safe_recover_hover(float(plan["grip_open"]), park_after=False)
                rec = diagnose_and_recover_pick(attempt=attempt, cur_directive=cur_directive, r_desc=r_desc, r_grasp={}, cal=cal, tried_xs=tried_xs, wrist_obs=None if vision_refined_xy else last_wrist_obs)
                recovery_log.append(rec)
                continue
            _safe_recover_hover(float(plan["grip_open"]), park_after=not bool(exec_cfg.get("stay_in_hover", False)))
            return {"directive_id": cur_directive.get("directive_id"), "result": "contact", "at": "run descend_pick", "pick": cur_directive["pick"], "place": cur_directive["place"], "recovery": recovery_log, "steps": steps_log}

        r_grasp = _run_cmd("run grasp_pick")
        state = r_grasp.get("state") or []
        jaw_pos = float(state[5]) if len(state) >= 6 and state[5] is not None else None
        curr_ma = r_grasp.get("gripper_current_ma")
        closed_pos = float(cal.get("grip_closed", 48.8))
        open_pos = float(plan.get("grip_open", 57.85))
        grasp_dynamics = cell_arm_cal.evaluate_grasp_dynamics(r_grasp, closed=closed_pos, open_pos=open_pos, held_30mm=float(cal.get("held_30mm", 53.5)), baseline_current_ma=float(cal.get("hold_current_ma", 80.0)))
        holding = bool(r_grasp.get("ok")) and (cell_arm_cal.infer_holding(r_grasp, closed=closed_pos, open_pos=open_pos) or bool(grasp_dynamics.get("holding")))

        # Schema v2 grasp stability deliberation
        if exec_cfg.get("grasp_deliberation", True) and jaw_pos is not None:
            params = {
                "gripper.held_30mm": float(cal.get("held_30mm", 54.3)),
                "gripper.closed": float(cal.get("grip_closed", 48.8)),
                "grasp.shallow_tol_units": float(exec_cfg.get("shallow_tol_units", 2.2)),
                "grasp.wedged_tol_units": float(exec_cfg.get("wedged_tol_units", 2.5)),
                "grasp.max_skew_mm": 5.5,
                "wrist.finger_color": 2 if cal.get("finger_color") == "white" else 1,
            }
            t_judge = cgd.telemetry_judge(state, holding, params, current_ma=curr_ma)
            v_judge = {"status": "skipped", "ok": True, "along_mm": 0.0, "across_mm": 0.0}
            d_res = cgd.debate_and_decide(stage="run grasp_pick", telemetry=t_judge, vision=v_judge, reinsert_count=attempt, max_reinsert=max_attempts - 1, models=[])
            debate_log.append(d_res)
            if d_res["verdict"] == "reinsert_and_retry" and attempt + 1 < max_attempts:
                r_rel = _run_cmd("run release_pick") if r_grasp.get("ok") else {"ok": False}
                if not r_rel.get("ok"):
                    _safe_recover_hover(float(plan["grip_open"]), park_after=False)
                rec = diagnose_and_recover_pick(attempt=attempt, cur_directive=cur_directive, r_desc=r_desc, r_grasp=r_grasp, cal=cal, tried_xs=tried_xs, wrist_obs=None if vision_refined_xy else last_wrist_obs)
                recovery_log.append(rec)
                continue

        if not holding:
            r_rel = (_run_cmd("run release_pick") if (r_grasp.get("ok") and not exec_cfg.get("stay_in_hover", False)) else {"ok": False})
            if attempt + 1 < max_attempts:
                if not r_rel.get("ok"):
                    _safe_recover_hover(float(plan["grip_open"]), park_after=False)
                rec = diagnose_and_recover_pick(attempt=attempt, cur_directive=cur_directive, r_desc=r_desc, r_grasp=r_grasp, cal=cal, tried_xs=tried_xs, wrist_obs=None if vision_refined_xy else last_wrist_obs)
                recovery_log.append(rec)
                continue
            if not r_rel.get("ok"):
                _safe_recover_hover(float(plan["grip_open"]), park_after=not bool(exec_cfg.get("stay_in_hover", False)))
            elif not exec_cfg.get("stay_in_hover", False):
                _run_cmd("park")
            out_empty = {"directive_id": cur_directive.get("directive_id"), "result": "empty", "task_verified": False, "at": "run grasp_pick", "pick": cur_directive["pick"], "place": cur_directive["place"], "recovery": recovery_log, "steps": steps_log}
            cpp.capture_from_attempt({"_work": work_dir, "arm_id": arm_id}, out_empty)
            return out_empty

        # Update and persist per-arm calibration profile on verified grasp
        updated_cal = cell_arm_cal.record_grasp_measurement(
            work_dir,
            arm_id=arm_id,
            gripper_pos=jaw_pos,
            gripper_current_ma=curr_ma,
            width_mm=30.0,
            skew_mm=wrist_log[-1].get("along_mm") if wrist_log and wrist_log[-1].get("found") else None,
            mm_per_px=wrist_log[-1].get("mm_per_px") if wrist_log and wrist_log[-1].get("found") else None,
            finger_color=cal.get("finger_color"),
        )

        slipped_in_transfer = False
        held_at_above_place = False
        tactile_or_full_place = False
        r_lift_step = None
        stay_hover = bool(exec_cfg.get("stay_in_hover", False))
        place_seq = ("run lift_pick", "goto above_place", "run descend_place", "run release_place", "run lift_place") + (() if stay_hover else ("park",))
        for chunk_cmd in place_seq:
            r_step = _run_cmd(chunk_cmd)
            if chunk_cmd in ("run lift_pick", "goto above_place"):
                if chunk_cmd == "run lift_pick":
                    r_lift_step = r_step
                    grasp_dynamics = cell_arm_cal.evaluate_grasp_dynamics(r_grasp, r_lift=r_lift_step, closed=closed_pos, open_pos=open_pos)
                else:
                    grasp_dynamics = cell_arm_cal.evaluate_grasp_dynamics(r_grasp, r_lift=r_lift_step, r_above_place=r_step, closed=closed_pos, open_pos=open_pos)
                if not grasp_dynamics.get("holding") and not cell_arm_cal.infer_holding(r_step, closed=closed_pos, min_units_above_closed=2.5, min_current_ma=40.0, prev_grasp=r_grasp, prev_lift=r_lift_step if chunk_cmd == "goto above_place" else None, open_pos=open_pos):
                    slipped_in_transfer = True
                    if not r_step.get("ok") or (attempt + 1 >= max_attempts and not stay_hover):
                        _run_cmd("goto above_place")
                        _run_cmd("park")
                    break
                if chunk_cmd == "goto above_place":
                    held_at_above_place = True
            if chunk_cmd == "run descend_place" and r_step.get("ok"):
                tactile_or_full_place = True
            if not r_step.get("ok"):
                if chunk_cmd == "run descend_place" and "contact in descend_place" in str(r_step.get("error") or ""):
                    tactile_or_full_place = True
                    _run_cmd(f"grip {float(plan['grip_release']):.2f}")
                    if frame_fn is not None and not stay_hover:
                        import time as _time
                        _time.sleep(0.55)
                    _run_cmd("retreat")
                    if not stay_hover:
                        _run_cmd("park")
                    break
                if chunk_cmd != "park":
                    _safe_recover_hover(float(plan["grip_open"]), park_after=not stay_hover)
                if chunk_cmd not in ("run lift_place", "park"):
                    out_err = {
                        "directive_id": cur_directive.get("directive_id"),
                        "result": "contact",
                        "task_verified": False,
                        "at": chunk_cmd,
                        "error": r_step.get("error"),
                        "pick": cur_directive["pick"],
                        "place": cur_directive["place"],
                        "recovery": recovery_log,
                        "steps": steps_log,
                    }
                    cpp.capture_from_attempt({"_work": work_dir, "arm_id": arm_id}, out_err)
                    return out_err

        if slipped_in_transfer:
            if attempt + 1 < max_attempts:
                if vision_refined_xy:
                    cur_directive["pick"]["effective_xyz_m"][0] = orig_pick_xyz[0]
                    cur_directive["pick"]["effective_xyz_m"][1] = orig_pick_xyz[1]
                    cur_directive["pick"]["x"] = orig_pick_xyz[0]
                    cur_directive["pick"]["y"] = orig_pick_xyz[1]
                    exec_cfg["vision_refine"] = False
                rec = diagnose_and_recover_pick(
                    attempt=attempt,
                    cur_directive=cur_directive,
                    r_desc=r_desc,
                    r_grasp=r_grasp,
                    cal=cal,
                    tried_xs=tried_xs,
                    wrist_obs=None,
                    slipped_in_transfer=True,
                )
                recovery_log.append(rec)
                continue
            out_slip = {
                "schema": DIRECTIVE_SCHEMA,
                "directive_id": cur_directive.get("directive_id"),
                "arm_id": arm_id,
                "result": "slipped_in_transfer",
                "task_verified": False,
                "grasp_dynamics": grasp_dynamics,
                "pick": cur_directive["pick"],
                "place": cur_directive["place"],
                "recovery": recovery_log,
                "wrist": wrist_log,
                "steps": steps_log,
            }
            cpp.capture_from_attempt({"_work": work_dir, "arm_id": arm_id}, out_slip)
            return out_slip

        after_side = frame_fn("side") if (frame_fn is not None and not stay_hover) else None
        after_top = frame_fn("top") if (frame_fn is not None and not stay_hover) else None
        verification = verify_stack_outcome(
            before_side=before_side,
            after_side=after_side,
            before_top=before_top,
            after_top=after_top,
            pick=cur_directive["pick"],
            place=cur_directive["place"],
        )
        if not verification["verified"] and exec_cfg.get("proprioceptive_verify", False) and held_at_above_place and tactile_or_full_place:
            verification["verified"] = True
            verification["reason"] = "proprioceptive_tactile_stack_verified"
        if not verification["verified"] and attempt + 1 < max_attempts and exec_cfg.get("retry_on_unverified_place", True):
            rec = diagnose_and_recover_pick(
                attempt=attempt,
                cur_directive=cur_directive,
                r_desc=r_desc,
                r_grasp=r_grasp,
                cal=cal,
                tried_xs=tried_xs,
                wrist_obs=None,
                slipped_in_transfer=True,
            )
            rec["verification_reason"] = verification["reason"]
            recovery_log.append(rec)
            continue

        out_final = {
            "schema": DIRECTIVE_SCHEMA,
            "directive_id": cur_directive.get("directive_id"),
            "arm_id": arm_id,
            "result": "placed" if verification["verified"] else "unverified_place",
            "task_verified": verification["verified"],
            "verification": verification,
            "pick": cur_directive["pick"],
            "place": cur_directive["place"],
            "gripper_pos": jaw_pos,
            "gripper_current_ma": curr_ma,
            "grasp_dynamics": grasp_dynamics,
            "calibration": updated_cal,
            "recovery": recovery_log,
            "wrist": wrist_log,
            "grasp_debate": debate_log,
            "steps": steps_log,
        }
        if not verification["verified"]:
            cpp.capture_from_attempt({"_work": work_dir, "arm_id": arm_id}, out_final)
        return out_final

    return {"directive_id": cur_directive.get("directive_id"), "result": "stopped", "task_verified": False, "recovery": recovery_log, "steps": steps_log}

