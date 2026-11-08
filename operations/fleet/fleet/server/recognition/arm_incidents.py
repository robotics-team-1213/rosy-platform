"""D-971: OMX arm incidents. The control PC reports, the AI PC explains, a named operator clears; Fleet keeps the ledger.

OPEN -> (EXPLAINED) -> CLEARED, in the shared Fleet SQLite DB. An arm with an incident that is not CLEARED is held: the
control PC asks before a session and does not start one. A hold is not a command and not a Cell Job claim (D-779).
The explanation is stored and shown, never acted on. Nothing is deleted."""
import asyncio
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
    ARM_INCIDENT_BODY_BYTES, ARM_INCIDENT_EVIDENCE_FRAMES, ARM_INCIDENT_FRAME_BYTES, ArmIncidentAccepted, ArmIncidentClear,
    ArmIncidentEvidenceFrame, ArmIncidentExplanation, ArmIncidentHold, ArmIncidentReport, software_stop)
from fleet.server.camera_peer_routes import body as bounded_json
from fleet.server.sqlite_policy import configure_connection, enable_wal

LISTED_MAX_AGE_S = 2.0  # backstop only; this store's own writes drop the shared list at once
SHOWN_CLEARED = 20  # cleared incidents stay in history; the snapshot shows this many per arm
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
ROLES = ("top", "side")
EVIDENCE_KEEP_S = 14 * 86400  # whole frames of a cleared incident; tip crops, labels and facts stay
EVIDENCE_BODY_BYTES = ARM_INCIDENT_FRAME_BYTES * 4 // 3 + 4096


