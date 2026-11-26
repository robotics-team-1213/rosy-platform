"""Guarded LLM/VLA recovery tool HTTP endpoints, CAS/idempotency/role enforcement & bounded dispatch."""
from __future__ import annotations

from contextlib import suppress
import copy
import json
import time
import uuid

from fastapi import HTTPException, Request
from pydantic import ValidationError

from core_common.protocol.cell_failure_context import canonical_sha256
from core_common.protocol.pipeline_recovery_tools import (
    MAX_ACT_FALLBACK_CHUNKS,
    MAX_INVOKE_BODY_BYTES,
    MAX_RECOVERIES_PER_ROOT,
    MAX_SAFE_HOME_PER_ARM_24H,
    RECOVERY_TOOLS_SCHEMA,
    RecoveryToolInvokeRequest,
    VisualCheckpointArgs,
)
from fleet.server.pipeline_port_events import TASK_IDENTITY_FIELDS
from fleet.server.sitemap import pipeline_auto_events, pipeline_pinky_dispatch, pipeline_repark
from fleet.server.pipeline_recovery_policy import (
    ARM_CELL,
    arm_folded_fresh,
    collect_unresolved_failures,
    effective_stop_fence,
    evaluate_visual_checkpoint,
)


def clear_label(body: dict, key: str) -> str | None:
    """An optional clear label from the operator: only a non-empty string of at most 64 chars passes."""
    value = body.get(key)
    return value if isinstance(value, str) and value.strip() and len(value) <= 64 else None


def arm_incident_sources(app, arm: str) -> list[str]:
    """Observation source_id candidates for a pipeline arm; incidents are keyed by source_id (D-971)."""
    candidates = [f"omx_{arm}", arm]  # fallback: the OMX naming the cell control PCs report under
    obs = getattr(app.state, "workcell_observations_service", None)
    snapshot = getattr(obs, "snapshot", None)
    if not callable(snapshot):
        return candidates
    try:
        cells = snapshot().get("workcells") or []
    except Exception:
        return candidates
    matched = [entry["source_id"] for cell in cells for entry in cell.get("arms") or ()
               if entry.get("arm_id") == arm
               or str(entry.get("arm_id") or "").removesuffix("_follower") == arm
               or entry.get("source_id") in (arm, f"omx_{arm}")]
    return matched + [c for c in candidates if c not in matched]


def clear_open_arm_incidents(app, arms: list[str], note: str, principal_id: str, cause: str, basis: str) -> None:
    """Clearing the Fleet arm hold also clears that arm's open incident rows in the shared D-971 store."""
    incidents = getattr(app.state, "arm_incidents", None)
    if incidents is None:
        return
    for arm in arms:
        for source_id in arm_incident_sources(app, arm):
            hold = incidents.hold(source_id)
            if not hold.held:
                continue
            for incident_id in hold.incident_ids:
                try:  # already cleared or not this arm's row: the first record stands
                    incidents.clear(source_id, incident_id, note, principal_id, cause=cause, basis=basis)
                except (KeyError, ValueError):
                    pass


