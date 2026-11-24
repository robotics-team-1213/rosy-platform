"""Dual-mode Fleet cell-plan HTTP routes (/api/fleet/pipeline/cell-plans*)."""
from __future__ import annotations

from contextlib import nullcontext
import time
import uuid
from typing import Any

from fastapi import HTTPException, Request
from pydantic import ValidationError as PydanticValidationError

from core_common.protocol.cell_plans import (
    CELL_PLAN_SCHEMA,
    CellPlanCancelRequest,
    CellPlanCancelResponse,
    CellPlanDryRunResponse,
    CellPlanResponse,
    CellPlanSummaryOut,
)
from fleet.pipeline import resolve_omx_cells
from fleet.pipeline.cell_plan_planner import plan_cell_moves
from fleet.pipeline.cell_site_targets import resolve_cell_task_targets
from fleet.server.pipeline_port_events import task_view_for_request
from .pipeline_governance_store import (
    canonical_digest, prepare_task_governance, safe_canonical_digest, scoped_idempotency_key, validate_request_key,
)
from fleet.server.sitemap.pipeline_routes import _enrich_task_health
from fleet.server.sitemap.pipeline_task_input import checked_json_value, checked_task_pose

_SCHEMA = CELL_PLAN_SCHEMA


def _aggregate_plan_status(tasks: list[dict[str, Any]]) -> str:
    statuses = [t.get("status") for t in tasks]
    if not statuses:
        return "ABORTED"
    if any(s == "ABORTED" for s in statuses):
        return "ABORTED"
    if any(s == "CANCELLED" for s in statuses):
        return "CANCELLED"
    if any(s == "PAUSED_HUMAN" for s in statuses):
        return "PAUSED_HUMAN"
    if any(s == "RUNNING" for s in statuses):
        return "RUNNING"
    if all(s == "COMPLETED" for s in statuses):
        return "COMPLETED"
    if all(s in ("QUEUED", "COMPLETED") for s in statuses):
        return "QUEUED"
    if any(s in ("QUEUED", "COMPLETED") for s in statuses):
        return "PARTIALLY_ADMITTED"
    return "PROPOSED"


