"""D-793 learned-policy governance ledger: stages, approval windows, confirmations, incidents, leases.

Training never changes execution authority. A policy enters at L0 and moves one stage at a time
only through a recorded human approval; stages that move the real arm need an approver other
than the proposer. An approval window bounds when a policy may run; a runtime lease (1 s
default, 2 s cap) never outlives its window. An open confirmation request or incident blocks
new leases, so execution stops at the next renewal. Nothing here sends a command to a device.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Mapping

from fleet.server.sqlite_policy import configure_connection, enable_wal

STAGES = ("L0", "L1", "L2", "L3", "LIMITED")
# Stages whose approval opens real-arm motion need two different people (D-793 1).
TWO_PERSON_STAGES = {"L3", "LIMITED"}
# kind -> (minimum stage, default minutes, maximum minutes, two-person approval, runtime lease)
WINDOW_KINDS = {
    "shadow": ("L2", 480, 480, False, False),
    "supervised": ("L3", 15, 30, True, True),
    "limited": ("LIMITED", 480, 480, True, True),
}
LEASE_DEFAULT_MS, LEASE_MAX_MS = 1000, 2000
REASONS = ("new_policy", "revision_mismatch", "environment_out_of_range", "policy_output_rejected",
           "target_not_reached", "timing_budget_exceeded", "owner_fault", "owner_hold", "other")
RESOLUTIONS = ("resume", "abort", "send_to_learning")
_MAX_EVIDENCE_BYTES = 8 * 1024


class GovernanceError(ValueError):
    """A rule refusal; `code` is the API error code and `status` its HTTP status."""

    def __init__(self, code: str, status: int = 409):
        super().__init__(code)
        self.code, self.status = code, status


def _id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(8)}"


def _evidence(value: Mapping[str, Any] | None) -> str:
    text = json.dumps(dict(value or {}), sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(text.encode()) > _MAX_EVIDENCE_BYTES:
        raise GovernanceError("EVIDENCE_TOO_LARGE", 422)
    return text


class PolicyGovernanceStore:
    def __init__(self, path: Path | str, *, clock=time.time_ns) -> None:
        self.path, self._clock = Path(path), clock
        with closing(self._connect()) as db:
            enable_wal(db)
            db.executescript("""
                CREATE TABLE IF NOT EXISTS fleet_policy_stage (
                    workcell_id TEXT NOT NULL, policy_revision TEXT NOT NULL, stage TEXT NOT NULL,
                    rig_revision TEXT NOT NULL, calibration_revision TEXT NOT NULL, updated_ns INTEGER NOT NULL,
                    PRIMARY KEY (workcell_id, policy_revision));
                CREATE TABLE IF NOT EXISTS fleet_policy_proposal (
                    proposal_id TEXT PRIMARY KEY, workcell_id TEXT NOT NULL, policy_revision TEXT NOT NULL,
                    from_stage TEXT, to_stage TEXT NOT NULL, rig_revision TEXT NOT NULL,
                    calibration_revision TEXT NOT NULL, evidence_sha256 TEXT NOT NULL, note TEXT NOT NULL,
                    proposed_by TEXT NOT NULL, proposed_ns INTEGER NOT NULL, state TEXT NOT NULL,
                    decided_by TEXT, decided_ns INTEGER);
                CREATE TABLE IF NOT EXISTS fleet_policy_window (
                    window_id TEXT PRIMARY KEY, workcell_id TEXT NOT NULL, policy_revision TEXT NOT NULL,
                    kind TEXT NOT NULL, minutes INTEGER NOT NULL, scope TEXT NOT NULL,
                    requested_by TEXT NOT NULL, requested_ns INTEGER NOT NULL, approved_by TEXT,
                    starts_ns INTEGER, expires_ns INTEGER, closed_ns INTEGER, closed_reason TEXT);
                CREATE TABLE IF NOT EXISTS fleet_policy_confirmation (
                    confirmation_id TEXT PRIMARY KEY, workcell_id TEXT NOT NULL, policy_revision TEXT,
                    reason TEXT NOT NULL, evidence_json TEXT NOT NULL, created_by TEXT NOT NULL,
                    created_ns INTEGER NOT NULL, resolution TEXT, note TEXT, resolved_by TEXT, resolved_ns INTEGER);
                CREATE TABLE IF NOT EXISTS fleet_policy_incident (
                    incident_id TEXT PRIMARY KEY, workcell_id TEXT NOT NULL, description TEXT NOT NULL,
                    reported_by TEXT NOT NULL, reported_ns INTEGER NOT NULL,
                    cleared_by TEXT, cleared_ns INTEGER, clear_note TEXT);
                CREATE TABLE IF NOT EXISTS fleet_policy_lease (
                    lease_id TEXT PRIMARY KEY, window_id TEXT NOT NULL, episode_id TEXT NOT NULL,
                    owner_session_id TEXT NOT NULL, issued_ns INTEGER NOT NULL, expires_ns INTEGER NOT NULL);
            """)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return configure_connection(connection)

    def _tx(self):
        db = self._connect()
        db.execute("BEGIN IMMEDIATE")
        return db

    def _run(self, fn):
        with closing(self._tx()) as db:
            try:
                result = fn(db, self._clock())
            except BaseException:
                db.execute("ROLLBACK")
                raise
            db.execute("COMMIT")
            return result

    # --- reads ---------------------------------------------------------------------------------

    @staticmethod
    def _rows(db, sql, *args):
        return [dict(row) for row in db.execute(sql, args)]

    def _open_incident(self, db, workcell_id):
        return db.execute("SELECT incident_id FROM fleet_policy_incident WHERE workcell_id=? AND cleared_ns IS NULL",
                          (workcell_id,)).fetchone()

    def _active_window(self, db, workcell_id, now):
        return db.execute("SELECT * FROM fleet_policy_window WHERE workcell_id=? AND approved_by IS NOT NULL "
                          "AND closed_ns IS NULL AND expires_ns>?", (workcell_id, now)).fetchone()

    def belongs(self, table: str, key: str, value: str, workcell_id: str) -> bool:
        tables = {"proposals": ("fleet_policy_proposal", "proposal_id"), "windows": ("fleet_policy_window", "window_id"),
                  "confirmations": ("fleet_policy_confirmation", "confirmation_id"),
                  "incidents": ("fleet_policy_incident", "incident_id")}
        name, column = tables[table]
        if column != key:
            raise ValueError("unknown governance key")
        with closing(self._connect()) as db:
            return db.execute(f"SELECT 1 FROM {name} WHERE {column}=? AND workcell_id=?",
                              (value, workcell_id)).fetchone() is not None

    def snapshot(self, workcell_id: str) -> dict:
        with closing(self._connect()) as db:
            now = self._clock()
            windows = self._rows(db, "SELECT * FROM fleet_policy_window WHERE workcell_id=? "
                                     "ORDER BY requested_ns DESC LIMIT 20", workcell_id)
            for window in windows:
                window["active"] = bool(window["approved_by"] and window["closed_ns"] is None
                                        and window["expires_ns"] > now)
            confirmations = self._rows(db, "SELECT * FROM fleet_policy_confirmation WHERE workcell_id=? "
                                           "ORDER BY created_ns DESC LIMIT 50", workcell_id)
            for row in confirmations:
                row["evidence"] = json.loads(row.pop("evidence_json"))
            return {
                "workcell_id": workcell_id, "now_ns": now,
                "policies": self._rows(db, "SELECT * FROM fleet_policy_stage WHERE workcell_id=? "
                                           "ORDER BY updated_ns DESC", workcell_id),
                "proposals": self._rows(db, "SELECT * FROM fleet_policy_proposal WHERE workcell_id=? "
                                            "ORDER BY proposed_ns DESC LIMIT 50", workcell_id),
                "windows": windows, "confirmations": confirmations,
                "incidents": self._rows(db, "SELECT * FROM fleet_policy_incident WHERE workcell_id=? "
                                            "ORDER BY reported_ns DESC LIMIT 20", workcell_id),
                "rules": {"stages": list(STAGES), "two_person_stages": sorted(TWO_PERSON_STAGES),
                          "windows": {k: dict(min_stage=v[0], default_minutes=v[1], max_minutes=v[2],
                                              two_person=v[3], runtime_lease=v[4]) for k, v in WINDOW_KINDS.items()},
                          "lease_default_ms": LEASE_DEFAULT_MS, "lease_max_ms": LEASE_MAX_MS,
                          "reasons": list(REASONS), "resolutions": list(RESOLUTIONS)},
            }

    # --- stages --------------------------------------------------------------------------------

    def propose(self, *, workcell_id, policy_revision, to_stage, rig_revision, calibration_revision,
                evidence_sha256, note, principal_id) -> dict:
        if to_stage not in STAGES:
            raise GovernanceError("UNKNOWN_STAGE", 422)

        def fn(db, now):
            current = db.execute("SELECT * FROM fleet_policy_stage WHERE workcell_id=? AND policy_revision=?",
                                 (workcell_id, policy_revision)).fetchone()
            from_stage = current["stage"] if current else None
            expected = STAGES[STAGES.index(from_stage)+1] if from_stage in STAGES[:-1] else (
                None if from_stage else "L0")
            if to_stage != expected:
                raise GovernanceError("STAGE_SKIP_REFUSED")
            if current and (current["rig_revision"], current["calibration_revision"]) != (
                    rig_revision, calibration_revision):
                raise GovernanceError("REVISION_CHANGED_REREGISTER_REQUIRED")
            if to_stage in TWO_PERSON_STAGES and self._open_incident(db, workcell_id):
                raise GovernanceError("INCIDENT_OPEN")
            if db.execute("SELECT 1 FROM fleet_policy_proposal WHERE workcell_id=? AND policy_revision=? "
                          "AND state='PENDING'", (workcell_id, policy_revision)).fetchone():
                raise GovernanceError("PROPOSAL_ALREADY_PENDING")
            row = dict(proposal_id=_id("prop"), workcell_id=workcell_id, policy_revision=policy_revision,
                       from_stage=from_stage, to_stage=to_stage, rig_revision=rig_revision,
                       calibration_revision=calibration_revision, evidence_sha256=evidence_sha256, note=note,
                       proposed_by=principal_id, proposed_ns=now, state="PENDING", decided_by=None, decided_ns=None)
            db.execute(f"INSERT INTO fleet_policy_proposal ({','.join(row)}) VALUES ({','.join('?'*len(row))})",
                       tuple(row.values()))
            return row
        return self._run(fn)

    def decide(self, *, proposal_id, approve: bool, principal_id) -> dict:
        def fn(db, now):
            row = db.execute("SELECT * FROM fleet_policy_proposal WHERE proposal_id=?", (proposal_id,)).fetchone()
            if row is None:
                raise GovernanceError("PROPOSAL_NOT_FOUND", 404)
            if row["state"] != "PENDING":
                raise GovernanceError("PROPOSAL_ALREADY_DECIDED")
            if approve and row["to_stage"] in TWO_PERSON_STAGES and row["proposed_by"] == principal_id:
                raise GovernanceError("APPROVER_MUST_DIFFER_FROM_PROPOSER", 403)
            if approve and row["to_stage"] in TWO_PERSON_STAGES and self._open_incident(db, row["workcell_id"]):
                raise GovernanceError("INCIDENT_OPEN")
            state = "APPROVED" if approve else "REJECTED"
            db.execute("UPDATE fleet_policy_proposal SET state=?, decided_by=?, decided_ns=? WHERE proposal_id=?",
                       (state, principal_id, now, proposal_id))
            if approve:
                db.execute("INSERT INTO fleet_policy_stage VALUES (?,?,?,?,?,?) ON CONFLICT(workcell_id, "
                           "policy_revision) DO UPDATE SET stage=excluded.stage, updated_ns=excluded.updated_ns",
                           (row["workcell_id"], row["policy_revision"], row["to_stage"], row["rig_revision"],
                            row["calibration_revision"], now))
            return dict(row, state=state, decided_by=principal_id, decided_ns=now)
        return self._run(fn)

    # --- approval windows and leases -----------------------------------------------------------

    def request_window(self, *, workcell_id, policy_revision, kind, minutes, scope, rig_revision,
                       calibration_revision, principal_id) -> dict:
        if kind not in WINDOW_KINDS:
            raise GovernanceError("UNKNOWN_WINDOW_KIND", 422)
        min_stage, default, maximum, _, _ = WINDOW_KINDS[kind]
        minutes = default if minutes is None else minutes
        if not 1 <= minutes <= maximum:
            raise GovernanceError("WINDOW_TOO_LONG", 422)

        def fn(db, now):
            stage = db.execute("SELECT * FROM fleet_policy_stage WHERE workcell_id=? AND policy_revision=?",
                               (workcell_id, policy_revision)).fetchone()
            if stage is None or STAGES.index(stage["stage"]) < STAGES.index(min_stage):
                raise GovernanceError("STAGE_TOO_LOW")
            if (stage["rig_revision"], stage["calibration_revision"]) != (rig_revision, calibration_revision):
                raise GovernanceError("REVISION_CHANGED_REAPPROVAL_REQUIRED")
            if self._open_incident(db, workcell_id):
                raise GovernanceError("INCIDENT_OPEN")
            row = dict(window_id=_id("win"), workcell_id=workcell_id, policy_revision=policy_revision, kind=kind,
                       minutes=minutes, scope=scope, requested_by=principal_id, requested_ns=now, approved_by=None,
                       starts_ns=None, expires_ns=None, closed_ns=None, closed_reason=None)
            db.execute(f"INSERT INTO fleet_policy_window ({','.join(row)}) VALUES ({','.join('?'*len(row))})",
                       tuple(row.values()))
            return row
        return self._run(fn)

    def approve_window(self, *, window_id, principal_id) -> dict:
        def fn(db, now):
            row = db.execute("SELECT * FROM fleet_policy_window WHERE window_id=?", (window_id,)).fetchone()
            if row is None:
                raise GovernanceError("WINDOW_NOT_FOUND", 404)
            if row["approved_by"] is not None or row["closed_ns"] is not None:
                raise GovernanceError("WINDOW_ALREADY_DECIDED")
            if WINDOW_KINDS[row["kind"]][3] and row["requested_by"] == principal_id:
                raise GovernanceError("APPROVER_MUST_DIFFER_FROM_PROPOSER", 403)
            if self._open_incident(db, row["workcell_id"]):
                raise GovernanceError("INCIDENT_OPEN")
            if self._active_window(db, row["workcell_id"], now) is not None:
                raise GovernanceError("ANOTHER_WINDOW_ACTIVE")
            expires = now + row["minutes"] * 60_000_000_000
            db.execute("UPDATE fleet_policy_window SET approved_by=?, starts_ns=?, expires_ns=? WHERE window_id=?",
                       (principal_id, now, expires, window_id))
            return dict(row, approved_by=principal_id, starts_ns=now, expires_ns=expires, active=True)
        return self._run(fn)

    @staticmethod
    def _close_windows(db, workcell_id, now, reason):
        db.execute("UPDATE fleet_policy_window SET closed_ns=?, closed_reason=? WHERE workcell_id=? "
                   "AND closed_ns IS NULL", (now, reason, workcell_id))

    def close_window(self, *, window_id, reason, principal_id) -> dict:
        def fn(db, now):
            row = db.execute("SELECT * FROM fleet_policy_window WHERE window_id=?", (window_id,)).fetchone()
            if row is None:
                raise GovernanceError("WINDOW_NOT_FOUND", 404)
            if row["closed_ns"] is None:
                db.execute("UPDATE fleet_policy_window SET closed_ns=?, closed_reason=? WHERE window_id=?",
                           (now, f"closed by {principal_id}: {reason}", window_id))
            return dict(db.execute("SELECT * FROM fleet_policy_window WHERE window_id=?", (window_id,)).fetchone())
        return self._run(fn)

    def issue_lease(self, *, workcell_id, episode_id, owner_session_id, duration_ms, lease_id=None) -> dict:
        if not 1 <= duration_ms <= LEASE_MAX_MS:
            raise GovernanceError("LEASE_TOO_LONG", 422)

        def fn(db, now):
            window = self._active_window(db, workcell_id, now)
            if window is None or not WINDOW_KINDS[window["kind"]][4]:
                raise GovernanceError("NO_ACTIVE_EXECUTION_WINDOW")
            if self._open_incident(db, workcell_id):
                raise GovernanceError("INCIDENT_OPEN")
            if db.execute("SELECT 1 FROM fleet_policy_confirmation WHERE workcell_id=? AND resolution IS NULL",
                          (workcell_id,)).fetchone():
                raise GovernanceError("CONFIRMATION_PENDING")
            stage = db.execute("SELECT * FROM fleet_policy_stage WHERE workcell_id=? AND policy_revision=?",
                               (workcell_id, window["policy_revision"])).fetchone()
            if stage is None or STAGES.index(stage["stage"]) < STAGES.index(WINDOW_KINDS[window["kind"]][0]):
                raise GovernanceError("STAGE_TOO_LOW")
            expires = min(now + duration_ms * 1_000_000, window["expires_ns"])
            if lease_id is None:
                lease = dict(lease_id=_id("lease"), window_id=window["window_id"], episode_id=episode_id,
                             owner_session_id=owner_session_id, issued_ns=now, expires_ns=expires)
                db.execute("INSERT INTO fleet_policy_lease VALUES (?,?,?,?,?,?)", tuple(lease.values()))
            else:
                old = db.execute("SELECT * FROM fleet_policy_lease WHERE lease_id=?", (lease_id,)).fetchone()
                if old is None or (old["window_id"], old["episode_id"], old["owner_session_id"]) != (
                        window["window_id"], episode_id, owner_session_id) or expires <= old["expires_ns"]:
                    raise GovernanceError("LEASE_RENEWAL_REFUSED")
                db.execute("UPDATE fleet_policy_lease SET issued_ns=?, expires_ns=? WHERE lease_id=?",
                           (now, expires, lease_id))
                lease = dict(old, issued_ns=now, expires_ns=expires)
            return dict(lease, workcell_id=workcell_id, policy_revision=window["policy_revision"],
                        clock="fleet_wall_ns", device_delivery="not_connected")
        return self._run(fn)

    # --- confirmations and incidents -----------------------------------------------------------

    def open_confirmation(self, *, workcell_id, reason, policy_revision, evidence, principal_id) -> dict:
        if reason not in REASONS:
            raise GovernanceError("UNKNOWN_REASON", 422)
        text = _evidence(evidence)

        def fn(db, now):
            row = dict(confirmation_id=_id("conf"), workcell_id=workcell_id, policy_revision=policy_revision,
                       reason=reason, evidence_json=text, created_by=principal_id, created_ns=now,
                       resolution=None, note=None, resolved_by=None, resolved_ns=None)
            db.execute(f"INSERT INTO fleet_policy_confirmation ({','.join(row)}) "
                       f"VALUES ({','.join('?'*len(row))})", tuple(row.values()))
            return dict(row, evidence=json.loads(row.pop("evidence_json")))
        return self._run(fn)

    def sync_owner_hold(self, *, workcell_id, owner_state: Mapping[str, Any], principal_id) -> dict | None:
        """One open confirmation per observed owner HOLD sequence; nothing when the owner is not held."""
        owner = owner_state.get("owner") or {}
        if owner.get("state") != "hold":
            return None
        evidence = dict(owner=owner, instance_id=owner_state.get("instance_id"))
        digest = hashlib.sha256(_evidence(evidence).encode()).hexdigest()
        with closing(self._connect()) as db:
            for row in db.execute("SELECT evidence_json FROM fleet_policy_confirmation WHERE workcell_id=? "
                                  "AND reason='owner_hold' AND resolution IS NULL", (workcell_id,)):
                if hashlib.sha256(row["evidence_json"].encode()).hexdigest() == digest:
                    return None
        return self.open_confirmation(workcell_id=workcell_id, reason="owner_hold", policy_revision=None,
                                      evidence=evidence, principal_id=principal_id)

    def resolve_confirmation(self, *, confirmation_id, resolution, note, demote_to, principal_id) -> dict:
        if resolution not in RESOLUTIONS:
            raise GovernanceError("UNKNOWN_RESOLUTION", 422)

        def fn(db, now):
            row = db.execute("SELECT * FROM fleet_policy_confirmation WHERE confirmation_id=?",
                             (confirmation_id,)).fetchone()
            if row is None:
                raise GovernanceError("CONFIRMATION_NOT_FOUND", 404)
            if row["resolution"] is not None:
                raise GovernanceError("CONFIRMATION_ALREADY_RESOLVED")
            if resolution != "resume":
                self._close_windows(db, row["workcell_id"], now, f"{resolution} of {confirmation_id}")
            if resolution == "send_to_learning" and row["policy_revision"]:
                target = demote_to or "L1"
                stage = db.execute("SELECT stage FROM fleet_policy_stage WHERE workcell_id=? AND policy_revision=?",
                                   (row["workcell_id"], row["policy_revision"])).fetchone()
                if target not in STAGES or (stage and STAGES.index(target) > STAGES.index(stage["stage"])):
                    raise GovernanceError("DEMOTION_MUST_LOWER_STAGE", 422)
                if stage:
                    db.execute("UPDATE fleet_policy_stage SET stage=?, updated_ns=? WHERE workcell_id=? "
                               "AND policy_revision=?", (target, now, row["workcell_id"], row["policy_revision"]))
            db.execute("UPDATE fleet_policy_confirmation SET resolution=?, note=?, resolved_by=?, resolved_ns=? "
                       "WHERE confirmation_id=?", (resolution, note, principal_id, now, confirmation_id))
            result = dict(db.execute("SELECT * FROM fleet_policy_confirmation WHERE confirmation_id=?",
                                     (confirmation_id,)).fetchone())
            result["evidence"] = json.loads(result.pop("evidence_json"))
            return result
        return self._run(fn)

    def report_incident(self, *, workcell_id, description, principal_id) -> dict:
        def fn(db, now):
            self._close_windows(db, workcell_id, now, "incident reported")
            row = dict(incident_id=_id("inc"), workcell_id=workcell_id, description=description,
                       reported_by=principal_id, reported_ns=now, cleared_by=None, cleared_ns=None, clear_note=None)
            db.execute("INSERT INTO fleet_policy_incident VALUES (?,?,?,?,?,?,?,?)", tuple(row.values()))
            return row
        return self._run(fn)

    def clear_incident(self, *, incident_id, note, principal_id) -> dict:
        def fn(db, now):
            row = db.execute("SELECT * FROM fleet_policy_incident WHERE incident_id=?", (incident_id,)).fetchone()
            if row is None:
                raise GovernanceError("INCIDENT_NOT_FOUND", 404)
            if row["cleared_ns"] is not None:
                raise GovernanceError("INCIDENT_ALREADY_CLEARED")
            if row["reported_by"] == principal_id:
                raise GovernanceError("APPROVER_MUST_DIFFER_FROM_PROPOSER", 403)
            db.execute("UPDATE fleet_policy_incident SET cleared_by=?, cleared_ns=?, clear_note=? "
                       "WHERE incident_id=?", (principal_id, now, note, incident_id))
            return dict(row, cleared_by=principal_id, cleared_ns=now, clear_note=note)
        return self._run(fn)
