"""Narrow event-to-outbox trigger policy for ER 2 feedback turns."""

from __future__ import annotations

from typing import Any

from core_common.protocol.schemas import MissionFeedbackTurnScope

from .mission_model_turn_store import MissionModelTurnStore

_TRIGGER_EVENTS = {
    "ACTION_TERMINAL_RESULT", "GOAL_PREDICATE_CONFIRMED",
    "GOAL_EVIDENCE_REJECTED", "GOAL_PREDICATE_UNSATISFIED",
}


class MissionModelTurnScheduler:
    """Create one scoped outbox row only for fresh durable Mission evidence."""

    def __init__(self, *, mission_service: Any, progress_service: Any,
                 turn_store: MissionModelTurnStore, policy_revision: str) -> None:
        if (not isinstance(policy_revision, str) or not policy_revision.strip()
                or policy_revision != policy_revision.strip() or len(policy_revision) > 96):
            raise ValueError("model policy revision must be a bounded stable identifier")
        self.mission_service = mission_service
        self.progress_service = progress_service
        self.turn_store = turn_store
        self.policy_revision = policy_revision

    def consider(self, mission_id: str, *, trigger_event_id: int) -> dict[str, Any] | None:
        if type(trigger_event_id) is not int or trigger_event_id < 1:
            raise ValueError("trigger_event_id must be a positive integer")
        mission = self.mission_service.get(mission_id)
        page = self.progress_service.events(
            mission_id, after_event_id=trigger_event_id - 1, limit=1,
        )
        snapshot = self.progress_service.snapshot(mission_id)
        if mission is None or page is None or snapshot is None:
            return None
        trigger = next((event for event in page["events"]
                        if event["event_id"] == trigger_event_id), None)
        if trigger is None or trigger["event_type"] not in _TRIGGER_EVENTS:
            return None
        if (trigger.get("action_id") != mission.get("action_id")
                or trigger.get("attempt_id") != mission.get("attempt_id")
                or not mission.get("action_id") or not mission.get("attempt_id")):
            return None

        progress = snapshot["progress"]
        scope = MissionFeedbackTurnScope.model_validate({
            "principal_id": mission["principal_id"],
            "workcell_id": mission["workcell_id"],
            "mission_id": mission_id, "action_id": mission["action_id"],
            "attempt_id": mission["attempt_id"],
            "dispatch_generation": mission["dispatch_generation"],
            "event_watermark": progress["snapshot_event_id"],
            "model_policy_revision": self.policy_revision,
            # The goal evidence contract exists, but no fresh authorized
            # post-action observation source is wired to this worker yet.
            # Therefore all turns remain status-only.
            "outcome_policy": "STATUS_ONLY",
        })
        inserted = self.turn_store.enqueue(scope=scope, trigger_event_id=trigger_event_id)
        turn = inserted["turn"]
        if turn is None:
            return {"turn": None, "created": False,
                    "reason_code": inserted.get("reason_code", "OUTBOX_REJECTED")}
        action = progress["action"]
        stop = progress["stop"]
        if stop["state"] != "DISPATCH_ENABLED":
            turn = self.turn_store.suppress(turn["turn_id"],
                                            reason_code="STOP_FENCE_CLOSED") or turn
        else:
            try:
                _epoch, generation = stop["revision"].split("/")
                stop_generation = int(generation.removeprefix("generation:"))
            except (AttributeError, TypeError, ValueError):
                stop_generation = -1
            if stop_generation != scope.dispatch_generation:
                turn = self.turn_store.suppress(
                    turn["turn_id"], reason_code="STOP_GENERATION_CHANGED",
                ) or turn
        if (turn["state"] == "PENDING"
                and (action["state"] in {"UNKNOWN", "RUNNING", "HOLD"}
                     or action["freshness"] != "FRESH")):
            turn = self.turn_store.suppress(turn["turn_id"],
                                            reason_code="ACTION_READBACK_UNSAFE") or turn
        return {"turn": turn, "created": inserted["created"]}

    def poll_once(self, *, limit: int = 100) -> int:
        """Durably scan a bounded global event page and enqueue eligible turns.

        A crash before cursor advancement replays the page; the outbox uniqueness
        key makes that replay idempotent. No provider call is made here.
        """
        cursor = self.turn_store.get_event_cursor()
        events = self.mission_service.store.feedback_events_after(
            after_event_id=cursor, limit=limit,
        )
        if not events:
            return 0
        for event in events:
            if event["event_type"] in _TRIGGER_EVENTS:
                self.consider(event["mission_id"], trigger_event_id=event["event_id"])
        self.turn_store.advance_event_cursor(events[-1]["event_id"])
        return len(events)


__all__ = ["MissionModelTurnScheduler"]
