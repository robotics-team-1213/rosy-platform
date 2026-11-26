"""Bridge verified OMX cell-task completions into Fleet's D-996 port-event ledger."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import logging
import sqlite3
from typing import Any

from pydantic import ValidationError

from core_common.protocol.port_events import PortEvent, event_id
from fleet.pipeline.cell_site_targets import cell_ab_completion_verified, resolve_cell_ab_site
from fleet.server.pipeline_unload_release import unload_release
from fleet.server.port_event_store import PortEventConflict

_LOG = logging.getLogger(__name__)

TASK_IDENTITY_FIELDS = (
    "object_ref",
    "identity",
    "identity_observation_ref",
    "identity_attested_by",
    "emit_release_permit",
)
CLAIM_STRIP_FIELDS = frozenset({
    "intake_occurrence_id",
    "placement_attempt_id",
    "object_ref",
    "identity",
    "identity_observation_ref",
    "identity_attested_by",
    "pending_port_events",
})
IDENTITY_INPUT_FIELDS = ("object_ref", "identity", "identity_observation_ref")


def _check_ref(value: Any, *, limit: int = 128) -> str:
    if (type(value) is not str or not 1 <= len(value) <= limit or value != value.strip()
            or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value)):
        raise ValueError("INVALID_CELL_TASK_INPUT")
    return value


def validate_task_identity(spec: dict[str, Any], *, cell_id: str, principal_id: str | None = None) -> dict[str, Any]:
    """Validate optional D-996 cargo identity and opt-in cell_s release permit fields on cell task creation."""
    out: dict[str, Any] = {}
    if "emit_release_permit" in spec:
        permit = spec["emit_release_permit"]
        if type(permit) is not bool or (permit and cell_id != "cell_s"):
            raise ValueError("INVALID_CELL_TASK_INPUT")
        if permit:
            out["emit_release_permit"] = True

    has_obj = "object_ref" in spec
    has_ident = "identity" in spec
    has_obs = "identity_observation_ref" in spec
    if has_obj or has_ident or has_obs:
        if not (has_obj and has_ident):
            raise ValueError("INVALID_CELL_TASK_INPUT")
        object_ref = _check_ref(spec["object_ref"])
        ident = spec["identity"]
        if type(ident) is not str or ident not in ("observed", "attested"):
            raise ValueError("INVALID_CELL_TASK_INPUT")
        out["object_ref"] = object_ref
        out["identity"] = ident
        if ident == "observed":
            if not has_obs:
                raise ValueError("IDENTITY_EVIDENCE_REQUIRED")
            out["identity_observation_ref"] = _check_ref(spec["identity_observation_ref"])
        else:
            if has_obs:
                out["identity_observation_ref"] = _check_ref(spec["identity_observation_ref"])
            out["identity_attested_by"] = _check_ref(principal_id or spec.get("identity_attested_by") or "operator")

    if out and spec.get("robot_id") is not None:
        _check_ref(spec["robot_id"])
    return out


def has_identity_input(body: dict[str, Any]) -> bool:
    return any(key in body for key in IDENTITY_INPUT_FIELDS)


def strip_task_for_claim(task: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of task with D-996 Harbor cargo identity and outbox fields omitted for cell PCs."""
    return {k: v for k, v in task.items() if k not in CLAIM_STRIP_FIELDS}


def task_view_for_request(task: dict[str, Any], request: Any) -> dict[str, Any]:
    """Enforce D-996 PC isolation for service principals while always keeping pending_port_events internal."""
    principal = getattr(getattr(request, "state", None), "site_principal", None)
    if getattr(principal, "role", None) == "service":
        return strip_task_for_claim(task)
    return {k: v for k, v in task.items() if k != "pending_port_events"}


def _utc_time(ts: float) -> datetime:
    return datetime.fromtimestamp(float(ts), tz=timezone.utc)


