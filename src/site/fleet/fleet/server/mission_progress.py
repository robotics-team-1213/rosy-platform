"""Conservative progress projection from Fleet's durable Mission journal."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Callable

from core_common.protocol.schemas import (
    MissionModelContext,
    MissionProgressAxis,
    MissionProgressSnapshot,
)

from .mission_store import MissionStore

ACTION_FRESHNESS_SECONDS = 15.0
GOAL_FRESHNESS_SECONDS = 2.0


def _timestamp(value: object) -> datetime | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            finite = math.isfinite(value)
        except OverflowError:
            return None
        if not finite:
            return None
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _freshness(observed_at: datetime | None, *, now: datetime,
               max_age_s: float) -> str:
    if observed_at is None:
        return "UNKNOWN"
    age = (now - observed_at).total_seconds()
    return "FRESH" if 0 <= age <= max_age_s else "STALE"


class MissionProgressService:
    """Build snapshots and cursor pages without inferring physical completion."""

    def __init__(self, store: MissionStore, *,
                 now: Callable[[], datetime] | None = None) -> None:
        self.store = store
        self.now = now or (lambda: datetime.now(timezone.utc))

    def snapshot(self, mission_id: str) -> dict[str, Any] | None:
        data = self.store.progress_snapshot_data(mission_id)
        if data is None:
            return None
        now = self.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Mission progress clock must be timezone-aware")
        mission = data["mission"]
        events = data["progress_events"]
        watermark = data["snapshot_event_id"]

        mission_axis = MissionProgressAxis(
            state=mission["status"], source="fleet_missions",
            last_event_id=watermark,
            observed_at=_timestamp(mission["updated_at"]),
            revision=mission["updated_at"], freshness="CURRENT",
            reason=mission["reason"],
        )
        step_state = {
            "PROPOSED": "NOT_ADMITTED", "READY": "READY",
            "RUNNING": "RUNNING",
            "ACTION_SUCCEEDED": "AWAITING_GOAL_EVIDENCE",
            "GOAL_CONFIRMED": "COMPLETED", "HOLD": "HOLD",
            "CANCELED": "CANCELED",
        }.get(mission["status"], "UNKNOWN")
        step_axis = MissionProgressAxis(
            state=step_state, source="fleet_missions", last_event_id=watermark,
            observed_at=_timestamp(mission["updated_at"]),
            revision=(str(mission["dispatch_generation"])
                      if isinstance(mission.get("dispatch_generation"), int)
                      and not isinstance(mission.get("dispatch_generation"), bool)
                      else "unassigned"),
            freshness="CURRENT", reason=mission["reason"],
        )

        attempt_events = [
            event for event in events
            if event["action_id"] == mission.get("action_id")
            and event["attempt_id"] == mission.get("attempt_id")
            and event["event_type"] in {
                "STEP_SUBMITTED", "ACTION_TERMINAL_RESULT",
            }
        ]
        action_event = attempt_events[-1] if attempt_events else None
        action_observed = None
        action_reason = "ACTION_NOT_SUBMITTED"
        if action_event is None:
            action_axis = MissionProgressAxis(
                state="UNKNOWN", source="none", last_event_id=None, observed_at=None,
                revision=None, freshness="UNKNOWN", reason=action_reason,
            )
        else:
            result = action_event["detail"].get("result", {})
            action_observed = _timestamp(result.get("observed_at"))
            action_reason = result.get("reason")
            is_submission = action_event["event_type"] == "STEP_SUBMITTED"
            action_state = (
                "RUNNING" if is_submission else action_event["state"]
            )
            action_axis = MissionProgressAxis(
                state=action_state, source="fleet_mission_events",
                last_event_id=action_event["event_id"], observed_at=action_observed,
                revision=mission.get("attempt_id"),
                freshness=("UNKNOWN" if is_submission or action_observed is None else
                           _freshness(action_observed, now=now,
                                      max_age_s=ACTION_FRESHNESS_SECONDS)),
                reason=(action_reason or
                        ("LOCAL_ACTION_READBACK_PENDING" if is_submission else None)),
            )

        goal_events = [
            event for event in events
            if event["action_id"] == mission.get("action_id")
            and event["attempt_id"] == mission.get("attempt_id")
            and event["event_type"] in {
                "GOAL_PREDICATE_CONFIRMED", "GOAL_EVIDENCE_REJECTED",
                "GOAL_PREDICATE_UNSATISFIED",
            }
        ]
        goal_event = goal_events[-1] if goal_events else None
        if goal_event is None:
            goal_state = "PENDING" if mission["status"] == "ACTION_SUCCEEDED" else "UNKNOWN"
            goal_axis = MissionProgressAxis(
                state=goal_state, source="none", last_event_id=None, observed_at=None,
                revision=None, freshness="UNKNOWN",
                reason=("GOAL_EVIDENCE_NOT_RECORDED"
                        if goal_state == "PENDING" else None),
            )
        else:
            goal_detail = goal_event["detail"]
            evidence = goal_detail.get("evidence", goal_detail)
            observed = _timestamp(evidence.get("observed_at"))
            goal_state = {
                "GOAL_PREDICATE_CONFIRMED": "CONFIRMED",
                "GOAL_PREDICATE_UNSATISFIED": "UNSATISFIED",
                "GOAL_EVIDENCE_REJECTED": "REJECTED",
            }[goal_event["event_type"]]
            goal_axis = MissionProgressAxis(
                state=goal_state, source="fleet_mission_events",
                last_event_id=goal_event["event_id"], observed_at=observed,
                revision=evidence.get("evaluator_revision"),
                freshness=_freshness(
                    observed, now=now, max_age_s=GOAL_FRESHNESS_SECONDS,
                ),
                reason=goal_detail.get("reason"),
            )

        control = data["stop_control"]
        if control is None:
            stop_axis = MissionProgressAxis(
                state="UNKNOWN", source="none", last_event_id=None,
                observed_at=None, revision=None, freshness="UNKNOWN",
                reason="FLEET_STOP_CONTROL_UNAVAILABLE", physical_state="UNKNOWN",
            )
        else:
            enabled = bool(control["dispatch_enabled"])
            stop_axis = MissionProgressAxis(
                state="DISPATCH_ENABLED" if enabled else "DISPATCH_BLOCKED",
                source="fleet_dispatch_control", last_event_id=None,
                observed_at=_timestamp(control["updated_at"]),
                revision=(f"epoch:{control['authority_epoch']}/"
                          f"generation:{control['generation']}"),
                freshness="CURRENT", reason=control["reason"],
                physical_state="UNKNOWN",
            )

        progress = MissionProgressSnapshot(
            snapshot_event_id=watermark,
            snapshot_at=now,
            mission=mission_axis, step=step_axis, action=action_axis,
            goal_evidence=goal_axis, stop=stop_axis,
        ).model_dump(mode="json")
        return {
            "mission": mission,
            "history": data["history"],
            "history_truncated": data["history_truncated"],
            "progress": progress,
        }

    def events(self, mission_id: str, *, after_event_id: int,
               limit: int) -> dict[str, Any] | None:
        return self.store.mission_events_after(
            mission_id, after_event_id=after_event_id,
            limit=limit,
        )

    def model_context(self, mission_id: str, *, principal_id: str,
                      workcell_id: str) -> dict[str, Any] | None:
        snapshot = self.snapshot(mission_id)
        if snapshot is None:
            return None
        mission = snapshot["mission"]
        if (mission["principal_id"] != principal_id
                or mission["workcell_id"] != workcell_id):
            return None
        progress = snapshot["progress"]
        stop_revision = progress["stop"].get("revision")
        try:
            epoch_text, generation_text = stop_revision.split("/")
            authority_epoch = int(epoch_text.removeprefix("epoch:"))
            stop_generation = int(generation_text.removeprefix("generation:"))
        except (AttributeError, TypeError, ValueError):
            return None
        context = MissionModelContext(
            mission_id=mission_id, workcell_id=workcell_id,
            snapshot_event_id=progress["snapshot_event_id"],
            mission_state=progress["mission"]["state"],
            step_state=progress["step"]["state"],
            action_state=progress["action"]["state"],
            action_reason=progress["action"]["reason"],
            goal_evidence_state=progress["goal_evidence"]["state"],
            goal_evidence_reason=progress["goal_evidence"]["reason"],
            stop_state=progress["stop"]["state"],
            stop_reason=progress["stop"]["reason"],
        )
        return {
            **context.model_dump(mode="json"),
            "authority_epoch": authority_epoch,
            "stop_generation": stop_generation,
            "snapshot_at": progress["snapshot_at"],
            "mission_source": progress["mission"]["source"],
            "step_source": progress["step"]["source"],
            "action_source": progress["action"]["source"],
            "action_freshness": progress["action"]["freshness"],
            "action_observed_at": progress["action"]["observed_at"],
            "goal_evidence_source": progress["goal_evidence"]["source"],
            "goal_evidence_freshness": progress["goal_evidence"]["freshness"],
            "goal_evidence_observed_at": progress["goal_evidence"]["observed_at"],
            "stop_source": progress["stop"]["source"],
            "stop_freshness": progress["stop"]["freshness"],
            "stop_observed_at": progress["stop"]["observed_at"],
        }
