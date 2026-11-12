#!/usr/bin/env python3
"""`rosy-cell` executor for unified `AreaXYZ` directives from ROSY middleware (D-1014), with closed-loop grasp failure
recovery, 6-Gate Execution Interlock (`cell_spec_recovery_fsm`), and multi-view (`top` + `side`) post-place verification.

Single Responsibility:
  - Closed-loop pick-transfer-place state machine (`execute_directive`) for 5/6/7-DOF arms.
  - Pre-pick visual zone & wrist servo alignment lives in `cell_area_vision_align.py`.
  - Pre-defined target zones and recovery rules live in `cell_area_zones.py` and are re-exported here unchanged.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from cell_control_core import (  # noqa: F401  (re-exported: existing importers are unchanged)
    ADAPTER_ROOT, HERE, apply_wrist_xy_step, build_crane_standby_transition, build_plan_from_directive,
    ensure_omx_paths, evaluate_tactile_place_compliance, plan_library_from_directive,
    predict_moving_belt_intercept, redirect_place_on_zone_obstruction,
    sim_precheck_and_optimize_directive,
)

ensure_omx_paths()

from omx_adapter.area_xyz import DIRECTIVE_SCHEMA, coerce_area_xyz  # noqa: E402
from cell_area_vision_align import _jaw_pos, refine_pick_pose_at_hover, settle_above_pick_jaws  # noqa: E402,F401
from cell_area_zones import (  # noqa: E402,F401  (re-exported: existing importers are unchanged)
    SIDE_COL_CENTER_U, SIDE_M_PER_PX, SIDE_ROI_BY_COL_TIER, TEMP_PLATE_TOP_ROI_BY_LANE, TOP_ROI_BY_COL_ROW,
    classify_container_orientation, diagnose_and_recover_pick, evaluate_zone,
    measure_side_gripper_zone_offset, normalize_pick_yaw_deg, verify_stack_outcome,
    verify_stack_outcome_z_mm, warm_container_ratio,
)
import cell_arm_cal  # noqa: E402
import cell_fingers  # noqa: E402,F401
from cell_fleet_pipeline import execute_task_plan  # noqa: E402,F401  (re-exported)
import cell_grasp_debate as cgd  # noqa: E402
import cell_problem_pipeline as cpp  # noqa: E402
from cell_spec_recovery_fsm import (  # noqa: E402,F401
    compile_recenter_on_temp_directives, evaluate_execution_gate, select_recovery_skill,
)
from cell_z_profile import (  # noqa: E402,F401
    calibrate_z_profile_mm, capture_top_depth_z16, default_z_profile_mm, judge_z_axis_alignment_mm,
    measure_ik_tracking_mm, measure_side_gripper_pose_mm, perceive_slot_z_mm, perceive_visual_distance_mm,
)
import grasp_planner  # noqa: E402,F401


def _build_vision_judge(last_wrist_obs: dict[str, Any] | None, max_skew_mm: float) -> dict[str, Any]:
    if isinstance(last_wrist_obs, dict) and last_wrist_obs.get("found"):
        along_mm = round(float(last_wrist_obs.get("along_mm") or 0.0), 2)
        across_mm = round(float(last_wrist_obs.get("across_mm") or 0.0), 2)
        skew_ok = abs(along_mm) <= float(max_skew_mm)
        return {
            "status": "measured", "ok": skew_ok, "found": True,
            "along_mm": along_mm, "across_mm": across_mm,
            "verdict": "proceed" if skew_ok else "reinsert",
            "class": "centered" if skew_ok else "unstable_skewed",
            "confidence": 0.85 if skew_ok else 0.88,
            "why": f"wrist skew along={along_mm}mm across={across_mm}mm (max={max_skew_mm}mm)",
        }
    return {"status": "skipped", "ok": True, "along_mm": 0.0, "across_mm": 0.0}


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
    import json

    work_dir.mkdir(parents=True, exist_ok=True)
    arm_id = str(directive.get("arm_id") or "arm_b")
    from cell_directive_compiler import _clone

    cur_directive = _clone(directive)
    cur_directive["pick"] = coerce_area_xyz(cur_directive["pick"])
    cur_directive["place"] = coerce_area_xyz(cur_directive["place"])
    orig_pick_xyz = list(cur_directive["pick"]["effective_xyz_m"])
    exec_cfg = dict(cur_directive.get("execution") or {})
    steps_log: list[dict[str, Any]] = []
    wrist_log: list[dict[str, Any]] = []
    debate_log: list[dict[str, Any]] = []
    recovery_log: list[dict[str, Any]] = []
    gate_trace: list[dict[str, Any]] = []
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
            _time.sleep(0.20)
        r_ab = _run_cmd("goto above_pick")
        if park_after or not r_ab.get("ok"):
            if steps_log and steps_log[-1].get("t") is not None:
                import time as _time
                _run_cmd("grip 55.80")
                _time.sleep(0.20)
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
                return {"directive_id": cur_directive.get("directive_id"), "result": "fault", "at": "load",
                        "pick": cur_directive["pick"], "place": cur_directive["place"], "gate_trace": gate_trace, "steps": steps_log}

        r_above = _run_cmd("goto above_pick")
        if not r_above.get("ok"):
            _run_cmd("park")
            r_above = _run_cmd("goto above_pick")
            if not r_above.get("ok"):
                return {"directive_id": cur_directive.get("directive_id"), "result": "contact", "at": "goto above_pick",
                        "pick": cur_directive["pick"], "place": cur_directive["place"], "gate_trace": gate_trace, "steps": steps_log}

        above_shaking = settle_above_pick_jaws(r_above, plan, _run_cmd, steps_log)
        lib, plan, cal, last_wrist_obs, vision_refined_xy = refine_pick_pose_at_hover(
            cur_directive=cur_directive, base_plan=base_plan, lib=lib, plan=plan, cal=cal, lib_path=lib_path,
            work_dir=work_dir, kinematics_root=kinematics_root, arm_id=arm_id, exec_cfg=exec_cfg, frame_fn=frame_fn,
            before_side=before_side, above_shaking=above_shaking, run_cmd=_run_cmd, wrist_log=wrist_log,
        )

        r_desc = _run_cmd("run descend_pick")
        if not r_desc.get("ok"):
            g_desc = evaluate_execution_gate("at_grasp", r_step=r_desc)
            gate_trace.append(g_desc)
            if attempt + 1 < max_attempts:
                _safe_recover_hover(float(plan["grip_open"]), park_after=False)
                rec = diagnose_and_recover_pick(attempt=attempt, cur_directive=cur_directive, r_desc=r_desc, r_grasp={},
                                                cal=cal, tried_xs=tried_xs, wrist_obs=None if vision_refined_xy else last_wrist_obs)
                rec["recovery_skill"] = select_recovery_skill("S7_DESCEND_OR_GRASP_CONTACT", level_tried=attempt)
                recovery_log.append(rec)
                continue
            _safe_recover_hover(float(plan["grip_open"]), park_after=not bool(exec_cfg.get("stay_in_hover", False)))
            return {"directive_id": cur_directive.get("directive_id"), "result": "contact", "at": "run descend_pick",
                    "pick": cur_directive["pick"], "place": cur_directive["place"], "gate_trace": gate_trace,
                    "recovery": recovery_log, "steps": steps_log}

        r_grasp = _run_cmd("run grasp_pick")
        state = r_grasp.get("state") or []
        jaw_pos = _jaw_pos(state)
        curr_ma = r_grasp.get("gripper_current_ma")
        closed_pos = float(cal.get("grip_closed", 48.8))
        open_pos = float(plan.get("grip_open", 57.85))
        g_at_grasp = evaluate_execution_gate("at_grasp", r_step=r_grasp, gripper_pos=jaw_pos, current_ma=curr_ma)
        gate_trace.append(g_at_grasp)
        grasp_dynamics = cell_arm_cal.evaluate_grasp_dynamics(
            r_grasp, closed=closed_pos, open_pos=open_pos,
            held_30mm=float(cal.get("held_30mm", 53.5)), baseline_current_ma=float(cal.get("hold_current_ma", 80.0)),
        )
        holding = bool(r_grasp.get("ok")) and (
            cell_arm_cal.infer_holding(r_grasp, closed=closed_pos, open_pos=open_pos) or bool(grasp_dynamics.get("holding"))
        )

        d_res = None
        params = {
            "gripper.held_30mm": float(cal.get("held_30mm", 54.3)),
            "gripper.closed": float(cal.get("grip_closed", 48.8)), "gripper.open": open_pos,
            "grasp.shallow_tol_units": float(exec_cfg.get("shallow_tol_units", 2.2)),
            "grasp.wedged_tol_units": float(exec_cfg.get("wedged_tol_units", 2.5)),
            "grasp.max_skew_mm": float(exec_cfg.get("max_skew_mm", 5.5)),
            "grasp.max_across_skew_mm": float(exec_cfg.get("max_across_skew_mm", 7.5)),
            "wrist.finger_color": 2 if cal.get("finger_color") == "white" else 1,
        }
        t_judge = cgd.telemetry_judge(state, holding, params, current_ma=curr_ma)
        v_judge = _build_vision_judge(None if vision_refined_xy else last_wrist_obs, float(params["grasp.max_skew_mm"]))
        if frame_fn is not None and exec_cfg.get("vision_after_grasp", False):
            w_after = frame_fn("wrist")
            if w_after is not None:
                closing_deg = float(plan["pick"].get("yaw_deg", -90.0)) + 90.0
                gap_mm = 36.0 if cal.get("finger_color") == "dark" else 44.0
                v_judge = cgd.vision_judge(
                    w_after, ([5, 95, 110], [32, 255, 255]), gap_mm, closing_deg,
                    dict(cal.get("finger_sign") or {"along": -1.0, "across": 1.0}), params, color=cal.get("finger_color"),
                )
        if exec_cfg.get("grasp_deliberation", True) and jaw_pos is not None:
            k_judge = (
                cgd.kinesthetic_judge(r_grasp, grasp_dynamics=grasp_dynamics, params=params) if holding
                else {"verdict": "proceed", "class": "unmeasured", "dq_lift": 0.0, "dz_mm": 0.0, "reason": "pre_lift"}
            )
            d_res = cgd.debate_and_decide(
                stage="run grasp_pick", telemetry=t_judge, vision=v_judge, kinesthetic=k_judge,
                reinsert_count=attempt, max_reinsert=max_attempts - 1, models=exec_cfg.get("debate_models") or [],
            )
            debate_log.append(d_res)
            if d_res["verdict"] == "reinsert_and_retry" and attempt + 1 < max_attempts:
                r_rel = _run_cmd("run release_pick") if r_grasp.get("ok") else {"ok": False}
                if not r_rel.get("ok"):
                    _safe_recover_hover(float(plan["grip_open"]), park_after=False)
                rec = diagnose_and_recover_pick(
                    attempt=attempt, cur_directive=cur_directive, r_desc=r_desc, r_grasp=r_grasp,
                    cal=cal, tried_xs=tried_xs, wrist_obs=None if vision_refined_xy else last_wrist_obs, debate_decision=d_res,
                )
                rec["recovery_skill"] = select_recovery_skill(
                    str(g_at_grasp.get("failure_code") or "S4_SHALLOW_OR_SLIPPED_LIFT"),
                    dx_mm=float(v_judge.get("along_mm") or 0.0), dy_mm=float(v_judge.get("across_mm") or 0.0), level_tried=attempt,
                )
                recovery_log.append(rec)
                continue

        if not holding:
            r_rel = _run_cmd("run release_pick") if (r_grasp.get("ok") and not exec_cfg.get("stay_in_hover", False)) else {"ok": False}
            if attempt + 1 < max_attempts:
                if not r_rel.get("ok"):
                    _safe_recover_hover(float(plan["grip_open"]), park_after=False)
                rec = diagnose_and_recover_pick(
                    attempt=attempt, cur_directive=cur_directive, r_desc=r_desc, r_grasp=r_grasp,
                    cal=cal, tried_xs=tried_xs, wrist_obs=None if vision_refined_xy else last_wrist_obs, debate_decision=d_res,
                )
                rec["recovery_skill"] = select_recovery_skill(
                    str(g_at_grasp.get("failure_code") or "S4_EMPTY_AIR_CLOSE"), level_tried=attempt,
                )
                recovery_log.append(rec)
                continue
            if not r_rel.get("ok"):
                _safe_recover_hover(float(plan["grip_open"]), park_after=not bool(exec_cfg.get("stay_in_hover", False)))
            elif not exec_cfg.get("stay_in_hover", False):
                _run_cmd("park")
            out_empty = {"directive_id": cur_directive.get("directive_id"), "result": "empty", "task_verified": False,
                         "at": "run grasp_pick", "pick": cur_directive["pick"], "place": cur_directive["place"],
                         "gate_trace": gate_trace, "recovery": recovery_log, "steps": steps_log}
            cpp.capture_from_attempt({"_work": work_dir, "arm_id": arm_id}, out_empty)
            return out_empty

        updated_cal = cell_arm_cal.record_grasp_measurement(
            work_dir, arm_id=arm_id, gripper_pos=jaw_pos, gripper_current_ma=curr_ma, width_mm=30.0,
            skew_mm=wrist_log[-1].get("along_mm") if wrist_log and wrist_log[-1].get("found") else None,
            mm_per_px=wrist_log[-1].get("mm_per_px") if wrist_log and wrist_log[-1].get("found") else None,
            finger_color=cal.get("finger_color"),
        )

        slipped_in_transfer = False
        reinsert_at_lift = False
        d_lift_res = None
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
                    gate_trace.append(evaluate_execution_gate(
                        "lift_verify", r_step=r_lift_step,
                        gripper_pos=_jaw_pos(r_lift_step.get("state") or []), current_ma=r_lift_step.get("gripper_current_ma"),
                    ))
                    grasp_dynamics = cell_arm_cal.evaluate_grasp_dynamics(r_grasp, r_lift=r_lift_step, closed=closed_pos, open_pos=open_pos)
                    if exec_cfg.get("grasp_deliberation", True) and r_step.get("ok"):
                        k_lift = cgd.kinesthetic_judge(r_grasp, r_lift=r_lift_step, grasp_dynamics=grasp_dynamics, params=params)
                        v_lift = cgd.vision_judge(frame_fn("wrist"), dict(exec_cfg.get("wrist_hsv") or cell_fingers.GREEN_HSV), 36.0 if cal.get("finger_color") == "dark" else 44.0, float(plan["pick"].get("yaw_deg", -90.0)) + 90.0, sign=exec_cfg.get("wrist_sign"), params=params, color=exec_cfg.get("object_color")) if (frame_fn is not None and exec_cfg.get("vision_after_grasp", False)) else v_judge
                        if k_lift.get("verdict") == "reinsert" or v_lift.get("verdict") == "reinsert":
                            d_lift_res = cgd.debate_and_decide(
                                stage="run lift_pick", telemetry=t_judge, vision=v_lift, kinesthetic=k_lift,
                                reinsert_count=attempt, max_reinsert=max_attempts - 1, models=exec_cfg.get("debate_models") or [],
                            )
                            debate_log.append(d_lift_res)
                            if d_lift_res["verdict"] == "reinsert_and_retry" and attempt + 1 < max_attempts:
                                _run_cmd("run reinsert_pick")
                                reinsert_at_lift = True
                                break
                else:
                    grasp_dynamics = cell_arm_cal.evaluate_grasp_dynamics(r_grasp, r_lift=r_lift_step, r_above_place=r_step, closed=closed_pos, open_pos=open_pos)
                if not grasp_dynamics.get("holding") and not cell_arm_cal.infer_holding(
                    r_step, closed=closed_pos, min_units_above_closed=2.5, min_current_ma=40.0, prev_grasp=r_grasp,
                    prev_lift=r_lift_step if chunk_cmd == "goto above_place" else None, open_pos=open_pos,
                ):
                    slipped_in_transfer = True
                    if not r_step.get("ok") or (attempt + 1 >= max_attempts and not stay_hover):
                        _run_cmd("goto above_place")
                        _run_cmd("park")
                    break
                if chunk_cmd == "goto above_place":
                    held_at_above_place = True
            if chunk_cmd == "run descend_place":
                tactile_eval = evaluate_tactile_place_compliance(
                    r_step, target_z_m=float(cur_directive["place"]["effective_xyz_m"][2]),
                    current_z_m=r_step.get("z_m"), holding=held_at_above_place or True,
                )
                if tactile_eval["compliant"]:
                    tactile_or_full_place = True
                    if tactile_eval["early_touchdown"]:
                        _run_cmd(f"grip {float(plan['grip_release']):.2f}")
                        if frame_fn is not None and not stay_hover:
                            import time as _time
                            _time.sleep(0.20)
                        _run_cmd("retreat")
                        if not stay_hover:
                            _run_cmd("park")
                        break
            if not r_step.get("ok"):
                if chunk_cmd != "park":
                    _safe_recover_hover(float(plan["grip_open"]), park_after=not stay_hover)
                if chunk_cmd not in ("run lift_place", "park"):
                    out_err = {"directive_id": cur_directive.get("directive_id"), "result": "contact", "task_verified": False,
                               "at": chunk_cmd, "error": r_step.get("error"), "pick": cur_directive["pick"],
                               "place": cur_directive["place"], "gate_trace": gate_trace, "recovery": recovery_log, "steps": steps_log}
                    cpp.capture_from_attempt({"_work": work_dir, "arm_id": arm_id}, out_err)
                    return out_err

        if reinsert_at_lift or slipped_in_transfer:
            if attempt + 1 < max_attempts:
                if vision_refined_xy and not reinsert_at_lift:
                    cur_directive["pick"]["effective_xyz_m"][0] = orig_pick_xyz[0]
                    cur_directive["pick"]["effective_xyz_m"][1] = orig_pick_xyz[1]
                    cur_directive["pick"]["x"] = orig_pick_xyz[0]
                    cur_directive["pick"]["y"] = orig_pick_xyz[1]
                    exec_cfg["vision_refine"] = False
                rec = diagnose_and_recover_pick(
                    attempt=attempt, cur_directive=cur_directive, r_desc=r_desc, r_grasp=r_grasp,
                    cal=cal, tried_xs=tried_xs, wrist_obs=None, slipped_in_transfer=True, debate_decision=d_lift_res,
                )
                rec["recovery_skill"] = select_recovery_skill("S4_SHALLOW_OR_SLIPPED_LIFT", level_tried=attempt)
                recovery_log.append(rec)
                continue
            out_slip = {"schema": DIRECTIVE_SCHEMA, "directive_id": cur_directive.get("directive_id"), "arm_id": arm_id,
                        "result": "slipped_in_transfer", "task_verified": False, "grasp_dynamics": grasp_dynamics,
                        "pick": cur_directive["pick"], "place": cur_directive["place"], "gate_trace": gate_trace,
                        "recovery": recovery_log, "wrist": wrist_log, "steps": steps_log}
            cpp.capture_from_attempt({"_work": work_dir, "arm_id": arm_id}, out_slip)
            return out_slip

        after_side = frame_fn("side") if (frame_fn is not None and not stay_hover) else None
        after_top = frame_fn("top") if (frame_fn is not None and not stay_hover) else None
        verification = verify_stack_outcome(before_side=before_side, after_side=after_side, before_top=before_top,
                                            after_top=after_top, pick=cur_directive["pick"], place=cur_directive["place"])
        if not verification["verified"] and exec_cfg.get("proprioceptive_verify", False) and held_at_above_place and tactile_or_full_place:
            verification["verified"] = True
            verification["reason"] = "proprioceptive_tactile_stack_verified"
        if not verification["verified"] and attempt + 1 < max_attempts and exec_cfg.get("retry_on_unverified_place", True):
            rec = diagnose_and_recover_pick(attempt=attempt, cur_directive=cur_directive, r_desc=r_desc, r_grasp=r_grasp,
                                            cal=cal, tried_xs=tried_xs, wrist_obs=None, slipped_in_transfer=True)
            rec["verification_reason"] = verification["reason"]
            rec["recovery_skill"] = select_recovery_skill("S4_SHALLOW_OR_SLIPPED_LIFT", level_tried=attempt)
            recovery_log.append(rec)
            continue

        out_final = {
            "schema": DIRECTIVE_SCHEMA, "directive_id": cur_directive.get("directive_id"), "arm_id": arm_id,
            "result": "placed" if verification["verified"] else "unverified_place",
            "task_verified": verification["verified"], "verification": verification,
            "pick": cur_directive["pick"], "place": cur_directive["place"],
            "gripper_pos": jaw_pos, "gripper_current_ma": curr_ma, "grasp_dynamics": grasp_dynamics,
            "gate_trace": gate_trace, "calibration": updated_cal, "recovery": recovery_log,
            "wrist": wrist_log, "grasp_debate": debate_log, "steps": steps_log,
        }
        if not verification["verified"]:
            cpp.capture_from_attempt({"_work": work_dir, "arm_id": arm_id}, out_final)
        return out_final

    return {"directive_id": cur_directive.get("directive_id"), "result": "stopped", "task_verified": False,
            "gate_trace": gate_trace, "recovery": recovery_log, "steps": steps_log}