def _tracked_placement(app, task, stage):
    """RFID supplies the identity. A single pick and the owner's measured destination supply the location."""
    receipt, verification, raw, clearance, place = (task.get("receipt"), stage.get("verification"),
            stage.get("raw"), stage.get("source_clearance"), stage.get("place"))
    if not all(isinstance(v, dict) for v in (receipt, verification, raw, clearance, place)):
        return []
    attempts = raw.get("attempts")
    placed = verification.get("place_slot")
    if (task.get("src_site") != "belt" or task.get("status") != "COMPLETED"
            or not task.get("placement_attempt_id") or not task.get("object_ref")
            or type(task.get("claimed_at")) not in (int, float) or type(task.get("completed_at")) not in (int, float)
            or receipt.get("phase") != "RELEASED" or receipt.get("physical_completion") is not True
            or receipt.get("simulated_success") is not False or receipt.get("stage_id") != task["task_id"]
            or not task.get("handoff_lease_id") or receipt.get("handoff_lease_id") != task["handoff_lease_id"]
            or stage.get("directive_id") != task["task_id"] or stage.get("arm_id") != task.get("arm_id")
            or stage.get("task_verified") is not True or raw.get("result") != "placed"
            or not isinstance(attempts, list) or not attempts or not isinstance(attempts[-1], dict)
            or type(attempts[-1].get("observed")) is not int or attempts[-1]["observed"] != 1
            or clearance.get("site") not in ("belt", "beltend") or type(clearance.get("objects")) is not int
            or clearance["objects"] != 0 or verification.get("basis") != "predefined_side_and_top_target_zones"
            or verification.get("verified") is not True or not isinstance(placed, dict) or placed.get("present") is not True
            or not isinstance(verification.get("z_gate"), dict) or not isinstance(verification.get("target"), dict)
            or not cell_ab_completion_verified(task, place, verification.get("z_gate") or {}, verification)):
        return []
    measured = verification.get("measured_at")
    if type(measured) not in (int, float) or not task["claimed_at"] <= measured <= task["completed_at"]:
        return []
    target = verification.get("target") or {}
    try:
        slot = resolve_cell_ab_site(target.get("site_id"), tier=target.get("tier"), has_tier=True,
                                    web_common=getattr(app.state, "web_common", None))
    except ValueError:
        return []
    if not slot.get("wire_ref") or slot["wire_ref"] != task.get("dst_wire_ref"):
        return []
    ref = "tracked-place:" + hashlib.sha256(task["task_id"].encode()).hexdigest()
    kind = "container.stored"
    event = PortEvent(event_id=event_id("cell_ab", ref, kind), kind=kind, observation_ref=ref,
                      object_ref=task["object_ref"], intake_occurrence_id=task["intake_occurrence_id"],
                      placement_attempt_id=task["placement_attempt_id"], slot_ref=slot["wire_ref"],
                      identity="attested", observed_at=_utc_time(measured))
    return [{"source": "cell_ab", "event": event.model_dump(mode="json")}]


def build_completion_events(
    app, task: dict[str, Any], *, cell_phase: str, stage_result: dict[str, Any], human_detected: bool,
) -> list[dict[str, Any]]:
    """Build durable D-996 pending port-event entries for a RELEASED, verified cell task completion."""
    if cell_phase != "RELEASED":
        return []
    if task.get("cell_id") == "cell_ab" and task.get("intake_occurrence_id"):
        return _tracked_placement(app, task, stage_result)
    if getattr(app.state, "intake", None) is not None:
        return []
    completed_at = _utc_time(task["completed_at"])
    cell_id = task.get("cell_id")
    events: list[dict[str, Any]] = []

    if (cell_id == "cell_ab" and task.get("object_ref")
            and task.get("identity") in ("observed", "attested") and task.get("dst_wire_ref")):
        obs_ref = f"cell-task:{hashlib.sha256(task['task_id'].encode('utf-8')).hexdigest()}"
        source, kind = "cell_ab", "container.stored"
        ev = PortEvent(
            event_id=event_id(source, obs_ref, kind),
            kind=kind,
            observation_ref=obs_ref,
            object_ref=task["object_ref"],
            slot_ref=task["dst_wire_ref"],
            identity=task["identity"],
            observed_at=completed_at,
        )
        events.append({"source": source, "event": ev.model_dump(mode="json")})
    elif cell_id == "cell_s" and task.get("emit_release_permit") is True:
        batch_id = task.get("unload_batch_id")
        if batch_id:
            rel = unload_release(
                app.state, task["robot_id"], now=float(task["completed_at"]),
                human_detected=human_detected, allow_used=True,
            )
            ready = rel["ready"] is True
            release_key = str(batch_id)
        else:
            cstate = app.state.omx_cell_states.get("cell_s") or {}
            arm_live = app.state.arm_live_states.get("arm_s") or {}
            sc = (stage_result or {}).get("source_clearance")
            ready = (
                task.get("dst_site") == "belt"
                and bool(task.get("src_site"))
                and task.get("src_site") != "belt"
                and not human_detected
                and cstate.get("phase") == "RELEASED"
                and not cstate.get("amr_motion_inhibited")
                and not (app.state.arm_holds.get("arm_s") or {}).get("held")
                and arm_live.get("folded") is True
                and isinstance(sc, dict) and type(sc.get("objects")) is int and sc["objects"] == 0
            )
            release_key = task["task_id"]
        if ready:
            obs_ref = f"cell-s-release:{hashlib.sha256(release_key.encode('utf-8')).hexdigest()}"
            source, kind = "cell_s", "vehicle.release_permitted"
            ev = PortEvent(
                event_id=event_id(source, obs_ref, kind),
                kind=kind,
                observation_ref=obs_ref,
                vehicle_id=task["robot_id"],
                observed_at=completed_at,
            )
            events.append({"source": source, "event": ev.model_dump(mode="json")})
    return events


