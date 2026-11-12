#!/usr/bin/env python3
"""Individual Grasp Judge Evaluators (`cell_grasp_judges.py`).

Single Responsibility:
  - Agent 1 (`telemetry_judge`): Evaluates jaw position (`state[-1]` for 5/6/7-DOF or `state[5]`)
    and squeeze current (`current_ma`) against calibrated `gripper.held_30mm`, catching shallow
    corner pinches, diagonal rim wedges, and low-current slipping grasps.
  - Agent 2 (`vision_judge`): Evaluates wrist camera container centering (`along_mm`, `across_mm`),
    partial-bite / longitudinal edge-clip geometry, and computes bounded corrective shifts
    `(dx_mm, dy_mm, dz_mm)`.
  - Agent 3 (`kinesthetic_judge`): Evaluates post-grasp / post-lift differential jaw slip (`dq_lift`),
    contact stiffness (`k_contact`), and whole-arm load current (`arm_load_delta_ma`) to catch
    containers that were only partially pinched by the fingertips and tilted/slipped under lift load.
  - Structured 3-Seat Council Deliberation (`council_deliberate`), Consensus Evidence Weighting
    (`compute_consensus_evidence_weight`), and model backend normalizers.
"""
from __future__ import annotations

import math

import numpy as np

from cell_finger_container import structural_container_between_fingers
import cell_fingers
from cell_grasp_dynamics import evaluate_grasp_dynamics
import cell_params as prm
import judge_seat

SCHEMA_VERSION = judge_seat.SCHEMA_VERSION
ACTIONS = ("proceed", "reinsert_and_retry", "reinsert_and_park")


def compute_consensus_evidence_weight(
    vision: dict | None = None,
    *,
    il_confidence: float | None = None,
    shape_score: float | None = None,
) -> float:
    """Compute a bounded consensus evidence weight (`0.40 .. 1.15`) combining OpenCV container
    `shape_score` and k-NN Imitation Learning confidence (`il_confidence`)."""
    v_shape = shape_score if shape_score is not None else (vision or {}).get("shape_score")
    if v_shape is None and il_confidence is None:
        return 1.0
    s_val = max(0.0, min(1.0, float(v_shape if v_shape is not None else 0.85)))
    il_val = max(0.0, min(1.0, float(il_confidence if il_confidence is not None else 0.75)))
    return round(max(0.40, min(1.15, 0.45 + 0.45 * s_val + 0.25 * il_val)), 3)


def load_zai_key() -> str | None:
    return judge_seat._resolve_api_key(provider="zai")


def glm_backend(
    model: str = "glm-5.3",
    url: str = "https://api.z.ai/api/coding/paas/v4/chat/completions",
    api_key: str | None = None,
    timeout: float = 15.0,
):
    """Decision model callable `(prompt, images_b64, schema) -> dict` backed by latest GLM (`glm-5.3` / `glm-5.3-flash`)."""
    return judge_seat.openai_chat(url=url, model=model, api_key=api_key, provider="zai", timeout=timeout)


def _jaw_value(state: list | None) -> float | None:
    if not isinstance(state, list) or len(state) < 6:
        return None
    raw = state[-1] if len(state) in (6, 7, 8) else state[5]
    return round(float(raw), 2) if isinstance(raw, (int, float)) else None