def policy_spec() -> dict:
    return {
        "schema": RECOVERY_TOOLS_SCHEMA,
        "state_machine": ["HELD", "READY", "HUMAN_REQUIRED", "EXECUTING", "VERIFYING", "RECOVERED"],
        "homing_state_machine": [
            "IDLE", "EXECUTING_RELEASE_AND_LIFT", "RUNNING_RELEASE_AND_LIFT", "AWAITING_LIFT_VISUAL_VERIFY",
            "AFTER_LIFT_VISUAL_CLEAR", "DIRECT_PARK_VISUAL_CLEAR", "EXECUTING_GUARDED_SLOW_PARK",
            "RUNNING_GUARDED_SLOW_PARK", "AWAITING_PARK_VISUAL_VERIFY", "AFTER_PARK_VISUAL_FOLDED",
            "HOLD_VISUAL_BLOCKED", "HOLD_GUARD_TRIPPED",
        ],
        "caps": {
            "safe_fold_home_per_strategy_root": MAX_RECOVERIES_PER_ROOT,
            "safe_fold_home_per_arm_24h": MAX_SAFE_HOME_PER_ARM_24H,
            "displaced_recovery_per_root": MAX_RECOVERIES_PER_ROOT,
            "repark_per_root": pipeline_repark.MAX_REPARK,
            "vla_act_fallback_per_root": MAX_RECOVERIES_PER_ROOT,
            "pinky_reroute_per_root": MAX_RECOVERIES_PER_ROOT,
            "vla_act_max_chunks": MAX_ACT_FALLBACK_CHUNKS,
        },
        "forbidden_rules": [
            "no_raw_joint_pwm_torque_pose_eeprom_url_fifo", "no_torque_drop_while_extended_D1048",
            "no_auto_clear_human_hold_estop_or_aborted", "no_repick_on_fold_readback_missing",
            "no_park_without_advancing_visual_clear_checkpoint",
            "no_act_or_displaced_execution_without_presence_confirm_D911",
        ],
    }


def build_tool_catalog() -> list[dict]:
    return [
        {"name": "inspect_failure_context", "tier": "A", "effect_class": "read_only",
         "description": "미해결 실패·카메라 신선도·호밍 단계(CAS sha256·veto·예산) 조회",
         "inputSchema": {"type": "object", "additionalProperties": False,
                         "properties": {"cell_id": {"type": ["string", "null"], "enum": ["cell_s", "cell_ab", None]},
                                        "root_task_id": {"type": ["string", "null"]}}}},
        {"name": "safe_fold_home", "tier": "B", "effect_class": "guarded_enqueue", "cap_per_root": MAX_RECOVERIES_PER_ROOT,
         "description": "D-1048 세션 래퍼 기반 상황별 가드 호밍(auto_fold / release_and_lift / guarded_slow_park / finalize_home_verify)",
         "inputSchema": {"type": "object", "additionalProperties": False,
                         "properties": {"arm_id": {"type": ["string", "null"], "enum": ["arm_s", "arm_a", "arm_b", None]},
                                        "strategy": {"type": "string", "enum": ["auto_fold", "release_and_lift", "guarded_slow_park", "finalize_home_verify"]}}}},
        {"name": "record_visual_checkpoint", "tier": "A", "effect_class": "checkpoint_gate",
         "description": "카메라 신선도·모션 이후 단조 프레임 시퀀스 바인딩 시각 판정 기록",
         "inputSchema": {"type": "object", "additionalProperties": False,
                         "required": ["stage", "verdict", "cargo_detached", "overhead_clear", "cameras_checked", "observation_summary"],
                         "properties": {"arm_id": {"type": ["string", "null"], "enum": ["arm_s", "arm_a", "arm_b", None]},
                                        "stage": {"type": "string", "enum": ["pre_park", "after_lift", "after_park"]},
                                        "verdict": {"type": "string", "enum": ["CLEAR", "FOLDED_HOME", "OBSTRUCTED", "UNCERTAIN"]},
                                        "cargo_detached": {"type": "boolean"}, "gripper_open": {"type": ["boolean", "null"]},
                                        "overhead_clear": {"type": "boolean"},
                                        "cameras_checked": {"type": "object", "additionalProperties": {"type": "integer", "minimum": 0}},
                                        "observation_summary": {"type": "string", "minLength": 1, "maxLength": 240}}}},
        {"name": "enqueue_displaced_recovery", "tier": "B", "effect_class": "guarded_enqueue", "cap_per_root": MAX_RECOVERIES_PER_ROOT,
         "requires_presence_confirm": True,
         "description": "cell_s 이탈(belt_far/floor_front) 보정 복구 태스크 큐 등록(D-911 입회 확인 필수)",
         "inputSchema": {"type": "object", "additionalProperties": False, "required": ["site"],
                         "properties": {"site": {"type": "string", "enum": ["belt_far", "floor_front"]},
                                        "robot_id": {"type": ["string", "null"]}}}},
        {"name": "request_repark", "tier": "B", "effect_class": "guarded_enqueue", "cap_per_root": pipeline_repark.MAX_REPARK,
         "description": "실측 reach_fix 기반 제한 재정차 요청(MAX_REPARK=2)",
         "inputSchema": {"type": "object", "additionalProperties": False, "properties": {"task_id": {"type": ["string", "null"]}}}},
        {"name": "enqueue_vla_act_fallback", "tier": "C", "effect_class": "guarded_enqueue", "cap_per_root": MAX_RECOVERIES_PER_ROOT,
         "requires_presence_confirm": True,
         "description": "ACT/VLA 폴백(vla_shadow=무동작 제안, act=D-911 입회 확인 후 실행)",
         "inputSchema": {"type": "object", "additionalProperties": False,
                         "properties": {"mode": {"type": "string", "enum": ["act", "vla_shadow"]},
                                        "max_chunks": {"type": "integer", "minimum": 1, "maximum": MAX_ACT_FALLBACK_CHUNKS},
                                        "robot_id": {"type": ["string", "null"]}, "note": {"type": ["string", "null"]}}}},
        {"name": "dispatch_pinky_reroute", "tier": "B", "effect_class": "guarded_enqueue", "cap_per_root": MAX_RECOVERIES_PER_ROOT,
         "description": "Pinky 실패 시 기존 dispatch 안전 게이트를 통과하는 재경로 1회 큐잉",
         "inputSchema": {"type": "object", "additionalProperties": False, "required": ["target_place"],
                         "properties": {"target_place": {"type": "string", "minLength": 1, "maxLength": 96},
                                        "robot_id": {"type": ["string", "null"]}}}},
        {"name": "escalate_human", "tier": "C", "effect_class": "candidate_writing", "cap_per_root": 1,
         "description": "동일 루트 실패를 사람 검토 티켓으로 에스컬레이션(중복 제거)",
         "inputSchema": {"type": "object", "additionalProperties": False, "properties": {"summary": {"type": ["string", "null"]}}}},
    ]

