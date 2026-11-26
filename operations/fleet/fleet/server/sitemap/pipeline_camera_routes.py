from __future__ import annotations

from contextlib import suppress
import copy
import functools
import hashlib
import json
import math
import os
import time
from fastapi import HTTPException, Request
from fleet.server.pipeline.bound_home_receipt import sync_home_receipts, verified_hold_reason
from fleet.charge_bays import ChargeBays, bays_from_map
from fleet.pipeline import evaluate_fleet_pipeline, resolve_omx_cells, evaluate_omx_cell_station
from fleet.pipeline.cell_site_targets import cell_ab_completion_verified
from fleet.site_rules import SiteRules

from fleet.server.pipeline_port_events import (
    build_completion_events,
    flush_pending_port_events_async,
    strip_task_for_claim,
)
from fleet.server.sitemap.pipeline_routes import _enrich_task_health
from fleet.server.sitemap import pipeline_auto_events as auto_events
from fleet.server.sitemap import pipeline_repark


from fleet.server.pipeline_recovery_policy import effective_stop_fence
from fleet.server.pipeline_recovery_tools import (
    clear_label as _clear_label,
    clear_open_arm_incidents as _clear_open_arm_incidents,
)

_CELL_ARMS = (("cell_s", ("arm_s",)), ("cell_ab", ("arm_a", "arm_b")))


# Refusals the console explains as missing evidence or a held cell; malformed requests leave the ledger as it was.
RECORDED_REFUSALS = frozenset({
    "AMR_BRAKE_BED_VELOCITY_UNMEASURED", "OMX_OWNER_EVIDENCE_UNAVAILABLE", "OMX_OWNER_EVIDENCE_MISMATCH",
    "UNVERIFIED_CELL_COMPLETION", "OWNER_PRINCIPAL_NOT_REGISTERED", "HUMAN_HOLD_ACTIVE",
    "CELL_BUSY_OR_HELD", "PREVIOUS_TIER_NOT_VERIFIED", "CELL_AB_EVIDENCE_NOT_ENABLED", "BED_CONFIRMATION_INVALID",
    "PRESENCE_CONFIRMATION_REQUIRED",
})


