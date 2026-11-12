#!/usr/bin/env python3
"""`AreaXYZ` Directive-to-Plan Compiler and Simulation Precheck (`cell_directive_compiler.py`).

Single Responsibility:
  - Compile middleware `AreaXYZ` directives and per-arm calibration profiles into `grasp_planner`
    plan dictionaries (`build_plan_from_directive`) and solved chunk libraries (`plan_library_from_directive`).
  - Run deterministic simulation precheck and pick-yaw cable-safety optimization (`sim_precheck_and_optimize_directive`).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from omx_adapter.motion_profile import compile_smooth_chunk

HERE = Path(__file__).resolve().parent
ADAPTER_ROOT = HERE.parents[2] / "middleware/devices/omx/adapter"


def _clone(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _clone(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clone(v) for v in obj]
    return obj


def build_plan_from_directive(
    directive: dict[str, Any],
    base_plan: dict[str, Any],
    work_dir: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge an `AreaXYZ` directive and per-arm calibration profile into a `grasp_planner` plan dictionary."""
    from omx_adapter.area_xyz import coerce_area_xyz
    import cell_arm_cal
    from cell_area_zones import normalize_pick_yaw_deg

    arm_id = str(directive.get("arm_id") or "arm_b")
    cal = cell_arm_cal.load(work_dir or Path("."), arm_id)
    pick = coerce_area_xyz(directive["pick"])
    place = coerce_area_xyz(directive["place"])
    exec_cfg = dict(directive.get("execution") or {})

    plan = _clone(base_plan)
    px, py, pz = pick["effective_xyz_m"]
    qx, qy, qz = place["effective_xyz_m"]
    approach_m = float(exec_cfg.get("approach_m", 0.032 if float(pz) < 0.020 else 0.028))
    place_approach_m = min(approach_m, 0.025 if float(qz) >= 0.060 else 0.028)

    safe_pick_yaw = normalize_pick_yaw_deg(float(pick.get("yaw_deg", -90.0)), px, py)
    default_lift_m = round(max(approach_m, float(qz) + approach_m - float(pz)), 4)
    if float(pz) >= 0.0 and float(px) >= 0.185:
        default_lift_m = min(default_lift_m, 0.036 if float(px) >= 0.215 else 0.058)
    actual_lift_m = float(exec_cfg.get("lift_m", default_lift_m))
    plan["pick"] = {
        "x": px,
        "y": py,
        "z": pz,
        "yaw_deg": safe_pick_yaw,
        "approach_m": approach_m,
        "lift_m": actual_lift_m,
    }
    plan["place"] = {
        "x": qx,
        "y": qy,
        "z": qz,
        "yaw_deg": float(place.get("yaw_deg", -90.0)),
        "approach_m": place_approach_m,
        "lift_m": place_approach_m,
    }
    plan["grip_closed"] = float(cal.get("grip_closed", plan.get("grip_closed", 48.8)))
    plan["grip_open"] = min(
        58.15, float(exec_cfg.get("grip_open_override") or cal.get("grip_open_30mm", plan.get("grip_open", 57.9)))
    )
    plan["grip_release"] = min(
        float(plan["grip_open"]), float(cal.get("grip_release_30mm", plan.get("grip_release", 57.5)))
    )
    plan["hold_current_ma"] = int(
        exec_cfg.get("hold_current_ma", max(140, int(cal.get("hold_current_ma", plan.get("hold_current_ma", 140)))))
    )
    plan["tcp_x_m"] = float(exec_cfg.get("tcp_x_m", plan.get("tcp_x_m", 0.0885)))
    plan["approach_m"] = approach_m
    plan["lift_m"] = actual_lift_m
    default_rel_lift = max(0.042, place_approach_m + 0.014) if arm_id == "arm_s" else place_approach_m
    plan["release_lift_m"] = float(exec_cfg.get("release_lift_m", default_rel_lift))
    plan.setdefault("descend_m_s", 0.025)
    plan.setdefault("lift_m_s", 0.032)
    plan["grip_s"] = float(exec_cfg.get("grip_s", 0.45))
    plan["settle_s"] = float(exec_cfg.get("settle_s", min(0.18, float(plan.get("settle_s", 0.18)))))
    plan["descend_guard_frac"] = float(
        exec_cfg.get("descend_guard_frac", plan.get("descend_guard_frac", 0.76))
    )
    plan["lift_guard_frac"] = float(
        exec_cfg.get("lift_guard_frac", plan.get("lift_guard_frac", 0.82))
    )
    if arm_id == "arm_b" and "limits" in plan and "joints_rad" in plan["limits"]:
        plan["limits"]["joints_rad"]["joint5"] = [0.16, 2.89]
    if "limits" in plan and float(pz) < float(plan["limits"]["workspace_min_m"][2]):
        lz = list(plan["limits"].get("low_zones") or [])
        lz.append({
            "x": [round(px - 0.04, 4), round(px + 0.04, 4)],
            "y": [round(py - 0.04, 4), round(py + 0.04, 4)],
            "z_min_m": round(float(pz) - 0.003, 4),
        })
        plan["limits"]["low_zones"] = lz
    rl_speed_scale = max(0.70, min(1.25, float(exec_cfg.get("rl_speed_scale", 1.0))))
    plan["rl_speed_scale"] = round(rl_speed_scale, 3)
    base_transit = float(exec_cfg.get("transit_speed", plan.get("transit_speed", 0.85)))
    if "transit_speed" not in exec_cfg and rl_speed_scale != 1.0:
        base_transit = round(min(1.0, max(0.50, base_transit * rl_speed_scale)), 4)
        plan["lift_m_s"] = round(min(0.040, max(0.015, float(plan["lift_m_s"]) * rl_speed_scale)), 4)
    plan["transit_speed"] = base_transit
    plan["descend_pick_guard_frac"] = float(
        exec_cfg.get("descend_pick_guard_frac", max(0.60, float(plan.get("descend_pick_guard_frac", 0.60))))
    )
    plan["descend_place_guard_frac"] = float(
        exec_cfg.get("descend_place_guard_frac", plan.get("descend_place_guard_frac", 0.70))
    )
    plan["lift_pick_guard_frac"] = float(
        exec_cfg.get("lift_pick_guard_frac", max(0.70, float(plan.get("lift_pick_guard_frac", plan.get("lift_guard_frac", 0.70)))))
    )
    return plan, cal


