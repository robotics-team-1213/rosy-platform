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
import sys
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
ADAPTER_ROOT = HERE.parents[2] / "middleware/devices/omx/adapter"
for _p in (HERE, ADAPTER_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from omx_adapter.area_xyz import DIRECTIVE_SCHEMA, coerce_area_xyz  # noqa: E402
import cell_arm_cal  # noqa: E402
import cell_fingers  # noqa: E402
import cell_grasp_debate as cgd  # noqa: E402
import cell_problem_pipeline as cpp  # noqa: E402
import grasp_planner  # noqa: E402
from cell_area_zones import (  # noqa: E402,F401  (re-exported: existing importers are unchanged)
    SIDE_COL_CENTER_U,
    SIDE_M_PER_PX,
    SIDE_ROI_BY_COL_TIER,
    TOP_ROI_BY_COL_ROW,
    diagnose_and_recover_pick,
    evaluate_zone,
    measure_side_gripper_zone_offset,
    verify_stack_outcome,
    warm_container_ratio,
)


def build_plan_from_directive(
    directive: dict[str, Any],
    base_plan: dict[str, Any],
    work_dir: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge an `AreaXYZ` directive and per-arm calibration profile into a `grasp_planner` plan dictionary."""
    arm_id = str(directive.get("arm_id") or "arm_b")
    cal = cell_arm_cal.load(work_dir or Path("."), arm_id)
    pick = coerce_area_xyz(directive["pick"])
    place = coerce_area_xyz(directive["place"])
    exec_cfg = dict(directive.get("execution") or {})

    plan = json.loads(json.dumps(base_plan))
    px, py, pz = pick["effective_xyz_m"]
    qx, qy, qz = place["effective_xyz_m"]
    approach_m = float(exec_cfg.get("approach_m", 0.034))

    plan["pick"] = {
        "x": px,
        "y": py,
        "z": pz,
        "yaw_deg": float(pick.get("yaw_deg", -90.0)),
        "approach_m": approach_m,
        "lift_m": approach_m,
    }
    plan["place"] = {
        "x": qx,
        "y": qy,
        "z": qz,
        "yaw_deg": float(place.get("yaw_deg", -90.0)),
        "approach_m": approach_m,
        "lift_m": approach_m,
    }
    plan["grip_closed"] = float(cal.get("grip_closed", plan.get("grip_closed", 48.8)))
    plan["grip_open"] = float(exec_cfg.get("grip_open_override") or cal.get("grip_open_30mm", plan.get("grip_open", 58.2)))
    plan["grip_release"] = float(cal.get("grip_release_30mm", plan.get("grip_release", 57.6)))
    plan["hold_current_ma"] = int(cal.get("hold_current_ma", plan.get("hold_current_ma", 93)))
    plan["approach_m"] = approach_m
    plan["lift_m"] = float(exec_cfg.get("lift_m", approach_m))
    plan.setdefault("descend_m_s", 0.015)
    plan.setdefault("lift_m_s", 0.025)
    plan.setdefault("grip_s", 0.6)
    plan.setdefault("settle_s", 0.35)
    plan.setdefault("descend_guard_frac", 0.30)
    plan.setdefault("lift_guard_frac", 0.30)
    plan["transit_speed"] = float(exec_cfg.get("transit_speed", plan.get("transit_speed", 0.82)))
    plan["descend_pick_guard_frac"] = float(exec_cfg.get("descend_pick_guard_frac", plan.get("descend_pick_guard_frac", 0.30)))
    plan["descend_place_guard_frac"] = float(exec_cfg.get("descend_place_guard_frac", plan.get("descend_place_guard_frac", 0.26)))
    plan["lift_pick_guard_frac"] = float(exec_cfg.get("lift_pick_guard_frac", plan.get("lift_pick_guard_frac", 0.28)))
    return plan, cal


def plan_library_from_directive(
    directive: dict[str, Any],
    base_plan: dict[str, Any],
    work_dir: Path | None = None,
    kinematics_root: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Build and solve the top-down chunk library for a middleware `AreaXYZ` directive."""
    plan, cal = build_plan_from_directive(directive, base_plan, work_dir=work_dir)
    planner = grasp_planner.Planner(plan, kinematics_root or ADAPTER_ROOT)
    lib = {k: v for k, v in planner.library().items() if v is not None}
    return lib, plan, cal


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

    for attempt in range(max_attempts):
        lib, plan, cal = plan_library_from_directive(cur_directive, base_plan, work_dir=work_dir, kinematics_root=kinematics_root)
        lib_path = work_dir / f"area-xyz-{cur_directive.get('directive_id', 'run')}-a{attempt}.library.json"
        lib_path.write_text(json.dumps(lib), encoding="utf-8")

        r_load = _run_cmd(f"load {lib_path}")
        if not r_load.get("ok"):
            _run_cmd("park")
            r_load = _run_cmd(f"load {lib_path}")
            if not r_load.get("ok"):
                return {"directive_id": cur_directive.get("directive_id"), "result": "fault", "at": "load", "steps": steps_log}

        r_above = _run_cmd("goto above_pick")
        if not r_above.get("ok"):
            _run_cmd("park")
            r_above = _run_cmd("goto above_pick")
            if not r_above.get("ok"):
                return {"directive_id": cur_directive.get("directive_id"), "result": "contact", "at": "goto above_pick", "steps": steps_log}

        # Ensure jaws have finished opening to grip_open at above_pick before descending
        above_state = r_above.get("state") or []
        if len(above_state) >= 6 and above_state[5] is not None and float(above_state[5]) < float(plan["grip_open"]) - 1.0:
            _run_cmd("run above_pick")

        # Pre-pick target zone alignment using Side View + Wrist View
        last_wrist_obs = None
        if exec_cfg.get("vision_refine", False) and frame_fn is not None:
            col = int(cur_directive["pick"].get("col") or 3)
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

            w_img = frame_fn("wrist")
            if w_img is not None:
                f_color = cal.get("finger_color", "white")
                obs = cell_fingers.finger_offset_mm(
                    w_img,
                    ([5, 110, 110], [25, 255, 255]),
                    gap_mm=44.0 if f_color == "white" else 36.0,
                    params={"wrist.finger_color": 2 if f_color == "white" else 1},
                    color=f_color,
                )
                last_wrist_obs = obs
                wrist_log.append(obs)
                if obs.get("found") and 1.5 < abs(float(obs.get("along_mm", 0.0))) <= 9.0:
                    sign_along = float((cal.get("finger_sign") or {}).get("along", -1.0 if arm_id != "arm_s" else 1.0))
                    dx_m = 0.55 * sign_along * float(obs["along_mm"]) / 1000.0
                    p_xyz = list(cur_directive["pick"]["effective_xyz_m"])
                    p_xyz[0] = round(max(0.120, min(0.204, p_xyz[0] + dx_m)), 5)
                    cur_directive["pick"]["effective_xyz_m"] = p_xyz
                    cur_directive["pick"]["x"] = p_xyz[0]
                    lib, plan, cal = plan_library_from_directive(cur_directive, base_plan, work_dir=work_dir, kinematics_root=kinematics_root)
                    lib_path.write_text(json.dumps(lib), encoding="utf-8")
                    _run_cmd(f"load {lib_path}")
                    _run_cmd("goto above_pick")

        r_desc = _run_cmd("run descend_pick")
        if not r_desc.get("ok"):
            r_lp = _run_cmd("run lift_pick")
            if not r_lp.get("ok"):
                _run_cmd("park")
            if attempt + 1 < max_attempts:
                rec = diagnose_and_recover_pick(
                    attempt=attempt,
                    cur_directive=cur_directive,
                    r_desc=r_desc,
                    r_grasp={},
                    cal=cal,
                    tried_xs=tried_xs,
                    wrist_obs=last_wrist_obs,
                )
                recovery_log.append(rec)
                continue
            _run_cmd("park")
            return {"directive_id": cur_directive.get("directive_id"), "result": "contact", "at": "run descend_pick", "recovery": recovery_log, "steps": steps_log}

        r_grasp = _run_cmd("run grasp_pick")
        state = r_grasp.get("state") or []
        jaw_pos = float(state[5]) if len(state) >= 6 and state[5] is not None else None
        curr_ma = r_grasp.get("gripper_current_ma")
        holding = cell_arm_cal.infer_holding(r_grasp, closed=float(cal.get("grip_closed", 48.8)))

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
            d_res = cgd.debate_and_decide(
                stage="run grasp_pick",
                telemetry=t_judge,
                vision=v_judge,
                reinsert_count=attempt,
                max_reinsert=max_attempts - 1,
                models=[],
            )
            debate_log.append(d_res)
            if d_res["verdict"] == "reinsert_and_retry" and attempt + 1 < max_attempts:
                r_rel = _run_cmd("run release_pick")
                r_lp = _run_cmd("run lift_pick")
                if not r_rel.get("ok") or not r_lp.get("ok"):
                    _run_cmd("park")
                rec = diagnose_and_recover_pick(
                    attempt=attempt,
                    cur_directive=cur_directive,
                    r_desc=r_desc,
                    r_grasp=r_grasp,
                    cal=cal,
                    tried_xs=tried_xs,
                    wrist_obs=last_wrist_obs,
                )
                recovery_log.append(rec)
                continue

        if not holding:
            r_rel = _run_cmd("run release_pick")
            r_lp = _run_cmd("run lift_pick")
            if not r_rel.get("ok") or not r_lp.get("ok"):
                _run_cmd("park")
            if attempt + 1 < max_attempts:
                rec = diagnose_and_recover_pick(
                    attempt=attempt,
                    cur_directive=cur_directive,
                    r_desc=r_desc,
                    r_grasp=r_grasp,
                    cal=cal,
                    tried_xs=tried_xs,
                    wrist_obs=last_wrist_obs,
                )
                recovery_log.append(rec)
                continue
            _run_cmd("park")
            out_empty = {
                "directive_id": cur_directive.get("directive_id"),
                "result": "empty",
                "task_verified": False,
                "at": "run grasp_pick",
                "pick": cur_directive["pick"],
                "place": cur_directive["place"],
                "recovery": recovery_log,
                "steps": steps_log,
            }
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
        for chunk_cmd in ("run lift_pick", "goto above_place", "run descend_place", "run release_place", "run lift_place", "park"):
            r_step = _run_cmd(chunk_cmd)
            if chunk_cmd in ("run lift_pick", "goto above_place"):
                # Check if container slipped out during lift_pick or transit to above_place
                if not cell_arm_cal.infer_holding(r_step, closed=float(cal.get("grip_closed", 48.8)), min_units_above_closed=2.5, min_current_ma=40.0):
                    slipped_in_transfer = True
                    _run_cmd("park")
                    break
            if not r_step.get("ok"):
                if chunk_cmd != "park":
                    _run_cmd("park")
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

        if slipped_in_transfer and attempt + 1 < max_attempts:
            rec = diagnose_and_recover_pick(
                attempt=attempt,
                cur_directive=cur_directive,
                r_desc=r_desc,
                r_grasp={"state": [0, 0, 0, 0, 0, 49.0], "gripper_current_ma": 0.0},
                cal=cal,
                tried_xs=tried_xs,
                wrist_obs=last_wrist_obs,
            )
            recovery_log.append(rec)
            continue

        after_side = frame_fn("side") if frame_fn is not None else None
        after_top = frame_fn("top") if frame_fn is not None else None
        verification = verify_stack_outcome(
            before_side=before_side,
            after_side=after_side,
            before_top=before_top,
            after_top=after_top,
            pick=cur_directive["pick"],
            place=cur_directive["place"],
        )
        if not verification["verified"] and attempt + 1 < max_attempts:
            recovery_log.append({"attempt": attempt, "reason": verification["reason"]})
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
