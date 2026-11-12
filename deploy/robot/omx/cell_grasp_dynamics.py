#!/usr/bin/env python3
"""Calculus & Trend-Based Grasp/Slip Dynamics Analyzer (`cell_grasp_dynamics.py`).

Single Responsibility:
  - Evaluates grasp equilibrium, elastic pad settling, and slip collapse (`evaluate_grasp_dynamics`,
    `infer_holding`) using contact stiffness derivatives (`-dI/dq`), current impulse integrals,
    and state-transition jaw derivatives across `grasp_pick` -> `lift_pick` -> `above_place`
    for 5/6/7-DOF arms (`state[-1]` or `state[5]`).
"""
from __future__ import annotations

from typing import Any


def _extract_jaw_and_current(status: dict[str, Any] | None) -> tuple[float | None, float | None, float]:
    if not isinstance(status, dict):
        return None, None, 0.0
    state = status.get("state")
    jaw = None
    if isinstance(state, list) and len(state) >= 6:
        raw_jaw = state[-1] if len(state) in (6, 7, 8) else state[5]
        if raw_jaw is not None:
            jaw = float(raw_jaw)
    curr_raw = status.get("gripper_current_ma")
    if curr_raw is None and isinstance(status.get("health"), dict):
        h_curr = status["health"].get("current_ma")
        if isinstance(h_curr, list) and len(h_curr) >= 6:
            raw_c = h_curr[-1] if len(h_curr) in (6, 7, 8) else h_curr[5]
            if raw_c is not None:
                curr_raw = raw_c
        else:
            g_h = (status["health"].get("joints") or {}).get("gripper") or {}
            curr_raw = g_h.get("current_ma")
    curr = abs(float(curr_raw)) if curr_raw is not None else None
    dt = max(0.05, float(status.get("dt_s") or 0.65))
    return jaw, curr, dt


def _extract_arm_load_ma(status: dict[str, Any] | None) -> float | None:
    if not isinstance(status, dict) or not isinstance(status.get("health"), dict):
        return None
    h_curr = status["health"].get("current_ma")
    if isinstance(h_curr, list) and len(h_curr) >= 4:
        return round(sum(abs(float(h_curr[i])) for i in (1, 2, 3) if h_curr[i] is not None), 1)
    joints = status["health"].get("joints") or {}
    vals = []
    for j_name in ("shoulder_lift", "elbow_flex", "wrist_flex"):
        j = joints.get(j_name)
        if isinstance(j, dict) and j.get("current_ma") is not None:
            vals.append(abs(float(j["current_ma"])))
    return round(sum(vals), 1) if vals else None