_LEDGER_LIMIT = 100
_IDEMPOTENCY_LIMIT = 500
_STATE_ATTRS = (
    "pipeline_recovery_ledger", "pipeline_recovery_budgets", "pipeline_recovery_idempotency",
    "pipeline_homing_sessions", "pending_safe_home_arms", "safe_home_history",
    "pipeline_recovery_escalations", "repark_requests", "pinky_tasks", "omx_cell_tasks", "cell_auto_events",
)


def _append_audit(state, row: dict) -> None:
    ledger = getattr(state, "pipeline_recovery_ledger", None)
    if ledger is None:
        ledger = state.pipeline_recovery_ledger = []
    ledger.append(row)
    if len(ledger) > _LEDGER_LIMIT:
        del ledger[:-_LEDGER_LIMIT]


def _record_idempotency(state, idem_key: str, req_hash: str, resp: dict, now: float, *, http_status: int = 200) -> None:
    store = getattr(state, "pipeline_recovery_idempotency", None)
    if store is None:
        store = state.pipeline_recovery_idempotency = {}
    store[idem_key] = {"req_hash": req_hash, "http_status": http_status, "response": resp, "at": round(now, 3)}
    if len(store) > _IDEMPOTENCY_LIMIT:
        for oldest in list(store.keys())[:len(store) - _IDEMPOTENCY_LIMIT]:
            store.pop(oldest, None)


def _safe_errors(exc: ValidationError) -> list[dict]:
    return [{"loc": [str(x) for x in err.get("loc", ())], "msg": str(err.get("msg", "")),
             "type": str(err.get("type", ""))} for err in exc.errors()[:4]]