def telemetry_judge(state: list | None, holding: bool | None, params=None, current_ma: float | None = None) -> dict:
    """Agent 1: evaluate jaw position (`state[-1]` for 5/6/7-DOF) and squeeze current `current_ma` against nominal 30 mm container width."""
    jaw = _jaw_value(state)
    if holding is False:
        return {"verdict": "empty", "class": "empty", "jaw_units": jaw, "error_units": None, "current_ma": current_ma, "dz_mm": 0.0, "reason": "runner reported holding=False"}
    if jaw is None:
        return {"verdict": "proceed", "class": "unmeasured", "jaw_units": None, "error_units": 0.0, "current_ma": current_ma, "dz_mm": 0.0, "reason": "no jaw state vector"}
    if not isinstance(params, dict) or "gripper.held_30mm" not in params:
        return {"verdict": "proceed", "class": "uncalibrated_jaw_band", "jaw_units": jaw, "error_units": 0.0, "current_ma": current_ma, "dz_mm": 0.0, "reason": "gripper.held_30mm not in params"}
    held_30 = float(prm.get(params, "gripper.held_30mm"))
    closed = float(prm.get(params, "gripper.closed", 48.8))
    open_pos = float(prm.get(params, "gripper.open", 57.85))
    shallow_tol = float(prm.get(params, "grasp.shallow_tol_units", 1.2))
    wedged_tol = float(prm.get(params, "grasp.wedged_tol_units", 0.7))
    min_current = float(prm.get(params, "grasp.min_stable_current_ma", 0.0))
    err = round(jaw - held_30, 2)
    closing_stroke = max(0.35, open_pos - jaw)
    k_contact = round(max(0.0, (abs(float(current_ma)) if current_ma is not None else 80.0) - 18.0) / closing_stroke, 2)
    base = {"jaw_units": jaw, "held_30mm_units": held_30, "error_units": err, "current_ma": current_ma, "k_contact_ma_per_unit": k_contact}
    if err < -shallow_tol:
        return {**base, "verdict": "reinsert", "class": "unstable_shallow", "dz_mm": -2.5, "reason": f"jaws closed {abs(err):.2f} units past nominal 30mm ({jaw} < {held_30 - shallow_tol:.2f}): shallow corner pinch"}
    if err > wedged_tol:
        return {**base, "verdict": "reinsert", "class": "unstable_wedged", "dz_mm": -1.5, "reason": f"jaws stopped {err:.2f} units wider than nominal 30mm ({jaw} > {held_30 + wedged_tol:.2f}): diagonal/rim wedge"}
    if min_current > 0 and current_ma is not None and abs(float(current_ma)) < min_current:
        if prm.get(params, "grasp.stiffness_override", 0) and abs(err) <= 0.85 and (jaw - closed) >= 3.2 and k_contact >= 4.0 and abs(float(current_ma)) >= 32.0:
            return {**base, "verdict": "proceed", "class": "stable_stiffness_arrest", "dz_mm": 0.0, "reason": f"jaw arrested at {jaw}u (|err|={abs(err):.2f}u, k={k_contact}mA/u) compensating low current {abs(float(current_ma)):.0f}mA"}
        return {**base, "verdict": "reinsert", "class": "unstable_slipping", "dz_mm": -2.0, "reason": f"gripper squeeze current {abs(float(current_ma)):.0f} mA below stable threshold {float(min_current):.0f} mA: slipping grasp"}
    return {**base, "verdict": "proceed", "class": "stable", "dz_mm": 0.0, "reason": "jaw span within nominal 30mm stability band"}