def install_cameras_routes(app, ctx) -> None:
    read_guard = ctx.read_guard
    operator_guard = ctx.operator_guard
    proposer_guard = getattr(ctx, "proposer_guard", operator_guard)
    _arm_live_catalog = ctx._arm_live_catalog
    gov = getattr(ctx, "gov", None) or getattr(app.state, "pipeline_governance", None)
    _save_ledger = ctx._save_ledger
    _commit_ledger = getattr(ctx, "_commit_ledger", None)
    _is_human_detected = ctx._is_human_detected
    rules = ctx.rules
    _ready_amr = ctx._ready_amr
    omx_evidence_fn = ctx.omx_evidence_fn
    active_map = ctx.active_map

    # Last claim/complete refusal per task, for the console (GET /cell-tasks merges it into the row). Kept beside the
    # ledger, not in it: a refused claim must leave the ledger file as it was.
    refusals = app.state.cell_task_refusals = getattr(app.state, "cell_task_refusals", None) or {}

    def _records_refusal(op):
        """Remember the route's last evidence refusal for its task; the answer or error passes through as it is."""
        def wrap(endpoint):
            @functools.wraps(endpoint)
            async def route(**kwargs):
                try:
                    result = await endpoint(**kwargs)
                except HTTPException as exc:
                    code = exc.detail.get("code") if isinstance(exc.detail, dict) else None
                    if code in RECORDED_REFUSALS and kwargs.get("task_id") in app.state.omx_cell_tasks:
                        refusals[kwargs["task_id"]] = {**exc.detail, "op": op, "at": round(time.time(), 3)}
                    raise
                task_id = (result.get("task") or {}).get("task_id") if op == "claim" else kwargs.get("task_id")
                if op == "claim" and result.get("claimed") is False and result.get("reason") in RECORDED_REFUSALS:
                    refusals[task_id] = {"code": result["reason"], "op": op, "at": round(time.time(), 3)}
                elif op == "complete" or result.get("claimed") is True:
                    refusals.pop(task_id, None)
                return result
            return route
        return wrap

    # D-136: 이 모듈은 카메라 프레임을 서빙하지 않는다. 셀 카메라 미리보기는
    # POST /api/fleet/vision/lease -> Vision frame_path로만 얻는다(test_no_video_relay).

    @app.post("/api/fleet/pipeline/cell-quality", dependencies=proposer_guard)
    async def ingest_cell_quality(request: Request):
        body = await request.json()
        from fleet.server.pipeline_recovery_policy import (
            ARM_CELL, CAM_CELL, cell_quality_key_allowed,
        )

        cams = body.get("cameras")
        if isinstance(cams, dict):
            cam_recorded = round(time.time(), 3)
            for k, v in cams.items():
                if isinstance(v, dict) and cell_quality_key_allowed(app, request, CAM_CELL.get(str(k))):
                    app.state.cell_camera_quality[str(k)] = {**v, "recorded_at": cam_recorded}
        holds = body.get("arm_holds")
        if isinstance(holds, dict):
            for arm_id in ("arm_s", "arm_a", "arm_b"):
                if isinstance(holds.get(arm_id), dict) and cell_quality_key_allowed(app, request, ARM_CELL[arm_id]):
                    h = holds[arm_id]
                    new_held = bool(h.get("local_held") or h.get("fleet_held") or h.get("held"))
                    if arm_id in app.state.pending_clear_arms:
                        if not new_held:
                            app.state.pending_clear_arms.pop(arm_id, None)
                        continue
                    prev_held = bool((app.state.arm_holds.get(arm_id) or {}).get("held"))
                    if prev_held and not new_held:
                        continue  # Clearing an arm hold requires POST /arm-holds/clear.
                    app.state.arm_holds[arm_id] = {
                        "arm": arm_id,
                        "held": new_held,
                        "reason": verified_hold_reason(h),
                        "incident_ids": list(h.get("incident_ids") or []),
                    }
                    if new_held and not prev_held and gov is not None:
                        gov.bump_stop_generation()
        arm_states = body.get("arm_states")
        if isinstance(arm_states, dict):
            now_ts = round(time.time(), 3)
            for arm_id in ("arm_s", "arm_a", "arm_b"):
                if isinstance(arm_states.get(arm_id), dict) and cell_quality_key_allowed(app, request, ARM_CELL[arm_id]):
                    s = arm_states[arm_id]
                    if "updated_at" in s:
                        raw_ts = s["updated_at"]
                        if isinstance(raw_ts, bool) or not isinstance(raw_ts, (int, float)):
                            raise HTTPException(422, detail={"code": "INVALID_PIPELINE_NUMBER"})
                        try:
                            ts = float(raw_ts)
                        except OverflowError:
                            raise HTTPException(422, detail={"code": "INVALID_PIPELINE_NUMBER"}) from None
                        if not math.isfinite(ts):
                            raise HTTPException(422, detail={"code": "INVALID_PIPELINE_NUMBER"})
                    else:
                        ts = now_ts
                    if "folded" in s and s["folded"] is not None and not isinstance(s["folded"], bool):
                        raise HTTPException(422, detail={"code": "INVALID_PIPELINE_NUMBER"})
                    prev = dict(app.state.arm_live_states.get(arm_id) or {})
                    joints = s.get("joints_deg") or s.get("state")
                    if isinstance(joints, list) and len(joints) >= 6:
                        prev["joints_deg"] = [round(float(x), 1) for x in joints[:6]]
                    if "folded" in s and s["folded"] is not None:
                        prev["folded"] = s["folded"]
                        prev["folded_updated_at"] = ts
                    else:
                        if prev.get("source") == "boot_default":
                            prev["folded"] = None
                        prev.setdefault("folded_updated_at", None)
                    if s.get("temp_c") is not None:
                        prev["temp_c"] = round(float(s["temp_c"]), 1)
                    if s.get("current_ma") is not None:
                        prev["current_ma"] = round(float(s["current_ma"]), 1)
                    if s.get("voltage_v") is not None:
                        prev["voltage_v"] = round(float(s["voltage_v"]), 2)
                    prev["updated_at"] = ts
                    prev["source"] = str(s.get("source") or "live_stream")
                    app.state.arm_live_states[arm_id] = prev
        if auto_events.add(app.state, body.get("auto_events"), "cell") and not app.state._pipeline_ledger_fault:
            _save_ledger()  # what the cell did by itself, kept with the ledger (pipeline_auto_events)
        for ack_arm in body.get("clear_ack_arms") or ():
            app.state.pending_clear_arms.pop(str(ack_arm), None)
        fence_held, fence_gen = effective_stop_fence(app.state)
        human_hold = bool(_is_human_detected() or fence_held or any(
            (s or {}).get("phase") == "HUMAN_HOLD" for s in app.state.omx_cell_states.values()
        ))
        pending_home_out = sync_home_receipts(app, request, body, human_hold, _save_ledger, time.time())
        pending = dict(app.state.pending_clear_arms)
        return {
            "ok": True,
            "schema": "rosy.pipeline.cell-quality.v1",
            "cameras_updated": len(app.state.cell_camera_quality),
            "arm_holds": app.state.arm_holds,
            "arm_live_states": _arm_live_catalog(),
            "pending_clear_arms": pending,
            "pending_safe_home_arms": pending_home_out,
            "human_hold": human_hold,
            "safety_stop_generation": fence_gen,
        }

    @app.post("/api/fleet/pipeline/arm-holds/clear", dependencies=operator_guard)
    async def clear_pipeline_arm_holds(request: Request):
        body = await request.json()
        target = str(body.get("arm_id") or body.get("cell_id") or "all")
        note = str(body.get("note") or "verified folded home and cleared hold from Fleet console").strip()
        if not note:
            raise HTTPException(400, detail={"code": "EMPTY_CLEAR_NOTE"})
        if target == "cell_s":
            arms = ["arm_s"]
        elif target == "cell_ab":
            arms = ["arm_a", "arm_b"]
        elif target in ("arm_s", "arm_a", "arm_b"):
            arms = [target]
        elif target == "all":
            arms = ["arm_s", "arm_a", "arm_b"]
        else:
            raise HTTPException(422, detail={"code": "UNKNOWN_ARM_OR_CELL"})
        from fleet.server.pipeline_recovery_policy import ensure_clearable_after_homing, mark_homing_cleared

        ensure_clearable_after_homing(app.state, arms)
        cause, basis = _clear_label(body, "cause"), _clear_label(body, "basis")
        principal = getattr(request.state, "site_principal", None)
        raw_principal_id = getattr(principal, "principal_id", None)
        named_principal_id = raw_principal_id.strip() if isinstance(raw_principal_id, str) else ""
        aborted_targets = [
            (cid, c_arms) for cid, c_arms in _CELL_ARMS
            if any(a in arms for a in c_arms) and (app.state.omx_cell_states.get(cid) or {}).get("phase") == "ABORTED"
        ]
        if aborted_targets:
            if not named_principal_id or named_principal_id == "site-console" or named_principal_id.startswith("development-"):
                raise HTTPException(403, detail={"code": "NAMED_OPERATOR_REQUIRED"})
            if getattr(app.state, "_pipeline_ledger_fault", False):
                raise HTTPException(503, detail={"code": "PIPELINE_LEDGER_UNAVAILABLE"})
        principal_id = named_principal_id or "operator"
        _missing = object()
        prev_holds = {a: (copy.deepcopy(app.state.arm_holds[a]) if a in app.state.arm_holds else _missing) for a in arms}
        prev_pending = {a: app.state.pending_clear_arms.get(a, _missing) for a in arms}
        prev_states = {cid: copy.deepcopy(app.state.omx_cell_states[cid])
                       for cid, _ in aborted_targets if cid in app.state.omx_cell_states}
        prev_homing = copy.deepcopy(app.state.pipeline_homing_sessions) if hasattr(app.state, "pipeline_homing_sessions") else _missing
        for a in arms:
            app.state.arm_holds[a] = {"arm": a, "held": False, "reason": None, "incident_ids": [], "last_cleared_note": note}
            app.state.pending_clear_arms[a] = note
        cleared_cells = []
        for cid, c_arms in aborted_targets:
            if (all(not (app.state.arm_holds.get(a) or {}).get("held") for a in c_arms)
                    and not _is_human_detected(cid)
                    and not any(t["cell_id"] == cid and t["status"] in ("RUNNING", "PAUSED_HUMAN")
                                for t in app.state.omx_cell_tasks.values())):
                prev = dict(app.state.omx_cell_states[cid])
                docked = prev.get("docked_robot")
                cleared_docked = {**docked, "wheel_brake_locked": False, "bed_ready": False} if isinstance(docked, dict) else None
                app.state.omx_cell_states[cid] = {
                    "phase": "IDLE", "robot_id": prev.get("robot_id"), "amr_motion_inhibited": False,
                    "reason": "OPERATOR_ABORT_CLEARED", "cleared_by": principal_id, "cleared_note": note,
                    "cleared_at": round(time.time(), 3), **({"docked_robot": cleared_docked} if cleared_docked is not None else {}),
                }
                cleared_cells.append(cid)
        try:
            mark_homing_cleared(app.state, arms)
            _commit_ledger(bump_stop=True) if callable(_commit_ledger) else (_save_ledger(), gov and gov.bump_stop_generation())
        except Exception:
            for a, old in prev_holds.items():
                app.state.arm_holds.pop(a, None) if old is _missing else app.state.arm_holds.__setitem__(a, old)
            for a, old in prev_pending.items():
                app.state.pending_clear_arms.pop(a, None) if old is _missing else app.state.pending_clear_arms.__setitem__(a, old)
            for cid, old in prev_states.items():
                app.state.omx_cell_states[cid] = old
            if prev_homing is _missing:
                if hasattr(app.state, "pipeline_homing_sessions"):
                    delattr(app.state, "pipeline_homing_sessions")
            else:
                app.state.pipeline_homing_sessions = prev_homing
            if callable(_commit_ledger) and not getattr(app.state, "_pipeline_ledger_fault", False):
                with suppress(Exception):
                    _commit_ledger(commit=False)
            raise
        _clear_open_arm_incidents(app, arms, note, principal_id, cause, basis)
        return {"ok": True, "cleared_arms": arms, "cleared_cells": cleared_cells, "note": note,
                "arm_holds": app.state.arm_holds}

    @app.post("/api/fleet/pipeline/cell-tasks/claim", dependencies=proposer_guard)
    @_records_refusal("claim")
    async def claim_cell_task(request: Request):
        if app.state._pipeline_ledger_fault:
            raise HTTPException(503, detail={"code": "PIPELINE_LEDGER_UNAVAILABLE"})
        active = active_map()
        body = await request.json()
        cell_id = str(body.get("cell_id") or "cell_s")
        if _is_human_detected(cell_id):
            return {"claimed": False, "task": None, "blocked_by_human": True, "reason": "HUMAN_DETECTED_ESTOP"}
        req_id = body.get("task_id")
        candidates = [
            t for t in app.state.omx_cell_tasks.values()
            if t["cell_id"] == cell_id and t["status"] == "QUEUED" and (req_id is None or t["task_id"] == req_id)
        ]
        if not candidates:
            return {"claimed": False, "task": None}
        task = candidates[0]
        # D-1057: the claiming principal must be a registered owner of this cell, or a result could never be accepted and the
        # task would stay RUNNING. Refused before the ledger changes. Bare apps without authentication (no principal) skip it.
        from fleet.server.sitemap.pipeline_evidence import cell_owner_principals, owner_principal_refusal

        if ((getattr(request.state, "site_principal", None) is not None or cell_owner_principals(cell_id))
                and owner_principal_refusal(request, task) is not None):
            return {"claimed": False, "task": strip_task_for_claim(task), "reason": "OWNER_PRINCIPAL_NOT_REGISTERED"}
        if type(task.get("tier")) is not int or task["tier"] not in (1, 2, 3):
            return {"claimed": False, "task": strip_task_for_claim(task), "reason": "INVALID_CELL_TIER"}
        predecessor = task.get("depends_on")
        if predecessor and (app.state.omx_cell_tasks.get(predecessor) or {}).get("status") != "COMPLETED":
            return {"claimed": False, "task": strip_task_for_claim(task), "reason": "PREVIOUS_TIER_NOT_VERIFIED"}
        active_task = next((t for t in app.state.omx_cell_tasks.values()
                            if t["cell_id"] == cell_id and t["status"] == "RUNNING"), None)
        cell_state = app.state.omx_cell_states.get(cell_id) or {}
        held_for_two_tier = (cell_id == "cell_s" and active_task is None
                             and bool(task.get("unload_batch_id"))
                             and cell_state.get("unload_batch_id") == task.get("unload_batch_id")
                             and cell_state.get("phase") == "CLAIMED"
                             and cell_state.get("robot_id") == task["robot_id"])
        if (active_task is not None or cell_state.get("phase") in ("ARM_IN_BED_ZONE", "HUMAN_HOLD")
                or (cell_state.get("amr_motion_inhibited") and not held_for_two_tier)):
            return {"claimed": False, "task": strip_task_for_claim(task), "reason": "CELL_BUSY_OR_HELD"}
        # D-1057: cell A/B release stays off until the depth acceptance; refused here, before anything in the ledger changes.
        if cell_id == "cell_ab" and os.environ.get("ROSY_FLEET_CELL_AB_RELEASE_ENABLED", "").strip().lower() not in ("1", "true", "yes", "on"):
            return {"claimed": False, "task": strip_task_for_claim(task), "reason": "CELL_AB_EVIDENCE_NOT_ENABLED"}
        if cell_id == "cell_ab":
            store = getattr(app.state, "arm_transfer_job_store", None)
            if callable(getattr(store, "has_active_transfer", None)) and store.has_active_transfer():
                return {"claimed": False, "task": strip_task_for_claim(task), "reason": "CELL_WORK_CONFLICT"}
        # D-1072: cell_internal on cell_ab allows claim without docked AMR once all gates above pass.
        internal = cell_id == "cell_ab" and task.get("interlock_scope") == "cell_internal"
        amr = _ready_amr(task)
        robot = None
        state = {"phase": "ARM_IN_BED_ZONE", "tier": task["tier"], "robot_id": task["robot_id"], "stage_id": task["task_id"]}
        if amr is None:
            if not internal:
                return {"claimed": False, "task": strip_task_for_claim(task), "reason": "AMR_BRAKE_BED_VELOCITY_UNMEASURED"}
            res = {"gate": {"cell_can_claim": True, "interlock_scope": "cell_internal"},
                   "handoff": {"handoff_lease_id": f"cell_ab:cell_internal:{task['task_id']}", "cell_id": cell_id}}
        else:
            station = resolve_omx_cells(active[1], active[2]).get(cell_id)
            if station is None:
                raise HTTPException(404, detail={"code": "UNKNOWN_CELL"})
            robot = {"robot_id": task["robot_id"], "robot_kind": task["robot_kind"], "pose": dict(amr["pose"]),
                     "wheel_brake_locked": amr["wheel_brake_locked"], "bed_ready": amr["bed_ready"], "v_cmd_mps": amr["v_cmd_mps"]}
            res = evaluate_omx_cell_station(station, docked_robot=robot, cell_state=state, map_version=getattr(active[2], "version", None))
            if res["gate"].get("cell_can_claim") is not True or res.get("handoff") is None:
                return {"claimed": False, "task": strip_task_for_claim(task), "gate": res["gate"]}
        from fleet.server.sitemap.pipeline_evidence import bind_bed, has_valid_presence, take_presence

        claim_now, tid, _missing = time.time(), task["task_id"], object()
        if (task.get("execution_mode") == "act_policy" or task.get("requires_presence_confirm")) and not has_valid_presence(app, task, now=claim_now):
            return {"claimed": False, "task": strip_task_for_claim(task), "reason": "PRESENCE_CONFIRMATION_REQUIRED"}
        pres_map = getattr(app.state, "cell_presence", None) or {}
        bed_map = getattr(app.state, "cell_bed_confirmations", None) or {}
        prev_cell = copy.deepcopy(app.state.omx_cell_states[cell_id]) if cell_id in app.state.omx_cell_states else _missing
        prev_task = copy.deepcopy(task)
        prev_pres = copy.deepcopy(pres_map[tid]) if tid in pres_map else _missing
        prev_bed = copy.deepcopy(bed_map[tid]) if tid in bed_map else _missing
        # D-1057: bind bed confirmation atomically with going RUNNING (skipped only for AMR-less cell_internal claims).
        if amr is not None and not bind_bed(app, task, res["handoff"].get("handoff_lease_id")):
            return {"claimed": False, "task": strip_task_for_claim(task), "reason": "AMR_BRAKE_BED_VELOCITY_UNMEASURED"}
        try:
            app.state.omx_cell_states[cell_id] = {**state, "docked_robot": robot}
            task["presence"] = take_presence(app, task, now=claim_now, delete_gov=not callable(_commit_ledger))  # D-1057/D-911
            task["status"], task["amr_claim_evidence"] = "RUNNING", (dict(amr) if amr is not None else None)
            task["handoff_lease_id"], task["claimed_at"] = res["handoff"].get("handoff_lease_id"), round(time.time(), 3)
            _enrich_task_health(task)
            _commit_ledger(bump_dispatch=True, delete_confirmation=("presence", tid)) if callable(_commit_ledger) else (_save_ledger(), gov and gov.bump_dispatch_generation())
        except Exception:
            app.state.omx_cell_states.pop(cell_id, None) if prev_cell is _missing else app.state.omx_cell_states.__setitem__(cell_id, prev_cell)
            task.clear(); task.update(prev_task)
            if prev_pres is not _missing and isinstance(getattr(app.state, "cell_presence", None), dict):
                app.state.cell_presence[tid] = prev_pres
            if prev_bed is not _missing and isinstance(getattr(app.state, "cell_bed_confirmations", None), dict):
                app.state.cell_bed_confirmations[tid] = prev_bed
                if gov is not None:
                    with suppress(Exception):
                        gov.save_confirmation("bed", tid, prev_bed)
            if callable(_commit_ledger) and not getattr(app.state, "_pipeline_ledger_fault", False):
                with suppress(Exception):
                    _commit_ledger(commit=False)
            raise
        handoff = {
            **res["handoff"], "task_id": tid, "arm_id": task["arm_id"], "tier": task["tier"],
            "directive": task.get("directive"), "src_site": task["src_site"], "dst_site": task["dst_site"],
            "interlock_scope": task.get("interlock_scope"), "displaced_to": task.get("displaced_to"),
            "tier_hint": task.get("tier_hint"), "presence": task["presence"],
            **{k: task[k] for k in ("src_site_id", "dst_site_id", "dst_area", "dst_slot", "execution_mode", "max_chunks") if task.get(k) is not None},
        }
        return {"claimed": True, "task": strip_task_for_claim(task), "handoff": handoff, "gate": res["gate"]}

    @app.post("/api/fleet/pipeline/cell-tasks/{task_id}/complete", dependencies=proposer_guard)
    @_records_refusal("complete")
    async def complete_cell_task(task_id: str, request: Request):
        if app.state._pipeline_ledger_fault:
            raise HTTPException(503, detail={"code": "PIPELINE_LEDGER_UNAVAILABLE"})
        active = active_map()
        task = app.state.omx_cell_tasks.get(task_id)
        if task is None:
            raise HTTPException(404, detail={"code": "UNKNOWN_TASK"})
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(422, detail={"code": "INVALID_CELL_COMPLETION"})
        try:
            json.dumps(body, allow_nan=False)
        except (TypeError, ValueError):
            raise HTTPException(422, detail={"code": "INVALID_CELL_COMPLETION"}) from None
        cell_id = task["cell_id"]
        station = resolve_omx_cells(active[1], active[2]).get(cell_id)
        phase = body.get("phase")
        if task.get("status") != "RUNNING" or phase not in ("RELEASED", "ABORTED"):
            raise HTTPException(409, detail={"code": "CELL_TASK_NOT_RUNNING_OR_PHASE_MISSING"})
        if phase == "RELEASED" and (_is_human_detected(cell_id)
                                    or (app.state.omx_cell_states.get(cell_id) or {}).get("phase") == "HUMAN_HOLD"):
            raise HTTPException(409, detail={"code": "HUMAN_HOLD_ACTIVE"})
        if phase == "RELEASED":  # D-1057: only the principal that registered the owner evidence may release on it
            stored = (getattr(app.state, "cell_owner_evidence", None) or {}).get(task_id)
            if stored is not None and stored["principal_id"] != getattr(
                    getattr(request.state, "site_principal", None), "principal_id", None):
                raise HTTPException(403, detail={"code": "OWNER_PRINCIPAL_NOT_REGISTERED"})
        # P0-1/D-1072: AMR-less cell_internal claims skip AMR re-check on release; owner/hold/receipt checks still run.
        internal_release = cell_id == "cell_ab" and task.get("interlock_scope") == "cell_internal" and task.get("amr_claim_evidence") is None
        amr = None
        if phase == "RELEASED" and not internal_release:
            amr = _ready_amr(task)
            if amr is None:
                from fleet.server.sitemap.pipeline_evidence import bed_confirmation_lost

                raise HTTPException(422, detail={"code": "BED_CONFIRMATION_INVALID" if bed_confirmation_lost(app, task)
                                                 else "AMR_BRAKE_BED_VELOCITY_UNMEASURED"})
        elif phase != "RELEASED":
            amr = task.get("amr_claim_evidence")
        if phase == "RELEASED":
            trusted = omx_evidence_fn(task) if callable(omx_evidence_fn) else None
            if not isinstance(trusted, dict):
                raise HTTPException(422, detail={"code": "OMX_OWNER_EVIDENCE_UNAVAILABLE"})
            receipt = body.get("receipt") if isinstance(body.get("receipt"), dict) else {}
            stage_result = body.get("stage_result") if isinstance(body.get("stage_result"), dict) else {}
            verification = stage_result.get("verification") if isinstance(stage_result.get("verification"), dict) else {}
            hardware = body.get("hardware_telemetry") if isinstance(body.get("hardware_telemetry"), dict) else {}
            if trusted != {"receipt": receipt, "stage_result": stage_result, "hardware_telemetry": hardware}:
                raise HTTPException(422, detail={"code": "OMX_OWNER_EVIDENCE_MISMATCH"})
            stop_event = hardware.get("stop_event") if isinstance(hardware.get("stop_event"), dict) else {}
            evidence = {"task_id": task_id, "lease": receipt.get("handoff_lease_id"),
                        "stage_result": stage_result, "hardware_telemetry": hardware}
            digest = "sha256:" + hashlib.sha256(json.dumps(evidence, sort_keys=True, default=str).encode()).hexdigest()
            verified = (type(task.get("tier")) is int and task["tier"] in (1, 2, 3)
                        and receipt.get("physical_completion") is True
                        and receipt.get("simulated_success") is False
                        and receipt.get("phase") == "RELEASED"
                        and receipt.get("stage_id") == task_id and receipt.get("cell_id") == cell_id
                        and bool(task.get("handoff_lease_id"))
                        and receipt.get("handoff_lease_id") == task.get("handoff_lease_id")
                        and receipt.get("goal_evidence_digest") == body.get("goal_evidence_digest") == digest
                        and stage_result.get("directive_id") == task_id
                        and stage_result.get("arm_id") == task.get("arm_id")
                        and stage_result.get("task_verified") is True
                        and verification.get("verified") is True
                        # D-1057 (user decision 2026-11-20): cell S has no side camera, so its top-camera zone check counts
                        and verification.get("basis") in (("predefined_side_and_top_target_zones", "top_camera_only_target_zone")
                                                          if cell_id == "cell_s" else ("predefined_side_and_top_target_zones",))
                        and stop_event.get("ok") is True and stop_event.get("folded") is True)
            if cell_id == "cell_ab":
                place = stage_result.get("place") or {}
                z_gate = verification.get("z_gate") if isinstance(verification.get("z_gate"), dict) else {}
                verified = verified and isinstance(place, dict) and cell_ab_completion_verified(task, place, z_gate, verification)
            if not verified:
                raise HTTPException(422, detail={"code": "UNVERIFIED_CELL_COMPLETION"})
        cell_phase = phase
        if cell_id == "cell_s" and phase == "RELEASED" and task.get("unload_batch_id"):
            sc = (body.get("stage_result") or {}).get("source_clearance")
            objects = sc.get("objects") if isinstance(sc, dict) else None
            if type(objects) is not int or objects < 0:
                raise HTTPException(422, detail={"code": "UNVERIFIED_CELL_COMPLETION"})
            if objects > 0:
                cell_phase = "CLAIMED"
        robot = None if internal_release else {
            "robot_id": task["robot_id"], "robot_kind": task["robot_kind"], "pose": dict((amr or {}).get("pose") or task["pose"]),
            "wheel_brake_locked": bool((amr or {}).get("wheel_brake_locked")), "bed_ready": bool((amr or {}).get("bed_ready")),
            "v_cmd_mps": float((amr or {}).get("v_cmd_mps", 1.0)),
        }
        state = {"phase": cell_phase, "tier": task["tier"], "robot_id": task["robot_id"], "stage_id": task_id,
                 **({"unload_batch_id": task["unload_batch_id"]} if task.get("unload_batch_id") else {}),
                 "goal_evidence_digest": body.get("goal_evidence_digest"),
                 "reason": body.get("reason") or ("TRANSFER_CONFIRMED" if phase == "RELEASED" else "TASK_ABORTED"),
                 "amr_motion_inhibited": cell_phase in ("ABORTED", "CLAIMED")}
        res = evaluate_omx_cell_station(station, docked_robot=robot, cell_state=state, map_version=getattr(active[2], "version", None))
        _missing, arm_id = object(), task.get("arm_id")
        arm_map = getattr(app.state, "arm_live_states", None) or {}
        prev_cell = copy.deepcopy(app.state.omx_cell_states[cell_id]) if cell_id in app.state.omx_cell_states else _missing
        prev_task = copy.deepcopy(task)
        prev_arm = copy.deepcopy(arm_map[arm_id]) if (arm_id and arm_id in arm_map) else _missing
        prev_repark = copy.deepcopy(app.state.repark_requests) if hasattr(app.state, "repark_requests") else _missing
        prev_events = copy.deepcopy(app.state.cell_auto_events) if hasattr(app.state, "cell_auto_events") else _missing
        try:
            app.state.omx_cell_states[cell_id] = {**state, "docked_robot": robot}
            task["status"], task["completed_at"] = ("COMPLETED" if phase == "RELEASED" else "ABORTED"), round(time.time(), 3)
            task["receipt"], task["stage_result"], task["hardware_telemetry"] = (body.get("receipt") or state), body.get("stage_result"), body.get("hardware_telemetry")
            stop_ev = ((task.get("hardware_telemetry") or {}).get("stop_event") or {})
            if arm_id in ("arm_s", "arm_a", "arm_b") and isinstance(stop_ev.get("state"), list) and len(stop_ev["state"]) >= 6:
                prev = dict(app.state.arm_live_states.get(arm_id) or {})
                health = stop_ev.get("health") or {}
                temps, curs = (health.get("temp_c") or []), (health.get("current_ma") or [])
                prev["joints_deg"] = [round(float(x), 1) for x in stop_ev["state"][:6]]
                prev["folded"] = stop_ev["folded"] if isinstance(stop_ev.get("folded"), bool) else False
                prev["folded_updated_at"] = task["completed_at"] if prev["folded"] or isinstance(stop_ev.get("folded"), bool) else None
                if temps:
                    prev["temp_c"] = round(float(max(temps)), 1)
                if curs:
                    prev["current_ma"] = round(float(max(curs)), 1)
                prev.update({"updated_at": task["completed_at"], "source": "task_complete", "last_task_id": task_id})
                app.state.arm_live_states[arm_id] = prev
            _enrich_task_health(task)
            if phase == "ABORTED":
                hw_err, rcpt_why = str(((task.get("hardware_telemetry") or {}).get("error") or "")), str(((task.get("receipt") or {}).get("reason") or ""))
                if "FOLD_READBACK_MISSING" not in (hw_err, rcpt_why):
                    pipeline_repark.on_abort(app.state, task, body.get("stage_result") or {}, time.time(), rules=rules())
            elif phase == "RELEASED":
                pending_events = build_completion_events(app, task, cell_phase=cell_phase, stage_result=body.get("stage_result") or {},
                                                         human_detected=bool(_is_human_detected(cell_id)))
                if pending_events:
                    task["pending_port_events"] = pending_events
            if callable(_commit_ledger):
                _commit_ledger(bump_dispatch=(phase == "RELEASED"), bump_stop=(phase == "ABORTED"))
            else:
                _save_ledger()
                if gov is not None and phase == "ABORTED":
                    gov.bump_stop_generation()
                elif gov is not None and phase == "RELEASED":
                    gov.bump_dispatch_generation()
        except Exception:
            app.state.omx_cell_states.pop(cell_id, None) if prev_cell is _missing else app.state.omx_cell_states.__setitem__(cell_id, prev_cell)
            task.clear(); task.update(prev_task)
            if arm_id and isinstance(getattr(app.state, "arm_live_states", None), dict):
                app.state.arm_live_states.pop(arm_id, None) if prev_arm is _missing else app.state.arm_live_states.__setitem__(arm_id, prev_arm)
            if prev_repark is _missing:
                if hasattr(app.state, "repark_requests"):
                    delattr(app.state, "repark_requests")
            else:
                app.state.repark_requests = prev_repark
            if prev_events is _missing:
                if hasattr(app.state, "cell_auto_events"):
                    delattr(app.state, "cell_auto_events")
            else:
                app.state.cell_auto_events = prev_events
            if callable(_commit_ledger) and not getattr(app.state, "_pipeline_ledger_fault", False):
                with suppress(Exception):
                    _commit_ledger(commit=False)
            raise
        flushed = 0
        if task.get("pending_port_events"):
            try:
                flushed = await flush_pending_port_events_async(app)
            except Exception:
                flushed = 0
        if flushed:
            _save_ledger()
        return {"ok": True, "task": strip_task_for_claim(task), "gate": res["gate"]}

    @app.post("/api/fleet/pipeline/evaluate", dependencies=read_guard)
    async def pipeline_evaluate(request: Request):
        active = active_map()
        body = await request.json()
        body_robots = body.get("robots", [])
        robots = [type("PipelineRobot", (), {
            "robot_id": row["robot_id"], "kind": row.get("kind"), "online": row.get("online", True),
            "percent": row.get("percent"), "voltage": row.get("voltage"),
            "pose": (row["x"], row["y"]), "yaw": row.get("yaw"),
            "on_trip": row.get("on_trip", False),
        })() for row in body_robots]
        bays = bays_from_map(active[1])
        active_rules = rules()
        if body.get("order") is not None or body.get("exit_place") is not None:
            rule_body = active_rules.body() if active_rules is not None else SiteRules().body()
            if body.get("order") is not None:
                if body["order"] not in ("exit_nearest", "fair"):
                    raise HTTPException(422, detail={"code": "INVALID_ORDER"})
                rule_body["departure"]["order"] = body["order"]
            if body.get("exit_place") is not None:
                if body["exit_place"] not in {place.id for place in active[1].places}:
                    raise HTTPException(422, detail={"code": "INVALID_EXIT_PLACE"})
                rule_body["return"]["exit_place"] = body["exit_place"]
            active_rules = SiteRules.model_validate(rule_body)
        charge_bays = None
        if any(row.get("percent") is not None or row.get("voltage") is not None for row in body_robots):
            charge_bays = ChargeBays(
                rate_pct_per_min=15.0,
                thresholds=(lambda: (active_rules.return_.go_percent, active_rules.return_.leave_percent))
                if active_rules is not None else lambda: (15.0, 80.0))
            seed_t0 = [type("PipelineRobot", (), {
                "robot_id": r.robot_id, "kind": r.kind, "online": r.online,
                "percent": min(50.0, float(r.percent)) if r.percent is not None else 50.0,
                "voltage": 7.40, "pose": r.pose, "yaw": r.yaw, "on_trip": r.on_trip,
            })() for r in robots]
            seed_t1 = [type("PipelineRobot", (), {
                "robot_id": r.robot_id, "kind": r.kind, "online": r.online,
                "percent": min(50.0, float(r.percent)) if r.percent is not None else 50.0,
                "voltage": r.voltage if r.voltage is not None else 7.50,
                "pose": r.pose, "yaw": r.yaw, "on_trip": r.on_trip,
            })() for r in robots]
            charge_bays.observe(0.0, seed_t0, bays)
            charge_bays.observe(1.0, seed_t1, bays)
            charge_bays.observe(300.0 if any((r.percent or 0) >= 80.0 for r in robots) else 2.0, robots, bays)
        goals = {
            row["robot_id"]: tuple(row["goal"]) if isinstance(row["goal"], list) else row["goal"]
            for row in body_robots if row.get("goal") is not None
        }
        result = evaluate_fleet_pipeline(active[1], active[2], robots, bays, charge_bays=charge_bays,
                                         site_rules=active_rules, goals_by_robot=goals,
                                         cell_states={**getattr(app.state, "omx_cell_states", {}),
                                                      **(body.get("cell_states") or {})})
        return {**result, "dispatch": False}
