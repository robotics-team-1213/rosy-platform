"""Versioned, ordered Fleet journal for fixed-cell transfer Missions (D-403)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from core_common.protocol.schemas import FleetCellTransferGrant

from .dispatch_admission import release as release_claims
from .dispatch_admission import reserve as reserve_claims
from .dispatch_admission import normalize_resources
from .mission_store import MissionConflict, _nonempty, _now
from .sqlite_policy import configure_connection, enable_wal
from .step_action_kinds import step_action_kind, step_grant_digest

_MIGRATION_VERSION = 1
_IDENTIFIER_HASH_FIELDS = ("recipe_digest", "cell_digest", "process_artifact_digest")
# Claim phases (D-403 §4 보강 2026-10-03): a Cell Job holds its claims from admission until it is
# terminal. CLAIMED = admitted and runnable; DISPATCHING = an Action is in flight; UNKNOWN = the
# device outcome is unresolved (blocks rearm); HELD = the Job is in HOLD with a confirmed device
# state (the stop latch skips it, rearm ignores it, admission of the same resources is refused).
# Device outcome -> (step and Job status, claim phase).
_OUTCOMES = {
    "SUCCEEDED": ("ACTION_SUCCEEDED", "CLAIMED"),
    "FAILED": ("HOLD", "HELD"),
    "REJECTED": ("HOLD", "HELD"),
    "UNKNOWN": ("HOLD", "UNKNOWN"),
    # The owner answered GetAction 404: it never journaled the attempt, so nothing ran.
    "NOT_FOUND": ("HOLD", "HELD"),
}
# A cancelled Job is terminal. The status column has no CANCELLED value and 1b makes no schema
# change, so it is HOLD with this reason and no claims; resume refuses it (D-420 v2 adds a status).
CANCELLED_REASON = "CANCELLED_BY_OPERATOR"
_HOLDABLE = frozenset({"READY", "RUNNING", "ACTION_SUCCEEDED"})


def _json(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("Cell Job data must be finite JSON") from exc


def hold_for_site_stop(connection: sqlite3.Connection, *, now: str, hold_reason: str | None) -> None:
    """Called inside the stop/startup latch transaction, before it drops CLAIMED claims.

    A non-terminal Cell Job keeps its claims: READY and ACTION_SUCCEEDED Jobs go to HOLD
    (``hold_reason``; None leaves the status to ``recover_after_startup``) and every CLAIMED
    claim of a Cell Job becomes HELD, which the latch skips. RUNNING claims stay DISPATCHING.
    """
    if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fleet_cell_jobs'"
                          ).fetchone() is None:
        return
    if hold_reason is not None:
        generation = connection.execute(
            "SELECT generation FROM fleet_dispatch_control WHERE control_id=1").fetchone()[0]
        for job in connection.execute(
                "SELECT * FROM fleet_cell_jobs WHERE status IN ('READY', 'ACTION_SUCCEEDED')").fetchall():
            CellJobStore._hold_in_transaction(
                connection, job, reason=hold_reason, claim_phase="HELD", actor_id="site-stop",
                event_key=f"site-stop:{generation}", detail={}, now=now, strict=False)
    connection.execute(
        "UPDATE fleet_action_claims SET phase='HELD', lease_until=NULL WHERE owner_kind='mission' "
        "AND phase='CLAIMED' AND owner_id IN (SELECT mission_id FROM fleet_cell_jobs)")


class CellJobStore:
    """Persist Cell Job ordering beside, but separate from, legacy PICK_PLACE rows."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._noted: set[tuple[str, str, str]] = set()  # device receipts already recorded
        with closing(self._connect()) as connection:
            enable_wal(connection)
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS fleet_component_migrations (
                    component TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    applied_at TEXT NOT NULL,
                    PRIMARY KEY(component, version)
                );
                CREATE TABLE IF NOT EXISTS fleet_cell_jobs (
                    mission_id TEXT PRIMARY KEY,
                    proposal_principal_id TEXT NOT NULL,
                    request_key TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    workcell_id TEXT NOT NULL,
                    instance_id TEXT NOT NULL,
                    recipe_digest TEXT NOT NULL,
                    cell_digest TEXT NOT NULL,
                    process_artifact_digest TEXT NOT NULL,
                    job_json TEXT NOT NULL,
                    resources_json TEXT NOT NULL,
                    ledger_markers_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN (
                        'PROPOSED', 'READY', 'RUNNING', 'ACTION_SUCCEEDED',
                        'GOAL_CONFIRMED', 'HOLD'
                    )),
                    current_step_index INTEGER NOT NULL DEFAULT 0 CHECK(current_step_index >= 0),
                    authority_epoch INTEGER,
                    dispatch_generation INTEGER,
                    reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fleet_cell_steps (
                    mission_id TEXT NOT NULL REFERENCES fleet_cell_jobs(mission_id),
                    step_index INTEGER NOT NULL CHECK(step_index >= 0),
                    step_id TEXT NOT NULL UNIQUE,
                    action_kind TEXT NOT NULL CHECK(action_kind='CELL_TRANSFER'),
                    step_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN (
                        'WAITING', 'READY', 'RUNNING', 'ACTION_SUCCEEDED',
                        'GOAL_CONFIRMED', 'HOLD'
                    )),
                    action_id TEXT,
                    attempt_id TEXT,
                    request_digest TEXT,
                    grant_json TEXT,
                    result_json TEXT,
                    goal_evidence_json TEXT,
                    reason TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(mission_id, step_index)
                );
                CREATE TABLE IF NOT EXISTS fleet_cell_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_key TEXT NOT NULL UNIQUE,
                    mission_id TEXT NOT NULL REFERENCES fleet_cell_jobs(mission_id),
                    step_index INTEGER,
                    event_type TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS fleet_cell_steps_status
                    ON fleet_cell_steps(status, updated_at);
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO fleet_component_migrations(component, version, applied_at) "
                "VALUES ('cell_jobs', ?, ?)", (_MIGRATION_VERSION, _now()),
            )
            applied = connection.execute(
                "SELECT MAX(version) FROM fleet_component_migrations WHERE component='cell_jobs'",
            ).fetchone()[0]
            if applied > _MIGRATION_VERSION:
                raise RuntimeError(f"unsupported Cell Job journal migration version {applied}")
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        configure_connection(connection)
        return connection

    def create(self, *, mission_id: str, proposal_principal_id: str, request_key: str,
               request_digest: str, submission: Mapping[str, Any]) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            result = self.create_in_transaction(
                connection, mission_id=mission_id,
                proposal_principal_id=proposal_principal_id, request_key=request_key,
                request_digest=request_digest, submission=submission,
            )
            connection.commit()
        return result

    @staticmethod
    def create_in_transaction(connection: sqlite3.Connection, *, mission_id: str,
                              proposal_principal_id: str, request_key: str,
                              request_digest: str, submission: Mapping[str, Any]) -> dict[str, Any]:
        """Insert a fully recompiled proposal and its ordered steps in caller's transaction."""
        mission_id = _nonempty("mission_id", mission_id)
        proposal_principal_id = _nonempty(
            "proposal_principal_id", proposal_principal_id, limit=96,
        )
        request_key = _nonempty("request_key", request_key, limit=160)
        if (not isinstance(request_digest, str) or len(request_digest) != 64
                or any(char not in "0123456789abcdef" for char in request_digest)):
            raise ValueError("request_digest must be lowercase SHA-256")
        if connection.execute(
                "SELECT 1 FROM fleet_missions WHERE mission_id=?", (mission_id,),
        ).fetchone() is not None:
            raise ValueError("Cell Job mission_id is already used by the legacy Mission journal")
        required = {
            "job_id", "workcell_id", "instance_id", "recipe_digest", "cell_digest",
            "process_artifact_digest", "job", "steps", "resources", "ledger_markers",
        }
        if set(submission) != required:
            raise ValueError("compiled Cell Job submission has an invalid shape")
        steps = submission["steps"]
        resources = submission["resources"]
        markers = submission["ledger_markers"]
        if not isinstance(steps, list) or not steps or not isinstance(resources, list) or not resources:
            raise ValueError("Cell Job requires ordered steps and resource claims")
        for field in _IDENTIFIER_HASH_FIELDS:
            value = submission[field]
            if (not isinstance(value, str) or len(value) != 64
                    or any(char not in "0123456789abcdef" for char in value)):
                raise ValueError(f"{field} must be lowercase SHA-256")
        now = _now()
        encoded_job = _json(submission["job"])
        resources_json = _json(resources)
        markers_json = _json(markers)
        connection.execute(
            """INSERT INTO fleet_cell_jobs
               (mission_id, proposal_principal_id, request_key, request_digest, job_id,
                workcell_id, instance_id, recipe_digest, cell_digest, process_artifact_digest,
                job_json, resources_json, ledger_markers_json, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PROPOSED', ?, ?)""",
            (mission_id, proposal_principal_id, request_key, request_digest,
             _nonempty("job_id", submission["job_id"]),
             _nonempty("workcell_id", submission["workcell_id"], limit=96),
             _nonempty("instance_id", submission["instance_id"], limit=96),
             submission["recipe_digest"], submission["cell_digest"],
             submission["process_artifact_digest"], encoded_job, resources_json,
             markers_json, now, now),
        )
        for index, step in enumerate(steps):
            # goal_predicate: the item_at_pose predicate fixed at resolution (C4b 1b C1), optional.
            if not isinstance(step, Mapping) or set(step) - {"goal_predicate"} != {"skill_id", "version", "inputs"}:
                raise ValueError("Cell Job step has an invalid execution shape")
            if step["skill_id"] != "pallet.transfer" or step["version"] != "1.0.0":
                raise ValueError("Cell Job steps must use pallet.transfer/1.0.0")
            step_id = f"{mission_id}:step-{index + 1}"
            connection.execute(
                """INSERT INTO fleet_cell_steps
                   (mission_id, step_index, step_id, action_kind, step_json, status, updated_at)
                   VALUES (?, ?, ?, 'CELL_TRANSFER', ?, 'WAITING', ?)""",
                (mission_id, index, step_id, _json(dict(step)), now),
            )
        return CellJobStore._get(connection, mission_id)

    @staticmethod
    def _get(connection: sqlite3.Connection, mission_id: str) -> dict[str, Any] | None:
        row = connection.execute(
            "SELECT * FROM fleet_cell_jobs WHERE mission_id=?", (mission_id,),
        ).fetchone()
        if row is None:
            return None
        job = dict(row)
        for source, target in (("job_json", "job"), ("resources_json", "resources"),
                               ("ledger_markers_json", "ledger_markers")):
            job[target] = json.loads(job.pop(source))
        job["steps"] = []
        for step_row in connection.execute(
                "SELECT * FROM fleet_cell_steps WHERE mission_id=? ORDER BY step_index",
                (mission_id,)):
            step = dict(step_row)
            step["step"] = json.loads(step.pop("step_json"))
            for source, target in (("grant_json", "grant"), ("result_json", "result"),
                                   ("goal_evidence_json", "goal_evidence")):
                raw = step.pop(source)
                step[target] = json.loads(raw) if raw is not None else None
            job["steps"].append(step)
        job["events"] = [
            {**dict(event), "detail": json.loads(event["detail_json"])}
            for event in connection.execute(
                "SELECT * FROM fleet_cell_events WHERE mission_id=? ORDER BY event_id",
                (mission_id,),
            )
        ]
        for event in job["events"]:
            event.pop("detail_json", None)
        return job

    def get(self, mission_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            return self._get(connection, mission_id)

    def jobs(self, status: str) -> list[dict[str, Any]]:
        """Every Job in ``status``, oldest update first (the dispatcher visits each, 1b B1)."""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT mission_id FROM fleet_cell_jobs WHERE status=? ORDER BY updated_at, mission_id",
                (status,),
            ).fetchall()
            return [self._get(connection, row["mission_id"]) for row in rows]

    def recover_after_startup(self) -> int:
        """Fence obsolete admitted Jobs while preserving attempts and occupancy claims."""
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            control = connection.execute(
                "SELECT authority_epoch, generation FROM fleet_dispatch_control WHERE control_id=1",
            ).fetchone()
            rows = connection.execute(
                """SELECT mission_id, current_step_index, authority_epoch, dispatch_generation
                   FROM fleet_cell_jobs WHERE status IN ('READY', 'RUNNING', 'ACTION_SUCCEEDED')
                     AND (authority_epoch != ? OR dispatch_generation != ?)""",
                (control["authority_epoch"], control["generation"]),
            ).fetchall()
            for job in rows:
                # 1c N1: an Action that was in flight across the restart has an unknown outcome;
                # UNKNOWN claims put it on the readback path (and block rearm until resolved).
                connection.execute(
                    "UPDATE fleet_action_claims SET phase='UNKNOWN' WHERE owner_kind='mission' "
                    "AND owner_id=? AND phase='DISPATCHING'", (job["mission_id"],))
                connection.execute(
                    "UPDATE fleet_cell_jobs SET status='HOLD', reason='SITE_AUTHORITY_CHANGED', "
                    "updated_at=? WHERE mission_id=?", (now, job["mission_id"]),
                )
                connection.execute(
                    "UPDATE fleet_cell_steps SET status='HOLD', reason='SITE_AUTHORITY_CHANGED', "
                    "updated_at=? WHERE mission_id=? AND step_index=? "
                    "AND status IN ('READY', 'RUNNING', 'ACTION_SUCCEEDED')",
                    (now, job["mission_id"], job["current_step_index"]),
                )
                self._event(connection, job["mission_id"], job["current_step_index"],
                            "CELL_JOB_STARTUP_HOLD", "system", {
                                "reason": "SITE_AUTHORITY_CHANGED",
                                "previous_authority_epoch": job["authority_epoch"],
                                "previous_dispatch_generation": job["dispatch_generation"],
                                "authority_epoch": control["authority_epoch"],
                                "dispatch_generation": control["generation"],
                            })
            connection.commit()
        return len(rows)

    def admit(self, mission_id: str, *, actor_id: str, expected_generation: int) -> dict[str, Any]:
        actor_id = _nonempty("actor_id", actor_id, limit=96)
        if type(expected_generation) is not int or expected_generation < 0:
            raise ValueError("expected_generation must be a non-negative integer")
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = connection.execute(
                "SELECT * FROM fleet_cell_jobs WHERE mission_id=?", (mission_id,),
            ).fetchone()
            if job is None:
                raise KeyError(mission_id)
            if job["status"] != "PROPOSED":
                raise MissionConflict("only a proposed Cell Job can be admitted")
            control = connection.execute(
                "SELECT authority_epoch, generation, dispatch_enabled "
                "FROM fleet_dispatch_control WHERE control_id=1",
            ).fetchone()
            if (control is None or not control["dispatch_enabled"]
                    or control["generation"] != expected_generation):
                raise MissionConflict("stop generation is closed or changed")
            if not reserve_claims(
                    connection, owner_kind="mission", owner_id=mission_id,
                    generation=expected_generation,
                    resources=[tuple(item) for item in json.loads(job["resources_json"])],
                    phase="CLAIMED"):
                raise MissionConflict("Cell Job resource claim conflicts with another action")
            now = _now()
            connection.execute(
                "UPDATE fleet_cell_jobs SET status='READY', authority_epoch=?, "
                "dispatch_generation=?, updated_at=? WHERE mission_id=?",
                (control["authority_epoch"], expected_generation, now, mission_id),
            )
            connection.execute(
                "UPDATE fleet_cell_steps SET status='READY', updated_at=? "
                "WHERE mission_id=? AND step_index=0 AND status='WAITING'",
                (now, mission_id),
            )
            self._event(connection, mission_id, None, "CELL_JOB_ADMITTED", actor_id,
                        {"authority_epoch": control["authority_epoch"],
                         "dispatch_generation": expected_generation})
            result = self._get(connection, mission_id)
            connection.commit()
        return result

    def start_step(self, mission_id: str, *, step_index: int, action_id: str,
                   attempt_id: str, grant: Mapping[str, Any],
                   now: datetime | None = None, owner_journal_id: str | None = None) -> dict[str, Any]:
        action_id = _nonempty("action_id", action_id)
        attempt_id = _nonempty("attempt_id", attempt_id)
        parsed = FleetCellTransferGrant.model_validate(dict(grant))
        canonical_grant = parsed.model_dump(mode="json")
        if step_grant_digest(parsed) != parsed.request_digest:
            raise ValueError("CELL_TRANSFER request digest does not match the complete grant")
        now_dt = now or datetime.now(timezone.utc)  # the dispatcher passes its own clock (1b B4)
        if parsed.issued_at > now_dt or parsed.expires_at <= now_dt:
            raise MissionConflict("CELL_TRANSFER grant is not current")
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = connection.execute(
                "SELECT * FROM fleet_cell_jobs WHERE mission_id=?", (mission_id,),
            ).fetchone()
            if job is None:
                raise KeyError(mission_id)
            step = connection.execute(
                "SELECT * FROM fleet_cell_steps WHERE mission_id=? AND step_index=?",
                (mission_id, step_index),
            ).fetchone()
            if step is None:
                raise KeyError((mission_id, step_index))
            if (job["status"] != "READY" or step["status"] != "READY"
                    or job["current_step_index"] != step_index):
                raise MissionConflict("only the current READY Cell Job step may start")
            control = connection.execute(
                "SELECT authority_epoch, generation, dispatch_enabled "
                "FROM fleet_dispatch_control WHERE control_id=1",
            ).fetchone()
            if (control is None or not control["dispatch_enabled"]
                    or control["authority_epoch"] != job["authority_epoch"]
                    or control["generation"] != job["dispatch_generation"]):
                # Nothing was sent. The claims are released only if the Job has no progress yet;
                # otherwise they are parked HELD for operator re-approval (1c item 2b, D-420 §4.1).
                self._hold_in_transaction(
                    connection, job, reason="FLEET_FENCE_CHANGED_BEFORE_SUBMISSION",
                    claim_phase=self._pre_send_claim_phase(connection, job), actor_id="fleet", strict=False,
                    event_key=f"hold-before-submit:{step_index}:{self._approvals(connection, job)}",
                    detail={"current_authority_epoch": None if control is None else control["authority_epoch"],
                            "current_generation": None if control is None else control["generation"],
                            "dispatch_enabled": bool(control and control["dispatch_enabled"])},
                )
                result = self._get(connection, mission_id)
                connection.commit()
                return result
            if (parsed.mission_id != mission_id or parsed.step_id != step["step_id"]
                    or parsed.action_id != action_id or parsed.attempt_id != attempt_id
                    or parsed.workcell_id != job["workcell_id"]
                    or parsed.instance_id != job["instance_id"]
                    or parsed.cell_transfer.job_id != job["job_id"]
                    or parsed.cell_transfer.step_index != step_index
                    or parsed.cell_transfer.recipe_sha256 != job["recipe_digest"]
                    or parsed.cell_transfer.cell_sha256 != job["cell_digest"]
                    or parsed.authority_epoch != job["authority_epoch"]
                    or parsed.dispatch_generation != job["dispatch_generation"]):
                raise ValueError("CELL_TRANSFER grant does not match the current persisted step")
            kind = step_action_kind(step["action_kind"])
            expected_payload = kind.body(job, step_index, json.loads(step["step_json"])["inputs"])
            if getattr(parsed, kind.body_field).model_dump(mode="json") != expected_payload:
                raise ValueError("CELL_TRANSFER payload does not match the persisted PlanBundle step")
            if not self._owns_runnable_claims(connection, job):
                # Nothing was sent: a pre-send hold releases what is left (D-420 §4.5 row 1).
                self._hold_in_transaction(
                    connection, job, reason="FLEET_CLAIM_MISSING_BEFORE_SUBMISSION",
                    claim_phase=self._pre_send_claim_phase(connection, job), actor_id="fleet", strict=False,
                    event_key=f"claim-missing:{step_index}:{self._approvals(connection, job)}", detail={})
                result = self._get(connection, mission_id)
                connection.commit()
                return result
            self._set_claims(connection, job, "DISPATCHING")
            connection.execute(
                """UPDATE fleet_cell_steps SET status='RUNNING', action_id=?, attempt_id=?,
                   request_digest=?, grant_json=?, updated_at=?
                   WHERE mission_id=? AND step_index=?""",
                (action_id, attempt_id, parsed.request_digest,
                 _json(canonical_grant), now, mission_id, step_index),
            )
            connection.execute(
                "UPDATE fleet_cell_jobs SET status='RUNNING', updated_at=? WHERE mission_id=?",
                (now, mission_id),
            )
            self._event(connection, mission_id, step_index, "CELL_STEP_SUBMITTING", "fleet",
                        {"action_id": action_id, "attempt_id": attempt_id,
                         "request_digest": parsed.request_digest,
                         "authority_epoch": parsed.authority_epoch,
                         "dispatch_generation": parsed.dispatch_generation,
                         "owner_journal_id": owner_journal_id})
            result = self._get(connection, mission_id)
            connection.commit()
        return result

    def record_action_result(self, mission_id: str, *, step_index: int, event_id: str,
                             action_id: str, attempt_id: str, outcome: str,
                             result: Mapping[str, Any], reason: str | None = None) -> dict[str, Any]:
        """Record one device outcome under the caller's ``event_id``; a replay is a no-op."""
        event_id = _nonempty("event_id", event_id)
        if outcome not in _OUTCOMES:
            raise ValueError("unsupported Action outcome")
        if outcome == "SUCCEEDED":
            if reason is not None:
                raise ValueError("a successful Action result carries no hold reason")
        else:
            reason = _nonempty("reason", reason, limit=96)
        step_state, claim_phase = _OUTCOMES[outcome]
        detail = {"event_id": event_id, "action_id": action_id, "attempt_id": attempt_id,
                  "outcome": outcome, "reason": reason, "result": dict(result)}
        event_type = f"CELL_STEP_ACTION_{outcome}"
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = connection.execute(
                "SELECT * FROM fleet_cell_jobs WHERE mission_id=?", (mission_id,),
            ).fetchone()
            step = connection.execute(
                "SELECT * FROM fleet_cell_steps WHERE mission_id=? AND step_index=?",
                (mission_id, step_index),
            ).fetchone()
            if job is None or step is None:
                raise KeyError(mission_id if job is None else (mission_id, step_index))
            if self._replayed(connection, mission_id, step_index, event_type, "device", event_id, detail):
                result_row = self._get(connection, mission_id)
                connection.commit()
                return result_row
            # RUNNING, or a readback of a HOLD whose claims are still UNKNOWN (1b A3).
            phases = self._claim_phases(connection, job)
            readback = step["status"] == "HOLD" and bool(phases) and phases <= {"UNKNOWN", "DISPATCHING"}
            if ((step["status"] != "RUNNING" and not readback) or step["action_id"] != action_id
                    or step["attempt_id"] != attempt_id or (readback and outcome == "UNKNOWN")):
                raise MissionConflict("Action result does not match the current Cell transfer attempt")
            job_reason = reason
            if outcome == "SUCCEEDED" and not self._fence_current(connection, job):
                # 1c item 2a: the Action ended after a stop or authority change. Keep the success
                # event (resume returns the step to ACTION_SUCCEEDED) but park the Job and claims.
                step_state, claim_phase = "HOLD", "HELD"
                job_reason = job["reason"] if job["status"] == "HOLD" else "site_stop"
            connection.execute(
                "UPDATE fleet_cell_steps SET status=?, result_json=?, reason=?, updated_at=? "
                "WHERE mission_id=? AND step_index=?",
                (step_state, _json(dict(result)), job_reason, now, mission_id, step_index),
            )
            connection.execute(
                "UPDATE fleet_cell_jobs SET status=?, reason=?, updated_at=? WHERE mission_id=?",
                (step_state, job_reason, now, mission_id),
            )
            self._set_claims(connection, job, claim_phase)
            self._event(connection, mission_id, step_index, event_type, "device", detail)
            result_row = self._get(connection, mission_id)
            connection.commit()
        return result_row

    def next_unresolved(self) -> list[dict[str, Any]]:
        """HOLD Jobs whose claims are UNKNOWN: the dispatcher keeps reading them back."""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT DISTINCT j.mission_id FROM fleet_cell_jobs j JOIN fleet_action_claims c "
                "ON c.owner_kind='mission' AND c.owner_id=j.mission_id AND c.generation=j.dispatch_generation "
                "WHERE j.status='HOLD' AND c.phase IN ('UNKNOWN', 'DISPATCHING') "
                "ORDER BY j.updated_at, j.mission_id").fetchall()
            return [self._get(connection, row["mission_id"]) for row in rows]

    def note_device_receipt(self, mission_id: str, step_index: int, action_id: str, attempt_id: str) -> None:
        """Remember that the owner journaled this attempt (1c item 3: a later 404 is not 'never ran')."""
        key = (mission_id, action_id, attempt_id)
        if key in self._noted or self.has_device_receipt(mission_id, action_id, attempt_id):
            self._noted.add(key)  # already recorded: no write transaction (1d item 2)
            return
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._event(connection, mission_id, step_index, "CELL_STEP_DEVICE_RECEIPT", "device",
                        {"event_id": f"device-receipt:{action_id}:{attempt_id}",
                         "action_id": action_id, "attempt_id": attempt_id})
            connection.commit()

    def submitted_journal_id(self, mission_id: str, action_id: str) -> str | None:
        """The owner journal identity recorded when this action was started (1d item 3)."""
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT json_extract(detail_json, '$.owner_journal_id') FROM fleet_cell_events "
                "WHERE mission_id=? AND event_type='CELL_STEP_SUBMITTING' "
                "AND json_extract(detail_json, '$.action_id')=?", (mission_id, action_id)).fetchone()
        return None if row is None else row[0]

    def has_device_receipt(self, mission_id: str, action_id: str, attempt_id: str) -> bool:
        """A noted receipt, or a device-reported terminal outcome (SUCCEEDED/FAILED, only ever read
        from an owner receipt) for the attempt: covers attempts in flight before receipts were
        noted. Fleet-side UNKNOWN/REJECTED/NOT_FOUND outcomes do not prove journaling."""
        with closing(self._connect()) as connection:
            return connection.execute(
                "SELECT 1 FROM fleet_cell_events WHERE event_key=? OR (mission_id=? AND event_type IN "
                "('CELL_STEP_ACTION_SUCCEEDED', 'CELL_STEP_ACTION_FAILED') "
                "AND json_extract(detail_json, '$.action_id')=? "
                "AND json_extract(detail_json, '$.attempt_id')=?) LIMIT 1",
                (f"{mission_id}:device-receipt:{action_id}:{attempt_id}", mission_id, action_id,
                 attempt_id)).fetchone() is not None

    def resource_claims(self) -> list[dict[str, Any]]:
        """Every durable claim with its owner; a Cell Job owner adds its status and reason."""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT c.resource_key, c.resource_kind, c.resource_id, c.owner_kind, c.owner_id, c.generation, "
                "c.phase, j.mission_id, j.status AS job_status, j.reason AS job_reason "
                "FROM fleet_action_claims c LEFT JOIN fleet_cell_jobs j "
                "ON c.owner_kind='mission' AND j.mission_id=c.owner_id ORDER BY c.resource_key").fetchall()
        return [dict(row) for row in rows]

    def resume(self, mission_id: str, *, actor_id: str, expected_generation: int) -> dict[str, Any]:
        """Operator re-approval of a HOLD Job under the current fence (D-420 item 18).

        The first step that is not GOAL_CONFIRMED becomes READY, or ACTION_SUCCEEDED if its last
        device outcome was a success (the transfer is never sent again; goal evidence decides).
        Refused while any claim is DISPATCHING or UNKNOWN, and for a cancelled Job.
        """
        actor_id = _nonempty("actor_id", actor_id, limit=96)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = self._require(connection, mission_id)
            phases = self._claim_phases(connection, job)
            if job["status"] != "HOLD" or job["reason"] == CANCELLED_REASON:
                raise MissionConflict("only a held, uncancelled Cell Job can resume")
            if phases & {"DISPATCHING", "UNKNOWN"}:
                raise MissionConflict("resume is refused while a claim is DISPATCHING or UNKNOWN")
            control = connection.execute(
                "SELECT authority_epoch, generation, dispatch_enabled FROM fleet_dispatch_control "
                "WHERE control_id=1").fetchone()
            if not control["dispatch_enabled"] or control["generation"] != expected_generation:
                raise MissionConflict("stop generation is closed or changed")
            release_claims(connection, owner_kind="mission", owner_id=mission_id)
            if not reserve_claims(connection, owner_kind="mission", owner_id=mission_id,
                                  generation=expected_generation, phase="CLAIMED",
                                  resources=[tuple(item) for item in json.loads(job["resources_json"])]):
                raise MissionConflict("Cell Job resource claim conflicts with another action")
            index = connection.execute(
                "SELECT MIN(step_index) FROM fleet_cell_steps WHERE mission_id=? AND status!='GOAL_CONFIRMED'",
                (mission_id,)).fetchone()[0]
            last = connection.execute(
                "SELECT event_type FROM fleet_cell_events WHERE mission_id=? AND step_index=? "
                "AND event_type LIKE 'CELL_STEP_ACTION_%' ORDER BY event_id DESC LIMIT 1",
                (mission_id, index)).fetchone()
            succeeded = last is not None and last["event_type"] == "CELL_STEP_ACTION_SUCCEEDED"
            state, now = ("ACTION_SUCCEEDED" if succeeded else "READY"), _now()
            clear = "" if succeeded else ", action_id=NULL, attempt_id=NULL, request_digest=NULL, grant_json=NULL"
            connection.execute(
                f"UPDATE fleet_cell_steps SET status=?, reason=NULL, updated_at=?{clear} "
                "WHERE mission_id=? AND step_index=?", (state, now, mission_id, index))
            connection.execute(
                "UPDATE fleet_cell_jobs SET status=?, reason=NULL, current_step_index=?, authority_epoch=?, "
                "dispatch_generation=?, updated_at=? WHERE mission_id=?",
                (state, index, control["authority_epoch"], expected_generation, now, mission_id))
            self._event(connection, mission_id, index, "CELL_JOB_RESUMED", actor_id, {
                "authority_epoch": control["authority_epoch"], "dispatch_generation": expected_generation,
                "previous_generation": job["dispatch_generation"], "step_status": state})
            result = self._get(connection, mission_id)
            connection.commit()
        return result

    def cancel(self, mission_id: str, *, actor_id: str) -> dict[str, Any]:
        """Operator abort: terminal, and the claims are released in the same transaction."""
        actor_id = _nonempty("actor_id", actor_id, limit=96)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = self._require(connection, mission_id)
            if job["status"] in {"PROPOSED", "GOAL_CONFIRMED", "RUNNING"} or job["reason"] == CANCELLED_REASON:
                raise MissionConflict(f"a {job['status']} Cell Job cannot be cancelled")
            if self._claim_phases(connection, job) & {"DISPATCHING", "UNKNOWN"}:
                raise MissionConflict("cancel is refused while a claim is DISPATCHING or UNKNOWN")
            now = _now()
            connection.execute(
                "UPDATE fleet_cell_steps SET status='HOLD', reason=?, updated_at=? WHERE mission_id=? "
                "AND status IN ('READY', 'ACTION_SUCCEEDED')", (CANCELLED_REASON, now, mission_id))
            connection.execute("UPDATE fleet_cell_jobs SET status='HOLD', reason=?, updated_at=? WHERE mission_id=?",
                               (CANCELLED_REASON, now, mission_id))
            release_claims(connection, owner_kind="mission", owner_id=mission_id)
            self._event(connection, mission_id, job["current_step_index"], "CELL_JOB_CANCELLED", actor_id,
                        {"previous_status": job["status"], "previous_reason": job["reason"]})
            result = self._get(connection, mission_id)
            connection.commit()
        return result

    @staticmethod
    def _require(connection: sqlite3.Connection, mission_id: str) -> sqlite3.Row:
        job = connection.execute("SELECT * FROM fleet_cell_jobs WHERE mission_id=?", (mission_id,)).fetchone()
        if job is None:
            raise KeyError(mission_id)
        return job

    @staticmethod
    def _claim_phases(connection: sqlite3.Connection, job: sqlite3.Row) -> set[str]:
        return {row[0] for row in connection.execute(
            "SELECT phase FROM fleet_action_claims WHERE owner_kind='mission' AND owner_id=?",
            (job["mission_id"],))}

    def hold(self, mission_id: str, *, reason: str, claim_phase: str | None, actor_id: str,
             event_key: str) -> dict[str, Any]:
        """HOLD a READY, RUNNING or ACTION_SUCCEEDED Job and its current step (idempotent).

        A held Job keeps its claims (D-403 보강 2026-10-03): ``claim_phase`` is HELD from READY or
        ACTION_SUCCEEDED, and UNKNOWN from RUNNING (so readback picks it up). hold() never releases
        claims; ``release_before_send`` and ``cancel`` are the only release paths.
        """
        reason = _nonempty("reason", reason, limit=96)
        actor_id = _nonempty("actor_id", actor_id, limit=96)
        event_key = _nonempty("event_key", event_key)
        if claim_phase not in {"HELD", "UNKNOWN"}:
            raise ValueError("claim_phase must be HELD or UNKNOWN; hold() never releases claims")
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = connection.execute(
                "SELECT * FROM fleet_cell_jobs WHERE mission_id=?", (mission_id,),
            ).fetchone()
            if job is None:
                raise KeyError(mission_id)
            event_key = f"{event_key}@{self._approvals(connection, job)}"
            detail = {"event_id": event_key, "reason": reason, "claim_phase": claim_phase}
            if not self._replayed(connection, mission_id, job["current_step_index"], "CELL_JOB_HELD",
                                  actor_id, event_key, detail):
                if job["status"] not in _HOLDABLE:
                    raise MissionConflict(f"a {job['status']} Cell Job cannot be held")
                allowed = {"UNKNOWN"} if job["status"] == "RUNNING" else {"HELD"}
                if claim_phase not in allowed:
                    raise MissionConflict(f"a {job['status']} Cell Job cannot hold its claims as {claim_phase}")
                self._hold_in_transaction(connection, job, reason=reason, claim_phase=claim_phase,
                                          actor_id=actor_id, event_key=event_key, detail={})
            result = self._get(connection, mission_id)
            connection.commit()
        return result

    def hold_unsent(self, mission_id: str, *, action_id: str, reason: str) -> dict[str, Any]:
        """RUNNING -> HOLD with DISPATCHING -> HELD for a started step that was never sent (1d item 1).

        Refused unless the step's current action is ``action_id`` and the owner never answered for
        it (no receipt, no CELL_STEP_ACTION_* event): only then is "not sent" a fact.
        """
        reason = _nonempty("reason", reason, limit=96)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = self._require(connection, mission_id)
            step = connection.execute("SELECT * FROM fleet_cell_steps WHERE mission_id=? AND step_index=?",
                                      (mission_id, job["current_step_index"])).fetchone()
            seen = connection.execute(
                "SELECT 1 FROM fleet_cell_events WHERE mission_id=? AND (event_key=? OR "
                "(event_type LIKE 'CELL_STEP_ACTION_%' AND json_extract(detail_json, '$.action_id')=?)) LIMIT 1",
                (mission_id, f"{mission_id}:device-receipt:{action_id}:{step['attempt_id'] if step else ''}",
                 action_id)).fetchone()
            if job["status"] != "RUNNING" or step is None or step["action_id"] != action_id or seen is not None:
                raise MissionConflict("only a started, never answered step can be held as unsent")
            self._hold_in_transaction(connection, job, reason=reason, claim_phase="HELD", actor_id="fleet",
                                      event_key=f"unsent:{action_id}", detail={"action_id": action_id})
            result = self._get(connection, mission_id)
            connection.commit()
        return result

    def release_before_send(self, mission_id: str, *, reason: str, event_key: str) -> dict[str, Any]:
        """HOLD a READY Job whose current step was never started; release its claims only if the
        Job has no progress (step 0, nothing ever submitted), else park them HELD (1c item 2b)."""
        reason = _nonempty("reason", reason, limit=96)
        event_key = _nonempty("event_key", event_key)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = self._require(connection, mission_id)
            step = connection.execute("SELECT * FROM fleet_cell_steps WHERE mission_id=? AND step_index=?",
                                      (mission_id, job["current_step_index"])).fetchone()
            if job["status"] != "READY" or step is None or step["action_id"] is not None:
                raise MissionConflict("only a READY step that was never started can be released before send")
            event_key = f"{event_key}@{self._approvals(connection, job)}"
            phase = self._pre_send_claim_phase(connection, job)
            detail = {"event_id": event_key, "reason": reason, "claim_phase": phase}
            if not self._replayed(connection, mission_id, job["current_step_index"], "CELL_JOB_HELD",
                                  "mission-dispatcher", event_key, detail):
                self._hold_in_transaction(connection, job, reason=reason, claim_phase=phase,
                                          actor_id="mission-dispatcher", event_key=event_key, detail={})
            result = self._get(connection, mission_id)
            connection.commit()
        return result

    @staticmethod
    def _pre_send_claim_phase(connection: sqlite3.Connection, job: sqlite3.Row) -> str | None:
        """None (release) only without progress: step 0 and nothing ever submitted; else HELD."""
        submitted = connection.execute(
            "SELECT 1 FROM fleet_cell_events WHERE mission_id=? AND event_type='CELL_STEP_SUBMITTING' LIMIT 1",
            (job["mission_id"],)).fetchone()
        return None if job["current_step_index"] == 0 and submitted is None else "HELD"

    @staticmethod
    def _fence_current(connection: sqlite3.Connection, job: sqlite3.Row) -> bool:
        control = connection.execute("SELECT authority_epoch, generation, dispatch_enabled "
                                     "FROM fleet_dispatch_control WHERE control_id=1").fetchone()
        return bool(control and control["dispatch_enabled"] and control["authority_epoch"] == job["authority_epoch"]
                    and control["generation"] == job["dispatch_generation"])

    @staticmethod
    def _hold_in_transaction(connection: sqlite3.Connection, job: sqlite3.Row, *,
                             reason: str, claim_phase: str | None, actor_id: str,
                             event_key: str, detail: Mapping[str, Any], now: str | None = None,
                             strict: bool = True) -> None:
        now = now or _now()
        connection.execute(
            "UPDATE fleet_cell_steps SET status='HOLD', reason=?, updated_at=? "
            "WHERE mission_id=? AND step_index=? AND status IN ('READY', 'RUNNING', 'ACTION_SUCCEEDED')",
            (reason, now, job["mission_id"], job["current_step_index"]),
        )
        connection.execute(
            "UPDATE fleet_cell_jobs SET status='HOLD', reason=?, updated_at=? WHERE mission_id=?",
            (reason, now, job["mission_id"]),
        )
        CellJobStore._set_claims(connection, job, claim_phase, strict=strict)
        CellJobStore._event(
            connection, job["mission_id"], job["current_step_index"], "CELL_JOB_HELD", actor_id,
            {"event_id": event_key, "reason": reason, "claim_phase": claim_phase, **detail})

    @staticmethod
    def _set_claims(connection: sqlite3.Connection, job: sqlite3.Row, phase: str | None, *,
                    strict: bool = True) -> None:
        if phase is None:
            release_claims(connection, owner_kind="mission", owner_id=job["mission_id"],
                           generation=job["dispatch_generation"])
            return
        updated = connection.execute(
            "UPDATE fleet_action_claims SET phase=?, lease_until=NULL "
            "WHERE owner_kind='mission' AND owner_id=? AND generation=?",
            (phase, job["mission_id"], job["dispatch_generation"]),
        ).rowcount
        expected = len(normalize_resources(json.loads(job["resources_json"])))
        if updated != expected and strict:
            raise MissionConflict("Cell Job no longer owns all durable resource claims")
        if updated != expected:
            # 1c N2: the stop path never fails on bookkeeping; it records what needs reconciling.
            CellJobStore._event(connection, job["mission_id"], job["current_step_index"],
                                "CLAIM_SET_INCOMPLETE_AT_STOP", "site-stop",
                                {"expected_claims": expected, "updated_claims": updated, "phase": phase})

    @staticmethod
    def _owns_runnable_claims(connection: sqlite3.Connection, job: sqlite3.Row) -> bool:
        claims = connection.execute(
            "SELECT resource_key, phase FROM fleet_action_claims "
            "WHERE owner_kind='mission' AND owner_id=? AND generation=?",
            (job["mission_id"], job["dispatch_generation"]),
        ).fetchall()
        expected = {key for _, _, key in normalize_resources(json.loads(job["resources_json"]))}
        return ({claim["resource_key"] for claim in claims} == expected
                and all(claim["phase"] == "CLAIMED" for claim in claims))

    @staticmethod
    def _approvals(connection: sqlite3.Connection, job: sqlite3.Row) -> int:
        """Approval count: hold event keys include it, so a hold after re-approval is not a replay."""
        return connection.execute(
            "SELECT COUNT(*) FROM fleet_cell_events WHERE mission_id=? AND event_type IN "
            "('CELL_JOB_ADMITTED', 'CELL_JOB_RESUMED')", (job["mission_id"],)).fetchone()[0]

    @staticmethod
    def _replayed(connection: sqlite3.Connection, mission_id: str, step_index: int | None,
                  event_type: str, actor_id: str, event_id: str, detail: Mapping[str, Any]) -> bool:
        """True for an exact replay of ``event_id``; a reuse with other content raises."""
        prior = connection.execute(
            "SELECT * FROM fleet_cell_events WHERE event_key=?", (f"{mission_id}:{event_id}",),
        ).fetchone()
        if prior is None:
            return False
        if (prior["step_index"] != step_index or prior["event_type"] != event_type
                or prior["actor_id"] != actor_id or prior["detail_json"] != _json(dict(detail))):
            raise MissionConflict("Cell Job event identity was reused with different evidence")
        return True

    def confirm_step_goal(self, mission_id: str, *, step_index: int,
                          action_id: str, attempt_id: str,
                          evidence: Mapping[str, Any]) -> dict[str, Any]:
        """Record already authenticated sim-model and post-action gripper evidence."""
        required_evidence = {
            "producer_id", "evidence_id", "evidence_source", "action_id", "attempt_id",
            "satisfied", "gripper_state", "gripper_evidence_id",
        }
        if not isinstance(evidence, Mapping) or not required_evidence.issubset(evidence):
            raise ValueError("Cell step goal confirmation requires independent producer and gripper evidence")
        if (evidence["evidence_source"] != "sim_model_pose"
                or evidence["action_id"] != action_id or evidence["attempt_id"] != attempt_id
                or evidence["gripper_state"] != "OPEN"
                or type(evidence["satisfied"]) is not bool):
            raise MissionConflict("Cell step goal evidence does not match the current transfer attempt")
        if evidence["satisfied"] is not True:
            raise MissionConflict("unsatisfied Cell step goal evidence cannot advance the Job")
        evidence_json = _json(dict(evidence))
        event_id = f"goal:{step_index}:{_nonempty('evidence_id', evidence['evidence_id'])}"
        detail = {**json.loads(evidence_json), "event_id": event_id}
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = connection.execute(
                "SELECT * FROM fleet_cell_jobs WHERE mission_id=?", (mission_id,),
            ).fetchone()
            step = connection.execute(
                "SELECT * FROM fleet_cell_steps WHERE mission_id=? AND step_index=?",
                (mission_id, step_index),
            ).fetchone()
            if job is None or step is None:
                raise KeyError(mission_id if job is None else (mission_id, step_index))
            final = connection.execute(
                "SELECT MAX(step_index) FROM fleet_cell_steps WHERE mission_id=?", (mission_id,),
            ).fetchone()[0] == step_index
            event_type = "CELL_JOB_GOAL_CONFIRMED" if final else "CELL_STEP_GOAL_CONFIRMED"
            if self._replayed(connection, mission_id, step_index, event_type, "goal-evidence",
                              event_id, detail):
                result = self._get(connection, mission_id)
                connection.commit()
                return result
            if (job["status"] != "ACTION_SUCCEEDED" or step["status"] != "ACTION_SUCCEEDED"
                    or step["action_id"] != action_id or step["attempt_id"] != attempt_id):
                raise MissionConflict("independent goal evidence requires this step's terminal Action success")
            now = _now()
            connection.execute(
                "UPDATE fleet_cell_steps SET status='GOAL_CONFIRMED', goal_evidence_json=?, "
                "reason=NULL, updated_at=? WHERE mission_id=? AND step_index=?",
                (evidence_json, now, mission_id, step_index),
            )
            next_index = step_index + 1
            next_step = connection.execute(
                "SELECT step_index FROM fleet_cell_steps WHERE mission_id=? AND step_index=?",
                (mission_id, next_index),
            ).fetchone()
            if next_step is not None:
                connection.execute(
                    "UPDATE fleet_cell_steps SET status='READY', updated_at=? "
                    "WHERE mission_id=? AND step_index=? AND status='WAITING'",
                    (now, mission_id, next_index),
                )
                connection.execute(
                    "UPDATE fleet_cell_jobs SET status='READY', current_step_index=?, "
                    "reason=NULL, updated_at=? WHERE mission_id=?",
                    (next_index, now, mission_id),
                )
                event_type = "CELL_STEP_GOAL_CONFIRMED"
            else:
                connection.execute(
                    "UPDATE fleet_cell_jobs SET status='GOAL_CONFIRMED', current_step_index=?, "
                    "reason=NULL, updated_at=? WHERE mission_id=?",
                    (next_index, now, mission_id),
                )
                release_claims(connection, owner_kind="mission", owner_id=mission_id,
                               generation=job["dispatch_generation"])
                event_type = "CELL_JOB_GOAL_CONFIRMED"
            self._event(connection, mission_id, step_index, event_type, "goal-evidence", detail)
            result = self._get(connection, mission_id)
            connection.commit()
        return result

    @staticmethod
    def _event(connection: sqlite3.Connection, mission_id: str, step_index: int | None,
               event_type: str, actor_id: str, detail: Mapping[str, Any]) -> None:
        identity = detail.get("event_id") or (
            f"{event_type}:{step_index}:"
            f"{hashlib.sha256(_json(dict(detail)).encode()).hexdigest()}"
        )
        key = f"{mission_id}:{identity}"
        encoded = _json(dict(detail))
        prior = connection.execute(
            "SELECT * FROM fleet_cell_events WHERE event_key=?", (key,),
        ).fetchone()
        if prior is not None:
            if (prior["mission_id"] != mission_id or prior["step_index"] != step_index
                    or prior["event_type"] != event_type or prior["actor_id"] != actor_id
                    or prior["detail_json"] != encoded):
                raise MissionConflict("Cell Job event identity was reused with different evidence")
            return
        connection.execute(
            """INSERT INTO fleet_cell_events
               (event_key, mission_id, step_index, event_type, actor_id, detail_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (key, mission_id, step_index, event_type, actor_id, encoded, _now()),
        )
