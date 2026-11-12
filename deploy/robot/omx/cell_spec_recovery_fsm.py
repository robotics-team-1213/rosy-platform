#!/usr/bin/env python3
"""Round 2 Consensus 6-Gate Execution Interlock & S1~S7 Alignment/Recovery Skill FSM (`cell_spec_recovery_fsm.py`).

Single Responsibility:
  - Evaluates the 6 execution interlock gates (`pre_grasp`, `at_grasp`, `lift_verify`,
    `pre_place`, `post_release`, `leg_transition`) with explicit `PASS` | `FAIL` | `UNKNOWN` verdicts
    and canonical `S1..S7` failure codes (`evaluate_execution_gate`).
  - Selects the exact L0/L1/L2/L3 recovery skill primitive (`reobserve_shift`, `seat_nudge`,
    `reinsert_pick`, `wrist_yaw_servo`, `push_align_side`, `push_align_end`, `free_push`,
    `recenter_on_temp`, `clear_neighbor_then_pick`, `abort_safe_hold`) using the Round 2
    consensus numerical decision boundaries (`select_recovery_skill`).
  - Compiles the 2-leg `S-Temp` fixture-assisted re-centering directives (`compile_recenter_on_temp_directives`)
    routing through `temp_plate_b` radial lanes `R1..R3` (`-141.3°`, `-159.6°`, `-0.1°`).
"""
from __future__ import annotations

from typing import Any
import uuid

from omx_adapter.area_xyz import DIRECTIVE_SCHEMA, build_directive, coerce_area_xyz, resolve_area_xyz

FSM_SCHEMA = "rosy.omx-spec-recovery-fsm.v1"

GATE_NAMES: tuple[str, ...] = (
    "pre_grasp", "at_grasp", "lift_verify", "pre_place", "post_release", "leg_transition",
)

FAILURE_CODES: tuple[str, ...] = (
    "S1_POSE_OFFSET_OR_YAW",
    "S2_TOPPLED_OR_SLUMPED",
    "S3_PACKED_NO_CLEARANCE",
    "S4_EMPTY_AIR_CLOSE",
    "S4_SHALLOW_OR_SLIPPED_LIFT",
    "S5_VIEW_OR_GATE_MISMATCH",
    "S5_X_BIMODAL_AMBIGUOUS",
    "S5_HEIGHT_ANOMALY",
    "S6_UNSEATED_CONE",
    "S7_DESCEND_OR_GRASP_CONTACT",
    "S7_PRIOR_LEG_FAILED_INTERLOCK",
    "S9_DISPLACED_CONTAINER_BELT_FAR",
    "S10_DISPLACED_CONTAINER_FLOOR_FRONT",
)

CELL_S_EXTENDED_ZONES: dict[str, dict[str, Any]] = {
    "pinky_tray": {
        "site": "pinky",
        "top_roi_px": (10, 40, 260, 240),
        "grasp_pose_units": [66.929, -5.845, 29.839, 39.243, 111.797],
        "hover_pose_units": [66.929, -24.0, 22.0, 39.243, 111.797],
        "xyz_m": (0.0535, 0.1720, 0.0200),
        "yaw_deg": -85.0,
    },
    "belt_center": {
        "site": "belt",
        "top_roi_px": (240, 90, 460, 270),
        "grasp_pose_units": [4.966, -15.337, 36.168, 43.330, 46.846],
        "hover_pose_units": [4.966, -27.0, 22.0, 43.330, 46.846],
        "xyz_m": (0.1250, -0.0550, 0.0250),
        "yaw_deg": -85.0,
    },
    "belt_far": {
        "site": "belt_far",
        "top_roi_px": (320, 110, 620, 290),
        "grasp_pose_units": [-27.685, 6.725, -2.289, 45.649, 17.882],
        "hover_pose_units": [-27.685, -27.0, 22.0, 45.649, 17.882],
        "xyz_m": (0.1850, -0.0950, 0.0250),
        "yaw_deg": -85.0,
    },
    "floor_front": {
        "site": "floor_front",
        "top_roi_px": (60, 180, 280, 420),
        "grasp_pose_units": [44.121, 9.500, 14.200, 38.000, 88.242],
        "hover_pose_units": [44.121, -27.0, 22.0, 38.000, 88.242],
        "xyz_m": (0.0950, 0.0980, 0.0080),
        "yaw_deg": -85.0,
    },
}