def vision_judge(
    wrist_img,
    hsv,
    gap_mm: float,
    closing_deg: float,
    sign: dict | None = None,
    params=None,
    color: str | int | None = None,
) -> dict:
    """Agent 2: measure container centering and partial-bite geometry between the fingers in the wrist camera view."""
    if wrist_img is None:
        return {"verdict": "proceed", "class": "no_frame", "found": False, "dx_mm": 0.0, "dy_mm": 0.0, "dz_mm": 0.0, "reason": "wrist frame not provided"}
    seen = cell_fingers.finger_offset_mm(wrist_img, hsv, gap_mm, params, color=color) if hsv is not None else {"found": False}
    if not seen.get("found") or (seen.get("mode") == "top_face" and float(seen.get("gap_px", 0.0)) < 120.0):
        struct = structural_container_between_fingers(wrist_img)
        if struct and struct.get("is_container_shape"):
            seen = {
                "found": True,
                "along_mm": float(struct["dx_mm"]),
                "across_mm": float(struct["dy_mm"]),
                "mm_per_px": struct.get("mm_per_px"),
                "clipped_border": bool(struct.get("clipped_border", False)),
                "y_front": float(struct.get("y_front", 360.0)),
                "mode": "structural",
            }
        else:
            return {"verdict": "proceed", "class": "no_frame" if hsv is None else "unseen", "found": False, "dx_mm": 0.0, "dy_mm": 0.0, "dz_mm": 0.0, "reason": "wrist frame not provided" if hsv is None else seen.get("why", "container not isolated in wrist view")}
    sign = sign or {"along": -1.0, "across": 1.0}
    c = math.radians(closing_deg)
    along_arm, across_arm = np.array([math.cos(c), math.sin(c)]), np.array([-math.sin(c), math.cos(c)])
    along_mm, raw_across_mm = float(seen["along_mm"]), float(seen.get("across_mm", 0.0))
    max_skew = float(prm.get(params, "grasp.max_skew_mm", 4.0))
    max_across_skew = float(prm.get(params, "grasp.max_across_skew_mm", 7.5))
    h_img = float(wrist_img.shape[0]) if hasattr(wrist_img, "shape") and len(wrist_img.shape) >= 2 else 480.0
    bite_ratio = round(max(0.0, min(1.0, float(seen.get("y_front", 0.76 * h_img)) / max(1.0, h_img))), 3)
    min_bite_ratio = float(prm.get(params, "grasp.min_bite_ratio", 0.42))
    partial_bite = bool(abs(raw_across_mm) > max_across_skew or bite_ratio < min_bite_ratio or (seen.get("clipped_border", False) and abs(along_mm) > 0.75 * max_skew))
    across_mm = raw_across_mm if (prm.get(params, "wrist.servo_across") or partial_bite) else 0.0
    gain = float(prm.get(params, "wrist.servo_gain", 0.85))
    step = gain * (sign.get("along", -1.0) * along_mm * along_arm + sign.get("across", 1.0) * across_mm * across_arm)
    max_step = float(prm.get(params, "wrist.max_step_mm", 8.0))
    if float(np.hypot(*step)) > max_step:
        step = step / float(np.hypot(*step)) * max_step
    dx_mm, dy_mm = round(float(step[0]), 2), round(float(step[1]), 2)
    dz_mm = -2.2 if bite_ratio < min_bite_ratio else 0.0
    base = {"found": True, "along_mm": along_mm, "across_mm": round(raw_across_mm, 2), "bite_ratio": bite_ratio, "dx_mm": dx_mm, "dy_mm": dy_mm, "mode": seen.get("mode", "blob")}
    if abs(along_mm) > max_skew:
        return {**base, "verdict": "reinsert", "class": "unstable_skewed", "dz_mm": dz_mm, "reason": f"wrist camera lateral offset {along_mm}mm exceeds {max_skew}mm"}
    if partial_bite:
        return {**base, "verdict": "reinsert", "class": "unstable_partial_bite", "dz_mm": dz_mm if dz_mm < 0.0 else -1.8, "reason": f"wrist camera partial edge bite (across={raw_across_mm:.1f}mm, bite_ratio={bite_ratio:.2f})"}
    return {**base, "verdict": "proceed", "class": "centered", "dz_mm": 0.0, "reason": f"wrist camera centered (along_mm={along_mm}mm)"}


