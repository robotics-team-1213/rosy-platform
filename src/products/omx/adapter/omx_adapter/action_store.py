"""Durable intent/result ledger for a future local OMX Action API.

The store is ROS-free and never talks to a driver. A caller must persist
SUBMITTING before a ROS goal and reconcile UNKNOWN from authoritative driver
readback; this module deliberately has no replay operation.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


class ActionConflict(ValueError):
    """An idempotency key was reused with a different semantic request."""


class InvalidActionTransition(ValueError):
    """The Action is not in a state that permits the requested transition."""


_TERMINAL = {"SUCCEEDED", "FAILED"}
_PICK_PLACE_PHASES = ("approach", "grasp", "transfer", "release")
_WORKFLOW_STATES = frozenset({
    "APPROACH", "GRASP", "VERIFY_HOLD", "TRANSFER", "RELEASE",
    "VERIFY_RELEASE", "ACTION_SUCCEEDED", "HOLD",
})
_WORKFLOW_EVIDENCE_KEYS = frozenset({
    "phase_result_id", "gripper_hold_sequence", "gripper_release_sequence",
    "hold_reason",
})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _nonempty(name: str, value: object, *, maximum: int = 192) -> str:
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or len(value) > maximum or any(ord(char) < 32 for char in value)):
        raise ValueError(f"{name} must be a non-empty trimmed string of at most {maximum} characters")
    return value


def _json(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("Action data must be finite JSON") from exc


class ActionStore:
    """Single-host SQLite Action journal; driver dispatch is always external."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if str(mode).lower() != "wal":
                raise RuntimeError(f"SQLite WAL mode is required, got {mode!r}")
            connection.execute("PRAGMA synchronous=FULL")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > 2:
                raise RuntimeError(f"unsupported Action database schema version {version}")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS omx_actions (
                    action_id TEXT PRIMARY KEY,
                    workcell_id TEXT NOT NULL,
                    instance_id TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    request_key TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    action_kind TEXT NOT NULL,
                    configuration_revision TEXT NOT NULL,
                    observation_id TEXT NOT NULL,
                    owner_generation INTEGER NOT NULL,
                    request_json TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN (
                        'PREPARED', 'SUBMITTING', 'ACCEPTED', 'RUNNING',
                        'CANCEL_REQUESTED', 'UNKNOWN', 'SUCCEEDED', 'FAILED', 'HOLD'
                    )),
                    attempt_id TEXT,
                    driver_goal_id TEXT,
                    cancel_acknowledged INTEGER CHECK(cancel_acknowledged IN (0, 1)),
                    result_source TEXT,
                    result_observed_at TEXT,
                    result_json TEXT,
                    reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(workcell_id, principal_id, request_key)
                );
                CREATE INDEX IF NOT EXISTS omx_actions_state ON omx_actions(state, updated_at);
                CREATE UNIQUE INDEX IF NOT EXISTS omx_actions_attempt
                    ON omx_actions(attempt_id) WHERE attempt_id IS NOT NULL;
                CREATE TABLE IF NOT EXISTS omx_action_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_id TEXT NOT NULL REFERENCES omx_actions(action_id),
                    attempt_id TEXT,
                    state TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS omx_action_events_action
                    ON omx_action_events(action_id, event_id);
                CREATE TABLE IF NOT EXISTS omx_action_phases (
                    action_id TEXT NOT NULL REFERENCES omx_actions(action_id),
                    attempt_id TEXT NOT NULL,
                    phase_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
                    command_digest TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN (
                        'SUBMITTING', 'ACCEPTED', 'RUNNING', 'CANCEL_REQUESTED',
                        'UNKNOWN', 'SUCCEEDED', 'FAILED', 'CANCELED'
                    )),
                    driver_goal_id TEXT UNIQUE,
                    cancel_acknowledged INTEGER CHECK(cancel_acknowledged IN (0, 1)),
                    result_source TEXT,
                    result_observed_at TEXT,
                    result_json TEXT,
                    reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(action_id, attempt_id, phase_id),
                    UNIQUE(action_id, attempt_id, ordinal)
                );
                CREATE INDEX IF NOT EXISTS omx_action_phases_state
                    ON omx_action_phases(action_id, attempt_id, state, ordinal);
                PRAGMA user_version=2;
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @staticmethod
    def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        result["owner_generation"] = int(result["owner_generation"])
        result["cancel_acknowledged"] = (
            None if result["cancel_acknowledged"] is None
            else bool(result["cancel_acknowledged"])
        )
        for field in ("request_json", "result_json"):
            if result[field] is not None:
                result[field.removesuffix("_json")] = json.loads(result[field])
                del result[field]
        return result

    def _append_event(self, connection: sqlite3.Connection, *, action_id: str,
                      attempt_id: str | None, state: str, event_type: str,
                      actor_id: str, detail: object, created_at: str) -> None:
        connection.execute(
            """INSERT INTO omx_action_events
               (action_id, attempt_id, state, event_type, actor_id, detail_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (action_id, attempt_id, state, event_type, actor_id, _json(detail), created_at),
        )

    def create_action(self, *, workcell_id: str, instance_id: str, principal_id: str,
                      request_key: str, action_kind: str, configuration_revision: str,
                      observation_id: str, owner_generation: int,
                      payload: Mapping[str, Any], action_id: str | None = None) -> dict[str, Any]:
        workcell_id = _nonempty("workcell_id", workcell_id, maximum=96)
        instance_id = _nonempty("instance_id", instance_id, maximum=96)
        principal_id = _nonempty("principal_id", principal_id, maximum=96)
        request_key = _nonempty("request_key", request_key, maximum=160)
        action_kind = _nonempty("action_kind", action_kind, maximum=48)
        configuration_revision = _nonempty("configuration_revision", configuration_revision)
        observation_id = _nonempty("observation_id", observation_id)
        if type(owner_generation) is not int or owner_generation < 0:
            raise ValueError("owner_generation must be a non-negative integer")
        if action_id is not None:
            action_id = _nonempty("action_id", action_id)
        if not isinstance(payload, Mapping):
            raise ValueError("payload must be a JSON object")
        request = {
            "workcell_id": workcell_id, "instance_id": instance_id,
            "action_kind": action_kind, "configuration_revision": configuration_revision,
            "observation_id": observation_id, "owner_generation": owner_generation,
            "payload": dict(payload),
        }
        request_json = _json(request)
        semantic_request = {key: value for key, value in request.items()
                            if key != "owner_generation"}
        digest = hashlib.sha256(_json(semantic_request).encode("utf-8")).hexdigest()
        now = _utc_now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """SELECT * FROM omx_actions WHERE workcell_id=? AND principal_id=?
                   AND request_key=?""",
                (workcell_id, principal_id, request_key),
            ).fetchone()
            if existing is not None:
                if existing["request_digest"] != digest:
                    raise ActionConflict("request_key is already bound to a different Action request")
                connection.commit()
                return {"action": self._dict(existing), "created": False}
            action_id = action_id or str(uuid.uuid4())
            connection.execute(
                """INSERT INTO omx_actions
                   (action_id, workcell_id, instance_id, principal_id, request_key,
                    request_digest, action_kind, configuration_revision, observation_id,
                    owner_generation, request_json, state, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PREPARED', ?, ?)""",
                (action_id, workcell_id, instance_id, principal_id, request_key, digest,
                 action_kind, configuration_revision, observation_id, owner_generation,
                 request_json, now, now),
            )
            self._append_event(
                connection, action_id=action_id, attempt_id=None, state="PREPARED",
                event_type="ACTION_PREPARED", actor_id=principal_id,
                detail={"request_digest": digest}, created_at=now,
            )
            row = connection.execute("SELECT * FROM omx_actions WHERE action_id=?",
                                     (action_id,)).fetchone()
            connection.commit()
        return {"action": self._dict(row), "created": True}

    def begin_submission(self, action_id: str, *, expected_generation: int,
                         attempt_id: str | None = None) -> dict[str, Any]:
        action_id = _nonempty("action_id", action_id)
        if type(expected_generation) is not int or expected_generation < 0:
            raise ValueError("expected_generation must be a non-negative integer")
        now = _utc_now()
        if attempt_id is None:
            attempt_id = str(uuid.uuid4())
        else:
            attempt_id = _nonempty("attempt_id", attempt_id)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM omx_actions WHERE action_id=?",
                                     (action_id,)).fetchone()
            if row is None:
                raise KeyError(action_id)
            if row["state"] != "PREPARED" or row["owner_generation"] != expected_generation:
                raise InvalidActionTransition("only a PREPARED Action with the current generation may submit")
            connection.execute(
                """UPDATE omx_actions SET state='SUBMITTING', attempt_id=?, updated_at=?
                   WHERE action_id=? AND state='PREPARED'""",
                (attempt_id, now, action_id),
            )
            self._append_event(
                connection, action_id=action_id, attempt_id=attempt_id, state="SUBMITTING",
                event_type="DRIVER_SUBMISSION_STARTED", actor_id=row["principal_id"],
                detail={"owner_generation": expected_generation}, created_at=now,
            )
            updated = connection.execute("SELECT * FROM omx_actions WHERE action_id=?",
                                         (action_id,)).fetchone()
            connection.commit()
        return self._dict(updated)

    def record_submission(self, action_id: str, attempt_id: str, *,
                          accepted: bool | None, driver_goal_id: str | None) -> dict[str, Any]:
        if accepted is not True and accepted is not False and accepted is not None:
            raise ValueError("accepted must be true, false, or unknown")
        if accepted is True and driver_goal_id is None:
            raise ValueError("positive driver acceptance requires driver_goal_id")
        if driver_goal_id is not None:
            driver_goal_id = _nonempty("driver_goal_id", driver_goal_id, maximum=192)
        state = "ACCEPTED" if accepted is True else "FAILED" if accepted is False else "UNKNOWN"
        now = _utc_now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._require_attempt(connection, action_id, attempt_id, {"SUBMITTING"})
            connection.execute(
                """UPDATE omx_actions SET state=?, driver_goal_id=?, reason=?, updated_at=?
                   WHERE action_id=? AND attempt_id=?""",
                (state, driver_goal_id, None if accepted is not None else "DRIVER_ACCEPTANCE_UNKNOWN",
                 now, action_id, attempt_id),
            )
            self._append_event(
                connection, action_id=action_id, attempt_id=attempt_id, state=state,
                event_type="DRIVER_ACCEPTANCE_RECORDED", actor_id=row["principal_id"],
                detail={"accepted": accepted, "driver_goal_id": driver_goal_id}, created_at=now,
            )
            updated = connection.execute("SELECT * FROM omx_actions WHERE action_id=?",
                                         (action_id,)).fetchone()
            connection.commit()
        return self._dict(updated)

    def mark_running(self, action_id: str, attempt_id: str, *, driver_goal_id: str) -> dict[str, Any]:
        return self._transition(action_id, attempt_id, allowed={"ACCEPTED"},
                                target="RUNNING", event_type="DRIVER_ACTION_RUNNING",
                                detail={"driver_goal_id": driver_goal_id},
                                driver_goal_id=driver_goal_id)

    def request_cancel(self, action_id: str, attempt_id: str) -> dict[str, Any]:
        return self._transition(action_id, attempt_id, allowed={"ACCEPTED", "RUNNING"},
                                target="CANCEL_REQUESTED", event_type="CANCEL_REQUESTED",
                                detail={})

    def record_cancel_ack(self, action_id: str, attempt_id: str, *, acknowledged: bool) -> dict[str, Any]:
        if type(acknowledged) is not bool:
            raise ValueError("acknowledged must be boolean")
        now = _utc_now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._require_attempt(connection, action_id, attempt_id, {"CANCEL_REQUESTED"})
            connection.execute(
                "UPDATE omx_actions SET cancel_acknowledged=?, updated_at=? WHERE action_id=?",
                (int(acknowledged), now, action_id),
            )
            self._append_event(
                connection, action_id=action_id, attempt_id=attempt_id,
                state="CANCEL_REQUESTED", event_type="CANCEL_ACK_RECORDED",
                actor_id=row["principal_id"], detail={"acknowledged": acknowledged},
                created_at=now,
            )
            updated = connection.execute("SELECT * FROM omx_actions WHERE action_id=?",
                                         (action_id,)).fetchone()
            connection.commit()
        return self._dict(updated)

    def record_terminal(self, action_id: str, attempt_id: str, *, driver_goal_id: str,
                        outcome: str, result_source: str, result_observed_at: str,
                        result: Mapping[str, Any]) -> dict[str, Any]:
        if outcome not in _TERMINAL:
            raise ValueError("outcome must be SUCCEEDED or FAILED")
        driver_goal_id = _nonempty("driver_goal_id", driver_goal_id)
        result_source = _nonempty("result_source", result_source, maximum=96)
        result_observed_at = _nonempty("result_observed_at", result_observed_at)
        if not isinstance(result, Mapping):
            raise ValueError("result must be a JSON object")
        result_json = _json(dict(result))
        now = _utc_now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._require_attempt(connection, action_id, attempt_id,
                                        {"ACCEPTED", "RUNNING", "CANCEL_REQUESTED", "UNKNOWN", "HOLD"})
            if row["driver_goal_id"] not in {None, driver_goal_id}:
                raise InvalidActionTransition("driver goal identity does not match Action attempt")
            connection.execute(
                """UPDATE omx_actions SET state=?, driver_goal_id=?, result_source=?,
                   result_observed_at=?, result_json=?, reason=NULL, updated_at=?
                   WHERE action_id=? AND attempt_id=?""",
                (outcome, driver_goal_id, result_source, result_observed_at, result_json,
                 now, action_id, attempt_id),
            )
            self._append_event(
                connection, action_id=action_id, attempt_id=attempt_id, state=outcome,
                event_type="DRIVER_TERMINAL_RESULT", actor_id=row["principal_id"],
                detail={"driver_goal_id": driver_goal_id, "result_source": result_source,
                        "result_observed_at": result_observed_at, "result": dict(result)},
                created_at=now,
            )
            updated = connection.execute("SELECT * FROM omx_actions WHERE action_id=?",
                                         (action_id,)).fetchone()
            connection.commit()
        return self._dict(updated)

    @staticmethod
    def _phase_dict(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["ordinal"] = int(result["ordinal"])
        result["cancel_acknowledged"] = (
            None if result["cancel_acknowledged"] is None
            else bool(result["cancel_acknowledged"])
        )
        if result["result_json"] is not None:
            result["result"] = json.loads(result.pop("result_json"))
        else:
            result.pop("result_json")
        return result

    def begin_phase(self, action_id: str, attempt_id: str, *, phase_id: str,
                    ordinal: int, command_digest: str) -> dict[str, Any]:
        """Persist one ordered phase intent before its ROS goal is submitted."""
        action_id = _nonempty("action_id", action_id)
        attempt_id = _nonempty("attempt_id", attempt_id)
        phase_id = _nonempty("phase_id", phase_id, maximum=96)
        if type(ordinal) is not int or ordinal < 0:
            raise ValueError("ordinal must be a non-negative integer")
        command_digest = _nonempty("command_digest", command_digest, maximum=64)
        if (len(command_digest) != 64
                or any(char not in "0123456789abcdef" for char in command_digest)):
            raise ValueError("command_digest must be a lowercase SHA-256 hex digest")
        now = _utc_now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            action = self._require_attempt(
                connection, action_id, attempt_id,
                {"SUBMITTING", "ACCEPTED", "RUNNING"},
            )
            previous = connection.execute(
                "SELECT * FROM omx_action_phases WHERE action_id=? AND attempt_id=? "
                "ORDER BY ordinal DESC LIMIT 1",
                (action_id, attempt_id),
            ).fetchone()
            expected_ordinal = 0 if previous is None else int(previous["ordinal"]) + 1
            if ordinal != expected_ordinal:
                raise InvalidActionTransition("phase ordinal must be contiguous and ordered")
            if action["state"] == "SUBMITTING" and (ordinal != 0 or previous is not None):
                raise InvalidActionTransition(
                    "only the first phase intent may be written while the Action is SUBMITTING",
                )
            if previous is not None and previous["state"] != "SUCCEEDED":
                raise InvalidActionTransition("next phase requires successful terminal result for previous phase")
            duplicate_id = connection.execute(
                """SELECT 1 FROM omx_action_phases WHERE action_id=? AND attempt_id=?
                   AND phase_id=?""",
                (action_id, attempt_id, phase_id),
            ).fetchone()
            if duplicate_id is not None:
                raise InvalidActionTransition("phase_id is already used by this Action attempt")
            connection.execute(
                """INSERT INTO omx_action_phases
                   (action_id, attempt_id, phase_id, ordinal, command_digest, state,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'SUBMITTING', ?, ?)""",
                (action_id, attempt_id, phase_id, ordinal, command_digest, now, now),
            )
            self._append_event(
                connection, action_id=action_id, attempt_id=attempt_id,
                state=action["state"], event_type="ACTION_PHASE_SUBMISSION_STARTED",
                actor_id=action["principal_id"],
                detail={"phase_id": phase_id, "ordinal": ordinal,
                        "command_digest": command_digest}, created_at=now,
            )
            row = connection.execute(
                "SELECT * FROM omx_action_phases WHERE action_id=? AND attempt_id=? AND phase_id=?",
                (action_id, attempt_id, phase_id),
            ).fetchone()
            connection.commit()
        return self._phase_dict(row)

    def record_phase_submission(self, action_id: str, attempt_id: str, *, phase_id: str,
                                accepted: bool | None,
                                driver_goal_id: str | None) -> dict[str, Any]:
        if accepted is not True and accepted is not False and accepted is not None:
            raise ValueError("accepted must be true, false, or unknown")
        if accepted is True and driver_goal_id is None:
            raise ValueError("positive phase acceptance requires driver_goal_id")
        if accepted is False and driver_goal_id is not None:
            raise ValueError("rejected phase cannot have a driver_goal_id")
        if accepted is None and driver_goal_id is not None:
            raise ValueError("unknown phase acceptance cannot have a driver_goal_id")
        if driver_goal_id is not None:
            driver_goal_id = _nonempty("driver_goal_id", driver_goal_id)
        phase_id = _nonempty("phase_id", phase_id, maximum=96)
        state = "ACCEPTED" if accepted is True else "FAILED" if accepted is False else "UNKNOWN"
        now = _utc_now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            action = self._require_attempt(
                connection, action_id, attempt_id, {"ACCEPTED", "RUNNING"},
            )
            phase = connection.execute(
                "SELECT * FROM omx_action_phases WHERE action_id=? AND attempt_id=? AND phase_id=?",
                (action_id, attempt_id, phase_id),
            ).fetchone()
            if phase is None or phase["state"] != "SUBMITTING":
                raise InvalidActionTransition("phase is not awaiting driver acceptance")
            connection.execute(
                """UPDATE omx_action_phases SET state=?, driver_goal_id=?, reason=?, updated_at=?
                   WHERE action_id=? AND attempt_id=? AND phase_id=?""",
                (state, driver_goal_id,
                 "DRIVER_ACCEPTANCE_UNKNOWN" if accepted is None else None, now,
                 action_id, attempt_id, phase_id),
            )
            self._append_event(
                connection, action_id=action_id, attempt_id=attempt_id, state=state,
                event_type="ACTION_PHASE_ACCEPTANCE_RECORDED", actor_id=action["principal_id"],
                detail={"phase_id": phase_id, "accepted": accepted,
                        "driver_goal_id": driver_goal_id}, created_at=now,
            )
            updated = connection.execute(
                "SELECT * FROM omx_action_phases WHERE action_id=? AND attempt_id=? AND phase_id=?",
                (action_id, attempt_id, phase_id),
            ).fetchone()
            connection.commit()
        return self._phase_dict(updated)

    def record_first_phase_submission(
        self, action_id: str, attempt_id: str, *, phase_id: str,
        accepted: bool | None, driver_goal_id: str | None,
    ) -> dict[str, Any]:
        """Atomically persist the parent and first ROS phase response.

        The phase intent must already be durable while the parent Action is
        SUBMITTING. A lost response or process restart is reconciled as
        UNKNOWN; this method never resubmits a goal.
        """
        if accepted is not True and accepted is not False and accepted is not None:
            raise ValueError("accepted must be true, false, or unknown")
        if accepted is True and driver_goal_id is None:
            raise ValueError("positive first-phase acceptance requires driver_goal_id")
        if accepted is not True and driver_goal_id is not None:
            raise ValueError("unaccepted first phase cannot have a driver_goal_id")
        if driver_goal_id is not None:
            driver_goal_id = _nonempty("driver_goal_id", driver_goal_id, maximum=192)
        action_id = _nonempty("action_id", action_id)
        attempt_id = _nonempty("attempt_id", attempt_id)
        phase_id = _nonempty("phase_id", phase_id, maximum=96)
        parent_state = "ACCEPTED" if accepted is True else "FAILED" if accepted is False else "UNKNOWN"
        phase_state = parent_state
        now = _utc_now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            action = self._require_attempt(connection, action_id, attempt_id, {"SUBMITTING"})
            phase = self._require_phase(
                connection, action_id, attempt_id, phase_id, {"SUBMITTING"},
            )
            if phase["ordinal"] != 0:
                raise InvalidActionTransition("first ROS phase ordinal must be zero")
            phase_count = connection.execute(
                "SELECT COUNT(*) FROM omx_action_phases WHERE action_id=? AND attempt_id=?",
                (action_id, attempt_id),
            ).fetchone()[0]
            if phase_count != 1:
                raise InvalidActionTransition("first ROS response requires exactly one phase intent")

            reason = "DRIVER_ACCEPTANCE_UNKNOWN" if accepted is None else None
            phase_reason = "DRIVER_ACCEPTANCE_UNKNOWN" if accepted is None else None
            connection.execute(
                """UPDATE omx_actions SET state=?, driver_goal_id=?, reason=?, updated_at=?
                   WHERE action_id=? AND attempt_id=? AND state='SUBMITTING'""",
                (parent_state, driver_goal_id, reason, now, action_id, attempt_id),
            )
            connection.execute(
                """UPDATE omx_action_phases SET state=?, driver_goal_id=?, reason=?, updated_at=?
                   WHERE action_id=? AND attempt_id=? AND phase_id=? AND state='SUBMITTING'""",
                (phase_state, driver_goal_id, phase_reason, now,
                 action_id, attempt_id, phase_id),
            )
            self._append_event(
                connection, action_id=action_id, attempt_id=attempt_id,
                state=parent_state, event_type="DRIVER_ACCEPTANCE_RECORDED",
                actor_id=action["principal_id"],
                detail={"accepted": accepted, "driver_goal_id": driver_goal_id,
                        "first_phase_id": phase_id}, created_at=now,
            )
            self._append_event(
                connection, action_id=action_id, attempt_id=attempt_id,
                state=phase_state, event_type="ACTION_PHASE_ACCEPTANCE_RECORDED",
                actor_id=action["principal_id"],
                detail={"phase_id": phase_id, "ordinal": 0, "accepted": accepted,
                        "driver_goal_id": driver_goal_id}, created_at=now,
            )
            updated_action = connection.execute(
                "SELECT * FROM omx_actions WHERE action_id=?", (action_id,),
            ).fetchone()
            updated_phase = connection.execute(
                "SELECT * FROM omx_action_phases WHERE action_id=? AND attempt_id=? AND phase_id=?",
                (action_id, attempt_id, phase_id),
            ).fetchone()
            connection.commit()
        return {"action": self._dict(updated_action), "phase": self._phase_dict(updated_phase)}

    def record_late_phase_acceptance(
        self, action_id: str, attempt_id: str, *, phase_id: str,
        driver_goal_id: str,
    ) -> dict[str, Any]:
        """Attach a late ROS UUID to an already held UNKNOWN phase without reopening it."""
        action_id = _nonempty("action_id", action_id)
        attempt_id = _nonempty("attempt_id", attempt_id)
        phase_id = _nonempty("phase_id", phase_id, maximum=96)
        driver_goal_id = _nonempty("driver_goal_id", driver_goal_id, maximum=192)
        now = _utc_now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            action = self._require_attempt(connection, action_id, attempt_id, {"UNKNOWN", "HOLD"})
            phase = self._require_phase(connection, action_id, attempt_id, phase_id, {"UNKNOWN"})
            if phase["driver_goal_id"] not in {None, driver_goal_id}:
                raise InvalidActionTransition("late ROS acceptance UUID conflicts with the phase journal")
            connection.execute(
                """UPDATE omx_action_phases SET driver_goal_id=?, updated_at=?
                   WHERE action_id=? AND attempt_id=? AND phase_id=? AND state='UNKNOWN'""",
                (driver_goal_id, now, action_id, attempt_id, phase_id),
            )
            self._append_event(
                connection, action_id=action_id, attempt_id=attempt_id,
                state=action["state"], event_type="ACTION_PHASE_LATE_GOAL_ACCEPTANCE_RECORDED",
                actor_id=action["principal_id"],
                detail={"phase_id": phase_id, "driver_goal_id": driver_goal_id,
                        "action_state_remains_held": True},
                created_at=now,
            )
            updated = connection.execute(
                "SELECT * FROM omx_action_phases WHERE action_id=? AND attempt_id=? AND phase_id=?",
                (action_id, attempt_id, phase_id),
            ).fetchone()
            connection.commit()
        return self._phase_dict(updated)

    def record_late_phase_cancel_request(
        self, action_id: str, attempt_id: str, *, phase_id: str,
        driver_goal_id: str,
    ) -> dict[str, Any]:
        """Journal exact-goal cancellation while preserving an UNKNOWN/HOLD phase."""
        action_id = _nonempty("action_id", action_id)
        attempt_id = _nonempty("attempt_id", attempt_id)
        phase_id = _nonempty("phase_id", phase_id, maximum=96)
        driver_goal_id = _nonempty("driver_goal_id", driver_goal_id, maximum=192)
        now = _utc_now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            action = self._require_attempt(connection, action_id, attempt_id, {"UNKNOWN", "HOLD"})
            phase = self._require_phase(connection, action_id, attempt_id, phase_id, {"UNKNOWN"})
            if phase["driver_goal_id"] != driver_goal_id:
                raise InvalidActionTransition("late cancel UUID does not match the held phase")
            self._append_event(
                connection, action_id=action_id, attempt_id=attempt_id,
                state=action["state"], event_type="ACTION_PHASE_LATE_CANCEL_REQUESTED",
                actor_id=action["principal_id"],
                detail={"phase_id": phase_id, "driver_goal_id": driver_goal_id,
                        "phase_state_remains_unknown": True},
                created_at=now,
            )
            updated = connection.execute(
                "SELECT * FROM omx_action_phases WHERE action_id=? AND attempt_id=? AND phase_id=?",
                (action_id, attempt_id, phase_id),
            ).fetchone()
            connection.commit()
        return self._phase_dict(updated)

    def mark_phase_running(self, action_id: str, attempt_id: str, *, phase_id: str,
                           driver_goal_id: str) -> dict[str, Any]:
        return self._transition_phase(
            action_id, attempt_id, phase_id=phase_id,
            allowed={"ACCEPTED"}, target="RUNNING", event_type="ACTION_PHASE_RUNNING",
            driver_goal_id=driver_goal_id,
        )

    def request_phase_cancel(self, action_id: str, attempt_id: str, *,
                             phase_id: str) -> dict[str, Any]:
        return self._transition_phase(
            action_id, attempt_id, phase_id=phase_id,
            allowed={"ACCEPTED", "RUNNING"}, target="CANCEL_REQUESTED",
            event_type="ACTION_PHASE_CANCEL_REQUESTED",
        )

    def record_phase_cancel_ack(self, action_id: str, attempt_id: str, *,
                                phase_id: str, acknowledged: bool) -> dict[str, Any]:
        if type(acknowledged) is not bool:
            raise ValueError("acknowledged must be boolean")
        phase_id = _nonempty("phase_id", phase_id, maximum=96)
        now = _utc_now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            action = self._require_attempt(
                connection, action_id, attempt_id,
                {"ACCEPTED", "RUNNING", "CANCEL_REQUESTED", "UNKNOWN", "HOLD"},
            )
            phase = self._require_phase(
                connection, action_id, attempt_id, phase_id, {"CANCEL_REQUESTED", "UNKNOWN"},
            )
            connection.execute(
                """UPDATE omx_action_phases SET cancel_acknowledged=?, updated_at=?
                   WHERE action_id=? AND attempt_id=? AND phase_id=?""",
                (int(acknowledged), now, action_id, attempt_id, phase_id),
            )
            self._append_event(
                connection, action_id=action_id, attempt_id=attempt_id,
                state=phase["state"], event_type="ACTION_PHASE_CANCEL_ACK_RECORDED",
                actor_id=action["principal_id"],
                detail={"phase_id": phase_id, "driver_goal_id": phase["driver_goal_id"],
                        "acknowledged": acknowledged}, created_at=now,
            )
            updated = self._require_phase(
                connection, action_id, attempt_id, phase_id,
                {"CANCEL_REQUESTED", "UNKNOWN"},
            )
            connection.commit()
        return self._phase_dict(updated)

    def record_phase_terminal(self, action_id: str, attempt_id: str, *, phase_id: str,
                              driver_goal_id: str, outcome: str, result_source: str,
                              result_observed_at: str,
                              result: Mapping[str, Any]) -> dict[str, Any]:
        if outcome not in {"SUCCEEDED", "FAILED", "CANCELED"}:
            raise ValueError("phase outcome must be SUCCEEDED, FAILED, or CANCELED")
        phase_id = _nonempty("phase_id", phase_id, maximum=96)
        driver_goal_id = _nonempty("driver_goal_id", driver_goal_id)
        result_source = _nonempty("result_source", result_source, maximum=96)
        result_observed_at = _nonempty("result_observed_at", result_observed_at)
        if not isinstance(result, Mapping):
            raise ValueError("result must be a JSON object")
        result_json = _json(dict(result))
        now = _utc_now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            action = self._require_attempt(
                connection, action_id, attempt_id,
                {"ACCEPTED", "RUNNING", "CANCEL_REQUESTED", "UNKNOWN", "HOLD"},
            )
            phase = self._require_phase(
                connection, action_id, attempt_id, phase_id,
                {"ACCEPTED", "RUNNING", "CANCEL_REQUESTED", "UNKNOWN"},
            )
            if phase["driver_goal_id"] != driver_goal_id:
                raise InvalidActionTransition("ROS goal identity does not match Action phase")
            connection.execute(
                """UPDATE omx_action_phases SET state=?, result_source=?, result_observed_at=?,
                   result_json=?, reason=NULL, updated_at=?
                   WHERE action_id=? AND attempt_id=? AND phase_id=?""",
                (outcome, result_source, result_observed_at, result_json, now,
                 action_id, attempt_id, phase_id),
            )
            self._append_event(
                connection, action_id=action_id, attempt_id=attempt_id, state=outcome,
                event_type="ACTION_PHASE_TERMINAL_RESULT", actor_id=action["principal_id"],
                detail={"phase_id": phase_id, "ordinal": phase["ordinal"],
                        "driver_goal_id": driver_goal_id, "result_source": result_source,
                        "result_observed_at": result_observed_at, "result": dict(result)},
                created_at=now,
            )
            if outcome == "CANCELED" and action["state"] != "HOLD":
                reason = "ROS_PHASE_CANCELED_ACTION_INCOMPLETE"
                connection.execute(
                    "UPDATE omx_actions SET state='HOLD', reason=?, updated_at=? WHERE action_id=?",
                    (reason, now, action_id),
                )
                self._append_event(
                    connection, action_id=action_id, attempt_id=attempt_id, state="HOLD",
                    event_type="ACTION_HELD", actor_id="system", detail={"reason": reason},
                    created_at=now,
                )
            updated = connection.execute(
                "SELECT * FROM omx_action_phases WHERE action_id=? AND attempt_id=? AND phase_id=?",
                (action_id, attempt_id, phase_id),
            ).fetchone()
            connection.commit()
        return self._phase_dict(updated)

    def record_workflow_state(
        self, action_id: str, attempt_id: str, *, workflow_state: str,
        object_may_be_held: bool, evidence_refs: Mapping[str, object],
    ) -> dict[str, Any]:
        """Append bounded semantic workflow evidence without inventing ROS goals."""
        if workflow_state not in _WORKFLOW_STATES:
            raise ValueError("unsupported pick-place workflow state")
        if type(object_may_be_held) is not bool:
            raise ValueError("object_may_be_held must be boolean")
        if not isinstance(evidence_refs, Mapping) or not set(evidence_refs) <= _WORKFLOW_EVIDENCE_KEYS:
            raise ValueError("workflow evidence refs contain unsupported fields")
        refs = dict(evidence_refs)
        for name, value in refs.items():
            if name.endswith("_sequence"):
                if type(value) is not int or value < 0:
                    raise ValueError(f"{name} must be a non-negative integer")
            else:
                _nonempty(name, value, maximum=192)
        _json(refs)
        if workflow_state == "ACTION_SUCCEEDED":
            if object_may_be_held or not {
                "gripper_hold_sequence", "gripper_release_sequence",
            } <= set(refs):
                raise InvalidActionTransition(
                    "Action success requires released-object readback evidence",
                )
            if refs["gripper_release_sequence"] <= refs["gripper_hold_sequence"]:
                raise InvalidActionTransition("release readback must follow the hold readback")
        now = _utc_now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            action = self._require_attempt(
                connection, action_id, attempt_id,
                {"SUBMITTING", "ACCEPTED", "RUNNING", "CANCEL_REQUESTED", "UNKNOWN", "HOLD"},
            )
            if action["state"] in {"UNKNOWN", "HOLD", "CANCEL_REQUESTED"} \
                    and workflow_state != "HOLD":
                raise InvalidActionTransition(
                    "unresolved or canceling Action can record HOLD only",
                )
            if workflow_state == "ACTION_SUCCEEDED":
                if action["state"] not in {"ACCEPTED", "RUNNING"}:
                    raise InvalidActionTransition("held or unresolved Action cannot complete")
                phases = connection.execute(
                    "SELECT phase_id, ordinal, state FROM omx_action_phases "
                    "WHERE action_id=? AND attempt_id=? ORDER BY ordinal",
                    (action_id, attempt_id),
                ).fetchall()
                if (tuple(row["phase_id"] for row in phases) != _PICK_PLACE_PHASES
                        or tuple(row["ordinal"] for row in phases) != tuple(range(4))
                        or any(row["state"] != "SUCCEEDED" for row in phases)):
                    raise InvalidActionTransition(
                        "completed workflow requires four successful ROS motion phases",
                    )
            detail = {
                "workflow_state": workflow_state,
                "object_may_be_held": object_may_be_held,
                "evidence_refs": refs,
            }
            self._append_event(
                connection, action_id=action_id, attempt_id=attempt_id,
                state=workflow_state, event_type="ACTION_WORKFLOW_STATE",
                actor_id=action["principal_id"], detail=detail, created_at=now,
            )
            event = connection.execute(
                "SELECT * FROM omx_action_events WHERE action_id=? ORDER BY event_id DESC LIMIT 1",
                (action_id,),
            ).fetchone()
            connection.commit()
        result = dict(event)
        result["detail"] = json.loads(result.pop("detail_json"))
        return result

    def complete_pick_place(self, action_id: str, attempt_id: str, *,
                            result_observed_at: str,
                            result: Mapping[str, Any]) -> dict[str, Any]:
        """Complete a local Action only after all phase and workflow evidence is durable."""
        result_observed_at = _nonempty("result_observed_at", result_observed_at)
        if not isinstance(result, Mapping):
            raise ValueError("result must be a JSON object")
        result_json = _json(dict(result))
        now = _utc_now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            action = self._require_attempt(
                connection, action_id, attempt_id, {"ACCEPTED", "RUNNING"},
            )
            phases = connection.execute(
                "SELECT phase_id, ordinal, state FROM omx_action_phases "
                "WHERE action_id=? AND attempt_id=? ORDER BY ordinal",
                (action_id, attempt_id),
            ).fetchall()
            latest_workflow = connection.execute(
                "SELECT detail_json FROM omx_action_events WHERE action_id=? AND attempt_id=? "
                "AND event_type='ACTION_WORKFLOW_STATE' ORDER BY event_id DESC LIMIT 1",
                (action_id, attempt_id),
            ).fetchone()
            if (tuple(row["phase_id"] for row in phases) != _PICK_PLACE_PHASES
                    or tuple(row["ordinal"] for row in phases) != tuple(range(4))
                    or any(row["state"] != "SUCCEEDED" for row in phases)):
                raise InvalidActionTransition("Action completion requires four successful ROS phases")
            if latest_workflow is None:
                raise InvalidActionTransition("Action completion requires durable workflow evidence")
            workflow = json.loads(latest_workflow["detail_json"])
            if (workflow.get("workflow_state") != "ACTION_SUCCEEDED"
                    or workflow.get("object_may_be_held") is not False):
                raise InvalidActionTransition("Action completion requires verified gripper release")
            refs = workflow.get("evidence_refs", {})
            if not {"gripper_hold_sequence", "gripper_release_sequence"} <= set(refs):
                raise InvalidActionTransition("Action completion evidence refs are incomplete")
            if refs["gripper_release_sequence"] <= refs["gripper_hold_sequence"]:
                raise InvalidActionTransition("release readback must follow the hold readback")
            connection.execute(
                """UPDATE omx_actions SET state='SUCCEEDED', result_source='pick-place-workflow',
                   result_observed_at=?, result_json=?, reason=NULL, updated_at=?
                   WHERE action_id=? AND attempt_id=?""",
                (result_observed_at, result_json, now, action_id, attempt_id),
            )
            self._append_event(
                connection, action_id=action_id, attempt_id=attempt_id, state="SUCCEEDED",
                event_type="PICK_PLACE_ACTION_COMPLETED", actor_id=action["principal_id"],
                detail={"result_source": "pick-place-workflow",
                        "result_observed_at": result_observed_at,
                        "phase_count": len(phases), "result": dict(result)},
                created_at=now,
            )
            updated = connection.execute(
                "SELECT * FROM omx_actions WHERE action_id=?", (action_id,),
            ).fetchone()
            connection.commit()
        return self._dict(updated)

    def _transition_phase(self, action_id: str, attempt_id: str, *, phase_id: str,
                          allowed: set[str], target: str, event_type: str,
                          driver_goal_id: str | None = None) -> dict[str, Any]:
        phase_id = _nonempty("phase_id", phase_id, maximum=96)
        if driver_goal_id is not None:
            driver_goal_id = _nonempty("driver_goal_id", driver_goal_id)
        now = _utc_now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            action = self._require_attempt(
                connection, action_id, attempt_id,
                {"ACCEPTED", "RUNNING", "CANCEL_REQUESTED", "UNKNOWN", "HOLD"},
            )
            phase = self._require_phase(connection, action_id, attempt_id, phase_id, allowed)
            if driver_goal_id is not None and phase["driver_goal_id"] != driver_goal_id:
                raise InvalidActionTransition("ROS goal identity does not match Action phase")
            connection.execute(
                "UPDATE omx_action_phases SET state=?, updated_at=? "
                "WHERE action_id=? AND attempt_id=? AND phase_id=?",
                (target, now, action_id, attempt_id, phase_id),
            )
            self._append_event(
                connection, action_id=action_id, attempt_id=attempt_id, state=target,
                event_type=event_type, actor_id=action["principal_id"],
                detail={"phase_id": phase_id, "driver_goal_id": phase["driver_goal_id"]},
                created_at=now,
            )
            updated = connection.execute(
                "SELECT * FROM omx_action_phases WHERE action_id=? AND attempt_id=? AND phase_id=?",
                (action_id, attempt_id, phase_id),
            ).fetchone()
            connection.commit()
        return self._phase_dict(updated)

    @staticmethod
    def _require_phase(connection: sqlite3.Connection, action_id: str, attempt_id: str,
                       phase_id: str, allowed: set[str]) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM omx_action_phases WHERE action_id=? AND attempt_id=? AND phase_id=?",
            (action_id, attempt_id, phase_id),
        ).fetchone()
        if row is None or row["state"] not in allowed:
            raise InvalidActionTransition("Action phase state does not allow this transition")
        return row

    def action_phases(self, action_id: str, attempt_id: str | None = None) -> list[dict[str, Any]]:
        action_id = _nonempty("action_id", action_id)
        with closing(self._connect()) as connection:
            if attempt_id is None:
                rows = connection.execute(
                    "SELECT * FROM omx_action_phases WHERE action_id=? ORDER BY attempt_id, ordinal",
                    (action_id,),
                ).fetchall()
            else:
                attempt_id = _nonempty("attempt_id", attempt_id)
                rows = connection.execute(
                    "SELECT * FROM omx_action_phases WHERE action_id=? AND attempt_id=? ORDER BY ordinal",
                    (action_id, attempt_id),
                ).fetchall()
        return [self._phase_dict(row) for row in rows]

    def action_phase_receipts(self, action_id: str, attempt_id: str) -> list[dict[str, Any]]:
        """Return bounded phase snapshots with each phase's latest local event ID."""
        phases = self.action_phases(action_id, attempt_id)
        if len(phases) > 4:
            raise InvalidActionTransition("pick-place phase journal exceeds its fixed bound")
        history = self.history(action_id)
        result = []
        for phase in phases:
            matching = [event for event in history
                        if event["attempt_id"] == attempt_id
                        and event["detail"].get("phase_id") == phase["phase_id"]
                        and event["event_type"].startswith("ACTION_PHASE_")]
            if not matching:
                raise InvalidActionTransition("phase journal has no durable event")
            result.append({
                "phase_id": phase["phase_id"], "ordinal": phase["ordinal"],
                "state": phase["state"], "journal_event_id": matching[-1]["event_id"],
                "observed_at": phase["updated_at"],
            })
        return result

    def latest_workflow_state(self, action_id: str, attempt_id: str) -> str | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT detail_json FROM omx_action_events WHERE action_id=? AND attempt_id=? "
                "AND event_type='ACTION_WORKFLOW_STATE' ORDER BY event_id DESC LIMIT 1",
                (action_id, attempt_id),
            ).fetchone()
        if row is None:
            return None
        detail = json.loads(row["detail_json"])
        state = detail.get("workflow_state")
        return state if state in _WORKFLOW_STATES else None

    def hold_action(self, action_id: str, attempt_id: str, *, reason: str) -> dict[str, Any]:
        reason = _nonempty("reason", reason, maximum=96)
        now = _utc_now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            action = self._require_attempt(
                connection, action_id, attempt_id,
                {"SUBMITTING", "ACCEPTED", "RUNNING", "CANCEL_REQUESTED", "UNKNOWN"},
            )
            connection.execute(
                "UPDATE omx_actions SET state='HOLD', reason=?, updated_at=? WHERE action_id=?",
                (reason, now, action_id),
            )
            self._append_event(
                connection, action_id=action_id, attempt_id=attempt_id, state="HOLD",
                event_type="ACTION_HELD", actor_id="system", detail={"reason": reason},
                created_at=now,
            )
            phases = connection.execute(
                """SELECT * FROM omx_action_phases WHERE action_id=? AND attempt_id=?
                   AND state IN ('SUBMITTING', 'ACCEPTED', 'RUNNING', 'CANCEL_REQUESTED')""",
                (action_id, attempt_id),
            ).fetchall()
            for phase in phases:
                connection.execute(
                    """UPDATE omx_action_phases SET state='UNKNOWN', reason=?, updated_at=?
                       WHERE action_id=? AND attempt_id=? AND phase_id=?""",
                    (reason, now, action_id, attempt_id, phase["phase_id"]),
                )
                self._append_event(
                    connection, action_id=action_id, attempt_id=attempt_id,
                    state="UNKNOWN", event_type="ACTION_PHASE_HELD_UNKNOWN",
                    actor_id=action["principal_id"],
                    detail={"phase_id": phase["phase_id"], "ordinal": phase["ordinal"],
                            "driver_goal_id": phase["driver_goal_id"], "reason": reason},
                    created_at=now,
                )
            updated = connection.execute("SELECT * FROM omx_actions WHERE action_id=?",
                                         (action_id,)).fetchone()
            connection.commit()
        return self._dict(updated)

    def _transition(self, action_id: str, attempt_id: str, *, allowed: set[str],
                    target: str, event_type: str, detail: object,
                    driver_goal_id: str | None = None) -> dict[str, Any]:
        now = _utc_now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._require_attempt(connection, action_id, attempt_id, allowed)
            if driver_goal_id is not None and row["driver_goal_id"] != driver_goal_id:
                raise InvalidActionTransition("driver goal identity does not match Action attempt")
            connection.execute(
                "UPDATE omx_actions SET state=?, updated_at=? WHERE action_id=? AND attempt_id=?",
                (target, now, action_id, attempt_id),
            )
            self._append_event(
                connection, action_id=action_id, attempt_id=attempt_id, state=target,
                event_type=event_type, actor_id=row["principal_id"], detail=detail,
                created_at=now,
            )
            updated = connection.execute("SELECT * FROM omx_actions WHERE action_id=?",
                                         (action_id,)).fetchone()
            connection.commit()
        return self._dict(updated)

    @staticmethod
    def _require_attempt(connection: sqlite3.Connection, action_id: str,
                         attempt_id: str, allowed: set[str]) -> sqlite3.Row:
        action_id = _nonempty("action_id", action_id)
        attempt_id = _nonempty("attempt_id", attempt_id)
        row = connection.execute("SELECT * FROM omx_actions WHERE action_id=?",
                                 (action_id,)).fetchone()
        if row is None:
            raise KeyError(action_id)
        if row["attempt_id"] != attempt_id or row["state"] not in allowed:
            raise InvalidActionTransition("Action state or attempt does not allow this transition")
        return row

    def recover_after_restart(self) -> list[str]:
        now = _utc_now()
        recovered: list[str] = []
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT * FROM omx_actions WHERE state IN "
                "('SUBMITTING', 'ACCEPTED', 'RUNNING', 'CANCEL_REQUESTED')"
            ).fetchall()
            for row in rows:
                connection.execute(
                    """UPDATE omx_actions SET state='UNKNOWN', reason=?, updated_at=?
                       WHERE action_id=?""",
                    ("PROCESS_RESTARTED_WITH_UNRESOLVED_ACTION", now, row["action_id"]),
                )
                self._append_event(
                    connection, action_id=row["action_id"], attempt_id=row["attempt_id"],
                    state="UNKNOWN", event_type="PROCESS_RESTARTED_UNRESOLVED",
                    actor_id="system", detail={"previous_state": row["state"]},
                    created_at=now,
                )
                all_phases = connection.execute(
                    "SELECT phase_id, ordinal, state, driver_goal_id FROM omx_action_phases "
                    "WHERE action_id=? AND attempt_id=? ORDER BY ordinal",
                    (row["action_id"], row["attempt_id"]),
                ).fetchall()
                phases = connection.execute(
                    """SELECT * FROM omx_action_phases WHERE action_id=? AND attempt_id=?
                       AND state IN ('SUBMITTING', 'ACCEPTED', 'RUNNING', 'CANCEL_REQUESTED')""",
                    (row["action_id"], row["attempt_id"]),
                ).fetchall()
                for phase in phases:
                    connection.execute(
                        """UPDATE omx_action_phases SET state='UNKNOWN', reason=?, updated_at=?
                           WHERE action_id=? AND attempt_id=? AND phase_id=?""",
                        ("PROCESS_RESTARTED_WITH_UNRESOLVED_PHASE", now,
                         row["action_id"], row["attempt_id"], phase["phase_id"]),
                    )
                    self._append_event(
                        connection, action_id=row["action_id"], attempt_id=row["attempt_id"],
                        state="UNKNOWN", event_type="ACTION_PHASE_RESTARTED_UNRESOLVED",
                        actor_id="system",
                        detail={"phase_id": phase["phase_id"], "ordinal": phase["ordinal"],
                                "previous_state": phase["state"],
                                "driver_goal_id": phase["driver_goal_id"]},
                        created_at=now,
                    )
                latest_workflow = connection.execute(
                    "SELECT detail_json FROM omx_action_events WHERE action_id=? "
                    "AND attempt_id=? AND event_type='ACTION_WORKFLOW_STATE' "
                    "ORDER BY event_id DESC LIMIT 1",
                    (row["action_id"], row["attempt_id"]),
                ).fetchone()
                workflow = (json.loads(latest_workflow["detail_json"])
                            if latest_workflow is not None else {})
                workflow_state = workflow.get("workflow_state")
                refs = workflow.get("evidence_refs", {})
                if not isinstance(refs, Mapping):
                    refs = {}
                held_states = {"VERIFY_HOLD", "TRANSFER", "RELEASE", "VERIFY_RELEASE", "HOLD"}
                object_may_be_held = (
                    workflow.get("object_may_be_held") is True
                    or workflow_state in held_states
                    or any(phase["ordinal"] > 0 and phase["state"] not in {"FAILED", "CANCELED"}
                           for phase in all_phases)
                )
                hold_refs = dict(refs)
                hold_refs["hold_reason"] = "PROCESS_RESTARTED_WITH_UNRESOLVED_ACTION"
                self._append_event(
                    connection, action_id=row["action_id"], attempt_id=row["attempt_id"],
                    state="HOLD", event_type="ACTION_WORKFLOW_STATE", actor_id="system",
                    detail={"workflow_state": "HOLD",
                            "object_may_be_held": object_may_be_held,
                            "evidence_refs": hold_refs},
                    created_at=now,
                )
                recovered.append(row["action_id"])
            connection.commit()
        return recovered

    def unresolved_actions(self, *, workcell_id: str | None = None) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            if workcell_id is None:
                rows = connection.execute(
                    "SELECT * FROM omx_actions WHERE state IN "
                    "('SUBMITTING', 'ACCEPTED', 'RUNNING', 'CANCEL_REQUESTED', 'UNKNOWN', 'HOLD') "
                    "ORDER BY created_at, action_id"
                ).fetchall()
            else:
                workcell_id = _nonempty("workcell_id", workcell_id, maximum=96)
                rows = connection.execute(
                    "SELECT * FROM omx_actions WHERE workcell_id=? AND state IN "
                    "('SUBMITTING', 'ACCEPTED', 'RUNNING', 'CANCEL_REQUESTED', 'UNKNOWN', 'HOLD') "
                    "ORDER BY created_at, action_id",
                    (workcell_id,),
                ).fetchall()
        return [self._dict(row) for row in rows]

    def get_action(self, action_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM omx_actions WHERE action_id=?",
                                     (action_id,)).fetchone()
            latest_event = connection.execute(
                "SELECT MAX(event_id) FROM omx_action_events WHERE action_id=?",
                (action_id,),
            ).fetchone()
        result = self._dict(row)
        if result is not None:
            result["journal_event_id"] = latest_event[0]
        return result

    def latest_event_id(self, action_id: str) -> int | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT MAX(event_id) FROM omx_action_events WHERE action_id=?",
                (action_id,),
            ).fetchone()
        return int(row[0]) if row is not None and row[0] is not None else None

    def get_by_request(self, *, workcell_id: str, principal_id: str,
                       request_key: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT * FROM omx_actions WHERE workcell_id=? AND principal_id=?
                   AND request_key=?""",
                (workcell_id, principal_id, request_key),
            ).fetchone()
        return self._dict(row)

    def history(self, action_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM omx_action_events WHERE action_id=? ORDER BY event_id",
                (action_id,),
            ).fetchall()
        events = [dict(row) for row in rows]
        for event in events:
            event["detail"] = json.loads(event.pop("detail_json"))
        return events
