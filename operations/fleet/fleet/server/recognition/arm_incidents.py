"""D-971: OMX arm incidents. The control PC reports, the AI PC explains, a named operator clears; Fleet keeps the ledger.

OPEN -> (EXPLAINED) -> CLEARED, in the shared Fleet SQLite DB. An arm with an incident that is not CLEARED is held: the
control PC asks before a session and does not start one. A hold is not a command and not a Cell Job claim (D-779).
The explanation is stored and shown, never acted on. Nothing is deleted."""
import base64
import json
import re
import sqlite3
import threading
import time
from uuid import uuid4

from fastapi import Depends, Header, HTTPException, Request, Response
from fastapi.responses import Response as RawResponse
from pydantic import ValidationError

from core_common.protocol.arm_incidents import (
    ARM_INCIDENT_BODY_BYTES, ArmIncidentAccepted, ArmIncidentClear, ArmIncidentExplanation, ArmIncidentHold,
    ArmIncidentReport)
from fleet.server.camera_peer_routes import body as bounded_json
from fleet.server.sqlite_policy import configure_connection, enable_wal

SHOWN_CLEARED = 20  # cleared incidents stay in history; the snapshot shows this many per arm
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
ROLES = ("top", "side")


class ArmIncidentStore:
    def __init__(self, path=None, *, wall=time.time):
        self._wall, self._lock = wall, threading.Lock()
        self._db = configure_connection(sqlite3.connect(str(path) if path else ":memory:", check_same_thread=False))
        if path:
            enable_wal(self._db)
        with self._db:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS arm_incidents (incident_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, "
                "session_id TEXT NOT NULL, reported_at REAL NOT NULL, facts TEXT NOT NULL, decision TEXT NOT NULL, "
                "recovery TEXT, seen TEXT, suspected_cause TEXT, model TEXT, explained_at REAL, "
                "cleared_by TEXT, cleared_at REAL, clear_note TEXT, UNIQUE (source_id, session_id))")
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS arm_incident_frames (incident_id TEXT NOT NULL, role TEXT NOT NULL, "
                "sha256 TEXT NOT NULL, jpeg BLOB NOT NULL, PRIMARY KEY (incident_id, role))")

    def report(self, report: ArmIncidentReport) -> str:
        """Store one report; the same (source, session) again is the same incident and changes nothing."""
        with self._lock, self._db:
            row = self._db.execute("SELECT incident_id FROM arm_incidents WHERE source_id=? AND session_id=?",
                                   (report.source_id, report.session_id)).fetchone()
            if row:
                return row[0]
            incident_id = uuid4().hex
            self._db.execute(
                "INSERT INTO arm_incidents (incident_id, source_id, session_id, reported_at, facts, decision, recovery) "
                "VALUES (?,?,?,?,?,?,?)",
                (incident_id, report.source_id, report.session_id, self._wall(), json.dumps(report.facts),
                 json.dumps(report.decision), None if report.recovery is None else json.dumps(report.recovery)))
            for frame in report.frames:
                self._db.execute("INSERT INTO arm_incident_frames VALUES (?,?,?,?)",
                                 (incident_id, frame.role, frame.sha256, base64.b64decode(frame.jpeg_b64)))
            return incident_id

    def hold(self, source_id) -> ArmIncidentHold:
        with self._lock:
            rows = self._db.execute("SELECT incident_id, decision FROM arm_incidents WHERE source_id=? "
                                    "AND cleared_at IS NULL ORDER BY reported_at, rowid", (source_id,)).fetchall()
        if not rows:
            return ArmIncidentHold(held=False, incident_ids=[])
        try:
            why = json.loads(rows[0][1]).get("reason")
        except ValueError:
            why = None
        why = CONTROL.sub(" ", why)[:300] if isinstance(why, str) and why.strip() else "arm incident not cleared"
        return ArmIncidentHold(held=True, incident_ids=[r[0] for r in rows[:64]],
                               reason=f"{len(rows)} open arm incident(s): {why}")

    def accepted(self, source_id, incident_id) -> ArmIncidentAccepted:
        return ArmIncidentAccepted(incident_id=incident_id, hold=self.hold(source_id))

    def clear(self, source_id, incident_id, note, principal_id) -> None:
        """KeyError: no such incident for this arm. ValueError: already cleared (the first record stands)."""
        with self._lock, self._db:
            row = self._db.execute("SELECT cleared_at FROM arm_incidents WHERE incident_id=? AND source_id=?",
                                   (incident_id, source_id)).fetchone()
            if row is None:
                raise KeyError(incident_id)
            if row[0] is not None:
                raise ValueError("already cleared")
            self._db.execute("UPDATE arm_incidents SET cleared_by=?, cleared_at=?, clear_note=? WHERE incident_id=?",
                             (principal_id, self._wall(), note, incident_id))

    def explain(self, source_id, incident_id, explanation: ArmIncidentExplanation) -> None:
        """KeyError: no such incident. ValueError: already explained or cleared (the first explanation stands)."""
        with self._lock, self._db:
            row = self._db.execute("SELECT explained_at, cleared_at FROM arm_incidents WHERE incident_id=? "
                                   "AND source_id=?", (incident_id, source_id)).fetchone()
            if row is None:
                raise KeyError(incident_id)
            if row[0] is not None or row[1] is not None:
                raise ValueError("not open for an explanation")
            self._db.execute("UPDATE arm_incidents SET seen=?, suspected_cause=?, model=?, explained_at=? "
                             "WHERE incident_id=?", (explanation.seen, explanation.suspected_cause,
                                                     explanation.model, self._wall(), incident_id))

    def frame(self, source_id, incident_id, role):
        with self._lock:
            row = self._db.execute(
                "SELECT f.jpeg FROM arm_incident_frames f JOIN arm_incidents i USING (incident_id) "
                "WHERE i.source_id=? AND f.incident_id=? AND f.role=?", (source_id, incident_id, role)).fetchone()
        return row[0] if row else None

    def _rows(self, where, args, limit=None):
        query = ("SELECT incident_id, source_id, session_id, reported_at, facts, decision, recovery, seen, "
                 "suspected_cause, model, explained_at, cleared_by, cleared_at, clear_note FROM arm_incidents "
                 f"WHERE {where} ORDER BY reported_at DESC, rowid DESC" + (f" LIMIT {int(limit)}" if limit else ""))
        return self._db.execute(query, args).fetchall()

    def _view(self, row, with_bytes):
        (incident_id, source_id, session_id, reported_at, facts, decision, recovery, seen, cause, model, explained_at,
         cleared_by, cleared_at, note) = row
        frames = self._db.execute("SELECT role, sha256, jpeg FROM arm_incident_frames WHERE incident_id=? "
                                  "ORDER BY role DESC", (incident_id,)).fetchall()
        out = {"incident_id": incident_id, "source_id": source_id, "session_id": session_id,
               "state": "cleared" if cleared_at is not None else "explained" if explained_at is not None else "open",
               "reported_at": reported_at, "facts": json.loads(facts), "decision": json.loads(decision),
               "recovery": json.loads(recovery) if recovery else None,
               "explanation": None if explained_at is None else {
                   "seen": seen, "suspected_cause": cause, "model": model, "explained_at": explained_at,
                   "note": "explanation only; it does not decide or move anything"},
               "cleared": None if cleared_at is None else {"by": cleared_by, "at": cleared_at, "note": note}}
        out["frames"] = [({"role": r, "sha256": h, "jpeg_b64": base64.b64encode(j).decode()} if with_bytes
                          else {"role": r, "sha256": h, "bytes": len(j)}) for r, h, j in frames]
        return out

    def unexplained(self, limit=8) -> list:
        """For the AI PC: open incidents with frames and no explanation yet, oldest first."""
        with self._lock:
            rows = self._rows("cleared_at IS NULL AND explained_at IS NULL", (), None)[::-1][:limit]
            return [self._view(r, True) for r in rows]

    def snapshot(self, source_id) -> list:
        """The console's list: every uncleared incident, then the latest cleared ones. No frame bytes."""
        with self._lock:
            rows = (self._rows("source_id=? AND cleared_at IS NULL", (source_id,))
                    + self._rows("source_id=? AND cleared_at IS NOT NULL", (source_id,), SHOWN_CLEARED))
            return [self._view(r, False) for r in rows]