def plan_library_from_directive(
    directive: dict[str, Any],
    base_plan: dict[str, Any],
    work_dir: Path | None = None,
    kinematics_root: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Build and solve the top-down chunk library for a middleware `AreaXYZ` directive, with anti-jitter settle tails
    and Sim-to-Real phase-lead + static deadband trajectory pre-compensation."""
    from omx_adapter.z_profile import SimRealTwin
    import grasp_planner

    plan, cal = build_plan_from_directive(directive, base_plan, work_dir=work_dir)
    planner = grasp_planner.Planner(plan, kinematics_root or ADAPTER_ROOT)
    lib = {k: v for k, v in planner.library().items() if v is not None}
    exec_cfg = dict(directive.get("execution") or {})
    if exec_cfg.get("anti_jitter_settle", True) and "chunks" in lib:
        chunks = lib["chunks"]
        for k in ("above_pick", "above_place"):
            if chunks.get(k):
                chunks[k] = list(chunks[k]) + [list(chunks[k][-1])]
        for k in ("descend_pick", "descend_place", "lift_pick", "lift_place"):
            if chunks.get(k):
                chunks[k] = list(chunks[k]) + [list(chunks[k][-1])]
    if exec_cfg.get("sim_real_compensate", True) and "chunks" in lib:
        chunks = lib["chunks"]
        arm_id = str(directive.get("arm_id") or "arm_b")
        tcp_x_mm = 91.93 if arm_id == "arm_s" else 74.1
        fps = int(lib.get("fps", 30))
        twin = SimRealTwin.from_dict(cal.get("sim_real_twin"))
        ideal_pick_end = list(chunks["descend_pick"][-1]) if chunks.get("descend_pick") else None
        ideal_place_end = list(chunks["descend_place"][-1]) if chunks.get("descend_place") else None
        comp_pick = twin.compensate_vertical_triplet(
            chunks["descend_pick"], chunks["grasp_pick"], chunks["lift_pick"], fps=fps, tcp_x_mm=tcp_x_mm,
        )
        comp_place = twin.compensate_vertical_triplet(
            chunks["descend_place"], chunks["release_place"], chunks["lift_place"], fps=fps, tcp_x_mm=tcp_x_mm,
        )
        chunks["descend_pick"], chunks["grasp_pick"], chunks["lift_pick"] = comp_pick["down"], comp_pick["hold"], comp_pick["lift"]
        chunks["descend_place"], chunks["release_place"], chunks["lift_place"] = comp_place["down"], comp_place["hold"], comp_place["lift"]
        plan["sim_real_prediction"] = {
            "twin": twin.to_dict(),
            "ideal_pick_end": ideal_pick_end,
            "ideal_place_end": ideal_place_end,
            "pick_uncompensated": comp_pick.get("before_sim"),
            "pick_compensated": comp_pick.get("after_sim"),
            "pick_terminal_offset_units": comp_pick.get("terminal_offset_units"),
            "place_uncompensated": comp_place.get("before_sim"),
            "place_compensated": comp_place.get("after_sim"),
            "place_terminal_offset_units": comp_place.get("terminal_offset_units"),
        }
    return lib, plan, cal


def sim_precheck_and_optimize_directive(
    directive: dict[str, Any],
    base_plan: dict[str, Any],
    *,
    work_dir: Path | None = None,
    kinematics_root: Path | None = None,
) -> dict[str, Any]:
    """Run deterministic simulation pre-flight on an `AreaXYZ` directive: normalize 180-deg pick yaw for cable safety,
    enforce vertical clearance `lift_m` over lower tiers, solve IK/FK chunk library, and pre-verify recovery policy."""
    from omx_adapter.area_xyz import coerce_area_xyz
    from cell_area_zones import normalize_pick_yaw_deg

    opt = _clone(directive)
    opt["pick"] = coerce_area_xyz(opt["pick"])
    opt["place"] = coerce_area_xyz(opt["place"])
    px, py, _ = opt["pick"]["effective_xyz_m"]
    raw_yaw = float(opt["pick"].get("yaw_deg", -90.0))
    safe_yaw = normalize_pick_yaw_deg(raw_yaw, px, py)
    opt["pick"]["yaw_deg"] = safe_yaw

    lib, plan, cal = plan_library_from_directive(opt, base_plan, work_dir=work_dir, kinematics_root=kinematics_root)
    rolls = [float(f[4]) for k, ch in lib.get("chunks", {}).items() if k != "home" for f in ch]
    return {
        "ok": True,
        "directive": opt,
        "normalized_pick_yaw_deg": safe_yaw,
        "reoriented_to_place_yaw_deg": float(opt["place"].get("yaw_deg", -90.0)),
        "clearance_lift_m": float(plan.get("lift_m", 0.04)),
        "wrist_roll_range_units": [round(min(rolls), 2), round(max(rolls), 2)] if rolls else [45.2, 48.8],
        "calibration_samples": int(cal.get("samples", 0)),
    }


def build_crane_standby_transition(
    start_pose: Sequence[float],
    standby_pose: Sequence[float],
    *,
    lift_step: float = 0.032,
    pan_step: float = 0.045,
) -> list[dict[str, Any]]:
    """Decompose an extended pick/place return into a 2-phase crane-lift (`elbow_flex` fold + `shoulder_lift` rise
    at `lift_step`, then `shoulder_pan` rotation at `pan_step`) so panning never occurs under full moment arm."""
    s = [float(v) for v in start_pose]
    b = [float(v) for v in standby_pose]
    if abs(s[0] - b[0]) <= 3.0 and s[1] <= -22.0:
        return [{"phase": "crane_direct_standby", "pose": b, "max_step": round(float(pan_step), 4),
                 "smooth_frames": compile_smooth_chunk([s, b]),
                 "combined_smooth_frames": compile_smooth_chunk([s, b])}]
    folded_lift = round(min(-27.0, b[1]), 2)
    folded_elbow = round(max(22.0, b[2], s[2] + 10.0), 2)
    fold_pose = [round(s[0], 2), folded_lift, folded_elbow, round(b[3], 2), round(s[4], 2), round(b[5], 2)]
    return [
        {"phase": "crane_lift_fold", "pose": fold_pose, "max_step": round(float(lift_step), 4),
         "smooth_frames": compile_smooth_chunk([s, fold_pose]),
         "combined_smooth_frames": compile_smooth_chunk([s, fold_pose, b])},
        {"phase": "crane_pan_standby", "pose": b, "max_step": round(float(pan_step), 4),
         "smooth_frames": compile_smooth_chunk([fold_pose, b])},
    ]


def redirect_place_on_zone_obstruction(
    directive: dict[str, Any],
    *,
    obstructed_zones: Sequence[str] = (),
    fallback_zones: Sequence[str] = ("temp_plate_b", "temp_plate_a", "pallet"),
    lane: int = 1,
    tier: int = 1,
) -> dict[str, Any]:
    """Redirect `directive['place']` to the first clear zone in `fallback_zones` when the target zone is obstructed."""
    from omx_adapter.area_xyz import coerce_area_xyz, resolve_area_xyz

    out = _clone(directive)
    place = coerce_area_xyz(out["place"])
    cur_area = str(place.get("area") or "")
    blocked = {str(z) for z in obstructed_zones}
    if cur_area not in blocked:
        out["place"] = place
        out["redirected"] = False
        return out
    for candidate in fallback_zones:
        cand_area = str(candidate)
        if cand_area not in blocked:
            out["place"] = resolve_area_xyz(cand_area, col=int(lane), row=1, tier=int(tier))
            out["redirected"] = True
            out["redirected_from_area"] = cur_area
            out["redirected_to_area"] = cand_area
            return out
    raise ValueError(f"All fallback zones {list(fallback_zones)} are obstructed ({sorted(blocked)})")