def install_cell_plan_routes(app, ctx) -> None:
    read_guard = ctx.read_guard
    proposer_guard = getattr(ctx, "proposer_guard", ctx.operator_guard)
    gov = getattr(ctx, "gov", None) or getattr(app.state, "pipeline_governance", None)
    active_map = ctx.active_map
    _save_ledger = ctx._save_ledger
    _is_human_detected = ctx._is_human_detected
    _arm_live_catalog = ctx._arm_live_catalog
    _evaluate_decision = ctx._evaluate_decision
    app.state.omx_cell_plans = getattr(app.state, "omx_cell_plans", None) or {}

    def _enriched_plan_task(tid: str, request: Request | None = None) -> dict[str, Any]:
        raw_task = _enrich_task_health(app.state.omx_cell_tasks[tid])
        refusals = getattr(app.state, "cell_task_refusals", None) or {}
        if tid in refusals and refusals[tid] is not None:
            raw_task = {**raw_task, "last_refusal": refusals[tid]}
        return task_view_for_request(raw_task, request) if request is not None else raw_task

    def _plan_view(plan_id: str, request: Request | None = None) -> dict[str, Any]:
        rec = app.state.omx_cell_plans[plan_id]
        raw_tasks = [
            _enrich_task_health(app.state.omx_cell_tasks[tid])
            for tid in rec["task_ids"] if tid in app.state.omx_cell_tasks
        ]
        completed = sum(1 for t in raw_tasks if t.get("status") == "COMPLETED")
        status = _aggregate_plan_status(raw_tasks)
        refusals = getattr(app.state, "cell_task_refusals", None) or {}
        cell_state = (getattr(app.state, "omx_cell_states", None) or {}).get(rec["cell_id"])
        cell_phase = cell_state.get("cell_phase") if isinstance(cell_state, dict) else None
        hold_reason: str | None = None
        for t in raw_tasks:
            for field in ("cancel_reason", "abort_reason"):
                if isinstance(t.get(field), str) and t[field].strip():
                    hold_reason = t[field].strip()
                    break
            if hold_reason:
                break
            refusal = refusals.get(t["task_id"])
            if isinstance(refusal, dict) and refusal.get("code"):
                hold_reason = str(refusal["code"])
                break
            if isinstance(refusal, str) and refusal.strip():
                hold_reason = refusal.strip()
                break
        if hold_reason is None and status in ("PAUSED_HUMAN", "ABORTED", "CANCELLED") and isinstance(cell_state, dict):
            if isinstance(cell_state.get("reason"), str) and cell_state["reason"].strip():
                hold_reason = cell_state["reason"].strip()
        principal = getattr(getattr(request, "state", None), "site_principal", None)
        is_service = getattr(principal, "role", None) == "service"
        moves = [
            {k: v for k, v in m.items() if (not is_service or k != "cargo_id")}
            for m in rec["moves"]
        ]
        return CellPlanSummaryOut(
            plan_id=rec["plan_id"],
            schema=_SCHEMA,
            mode=rec["mode"],
            order_source=rec["order_source"],
            cell_id=rec["cell_id"],
            status=status,
            total_steps=len(rec["task_ids"]),
            completed_steps=completed,
            proposer=rec.get("proposer"),
            request_key=rec.get("request_key"),
            request_digest=rec.get("request_digest"),
            hold_reason=hold_reason,
            cell_phase=cell_phase,
            task_ids=list(rec["task_ids"]),
            moves=moves,
            created_at=rec["created_at"],
        ).model_dump(by_alias=True)

    @app.post("/api/fleet/pipeline/cell-plans/dry-run", dependencies=read_guard)
    async def preview_cell_plan(request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(422, detail={"code": "INVALID_CELL_PLAN_INPUT"})
        checked_json_value(body)
        try:
            planned = plan_cell_moves(body, web_common=getattr(app.state, "web_common", None))
        except ValueError as exc:
            raise HTTPException(422, detail={"code": str(exc) or "INVALID_CELL_PLAN_INPUT"}) from None
        if not planned["ok"]:
            raise HTTPException(422, detail={"code": planned["why"] or "NO_LEGAL_PLAN"})
        return CellPlanDryRunResponse(
            schema=_SCHEMA,
            mode=planned["mode"],
            order_source=planned["order_source"],
            moves=planned["moves"],
            final_state=planned.get("final_state"),
            why=planned.get("why"),
        ).model_dump(by_alias=True)

    @app.post("/api/fleet/pipeline/cell-plans", dependencies=proposer_guard)
    async def create_cell_plan(request: Request):
        active = active_map()
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(422, detail={"code": "INVALID_CELL_PLAN_INPUT"})
        checked_json_value(body)
        principal = getattr(request.state, "site_principal", None)
        principal_id = getattr(principal, "principal_id", None)
        principal_role = getattr(principal, "role", None)
        raw_key = body["request_key"] if "request_key" in body else request.headers.get("Idempotency-Key")
        req_key = validate_request_key(raw_key)
        scoped_key = scoped_idempotency_key(req_key, principal_id, principal_role) if req_key else None
        body_hash = safe_canonical_digest({"principal_id": principal_id, "principal_role": principal_role, "body": body}) if scoped_key else None

        with (gov._lock if gov is not None else nullcontext()):
            if scoped_key and gov is not None and (cached := gov.check_idempotency(scoped_key, body_hash)):
                return cached[1]
            plan_id = str(body.get("plan_id") or f"cell-plan-{uuid.uuid4().hex[:8]}").strip()
            if not plan_id or plan_id in app.state.omx_cell_plans:
                raise HTTPException(409, detail={"code": "CELL_PLAN_ID_EXISTS"})

            web_common = getattr(app.state, "web_common", None)
            try:
                planned = plan_cell_moves(body, web_common=web_common)
            except ValueError as exc:
                raise HTTPException(422, detail={"code": str(exc) or "INVALID_CELL_PLAN_INPUT"}) from None
            if not planned["ok"]:
                raise HTTPException(422, detail={"code": planned["why"] or "NO_LEGAL_PLAN"})

            station = resolve_omx_cells(active[1], active[2]).get("cell_ab")
            if station is None:
                raise HTTPException(404, detail={"code": "UNKNOWN_CELL"})
            if getattr(app.state, "_pipeline_ledger_fault", False):
                raise HTTPException(503, detail={"code": "PIPELINE_LEDGER_UNAVAILABLE"})

            robot_id = str(body.get("robot_id") or "rosy_01")
            robot_kind = str(body.get("robot_kind") or "")
            total_steps = len(planned["moves"])
            gov_passthrough = {
                k: body[k] for k in (
                    "propose", "proposer", "expected_context_sha256", "expected_readiness_digest",
                    "expected_dispatch_generation", "expected_authority_epoch", "expected_stop_generation",
                    "failure_bundle_id", "failure_context_sha256",
                ) if k in body
            }
            validated_steps: list[tuple[dict[str, Any], dict[str, Any], int, dict[str, float], str, dict[str, Any]]] = []
            prev_task_id: str | None = body.get("depends_on")

            for idx, move in enumerate(planned["moves"]):
                task_id = f"{plan_id}-s{idx + 1}"
                if task_id in app.state.omx_cell_tasks:
                    raise HTTPException(409, detail={"code": "CELL_TASK_ID_EXISTS"})
                step_spec = {
                    "task_id": task_id,
                    "cell_id": "cell_ab",
                    "arm_id": move["arm_id"],
                    "src_site": move["src_site"],
                    "dst_site": move["dst_site"],
                    "tier": move["tier"],
                    "robot_id": robot_id,
                    "robot_kind": robot_kind,
                    **gov_passthrough,
                }
                targets = resolve_cell_task_targets("cell_ab", step_spec, web_common=web_common, legacy_sites=("belt", "vehicle"))
                tier, pose = checked_task_pose(step_spec, station)
                target_status, gov_meta = prepare_task_governance(
                    app, step_spec, principal_id=principal_id, principal_role=principal_role,
                    cell_id="cell_ab", src_site=targets["src_site"], dst_site=targets["dst_site"], gov=gov,
                    active_map_fn=active_map, resolve_cells_fn=resolve_omx_cells,
                    is_human_detected_fn=_is_human_detected, arm_live_catalog_fn=_arm_live_catalog,
                    vehicle_sites=(),
                )
                validated_steps.append((move, targets, tier, pose, target_status, {**gov_meta, "task_id": task_id, "depends_on": prev_task_id}))
                prev_task_id = task_id

            dec_row = _evaluate_decision("cell_ab", "arm_target", {})
            built: list[dict[str, Any]] = []
            for idx, (move, targets, tier, pose, target_status, meta) in enumerate(validated_steps):
                task_id = meta.pop("task_id")
                dep_id = meta.pop("depends_on")
                task = _enrich_task_health({
                    "task_id": task_id,
                    "cell_id": "cell_ab",
                    "arm_id": targets["arm_id"],
                    "directive": None,
                    "robot_id": robot_id,
                    "robot_kind": robot_kind,
                    "src_site": targets["src_site"],
                    "dst_site": targets["dst_site"],
                    "src_site_id": targets["src_site_id"],
                    "dst_site_id": targets["dst_site_id"],
                    "dst_wire_ref": targets["dst_wire_ref"],
                    "dst_area": targets["dst_area"],
                    "dst_slot": targets["dst_slot"],
                    **meta,
                    "tier": tier,
                    "depends_on": dep_id,
                    "plan_id": plan_id,
                    "plan_mode": planned["mode"],
                    "order_source": planned["order_source"],
                    "step_index": idx,
                    "step_count": total_steps,
                    "phase_label": move["phase_label"],
                    "displaced_to": None,
                    "auto_recovered": False,
                    "cable_guard_micro": bool(dec_row["cable_guard_micro"]),
                    "decision": dec_row,
                    "pose": pose,
                    "status": target_status,
                    "created_at": round(time.time(), 3),
                })
                built.append(task)

            plan_record = {
                "plan_id": plan_id,
                "schema": _SCHEMA,
                "mode": planned["mode"],
                "order_source": planned["order_source"],
                "cell_id": "cell_ab",
                "proposer": built[0].get("proposer") if built else principal_id,
                "request_key": req_key,
                "scoped_request_key": scoped_key,
                "request_digest": canonical_digest(body),
                "task_ids": [t["task_id"] for t in built],
                "moves": [{**m, "task_id": built[i]["task_id"]} for i, m in enumerate(planned["moves"])],
                "created_at": round(time.time(), 3),
            }
            for task in built:
                app.state.omx_cell_tasks[task["task_id"]] = task
            app.state.omx_cell_plans[plan_id] = plan_record
            try:
                _save_ledger()
            except Exception:
                app.state.omx_cell_plans.pop(plan_id, None)
                for task in built:
                    app.state.omx_cell_tasks.pop(task["task_id"], None)
                raise
            if gov is not None and any(task["status"] == "QUEUED" for task in built):
                gov.bump_dispatch_generation()

            out = CellPlanResponse(
                schema=_SCHEMA,
                plan=_plan_view(plan_id, request),
                tasks=[_enriched_plan_task(t["task_id"], request) for t in built],
            ).model_dump(by_alias=True)
            if scoped_key and gov is not None:
                gov.record_idempotency(scoped_key, body_hash, 200, out)
            return out

    @app.get("/api/fleet/pipeline/cell-plans", dependencies=read_guard)
    async def list_cell_plans(request: Request, request_key: str | None = None):
        if request_key is not None:
            req_key = validate_request_key(request_key)
            principal = getattr(request.state, "site_principal", None)
            principal_id = getattr(principal, "principal_id", None)
            principal_role = getattr(principal, "role", None)
            caller_scoped = scoped_idempotency_key(req_key, principal_id, principal_role)
            matched_id = next(
                (pid for pid, rec in app.state.omx_cell_plans.items() if rec.get("scoped_request_key") == caller_scoped),
                None,
            )
            if matched_id is None and principal_role != "service":
                matched_id = next(
                    (pid for pid, rec in app.state.omx_cell_plans.items() if rec.get("request_key") == req_key),
                    None,
                )
            if matched_id is None:
                raise HTTPException(404, detail={"code": "UNKNOWN_CELL_PLAN"})
            rec = app.state.omx_cell_plans[matched_id]
            tasks = [
                _enriched_plan_task(tid, request)
                for tid in rec["task_ids"] if tid in app.state.omx_cell_tasks
            ]
            return CellPlanResponse(schema=_SCHEMA, plan=_plan_view(matched_id, request), tasks=tasks).model_dump(by_alias=True)
        plans = [_plan_view(pid, request) for pid in app.state.omx_cell_plans]
        return {"ok": True, "schema": _SCHEMA, "plans": plans}

    @app.get("/api/fleet/pipeline/cell-plans/{plan_id}", dependencies=read_guard)
    async def get_cell_plan(plan_id: str, request: Request):
        if plan_id not in app.state.omx_cell_plans:
            raise HTTPException(404, detail={"code": "UNKNOWN_CELL_PLAN"})
        rec = app.state.omx_cell_plans[plan_id]
        tasks = [
            _enriched_plan_task(tid, request)
            for tid in rec["task_ids"] if tid in app.state.omx_cell_tasks
        ]
        return CellPlanResponse(schema=_SCHEMA, plan=_plan_view(plan_id, request), tasks=tasks).model_dump(by_alias=True)

    @app.post("/api/fleet/pipeline/cell-plans/{plan_id}/cancel", dependencies=proposer_guard)
    async def cancel_cell_plan(plan_id: str, request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(422, detail={"code": "INVALID_CANCEL_REASON"})
        checked_json_value(body)
        try:
            cancel_req = CellPlanCancelRequest.model_validate(body)
        except PydanticValidationError:
            raise HTTPException(422, detail={"code": "INVALID_CANCEL_REASON"}) from None

        principal = getattr(request.state, "site_principal", None)
        principal_id = getattr(principal, "principal_id", None)
        principal_role = getattr(principal, "role", None)

        with (gov._lock if gov is not None else nullcontext()):
            rec = app.state.omx_cell_plans.get(plan_id)
            if rec is None:
                raise HTTPException(404, detail={"code": "UNKNOWN_CELL_PLAN"})
            if principal_role == "service" and rec.get("proposer") != principal_id:
                raise HTTPException(403, detail={"code": "CELL_PLAN_CANCEL_FORBIDDEN"})
            if getattr(app.state, "_pipeline_ledger_fault", False):
                raise HTTPException(503, detail={"code": "PIPELINE_LEDGER_UNAVAILABLE"})

            previous: list[tuple[str, dict[str, Any]]] = []
            cancelled_ids: list[str] = []
            now = round(time.time(), 3)
            for tid in rec["task_ids"]:
                task = app.state.omx_cell_tasks.get(tid)
                if task is None:
                    continue
                if task.get("status") in ("PROPOSED", "QUEUED"):
                    previous.append((tid, dict(task)))
                    task["status"] = "CANCELLED"
                    task["cancel_reason"] = cancel_req.reason
                    task["cancelled_by"] = principal_id
                    task["cancelled_at"] = now
                    cancelled_ids.append(tid)
            if not cancelled_ids:
                raise HTTPException(409, detail={"code": "CELL_PLAN_NOT_CANCELLABLE"})
            try:
                _save_ledger()
            except Exception:
                for tid, prev in previous:
                    app.state.omx_cell_tasks[tid] = prev
                raise
            if gov is not None:
                gov.bump_dispatch_generation()
            tasks = [
                _enriched_plan_task(tid, request)
                for tid in rec["task_ids"] if tid in app.state.omx_cell_tasks
            ]
            return CellPlanCancelResponse(
                schema=_SCHEMA,
                plan=_plan_view(plan_id, request),
                tasks=tasks,
                cancelled_task_ids=cancelled_ids,
            ).model_dump(by_alias=True)
