"""Single-step Mission journal sharing Fleet's SQLite resource claims.

This is an internal SOURCE store. It defines no public REST route and contains
no Mission dispatcher; device-side stop-generation enforcement is still absent.
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

from .dispatch_admission import release as release_dispatch_claims
from .dispatch_admission import reserve as reserve_dispatch_claims
from .goal_evidence import GoalEvidence, GoalPredicate


class MissionConflict(ValueError):
    """Mission request, admission, or event conflicts with durable state."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _nonempty(name: str, value: object, *, limit: int = 192) -> str:
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or len(value) > limit or any(ord(char) < 32 for char in value)):
        raise ValueError(f"{name} must be a non-empty trimmed string of at most {limit} characters")
    return value


def _json(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("Mission data must be finite JSON") from exc


class MissionStore:
    """Atomic Mission proposals/admission/results on the Fleet task database."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS fleet_missions (
                    mission_id TEXT PRIMARY KEY,
                    step_id TEXT NOT NULL UNIQUE,
                    principal_id TEXT NOT NULL,
                    request_key TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    action_kind TEXT NOT NULL CHECK(action_kind='PICK_PLACE'),
                    workcell_id TEXT NOT NULL,
                    instance_id TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    goal_predicate_json TEXT NOT NULL,
                    resources_json TEXT,
                    status TEXT NOT NULL CHECK(status IN (
                        'PROPOSED', 'READY', 'RUNNING', 'ACTION_SUCCEEDED',
                        'GOAL_CONFIRMED', 'HOLD', 'CANCELED'
                    )),
                    dispatch_generation INTEGER,
                    action_id TEXT,
                    attempt_id TEXT,
                    reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(principal_id, request_key)
                );
                CREATE INDEX IF NOT EXISTS fleet_missions_status
                    ON fleet_missions(status, updated_at);
                CREATE TABLE IF NOT EXISTS fleet_mission_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_source TEXT NOT NULL,
                    source_event_id TEXT NOT NULL,
                    mission_id TEXT NOT NULL REFERENCES fleet_missions(mission_id),
                    step_id TEXT NOT NULL,
                    action_id TEXT,
                    attempt_id TEXT,
                    state TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(event_source, source_event_id)
                );
                CREATE INDEX IF NOT EXISTS fleet_mission_events_mission
                    ON fleet_mission_events(mission_id, event_id);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        for field in ("plan_json", "goal_predicate_json", "resources_json"):
            if result[field] is not None:
                result[field.removesuffix("_json")] = json.loads(result[field])
                del result[field]
        return result

    def _event(self, connection: sqlite3.Connection, *, event_source: str,
               source_event_id: str, mission: sqlite3.Row, event_type: str,
               state: str, actor_id: str, detail: object,
               action_id: str | None = None, attempt_id: str | None = None) -> bool:
        source_event_id = _nonempty("source_event_id", source_event_id)
        event_source = _nonempty("event_source", event_source, limit=48)
        detail_json = _json(detail)
        prior = connection.execute(
            "SELECT * FROM fleet_mission_events WHERE event_source=? AND source_event_id=?",
            (event_source, source_event_id),
        ).fetchone()
        if prior is not None:
            if (prior["mission_id"] != mission["mission_id"]
                    or prior["step_id"] != mission["step_id"]
                    or prior["action_id"] != action_id
                    or prior["attempt_id"] != attempt_id
                    or prior["state"] != state
                    or prior["event_type"] != event_type
                    or prior["actor_id"] != actor_id
                    or prior["detail_json"] != detail_json):
                raise MissionConflict("event identity was reused with different Mission evidence")
            return False
        connection.execute(
            """INSERT INTO fleet_mission_events
               (event_source, source_event_id, mission_id, step_id, action_id, attempt_id,
                state, event_type, actor_id, detail_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (event_source, source_event_id, mission["mission_id"], mission["step_id"],
             action_id, attempt_id, state, event_type, actor_id, detail_json, _now()),
        )
        return True

    def create_proposal(self, *, mission_id: str, principal_id: str, request_key: str,
                        action_kind: str, workcell_id: str, instance_id: str,
                        plan: Mapping[str, Any], goal_predicate: Mapping[str, Any]) -> dict[str, Any]:
        mission_id = _nonempty("mission_id", mission_id)
        principal_id = _nonempty("principal_id", principal_id, limit=96)
        request_key = _nonempty("request_key", request_key, limit=160)
        workcell_id = _nonempty("workcell_id", workcell_id, limit=96)
        instance_id = _nonempty("instance_id", instance_id, limit=96)
        if action_kind != "PICK_PLACE":
            raise ValueError("only the fixed-workcell PICK_PLACE proposal is supported")
        if not isinstance(plan, Mapping):
            raise ValueError("plan must be a JSON object")
        predicate = GoalPredicate.from_mapping(dict(goal_predicate))
        plan_json = _json(dict(plan))
        predicate_json = _json(predicate.to_dict())
        request_document = {
            "action_kind": action_kind, "workcell_id": workcell_id,
            "instance_id": instance_id, "plan": json.loads(plan_json),
            "goal_predicate": predicate.to_dict(),
        }
        digest = hashlib.sha256(_json(request_document).encode("utf-8")).hexdigest()
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = connection.execute(
                "SELECT * FROM fleet_missions WHERE principal_id=? AND request_key=?",
                (principal_id, request_key),
            ).fetchone()
            if prior is not None:
                if prior["request_digest"] != digest:
                    raise MissionConflict("request_key is already bound to a different Mission proposal")
                connection.commit()
                return {"mission": self._row(prior), "created": False}
            step_id = f"{mission_id}:step-1"
            connection.execute(
                """INSERT INTO fleet_missions
                   (mission_id, step_id, principal_id, request_key, request_digest,
                    action_kind, workcell_id, instance_id, plan_json, goal_predicate_json,
                    status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PROPOSED', ?, ?)""",
                (mission_id, step_id, principal_id, request_key, digest, action_kind,
                 workcell_id, instance_id, plan_json, predicate_json, now, now),
            )
            row = connection.execute("SELECT * FROM fleet_missions WHERE mission_id=?",
                                     (mission_id,)).fetchone()
            self._event(
                connection, event_source="fleet_mission", source_event_id=f"proposal:{mission_id}",
                mission=row, event_type="MISSION_PROPOSED", state="PROPOSED",
                actor_id=principal_id, detail={"request_digest": digest},
            )
            row = connection.execute("SELECT * FROM fleet_missions WHERE mission_id=?",
                                     (mission_id,)).fetchone()
            connection.commit()
        return {"mission": self._row(row), "created": True}

    def admit(self, mission_id: str, *, actor_id: str, expected_generation: int,
              resources: list[tuple[str, str]]) -> dict[str, Any]:
        actor_id = _nonempty("actor_id", actor_id, limit=96)
        if type(expected_generation) is not int or expected_generation < 0:
            raise ValueError("expected_generation must be a non-negative integer")
        resources_json = _json([list(item) for item in sorted(set(resources))])
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM fleet_missions WHERE mission_id=?",
                                     (mission_id,)).fetchone()
            if row is None:
                raise KeyError(mission_id)
            if row["status"] != "PROPOSED":
                raise MissionConflict("only a PROPOSED Mission can be admitted")
            control = connection.execute(
                "SELECT generation, dispatch_enabled FROM fleet_dispatch_control WHERE control_id=1"
            ).fetchone()
            if not control["dispatch_enabled"] or control["generation"] != expected_generation:
                raise MissionConflict("stop generation is closed or changed")
            if not reserve_dispatch_claims(
                    connection, owner_kind="mission", owner_id=mission_id,
                    generation=expected_generation, resources=resources, phase="CLAIMED"):
                raise MissionConflict("Mission resource claim conflicts with another action")
            connection.execute(
                """UPDATE fleet_missions SET status='READY', dispatch_generation=?,
                   resources_json=?, updated_at=? WHERE mission_id=?""",
                (expected_generation, resources_json, now, mission_id),
            )
            self._event(
                connection, event_source="fleet_mission", source_event_id=f"admit:{mission_id}:{expected_generation}",
                mission=row, event_type="MISSION_ADMITTED", state="READY",
                actor_id=actor_id,
                detail={"dispatch_generation": expected_generation,
                        "resources": json.loads(resources_json)},
            )
            updated = connection.execute("SELECT * FROM fleet_missions WHERE mission_id=?",
                                         (mission_id,)).fetchone()
            connection.commit()
        return self._row(updated)

    def start_step(self, mission_id: str, *, action_id: str, attempt_id: str,
                   expected_generation: int) -> dict[str, Any]:
        action_id = _nonempty("action_id", action_id)
        attempt_id = _nonempty("attempt_id", attempt_id)
        if type(expected_generation) is not int or expected_generation < 0:
            raise ValueError("expected_generation must be a non-negative integer")
        now = _now()
        rejected_reason = None
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM fleet_missions WHERE mission_id=?",
                                     (mission_id,)).fetchone()
            if row is None:
                raise KeyError(mission_id)
            control = connection.execute(
                "SELECT generation, dispatch_enabled FROM fleet_dispatch_control WHERE control_id=1"
            ).fetchone()
            if row["status"] != "READY":
                raise MissionConflict("only a READY Mission step may start")
            if (not control["dispatch_enabled"] or control["generation"] != expected_generation
                    or row["dispatch_generation"] != expected_generation):
                rejected_reason = "stop generation changed before Mission step submission"
            else:
                resources = json.loads(row["resources_json"] or "[]")
                expected_keys = {f"{kind}:{resource}" for kind, resource in resources}
                claims = connection.execute(
                    """SELECT resource_key FROM fleet_action_claims WHERE owner_kind='mission'
                       AND owner_id=? AND generation=? AND phase='CLAIMED'""",
                    (mission_id, expected_generation),
                ).fetchall()
                if {claim["resource_key"] for claim in claims} != expected_keys:
                    rejected_reason = "Mission resource claim is no longer complete"
            if rejected_reason:
                reason_code = ("STOP_GENERATION_CHANGED_BEFORE_SUBMISSION"
                               if "stop generation" in rejected_reason
                               else "MISSION_RESOURCE_CLAIM_LOST")
                connection.execute(
                    "UPDATE fleet_missions SET status='HOLD', reason=?, updated_at=? WHERE mission_id=?",
                    (reason_code, now, mission_id),
                )
                self._event(
                    connection, event_source="fleet_mission",
                    source_event_id=f"hold-before-submit:{mission_id}:{row['dispatch_generation']}",
                    mission=row, event_type="STEP_HELD_BEFORE_SUBMISSION", state="HOLD",
                    actor_id=row["principal_id"], action_id=action_id, attempt_id=attempt_id,
                    detail={"reason": reason_code, "expected_generation": expected_generation,
                            "current_generation": control["generation"],
                            "dispatch_enabled": bool(control["dispatch_enabled"])},
                )
                release_dispatch_claims(
                    connection, owner_kind="mission", owner_id=mission_id,
                    generation=row["dispatch_generation"],
                )
            else:
                connection.execute(
                    """UPDATE fleet_action_claims SET phase='DISPATCHING', lease_until=NULL
                       WHERE owner_kind='mission' AND owner_id=? AND generation=? AND phase='CLAIMED'""",
                    (mission_id, expected_generation),
                )
                connection.execute(
                    """UPDATE fleet_missions SET status='RUNNING', action_id=?, attempt_id=?,
                       updated_at=? WHERE mission_id=?""",
                    (action_id, attempt_id, now, mission_id),
                )
                self._event(
                    connection, event_source="fleet_mission", source_event_id=f"submit:{attempt_id}",
                    mission=row, event_type="STEP_SUBMITTED", state="RUNNING", actor_id=row["principal_id"],
                    action_id=action_id, attempt_id=attempt_id,
                    detail={"dispatch_generation": expected_generation},
                )
            updated = connection.execute("SELECT * FROM fleet_missions WHERE mission_id=?",
                                         (mission_id,)).fetchone()
            connection.commit()
        if rejected_reason:
            raise MissionConflict(rejected_reason)
        return self._row(updated)

    def record_action_result(self, mission_id: str, *, event_id: str, action_id: str,
                             attempt_id: str, outcome: str,
                             result: Mapping[str, Any]) -> dict[str, Any]:
        if outcome not in {"SUCCEEDED", "FAILED", "UNKNOWN", "HOLD"}:
            raise ValueError("unsupported terminal Action outcome")
        if not isinstance(result, Mapping):
            raise ValueError("Action result must be a JSON object")
        detail = {"outcome": outcome, "result": dict(result)}
        detail_json = _json(detail)
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM fleet_missions WHERE mission_id=?",
                                     (mission_id,)).fetchone()
            if row is None:
                raise KeyError(mission_id)
            duplicate = connection.execute(
                "SELECT * FROM fleet_mission_events WHERE event_source='device_action' AND source_event_id=?",
                (event_id,),
            ).fetchone()
            if duplicate is not None:
                if (duplicate["mission_id"] != mission_id or duplicate["action_id"] != action_id
                        or duplicate["attempt_id"] != attempt_id
                        or duplicate["event_type"] != "ACTION_TERMINAL_RESULT"
                        or duplicate["detail_json"] != detail_json):
                    raise MissionConflict("device Action event ID was reused with different evidence")
                connection.commit()
                return self._row(row)
            if (row["status"] != "RUNNING" or row["action_id"] != action_id
                    or row["attempt_id"] != attempt_id):
                raise MissionConflict("Action result does not match the active Mission attempt")
            target_state = "ACTION_SUCCEEDED" if outcome == "SUCCEEDED" else "HOLD"
            connection.execute(
                "UPDATE fleet_missions SET status=?, reason=?, updated_at=? WHERE mission_id=?",
                (target_state, None if outcome == "SUCCEEDED" else f"ACTION_{outcome}", now, mission_id),
            )
            self._event(
                connection, event_source="device_action", source_event_id=event_id,
                mission=row, event_type="ACTION_TERMINAL_RESULT", state=target_state,
                actor_id=row["principal_id"], action_id=action_id,
                attempt_id=attempt_id, detail=detail,
            )
            updated = connection.execute("SELECT * FROM fleet_missions WHERE mission_id=?",
                                         (mission_id,)).fetchone()
            connection.commit()
        return self._row(updated)

    def hold_mission(self, mission_id: str, *, actor_id: str, event_id: str,
                     reason: str, evidence: Mapping[str, Any]) -> dict[str, Any]:
        reason = _nonempty("reason", reason, limit=96)
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM fleet_missions WHERE mission_id=?",
                                     (mission_id,)).fetchone()
            if row is None:
                raise KeyError(mission_id)
            if row["status"] not in {"ACTION_SUCCEEDED", "HOLD"}:
                raise MissionConflict("only an Action result or held Mission can be reconciled")
            connection.execute(
                "UPDATE fleet_missions SET status='HOLD', reason=?, updated_at=? WHERE mission_id=?",
                (reason, now, mission_id),
            )
            self._event(
                connection, event_source="goal_evidence", source_event_id=event_id,
                mission=row, event_type="GOAL_EVIDENCE_REJECTED", state="HOLD",
                actor_id=actor_id, action_id=row["action_id"], attempt_id=row["attempt_id"],
                detail={"reason": reason, "evidence": dict(evidence)},
            )
            updated = connection.execute("SELECT * FROM fleet_missions WHERE mission_id=?",
                                         (mission_id,)).fetchone()
            connection.commit()
        return self._row(updated)

    def confirm_goal(self, mission_id: str, *, actor_id: str, event_id: str,
                     evidence: GoalEvidence) -> dict[str, Any]:
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM fleet_missions WHERE mission_id=?",
                                     (mission_id,)).fetchone()
            if row is None:
                raise KeyError(mission_id)
            if row["status"] != "ACTION_SUCCEEDED":
                raise MissionConflict("independent goal evidence requires terminal Action success")
            detail = evidence.to_dict()
            self._event(
                connection, event_source="goal_evidence", source_event_id=event_id,
                mission=row, event_type="GOAL_PREDICATE_CONFIRMED", state="GOAL_CONFIRMED",
                actor_id=actor_id, action_id=row["action_id"], attempt_id=row["attempt_id"],
                detail=detail,
            )
            released = release_dispatch_claims(
                connection, owner_kind="mission", owner_id=mission_id,
                generation=row["dispatch_generation"],
            )
            if released <= 0:
                raise MissionConflict("Mission cannot complete without its durable resource claims")
            connection.execute(
                "UPDATE fleet_missions SET status='GOAL_CONFIRMED', reason=NULL, updated_at=? WHERE mission_id=?",
                (now, mission_id),
            )
            updated = connection.execute("SELECT * FROM fleet_missions WHERE mission_id=?",
                                         (mission_id,)).fetchone()
            connection.commit()
        return self._row(updated)

    def get_mission(self, mission_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM fleet_missions WHERE mission_id=?",
                                     (mission_id,)).fetchone()
        return self._row(row)

    def history(self, mission_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM fleet_mission_events WHERE mission_id=? ORDER BY event_id",
                (mission_id,),
            ).fetchall()
        result = [dict(row) for row in rows]
        for event in result:
            event["detail"] = json.loads(event.pop("detail_json"))
        return result