def kinesthetic_judge(
    r_grasp: dict | None = None,
    r_lift: dict | None = None,
    *,
    grasp_dynamics: dict | None = None,
    params: dict | None = None,
) -> dict:
    """Agent 3: Proprioceptive load, stiffness & post-lift differential slip critic."""
    if grasp_dynamics is None and isinstance(r_grasp, dict):
        closed = float(prm.get(params, "gripper.closed", 48.8)) if isinstance(params, dict) else 48.8
        held_30 = float(prm.get(params, "gripper.held_30mm", 53.5)) if isinstance(params, dict) else 53.5
        open_pos = float(prm.get(params, "gripper.open", 57.85)) if isinstance(params, dict) else 57.85
        grasp_dynamics = evaluate_grasp_dynamics(r_grasp, r_lift=r_lift, closed=closed, open_pos=open_pos, held_30mm=held_30)
    if not isinstance(grasp_dynamics, dict):
        return {"verdict": "proceed", "class": "unmeasured", "dq_lift": 0.0, "dz_mm": 0.0, "reason": "no kinesthetic dynamics provided"}
    regime = str(grasp_dynamics.get("regime") or "stable_hold")
    dq_lift = float(grasp_dynamics.get("dq_lift") or 0.0)
    q_margin = float(grasp_dynamics.get("q_margin_units") or 4.5)
    k_contact = float(grasp_dynamics.get("k_contact_ma_per_unit") or 10.0)
    conf = float(grasp_dynamics.get("confidence") or 0.8)
    arm_load_delta = grasp_dynamics.get("arm_load_delta_ma")
    max_partial_slip = float(prm.get(params, "grasp.max_partial_slip_units", 0.90)) if isinstance(params, dict) else 0.90
    base = {"regime": regime, "dq_lift": round(dq_lift, 2), "q_margin_units": round(q_margin, 2), "k_contact_ma_per_unit": round(k_contact, 2), "arm_load_delta_ma": arm_load_delta}
    if regime in ("empty_closure", "slip_collapse") or not grasp_dynamics.get("holding", True):
        return {**base, "verdict": "reinsert", "class": "unstable_slip_collapse", "dz_mm": -3.0, "reason": f"kinesthetic slip collapse ({regime}, dq_lift={dq_lift:.2f}u, margin={q_margin:.2f}u)"}
    if dq_lift <= -max_partial_slip and q_margin < 3.6:
        return {**base, "verdict": "reinsert", "class": "unstable_partial_slip", "dz_mm": -2.5, "reason": f"post-lift partial bite slip (dq_lift={dq_lift:.2f}u <= -{max_partial_slip:.2f}u, margin={q_margin:.2f}u)"}
    if regime == "weak_contact" or (k_contact < 3.8 and q_margin < 3.3 and conf < 0.56):
        return {**base, "verdict": "reinsert", "class": "unstable_weak_bite", "dz_mm": -2.2, "reason": f"weak fingertip bite stiffness (k={k_contact:.1f}mA/u, margin={q_margin:.2f}u, conf={conf:.2f})"}
    return {**base, "verdict": "proceed", "class": "stable_load", "dz_mm": 0.0, "reason": f"kinesthetic load stable ({regime}, dq_lift={dq_lift:.2f}u, k={k_contact:.1f}mA/u)"}