def _apply_flush_item(store, receipts, task_id, task, history, item):
    try:
        source = item["source"]
        ev = PortEvent.model_validate(item["event"])
    except (ValidationError, KeyError, TypeError):
        _LOG.error("Dropping malformed pending port event for task %s", task_id)
        return 1
    try:
        if ev.placement_attempt_id and ev.identity == "attested":
            if store.by_observation(source, ev.observation_ref):
                return 1  # The last flush committed before a restart.
            if receipts is None or not receipts.tracked_source(ev.intake_occurrence_id, ev.object_ref,
                    task.get("claimed_at"), task.get("completed_at"), history):
                return 0
        store.append(source, ev)
        return 1
    except (PortEventConflict, PermissionError):
        _LOG.warning("Dropping conflicting/unmatched pending port event for task %s", task_id)
        return 1
    except (OSError, sqlite3.Error):
        _LOG.exception("Port event append failed for task %s; retaining in outbox", task_id)
        return 0


def _finish_task_flush(tasks: dict[str, Any], tid: str, remaining: list[dict[str, Any]]) -> None:
    task = tasks.get(tid)
    if task is None:
        return
    if remaining:
        task["pending_port_events"] = remaining
    else:
        task.pop("pending_port_events", None)


async def flush_pending_port_events_async(app_or_state) -> int:
    """Thread-safe event-loop flush: snapshot and mutate on the loop, run SQLite append in to_thread."""
    state = getattr(app_or_state, "state", app_or_state)
    store = getattr(state, "port_event_store", None)
    if store is None:
        return 0
    lock = getattr(state, "_port_event_flush_lock", None)
    if lock is None:
        lock = state._port_event_flush_lock = asyncio.Lock()
    async with lock:
        tasks = getattr(state, "omx_cell_tasks", None) or {}
        work = [
            (tid, list(task.get("pending_port_events") or ()))
            for tid, task in tasks.items()
            if task.get("pending_port_events")
        ]
        changed = 0
        for tid, pending in work:
            remaining: list[dict[str, Any]] = []
            for item in pending:
                task = dict(tasks[tid])
                history = [dict(t) for t in tasks.values()] if task.get("placement_attempt_id") else ()
                if await asyncio.to_thread(_apply_flush_item, store, getattr(state, "rfid_receipts", None),
                                           tid, task, history, item):
                    changed += 1
                else:
                    remaining.append(item)
            _finish_task_flush(tasks, tid, remaining)
        return changed


def flush_pending_port_events(app_or_state) -> int:
    """Synchronous flush helper for unit tests and single-thread callers."""
    state = getattr(app_or_state, "state", app_or_state)
    store = getattr(state, "port_event_store", None)
    if store is None:
        return 0
    changed = 0
    tasks = getattr(state, "omx_cell_tasks", None) or {}
    for tid, pending in [
        (tid, list(task.get("pending_port_events") or ()))
        for tid, task in tasks.items()
        if task.get("pending_port_events")
    ]:
        remaining: list[dict[str, Any]] = []
        for item in pending:
            if _apply_flush_item(store, getattr(state, "rfid_receipts", None), tid, tasks[tid], tasks.values(), item):
                changed += 1
            else:
                remaining.append(item)
        _finish_task_flush(tasks, tid, remaining)
    return changed
