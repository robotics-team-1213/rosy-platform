"""SQLite ledger for OMX arm incidents (D-971)."""
import base64
import json
import re
import sqlite3
import threading
import time
from uuid import uuid4

from core_common.protocol.arm_incident.arm_incidents import (
    ARM_INCIDENT_EVIDENCE_FRAMES, AUTO_CLEAR_MIN_SCORE, ArmIncidentAccepted, ArmIncidentEvidenceFrame,
    ArmIncidentExplanation, ArmIncidentHold, ArmIncidentReport, clearable_after_fold, evaluate_clear_safety,
    machine_clearable, software_stop,
)
from fleet.server.sqlite_policy import configure_connection, enable_wal
from core_common.protocol.arm_incident.home_recovery import HOME_RECOVERY_REASON, is_home_recovery


LISTED_MAX_AGE_S = 2.0  # backstop only; this store's own writes drop the shared list at once
SHOWN_CLEARED = 20  # cleared incidents stay in history; the snapshot shows this many per arm
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
ROLES = ("top", "side")
EVIDENCE_KEEP_S = 14 * 86400  # whole frames of a cleared incident; tip crops, labels and facts stay
REPEAT_WINDOW_S = 86400  # D-1039 window
MACHINE_CLEARS_PER_WINDOW = 3  # D-1047 (was 1): a fourth machine clear of one arm in 24 h goes to a person


