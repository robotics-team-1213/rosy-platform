"""Atomic batch admission helper for dual-mode OMX cell plans (/api/fleet/pipeline/cell-plans/{plan_id}/admit)."""
from __future__ import annotations

from contextlib import suppress
import json
import time
from typing import Any

from fastapi import HTTPException

from fleet.server.sitemap.pipeline_governance_store import (
    _validate_cas_fields,
    build_cell_readiness,
    canonical_digest,
    require_human_operator,
)


def _admit_batch_cas(
    gov,
    expected: dict[str, Any],
    actual: dict[str, Any],
    *,
    task_ids: list[str],
    approved_by: str,
    ledger_snapshot: dict[str, Any] | None = None,
) -> tuple[bool, list[str], int]:
    """Verify readiness CAS once and atomically mark all target plan steps admitted in governance SQLite."""
    ledger_encoded = (
        json.dumps(
            {"sha256": canonical_digest(ledger_snapshot), "payload": ledger_snapshot},
            ensure_ascii=False, allow_nan=False, default=str,
        )
        if ledger_snapshot is not None else None
    )
    placeholders = ",".join("?" for _ in task_ids)
    with gov._write_tx():
        already = gov._conn.execute(
            f"SELECT task_id FROM pipeline_admitted_tasks WHERE task_id IN ({placeholders})",
            tuple(task_ids),
        ).fetchone()
        if already is not None:
            row = gov._conn.execute("SELECT dispatch_generation FROM pipeline_authority_state WHERE id = 1").fetchone()
            return False, ["task already admitted"], int(row["dispatch_generation"])
        row = gov._conn.execute(
            "SELECT authority_epoch, dispatch_generation, stop_generation FROM pipeline_authority_state WHERE id = 1"
        ).fetchone()
        ep, dg, sg = int(row["authority_epoch"]), int(row["dispatch_generation"]), int(row["stop_generation"])
        reasons = _validate_cas_fields(
            expected, actual, ep=ep, dg=dg, sg=sg,
            require_all=True, require_context_sha=bool(actual.get("context_sha256")),
        )
        if reasons:
            return False, reasons, dg
        new_dg = dg + 1
        now = time.time()
        gov._conn.execute(
            "UPDATE pipeline_authority_state SET dispatch_generation = ?, updated_at = ? WHERE id = 1",
            (new_dg, now),
        )
        for tid in task_ids:
            gov._conn.execute(
                "INSERT INTO pipeline_admitted_tasks (task_id, approved_by, admitted_at) VALUES (?, ?, ?)",
                (tid, approved_by, now),
            )
        if ledger_encoded is not None:
            gov._conn.execute(
                "INSERT OR REPLACE INTO pipeline_confirmations (kind, task_id, record_json, updated_at) VALUES ('ledger_commit', 'current', ?, ?)",
                (ledger_encoded, now),
            )
        return True, [], new_dg