TEMP_PLATE_B_LANES_XY_YAW: dict[int, tuple[float, float, float]] = {
    1: (0.1163, -0.1452, -141.3),
    2: (0.0584, -0.1567, -159.6),
    3: (-0.0004, -0.1521, -0.1),
}

TEMP_PLATE_A_LANES_XY_YAW: dict[int, tuple[float, float, float]] = {
    1: (-0.0681, 0.1841, -3.1),
    2: (-0.0109, 0.1729, -18.7),
    3: (0.0419, 0.1465, -34.4),
}


def _extract_jaw(r_step: dict[str, Any] | None, gripper_pos: float | None) -> float | None:
    if gripper_pos is not None:
        return float(gripper_pos)
    state = r_step.get("state") if isinstance(r_step, dict) else None
    if isinstance(state, (list, tuple)) and len(state) >= 6 and state[-1] is not None:
        return float(state[-1])
    return None


def _extract_current_ma(r_step: dict[str, Any] | None, current_ma: float | None) -> float | None:
    if current_ma is not None:
        return float(current_ma)
    if isinstance(r_step, dict) and r_step.get("gripper_current_ma") is not None:
        return float(r_step["gripper_current_ma"])
    return None


def _gate_res(gate: str, verdict: str, failure_code: str | None = None, reason: str = "") -> dict[str, Any]:
    return {"gate": gate, "verdict": verdict, "ok": verdict == "PASS", "failure_code": failure_code, "reason": reason}


def _skill_res(level: str, skill: str, code: str, **params: Any) -> dict[str, Any]:
    return {"level": level, "skill": skill, "failure_code": code, "params": params}