def install_arm_incident_routes(app, *, service, store, require_viewer, require_named_operator, authorize=None):
    base = "/api/fleet/workcell-observations"

    def source(source_id, token):
        try:
            service.authorize(source_id, token or "")
        except PermissionError:
            raise HTTPException(401, detail={"code": "WORKCELL_OBSERVATION_UNAUTHORIZED"}) from None

    @app.post(base + "/arms/{source_id}/incidents", tags=["workcell-observations"])
    async def report(source_id: str, request: Request, response: Response,
                     token: str | None = Header(None, alias="X-Workcell-Observation-Token")):
        response.headers["Cache-Control"] = "no-store"
        source(source_id, token)
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > ARM_INCIDENT_BODY_BYTES:
                raise HTTPException(413, detail={"code": "WORKCELL_OBSERVATION_TOO_LARGE"})
            data.extend(chunk)
        try:
            parsed = ArmIncidentReport.model_validate_json(data)
        except ValidationError:
            raise HTTPException(422, detail={"code": "INVALID_ARM_INCIDENT"}) from None
        if parsed.source_id != source_id:
            raise HTTPException(422, detail={"code": "INVALID_ARM_INCIDENT"})
        return store.accepted(source_id, store.report(parsed)).model_dump()

    @app.get(base + "/arms/{source_id}/hold", tags=["workcell-observations"])
    def hold(source_id: str, response: Response,
             token: str | None = Header(None, alias="X-Workcell-Observation-Token")):
        response.headers["Cache-Control"] = "no-store"
        source(source_id, token)
        return store.hold(source_id).model_dump()

    @app.post(base + "/arms/{source_id}/incidents/{incident_id}/clear", tags=["workcell-observations"])
    async def clear(source_id: str, incident_id: str, request: Request, response: Response,
                    principal=Depends(require_named_operator)):
        response.headers["Cache-Control"] = "no-store"
        try:
            note = ArmIncidentClear.model_validate(await bounded_json(request))
        except ValidationError:
            raise HTTPException(422, detail={"code": "INVALID_ARM_INCIDENT_CLEAR"}) from None
        try:
            store.clear(source_id, incident_id, note.note, principal.principal_id)
        except KeyError:
            raise HTTPException(404, detail={"code": "ARM_INCIDENT_UNKNOWN"}) from None
        except ValueError:
            raise HTTPException(409, detail={"code": "ARM_INCIDENT_ALREADY_CLEARED"}) from None
        return store.hold(source_id).model_dump()

    @app.get(base + "/arms/{source_id}/incidents/{incident_id}/frames/{role}", tags=["workcell-observations"])
    def frame(source_id: str, incident_id: str, role: str, _principal=Depends(require_viewer)):
        jpeg = store.frame(source_id, incident_id, role) if role in ROLES else None
        if jpeg is None:
            raise HTTPException(404, detail={"code": "ARM_INCIDENT_FRAME_UNKNOWN"})
        return RawResponse(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    if authorize is None:
        return

    def require_ai_observer(principal=Depends(authorize)):
        if principal.role != "ai_observer":
            raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "ai_observer role required"})
        return principal

    @app.get(base + "/arm-incidents/unexplained", tags=["workcell-observations"])
    def unexplained(response: Response, _principal=Depends(require_ai_observer)):
        response.headers["Cache-Control"] = "no-store"
        return {"incidents": store.unexplained()}

    @app.post(base + "/arms/{source_id}/incidents/{incident_id}/explanation", tags=["workcell-observations"])
    async def explanation(source_id: str, incident_id: str, request: Request, response: Response,
                          _principal=Depends(require_ai_observer)):
        response.headers["Cache-Control"] = "no-store"
        try:
            parsed = ArmIncidentExplanation.model_validate(await bounded_json(request))
        except ValidationError:
            raise HTTPException(422, detail={"code": "INVALID_ARM_INCIDENT_EXPLANATION"}) from None
        try:
            store.explain(source_id, incident_id, parsed)
        except KeyError:
            raise HTTPException(404, detail={"code": "ARM_INCIDENT_UNKNOWN"}) from None
        except ValueError:
            raise HTTPException(409, detail={"code": "ARM_INCIDENT_NOT_OPEN_FOR_EXPLANATION"}) from None
        return {"incident_id": incident_id, "explained": True}
