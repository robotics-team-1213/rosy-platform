"""Authenticate, scope, persist, and apply independent goal evidence."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from .goal_evidence import GoalEvidence, GoalEvidenceError, GoalPredicate, verify_goal
from .goal_evidence_registry import GoalEvidenceProducer, GoalEvidenceRegistry
from .goal_evidence_store import GoalEvidenceConflict, GoalEvidenceStore
from .mission_service import MissionService


class GoalEvidenceSubmissionError(ValueError):
    """Stable boundary error safe to expose to a producer client."""

    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class GoalEvidenceService:
    """Connect source credentials to Mission's independent goal verifier."""

    def __init__(self, missions: MissionService, registry: GoalEvidenceRegistry,
                 store: GoalEvidenceStore, *, now: Callable[[], float] | None = None) -> None:
        self.missions = missions
        self.registry = registry
        self.store = store
        self.now = now or time.time
        # Supplying this service is the explicit trusted verifier composition.
        self.missions.goal_evidence_verifier = self._verify_registered_evidence

    def _producer_for_evidence(self, mission: Mapping[str, Any],
                               evidence: GoalEvidence, *, now: float
                               ) -> GoalEvidenceProducer | None:
        goal = GoalPredicate.from_mapping(mission["goal_predicate"])
        producer = self.registry.producer_for_scope(
            producer_id=evidence.producer_id, workcell_id=mission["workcell_id"],
            predicate_id=goal.predicate_id, now=now,
        )
        if producer is None:
            return None
        if (producer.object_id != goal.object_id
                or producer.destination_id != goal.destination_id
                or producer.evidence_source != goal.evidence_source
                or evidence.evaluator_revision not in producer.evaluator_revisions):
            return None
        return producer

    def _verify_registered_evidence(self, mission: Mapping[str, Any],
                                    evidence: GoalEvidence) -> bool:
        producer = self._producer_for_evidence(mission, evidence, now=self.now())
        return producer is not None

    def on_action_terminal(self, mission_id: str) -> dict[str, Any] | None:
        """Verify evidence that arrived before terminal action readback."""
        mission = self.missions.get(mission_id)
        if mission is None or mission.get("status") != "ACTION_SUCCEEDED":
            return None
        action_id, attempt_id = mission.get("action_id"), mission.get("attempt_id")
        if not isinstance(action_id, str) or not isinstance(attempt_id, str):
            return None
        stored = self.store.latest_for_attempt(
            mission_id=mission_id, action_id=action_id, attempt_id=attempt_id,
        )
        if stored is None:
            return None
        raw_evidence = stored["evidence"]
        evidence = GoalEvidence.from_mapping(raw_evidence)
        producer = self._producer_for_evidence(mission, evidence, now=self.now())
        if producer is None:
            return None
        return self.missions.confirm_goal(
            mission_id, event_id="goal-evidence:" + evidence.evidence_id,
            evidence=evidence.to_dict(), now=self.now(),
            max_age_s=producer.max_age_s, actor_id=producer.producer_id,
        )

    def hold_expired_without_evidence(self) -> int:
        """Move missing-evidence Missions to HOLD after their registered grace window."""
        now = self.now()
        held = 0
        for mission in self.missions.store.missions_awaiting_goal_evidence():
            producer = self.registry.producer_for_goal(
                workcell_id=mission["workcell_id"],
                predicate_id=mission["goal_predicate"]["predicate_id"], now=now,
            )
            if producer is None:
                continue
            try:
                terminal_at = datetime.fromisoformat(
                    mission["action_terminal_at"].replace("Z", "+00:00")
                ).astimezone(timezone.utc).timestamp()
            except (AttributeError, TypeError, ValueError):
                continue
            if now < terminal_at + producer.grace_s:
                continue
            evidence = self.store.latest_for_attempt(
                mission_id=mission["mission_id"], action_id=mission["action_id"],
                attempt_id=mission["attempt_id"],
            )
            if evidence is not None:
                continue
            identity = (f"goal-evidence-timeout:{mission['mission_id']}:"
                        f"{mission['action_id']}:{mission['attempt_id']}")
            try:
                self.missions.store.hold_mission(
                    mission["mission_id"], actor_id="goal-evidence-verifier",
                    event_id=identity, reason="GOAL_EVIDENCE_TIMEOUT",
                    evidence={"evidence_id": None, "grace_s": producer.grace_s},
                )
            except ValueError:
                continue
            held += 1
        return held

    def submit(self, *, token: str, mission_id: str,
               raw_evidence: Mapping[str, Any]) -> dict[str, Any]:
        now = self.now()
        producer = self.registry.source_for_token(token, now=now)
        if producer is None:
            raise GoalEvidenceSubmissionError(
                "PRODUCER_UNAUTHORIZED", "producer credential is invalid or expired",
                status_code=401,
            )
        mission = self.missions.get(mission_id)
        if mission is None:
            raise GoalEvidenceSubmissionError("MISSION_NOT_FOUND", "Mission was not found",
                                              status_code=404)
        try:
            evidence = GoalEvidence.from_mapping(dict(raw_evidence))
            predicate = GoalPredicate.from_mapping(mission["goal_predicate"])
            registered = self._producer_for_evidence(mission, evidence, now=now)
            if registered is None or registered.producer_id != producer.producer_id:
                raise GoalEvidenceSubmissionError(
                    "PRODUCER_SCOPE_MISMATCH", "producer is not registered for this goal",
                )
            if (evidence.predicate_id != predicate.predicate_id
                    or evidence.object_id != predicate.object_id
                    or evidence.destination_id != predicate.destination_id
                    or evidence.action_id != mission.get("action_id")
                    or evidence.attempt_id != mission.get("attempt_id")):
                raise GoalEvidenceSubmissionError(
                    "EVIDENCE_SCOPE_MISMATCH", "evidence does not match the active Mission attempt",
                )
            verify_goal(predicate, evidence, now=now, max_age_s=producer.max_age_s)
        except GoalEvidenceSubmissionError:
            raise
        except (GoalEvidenceError, KeyError, TypeError, ValueError) as exc:
            raise GoalEvidenceSubmissionError("GOAL_EVIDENCE_INVALID", str(exc)) from exc

        try:
            stored = self.store.submit(
                evidence.to_dict(), received_at=now, mission_id=mission_id,
            )
        except GoalEvidenceConflict as exc:
            raise GoalEvidenceSubmissionError(
                "EVIDENCE_ID_CONFLICT", str(exc), status_code=409,
            ) from exc
        except ValueError as exc:
            raise GoalEvidenceSubmissionError("GOAL_EVIDENCE_INVALID", str(exc)) from exc

        current = self.missions.get(mission_id)
        if current is not None and current["status"] == "ACTION_SUCCEEDED":
            try:
                result = self.on_action_terminal(mission_id)
            except (GoalEvidenceError, ValueError) as exc:
                raise GoalEvidenceSubmissionError("GOAL_EVIDENCE_REJECTED", str(exc)) from exc
            state = result["status"] if result is not None else current["status"]
        else:
            state = "PENDING_ACTION_TERMINAL"
        return {
            "accepted": True, "created": stored["created"],
            "evidence_id": evidence.evidence_id, "mission_id": mission_id,
            "state": state,
        }