def council_deliberate(
    stage: str,
    telemetry: dict,
    vision: dict,
    kinesthetic: dict,
    *,
    reinsert_count: int = 0,
    max_reinsert: int = 1,
    recovery_chunk: str = "run release_pick",
) -> tuple[list[dict], float, float, float]:
    """Run structured 3-agent deliberation (`proposal -> critique -> arbiter`) across
    Seat 1 (`telemetry_judge`), Seat 2 (`vision_judge`), and Seat 3 (`kinesthetic_judge`)."""
    t_verdict, v_verdict, k_verdict = (str(d.get("verdict") or "proceed") for d in (telemetry, vision, kinesthetic))
    v_dx, v_dy, err_u = float(vision.get("dx_mm") or 0.0), float(vision.get("dy_mm") or 0.0), float(telemetry.get("error_units") or 0.0)
    if (t_verdict == "reinsert" or k_verdict == "reinsert") and abs(v_dx) < 0.2 and abs(v_dy) < 0.2:
        v_dx = 2.0 if err_u <= 0 else -2.0
    neg_dz = [float(d.get("dz_mm") or 0.0) for d in (telemetry, vision, kinesthetic) if float(d.get("dz_mm") or 0.0) < 0.0]
    prop_dz = round(min(neg_dz), 2) if neg_dz else 0.0
    prop_unstable = t_verdict == "reinsert" or v_verdict == "reinsert"
    prop_verdict = ("reinsert_and_retry" if reinsert_count < max_reinsert else "reinsert_and_park") if prop_unstable else "proceed"
    prop_entry = {
        "role": "proposal",
        "seat": "telemetry_and_vision",
        "verdict": prop_verdict,
        "dx_mm": round(v_dx, 2),
        "dy_mm": round(v_dy, 2),
        "dz_mm": prop_dz,
        "reason": f"Seat1({telemetry.get('class')}): {telemetry.get('reason')}; Seat2({vision.get('class')}): {vision.get('reason')}",
    }
    crit_dx, crit_dy, crit_dz = v_dx, v_dy, prop_dz
    any_unstable = prop_unstable or (k_verdict == "reinsert")
    crit_verdict = ("reinsert_and_retry" if reinsert_count < max_reinsert else "reinsert_and_park") if any_unstable else "proceed"
    if not prop_unstable and k_verdict == "reinsert":
        if abs(crit_dx) < 0.2 and abs(crit_dy) < 0.2:
            crit_dx = 2.0 if err_u <= 0 else -2.0
        crit_reason = f"Override static proceed -> {crit_verdict}: {kinesthetic.get('reason')} (put back via {recovery_chunk} and lower z by {crit_dz}mm)"
    elif t_verdict == "proceed" and v_verdict == "reinsert":
        crit_reason = f"Confirm partial edge bite override ({vision.get('reason')}); shift [{crit_dx:.2f}, {crit_dy:.2f}, {crit_dz:.2f}]mm"
    elif t_verdict == "reinsert" and v_verdict == "proceed":
        crit_reason = f"Confirm contact span anomaly ({telemetry.get('class')}): shift [{crit_dx:.2f}, {crit_dy:.2f}, {crit_dz:.2f}]mm via {recovery_chunk}"
    else:
        crit_reason = f"Kinesthetic critic ({kinesthetic.get('class')}): {kinesthetic.get('reason')}"
    crit_entry = {"role": "critique", "seat": "kinesthetic_critic", "verdict": crit_verdict, "dx_mm": round(crit_dx, 2), "dy_mm": round(crit_dy, 2), "dz_mm": round(crit_dz, 2), "reason": crit_reason}
    arb_dx, arb_dy, arb_dz = round(float(np.clip(crit_dx, -8.0, 8.0)), 2), round(float(np.clip(crit_dy, -8.0, 8.0)), 2), round(float(np.clip(crit_dz, -4.5, 2.0)), 2)
    arb_entry = {
        "role": "arbiter",
        "seat": "consensus_arbiter",
        "verdict": crit_verdict,
        "dx_mm": arb_dx,
        "dy_mm": arb_dy,
        "dz_mm": arb_dz,
        "recovery_chunk": None if crit_verdict == "proceed" else recovery_chunk,
        "reason": f"Council consensus={crit_verdict}: shift=[{arb_dx}, {arb_dy}, {arb_dz}]mm ({telemetry.get('class')}/{vision.get('class')}/{kinesthetic.get('class')})",
    }
    return [prop_entry, crit_entry, arb_entry], arb_dx, arb_dy, arb_dz


def _normalize_models(models) -> list:
    if not models:
        return []
    if callable(models):
        return [models]
    if isinstance(models, dict):
        if "models" in models or "profiles" in models:
            items = [judge_seat.from_config(m) for m in (models.get("models") or models.get("profiles") or ())]
            if models.get("arbiter"):
                items.append(judge_seat.from_config(models["arbiter"]))
            return [m for m in items if callable(m)]
        fn = judge_seat.from_config(models)
        return [fn] if callable(fn) else []
    return [fn for item in models if callable(fn := (item if callable(item) else judge_seat.from_config(item)))]
