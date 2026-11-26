"""D-996 2/7: port event ingest (a workcell's machine token), the direct-parent peer read, and the app's read.

``GET /api/fleet/port-events`` reads this Fleet's own ledger and every direct child cell that owns a workcell
(deeper cells are out of scope, like the ARM relay). The cursor is opaque to the app: base64url JSON of the last seq
read per source. A source that cannot be reached, or whose seqs skip, leaves its position where it was and makes the
page ``complete: false``.
"""
import asyncio
import base64
import binascii
import json
import sqlite3

import httpx
from fastapi import Depends, Header, HTTPException, Query, Request, Response
from pydantic import ValidationError

from core_common.protocol.port_events import IntakeCandidatePage, IntakeReading, PortEvent, PortEventLedgerPage, PortEventPage
from fleet.server.control_unit_arm_coordinator import direct_child_unit_ids
from .port_event_store import PortEventConflict, PortEventStore
from .rfid_receipts import RfidReceipts, supply_intervals

PORT_EVENT_BODY_BYTES = 4096
LOCAL = "local"


def encode_cursor(positions: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(positions, sort_keys=True, separators=(",", ":")).encode()).decode()


def decode_cursor(cursor: str | None) -> dict:
    if not cursor:
        return {}
    try:
        positions = json.loads(base64.urlsafe_b64decode(cursor.encode()))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise ValueError("PORT_EVENT_CURSOR_INVALID") from None
    if not isinstance(positions, dict) or not all(
            isinstance(k, str) and type(v) is int and v >= 0 for k, v in positions.items()):
        raise ValueError("PORT_EVENT_CURSOR_INVALID")
    return positions


def contiguous(rows: list, after: int) -> tuple[list, bool]:
    """The rows up to the first gap after ``after``, and whether a gap cut them."""
    kept = []
    for row in rows:
        if row["seq"] != after + len(kept) + 1:
            return kept, True
        kept.append(row)
    return kept, False


def workcell_children(control) -> list[str]:
    return direct_child_unit_ids(control, resource_prefix="workcell:")


async def _fetch_source_rows(store, control, source: str, after: int, budget: int) -> list[dict]:
    if source == LOCAL:
        return await asyncio.to_thread(store.after, after, budget)
    page = PortEventLedgerPage.model_validate(await control.peer.port_events(source, after, budget))
    return [{"seq": r.seq, "event": r.event} for r in page.rows]


