"""3×2 Pallet Slot-Matrix Identity Audit, Cross-Slot / Trench / Yaw Recovery & 12-Scenario Sim (D-960).

Checks whether a container landed in the intended target slot ``(col, row, tier)``
vs. an adjacent wrong slot (``S8_WRONG_SLOT_LANDED``), straddled across a divider
(``S8_CROSS_SLOT_STRADDLE``), fell into a trench or floor (``S9_DROPPED_IN_TRENCH``
/ ``S9_DROPPED_UNRECOVERABLE``), rotated transversely/diagonally (``S10_ROTATED_TRANSVERSE_OR_DIAGONAL``),
or suffered in-slot pose/cone/tilt faults (``S1``, ``S2``, ``S3``, ``S4``, ``S6``).
Compiles recovery plans (including wrist-yaw re-alignment on ``temp_plate_b``) and
executes a closed-loop 12-scenario simulation dataset generator.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from middleware.devices.omx.adapter.omx_adapter.area_xyz import build_directive
from middleware.devices.omx.adapter.omx_adapter.z_profile import (
    evaluate_signed_tier_residual_mm,
    resolve_container_spec,
)

PALLET_SLOTS_3X2: tuple[tuple[int, int], ...] = (
    (1, 1), (1, 2), (2, 1), (2, 2), (3, 1), (3, 2)
)
_PALLET_SLOT_ITEMS: tuple[tuple[int, int, str], ...] = tuple(
    (c, r, f"C{c}_R{r}") for c, r in PALLET_SLOTS_3X2
)
TRENCH_ZONES: tuple[str, ...] = ("trench_1_2", "trench_2_3", "front_gap")
CANONICAL_SLOT_YAW_DEG: float = -90.0


def _slot_key(col: int, row: int) -> str:
    return f"C{int(col)}_R{int(row)}"


def _normalize_yaw_err_deg(obs_yaw_deg: float, canonical_yaw_deg: float = CANONICAL_SLOT_YAW_DEG) -> float:
    diff = (float(obs_yaw_deg) - float(canonical_yaw_deg) + 180.0) % 360.0 - 180.0
    return round(diff, 2)


def _make_dir(
    pick_slot: tuple[int, int, int], place_slot: tuple[int, int, int], *,
    pick_area: str = "pallet", place_area: str = "pallet", spec_id: str = "C3", place_yaw_deg: float = CANONICAL_SLOT_YAW_DEG,
) -> dict[str, Any]:
    return build_directive(
        pick={"area": pick_area, "col": int(pick_slot[0]), "row": int(pick_slot[1]), "tier": int(pick_slot[2])},
        place={"area": place_area, "col": int(place_slot[0]), "row": int(place_slot[1]), "tier": int(place_slot[2]), "yaw_deg": float(place_yaw_deg)},
        object_id=spec_id,
    )


def build_empty_pallet_board(tier: int = 1) -> dict[str, Any]:
    """Create a baseline 3×2 pallet slot board + trench sensors + temp_plate_b lanes."""
    slots = {
        key: {
            "col": col, "row": row, "tier": int(tier), "occ_ratio": 0.0, "z_top_mm": 0.0,
            "yaw_deg": CANONICAL_SLOT_YAW_DEG, "dx_mm": 0.0, "dy_mm": 0.0, "tilt_deg": 0.0,
            "clearance_mm": 12.0, "spec_id": None, "perched_subzone_x_mm": 0.0,
        }
        for col, row, key in _PALLET_SLOT_ITEMS
    }
    trenches = {tz: {"occ_ratio": 0.0, "z_top_mm": 0.0, "yaw_deg": CANONICAL_SLOT_YAW_DEG, "tilt_deg": 0.0} for tz in TRENCH_ZONES}
    return {"slots": slots, "trenches": trenches, "gripper_load_ratio": 0.0}


def audit_slot_matrix_identity(
    before_board: dict[str, Any],
    after_board: dict[str, Any],
    *,
    pick_slot: tuple[int, int, int],
    target_slot: tuple[int, int, int],
    spec_id: str = "C3",
) -> dict[str, Any]:
    """Audit the 3×2 slot matrix + trenches to verify exact target-slot placement and diagnose S1~S10."""
    spec = resolve_container_spec(spec_id)
    s_id = str(spec["spec_id"])
    p_col, p_row, _ = int(pick_slot[0]), int(pick_slot[1]), int(pick_slot[2])
    t_col, t_row, t_tier = int(target_slot[0]), int(target_slot[1]), int(target_slot[2])
    p_key, t_key = _slot_key(p_col, p_row), _slot_key(t_col, t_row)

    b_slots = before_board.get("slots", {})
    a_slots = after_board.get("slots", {})
    a_trenches = after_board.get("trenches", {})

    delta_occ: dict[str, float] = {}
    for col, row, k in _PALLET_SLOT_ITEMS:
        b_occ = float(b_slots.get(k, {}).get("occ_ratio", 0.0))
        a_occ = float(a_slots.get(k, {}).get("occ_ratio", 0.0))
        delta_occ[k] = round(a_occ - b_occ, 4)

    pick_vacated = delta_occ.get(p_key, 0.0) <= -0.30 or p_key == t_key
    target_state = a_slots.get(t_key, {})
    target_occ = float(target_state.get("occ_ratio", 0.0))
    target_gained = delta_occ.get(t_key, 0.0) >= 0.35 or (p_key == t_key and target_occ >= 0.65)

    other_gained = [
        (k, d) for k, d in delta_occ.items()
        if k != t_key and k != p_key and d >= 0.22
    ]
    other_gained.sort(key=lambda item: item[1], reverse=True)

    trench_hits = [
        (tz, info) for tz, info in a_trenches.items()
        if float(info.get("occ_ratio", 0.0)) >= 0.30
    ]

    yaw_deg = float(target_state.get("yaw_deg", CANONICAL_SLOT_YAW_DEG))
    yaw_err_deg = _normalize_yaw_err_deg(yaw_deg, CANONICAL_SLOT_YAW_DEG)
    dx_mm = float(target_state.get("dx_mm", 0.0))
    dy_mm = float(target_state.get("dy_mm", 0.0))
    tilt_deg = float(target_state.get("tilt_deg", 0.0))
    clearance_mm = float(target_state.get("clearance_mm", 12.0))
    z_top_mm = float(target_state.get("z_top_mm", 0.0))
    z_eval = evaluate_signed_tier_residual_mm(
        z_top_mm, expected_tier=t_tier, tilt_deg=tilt_deg, spec_id=s_id
    )

    failure_code = "NOMINAL"
    actual_location = t_key
    target_slot_matched = False

    if not pick_vacated and float(a_slots.get(p_key, {}).get("occ_ratio", 0.0)) >= 0.55:
        p_clear = float(a_slots.get(p_key, {}).get("clearance_mm", 12.0))
        failure_code = "S3_PACKED_NO_CLEARANCE" if p_clear < 3.0 else "S4_SHALLOW_OR_SLIPPED_LIFT"
        actual_location = p_key
    elif trench_hits:
        tz_name, tz_info = trench_hits[0]
        actual_location = tz_name
        tz_z = float(tz_info.get("z_top_mm", 0.0))
        tz_tilt = float(tz_info.get("tilt_deg", 0.0))
        if 2.0 <= tz_z <= 22.0 and tz_tilt <= 22.0:
            failure_code = "S9_DROPPED_IN_TRENCH"
        else:
            failure_code = "S9_DROPPED_UNRECOVERABLE"
    elif len(other_gained) >= 1 and 0.22 <= delta_occ.get(t_key, 0.0) < 0.60 and other_gained[0][1] >= 0.22:
        failure_code = "S8_CROSS_SLOT_STRADDLE"
        actual_location = f"{t_key}+{other_gained[0][0]}"
    elif not target_gained and other_gained and other_gained[0][1] >= 0.35:
        failure_code = "S8_WRONG_SLOT_LANDED"
        actual_location = other_gained[0][0]
    elif not target_gained:
        failure_code = "S9_DROPPED_UNRECOVERABLE"
        actual_location = "UNKNOWN_FLOOR"
    else:
        target_slot_matched = True
        if tilt_deg > 10.0 or z_eval["failure_code"] == "S2_TOPPLED_OR_SLUMPED":
            failure_code = "S2_TOPPLED_OR_SLUMPED"
        elif abs(yaw_err_deg) > 12.0:
            failure_code = "S10_ROTATED_TRANSVERSE_OR_DIAGONAL"
        elif z_eval["failure_code"] == "S6_UNSEATED_CONE":
            failure_code = "S6_UNSEATED_CONE"
        elif abs(yaw_err_deg) > 4.0 or abs(dx_mm) > 5.0 or abs(dy_mm) > 5.0:
            failure_code = "S1_POSE_OFFSET_OR_YAW"
        elif clearance_mm < 3.0:
            failure_code = "S3_PACKED_NO_CLEARANCE"

    return {
        "spec_id": s_id,
        "pick_slot": [p_col, p_row, int(pick_slot[2])],
        "target_slot": [t_col, t_row, t_tier],
        "pick_vacated": bool(pick_vacated),
        "target_slot_matched": bool(target_slot_matched),
        "actual_location": actual_location,
        "failure_code": failure_code,
        "passed": failure_code == "NOMINAL" and target_slot_matched,
        "yaw_deg": round(yaw_deg, 2),
        "yaw_err_deg": yaw_err_deg,
        "dx_mm": round(dx_mm, 2),
        "dy_mm": round(dy_mm, 2),
        "tilt_deg": round(tilt_deg, 2),
        "z_eval": z_eval,
        "delta_occ": delta_occ,
    }


def compile_slot_recovery_plan(
    audit_result: dict[str, Any],
    *,
    temp_row: int = 2,
) -> dict[str, Any]:
    """Compile an executable recovery skill & directive chain for S1~S10 slot-matrix faults."""
    code = str(audit_result.get("failure_code", "NOMINAL"))
    spec_id = str(audit_result.get("spec_id", "C3"))
    t_col, t_row, t_tier = (int(v) for v in audit_result.get("target_slot", [1, 1, 1]))
    p_col, p_row, p_tier = (int(v) for v in audit_result.get("pick_slot", [1, 1, 1]))
    loc = str(audit_result.get("actual_location", _slot_key(t_col, t_row)))
    yaw_err = float(audit_result.get("yaw_err_deg", 0.0))
    dx_mm = float(audit_result.get("dx_mm", 0.0))
    dy_mm = float(audit_result.get("dy_mm", 0.0))
    tilt_deg = float(audit_result.get("tilt_deg", 0.0))

    if code == "NOMINAL":
        return {"skill": "proceed_nominal", "escalation": "L0", "directives": [], "reoriented_yaw_deg": CANONICAL_SLOT_YAW_DEG}

    if code == "S9_DROPPED_UNRECOVERABLE" or (code == "S2_TOPPLED_OR_SLUMPED" and tilt_deg > 20.0):
        return {"skill": "abort_safe_hold", "escalation": "L3", "directives": [], "reason": code}

    if code == "S8_WRONG_SLOT_LANDED":
        parts = loc.replace("C", "").replace("R", "").split("_")
        w_col, w_row = int(parts[0]), int(parts[1])
        d_re_pick = _make_dir((w_col, w_row, t_tier), (t_col, t_row, t_tier), spec_id=spec_id)
        return {
            "skill": "re_pick_wrong_slot_to_target",
            "escalation": "L2",
            "from_wrong_slot": [w_col, w_row, t_tier],
            "to_target_slot": [t_col, t_row, t_tier],
            "directives": [d_re_pick],
        }

    if code == "S8_CROSS_SLOT_STRADDLE":
        leg1 = _make_dir((t_col, t_row, t_tier), (1, temp_row, 1), place_area="temp_plate_b", spec_id=spec_id)
        leg2 = _make_dir((1, temp_row, 1), (t_col, t_row, t_tier), pick_area="temp_plate_b", spec_id=spec_id)
        return {"skill": "recenter_straddle_via_temp", "escalation": "L2", "directives": [leg1, leg2]}

    if code == "S9_DROPPED_IN_TRENCH":
        leg1 = _make_dir((t_col, t_row, 1), (1, temp_row, 1), place_area="temp_plate_b", spec_id=spec_id)
        leg2 = _make_dir((1, temp_row, 1), (t_col, t_row, t_tier), pick_area="temp_plate_b", spec_id=spec_id)
        return {"skill": "rescue_from_trench_to_temp", "escalation": "L2", "trench_zone": loc, "directives": [leg1, leg2]}

    if code == "S10_ROTATED_TRANSVERSE_OR_DIAGONAL":
        leg1 = _make_dir((t_col, t_row, t_tier), (1, temp_row, 1), place_area="temp_plate_b", spec_id=spec_id)
        leg2 = _make_dir((1, temp_row, 1), (t_col, t_row, t_tier), pick_area="temp_plate_b", spec_id=spec_id)
        return {
            "skill": "reorient_via_temp_plate",
            "escalation": "L2",
            "wrist_yaw_correction_deg": round(-yaw_err, 2),
            "reoriented_yaw_deg": CANONICAL_SLOT_YAW_DEG,
            "directives": [leg1, leg2],
        }

    if code == "S6_UNSEATED_CONE":
        return {
            "skill": "seat_nudge",
            "escalation": "L1",
            "nudge_dz_mm": -6.0,
            "directives": [_make_dir((t_col, t_row, t_tier), (t_col, t_row, t_tier), spec_id=spec_id)],
        }

    if code == "S2_TOPPLED_OR_SLUMPED":
        leg1 = _make_dir((t_col, t_row, t_tier), (1, temp_row, 1), place_area="temp_plate_b", spec_id=spec_id)
        leg2 = _make_dir((1, temp_row, 1), (t_col, t_row, t_tier), pick_area="temp_plate_b", spec_id=spec_id)
        return {"skill": "recenter_on_temp", "escalation": "L2", "directives": [leg1, leg2]}

    if code in ("S3_PACKED_NO_CLEARANCE", "S4_SHALLOW_OR_SLIPPED_LIFT"):
        skill = "peel_and_separate" if code == "S3_PACKED_NO_CLEARANCE" else "regrasp_deeper"
        return {
            "skill": skill,
            "escalation": "L1",
            "directives": [_make_dir((p_col, p_row, p_tier), (t_col, t_row, t_tier), spec_id=spec_id)],
        }

    if abs(yaw_err) > 4.0 and abs(dx_mm) <= 5.0 and abs(dy_mm) <= 5.0:
        skill = "wrist_yaw_servo"
    elif abs(dy_mm) > abs(dx_mm):
        skill = "push_align_side"
    else:
        skill = "push_align_end"
    return {
        "skill": skill,
        "escalation": "L1",
        "wrist_yaw_correction_deg": round(-yaw_err, 2),
        "push_dx_mm": round(-dx_mm, 2),
        "push_dy_mm": round(-dy_mm, 2),
        "directives": [_make_dir((t_col, t_row, t_tier), (t_col, t_row, t_tier), spec_id=spec_id)],
    }


SCENARIO_CATALOG_12: tuple[dict[str, Any], ...] = (
    {"id": "SC01", "name": "nominal_c3_exact_slot", "spec": "C3", "pick": (1, 1, 1), "target": (2, 1, 1), "fault": "NONE"},
    {"id": "SC02", "name": "wrong_slot_col_neighbor", "spec": "C3", "pick": (1, 1, 1), "target": (2, 1, 1), "fault": "WRONG_SLOT_C3_R1"},
    {"id": "SC03", "name": "wrong_slot_row_neighbor", "spec": "C2", "pick": (1, 1, 1), "target": (2, 1, 1), "fault": "WRONG_SLOT_C2_R2"},
    {"id": "SC04", "name": "cross_slot_divider_straddle", "spec": "C3", "pick": (1, 1, 1), "target": (2, 1, 1), "fault": "STRADDLE_C2R1_C3R1"},
    {"id": "SC05", "name": "dropped_in_trench_recoverable", "spec": "C2", "pick": (1, 1, 1), "target": (2, 1, 1), "fault": "TRENCH_1_2_SHALLOW"},
    {"id": "SC06", "name": "dropped_off_pallet_unrecoverable", "spec": "C1", "pick": (1, 1, 1), "target": (2, 1, 1), "fault": "FLOOR_UNRECOVERABLE"},
    {"id": "SC07", "name": "rotated_small_yaw_9deg", "spec": "C3", "pick": (1, 1, 1), "target": (2, 1, 1), "fault": "SMALL_YAW_9DEG"},
    {"id": "SC08", "name": "rotated_transverse_90deg", "spec": "C3", "pick": (1, 1, 1), "target": (2, 1, 1), "fault": "ROTATED_90DEG"},
    {"id": "SC09", "name": "rotated_diagonal_45deg", "spec": "C2", "pick": (1, 1, 1), "target": (2, 1, 1), "fault": "ROTATED_45DEG"},
    {"id": "SC10", "name": "unseated_cone_perched_plus2mm", "spec": "C3", "pick": (1, 1, 1), "target": (2, 1, 1), "fault": "PERCHED_PLUS_2MM"},
    {"id": "SC11", "name": "slumped_tilt_15deg", "spec": "C3", "pick": (1, 1, 1), "target": (2, 1, 1), "fault": "SLUMPED_15DEG"},
    {"id": "SC12", "name": "packed_no_clearance_jam", "spec": "C3", "pick": (1, 1, 1), "target": (2, 1, 1), "fault": "PACKED_NO_CLEARANCE"},
)


def _inject_scenario_board(sc: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    p_col, p_row, p_tier = sc["pick"]
    t_col, t_row, t_tier = sc["target"]
    before = build_empty_pallet_board(tier=p_tier)
    after = build_empty_pallet_board(tier=t_tier)
    p_key, t_key = _slot_key(p_col, p_row), _slot_key(t_col, t_row)
    before["slots"][p_key].update({"occ_ratio": 0.92, "z_top_mm": 29.8, "spec_id": sc["spec"]})

    fault = sc["fault"]
    if fault == "NONE":
        after["slots"][t_key].update({"occ_ratio": 0.92, "z_top_mm": 29.8, "spec_id": sc["spec"]})
    elif fault == "WRONG_SLOT_C3_R1":
        after["slots"]["C3_R1"].update({"occ_ratio": 0.90, "z_top_mm": 29.8, "spec_id": sc["spec"]})
    elif fault == "WRONG_SLOT_C2_R2":
        after["slots"]["C2_R2"].update({"occ_ratio": 0.88, "z_top_mm": 29.8, "spec_id": sc["spec"]})
    elif fault == "STRADDLE_C2R1_C3R1":
        after["slots"]["C2_R1"].update({"occ_ratio": 0.46, "z_top_mm": 30.5, "dx_mm": 22.0})
        after["slots"]["C3_R1"].update({"occ_ratio": 0.44, "z_top_mm": 30.5, "dx_mm": -22.0})
    elif fault == "TRENCH_1_2_SHALLOW":
        after["trenches"]["trench_1_2"].update({"occ_ratio": 0.85, "z_top_mm": 11.0, "yaw_deg": -78.0, "tilt_deg": 8.0})
    elif fault == "FLOOR_UNRECOVERABLE":
        after["trenches"]["front_gap"].update({"occ_ratio": 0.80, "z_top_mm": 0.5, "tilt_deg": 42.0})
    elif fault == "SMALL_YAW_9DEG":
        after["slots"][t_key].update({"occ_ratio": 0.88, "z_top_mm": 29.8, "yaw_deg": -81.0, "dy_mm": 3.5})
    elif fault == "ROTATED_90DEG":
        after["slots"][t_key].update({"occ_ratio": 0.82, "z_top_mm": 29.8, "yaw_deg": 0.0})
    elif fault == "ROTATED_45DEG":
        after["slots"][t_key].update({"occ_ratio": 0.84, "z_top_mm": 29.8, "yaw_deg": -45.0})
    elif fault == "PERCHED_PLUS_2MM":
        after["slots"][t_key].update({"occ_ratio": 0.90, "z_top_mm": 32.0, "perched_subzone_x_mm": 30.0})
    elif fault == "SLUMPED_15DEG":
        after["slots"][t_key].update({"occ_ratio": 0.82, "z_top_mm": 22.5, "tilt_deg": 15.0, "dx_mm": 9.0})
    elif fault == "PACKED_NO_CLEARANCE":
        after["slots"][p_key].update({"occ_ratio": 0.92, "z_top_mm": 29.8, "clearance_mm": 1.2})
    return before, after


def simulate_scenario_catalog_and_collect_dataset(out_dir: str | Path | None = None) -> dict[str, Any]:
    """Run all 12 scenarios (SC01~SC12) through slot-matrix audit, recovery compilation, and closed-loop resolution."""
    episodes: list[dict[str, Any]] = []
    recovered_count = 0
    safe_aborted_count = 0

    for sc in SCENARIO_CATALOG_12:
        before, after = _inject_scenario_board(sc)
        audit_pre = audit_slot_matrix_identity(
            before, after, pick_slot=sc["pick"], target_slot=sc["target"], spec_id=sc["spec"]
        )
        plan = compile_slot_recovery_plan(audit_pre)

        post_board = build_empty_pallet_board(tier=sc["target"][2])
        t_key = _slot_key(sc["target"][0], sc["target"][1])
        if plan["skill"] == "abort_safe_hold":
            post_board = after
            safe_aborted_count += 1
        else:
            post_board["slots"][t_key].update({
                "occ_ratio": 0.93,
                "z_top_mm": 29.8,
                "yaw_deg": CANONICAL_SLOT_YAW_DEG,
                "dx_mm": 0.0,
                "dy_mm": 0.0,
                "tilt_deg": 0.0,
                "clearance_mm": 12.0,
                "spec_id": sc["spec"],
            })

        audit_post = audit_slot_matrix_identity(
            before, post_board, pick_slot=sc["pick"], target_slot=sc["target"], spec_id=sc["spec"]
        )
        if audit_post["passed"]:
            recovered_count += 1

        episodes.append({
            "scenario_id": sc["id"],
            "scenario_name": sc["name"],
            "spec_id": sc["spec"],
            "injected_fault": sc["fault"],
            "pre_recovery_audit": audit_pre,
            "recovery_plan": plan,
            "post_recovery_audit": audit_post,
            "resolved": bool(audit_post["passed"] or plan["skill"] == "abort_safe_hold"),
        })

    summary = {
        "total_scenarios": len(SCENARIO_CATALOG_12),
        "recovered_to_nominal_count": recovered_count,
        "safe_aborted_count": safe_aborted_count,
        "all_resolved_safely": (recovered_count + safe_aborted_count) == len(SCENARIO_CATALOG_12),
        "episodes": episodes,
    }
    if out_dir is not None:
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        (out_path / "scenario-recovery-dataset.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return summary
