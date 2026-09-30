"""Internal single-step Mission lifecycle; no REST or model-dispatch binding."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from collections.abc import Mapping
from typing import Any, Callable

from .goal_evidence import GoalEvidence, GoalEvidenceError, GoalPredicate, verify_goal
from .mission_store import MissionStore

_GOAL_EVIDENCE_AUDIT_FIELDS = (
    "predicate_id", "object_id", "destination_id", "evidence_source", "evidence_id",
    "evidence_revision", "producer_id", "observation_id", "observation_digest",
    "evaluator_revision", "action_id", "attempt_id", "gripper_state",
    "gripper_evidence_id", "gripper_evidence_revision", "gripper_observed_at",
    "observed_at", "satisfied",
)


def _goal_evidence_audit_summary(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Retain a bounded digest and field list, never raw rejected producer data."""
    bounded: dict[str, Any] = {}
    present: list[str] = []
    for field in _GOAL_EVIDENCE_AUDIT_FIELDS:
        if field not in evidence:
            continue
        present.append(field)
        value = evidence[field]
        if isinstance(value, str):
            bounded[field] = {"length": len(value), "prefix": value[:128]}
        elif isinstance(value, bool):
            bounded[field] = value
        elif isinstance(value, int) and value.bit_length() <= 53:
            bounded[field] = value
        elif isinstance(value, int):
            bounded[field] = {"type": "int", "bits": value.bit_length()}
        elif isinstance(value, float) and math.isfinite(value):
            bounded[field] = value
        else:
            bounded[field] = {"type": type(value).__name__[:64]}
    try:
        unexpected_count = max(0, len(evidence) - len(present))
    except (TypeError, OverflowError):
        unexpected_count = 0
    canonical = json.dumps(
        bounded, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return {
        "sha256": hashlib.sha256(canonical).hexdigest(),
        "fields": present,
        "unexpected_field_count": unexpected_count,
    }


class MissionService:
    def __init__(self, store: MissionStore, *,
                 goal_evidence_verifier: Callable[[Mapping[str, Any], GoalEvidence], bool] | None = None) -> None:
        self.store = store
        self.goal_evidence_verifier = goal_evidence_verifier

    def propose(self, **request: Any) -> dict[str, Any]:
        """Store a candidate only; it does not reserve or submit physical work."""
        return self.store.create_proposal(**request)

    def get(self, mission_id: str) -> dict[str, Any] | None:
        return self.store.get_mission(mission_id)

    def history(self, mission_id: str) -> list[dict[str, Any]]:
        return self.store.history(mission_id)

    def next_ready(self) -> dict[str, Any] | None:
        return self.store.next_ready_mission()

    def next_running(self) -> dict[str, Any] | None:
        return self.store.next_running_mission()

    def next_reconciliation(self) -> dict[str, Any] | None:
        return self.store.next_reconciliation_mission()

    def finish_reconciliation(self, mission_id: str, *, action_id: str,
                              attempt_id: str) -> dict[str, Any]:
        return self.store.finish_reconciliation(
            mission_id, action_id=action_id, attempt_id=attempt_id,
        )

    def admit(self, mission_id: str, *, actor_id: str, expected_generation: int,
              resources: list[tuple[str, str]]) -> dict[str, Any]:
        return self.store.admit(mission_id, actor_id=actor_id,
                                expected_generation=expected_generation, resources=resources)

    def start_step(self, mission_id: str, *, action_id: str, attempt_id: str,
                   expected_authority_epoch: int,
                   expected_generation: int,
                   action_grant: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self.store.start_step(mission_id, action_id=action_id,
                                     attempt_id=attempt_id,
                                     expected_authority_epoch=expected_authority_epoch,
                                     expected_generation=expected_generation,
                                     action_grant=action_grant)

    def record_action_result(self, mission_id: str, *, event_id: str, action_id: str,
                             attempt_id: str, outcome: str,
                             result: Mapping[str, Any]) -> dict[str, Any]:
        return self.store.record_action_result(
            mission_id, event_id=event_id, action_id=action_id,
            attempt_id=attempt_id, outcome=outcome, result=result,
        )

    def confirm_goal(self, mission_id: str, *, event_id: str, evidence: Mapping[str, Any],
                     now: float, max_age_s: float, actor_id: str = "goal-evidence") -> dict[str, Any]:
        mission = self.store.get_mission(mission_id)
        if mission is None:
            raise KeyError(mission_id)
        try:
            predicate = GoalPredicate.from_mapping(mission["goal_predicate"])
            parsed = GoalEvidence.from_mapping(dict(evidence))
            satisfied = verify_goal(predicate, parsed, now=now, max_age_s=max_age_s)
            if (mission.get("action_id") != parsed.action_id
                    or mission.get("attempt_id") != parsed.attempt_id):
                raise GoalEvidenceError("goal evidence belongs to a different Action attempt")
            plan = mission.get("plan", {})
            if isinstance(plan, Mapping):
                original_observation = plan.get("observation_id")
                source = plan.get("source_evidence", {})
                original_digest = (source.get("frame_sha256")
                                   if isinstance(source, Mapping) else None)
                original_digest = original_digest or plan.get("image_sha256")
                if (parsed.observation_id == original_observation
                        or (isinstance(original_digest, str)
                            and parsed.observation_digest == original_digest)):
                    raise GoalEvidenceError("goal evidence must use a new post-action observation")
            terminal = next((event for event in reversed(self.store.history(mission_id))
                             if event["event_type"] == "ACTION_TERMINAL_RESULT"
                             and event["action_id"] == parsed.action_id
                             and event["attempt_id"] == parsed.attempt_id), None)
            if terminal is None:
                raise GoalEvidenceError("matching terminal Action evidence is unavailable")
            terminal_at = datetime.fromisoformat(terminal["created_at"]).astimezone(timezone.utc).timestamp()
            if (parsed.observed_at <= terminal_at
                    or parsed.gripper_observed_at <= terminal_at):
                raise GoalEvidenceError("goal and gripper evidence must be observed after Action completion")
            if self.goal_evidence_verifier is None:
                raise GoalEvidenceError("no trusted goal-evidence producer is configured")
            try:
                trusted = self.goal_evidence_verifier(mission, parsed)
            except Exception as exc:
                raise GoalEvidenceError("trusted goal-evidence verification failed") from exc
            if trusted is not True:
                raise GoalEvidenceError("goal-evidence producer is not authenticated or current")
        except GoalEvidenceError:
            self.store.hold_mission(
                mission_id, actor_id=actor_id, event_id=event_id,
                reason="GOAL_EVIDENCE_REJECTED",
                evidence=_goal_evidence_audit_summary(evidence),
            )
            raise
        if not satisfied:
            return self.store.hold_mission(
                mission_id, actor_id=actor_id, event_id=event_id,
                reason="GOAL_NOT_SATISFIED", evidence=parsed.to_dict(),
                event_type="GOAL_PREDICATE_UNSATISFIED",
            )
        return self.store.confirm_goal(mission_id, actor_id=actor_id,
                                       event_id=event_id, evidence=parsed)