async def read_page(store, control, cursor: str | None, limit: int) -> dict:
    positions, events, complete = decode_cursor(cursor), [], True
    sources = ([LOCAL] if store is not None else []) + (workcell_children(control) if control is not None else [])
    more = set(sources)
    while len(events) < limit and more:
        pending = [s for s in sources if s in more]
        more.clear()
        for idx, source in enumerate(pending):
            remaining = limit - len(events)
            if remaining <= 0:
                more.update(pending[idx:])
                break
            share = max(1, (remaining + len(pending) - idx - 1) // (len(pending) - idx))
            after = positions.get(source, 0)
            try:
                rows = await _fetch_source_rows(store, control, source, after, share)
            except (OSError, sqlite3.Error, httpx.HTTPError, asyncio.TimeoutError, ValueError, ValidationError):
                complete = False  # this cell keeps its position; the next read asks again
                continue
            kept, gap = contiguous(rows[:share], after)
            complete = complete and not gap
            events += [row["event"] for row in kept]
            if kept:
                positions[source] = kept[-1]["seq"]
            if not gap and len(rows) >= share:
                more.add(source)
    if more:
        complete = False
    return PortEventPage(events=events, cursor=encode_cursor(positions), complete=complete).model_dump(mode="json")


def install_port_event_routes(app, observations, task_service, *, authorize, require_viewer):
    store = PortEventStore(task_service.store.path) if task_service is not None else None
    app.state.port_event_store = store
    rfid = RfidReceipts.configured(store) if store is not None else None
    app.state.rfid_receipts = rfid

    def available():
        if store is None:
            raise HTTPException(503, detail={"code": "PORT_EVENTS_UNAVAILABLE"})
        return store

    async def machine_body(workcell_id, request, token):
        if observations is None or not token:
            raise HTTPException(401, detail={"code": "WORKCELL_OBSERVATION_UNAUTHORIZED"})
        try:
            observations.authorize_workcell(workcell_id, token)
        except (KeyError, PermissionError):
            raise HTTPException(401, detail={"code": "WORKCELL_OBSERVATION_UNAUTHORIZED"}) from None
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > PORT_EVENT_BODY_BYTES:
                raise HTTPException(413, detail={"code": "WORKCELL_OBSERVATION_TOO_LARGE"})
            data.extend(chunk)
        return data

    @app.post("/api/fleet/workcell-observations/{workcell_id}/intake-readings", tags=["workcell-observations"])
    async def reading(workcell_id: str, request: Request, response: Response,
                      token: str | None = Header(None, alias="X-Workcell-Observation-Token")):
        """D-996 3: Fleet translates intake RFID or camera tag readings into port events."""
        response.headers["Cache-Control"] = "no-store"
        data = await machine_body(workcell_id, request, token)
        try:
            parsed = IntakeReading.model_validate_json(data)
        except ValidationError:
            raise HTTPException(422, detail={"code": "INVALID_INTAKE_READING"}) from None
        if parsed.point == "rfid_intake" and rfid is not None and rfid.reader_workcell:
            try:
                await asyncio.to_thread(rfid.record, workcell_id, parsed)
            except PermissionError:
                raise HTTPException(403, detail={"code": "RFID_WORKCELL_UNBOUND"}) from None
            except PortEventConflict:
                raise HTTPException(409, detail={"code": "INTAKE_READING_CONFLICT"}) from None
            except (OSError, sqlite3.Error):
                raise HTTPException(503, detail={"code": "INTAKE_READINGS_UNAVAILABLE"}) from None
            return {"observation_ref": parsed.observation_ref, "seqs": []}
        if parsed.reader_epoch is not None:
            raise HTTPException(503, detail={"code": "RFID_INTAKE_NOT_CONFIGURED"})
        intake, arms = getattr(app.state, "intake", None), getattr(app.state, "arm_transfer_job_store", None)
        if store is None or intake is None or arms is None:
            raise HTTPException(503, detail={"code": "INTAKE_READINGS_UNAVAILABLE"})
        if parsed.point == "rfid_intake" and not intake.get("container_epcs"):
            raise HTTPException(503, detail={"code": "RFID_INTAKE_NOT_CONFIGURED"})
        from .intake_readings import record
        try:
            seqs = await asyncio.to_thread(record, arms, store, intake, workcell_id, parsed)
        except PortEventConflict:
            raise HTTPException(409, detail={"code": "INTAKE_READING_CONFLICT"}) from None
        except (OSError, sqlite3.Error):
            raise HTTPException(503, detail={"code": "PORT_EVENTS_UNAVAILABLE"}) from None
        return {"observation_ref": parsed.observation_ref, "seqs": seqs}

    @app.post("/api/fleet/workcell-observations/{workcell_id}/port-events", tags=["workcell-observations"])
    async def ingest(workcell_id: str, request: Request, response: Response,
                     token: str | None = Header(None, alias="X-Workcell-Observation-Token")):
        response.headers["Cache-Control"] = "no-store"
        data = await machine_body(workcell_id, request, token)
        try:
            event = PortEvent.model_validate_json(data)
        except ValidationError:
            raise HTTPException(422, detail={"code": "INVALID_PORT_EVENT"}) from None
        if event.intake_occurrence_id or event.placement_attempt_id or event.kind == "vehicle.release_permitted":
            raise HTTPException(422, detail={"code": "PORT_EVENT_KIND_NOT_ALLOWED"})
        try:
            seq = await asyncio.to_thread(available().append, workcell_id, event)
        except PermissionError:
            raise HTTPException(422, detail={"code": "PORT_EVENT_ID_MISMATCH"}) from None
        except PortEventConflict:
            raise HTTPException(409, detail={"code": "PORT_EVENT_CONFLICT"}) from None
        except (OSError, sqlite3.Error):
            raise HTTPException(503, detail={"code": "PORT_EVENTS_UNAVAILABLE"}) from None
        return {"event_id": event.event_id, "seq": seq}

    def parent_only(principal=Depends(authorize)):
        control = getattr(app.state, "control_unit", None)
        if (control is None or control.unit.parent is None or principal.role != "service"
                or principal.principal_id != "control-unit:" + control.unit.parent):
            raise HTTPException(403, detail={"code": "CONTROL_UNIT_PARENT_ONLY"})
        return principal

    @app.get("/api/fleet/control-unit/intake-candidates", response_model=IntakeCandidatePage, tags=["control-unit"])
    async def candidates(after_seq: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200),
                         principal=Depends(parent_only)):
        if rfid is None or not rfid.reader_workcell:
            raise HTTPException(503, detail={"code": "RFID_INTAKE_NOT_CONFIGURED"})
        return await asyncio.to_thread(rfid.page, after_seq, limit)

    async def reconcile_rfid(control):
        if control.unit.parent is not None:
            return False
        owners = [u.unit_id for u in control.topology.units.values()
                  if u.parent == control.unit.unit_id and f"observation-workcell:{rfid.workcell}" in u.resources]
        if len(owners) != 1:
            return False
        peer = owners[0]
        after = await asyncio.to_thread(rfid.cursor, peer)
        # Ask for one extra pass after a full page, before committing possibly quarantined labels.
        page = await control.peer.intake_candidates(peer, after, 200)
        count = await asyncio.to_thread(rfid.accept_page, peer, after, page)
        if count == 200 or getattr(app.state, "_pipeline_ledger_fault", False):
            return False
        tasks = supply_intervals(getattr(app.state, "omx_cell_tasks", {}).values(), rfid.workcell)
        await asyncio.to_thread(rfid.reconcile, peer, tasks)
        return True

    @app.get("/api/fleet/control-unit/port-events", response_model=PortEventLedgerPage, tags=["control-unit"])
    async def ledger(after_seq: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200),
                     principal=Depends(parent_only)):
        try:
            rows = await asyncio.to_thread(available().after, after_seq, limit)
        except (OSError, sqlite3.Error):
            raise HTTPException(503, detail={"code": "PORT_EVENTS_UNAVAILABLE"}) from None
        return {"rows": rows}

    @app.get("/api/fleet/port-events", response_model=PortEventPage, tags=["fleet-work"])
    async def read(response: Response, after: str | None = Query(None, max_length=4096),
                   limit: int = Query(100, ge=1, le=200), principal=Depends(require_viewer)):
        response.headers["Cache-Control"] = "no-store"
        try:
            control = getattr(app.state, "control_unit", None)
            caught_up = True
            if rfid is not None and rfid.workcell:
                try:
                    caught_up = control is not None and await reconcile_rfid(control)
                except (OSError, sqlite3.Error, httpx.HTTPError, asyncio.TimeoutError, ValueError):
                    caught_up = False
            page = await read_page(store, control, after, limit)
            page["complete"] = page["complete"] and caught_up
            return page
        except ValueError:
            raise HTTPException(400, detail={"code": "PORT_EVENT_CURSOR_INVALID"}) from None
