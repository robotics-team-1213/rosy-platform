#!/usr/bin/env python3
"""Individual Grasp Judge Evaluators (`cell_grasp_judges.py`).

Single Responsibility:
  - Agent 1 (`telemetry_judge`): Evaluates jaw position (`state[-1]` for 5/6/7-DOF or `state[5]`)
    and squeeze current (`current_ma`) against calibrated `gripper.held_30mm`, catching shallow
    corner pinches, diagonal rim wedges, and low-current slipping grasps.
  - Agent 2 (`vision_judge`): Evaluates wrist camera container centering (`along_mm`, `across_mm`)
    and computes bounded corrective shifts `(dx_mm, dy_mm)` along the closing axis.
  - Consensus Evidence Weighting (`compute_consensus_evidence_weight`) and model backend normalizers
    (`load_zai_key`, `glm_backend`, `_normalize_models`).
"""
from __future__ import annotations

import math

import numpy as np

import cell_fingers
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
    `shape_score` and k-NN Imitation Learning confidence (`il_confidence`). Defaults to `1.0` when
    neither signal is provided so existing rule/telemetry baselines remain exact."""
    v_shape = shape_score if shape_score is not None else (vision or {}).get("shape_score")
    if v_shape is None and il_confidence is None:
        return 1.0
    s_val = max(0.0, min(1.0, float(v_shape if v_shape is not None else 0.85)))
    il_val = max(0.0, min(1.0, float(il_confidence if il_confidence is not None else 0.75)))
    raw_w = 0.45 + 0.45 * s_val + 0.25 * il_val
    return round(max(0.40, min(1.15, raw_w)), 3)


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
        return {
            "verdict": "empty",
            "class": "empty",
            "jaw_units": jaw,
            "error_units": None,
            "current_ma": current_ma,
            "reason": "runner reported holding=False",
        }
    if jaw is None:
        return {
            "verdict": "proceed",
            "class": "unmeasured",
            "jaw_units": None,
            "error_units": 0.0,
            "current_ma": current_ma,
            "reason": "no jaw state vector",
        }
    if not isinstance(params, dict) or "gripper.held_30mm" not in params:
        return {
            "verdict": "proceed",
            "class": "uncalibrated_jaw_band",
            "jaw_units": jaw,
            "error_units": 0.0,
            "current_ma": current_ma,
            "reason": "gripper.held_30mm not in params",
        }
    held_30 = float(prm.get(params, "gripper.held_30mm"))
    closed = float(prm.get(params, "gripper.closed", 48.8))
    open_pos = float(prm.get(params, "gripper.open", 57.85))
    shallow_tol = float(prm.get(params, "grasp.shallow_tol_units", 1.2))
    wedged_tol = float(prm.get(params, "grasp.wedged_tol_units", 0.7))
    min_current = float(prm.get(params, "grasp.min_stable_current_ma", 0.0))
    err = round(jaw - held_30, 2)
    closing_stroke = max(0.35, open_pos - jaw)
    k_contact = round(max(0.0, (abs(float(current_ma)) if current_ma is not None else 80.0) - 18.0) / closing_stroke, 2)
    if err < -shallow_tol:
        return {
            "verdict": "reinsert",
            "class": "unstable_shallow",
            "jaw_units": jaw,
            "held_30mm_units": held_30,
            "error_units": err,
            "current_ma": current_ma,
            "k_contact_ma_per_unit": k_contact,
            "reason": f"jaws closed {abs(err):.2f} units past nominal 30mm ({jaw} < {held_30 - shallow_tol:.2f}): shallow corner pinch",
        }
    if err > wedged_tol:
        return {
            "verdict": "reinsert",
            "class": "unstable_wedged",
            "jaw_units": jaw,
            "held_30mm_units": held_30,
            "error_units": err,
            "current_ma": current_ma,
            "k_contact_ma_per_unit": k_contact,
            "reason": f"jaws stopped {err:.2f} units wider than nominal 30mm ({jaw} > {held_30 + wedged_tol:.2f}): diagonal/rim wedge",
        }
    if min_current > 0 and current_ma is not None and abs(float(current_ma)) < min_current:
        if (
            prm.get(params, "grasp.stiffness_override", 0)
            and abs(err) <= 0.85
            and (jaw - closed) >= 3.2
            and k_contact >= 4.0
            and abs(float(current_ma)) >= 32.0
        ):
            return {
                "verdict": "proceed",
                "class": "stable_stiffness_arrest",
                "jaw_units": jaw,
                "held_30mm_units": held_30,
                "error_units": err,
                "current_ma": current_ma,
                "k_contact_ma_per_unit": k_contact,
                "reason": f"jaw arrested at {jaw}u (|err|={abs(err):.2f}u, k={k_contact}mA/u) compensating low current {abs(float(current_ma)):.0f}mA",
            }
        return {
            "verdict": "reinsert",
            "class": "unstable_slipping",
            "jaw_units": jaw,
            "held_30mm_units": held_30,
            "error_units": err,
            "current_ma": current_ma,
            "k_contact_ma_per_unit": k_contact,
            "reason": f"gripper squeeze current {abs(float(current_ma)):.0f} mA below stable threshold {float(min_current):.0f} mA: slipping grasp",
        }
    return {
        "verdict": "proceed",
        "class": "stable",
        "jaw_units": jaw,
        "held_30mm_units": held_30,
        "error_units": err,
        "current_ma": current_ma,
        "k_contact_ma_per_unit": k_contact,
        "reason": "jaw span within nominal 30mm stability band",
    }


def vision_judge(
    wrist_img,
    hsv,
    gap_mm: float,
    closing_deg: float,
    sign: dict | None = None,
    params=None,
    color: str | int | None = None,
) -> dict:
    """Agent 2: measure container centering between the fingers in the wrist camera view."""
    if wrist_img is None or hsv is None:
        return {
            "verdict": "proceed",
            "class": "no_frame",
            "found": False,
            "dx_mm": 0.0,
            "dy_mm": 0.0,
            "reason": "wrist frame not provided",
        }
    seen = cell_fingers.finger_offset_mm(wrist_img, hsv, gap_mm, params, color=color)
    if not seen.get("found"):
        return {
            "verdict": "proceed",
            "class": "unseen",
            "found": False,
            "dx_mm": 0.0,
            "dy_mm": 0.0,
            "reason": seen.get("why", "container not isolated in wrist view"),
        }
    sign = sign or {"along": -1.0, "across": 1.0}
    c = math.radians(closing_deg)
    along_arm = np.array([math.cos(c), math.sin(c)])
    across_arm = np.array([-math.sin(c), math.cos(c)])
    along_mm = float(seen["along_mm"])
    across_mm = float(seen.get("across_mm", 0.0)) if prm.get(params, "wrist.servo_across") else 0.0
    gain = float(prm.get(params, "wrist.servo_gain", 0.85))
    step = gain * (sign.get("along", -1.0) * along_mm * along_arm + sign.get("across", 1.0) * across_mm * across_arm)
    max_step = float(prm.get(params, "wrist.max_step_mm", 8.0))
    if float(np.hypot(*step)) > max_step:
        step = step / float(np.hypot(*step)) * max_step
    dx_mm, dy_mm = round(float(step[0]), 2), round(float(step[1]), 2)
    max_skew = float(prm.get(params, "grasp.max_skew_mm", 4.0))
    if abs(along_mm) > max_skew:
        return {
            "verdict": "reinsert",
            "class": "unstable_skewed",
            "found": True,
            "along_mm": along_mm,
            "across_mm": across_mm,
            "dx_mm": dx_mm,
            "dy_mm": dy_mm,
            "mode": seen.get("mode", "blob"),
            "reason": f"wrist camera lateral offset {along_mm}mm exceeds {max_skew}mm",
        }
    return {
        "verdict": "proceed",
        "class": "centered",
        "found": True,
        "along_mm": along_mm,
        "across_mm": across_mm,
        "dx_mm": dx_mm,
        "dy_mm": dy_mm,
        "mode": seen.get("mode", "blob"),
        "reason": f"wrist camera centered (along_mm={along_mm}mm)",
    }


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
    out = []
    for item in models:
        fn = item if callable(item) else judge_seat.from_config(item)
        if callable(fn):
            out.append(fn)
    return out
