#!/usr/bin/env python3
"""Multi-agent consistency debate and post-grasp stability / put-back (reinsert) judge.

Built on top of ROSY's `judge_seat` (`schema_version = 2`), `cell_decisions`, `cell_knowledge`, and `cell_diagnose`
architecture so that any single model or multi-model deliberation panel (`ollama` local VLM, `zai`/`glm-5.3`/
`glm-5.3-flash`, `openai`/`vllm` HTTP, `opencode`/`claude` CLI, or custom callables) can participate.

Combines three seats at `above_pick`, `run grasp_pick`, and `run lift_pick`:
  1. Telemetry / Kinematic Judge (`telemetry_judge`): checks jaw position `state[5]` against `gripper.held_30mm`
     to catch shallow corner pinches (`state[5] < held_30mm - shallow_tol_units`, which slipped during fold in
     Trials 4-5) and diagonal rim wedges (`state[5] > held_30mm + wedged_tol_units`).
  2. Wrist-Vision Judge (`vision_judge`): measures the container's lateral (`along_mm`) and depth (`across_mm`)
     offset between the v2.1 white fingers (`cell_fingers.finger_offset_mm`) and computes the corrective shift
     `(dx_mm, dy_mm)` along the closing axis.
  3. Model-Agnostic Deliberation (`judge_seat.from_config` / `judge_seat.cooperate`): runs a Proposal -> Critique ->
     Arbiter consistency deliberation across configured models (defaulting GLM to `glm-5.3` / `glm-5.3-flash`) while
     keeping measured safety bounds sovereign (`judge_seat.measured`).

When a grasp is judged unstable (`unstable_shallow`, `unstable_wedged`, or `unstable_skewed`), the container is
never dropped in mid-air or carried crooked to `place`:
  - At `run grasp_pick` (still seated at `pick.z`): runs `run release_pick` (opens gently to `grip_release` +1 mm
    per side, settles, and lifts clear).
  - At `run lift_pick` (already lifted above the slot): runs `run reinsert_pick` (slowly lowers vertically back to
    `pick.z`, opens gently to `grip_release`, and lifts clear), then either shifts `target["pick"]` by the debated
    `(dx_mm, dy_mm)` and re-grasps (`reinsert_and_retry`), or parks (`reinsert_and_park`).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

import cell_decisions as cd
import cell_fingers
import cell_params as prm
import judge_seat

SCHEMA_VERSION = judge_seat.SCHEMA_VERSION
ACTIONS = ("proceed", "reinsert_and_retry", "reinsert_and_park")


def load_zai_key() -> str | None:
    return judge_seat._resolve_api_key(provider="zai")


def glm_backend(model: str = "glm-5.3", url: str = "https://api.z.ai/api/coding/paas/v4/chat/completions",
                api_key: str | None = None, timeout: float = 15.0):
    """Decision model callable `(prompt, images_b64, schema) -> dict` backed by latest GLM (`glm-5.3` / `glm-5.3-flash`)."""
    return judge_seat.openai_chat(url=url, model=model, api_key=api_key, provider="zai", timeout=timeout)


def telemetry_judge(state: list | None, holding: bool | None, params=None) -> dict:
    """Agent 1: evaluate jaw position `state[5]` against nominal 30 mm container width (`gripper.held_30mm`)."""
    if holding is False:
        jaw = round(float(state[5]), 2) if isinstance(state, list) and len(state) >= 6 and state[5] is not None else None
        return {"verdict": "empty", "class": "empty", "jaw_units": jaw, "error_units": None,
                "reason": "runner reported holding=False"}
    if not isinstance(state, list) or len(state) < 6 or not isinstance(state[5], (int, float)):
        return {"verdict": "proceed", "class": "unmeasured", "jaw_units": None, "error_units": 0.0,
                "reason": "no jaw state vector"}
    # Only enforce tight 30 mm jaw band when gripper.held_30mm is explicitly calibrated in params
    if not isinstance(params, dict) or "gripper.held_30mm" not in params:
        return {"verdict": "proceed", "class": "uncalibrated_jaw_band", "jaw_units": round(float(state[5]), 2),
                "error_units": 0.0, "reason": "gripper.held_30mm not in params"}
    held_30 = float(prm.get(params, "gripper.held_30mm"))
    shallow_tol = float(prm.get(params, "grasp.shallow_tol_units", 1.2))
    wedged_tol = float(prm.get(params, "grasp.wedged_tol_units", 0.7))
    jaw = round(float(state[5]), 2)
    err = round(jaw - held_30, 2)
    if err < -shallow_tol:
        return {
            "verdict": "reinsert",
            "class": "unstable_shallow",
            "jaw_units": jaw,
            "held_30mm_units": held_30,
            "error_units": err,
            "reason": f"jaws closed {abs(err):.2f} units past nominal 30mm ({jaw} < {held_30 - shallow_tol:.2f}): shallow corner pinch",
        }
    if err > wedged_tol:
        return {
            "verdict": "reinsert",
            "class": "unstable_wedged",
            "jaw_units": jaw,
            "held_30mm_units": held_30,
            "error_units": err,
            "reason": f"jaws stopped {err:.2f} units wider than nominal 30mm ({jaw} > {held_30 + wedged_tol:.2f}): diagonal/rim wedge",
        }
    return {
        "verdict": "proceed",
        "class": "stable",
        "jaw_units": jaw,
        "held_30mm_units": held_30,
        "error_units": err,
        "reason": "jaw span within nominal 30mm stability band",
    }


def vision_judge(wrist_img, hsv, gap_mm: float, closing_deg: float, sign: dict | None = None, params=None) -> dict:
    """Agent 2: measure container centering between the fingers in the wrist camera view."""
    if wrist_img is None or hsv is None:
        return {"verdict": "proceed", "class": "no_frame", "found": False, "dx_mm": 0.0, "dy_mm": 0.0,
                "reason": "wrist frame not provided"}
    seen = cell_fingers.finger_offset_mm(wrist_img, hsv, gap_mm, params)
    if not seen.get("found"):
        return {"verdict": "proceed", "class": "unseen", "found": False, "dx_mm": 0.0, "dy_mm": 0.0,
                "reason": seen.get("why", "container not isolated in wrist view")}
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


def debate_and_decide(stage: str, telemetry: dict, vision: dict, reinsert_count: int = 0,
                      max_reinsert: int = 1, models: list | tuple | dict = ()) -> dict:
    """Cross-check Telemetry (Agent 1) + Wrist Vision (Agent 2) + Model Deliberation (Agent 3..N).

    Uses `judge_seat.measured` for precondition sovereignty (`next='transport'`, `holding=True`, `stable=not unstable`)
    and runs `proposal -> critique -> arbiter` deliberation across any configured model backends.
    """
    if telemetry.get("verdict") == "empty":
        return {
            "schema_version": SCHEMA_VERSION,
            "verdict": "empty",
            "by": "measurement",
            "recovery_chunk": None,
            "dx_mm": 0.0,
            "dy_mm": 0.0,
            "telemetry": telemetry,
            "vision": vision,
            "debate": [],
            "reason": telemetry.get("reason", "empty grasp"),
        }

    recovery_chunk = "run release_pick" if stage == "run grasp_pick" else "run reinsert_pick"
    dx_mm = float(vision.get("dx_mm", 0.0))
    dy_mm = float(vision.get("dy_mm", 0.0))
    # When telemetry sees a shallow/wedged grasp but wrist vision had no frame, nudge 2.0 mm toward container center
    if telemetry.get("verdict") == "reinsert" and abs(dx_mm) < 0.2 and abs(dy_mm) < 0.2:
        dx_mm = 2.0 if (telemetry.get("error_units") or 0.0) < 0 else -2.0

    unstable = telemetry.get("verdict") == "reinsert" or vision.get("verdict") == "reinsert"
    seat_facts = {
        "box_found": True,
        "next": "lift" if stage == "run grasp_pick" else "transport",
        "holding": True,
        "stable": not unstable,
        "reinsert": unstable,
        "stage": stage,
        "reinsert_count": reinsert_count,
    }
    _, seat_forbidden = judge_seat.measured(seat_facts)

    if not unstable:
        rule_verdict = "proceed"
        rule_reason = f"{telemetry.get('reason')}; {vision.get('reason')}"
    elif reinsert_count < max_reinsert:
        rule_verdict = "reinsert_and_retry"
        rule_reason = (f"unstable grasp at {stage} ({telemetry.get('class')}/{vision.get('class')}): "
                       f"put back via {recovery_chunk} and re-pick shifted by [{dx_mm}, {dy_mm}] mm")
    else:
        rule_verdict = "reinsert_and_park"
        rule_reason = (f"unstable grasp at {stage} after {reinsert_count} re-inserts: "
                       f"put back via {recovery_chunk} and park")

    debate_log = []
    final_verdict = rule_verdict
    final_reason = rule_reason
    by = "measurement"
    allowed = [a for a in ACTIONS if not (a == "proceed" and "proceed" in seat_forbidden)]
    if reinsert_count >= max_reinsert and "reinsert_and_retry" in allowed:
        allowed.remove("reinsert_and_retry")
    if not allowed:
        allowed = [rule_verdict]

    schema = {
        "type": "object",
        "required": ["verdict", "dx_mm", "dy_mm", "reason"],
        "properties": {
            "verdict": {"type": "string", "enum": allowed},
            "dx_mm": {"type": "number"},
            "dy_mm": {"type": "number"},
            "reason": {"type": "string"},
        },
    }

    live_models = _normalize_models(models)
    for idx, model_fn in enumerate(live_models):
        role = "proposal" if idx == 0 else ("critique" if idx == 1 and len(live_models) > 2 else f"arbiter_{idx}")
        prompt = (
            f"[Deliberation v{SCHEMA_VERSION}] Role: {role}. Stage: {stage}. Reinsert count: {reinsert_count}/{max_reinsert}.\n"
            f"Seat measured facts: {json.dumps(seat_facts)} (forbidden decisions: {sorted(seat_forbidden)})\n"
            f"Agent 1 (Telemetry): {json.dumps(telemetry)}\n"
            f"Agent 2 (Wrist Vision): {json.dumps(vision)}\n"
            f"Rule baseline: {{'verdict': {rule_verdict!r}, 'dx_mm': {dx_mm}, 'dy_mm': {dy_mm}, 'reason': {rule_reason!r}}}\n"
            f"Prior deliberation rounds: {json.dumps(debate_log)}\n"
            f"Allowed verdicts: {allowed}. Note: if Agent 1 or Agent 2 flagged 'reinsert', 'proceed' is forbidden by safety invariant. "
            "Reply with JSON only: {\"verdict\": ..., \"dx_mm\": ..., \"dy_mm\": ..., \"reason\": ...}."
        )
        try:
            ans = model_fn(prompt, (), schema)
            m_verdict = ans.get("verdict") or ans.get("decision")
            if m_verdict == "reinsert":
                m_verdict = "reinsert_and_retry" if reinsert_count < max_reinsert else "reinsert_and_park"
            elif m_verdict in ("park", "abort"):
                m_verdict = "reinsert_and_park"
            # Measured safety invariant: a model cannot override a measured unstable grasp into 'proceed'
            if (unstable or "proceed" in seat_forbidden) and m_verdict == "proceed":
                m_verdict = rule_verdict
            if m_verdict not in allowed:
                m_verdict = rule_verdict
            m_dx = float(np.clip(float(ans.get("dx_mm", dx_mm)), -8.0, 8.0))
            m_dy = float(np.clip(float(ans.get("dy_mm", dy_mm)), -8.0, 8.0))
            entry = {
                "role": role,
                "model": getattr(model_fn, "__name__", "model"),
                "verdict": m_verdict,
                "dx_mm": round(m_dx, 2),
                "dy_mm": round(m_dy, 2),
                "reason": str(ans.get("reason", ""))[:240],
            }
            if "deliberation" in ans:
                entry["sub_deliberation"] = ans["deliberation"]
            debate_log.append(entry)
            final_verdict = m_verdict
            dx_mm, dy_mm = entry["dx_mm"], entry["dy_mm"]
            final_reason = entry["reason"] or rule_reason
            by = "model"
        except Exception as exc:
            debate_log.append({
                "role": role,
                "model": getattr(model_fn, "__name__", "model"),
                "error": str(exc)[:120],
            })

    return {
        "schema_version": SCHEMA_VERSION,
        "verdict": final_verdict,
        "by": by,
        "options": allowed,
        "recovery_chunk": None if final_verdict == "proceed" else recovery_chunk,
        "dx_mm": round(dx_mm, 2),
        "dy_mm": round(dy_mm, 2),
        "telemetry": telemetry,
        "vision": vision,
        "debate": debate_log,
        "reason": final_reason,
    }


def hook(config: dict, cell, target: dict, write_library, gap_mm: float):
    """Post-grasp / post-lift stability and put-back (`release_pick` / `reinsert_pick`) hook for `transfer_folded`."""
    params, spec = config.get("params"), config.get("wrist") or {}
    if not isinstance(params, dict) or not prm.get(params, "grasp.stability_check", 1):
        return None
    # Active when gripper.held_30mm is calibrated in params or decision_model/debate_models is configured
    if "gripper.held_30mm" not in params and not config.get("decision_model") and not config.get("debate_models"):
        return None

    work = Path(config["work_dir"]).expanduser()
    camera = spec.get("camera", "wrist")
    hsv = (spec["hsv_min"], spec["hsv_max"]) if spec.get("hsv_min") and spec.get("hsv_max") else None
    closing = target["pick"]["yaw_deg"] + prm.get(params, "auto.closing_theory_deg")
    signs_path = work / f"wrist-signs-{config.get('arm_id', 'arm_s')}.json"
    default_signs = dict({"along": -1.0, "across": 1.0}, **(spec.get("finger_sign") or {}))
    max_reinsert = int(prm.get(params, "grasp.max_reinsert", 1))
    models = _normalize_models(config.get("debate_models") or config.get("decision_model"))

    state_tracker = {"reinsert_count": 0}

    def check(stage: str, status: dict, run_cmd) -> dict:
        signs = json.loads(signs_path.read_text()) if signs_path.exists() else default_signs
        t_res = telemetry_judge(status.get("state"), status.get("holding"), params)
        wrist_img = None
        if hsv is not None and stage == "run grasp_pick" and prm.get(params, "grasp.vision_after_grasp", 0):
            try:
                wrist_img = cell.frame(camera)
            except Exception:
                wrist_img = None
        v_res = vision_judge(wrist_img, hsv, gap_mm, closing, signs, params)
        decision = debate_and_decide(
            stage=stage,
            telemetry=t_res,
            vision=v_res,
            reinsert_count=state_tracker["reinsert_count"],
            max_reinsert=max_reinsert,
            models=models,
        )
        cd.emit(
            "grasp_stability",
            {
                "stage": stage,
                "telemetry": t_res,
                "vision": v_res,
                "reinsert_count": state_tracker["reinsert_count"],
                "dx_mm": decision["dx_mm"],
                "dy_mm": decision["dy_mm"],
                "debate": decision["debate"],
            },
            decision.get("options", list(ACTIONS)),
            decision["verdict"],
            decision.get("by", "measurement"),
            decision["reason"],
        )
        if decision["verdict"] == "proceed" or decision["verdict"] == "empty":
            return decision

        # Execute physical put-back (`run release_pick` at grasp_pick, or `run reinsert_pick` at lift_pick)
        rec_cmd = decision["recovery_chunk"]
        rec_status = run_cmd(rec_cmd)
        decision["put_back_ok"] = bool(rec_status.get("ok")) and not rec_status.get("contact")
        if not decision["put_back_ok"]:
            decision["verdict"] = "reinsert_and_park"
            return decision

        if decision["verdict"] == "reinsert_and_retry":
            state_tracker["reinsert_count"] += 1
            dx_mm, dy_mm = decision["dx_mm"], decision["dy_mm"]
            pick = dict(
                target["pick"],
                x=round(target["pick"]["x"] + dx_mm / 1000.0, 4),
                y=round(target["pick"]["y"] + dy_mm / 1000.0, 4),
            )
            target["pick"] = pick
            replan_path = write_library(config, pick, target["place"], work / "reinsert-replan.json")
            retry_cmds = (f"load {replan_path}", "goto above_pick", "run descend_pick", "run grasp_pick")
            if stage == "run lift_pick":
                retry_cmds = (*retry_cmds, "run lift_pick")
            for c in retry_cmds:
                st = run_cmd(c)
                if not st.get("ok") or st.get("contact"):
                    decision["verdict"] = "reinsert_and_park"
                    decision["retry_failed_at"] = c
                    return decision
            decision["retry_status"] = st
        return decision

    return check