def evaluate_execution_gate(
    gate_name: str,
    *,
    r_step: dict[str, Any] | None = None,
    z_gate: dict[str, Any] | None = None,
    wrist_obs: dict[str, Any] | None = None,
    gripper_pos: float | None = None,
    current_ma: float | None = None,
    lift_delta_mm: float | None = None,
    clearance_min_mm: float = 6.0,
    sigma_x_mm: float = 0.0,
    prior_leg_result: str | None = None,
) -> dict[str, Any]:
    """Evaluate one of the 6 execution interlock gates (`pre_grasp`, `at_grasp`, `lift_verify`,
    `pre_place`, `post_release`, `leg_transition`)."""
    gate = str(gate_name).strip().lower()
    jaw = _extract_jaw(r_step, gripper_pos)
    curr = _extract_current_ma(r_step, current_ma)
    eff_sigma_x = float(sigma_x_mm or (wrist_obs or {}).get("sigma_x_mm") or 0.0)

    if gate == "pre_grasp":
        if 2.0 * eff_sigma_x > 5.0:
            return _gate_res(gate, "UNKNOWN", "S5_X_BIMODAL_AMBIGUOUS", f"2*sigma_x_mm={2.0 * eff_sigma_x:.2f} > 5.0mm")
        if isinstance(z_gate, dict) and z_gate.get("verdict", "PASS") != "PASS":
            v_z = str(z_gate.get("verdict") or "FAIL")
            f_code = str(z_gate.get("failure_code") or "S5_VIEW_OR_GATE_MISMATCH")
            return _gate_res(gate, v_z, f_code, str(z_gate.get("reason") or f"z_gate returned {v_z} ({f_code})"))
        if float(clearance_min_mm) < 5.0:
            return _gate_res(gate, "FAIL", "S3_PACKED_NO_CLEARANCE", f"clearance {float(clearance_min_mm):.2f}mm < 5.0mm")
        return _gate_res(gate, "PASS", None, "pre_grasp interlock passed")

    if gate == "at_grasp":
        if isinstance(r_step, dict) and "ok" in r_step and not r_step.get("ok"):
            return _gate_res(gate, "FAIL", "S7_DESCEND_OR_GRASP_CONTACT", str(r_step.get("error") or "grasp contact"))
        if jaw is not None and jaw < 51.5 and abs(float(curr or 0.0)) < 65.0:
            return _gate_res(gate, "FAIL", "S4_EMPTY_AIR_CLOSE", f"jaws={jaw:.2f}u (<51.5) current={curr}mA (<65)")
        return _gate_res(gate, "PASS", None, "at_grasp interlock passed")

    if gate == "lift_verify":
        if isinstance(r_step, dict) and "ok" in r_step and not r_step.get("ok"):
            return _gate_res(gate, "FAIL", "S7_DESCEND_OR_GRASP_CONTACT", str(r_step.get("error") or "lift contact"))
        curr_low = curr is not None and abs(float(curr)) < 75.0
        jaw_outside = jaw is not None and not (51.8 <= jaw <= 56.8)
        lift_short = lift_delta_mm is not None and float(lift_delta_mm) < 3.5
        if curr_low or jaw_outside or lift_short:
            msg = f"lift_verify failed (jaw={jaw}, current_ma={curr}, lift_delta_mm={lift_delta_mm})"
            return _gate_res(gate, "FAIL", "S4_SHALLOW_OR_SLIPPED_LIFT", msg)
        return _gate_res(gate, "PASS", None, "lift_verify interlock passed")

    if gate == "pre_place":
        if isinstance(r_step, dict) and "ok" in r_step and not r_step.get("ok"):
            return _gate_res(gate, "FAIL", "S7_DESCEND_OR_GRASP_CONTACT", str(r_step.get("error") or "place contact"))
        if isinstance(z_gate, dict) and z_gate.get("verdict", "PASS") != "PASS":
            v_z = str(z_gate.get("verdict") or "FAIL")
            f_code = str(z_gate.get("failure_code") or "S5_VIEW_OR_GATE_MISMATCH")
            return _gate_res(gate, v_z, f_code, str(z_gate.get("reason") or f"pre_place z_gate {v_z}"))
        if float(clearance_min_mm) < 5.0:
            return _gate_res(gate, "FAIL", "S3_PACKED_NO_CLEARANCE", f"place clearance {float(clearance_min_mm):.2f}mm < 5.0mm")
        return _gate_res(gate, "PASS", None, "pre_place interlock passed")

    if gate == "post_release":
        if isinstance(z_gate, dict):
            r_k = z_gate.get("r_k_mm")
            if r_k is not None and 1.0 <= float(r_k) <= 3.0:
                return _gate_res(gate, "FAIL", "S6_UNSEATED_CONE", f"r_k_mm={float(r_k):.2f}mm in [1.0, 3.0]mm")
            if z_gate.get("verdict", "PASS") != "PASS":
                v_z = str(z_gate.get("verdict") or "FAIL")
                f_code = str(z_gate.get("failure_code") or "S6_UNSEATED_CONE")
                return _gate_res(gate, v_z, f_code, str(z_gate.get("reason") or "post_release z_gate failed"))
        return _gate_res(gate, "PASS", None, "post_release interlock passed")

    if gate == "leg_transition":
        leg_res = prior_leg_result
        if leg_res is None and isinstance(r_step, dict):
            if "result" in r_step:
                leg_res = str(r_step["result"])
            elif "prior_leg_result" in r_step:
                leg_res = str(r_step["prior_leg_result"])
            elif "ok" in r_step and not r_step.get("ok"):
                leg_res = "fault"
        if leg_res is None and isinstance(z_gate, dict) and "prior_leg_result" in z_gate:
            leg_res = str(z_gate["prior_leg_result"])
        if leg_res is not None and leg_res != "placed":
            return _gate_res(gate, "FAIL", "S7_PRIOR_LEG_FAILED_INTERLOCK", f"prior leg result={leg_res!r} != 'placed'")
        return _gate_res(gate, "PASS", None, "leg_transition interlock passed")

    return _gate_res(gate, "UNKNOWN", "S5_VIEW_OR_GATE_MISMATCH", f"unknown gate {gate!r}")


