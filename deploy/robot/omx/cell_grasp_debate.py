#!/usr/bin/env python3
"""Multi-agent consistency debate and post-grasp stability / put-back (reinsert) judge.

Single Responsibility:
  - Multi-agent deliberation (`debate_and_decide`) across Telemetry (Agent 1), Wrist-Vision (Agent 2),
    and Model Seats (Agent 3..N) under `judge_seat.measured` safety sovereignty.
  - Post-grasp / post-lift physical put-back (`release_pick` / `reinsert_pick`) and replan hook (`hook`).

Individual Agent 1 (`telemetry_judge`), Agent 2 (`vision_judge`), and consensus evidence weighting
live in `cell_grasp_judges.py` and are re-exported here for backward compatibility.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from cell_control_core import clamp_workspace_xy
import cell_decisions as cd
import cell_fingers
from cell_grasp_judges import (  # noqa: F401  (re-exported)
    ACTIONS,
    SCHEMA_VERSION,
    _jaw_value,
    _normalize_models,
    compute_consensus_evidence_weight,
    glm_backend,
    load_zai_key,
    telemetry_judge,
    vision_judge,
)
import cell_params as prm
import judge_seat


def debate_and_decide(
    stage: str,
    telemetry: dict,
    vision: dict,
    reinsert_count: int = 0,
    max_reinsert: int = 1,
    models: list | tuple | dict = (),
    *,
    images: list | tuple = (),
    knowledge=None,
    context: str = "",
    il_confidence: float | None = None,
    shape_score: float | None = None,
) -> dict:
    """Cross-check Telemetry (Agent 1) + Wrist Vision (Agent 2) + Model Deliberation (Agent 3..N).

    Uses `judge_seat.measured` for precondition sovereignty (`next='transport'`, `holding=True`, `stable=not unstable`),
    injects `cell_knowledge` and `cell_decisions.context` background, and runs `proposal -> critique -> arbiter`
    deliberation across any configured model backends.
    """
    if telemetry.get("verdict") == "empty":
        return {
            "schema_version": SCHEMA_VERSION,
            "verdict": "empty",
            "by": "measurement",
            "consensus": True,
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
        "applies": ["grasp", "lift", "safety"],
        "holding": True,
        "stable": not unstable,
        "reinsert": unstable,
        "stage": stage,
        "reinsert_count": reinsert_count,
    }
    _, seat_forbidden = judge_seat.measured(seat_facts)

    notes = []
    if knowledge:
        import cell_knowledge

        if isinstance(knowledge, (str, Path)):
            knowledge = cell_knowledge.load(knowledge)
        notes = cell_knowledge.select(knowledge, seat_facts)

    if not unstable:
        rule_verdict = "proceed"
        rule_reason = f"{telemetry.get('reason')}; {vision.get('reason')}"
    elif reinsert_count < max_reinsert:
        rule_verdict = "reinsert_and_retry"
        rule_reason = (
            f"unstable grasp at {stage} ({telemetry.get('class')}/{vision.get('class')}): "
            f"put back via {recovery_chunk} and re-pick shifted by [{dx_mm}, {dy_mm}] mm"
        )
    else:
        rule_verdict = "reinsert_and_park"
        rule_reason = (
            f"unstable grasp at {stage} after {reinsert_count} re-inserts: "
            f"put back via {recovery_chunk} and park"
        )

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

    bg = ""
    if notes:
        bg += "Cell knowledge (background): " + " ".join(f"[{e['id']} {e['status']}] {e['statement']}" for e in notes) + "\n"
    if context:
        bg += f"Past cell decisions (background): {context}\n"

    live_models = _normalize_models(models)
    for idx, model_fn in enumerate(live_models):
        role = "proposal" if idx == 0 else ("critique" if idx == 1 and len(live_models) > 2 else f"arbiter_{idx}")
        prompt = (
            f"{bg}[Deliberation v{SCHEMA_VERSION}] Role: {role}. Stage: {stage}. Reinsert count: {reinsert_count}/{max_reinsert}.\n"
            f"Seat measured facts: {json.dumps(seat_facts)} (forbidden decisions: {sorted(seat_forbidden)})\n"
            f"Agent 1 (Telemetry): {json.dumps(telemetry)}\n"
            f"Agent 2 (Wrist Vision): {json.dumps(vision)}\n"
            f"Rule baseline: {{'verdict': {rule_verdict!r}, 'dx_mm': {dx_mm}, 'dy_mm': {dy_mm}, 'reason': {rule_reason!r}}}\n"
            f"Prior deliberation rounds: {json.dumps(debate_log)}\n"
            f"Allowed verdicts: {allowed}. Note: if Agent 1 or Agent 2 flagged 'reinsert', 'proceed' is forbidden by safety invariant. "
            'Reply with JSON only: {"verdict": ..., "dx_mm": ..., "dy_mm": ..., "reason": ...}.'
        )
        try:
            ans = model_fn(prompt, images, schema)
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
            debate_log.append(
                {
                    "role": role,
                    "model": getattr(model_fn, "__name__", "model"),
                    "error": str(exc)[:120],
                }
            )

    verdicts_seen = [d["verdict"] for d in debate_log if "verdict" in d]
    consensus = len(set(verdicts_seen)) <= 1
    ev_weight = compute_consensus_evidence_weight(vision, il_confidence=il_confidence, shape_score=shape_score)
    if ev_weight != 1.0:
        dx_mm = float(np.clip(dx_mm * ev_weight, -8.0, 8.0))
        dy_mm = float(np.clip(dy_mm * ev_weight, -8.0, 8.0))
    out = {
        "schema_version": SCHEMA_VERSION,
        "verdict": final_verdict,
        "by": by,
        "consensus": consensus,
        "evidence_weight": ev_weight,
        "options": allowed,
        "recovery_chunk": None if final_verdict == "proceed" else recovery_chunk,
        "dx_mm": round(dx_mm, 2),
        "dy_mm": round(dy_mm, 2),
        "telemetry": telemetry,
        "vision": vision,
        "debate": debate_log,
        "reason": final_reason,
    }
    if notes:
        out["knowledge_ids"] = [e["id"] for e in notes]
    return out


def hook(config: dict, cell, target: dict, write_library, gap_mm: float):
    """Post-grasp / post-lift stability and put-back (`release_pick` / `reinsert_pick`) hook for `transfer_folded`."""
    params, spec = config.get("params"), config.get("wrist") or {}
    if not isinstance(params, dict) or not prm.get(params, "grasp.stability_check", 1):
        return None
    if "gripper.held_30mm" not in params and not config.get("decision_model") and not config.get("debate_models"):
        return None

    work = Path(config["work_dir"]).expanduser()
    camera = spec.get("camera", "wrist")
    hsv = (spec["hsv_min"], spec["hsv_max"]) if spec.get("hsv_min") and spec.get("hsv_max") else None
    closing = target["pick"]["yaw_deg"] + prm.get(params, "auto.closing_theory_deg")
    signs_path = work / f"wrist-signs-{config.get('arm_id', 'arm_s')}.json"
    default_signs = dict({"along": -1.0, "across": 1.0}, **(spec.get("finger_sign") or {}))
    finger_color = cell_fingers.resolve_finger_color(params, spec)
    max_reinsert = int(prm.get(params, "grasp.max_reinsert", 1))
    models = _normalize_models(config.get("debate_models") or config.get("decision_model"))
    knowledge = config.get("knowledge")
    decision_ctx = cd.context(config["decision_context"]) if config.get("decision_context") else ""

    state_tracker = {"reinsert_count": 0, "last_along_mm": None, "signs_cache": None}

    def _load_signs() -> dict:
        try:
            st = signs_path.stat()
        except OSError:
            return dict(default_signs)
        cached = state_tracker["signs_cache"]
        if cached is not None and cached[0] == st.st_mtime_ns and cached[1] == st.st_size:
            return dict(cached[2])
        loaded = json.loads(signs_path.read_text())
        state_tracker["signs_cache"] = (st.st_mtime_ns, st.st_size, loaded)
        return dict(loaded)

    def check(stage: str, status: dict, run_cmd) -> dict:
        signs = _load_signs()
        current_ma = status.get("gripper_current_ma")
        if current_ma is None:
            cur_list = (status.get("health") or {}).get("current_ma")
            if isinstance(cur_list, list) and len(cur_list) >= 6:
                current_ma = cur_list[-1] if len(cur_list) in (6, 7, 8) else cur_list[5]
        t_res = telemetry_judge(status.get("state"), status.get("holding"), params, current_ma=current_ma)
        wrist_img, images_b64 = None, ()
        if hsv is not None and stage == "run grasp_pick" and prm.get(params, "grasp.vision_after_grasp", 0):
            try:
                wrist_img = cell.frame(camera)
                if wrist_img is not None:
                    import base64
                    import cv2

                    images_b64 = (base64.b64encode(cv2.imencode(".jpg", wrist_img)[1].tobytes()).decode(),)
            except Exception:
                wrist_img = None
        v_res = vision_judge(wrist_img, hsv, gap_mm, closing, signs, params, color=finger_color)
        if v_res.get("found") and state_tracker["last_along_mm"] is not None:
            prev_along, cur_along = state_tracker["last_along_mm"], v_res["along_mm"]
            if prev_along * cur_along < 0 and abs(cur_along) > 1.5:
                v_res["dx_mm"] = round(v_res["dx_mm"] * 0.5, 2)
                v_res["dy_mm"] = round(v_res["dy_mm"] * 0.5, 2)
        if v_res.get("found"):
            state_tracker["last_along_mm"] = v_res["along_mm"]

        decision = debate_and_decide(
            stage=stage,
            telemetry=t_res,
            vision=v_res,
            reinsert_count=state_tracker["reinsert_count"],
            max_reinsert=max_reinsert,
            models=models,
            images=images_b64,
            knowledge=knowledge,
            context=decision_ctx,
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
                "consensus": decision["consensus"],
                "debate": decision["debate"],
            },
            decision.get("options", list(ACTIONS)),
            decision["verdict"],
            decision.get("by", "measurement"),
            decision["reason"],
        )
        if decision["verdict"] == "proceed":
            import cell_arm_cal

            jaw_pos = _jaw_value(status.get("state"))
            decision["arm_calibration"] = cell_arm_cal.record_grasp_measurement(
                config,
                arm_id=config.get("arm_id", "arm_s"),
                gripper_pos=jaw_pos,
                gripper_current_ma=status.get("gripper_current_ma"),
                width_mm=float(target.get("across_mm", 30.0)),
                skew_mm=v_res.get("along_mm") if v_res.get("found") else None,
                mm_per_px=v_res.get("mm_per_px"),
                finger_color=finger_color if finger_color in ("dark", "white") else None,
            )
            return decision
        if decision["verdict"] == "empty":
            return decision

        rec_cmd = decision["recovery_chunk"]
        rec_status = run_cmd(rec_cmd)
        decision["released_jaw_units"] = _jaw_value(rec_status.get("state"))
        decision["put_back_ok"] = bool(rec_status.get("ok")) and not rec_status.get("contact")
        if not decision["put_back_ok"]:
            decision["verdict"] = "reinsert_and_park"
            return decision

        if decision["verdict"] == "reinsert_and_retry":
            state_tracker["reinsert_count"] += 1
            dx_mm, dy_mm = decision["dx_mm"], decision["dy_mm"]
            cx, cy = clamp_workspace_xy(
                target["pick"]["x"] + dx_mm / 1000.0,
                target["pick"]["y"] + dy_mm / 1000.0,
                arm_id=str(config.get("arm_id", "arm_s")),
            )
            pick = dict(target["pick"], x=cx, y=cy)
            target["pick"] = pick
            replan_path = write_library(config, pick, target["place"], work / "reinsert-replan.json")
            reach_fn = None
            if prm.get(params, "grasp.reach_on_reinsert", 0):
                import cell_reach

                reach_fn = cell_reach.hook(config, cell, target, write_library)
            retry_cmds = (f"load {replan_path}", "goto above_pick", "reach", "run descend_pick", "run grasp_pick")
            if stage == "run lift_pick":
                retry_cmds = (*retry_cmds, "run lift_pick")
            for c in retry_cmds:
                if c == "reach":
                    if reach_fn is not None and reach_fn().get("verdict") == "refuse":
                        decision["verdict"] = "reinsert_and_park"
                        decision["retry_failed_at"] = "reach"
                        return decision
                    continue
                st = run_cmd(c)
                if not st.get("ok") or st.get("contact"):
                    decision["verdict"] = "reinsert_and_park"
                    decision["retry_failed_at"] = c
                    return decision
            decision["retry_status"] = st
        return decision

    return check
