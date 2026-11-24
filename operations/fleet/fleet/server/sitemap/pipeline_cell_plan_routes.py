"""Dual-mode Fleet cell-plan HTTP routes (/api/fleet/pipeline/cell-plans*)."""
from __future__ import annotations

from contextlib import nullcontext
import time
import uuid
from typing import Any

from fastapi import HTTPException, Request

from fleet.pipeline import resolve_omx_cells
from fleet.pipeline.cell_plan_planner import plan_cell_moves
from fleet.pipeline.cell_site_targets import resolve_cell_task_targets
from fleet.server.pipeline_port_events import task_view_for_request
from .pipeline_governance_store import (
    canonical_digest, prepare_task_governance, safe_canonical_digest, scoped_idempotency_key, validate_request_key,
)
from fleet.server.sitemap.pipeline_routes import _enrich_task_health
from fleet.server.sitemap.pipeline_task_input import checked_json_value, checked_task_pose

_SCHEMA = "rosy.cell-plan.v1"


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

    def _plan_view(plan_id: str, request: Request | None = None) -> dict[str, Any]:
        rec = app.state.omx_cell_plans[plan_id]
        tasks = [
            _enrich_task_health(app.state.omx_cell_tasks[tid])
            for tid in rec["task_ids"] if tid in app.state.omx_cell_tasks
        ]
        completed = sum(1 for t in tasks if t.get("status") == "COMPLETED")
        principal = getattr(getattr(request, "state", None), "site_principal", None)
        is_service = getattr(principal, "role", None) == "service"
        moves = [
            {k: v for k, v in m.items() if (not is_service or k != "cargo_id")}
            for m in rec["moves"]
        ]
        return {
            "plan_id": rec["plan_id"],
            "schema": rec["schema"],
            "mode": rec["mode"],
            "order_source": rec["order_source"],
            "cell_id": rec["cell_id"],
            "status": _aggregate_plan_status(tasks),
            "total_steps": len(rec["task_ids"]),
            "completed_steps": completed,
            "proposer": rec.get("proposer"),
            "request_digest": rec.get("request_digest"),
            "task_ids": list(rec["task_ids"]),
            "moves": moves,
            "created_at": rec["created_at"],
        }

    @app.post("/api/fleet/pipeline/cell-plans/preview", dependencies=read_guard)
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
        return {"ok": True, "schema": _SCHEMA, **planned}

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

            robot_id = str(body.get("robot_id") or "rosy_01")
            robot_kind = str(body.get("robot_kind") or "pinky")
            total_steps = len(planned["moves"])
            built: list[dict[str, Any]] = []
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
                    **({"propose": body["propose"]} if "propose" in body else {}),
                }
                targets = resolve_cell_task_targets("cell_ab", step_spec, web_common=web_common, legacy_sites=("belt", "vehicle"))
                tier, pose = checked_task_pose(step_spec, station)
                dec_row = _evaluate_decision("cell_ab", "arm_target", {})
                target_status, gov_meta = prepare_task_governance(
                    app, step_spec, principal_id=principal_id, principal_role=principal_role,
                    cell_id="cell_ab", src_site=targets["src_site"], dst_site=targets["dst_site"], gov=gov,
                    active_map_fn=active_map, resolve_cells_fn=resolve_omx_cells,
                    is_human_detected_fn=_is_human_detected, arm_live_catalog_fn=_arm_live_catalog,
                    vehicle_sites=("pinky",),
                )
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
                    **gov_meta,
                    "tier": tier,
                    "depends_on": prev_task_id,
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
                prev_task_id = task_id

            plan_record = {
                "plan_id": plan_id,
                "schema": _SCHEMA,
                "mode": planned["mode"],
                "order_source": planned["order_source"],
                "cell_id": "cell_ab",
                "proposer": built[0].get("proposer") if built else principal_id,
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

            out = {
                "ok": True,
                "schema": _SCHEMA,
                "plan": _plan_view(plan_id, request),
                "tasks": [task_view_for_request(t, request) for t in built],
            }
            if scoped_key and gov is not None:
                gov.record_idempotency(scoped_key, body_hash, 200, out)
            return out

    @app.get("/api/fleet/pipeline/cell-plans", dependencies=read_guard)
    async def list_cell_plans(request: Request):
        plans = [_plan_view(pid, request) for pid in app.state.omx_cell_plans]
        return {"ok": True, "schema": _SCHEMA, "plans": plans}

    @app.get("/api/fleet/pipeline/cell-plans/{plan_id}", dependencies=read_guard)
    async def get_cell_plan(plan_id: str, request: Request):
        if plan_id not in app.state.omx_cell_plans:
            raise HTTPException(404, detail={"code": "UNKNOWN_CELL_PLAN"})
        rec = app.state.omx_cell_plans[plan_id]
        tasks = [
            task_view_for_request(_enrich_task_health(app.state.omx_cell_tasks[tid]), request)
            for tid in rec["task_ids"] if tid in app.state.omx_cell_tasks
        ]
        return {"ok": True, "schema": _SCHEMA, "plan": _plan_view(plan_id, request), "tasks": tasks}