class MachineClearRefused(PermissionError):
    def __init__(self, code, reason):
        super().__init__(reason)
        self.code = code


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
            # cleared_kind: D-1039 'machine', else NULL; clear_remeasured: D-1040 the fresh read; clear_risk: risk score JSON
            for column in ("true_cause", "label_basis", "cleared_kind", "clear_remeasured", "clear_risk"):
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
        physical_or_unknown = next((row for row in rows if not is_home_recovery(_facts(row[2]))), None)
        if physical_or_unknown is None:
            return ArmIncidentHold(held=True, incident_ids=[r[0] for r in rows[:64]], reason=HOME_RECOVERY_REASON)
        try:
            why = json.loads(physical_or_unknown[1]).get("reason")
        except ValueError:
            why = None
        why = CONTROL.sub(" ", why)[:300] if isinstance(why, str) and why.strip() else "arm incident not cleared"
        return ArmIncidentHold(held=True, incident_ids=[r[0] for r in rows[:64]],
                               reason=f"{len(rows)} open arm incident(s): {why}")

    def any_hold(self) -> bool:
        with self._lock:
            sources = [r[0] for r in self._db.execute(
                "SELECT DISTINCT source_id FROM arm_incidents WHERE cleared_at IS NULL").fetchall()]
        return any(self.hold(source).held for source in sources)

    def accepted(self, source_id, incident_id) -> ArmIncidentAccepted:
        return ArmIncidentAccepted(incident_id=incident_id, hold=self.hold(source_id))

    def clear(self, source_id, incident_id, note, principal_id, cause=None, basis=None, machine=False,
              remeasured=None, binding=None, recovery=None) -> None:
        """KeyError: no such incident for this arm. ValueError: already cleared (the first record stands).
        machine (D-1039): an AI assessor clears; MachineClearRefused when the stored facts or a machine clear of this
        arm within REPEAT_WINDOW_S keep it for a person. A machine clear is marked and its basis stored as 'unknown',
        so its cause is never scored as truth. remeasured (D-1040): the fresh read of the arm, judged against this
        incident, its reported_at and `binding` (the source's manifest (arm_id, board_id)); kept with a machine clear
        only (a person's clear does not judge it)."""
        with self._lock, self._db:
            self._listed.clear()
            row = self._db.execute("SELECT cleared_at, facts, reported_at, recovery FROM arm_incidents "
                                   "WHERE incident_id=? AND source_id=?", (incident_id, source_id)).fetchone()
            if row is None:
                raise KeyError(incident_id)
            if row[0] is not None:
                raise ValueError("already cleared")
            now = self._wall()
            risk_json = None
            if machine:
                facts = _facts(row[1])
                ok, why = machine_clearable(facts, remeasured, since=row[2], now=now,
                                            incident_id=incident_id, binding=binding)
                if not ok and recovery is not None:  # D-1048: the cell folded the arm home by itself
                    ok, why = clearable_after_fold(facts, recovery, incident_id, row[2])
                if not ok:
                    raise MachineClearRefused("AI_CLEAR_KIND_REFUSED", why)
                done = self._db.execute("SELECT count(*) FROM arm_incidents WHERE source_id=? AND cleared_kind='machine' "
                                        "AND cleared_at>=?", (source_id, now - REPEAT_WINDOW_S)).fetchone()[0]
                if done >= MACHINE_CLEARS_PER_WINDOW:
                    raise MachineClearRefused("AI_CLEAR_REPEAT_LIMIT",
                                              f"{done} machine clears of this arm in the last 24 h")
                risk = evaluate_clear_safety(facts, remeasured=remeasured, recovery=recovery,
                                             recent_clears_24h=done, since=row[2], now=now,
                                             incident_id=incident_id, binding=binding,
                                             min_score=AUTO_CLEAR_MIN_SCORE)
                if not risk["allowed"]:
                    codes = ", ".join(item["code"] for item in (risk["hard_vetoes"] or risk["deductions"]))
                    raise MachineClearRefused(
                        "AI_CLEAR_RISK_SCORE_BELOW_THRESHOLD",
                        f"safety score {risk['safety_score']}/{risk['threshold']} below threshold "
                        f"(risk {risk['risk_score']}): {codes}",
                    )
                risk_json = json.dumps(risk, separators=(",", ":"))
                basis = "unknown"
            self._db.execute("UPDATE arm_incidents SET cleared_by=?, cleared_at=?, clear_note=?, true_cause=?, label_basis=?, "
                             "cleared_kind=?, clear_remeasured=?, clear_risk=? WHERE incident_id=?",
                             (principal_id, now, note, cause, basis, "machine" if machine else None,
                              json.dumps(remeasured) if machine and remeasured is not None else None,
                              risk_json, incident_id))
            if machine and recovery is not None:  # kept beside the device's own recovery: what the fold measured
                kept = {"device": json.loads(row[3]) if row[3] else None, "auto_fold": recovery}
                self._db.execute("UPDATE arm_incidents SET recovery=? WHERE incident_id=?",
                                 (json.dumps(kept, default=str), incident_id))
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
                 "suspected_cause, model, explained_at, cleared_by, cleared_at, clear_note, true_cause, label_basis, cleared_kind, "
                 "clear_remeasured, clear_risk "
                 "FROM arm_incidents "
                 f"WHERE {where} ORDER BY reported_at DESC, rowid DESC" + (f" LIMIT {int(limit)}" if limit else ""))
        return self._db.execute(query, args).fetchall()

    def _view(self, row, with_bytes):
        (incident_id, source_id, session_id, reported_at, facts, decision, recovery, seen, cause, model, explained_at,
         cleared_by, cleared_at, note, true_cause, basis, kind, remeasured, clear_risk) = row
        # the list only needs each frame's size: never read the JPEG blob (up to 200 kB) for it
        frames = self._db.execute(f"SELECT role, sha256, {'jpeg' if with_bytes else 'length(jpeg)'} "
                                  "FROM arm_incident_frames WHERE incident_id=? ORDER BY role DESC",
                                  (incident_id,)).fetchall()
        out = {"incident_id": incident_id, "source_id": source_id, "session_id": session_id,
               "state": "cleared" if cleared_at is not None else "explained" if explained_at is not None else "open",
               "held": cleared_at is None and _holds(decision) and not software_stop(_facts(facts)),
               "reported_at": reported_at, "facts": json.loads(facts), "decision": json.loads(decision),
               "recovery": json.loads(recovery) if recovery else None,
               "explanation": None if explained_at is None else {
                   "seen": seen, "suspected_cause": cause, "model": model, "explained_at": explained_at,
                   "note": "explanation only; it does not decide or move anything"},
               "cleared": None if cleared_at is None else {"by": cleared_by, "at": cleared_at, "note": note,
                                                           "cause": true_cause, "basis": basis,
                                                           "kind": kind or "person",
                                                           "remeasured": json.loads(remeasured) if remeasured else None,
                                                           **({"risk": json.loads(clear_risk)} if clear_risk else {})}}
        if is_home_recovery(out["facts"]):
            out["event_kind"] = "home_recovery"
            out["decision"]["reason"] = HOME_RECOVERY_REASON
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
