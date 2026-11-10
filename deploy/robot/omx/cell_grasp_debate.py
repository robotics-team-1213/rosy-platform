#!/usr/bin/env python3
"""Multi-agent consistency debate and post-grasp stability / put-back (reinsert) judge.

Combines three seats at `above_pick`, `run grasp_pick`, and `run lift_pick`:
  1. Telemetry / Kinematic Judge (`telemetry_judge`): checks jaw position `state[5]` against `gripper.held_30mm`
     to catch shallow corner pinches (`state[5] < held_30mm - shallow_tol_units`, which slipped during fold in
     Trials 4-5) and diagonal rim wedges (`state[5] > held_30mm + wedged_tol_units`).
  2. Wrist-Vision Judge (`vision_judge`): measures the container's lateral (`along_mm`) and depth (`across_mm`)
     offset between the v2.1 white fingers (`cell_fingers.finger_offset_mm`) and computes the corrective shift
     `(dx_mm, dy_mm)` along the closing axis.
  3. Multi-Model Debate (`debate_models`): runs a Critic -> Arbiter consistency debate across configured decision
     models (e.g., GLM `glm-4.7` + `glm-4.5-air` via ZAI API or Ollama VLMs) while keeping measured safety bounds
     sovereign.

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
import os
import urllib.request
from pathlib import Path

import numpy as np

import cell_fingers
import cell_params as prm

ACTIONS = ("proceed", "reinsert_and_retry", "reinsert_and_park")


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start:end + 1])
    return json.loads(text)


def load_zai_key() -> str | None:
    for env_name in ("ZAI_API_KEY", "GLM_API_KEY"):
        if os.environ.get(env_name):
            return os.environ[env_name].strip()
    auth_path = Path.home() / ".local/share/opencode/auth.json"
    if auth_path.is_file():
        try:
            data = json.loads(auth_path.read_text(encoding="utf-8"))
            key = (data.get("zai-coding-plan") or {}).get("key")
            if isinstance(key, str) and key.strip():
                return key.strip()
        except Exception:
            pass
    return None


def glm_backend(model: str = "glm-4.7", url: str = "https://api.z.ai/api/coding/paas/v4/chat/completions",
                api_key: str | None = None, timeout: float = 12.0):
    """Decision model callable `(prompt, images_b64, schema) -> dict` backed by GLM (ZAI Coding Plan API)."""
    def ask(prompt: str, images=(), schema=None) -> dict:
        key = api_key or load_zai_key()
        if not key:
            raise RuntimeError("no ZAI_API_KEY / opencode auth key configured")
        sys_msg = (
            "You are a robotics grasp-stability and multi-tier stacking arbiter. "
            "Reply with a single compact JSON object matching the requested schema."
        )
        if schema:
            sys_msg += f" Schema: {json.dumps(schema)}"
        body = {
            "model": model,
            "thinking": {"type": "disabled"},
            "temperature": 0.0,
            "messages": [
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": prompt},
            ],
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read())
        content = payload["choices"][0]["message"]["content"]
        return _extract_json(content)

    ask.__name__ = f"glm({model})"
    return ask


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


def debate_and_decide(stage: str, telemetry: dict, vision: dict, reinsert_count: int = 0,
                      max_reinsert: int = 1, models: list | tuple = ()) -> dict:
    """Cross-check Telemetry (Agent 1) + Wrist Vision (Agent 2) + Decision Model Debate (Agent 3..N).

    Returns:
      {
        "verdict": "proceed" | "reinsert_and_retry" | "reinsert_and_park" | "empty",
        "recovery_chunk": None | "run release_pick" | "run reinsert_pick",
        "dx_mm": float, "dy_mm": float,
        "telemetry": dict, "vision": dict, "debate": list[dict], "reason": str
      }
    """
    if telemetry.get("verdict") == "empty":
        return {
            "verdict": "empty",
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
    allowed = list(ACTIONS) if reinsert_count < max_reinsert else ["proceed", "reinsert_and_park"]
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

    for idx, model_fn in enumerate(models or ()):
        role = "critic" if idx == 0 else f"arbiter_{idx}"
        prompt = (
            f"Role: {role}. Stage: {stage}. Reinsert count: {reinsert_count}/{max_reinsert}.\n"
            f"Agent 1 (Telemetry): {json.dumps(telemetry)}\n"
            f"Agent 2 (Wrist Vision): {json.dumps(vision)}\n"
            f"Rule baseline: {{'verdict': {rule_verdict!r}, 'dx_mm': {dx_mm}, 'dy_mm': {dy_mm}, 'reason': {rule_reason!r}}}\n"
            f"Prior debate rounds: {json.dumps(debate_log)}\n"
            f"Allowed verdicts: {allowed}. Note: if Agent 1 or Agent 2 flagged 'reinsert', 'proceed' is forbidden by safety invariant. "
            "Reply with JSON only: {\"verdict\": ..., \"dx_mm\": ..., \"dy_mm\": ..., \"reason\": ...}."
        )
        try:
            ans = model_fn(prompt, (), schema)
            m_verdict = ans.get("verdict")
            # Measured safety invariant: a model cannot override a measured unstable grasp into 'proceed'
            if unstable and m_verdict == "proceed":
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
            debate_log.append(entry)
            final_verdict = m_verdict
            dx_mm, dy_mm = entry["dx_mm"], entry["dy_mm"]
            final_reason = entry["reason"] or rule_reason
        except Exception as exc:
            debate_log.append({
                "role": role,
                "model": getattr(model_fn, "__name__", "model"),
                "error": str(exc)[:120],
            })

    return {
        "verdict": final_verdict,
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

    models = []
    for m_spec in (config.get("debate_models") or ()):
        if callable(m_spec):
            models.append(m_spec)
        elif isinstance(m_spec, dict) and m_spec.get("provider") == "glm":
            models.append(glm_backend(model=m_spec.get("model", "glm-4.7"), timeout=float(m_spec.get("timeout", 10.0))))
        elif isinstance(m_spec, dict):
            import judge_seat
            models.append(judge_seat.ollama(**{k: v for k, v in m_spec.items() if k in ("url", "model", "timeout")}))

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