def admit_cell_plan_guarded(app, ctx, plan_id: str, body: dict[str, Any], principal: Any) -> dict[str, Any]:
    """Atomically admit all remaining PROPOSED tasks of a cell plan under D-1057 two-person CAS governance."""
    gov = getattr(ctx, "gov", None) or getattr(app.state, "pipeline_governance", None)
    if gov is None or getattr(app.state, "_pipeline_ledger_fault", False):
        raise HTTPException(503, detail={"code": "GOVERNANCE_STORE_UNAVAILABLE"})
    approver = require_human_operator(principal)
    from fleet.server.sitemap.pipeline_routes import _enrich_task_health

    with gov._lock:
        rec = (getattr(app.state, "omx_cell_plans", None) or {}).get(plan_id)
        if rec is None:
            raise HTTPException(404, detail={"code": "UNKNOWN_CELL_PLAN"})
        store = getattr(app.state, "arm_transfer_job_store", None)
        if callable(getattr(store, "has_active_transfer", None)) and store.has_active_transfer():
            raise HTTPException(409, detail={"code": "CELL_WORK_CONFLICT"})

        plan_proposer = str(rec.get("proposer") or "").strip()
        if not plan_proposer or plan_proposer == approver:
            raise HTTPException(403, detail={"code": "SELF_APPROVAL_FORBIDDEN"})
        target_tasks: list[dict[str, Any]] = []
        for tid in rec.get("task_ids") or ():
            task = app.state.omx_cell_tasks.get(tid)
            if task is not None and task.get("status") == "PROPOSED":
                proposer = str(task.get("proposer") or "").strip()
                if not proposer or proposer == approver:
                    raise HTTPException(403, detail={"code": "SELF_APPROVAL_FORBIDDEN"})
                target_tasks.append(task)
        if not target_tasks:
            raise HTTPException(409, detail={"code": "CELL_PLAN_NOT_ADMITTABLE"})

        expected_digest = body.get("expected_request_digest")
        if expected_digest is not None and expected_digest != rec.get("request_digest"):
            raise HTTPException(409, detail={"code": "STALE_FAILURE_CONTEXT", "reasons": ["request_digest mismatch"]})

        ctx_hashes = {t.get("failure_context_sha256") for t in target_tasks if t.get("failure_context_sha256")}
        if len(ctx_hashes) > 1:
            raise HTTPException(409, detail={"code": "STALE_FAILURE_CONTEXT", "reasons": ["mixed context_sha256 across steps"]})
        actual_ctx = next(iter(ctx_hashes), None)

        rdy = build_cell_readiness(
            app, rec["cell_id"],
            active_map_fn=ctx.active_map,
            resolve_cells_fn=ctx.resolve_omx_cells if hasattr(ctx, "resolve_omx_cells") else None,
            is_human_detected_fn=ctx._is_human_detected,
            arm_live_catalog_fn=ctx._arm_live_catalog,
            gov=gov,
        ) if hasattr(ctx, "resolve_omx_cells") else None
        if rdy is None:
            from fleet.pipeline import resolve_omx_cells
            rdy = build_cell_readiness(
                app, rec["cell_id"],
                active_map_fn=ctx.active_map,
                resolve_cells_fn=resolve_omx_cells,
                is_human_detected_fn=ctx._is_human_detected,
                arm_live_catalog_fn=ctx._arm_live_catalog,
                gov=gov,
            )

        actual_cas = {"context_sha256": actual_ctx, "readiness_digest": rdy["readiness_digest"]}
        prev_states = [
            (t, {k: t.get(k) for k in ("status", "approved_by", "admitted_at", "health_summary")})
            for t in target_tasks
        ]
        target_ids = [t["task_id"] for t in target_tasks]
        now = round(time.time(), 3)
        ledger_payload_fn = getattr(ctx, "_ledger_payload", None)
        write_ledger_fn = getattr(ctx, "_write_ledger_only", None)

        def _restore() -> None:
            for t, prev in prev_states:
                for k, v in prev.items():
                    t.pop(k, None) if v is None else t.__setitem__(k, v)

        if callable(ledger_payload_fn) and callable(write_ledger_fn):
            for t in target_tasks:
                t["status"], t["approved_by"], t["admitted_at"] = "QUEUED", approver, now
                _enrich_task_health(t)
            try:
                payload = ledger_payload_fn()
                write_ledger_fn(payload)
                ok_cas, reasons, new_dg = _admit_batch_cas(
                    gov, body, actual_cas, task_ids=target_ids, approved_by=approver, ledger_snapshot=payload,
                )
                if not ok_cas:
                    raise HTTPException(409, detail={"code": "STALE_FAILURE_CONTEXT", "reasons": reasons})
            except Exception:
                _restore()
                if not getattr(app.state, "_pipeline_ledger_fault", False):
                    with suppress(Exception):
                        write_ledger_fn(ledger_payload_fn())
                raise
            return {"admitted_task_ids": target_ids, "dispatch_generation": new_dg}

        ok_cas, reasons, new_dg = _admit_batch_cas(
            gov, body, actual_cas, task_ids=target_ids, approved_by=approver,
        )
        if not ok_cas:
            raise HTTPException(409, detail={"code": "STALE_FAILURE_CONTEXT", "reasons": reasons})
        for t in target_tasks:
            t["status"], t["approved_by"], t["admitted_at"] = "QUEUED", approver, now
            _enrich_task_health(t)
        try:
            ctx._save_ledger()
        except Exception:
            _restore()
            with gov._write_tx():
                placeholders = ",".join("?" for _ in target_ids)
                gov._conn.execute(f"DELETE FROM pipeline_admitted_tasks WHERE task_id IN ({placeholders})", tuple(target_ids))
            raise
        return {"admitted_task_ids": target_ids, "dispatch_generation": new_dg}