def select_recovery_skill(
    failure_code: str,
    *,
    gate_ok: bool = True,
    sigma_x_mm: float = 0.0,
    dy_mm: float = 0.0,
    dx_mm: float = 0.0,
    yaw_err_deg: float = 0.0,
    r_k_mm: float = 0.0,
    tilt_deg: float = 0.0,
    swept_clearance_mm: float = 6.0,
    free_push_open: bool = False,
    temp_slot_free: bool = True,
    neighbor_removable: bool = True,
    level_tried: int = 0,
    target_site: str = "pinky",
) -> dict[str, Any]:
    """Select the L0/L1/L2/L3 recovery skill primitive using Round 2 consensus numerical decision boundaries."""
    code = str(failure_code or "").strip()

    if code == "S9_DISPLACED_CONTAINER_BELT_FAR":
        norm_target = str(target_site or "pinky").strip().lower()
        skill_name = (
            "recover_from_belt_far_to_belt_center"
            if norm_target in ("belt", "belt_center")
            else "recover_from_belt_far_to_pinky"
        )
        return _skill_res(
            "L2",
            skill_name,
            code,
            displaced_zone="belt_far",
            target_site=norm_target,
            grasp_pose_units=list(CELL_S_EXTENDED_ZONES["belt_far"]["grasp_pose_units"]),
            crane_shoulder_lift=-27.0,
            crane_elbow_flex=22.0,
            max_step=0.032,
            lift_before_pan=True,
        )

    if code == "S10_DISPLACED_CONTAINER_FLOOR_FRONT":
        norm_target = str(target_site or "pinky").strip().lower()
        return _skill_res(
            "L2",
            "recover_from_floor_front_to_pinky",
            code,
            displaced_zone="floor_front",
            target_site=norm_target,
            grasp_pose_units=list(CELL_S_EXTENDED_ZONES["floor_front"]["grasp_pose_units"]),
            crane_shoulder_lift=-27.0,
            crane_elbow_flex=22.0,
            max_step=0.032,
            lift_before_pan=True,
        )

    if code in ("S5_VIEW_OR_GATE_MISMATCH", "S5_X_BIMODAL_AMBIGUOUS", "S5_HEIGHT_ANOMALY") or not gate_ok or 2.0 * float(sigma_x_mm) > 5.0:
        if int(level_tried) == 0:
            return _skill_res("L0", "reobserve_shift", code, shift_xy_mm=[4.0, 0.0], wrist_samples=3)
        return _skill_res("L3", "abort_safe_hold", code, ask_person=True)

    if code == "S6_UNSEATED_CONE":
        rk = float(r_k_mm)
        if (rk == 0.0 or 1.0 <= rk <= 3.0) and float(tilt_deg) <= 5.0 and int(level_tried) == 0:
            return _skill_res("L1", "seat_nudge", code, press_dz_mm=-3.0, wiggle_deg=2.0, max_current_ma=180.0)
        return _skill_res("L3", "abort_safe_hold", code, ask_person=True)

    if code in ("S4_SHALLOW_OR_SLIPPED_LIFT", "S4_EMPTY_AIR_CLOSE"):
        if bool(temp_slot_free) and int(level_tried) >= 1:
            return _skill_res("L2", "recenter_on_temp", code, temp_area="temp_plate_b", lane=2)
        dx_c = round(max(-8.0, min(8.0, float(dx_mm))), 2)
        dy_c = round(max(-8.0, min(8.0, float(dy_mm))), 2)
        return _skill_res("L1", "reinsert_pick", code, dx_mm=dx_c, dy_mm=dy_c)

    if code == "S1_POSE_OFFSET_OR_YAW":
        in_place_ok = (
            bool(gate_ok)
            and 2.0 * float(sigma_x_mm) <= 5.0
            and float(tilt_deg) <= 5.0
            and float(swept_clearance_mm) >= 5.0
            and int(level_tried) == 0
        )
        if in_place_ok:
            if abs(float(yaw_err_deg)) <= 12.0 and abs(float(dy_mm)) <= 1.5 and abs(float(dx_mm)) <= 1.5:
                return _skill_res("L1", "wrist_yaw_servo", code, dyaw_deg=round(float(yaw_err_deg), 1))
            if abs(float(dy_mm)) <= 5.0 and abs(float(dx_mm)) <= 5.0 and abs(float(yaw_err_deg)) <= 12.0:
                return _skill_res("L1", "push_align_side", code, stroke_y_mm=round(float(dy_mm), 2))
            if abs(float(dx_mm)) <= 30.0 and abs(float(dy_mm)) <= 5.0 and abs(float(yaw_err_deg)) <= 12.0:
                return _skill_res("L1", "push_align_end", code, stroke_x_mm=round(float(dx_mm), 2))
        if bool(temp_slot_free):
            return _skill_res("L2", "recenter_on_temp", code, temp_area="temp_plate_b", lane=2)
        return _skill_res("L3", "abort_safe_hold", code, ask_person=True)

    if code == "S3_PACKED_NO_CLEARANCE":
        if bool(free_push_open) and bool(gate_ok) and float(tilt_deg) <= 5.0 and int(level_tried) == 0:
            return _skill_res("L1", "free_push", code, stroke_along_mm=18.0)
        if bool(temp_slot_free) and bool(neighbor_removable):
            return _skill_res("L2", "clear_neighbor_then_pick", code, evacuate_to="temp_plate_b", lane=1)
        return _skill_res("L3", "abort_safe_hold", code, ask_person=True)

    if code in ("S2_TOPPLED_OR_SLUMPED", "S7_DESCEND_OR_GRASP_CONTACT", "S7_PRIOR_LEG_FAILED_INTERLOCK"):
        if (
            code == "S2_TOPPLED_OR_SLUMPED"
            and float(tilt_deg) <= 20.0
            and bool(temp_slot_free)
            and bool(neighbor_removable)
            and int(level_tried) == 0
        ):
            return _skill_res("L2", "recenter_on_temp", code, temp_area="temp_plate_b", lane=2)
        return _skill_res("L3", "abort_safe_hold", code, ask_person=True)

    return _skill_res("L3", "abort_safe_hold", code or "UNKNOWN_FAILURE", ask_person=True)


