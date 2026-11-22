"""Bridge verified OMX cell-task completions into Fleet's D-996 port-event ledger."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import logging
import sqlite3
from typing import Any

from core_common.protocol.port_events import PortEvent, event_id
from fleet.server.sitemap.pipeline_unload_release import unload_release
from fleet.server.work.port_event_store import PortEventConflict

_LOG = logging.getLogger(__name__)

TASK_IDENTITY_FIELDS = (
    "object_ref",
    "identity",
    "identity_observation_ref",
    "identity_attested_by",
    "emit_release_permit",
)
CLAIM_STRIP_FIELDS = frozenset({
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
    if not (has_obj or has_ident or has_obs):
        return out
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
    return out


def has_identity_input(body: dict[str, Any]) -> bool:
    return any(key in body for key in IDENTITY_INPUT_FIELDS)


def strip_task_for_claim(task: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of task with D-996 Harbor cargo identity and outbox fields omitted for cell PCs."""
    return {k: v for k, v in task.items() if k not in CLAIM_STRIP_FIELDS}


def _utc_time(ts: float) -> datetime:
    return datetime.fromtimestamp(float(ts), tz=timezone.utc)


def build_completion_events(
    app, task: dict[str, Any], *, cell_phase: str, stage_result: dict[str, Any], human_detected: bool,
) -> list[dict[str, Any]]:
    """Build durable D-996 pending port-event entries for a RELEASED, verified cell task completion."""
    if cell_phase != "RELEASED":
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
    elif (cell_id == "cell_s" and task.get("emit_release_permit") is True
          and getattr(app.state, "intake", None) is None):
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


def flush_pending_port_events(app_or_state) -> int:
    """Drain pending_port_events from omx_cell_tasks into app.state.port_event_store."""
    state = getattr(app_or_state, "state", app_or_state)
    store = getattr(state, "port_event_store", None)
    if store is None:
        return 0
    changed = 0
    tasks = getattr(state, "omx_cell_tasks", None) or {}
    for task in list(tasks.values()):
        pending = list(task.get("pending_port_events") or ())
        if not pending:
            continue
        remaining: list[dict[str, Any]] = []
        for item in pending:
            try:
                ev = PortEvent.model_validate(item["event"])
                store.append(item["source"], ev)
                changed += 1
            except PortEventConflict:
                _LOG.warning("Dropping conflicting pending port event for task %s", task.get("task_id"))
                changed += 1
            except (OSError, sqlite3.Error):
                _LOG.exception("Port event append failed for task %s; retaining in outbox", task.get("task_id"))
                remaining.append(item)
        if remaining:
            task["pending_port_events"] = remaining
        else:
            task.pop("pending_port_events", None)
    return changed
