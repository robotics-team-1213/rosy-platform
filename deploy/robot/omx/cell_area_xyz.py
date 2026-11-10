#!/usr/bin/env python3
"""`rosy-cell` executor for unified `AreaXYZ` directives from ROSY middleware (D-1014).

Receives a `rosy.omx-cell-area-xyz-directive.v1` payload (constructed by `omx_adapter.area_xyz.build_directive`),
applies the per-arm calibration profile (`cell_arm_cal.py`, `arm-cal-<arm_id>.json`), plans top-down guarded chunks
via `grasp_planner.Planner`, executes wrist-camera `(x, y)` centering (`wrist_servo`), runs `schema_version = 2`
grasp-stability deliberation (`cell_grasp_debate.py` with `reinsert_pick` / `release_pick` recovery), and places the
container at the designated `(area, x, y, z)` coordinate up to 3단 (`tier=3, l2`).
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
ADAPTER_ROOT = HERE.parents[2] / "middleware/devices/omx/adapter"
for _p in (HERE, ADAPTER_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from omx_adapter.area_xyz import DIRECTIVE_SCHEMA, build_directive, coerce_area_xyz, resolve_area_xyz  # noqa: E402
import cell_arm_cal  # noqa: E402
import cell_fingers  # noqa: E402
import cell_grasp_debate as cgd  # noqa: E402
import cell_problem_pipeline as cpp  # noqa: E402
import grasp_planner  # noqa: E402


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
    approach_m = float(exec_cfg.get("approach_m", 0.04))

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
    plan["grip_open"] = float(cal.get("grip_open_30mm", plan.get("grip_open", 58.2)))
    plan["grip_release"] = float(cal.get("grip_release_30mm", plan.get("grip_release", 57.6)))
    plan["hold_current_ma"] = int(cal.get("hold_current_ma", plan.get("hold_current_ma", 93)))
    plan["approach_m"] = float(exec_cfg.get("approach_m", plan.get("approach_m", 0.04)))
    plan["lift_m"] = float(exec_cfg.get("lift_m", plan.get("lift_m", 0.04)))
    plan.setdefault("descend_m_s", 0.015)
    plan.setdefault("lift_m_s", 0.025)
    plan.setdefault("grip_s", 0.6)
    plan.setdefault("settle_s", 0.35)
    plan.setdefault("descend_guard_frac", 0.30)
    plan.setdefault("lift_guard_frac", 0.45)
    plan["transit_speed"] = float(exec_cfg.get("transit_speed", plan.get("transit_speed", 0.82)))
    plan["descend_pick_guard_frac"] = float(exec_cfg.get("descend_pick_guard_frac", plan.get("descend_pick_guard_frac", 0.30)))
    plan["descend_place_guard_frac"] = float(exec_cfg.get("descend_place_guard_frac", plan.get("descend_place_guard_frac", 0.26)))
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
    max_attempts: int = 2,
) -> dict[str, Any]:
    """Execute a `rosy.omx-cell-area-xyz-directive.v1` directive on `rosy-cell` and return the structured outcome."""
    work_dir.mkdir(parents=True, exist_ok=True)
    arm_id = str(directive.get("arm_id") or "arm_b")
    cur_directive = json.loads(json.dumps(directive))
    cur_directive["pick"] = coerce_area_xyz(cur_directive["pick"])
    cur_directive["place"] = coerce_area_xyz(cur_directive["place"])
    exec_cfg = dict(cur_directive.get("execution") or {})
    steps_log: list[dict[str, Any]] = []
    wrist_log: list[dict[str, Any]] = []
    debate_log: list[dict[str, Any]] = []

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
            return {"directive_id": cur_directive.get("directive_id"), "result": "fault", "at": "load", "steps": steps_log}

        r_above = _run_cmd("goto above_pick")
        if not r_above.get("ok"):
            # Clear own stale zone via park once and retry goto above_pick
            _run_cmd("park")
            r_above = _run_cmd("goto above_pick")
            if not r_above.get("ok"):
                return {"directive_id": cur_directive.get("directive_id"), "result": "contact", "at": "goto above_pick", "steps": steps_log}

        # Optional wrist-camera (x, y) centering at above_pick
        if exec_cfg.get("vision_refine", True) and frame_fn is not None:
            w_img = frame_fn(f"{arm_id}_wrist")
            if w_img is not None:
                f_color = cal.get("finger_color", "white")
                obs = cell_fingers.finger_offset_mm(
                    w_img,
                    ([5, 110, 110], [25, 255, 255]),
                    gap_mm=44.0 if f_color == "white" else 36.0,
                    params={"wrist.finger_color": 2 if f_color == "white" else 1},
                    color=f_color,
                )
                wrist_log.append(obs)
                if obs.get("found") and 1.5 < abs(float(obs.get("along_mm", 0.0))) <= 12.0:
                    sign_along = float((cal.get("finger_sign") or {}).get("along", -1.0 if arm_id != "arm_s" else 1.0))
                    dx_m = 0.65 * sign_along * float(obs["along_mm"]) / 1000.0
                    p_xyz = list(cur_directive["pick"]["effective_xyz_m"])
                    p_xyz[0] = round(max(0.115, min(0.215, p_xyz[0] + dx_m)), 5)
                    cur_directive["pick"]["effective_xyz_m"] = p_xyz
                    cur_directive["pick"]["x"] = p_xyz[0]
                    lib, plan, cal = plan_library_from_directive(cur_directive, base_plan, work_dir=work_dir, kinematics_root=kinematics_root)
                    lib_path.write_text(json.dumps(lib), encoding="utf-8")
                    _run_cmd(f"load {lib_path}")
                    _run_cmd("goto above_pick")

        r_desc = _run_cmd("run descend_pick")
        if not r_desc.get("ok"):
            _run_cmd("park")
            return {"directive_id": cur_directive.get("directive_id"), "result": "contact", "at": "run descend_pick", "steps": steps_log}

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
                "grasp.pos_tol_units": 2.2,
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
                _run_cmd("run release_pick")
                _run_cmd("run lift_pick")
                dx_m = float(d_res.get("dx_mm", 0.0)) / 1000.0
                p_xyz = list(cur_directive["pick"]["effective_xyz_m"])
                p_xyz[0] = round(p_xyz[0] + dx_m, 5)
                cur_directive["pick"]["effective_xyz_m"] = p_xyz
                continue

        if not holding:
            _run_cmd("run release_pick")
            _run_cmd("run lift_pick")
            _run_cmd("park")
            return {"directive_id": cur_directive.get("directive_id"), "result": "empty", "at": "run grasp_pick", "steps": steps_log}

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

        for chunk_cmd in ("run lift_pick", "park", "goto above_place", "run descend_place", "run release_place", "run lift_place", "park"):
            r_step = _run_cmd(chunk_cmd)
            if not r_step.get("ok"):
                # If park or lift_place had a transient contact after release, try parking once more
                if chunk_cmd in ("run lift_place", "park"):
                    _run_cmd("park")
                else:
                    out_err = {
                        "directive_id": cur_directive.get("directive_id"),
                        "result": "contact",
                        "at": chunk_cmd,
                        "error": r_step.get("error"),
                        "pick": cur_directive["pick"],
                        "place": cur_directive["place"],
                        "steps": steps_log,
                        "wrist": wrist_log[-1] if wrist_log else {},
                        "grasp_debate": debate_log[-1] if debate_log else None,
                    }
                    cpp.capture_from_attempt({"_work": work_dir, "arm_id": arm_id}, out_err)
                    return out_err

        return {
            "schema": DIRECTIVE_SCHEMA,
            "directive_id": cur_directive.get("directive_id"),
            "arm_id": arm_id,
            "result": "placed",
            "pick": cur_directive["pick"],
            "place": cur_directive["place"],
            "gripper_pos": jaw_pos,
            "gripper_current_ma": curr_ma,
            "calibration": updated_cal,
            "wrist": wrist_log,
            "grasp_debate": debate_log,
            "steps": steps_log,
        }

    return {"directive_id": cur_directive.get("directive_id"), "result": "stopped", "steps": steps_log}