def compile_recenter_on_temp_directives(
    directive: dict[str, Any],
    *,
    temp_area: str = "temp_plate_b",
    lane: int = 2,
) -> list[dict[str, Any]]:
    """Build the 2-leg `S-Temp` fixture-assisted re-centering sequence:
    - Leg A: pick from original slot -> place into `temp_plate_b` lane `R1..R3` (where radial walls constrain yaw/tilt).
    - Leg B: pick dead-center from `temp_plate_b` lane `R1..R3` -> place into original destination."""
    arm_id = str(directive.get("arm_id") or "arm_b")
    base_id = str(directive.get("directive_id") or f"dir-{uuid.uuid4().hex[:8]}")
    object_id = str(directive.get("object_id") or "container-v2-3")
    lane_idx = int(lane) if int(lane) in (1, 2, 3) else 2
    norm_temp = str(temp_area or "temp_plate_b").strip().lower()
    lanes_map = TEMP_PLATE_A_LANES_XY_YAW if norm_temp == "temp_plate_a" else TEMP_PLATE_B_LANES_XY_YAW
    tx, ty, tyaw = lanes_map[lane_idx]

    orig_pick = coerce_area_xyz(directive["pick"])
    orig_place = coerce_area_xyz(directive["place"])
    temp_slot = resolve_area_xyz(norm_temp, col=lane_idx, row=1, tier=1, x=tx, y=ty, z=0.0074, yaw_deg=tyaw)

    leg_a = build_directive(
        arm_id=arm_id, pick=orig_pick, place=temp_slot,
        directive_id=f"{base_id}-legA-to-temp-r{lane_idx}", object_id=object_id,
    )
    leg_a.update({"schema": DIRECTIVE_SCHEMA, "recovery_skill": "recenter_on_temp", "recovery_leg": "leg_a_to_temp", "temp_lane": lane_idx})

    leg_b = build_directive(
        arm_id=arm_id, pick=temp_slot, place=orig_place,
        directive_id=f"{base_id}-legB-from-temp-r{lane_idx}", object_id=object_id,
    )
    leg_b.update({
        "schema": DIRECTIVE_SCHEMA, "recovery_skill": "recenter_on_temp",
        "recovery_leg": "leg_b_from_temp", "temp_lane": lane_idx, "interlock_requires_leg": leg_a["directive_id"],
    })
    return [leg_a, leg_b]