def _optional_active(ctx):
    try:
        return ctx.active_map()
    except HTTPException:
        return None


def _save_or_rollback(state, ctx, snap: dict[str, object], *, bump_dispatch: bool = False) -> None:
    commit_ledger = getattr(ctx, "_commit_ledger", None)
    if callable(commit_ledger):
        try:
            commit_ledger(bump_dispatch=bump_dispatch)
        except Exception:
            for attr, val in snap.items():
                setattr(state, attr, val)
            if not getattr(state, "_pipeline_ledger_fault", False):
                with suppress(Exception):
                    commit_ledger(commit=False)
            raise
        return
    saved = False
    try:
        ctx._save_ledger()
        saved = True
        gov = getattr(ctx, "gov", None) or getattr(state, "pipeline_governance", None)
        if bump_dispatch and gov is not None:
            gov.bump_dispatch_generation()
    except Exception:
        for attr, val in snap.items():
            setattr(state, attr, val)
        if saved:
            with suppress(Exception):
                ctx._save_ledger()
        raise


def install_recovery_tool_routes(app, ctx) -> None:
    for attr, default in (
        ("pipeline_recovery_ledger", []),
        ("pipeline_recovery_budgets", {}),
        ("pipeline_recovery_idempotency", {}),
        ("pipeline_homing_sessions", {}),
        ("pending_safe_home_arms", {}),
        ("safe_home_history", {}),
        ("pipeline_recovery_escalations", {}),
    ):
        if getattr(app.state, attr, None) is None:
            setattr(app.state, attr, default)

    @app.get("/api/fleet/pipeline/recovery-tools", dependencies=ctx.read_guard)
    async def get_recovery_tools():
        now = time.time()
        active = _optional_active(ctx)
        fence_held, _fence_gen = effective_stop_fence(app.state)
        failures = collect_unresolved_failures(
            app.state, now, human_detected=bool(ctx._is_human_detected() or fence_held),
            active=active, dispatch_enabled=pipeline_pinky_dispatch.enabled(),
        )
        return {
            "schema": RECOVERY_TOOLS_SCHEMA, "policy": policy_spec(), "tools": build_tool_catalog(),
            "active_failures": failures, "homing_sessions": dict(app.state.pipeline_homing_sessions),
            "recent_invocations": list(app.state.pipeline_recovery_ledger[-20:]),
        }

    @app.post("/api/fleet/pipeline/recovery-tools/invoke", dependencies=ctx.proposer_guard)
    async def invoke_recovery_tool(request: Request):
        raw_bytes = await request.body()
        if len(raw_bytes) > MAX_INVOKE_BODY_BYTES:
            raise HTTPException(413, detail={"code": "PAYLOAD_TOO_LARGE", "limit": MAX_INVOKE_BODY_BYTES})
        try:
            raw_body = json.loads(raw_bytes.decode("utf-8"))
        except Exception:
            raise HTTPException(422, detail={"code": "INVALID_JSON"}) from None
        try:
            req = RecoveryToolInvokeRequest.model_validate(raw_body)
        except ValidationError as exc:
            msg = str(exc)
            code = ("PAYLOAD_TOO_DEEP" if "PAYLOAD_TOO_DEEP" in msg
                    else "FORBIDDEN_RAW_COMMAND_KEY" if "FORBIDDEN_RAW_COMMAND_KEY" in msg
                    else "INVALID_RECOVERY_TOOL_REQUEST")
            raise HTTPException(422, detail={"code": code, "errors": _safe_errors(exc)}) from None
        if getattr(app.state, "_pipeline_ledger_fault", False):
            raise HTTPException(503, detail={"code": "PIPELINE_LEDGER_UNAVAILABLE"})

        now = time.time()
        principal_obj = getattr(request.state, "site_principal", None)
        principal = getattr(principal_obj, "principal_id", None)
        actor_role = getattr(principal_obj, "role", None)
        if principal_obj is not None and actor_role != "operator" and req.caller_kind == "operator":
            raise HTTPException(403, detail={"code": "CALLER_KIND_ROLE_MISMATCH"})

        idem_key = f"{principal or 'anonymous'}:{req.request_id}"
        req_hash = canonical_sha256({
            "tool_name": req.tool_name, "arguments": req.arguments, "caller_kind": req.caller_kind,
            "root_task_id": req.root_task_id, "expected_context_sha256": req.expected_context_sha256,
        })
        prev = app.state.pipeline_recovery_idempotency.get(idem_key)
        if prev is not None:
            if prev.get("req_hash") != req_hash:
                raise HTTPException(409, detail={"code": "IDEMPOTENCY_CONFLICT"})
            status_code = int(prev.get("http_status", 200))
            if status_code >= 400:
                raise HTTPException(status_code, detail={**prev["response"], "idempotent_replay": True})
            return {**prev["response"], "idempotent_replay": True}

        active = _optional_active(ctx)
        fence_held, fence_gen = effective_stop_fence(app.state)
        failures = collect_unresolved_failures(
            app.state, now, human_detected=bool(ctx._is_human_detected() or fence_held),
            active=active, dispatch_enabled=pipeline_pinky_dispatch.enabled(),
        )
        snap = {attr: copy.deepcopy(getattr(app.state, attr, None)) for attr in _STATE_ATTRS}

        if req.tool_name == "inspect_failure_context":
            matched = [f for f in failures if (not req.arguments.get("cell_id") or f["cell_id"] == req.arguments["cell_id"])
                       and (not (req.arguments.get("root_task_id") or req.root_task_id)
                            or f["root_task_id"] == (req.arguments.get("root_task_id") or req.root_task_id))]
            inv_id = f"rec-{uuid.uuid4().hex[:8]}"
            resp = {"ok": True, "invocation_id": inv_id, "request_id": req.request_id,
                    "tool_name": req.tool_name, "status": "EXECUTED", "result": {"failures": matched}}
            _record_idempotency(app.state, idem_key, req_hash, resp, now, http_status=200)
            _append_audit(app.state, {"invocation_id": inv_id, "request_id": req.request_id, "tool_name": req.tool_name,
                                      "caller_kind": req.caller_kind, "actor": principal, "actor_role": actor_role,
                                      "status": "EXECUTED", "at": round(now, 3)})
            _save_or_rollback(app.state, ctx, snap)
            return resp

        def _refuse(http_status: int, code: str, *, root: str | None = req.root_task_id, detail: dict | None = None):
            resp_err = {"code": code, **(detail or {})}
            audit = {"invocation_id": f"rec-{uuid.uuid4().hex[:8]}", "request_id": req.request_id,
                     "tool_name": req.tool_name, "caller_kind": req.caller_kind, "actor": principal,
                     "actor_role": actor_role, "root_task_id": root, "status": "REFUSED", "reason": code, "at": round(now, 3)}
            _record_idempotency(app.state, idem_key, req_hash, resp_err, now, http_status=http_status)
            _append_audit(app.state, audit)
            _save_or_rollback(app.state, ctx, snap)
            raise HTTPException(http_status, detail=resp_err)

        if not req.root_task_id:
            _refuse(422, "ROOT_TASK_ID_REQUIRED")
        if fence_gen is None and req.tool_name != "escalate_human":
            _refuse(409, "STOP_AUTHORITY_UNAVAILABLE")
        failure = next((f for f in failures if f["root_task_id"] == req.root_task_id), None)
        if failure is None:
            _refuse(404, "UNKNOWN_FAILURE_CONTEXT")
        if not req.expected_context_sha256 or req.expected_context_sha256 != failure["context_sha256"]:
            _refuse(409, "STALE_FAILURE_CONTEXT", detail={"expected": failure["context_sha256"]})

        if req.tool_name == "escalate_human":
            existing = app.state.pipeline_recovery_escalations.get(req.root_task_id)
            if existing is None:
                existing = {
                    "ticket_id": f"esc-{uuid.uuid4().hex[:8]}", "root_task_id": req.root_task_id,
                    "cell_id": failure.get("cell_id"), "arm_id": failure.get("arm_id"),
                    "robot_id": failure.get("robot_id"), "trigger_code": failure.get("trigger_code"),
                    "summary": req.arguments.get("summary") or req.rationale, "actor": principal, "at": round(now, 3),
                }
                app.state.pipeline_recovery_escalations[req.root_task_id] = existing
                pipeline_auto_events.add(app.state, [{
                    "kind": "recovery_escalation", "arm": existing["arm_id"], "robot_id": existing["robot_id"],
                    "batch_id": existing["ticket_id"], "result": "escalated", "why": existing["trigger_code"],
                    "person_needed": True, "t": now,
                }], "fleet")
            inv_id = f"rec-{uuid.uuid4().hex[:8]}"
            resp = {"ok": True, "invocation_id": inv_id, "request_id": req.request_id,
                    "tool_name": req.tool_name, "status": "EXECUTED", "result": {"ticket": existing}}
            _record_idempotency(app.state, idem_key, req_hash, resp, now, http_status=200)
            _append_audit(app.state, {"invocation_id": inv_id, "request_id": req.request_id, "tool_name": req.tool_name,
                                      "caller_kind": req.caller_kind, "actor": principal, "actor_role": actor_role,
                                      "root_task_id": req.root_task_id, "status": "EXECUTED", "at": round(now, 3)})
            _save_or_rollback(app.state, ctx, snap)
            return resp

        if ctx._is_human_detected() or fence_held or any((s or {}).get("phase") == "HUMAN_HOLD" for s in app.state.omx_cell_states.values()):
            _refuse(409, "HUMAN_HOLD_ACTIVE")
        gate = failure["eligible_tools"].get(req.tool_name) or {}
        if not gate.get("allowed"):
            _refuse(409, gate.get("reason") or "RECOVERY_TOOL_NOT_ELIGIBLE", detail={"vetoes": failure["vetoes"]})

        req_arm = req.arguments.get("arm_id")
        if req_arm is not None and req_arm != failure.get("arm_id"):
            _refuse(409, "TARGET_MISMATCH_AFTER_CAS", detail={"field": "arm_id", "expected": failure.get("arm_id")})
        req_rid = req.arguments.get("robot_id")
        if req_rid is not None and req_rid != failure.get("robot_id"):
            _refuse(409, "TARGET_MISMATCH_AFTER_CAS", detail={"field": "robot_id", "expected": failure.get("robot_id")})
        req_tid = req.arguments.get("task_id")
        if req_tid is not None and req_tid != failure.get("task_id"):
            _refuse(409, "TARGET_MISMATCH_AFTER_CAS", detail={"field": "task_id", "expected": failure.get("task_id")})

        budgets = app.state.pipeline_recovery_budgets.setdefault(req.root_task_id, {})
        result: dict = {}
        bump_dispatch = False
        if req.tool_name == "safe_fold_home":
            strategy = req.arguments.get("strategy", "auto_fold")
            target_arm = failure["arm_id"]
            if not target_arm or ARM_CELL.get(target_arm) != failure["cell_id"]:
                _refuse(422, "INVALID_ARM_FOR_FAILURE")
            sgate = (failure.get("homing_strategies") or {}).get(strategy) or {}
            if not sgate.get("allowed"):
                _refuse(409, sgate.get("reason") or "HOMING_STRATEGY_NOT_ELIGIBLE")
            if strategy == "finalize_home_verify":
                result = {"arm_id": target_arm, "strategy": strategy, "action": "READY_FOR_OPERATOR_HOLD_CLEAR", "folded": True}
            elif strategy == "auto_fold" and not failure.get("incident_id") and arm_folded_fresh(app.state, target_arm, now):
                result = {"arm_id": target_arm, "strategy": strategy, "action": "ALREADY_FOLDED_READBACK"}
            else:
                budgets[f"safe_fold_home:{strategy}"] = budgets.get(f"safe_fold_home:{strategy}", 0) + 1
                hist = [ts for ts in app.state.safe_home_history.get(target_arm, []) if now - ts < 86400.0]
                hist.append(now)
                app.state.safe_home_history[target_arm] = hist
                sess = dict(app.state.pipeline_homing_sessions.get(req.root_task_id) or {"root_task_id": req.root_task_id, "arm_id": target_arm})
                vis_at = sess.get("visual_clear_at")
                exp_at = min(now + 60.0, float(vis_at) + 60.0) if (strategy == "guarded_slow_park" and isinstance(vis_at, (int, float))) else (now + 60.0)
                req_row = {"request_id": req.request_id, "root_task_id": req.root_task_id, "arm_id": target_arm,
                           "strategy": strategy, "expires_at": round(exp_at, 3),
                           "stop_generation": fence_gen,
                           "requested_by": principal, "caller_kind": req.caller_kind, "requested_at": round(now, 3)}
                if failure.get("incident_id"):
                    req_row["incident_id"] = failure["incident_id"]
                app.state.pending_safe_home_arms[target_arm] = req_row
                sess.update({"arm_id": target_arm, "stage": f"EXECUTING_{strategy.upper()}", "active_request_id": req.request_id,
                             "updated_at": round(now, 3)})
                app.state.pipeline_homing_sessions[req.root_task_id] = sess
                result = {"arm_id": target_arm, "strategy": strategy, "action": "QUEUED_D1048_SAFE_FOLD", "pending": req_row}
        elif req.tool_name == "record_visual_checkpoint":
            ok_vis, err_vis, vis_detail = evaluate_visual_checkpoint(app.state, failure, VisualCheckpointArgs(**req.arguments), now)
            if not ok_vis:
                _refuse(409, err_vis or "VISUAL_CHECKPOINT_REJECTED", detail=vis_detail)
            result = {"action": "VISUAL_CHECKPOINT_RECORDED", **vis_detail}
        elif req.tool_name == "enqueue_displaced_recovery":
            if principal_obj is not None and actor_role != "operator":
                _refuse(403, "OPERATOR_APPROVAL_REQUIRED_FOR_FALLBACK_ENQUEUE")
            site = req.arguments["site"]
            spec = {**ctx.CELL_TASK_PRESETS[f"s3_recover_{site}"], "fallback_from_task_id": req.root_task_id,
                    "fallback_chain_depth": int(failure["fallback_chain_depth"]) + 1, "requires_presence_confirm": True,
                    **({"robot_id": failure["robot_id"]} if failure.get("robot_id") else {})}
            task = ctx._enqueue_one_task(ctx.active_map(), spec, principal_id=principal, principal_role=actor_role, save=False)
            bump_dispatch = task.get("status") == "QUEUED"
            budgets["enqueue_displaced_recovery"] = budgets.get("enqueue_displaced_recovery", 0) + 1
            result = {"action": "ENQUEUED_DISPLACED_RECOVERY", "requires_presence_confirm": True, "task": task}
        elif req.tool_name == "request_repark":
            orig = app.state.omx_cell_tasks.get(failure.get("task_id") or "")
            if orig is None:
                _refuse(409, "NO_REACH_FIX")
            req_rp = pipeline_repark.on_abort(app.state, orig, orig.get("stage_result") or {}, now, rules=ctx.rules())
            if req_rp is None:
                _refuse(409, "REPARK_NOT_AVAILABLE")
            result = {"action": "REPARK_REQUESTED", "repark_request": req_rp}
        elif req.tool_name == "enqueue_vla_act_fallback":
            mode = req.arguments.get("mode", "act")
            if mode == "vla_shadow":
                budgets["enqueue_vla_act_fallback"] = budgets.get("enqueue_vla_act_fallback", 0) + 1
                result = {"action": "VLA_SHADOW_PROPOSAL_RECORDED", "vla_executed": False, "execution_authorized": False,
                          "note": req.arguments.get("note") or req.rationale}
            else:
                if principal_obj is not None and actor_role != "operator":
                    _refuse(403, "OPERATOR_APPROVAL_REQUIRED_FOR_FALLBACK_ENQUEUE")
                orig = app.state.omx_cell_tasks[failure["task_id"]]
                spec = {k: orig[k] for k in ("cell_id", "arm_id", "robot_id", "robot_kind", "src_site", "dst_site",
                                             "tier", "col", "row", "tier_hint", "zone_id", "cable_guard_micro",
                                             "unload_batch_id", "unload_index", "unload_expected", *TASK_IDENTITY_FIELDS)
                        if k in orig}
                spec.update(execution_mode="act_policy", max_chunks=req.arguments.get("max_chunks", 2),
                            fallback_from_task_id=req.root_task_id, requires_presence_confirm=True,
                            fallback_chain_depth=int(failure["fallback_chain_depth"]) + 1)
                task = ctx._enqueue_one_task(ctx.active_map(), spec, principal_id=principal, principal_role=actor_role, save=False)
                bump_dispatch = task.get("status") == "QUEUED"
                budgets["enqueue_vla_act_fallback"] = budgets.get("enqueue_vla_act_fallback", 0) + 1
                result = {"action": "ENQUEUED_ACT_FALLBACK_REQUIRES_PRESENCE", "requires_presence_confirm": True, "task": task}
        elif req.tool_name == "dispatch_pinky_reroute":
            if active is None:
                _refuse(404, "NO_ACTIVE_MAP")
            if getattr(app.state, "trip_requester_guards", None) and not pipeline_pinky_dispatch.requester_named(app.state, principal_obj):
                _refuse(403, "REQUESTER_NOT_NAMED")
            place = req.arguments["target_place"]
            if place not in active[2].places:
                _refuse(422, "PLACE_NOT_ON_MAP")
            rid = failure.get("robot_id")
            if not rid:
                _refuse(422, "ROBOT_ID_REQUIRED")
            cell_why = pipeline_pinky_dispatch._cell_refusal(app.state, place, rid)
            if cell_why:
                _refuse(409, cell_why)
            budgets["dispatch_pinky_reroute"] = budgets.get("dispatch_pinky_reroute", 0) + 1
            pid = f"pinky-reroute-{uuid.uuid4().hex[:6]}"
            ptask = {
                "task_id": pid, "robot_id": rid, "action": "recovery_reroute",
                "target_place": place, "status": "QUEUED", "fallback_from_task_id": req.root_task_id,
                "created_at": round(now, 3), **pipeline_pinky_dispatch.dispatch_fields(active, request, place),
            }
            app.state.pinky_tasks[pid] = ptask
            result = {"action": "PINKY_REROUTE_QUEUED", "pinky_task": ptask}

        inv_id = f"rec-{uuid.uuid4().hex[:8]}"
        audit = {"invocation_id": inv_id, "request_id": req.request_id, "tool_name": req.tool_name,
                 "caller_kind": req.caller_kind, "actor": principal, "actor_role": actor_role,
                 "root_task_id": req.root_task_id, "status": "EXECUTED", "result_action": result.get("action"), "at": round(now, 3)}
        resp = {"ok": True, "invocation_id": inv_id, "request_id": req.request_id, "tool_name": req.tool_name,
                "status": "EXECUTED", "result": result, "audit_record": audit}
        _record_idempotency(app.state, idem_key, req_hash, resp, now, http_status=200)
        _append_audit(app.state, audit)
        _save_or_rollback(app.state, ctx, snap, bump_dispatch=bump_dispatch)
        return resp
