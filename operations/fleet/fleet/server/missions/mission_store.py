"""Single-step Mission journal sharing Fleet's SQLite resource claims.

This is an internal SOURCE store. REST routes and device transport are owned by
the Site Fleet application and mission dispatcher.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing, nullcontext
from pathlib import Path
from typing import Any, Mapping

from core_common.protocol.schemas import (
    DeviceActionPhaseReceipt, MISSION_EVENT_DETAIL_MAX_BYTES,
)

from .dispatch_admission import release as release_dispatch_claims
from .dispatch_admission import reserve as reserve_dispatch_claims
from .mission_store_helpers import (
    MissionConflict,
    MissionStoreHelpersMixin,
    _ensure_mission_schema,
    _json,
    _json_utf8_size,
    _nonempty,
    _now,
    _phase_event_key,
)
from rosy.execution.site.goal_evidence import GoalEvidence, GoalPredicate
from .sqlite_policy import configure_connection, enable_wal

__all__ = [
    "MISSION_EVENT_DETAIL_MAX_BYTES",
    "MissionConflict",
    "MissionStore",
    "_json",
    "_json_utf8_size",
    "_nonempty",
    "_now",
    "_phase_event_key",
]


class MissionStore(MissionStoreHelpersMixin):
    """Atomic Mission proposals/admission/results on the Fleet task database."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        with closing(self._connect()) as connection:
            enable_wal(connection)
            _ensure_mission_schema(connection)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return configure_connection(connection)

    def create_proposal(self, *, mission_id: str, principal_id: str, request_key: str,
                        action_kind: str, workcell_id: str, instance_id: str,
                        plan: Mapping[str, Any], goal_predicate: Mapping[str, Any],
                        supersedes_mission_id: str | None = None,
                        connection: sqlite3.Connection | None = None) -> dict[str, Any]:
        mission_id = _nonempty("mission_id", mission_id)
        principal_id = _nonempty("principal_id", principal_id, limit=96)
        request_key = _nonempty("request_key", request_key, limit=160)
        workcell_id = _nonempty("workcell_id", workcell_id, limit=96)
        instance_id = _nonempty("instance_id", instance_id, limit=96)
        if supersedes_mission_id is not None:
            supersedes_mission_id = _nonempty(
                "supersedes_mission_id", supersedes_mission_id,
            )
            if supersedes_mission_id == mission_id:
                raise ValueError("a Mission cannot supersede itself")
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
        if supersedes_mission_id is not None:
            request_document["supersedes_mission_id"] = supersedes_mission_id
        digest = hashlib.sha256(_json(request_document).encode("utf-8")).hexdigest()
        now = _now()
        owns_transaction = connection is None
        connection_context = closing(self._connect()) if owns_transaction else nullcontext(connection)
        with connection_context as db:
            if owns_transaction:
                db.execute("BEGIN IMMEDIATE")
            prior = db.execute(
                "SELECT * FROM fleet_missions WHERE principal_id=? AND request_key=?",
                (principal_id, request_key),
            ).fetchone()
            if prior is not None:
                if prior["request_digest"] != digest:
                    raise MissionConflict("request_key is already bound to a different Mission proposal")
                if owns_transaction:
                    db.commit()
                return {"mission": self._row(prior), "created": False}
            step_id = f"{mission_id}:step-1"
            db.execute(
                """INSERT INTO fleet_missions
                   (mission_id, step_id, principal_id, request_key, request_digest,
                    action_kind, workcell_id, instance_id, plan_json, goal_predicate_json,
                    supersedes_mission_id, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PROPOSED', ?, ?)""",
                (mission_id, step_id, principal_id, request_key, digest, action_kind,
                 workcell_id, instance_id, plan_json, predicate_json,
                 supersedes_mission_id, now, now),
            )
            row = db.execute("SELECT * FROM fleet_missions WHERE mission_id=?",
                             (mission_id,)).fetchone()
            self._event(
                db, event_source="fleet_mission", source_event_id=f"proposal:{mission_id}",
                mission=row, event_type="MISSION_PROPOSED", state="PROPOSED",
                actor_id=principal_id, detail={"request_digest": digest},
            )
            row = db.execute("SELECT * FROM fleet_missions WHERE mission_id=?",
                             (mission_id,)).fetchone()
            if owns_transaction:
                db.commit()
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
                "SELECT authority_epoch, generation, dispatch_enabled "
                "FROM fleet_dispatch_control WHERE control_id=1"
            ).fetchone()
            if not control["dispatch_enabled"] or control["generation"] != expected_generation:
                raise MissionConflict("stop generation is closed or changed")
            if not reserve_dispatch_claims(
                    connection, owner_kind="mission", owner_id=mission_id,
                    generation=expected_generation, resources=resources, phase="CLAIMED"):
                raise MissionConflict("Mission resource claim conflicts with another action")
            connection.execute(
                """UPDATE fleet_missions SET status='READY', authority_epoch=?,
                   dispatch_generation=?, resources_json=?, updated_at=? WHERE mission_id=?""",
                (control["authority_epoch"], expected_generation, resources_json, now, mission_id),
            )
            self._event(
                connection, event_source="fleet_mission", source_event_id=f"admit:{mission_id}:{expected_generation}",
                mission=row, event_type="MISSION_ADMITTED", state="READY",
                actor_id=actor_id,
                detail={"authority_epoch": control["authority_epoch"],
                        "dispatch_generation": expected_generation,
                        "resources": json.loads(resources_json)},
            )
            updated = connection.execute("SELECT * FROM fleet_missions WHERE mission_id=?",
                                         (mission_id,)).fetchone()
            connection.commit()
        return self._row(updated)

    def start_step(self, mission_id: str, *, action_id: str, attempt_id: str,
                   expected_authority_epoch: int,
                   expected_generation: int,
                   action_grant: Mapping[str, Any] | None = None) -> dict[str, Any]:
        action_id = _nonempty("action_id", action_id)
        attempt_id = _nonempty("attempt_id", attempt_id)
        if (type(expected_authority_epoch) is not int or expected_authority_epoch < 0
                or type(expected_generation) is not int or expected_generation < 0):
            raise ValueError("authority epoch and generation must be non-negative integers")
        action_grant_json = None
        if action_grant is not None:
            if not isinstance(action_grant, Mapping):
                raise ValueError("Action grant must be a JSON object")
            grant = dict(action_grant)
            if (grant.get("mission_id") != mission_id
                    or grant.get("action_id") != action_id
                    or grant.get("attempt_id") != attempt_id
                    or grant.get("authority_epoch") != expected_authority_epoch
                    or grant.get("dispatch_generation") != expected_generation):
                raise ValueError("Action grant identity or fence does not match Mission start")
            action_grant_json = _json(grant)
        now = _now()
        rejected_reason = None
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM fleet_missions WHERE mission_id=?",
                                     (mission_id,)).fetchone()
            if row is None:
                raise KeyError(mission_id)
            control = connection.execute(
                "SELECT authority_epoch, generation, dispatch_enabled "
                "FROM fleet_dispatch_control WHERE control_id=1"
            ).fetchone()
            if row["status"] != "READY":
                raise MissionConflict("only a READY Mission step may start")
            if (not control["dispatch_enabled"]
                    or control["authority_epoch"] != expected_authority_epoch
                    or control["generation"] != expected_generation
                    or row["authority_epoch"] != expected_authority_epoch
                    or row["dispatch_generation"] != expected_generation):
                rejected_reason = "Fleet authority or stop generation changed before Mission step submission"
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
                reason_code = ("FLEET_FENCE_CHANGED_BEFORE_SUBMISSION"
                               if "generation" in rejected_reason
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
                    detail={"reason": reason_code,
                            "expected_authority_epoch": expected_authority_epoch,
                            "current_authority_epoch": control["authority_epoch"],
                            "expected_generation": expected_generation,
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
                       action_grant_json=?, updated_at=? WHERE mission_id=?""",
                    (action_id, attempt_id, action_grant_json, now, mission_id),
                )
                self._event(
                    connection, event_source="fleet_mission", source_event_id=f"submit:{attempt_id}",
                    mission=row, event_type="STEP_SUBMITTED", state="RUNNING", actor_id=row["principal_id"],
                    action_id=action_id, attempt_id=attempt_id,
                    detail={"authority_epoch": expected_authority_epoch,
                            "dispatch_generation": expected_generation,
                            "request_digest": (grant.get("request_digest")
                                               if action_grant is not None else None)},
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
            reconciling_hold = (row["status"] == "HOLD" and row["reconciliation_pending"])
            if ((row["status"] != "RUNNING" and not reconciling_hold)
                    or row["action_id"] != action_id or row["attempt_id"] != attempt_id):
                raise MissionConflict("Action result does not match the active Mission attempt")
            late_success_requires_goal = reconciling_hold and outcome == "SUCCEEDED"
            target_state = ("HOLD" if late_success_requires_goal else
                            "ACTION_SUCCEEDED" if outcome == "SUCCEEDED" else "HOLD")
            reason = ("LATE_SUCCESS_REQUIRES_INDEPENDENT_GOAL_EVIDENCE"
                      if late_success_requires_goal else
                      None if outcome == "SUCCEEDED" else f"ACTION_{outcome}")
            connection.execute(
                "UPDATE fleet_missions SET status=?, reason=?, updated_at=? WHERE mission_id=?",
                (target_state, reason, now, mission_id),
            )
            connection.execute(
                "UPDATE fleet_missions SET reconciliation_pending=? WHERE mission_id=?",
                (1 if outcome == "UNKNOWN" and result.get("reason") in {
                    "LOCAL_ACTION_SUBMIT_OUTCOME_UNKNOWN", "LOCAL_ACTION_READBACK_UNKNOWN"
                } else 0, mission_id),
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

    def record_action_phase_summaries(self, mission_id: str, *, action_id: str,
                                      attempt_id: str, authority_epoch: int,
                                      dispatch_generation: int,
                                      phases: list[Mapping[str, Any]]) -> dict[str, Any]:
        """Atomically append idempotent, attempt-fenced local phase snapshots."""
        if type(authority_epoch) is not int or type(dispatch_generation) is not int:
            raise ValueError("phase receipt fence must be integer-valued")
        if not isinstance(phases, list) or len(phases) > 4:
            raise ValueError("phase summaries must be a bounded list")
        phases = [DeviceActionPhaseReceipt.model_validate(phase).model_dump(mode="json")
                  for phase in phases]
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM fleet_missions WHERE mission_id=?", (mission_id,),
            ).fetchone()
            if row is None:
                raise KeyError(mission_id)
            if (row["action_id"] != action_id or row["attempt_id"] != attempt_id
                    or row["authority_epoch"] != authority_epoch
                    or row["dispatch_generation"] != dispatch_generation
                    or row["status"] not in {
                        "RUNNING", "ACTION_SUCCEEDED", "HOLD", "GOAL_CONFIRMED",
                    }):
                raise MissionConflict("phase receipt does not match the active Mission attempt")

            prior_rows = connection.execute(
                "SELECT * FROM fleet_mission_events WHERE mission_id=? AND action_id=? "
                "AND attempt_id=? AND event_source='device_action_phase' ORDER BY event_id",
                (mission_id, action_id, attempt_id),
            ).fetchall()
            latest: dict[int, dict[str, Any]] = {}
            for prior in prior_rows:
                detail = json.loads(prior["detail_json"])
                ordinal = detail["ordinal"]
                if (ordinal not in latest or detail["source_journal_event_id"]
                        > latest[ordinal]["detail"]["source_journal_event_id"]):
                    latest[ordinal] = {"detail": detail}

            for phase in phases:
                if not isinstance(phase, Mapping):
                    raise ValueError("phase snapshot must be an object")
                ordinal = phase.get("ordinal")
                source_event_id = phase.get("journal_event_id")
                if (type(ordinal) is not int or not 0 <= ordinal < 4
                        or type(source_event_id) is not int or source_event_id < 1):
                    raise ValueError("phase snapshot identity is invalid")
                detail = {
                    "phase_id": phase["phase_id"], "ordinal": ordinal,
                    "state": phase["state"], "observed_at": phase["observed_at"],
                    "source_journal_event_id": source_event_id,
                }
                event_key = _phase_event_key(
                    mission_id, action_id, attempt_id, ordinal, source_event_id,
                )
                self._event(
                    connection, event_source="device_action_phase",
                    source_event_id=event_key, mission=row,
                    event_type="ACTION_PHASE_SNAPSHOT", state=phase["state"],
                    actor_id="device-action", action_id=action_id,
                    attempt_id=attempt_id, detail=detail,
                )
                previous = latest.get(ordinal)
                if previous is not None:
                    previous_id = previous["detail"]["source_journal_event_id"]
                    if source_event_id <= previous_id:
                        continue
                    allowed_next = {
                        "SUBMITTING": {"ACCEPTED", "RUNNING", "CANCEL_REQUESTED",
                                       "UNKNOWN", "SUCCEEDED", "FAILED", "CANCELED"},
                        "ACCEPTED": {"RUNNING", "CANCEL_REQUESTED", "UNKNOWN",
                                     "SUCCEEDED", "FAILED", "CANCELED"},
                        "RUNNING": {"CANCEL_REQUESTED", "UNKNOWN", "SUCCEEDED",
                                    "FAILED", "CANCELED"},
                        "CANCEL_REQUESTED": {"UNKNOWN", "SUCCEEDED", "FAILED", "CANCELED"},
                    }
                    prior_state = previous["detail"]["state"]
                    if (prior_state not in allowed_next
                            or phase["state"] not in allowed_next[prior_state]
                            and phase["state"] != prior_state):
                        raise MissionConflict("phase receipt regresses or changes a terminal phase")
                if ordinal > 0:
                    previous_phase = latest.get(ordinal - 1)
                    if previous_phase is None or previous_phase["detail"]["state"] != "SUCCEEDED":
                        raise MissionConflict("phase receipt skips an unconfirmed prior phase")
                latest[ordinal] = {"detail": detail}
            updated = connection.execute(
                "SELECT * FROM fleet_missions WHERE mission_id=?", (mission_id,),
            ).fetchone()
            connection.commit()
        return self._row(updated)

    def reject(self, mission_id: str, *, actor_id: str, expected_generation: int,
               decision: str) -> dict[str, Any]:
        """D-763 5b: a PROPOSED Mission ends CANCELED with ``decision`` as reason; it held no claim."""
        actor_id = _nonempty("actor_id", actor_id, limit=96)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM fleet_missions WHERE mission_id=?",
                                     (mission_id,)).fetchone()
            control = connection.execute(
                "SELECT generation FROM fleet_dispatch_control WHERE control_id=1").fetchone()
            if (row is None or row["status"] != "PROPOSED" or control is None
                    or control[0] != expected_generation):
                raise MissionConflict("only a PROPOSED Mission at the current stop generation can be rejected")
            connection.execute("UPDATE fleet_missions SET status='CANCELED', reason=?, updated_at=? "
                               "WHERE mission_id=?", (decision, _now(), mission_id))
            self._event(connection, event_source="fleet_mission", source_event_id=f"reject:{mission_id}",
                        mission=row, event_type="MISSION_REJECTED", state="CANCELED", actor_id=actor_id,
                        detail={"decision": decision, "dispatch_generation": expected_generation})
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
            if (row["status"] not in {"ACTION_SUCCEEDED", "HOLD"}
                    or evidence.action_id != row["action_id"]
                    or evidence.attempt_id != row["attempt_id"]):
                raise MissionConflict("independent goal evidence requires terminal Action success")
            if not self._terminal_action_succeeded(connection, mission_id, row["action_id"], row["attempt_id"]):
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
