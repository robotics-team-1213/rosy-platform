"""Internal single-step Mission lifecycle; no REST or model-dispatch binding."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .goal_evidence import GoalEvidence, GoalEvidenceError, GoalPredicate, verify_goal
from .mission_store import MissionStore


class MissionService:
    def __init__(self, store: MissionStore) -> None:
        self.store = store

    def propose(self, **request: Any) -> dict[str, Any]:
        """Store a candidate only; it does not reserve or submit physical work."""
        return self.store.create_proposal(**request)

    def admit(self, mission_id: str, *, actor_id: str, expected_generation: int,
              resources: list[tuple[str, str]]) -> dict[str, Any]:
        return self.store.admit(mission_id, actor_id=actor_id,
                                expected_generation=expected_generation, resources=resources)

    def start_step(self, mission_id: str, *, action_id: str, attempt_id: str,
                   expected_generation: int) -> dict[str, Any]:
        return self.store.start_step(mission_id, action_id=action_id,
                                     attempt_id=attempt_id,
                                     expected_generation=expected_generation)

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
            verify_goal(predicate, parsed, now=now, max_age_s=max_age_s)
        except GoalEvidenceError as exc:
            self.store.hold_mission(
                mission_id, actor_id=actor_id, event_id=event_id,
                reason="GOAL_EVIDENCE_REJECTED", evidence=dict(evidence),
            )
            raise
        return self.store.confirm_goal(mission_id, actor_id=actor_id,
                                       event_id=event_id, evidence=parsed)