def evaluate_grasp_dynamics(
    r_grasp: dict[str, Any],
    r_lift: dict[str, Any] | None = None,
    r_above_place: dict[str, Any] | None = None,
    *,
    closed: float = 48.8,
    open_pos: float = 57.85,
    held_30mm: float = 53.5,
    baseline_current_ma: float = 80.0,
    free_current_ma: float = 18.0,
) -> dict[str, Any]:
    """Calculus & trend-based grasp/slip analyzer using position-current derivatives and impulse integration."""
    q_g, i_g, dt_g = _extract_jaw_and_current(r_grasp)
    q_l, i_l, dt_l = _extract_jaw_and_current(r_lift)
    q_a, i_a, dt_a = _extract_jaw_and_current(r_above_place)

    if q_g is None:
        return {"holding": False, "regime": "no_telemetry", "confidence": 0.0, "reason": "missing gripper state"}

    span_full = max(1.0, float(open_pos) - float(closed))
    q_margin_g = q_g - float(closed)
    closing_stroke = max(0.35, float(open_pos) - q_g)
    arrest_ratio = q_margin_g / span_full

    eff_i_g = i_g if i_g is not None else float(baseline_current_ma)
    net_i_g = max(0.0, eff_i_g - float(free_current_ma))
    k_contact = net_i_g / closing_stroke
    rel_i_ratio = eff_i_g / max(30.0, float(baseline_current_ma))

    impulse_mas = net_i_g * dt_g
    if i_l is not None:
        impulse_mas += 0.5 * (net_i_g + max(0.0, i_l - float(free_current_ma))) * dt_l
    if i_a is not None:
        prev_i = max(0.0, (i_l if i_l is not None else eff_i_g) - float(free_current_ma))
        impulse_mas += 0.5 * (prev_i + max(0.0, i_a - float(free_current_ma))) * dt_a

    q_now = q_a if q_a is not None else (q_l if q_l is not None else q_g)
    i_now = i_a if i_a is not None else (i_l if i_l is not None else eff_i_g)
    q_margin_now = q_now - float(closed)

    dq_lift = (q_l - q_g) if q_l is not None else 0.0
    dq_dt_lift = dq_lift / dt_l if q_l is not None else 0.0
    di_lift = (i_l - eff_i_g) if (q_l is not None and i_l is not None) else 0.0
    dq_transit = (q_a - q_l) if (q_a is not None and q_l is not None) else 0.0
    d2q_settle = dq_transit - dq_lift if (q_a is not None and q_l is not None) else 0.0

    load_g = _extract_arm_load_ma(r_grasp)
    load_now = _extract_arm_load_ma(r_above_place or r_lift)
    arm_load_delta_ma = round(load_now - load_g, 1) if (load_g is not None and load_now is not None) else None

    if q_margin_now < 1.85 or (q_l is None and q_margin_g < 2.2):
        return {
            "holding": False,
            "regime": "empty_closure" if q_l is None else "slip_collapse",
            "confidence": 0.95,
            "q_margin_units": round(q_margin_now, 2),
            "arrest_ratio": round(arrest_ratio, 3),
            "k_contact_ma_per_unit": round(k_contact, 2),
            "impulse_mas": round(impulse_mas, 1),
            "dq_lift": round(dq_lift, 2),
            "dq_transit": round(dq_transit, 2),
            "reason": f"jaw collapsed to {q_now:.2f} (margin={q_margin_now:.2f}u <= deadband)",
        }

    if q_l is not None:
        if (dq_lift < -2.1 and q_margin_now < 2.4) or (dq_lift < -1.2 and dq_transit < -1.0 and q_margin_now < 2.8):
            return {
                "holding": False,
                "regime": "slip_collapse",
                "confidence": 0.92,
                "q_margin_units": round(q_margin_now, 2),
                "arrest_ratio": round(arrest_ratio, 3),
                "k_contact_ma_per_unit": round(k_contact, 2),
                "impulse_mas": round(impulse_mas, 1),
                "dq_lift": round(dq_lift, 2),
                "dq_dt_lift": round(dq_dt_lift, 2),
                "dq_transit": round(dq_transit, 2),
                "d2q_settle": round(d2q_settle, 2),
                "di_lift_ma": round(di_lift, 1),
                "arm_load_delta_ma": arm_load_delta_ma,
                "reason": f"differential slip: dq_lift={dq_lift:.2f}u, dq_transit={dq_transit:.2f}u, q_now={q_now:.2f}",
            }

    geom_prox = max(0.0, 1.0 - abs(q_now - float(held_30mm)) / 4.5)
    stiffness_score = min(1.0, k_contact / 12.0)
    current_score = min(1.0, max(rel_i_ratio, i_now / 55.0))
    arrest_score = min(1.0, max(0.0, (q_margin_now - 1.8) / 3.2))
    composite_score = round(0.45 * arrest_score + 0.30 * max(stiffness_score, geom_prox) + 0.25 * current_score, 3)

    if q_l is None and q_a is None:
        if r_grasp.get("holding") is False and i_now < float(baseline_current_ma):
            holding = bool(q_margin_g >= 4.4 and abs(q_g - float(held_30mm)) <= 1.2 and i_now >= 35.0)
        else:
            holding = bool(q_margin_g >= 3.2 and (i_now >= float(baseline_current_ma) or r_grasp.get("holding") is True))
    else:
        min_adaptive_curr = 26.0 if q_margin_now >= 2.8 else 48.0
        holding = bool(composite_score >= 0.48 and i_now >= min_adaptive_curr)

    regime = (
        "elastic_settle"
        if (holding and q_l is not None and dq_lift < -0.45)
        else ("stable_hold" if holding else "weak_contact")
    )
    return {
        "holding": holding,
        "regime": regime,
        "confidence": composite_score,
        "q_margin_units": round(q_margin_now, 2),
        "arrest_ratio": round(arrest_ratio, 3),
        "k_contact_ma_per_unit": round(k_contact, 2),
        "impulse_mas": round(impulse_mas, 1),
        "dq_lift": round(dq_lift, 2),
        "dq_dt_lift": round(dq_dt_lift, 2),
        "dq_transit": round(dq_transit, 2),
        "d2q_settle": round(d2q_settle, 2),
        "di_lift_ma": round(di_lift, 1),
        "arm_load_delta_ma": arm_load_delta_ma,
        "reason": f"{regime}: q={q_now:.2f} (margin={q_margin_now:.2f}u), k={k_contact:.1f}mA/u, J={impulse_mas:.1f}mAs, dq_lift={dq_lift:.2f}u",
    }


def infer_holding(
    status: dict[str, Any],
    closed: float = 48.8,
    min_units_above_closed: float = 3.8,
    min_current_ma: float = 65.0,
    *,
    prev_grasp: dict[str, Any] | None = None,
    prev_lift: dict[str, Any] | None = None,
    open_pos: float = 57.85,
) -> bool:
    """True when the follower jaws physically stopped on an object and maintain grasp equilibrium."""
    if isinstance(status, dict) and status.get("gripper_closed") is not None and closed == 48.8:
        closed = float(status["gripper_closed"])
    if prev_grasp is not None or prev_lift is not None:
        dyn = evaluate_grasp_dynamics(
            prev_grasp or status,
            r_lift=status if prev_lift is None else prev_lift,
            r_above_place=status if prev_lift is not None else None,
            closed=closed,
            open_pos=open_pos,
        )
        return bool(dyn["holding"])
    state = status.get("state")
    raw_jaw = (state[-1] if len(state) in (6, 7, 8) else state[5]) if isinstance(state, list) and len(state) >= 6 else None
    if status.get("holding") is True:
        if raw_jaw is not None:
            return float(raw_jaw) >= float(closed) + 2.0
        return True
    if raw_jaw is None:
        return False
    jaw = float(raw_jaw)
    if jaw < float(closed) + float(min_units_above_closed):
        if jaw >= float(closed) + 2.5:
            dyn = evaluate_grasp_dynamics(status, closed=closed, open_pos=open_pos, baseline_current_ma=min_current_ma)
            return bool(dyn["holding"])
        return False
    curr = status.get("gripper_current_ma")
    if curr is not None and abs(float(curr)) < float(min_current_ma):
        dyn = evaluate_grasp_dynamics(status, closed=closed, open_pos=open_pos, baseline_current_ma=min_current_ma)
        return bool(dyn["holding"])
    return True
