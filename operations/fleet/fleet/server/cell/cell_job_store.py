"""Versioned, ordered Fleet journal for fixed-cell transfer Missions (D-403)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Mapping

from . import cell_arm_jobs as arm_jobs, cell_sheet_checkpoints as sheets, step_ledger_schema
from . import cell_job_read_model as read_model
from . import job_provenance_schema
from . import physical_transfer_schema
from .cell_job_completion import confirm_step_goal
from .cell_job_store_helpers import (  # noqa: F401
    CANCELLED_REASON,
    _HOLDABLE,
    _IDENTIFIER_HASH_FIELDS,
    _OUTCOMES,
    admit,
    cancel,
    create_in_transaction,
    guard_sheet_checkpoint,
    hold,
    hold_unsent,
    record_action_result,
    release_before_send,
    resume,
    start_step,
)
from .dispatch_admission import normalize_resources, release as release_claims, reserve as reserve_claims  # noqa: F401
from .mission_store import MissionConflict, _json, _nonempty, _now  # noqa: F401
from .sqlite_policy import configure_connection, enable_wal

_MIGRATION_VERSION = 8  # D-856: bound physical observations; old hosts must refuse this journal.


def hold_for_site_stop(connection: sqlite3.Connection, *, now: str, hold_reason: str | None) -> None:
    """Called inside the stop/startup latch transaction, before it drops CLAIMED claims.

    A non-terminal Cell Job keeps its claims: READY and ACTION_SUCCEEDED Jobs go to HOLD
    (``hold_reason``; None leaves the status to ``recover_after_startup``) and every CLAIMED
    claim of a Cell Job becomes HELD, which the latch skips. RUNNING claims stay DISPATCHING.
    """
    if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='fleet_cell_jobs'"
                          ).fetchone() is None:
        return
    physical_transfer_schema.hold_for_site_stop(connection, now=now,
        reason="SITE_AUTHORITY_CHANGED" if hold_reason is None else "SITE_STOP", event=CellJobStore._event)
    if hold_reason is not None:
        generation = connection.execute(
            "SELECT generation FROM fleet_dispatch_control WHERE control_id=1").fetchone()[0]
        for job in arm_jobs.single_arm_jobs(connection, "READY", "ACTION_SUCCEEDED"):
            CellJobStore._hold_in_transaction(
                connection, job, reason=hold_reason, claim_phase="HELD", actor_id="site-stop",
                event_key=f"site-stop:{generation}", detail={}, now=now, strict=False)
        arm_jobs.site_stop(connection, now=now, hold_reason=hold_reason)  # D-779 §5: per arm
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
            with job_provenance_schema.initialize(connection, version=_MIGRATION_VERSION, now=_now()):
                step_ledger_schema.ensure(connection)
                sheets.migrate(connection)
                physical_transfer_schema.ensure(connection)

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

    create_in_transaction = staticmethod(create_in_transaction)
    admit = admit
    guard_sheet_checkpoint = guard_sheet_checkpoint
    start_step = start_step
    record_action_result = record_action_result
    resume = resume
    cancel = cancel
    hold = hold
    hold_unsent = hold_unsent
    release_before_send = release_before_send

    @staticmethod
    def _get(connection: sqlite3.Connection, mission_id: str) -> dict[str, Any] | None:
        return read_model.read_cell_job(connection, mission_id)

    def get(self, mission_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            return self._get(connection, mission_id)

    def jobs(self, status: str) -> list[dict[str, Any]]:
        """Every Job in ``status``, oldest update first (the dispatcher visits each, 1b B1)."""
        with closing(self._connect()) as connection:
            return read_model.jobs_by_status(connection, status)

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
                   FROM fleet_cell_jobs WHERE provenance_kind='legacy'
                     AND status IN ('READY', 'RUNNING', 'ACTION_SUCCEEDED')
                     AND (authority_epoch != ? OR dispatch_generation != ?)
                     AND mission_id NOT IN (SELECT mission_id FROM fleet_cell_arm_jobs)""",
                (control["authority_epoch"], control["generation"])).fetchall()
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
            held = sheets.recover_ready(connection, now, self._event) + arm_jobs.recover(connection, now, control)
            connection.commit()
        return len(rows) + held

    def next_unresolved(self) -> list[dict[str, Any]]:
        """HOLD Jobs whose claims are UNKNOWN: the dispatcher keeps reading them back."""
        with closing(self._connect()) as connection:
            return read_model.unresolved_jobs(connection)

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

    @staticmethod
    def _require(connection: sqlite3.Connection, mission_id: str) -> sqlite3.Row:
        job = connection.execute(
            "SELECT * FROM fleet_cell_jobs WHERE mission_id=? AND provenance_kind='legacy'",
            (mission_id,),
        ).fetchone()
        if job is None:
            raise KeyError(mission_id)
        return job

    @staticmethod
    def _claim_phases(connection: sqlite3.Connection, job: sqlite3.Row) -> set[str]:
        return {row[0] for row in connection.execute(
            "SELECT phase FROM fleet_action_claims WHERE owner_kind='mission' AND owner_id=?",
            (job["mission_id"],))}

    @staticmethod
    def _pre_send_claim_phase(connection: sqlite3.Connection, job: sqlite3.Row) -> str | None:
        """None (release) only without progress: step 0 and nothing ever submitted; else HELD."""
        submitted = connection.execute(
            "SELECT 1 FROM fleet_cell_events WHERE mission_id=? AND event_type='CELL_STEP_SUBMITTING' LIMIT 1",
            (job["mission_id"],)).fetchone()
        return None if job["current_step_index"] == 0 and submitted is None else "HELD"

    @staticmethod
    def _durable_success(connection: sqlite3.Connection, mission_id: str, step_index: int,
                         action_id: str, attempt_id: str) -> bool:
        """The latest device outcome of the step is this exact attempt's SUCCEEDED (main 64b4b1faa)."""
        row = connection.execute(
            "SELECT event_type, detail_json FROM fleet_cell_events WHERE mission_id=? AND step_index=? "
            "AND event_type LIKE 'CELL_STEP_ACTION_%' ORDER BY event_id DESC LIMIT 1",
            (mission_id, step_index)).fetchone()
        if row is None or row["event_type"] != "CELL_STEP_ACTION_SUCCEEDED":
            return False
        detail = json.loads(row["detail_json"])
        return detail.get("action_id") == action_id and detail.get("attempt_id") == attempt_id

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
        CellJobStore._set_claims(connection, job, claim_phase, strict=strict,
                                 context="site-stop" if actor_id == "site-stop" else "pre-send",
                                 actor_id=actor_id)
        CellJobStore._event(
            connection, job["mission_id"], job["current_step_index"], "CELL_JOB_HELD", actor_id,
            {"event_id": event_key, "reason": reason, "claim_phase": claim_phase, **detail})

    @staticmethod
    def _set_claims(connection: sqlite3.Connection, job: sqlite3.Row, phase: str | None, *,
                    strict: bool = True, context: str = "hold", actor_id: str = "fleet") -> None:
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
                                "CLAIM_SET_INCOMPLETE_AT_STOP", actor_id, {
                                    "event_id": (f"claim-set-incomplete:{context}:{job['dispatch_generation']}:"
                                                 f"{CellJobStore._approvals(connection, job)}:{phase}"),
                                    "context": context, "expected_claims": expected,
                                    "updated_claims": updated, "phase": phase})

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

    confirm_step_goal = confirm_step_goal

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