def _facts(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return None  # unreadable: the decision alone decides


def _holds(decision: str) -> bool:
    try:
        return json.loads(decision).get("hold") is not False
    except (ValueError, AttributeError):
        return True  # unreadable: hold, as before


class ArmIncidentStore:
    def __init__(self, path=None, *, wall=time.time, monotonic=time.monotonic):
        self._wall, self._lock, self._monotonic = wall, threading.Lock(), monotonic
        self._listed: dict = {}  # source_id -> (monotonic time, list); see snapshot()
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
            # the person's cause and its basis (cleared with them), and the frames of the seconds around the stop
            have = {r[1] for r in self._db.execute("PRAGMA table_info(arm_incidents)")}
            for column in ("true_cause", "label_basis"):
                if column not in have:
                    self._db.execute(f"ALTER TABLE arm_incidents ADD COLUMN {column} TEXT")
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS arm_incident_evidence (incident_id TEXT NOT NULL, seq INTEGER NOT NULL, "
                "camera TEXT NOT NULL, t_rel_s REAL NOT NULL, kind TEXT NOT NULL, sha256 TEXT NOT NULL, jpeg BLOB NOT NULL, "
                "PRIMARY KEY (incident_id, seq), UNIQUE (incident_id, sha256))")

    def report(self, report: ArmIncidentReport) -> str:
        """Store one report; the same (source, session) again is the same incident and changes nothing."""
        with self._lock, self._db:
            self._listed.clear()
            row = self._db.execute("SELECT incident_id FROM arm_incidents WHERE source_id=? AND session_id=?",
                                   (report.source_id, report.session_id)).fetchone()
            if row:
                return row[0]
            self._expire()  # every report and upload, not only a clear: a quiet ledger still lets old frames go (review)
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
            rows = self._db.execute("SELECT incident_id, decision, facts FROM arm_incidents WHERE source_id=? "
                                    "AND cleared_at IS NULL ORDER BY reported_at, rowid", (source_id,)).fetchall()
        # a report whose decision does not hold (a guard stop the recovery handled, sent for a person's cause) waits for
        # its label and never holds the arm; every report before 2026-11-08 held
        # software_stop: the control PC's own rule on the stored facts, so incidents reported before it stop holding too
        rows = [r for r in rows if _holds(r[1]) and not software_stop(_facts(r[2]))]
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

    def clear(self, source_id, incident_id, note, principal_id, cause=None, basis=None) -> None:
        """KeyError: no such incident for this arm. ValueError: already cleared (the first record stands)."""
        with self._lock, self._db:
            self._listed.clear()
            row = self._db.execute("SELECT cleared_at FROM arm_incidents WHERE incident_id=? AND source_id=?",
                                   (incident_id, source_id)).fetchone()
            if row is None:
                raise KeyError(incident_id)
            if row[0] is not None:
                raise ValueError("already cleared")
            self._db.execute("UPDATE arm_incidents SET cleared_by=?, cleared_at=?, clear_note=?, true_cause=?, label_basis=? "
                             "WHERE incident_id=?", (principal_id, self._wall(), note, cause, basis, incident_id))
            self._expire()

    def add_evidence(self, source_id, incident_id, frame: ArmIncidentEvidenceFrame) -> int:
        """One frame of the seconds around the stop; the same frame again changes nothing. KeyError: no such incident for
        this arm. OverflowError: the incident has ARM_INCIDENT_EVIDENCE_FRAMES already."""
        with self._lock, self._db:
            self._listed.clear()
            if self._db.execute("SELECT 1 FROM arm_incidents WHERE incident_id=? AND source_id=?",
                                (incident_id, source_id)).fetchone() is None:
                raise KeyError(incident_id)
            had = self._db.execute("SELECT seq FROM arm_incident_evidence WHERE incident_id=? AND sha256=?",
                                   (incident_id, frame.sha256)).fetchone()
            if had:
                return had[0]
            self._expire()
            n = self._db.execute("SELECT count(*) FROM arm_incident_evidence WHERE incident_id=?", (incident_id,)).fetchone()[0]
            if n >= ARM_INCIDENT_EVIDENCE_FRAMES:
                raise OverflowError(incident_id)
            self._db.execute("INSERT INTO arm_incident_evidence VALUES (?,?,?,?,?,?,?)",
                             (incident_id, n, frame.camera, frame.t_rel_s, frame.kind, frame.sha256,
                              base64.b64decode(frame.jpeg_b64)))
            return n

    def evidence_frame(self, source_id, incident_id, seq):
        with self._lock:
            row = self._db.execute(
                "SELECT e.jpeg FROM arm_incident_evidence e JOIN arm_incidents i USING (incident_id) "
                "WHERE i.source_id=? AND e.incident_id=? AND e.seq=?", (source_id, incident_id, seq)).fetchone()
        return row[0] if row else None

    def _expire(self) -> None:
        """Whole frames of incidents cleared EVIDENCE_KEEP_S ago go; the jaw-tip crops, the label and the facts stay."""
        self._db.execute("DELETE FROM arm_incident_evidence WHERE kind='full' AND incident_id IN "
                         "(SELECT incident_id FROM arm_incidents WHERE cleared_at < ?)", (self._wall() - EVIDENCE_KEEP_S,))

    def labelled(self, limit=200) -> list:
        """For learning (the model PC's export): cleared incidents with a cause, newest first; frame list without bytes."""
        with self._lock:
            return [self._view(r, False) for r in self._rows("cleared_at IS NOT NULL AND true_cause IS NOT NULL", (), limit)]

    def explain(self, source_id, incident_id, explanation: ArmIncidentExplanation) -> None:
        """KeyError: no such incident. ValueError: already explained or cleared (the first explanation stands)."""
        with self._lock, self._db:
            self._listed.clear()
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
                 "suspected_cause, model, explained_at, cleared_by, cleared_at, clear_note, true_cause, label_basis FROM arm_incidents "
                 f"WHERE {where} ORDER BY reported_at DESC, rowid DESC" + (f" LIMIT {int(limit)}" if limit else ""))
        return self._db.execute(query, args).fetchall()

    def _view(self, row, with_bytes):
        (incident_id, source_id, session_id, reported_at, facts, decision, recovery, seen, cause, model, explained_at,
         cleared_by, cleared_at, note, true_cause, basis) = row
        # the list only needs each frame's size: never read the JPEG blob (up to 200 kB) for it
        frames = self._db.execute(f"SELECT role, sha256, {'jpeg' if with_bytes else 'length(jpeg)'} "
                                  "FROM arm_incident_frames WHERE incident_id=? ORDER BY role DESC",
                                  (incident_id,)).fetchall()
        out = {"incident_id": incident_id, "source_id": source_id, "session_id": session_id,
               "state": "cleared" if cleared_at is not None else "explained" if explained_at is not None else "open",
               "reported_at": reported_at, "facts": json.loads(facts), "decision": json.loads(decision),
               "recovery": json.loads(recovery) if recovery else None,
               "explanation": None if explained_at is None else {
                   "seen": seen, "suspected_cause": cause, "model": model, "explained_at": explained_at,
                   "note": "explanation only; it does not decide or move anything"},
               "cleared": None if cleared_at is None else {"by": cleared_by, "at": cleared_at, "note": note,
                                                           "cause": true_cause, "basis": basis}}
        out["frames"] = [({"role": r, "sha256": h, "jpeg_b64": base64.b64encode(j).decode()} if with_bytes
                          else {"role": r, "sha256": h, "bytes": j}) for r, h, j in frames]
        out["evidence"] = [{"seq": s, "camera": c, "t_rel_s": t, "kind": k, "sha256": h, "bytes": n} for s, c, t, k, h, n in
                           self._db.execute("SELECT seq, camera, t_rel_s, kind, sha256, length(jpeg) FROM arm_incident_evidence "
                                            "WHERE incident_id=? ORDER BY kind DESC, camera, t_rel_s", (incident_id,))]
        return out

    def unexplained(self, limit=8) -> list:
        """For the AI PC: open incidents with frames and no explanation yet, oldest first."""
        with self._lock:
            rows = self._rows("cleared_at IS NULL AND explained_at IS NULL", (), None)[::-1][:limit]
            return [self._view(r, True) for r in rows]

    def snapshot(self, source_id) -> list:
        """The console's list: every uncleared incident, then the latest cleared ones. No frame bytes.

        Every open console tab asks for this each 500 ms, so it is read once and shared until this store
        writes or ``LISTED_MAX_AGE_S`` passes. Callers must not modify the returned list."""
        with self._lock:
            now, hit = self._monotonic(), self._listed.get(source_id)
            if hit is not None and now - hit[0] < LISTED_MAX_AGE_S:
                return hit[1]
            rows = (self._rows("source_id=? AND cleared_at IS NULL", (source_id,))
                    + self._rows("source_id=? AND cleared_at IS NOT NULL", (source_id,), SHOWN_CLEARED))
            listed = [self._view(r, False) for r in rows]
            self._listed[source_id] = (now, listed)
            return listed


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
        # a blocked loop holds every robot's heartbeat reply: store waits run off the loop
        accepted = await asyncio.to_thread(lambda: store.accepted(source_id, store.report(parsed)))
        return accepted.model_dump()

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
            await asyncio.to_thread(store.clear, source_id, incident_id, note.note, principal.principal_id, note.cause, note.basis)
        except KeyError:
            raise HTTPException(404, detail={"code": "ARM_INCIDENT_UNKNOWN"}) from None
        except ValueError:
            raise HTTPException(409, detail={"code": "ARM_INCIDENT_ALREADY_CLEARED"}) from None
        return (await asyncio.to_thread(store.hold, source_id)).model_dump()

    @app.post(base + "/arms/{source_id}/incidents/{incident_id}/evidence", tags=["workcell-observations"])
    async def evidence(source_id: str, incident_id: str, request: Request, response: Response,
                       token: str | None = Header(None, alias="X-Workcell-Observation-Token")):
        response.headers["Cache-Control"] = "no-store"
        source(source_id, token)
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > EVIDENCE_BODY_BYTES:
                raise HTTPException(413, detail={"code": "WORKCELL_OBSERVATION_TOO_LARGE"})
            data.extend(chunk)
        try:
            parsed = ArmIncidentEvidenceFrame.model_validate_json(data)
        except ValidationError:
            raise HTTPException(422, detail={"code": "INVALID_ARM_INCIDENT_EVIDENCE"}) from None
        try:
            seq = await asyncio.to_thread(store.add_evidence, source_id, incident_id, parsed)
        except KeyError:
            raise HTTPException(404, detail={"code": "ARM_INCIDENT_UNKNOWN"}) from None
        except OverflowError:
            raise HTTPException(409, detail={"code": "ARM_INCIDENT_EVIDENCE_FULL"}) from None
        return {"incident_id": incident_id, "seq": seq}

    @app.get(base + "/arms/{source_id}/incidents/{incident_id}/evidence/{seq}", tags=["workcell-observations"])
    def evidence_frame(source_id: str, incident_id: str, seq: int, _principal=Depends(require_viewer)):
        jpeg = store.evidence_frame(source_id, incident_id, seq)
        if jpeg is None:
            raise HTTPException(404, detail={"code": "ARM_INCIDENT_FRAME_UNKNOWN"})
        return RawResponse(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

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

    @app.get(base + "/arm-incidents/labelled", tags=["workcell-observations"])
    def labelled(response: Response, _principal=Depends(require_ai_observer)):
        # learning reads what people cleared with a cause; the model PC pulls it through the same observer seat (D-516)
        response.headers["Cache-Control"] = "no-store"
        return {"incidents": store.labelled()}

    @app.post(base + "/arms/{source_id}/incidents/{incident_id}/explanation", tags=["workcell-observations"])
    async def explanation(source_id: str, incident_id: str, request: Request, response: Response,
                          _principal=Depends(require_ai_observer)):
        response.headers["Cache-Control"] = "no-store"
        try:
            parsed = ArmIncidentExplanation.model_validate(await bounded_json(request))
        except ValidationError:
            raise HTTPException(422, detail={"code": "INVALID_ARM_INCIDENT_EXPLANATION"}) from None
        try:
            await asyncio.to_thread(store.explain, source_id, incident_id, parsed)
        except KeyError:
            raise HTTPException(404, detail={"code": "ARM_INCIDENT_UNKNOWN"}) from None
        except ValueError:
            raise HTTPException(409, detail={"code": "ARM_INCIDENT_NOT_OPEN_FOR_EXPLANATION"}) from None
        return {"incident_id": incident_id, "explained": True}
