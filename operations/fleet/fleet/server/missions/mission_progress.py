"""Conservative progress projection from Fleet's durable Mission journal."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from core_common.protocol.schemas import MissionModelContext
from rosy.execution.site.workflow import project_progress

from .mission_store import MissionStore


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
        return project_progress(data, now=self.now())

    def events(self, mission_id: str, *, after_event_id: int,
               limit: int) -> dict[str, Any] | None:
        return self.store.mission_events_after(
            mission_id, after_event_id=after_event_id,
            limit=limit,
        )

    def model_context(self, mission_id: str, *, principal_id: str,
                      workcell_id: str) -> dict[str, Any] | None:
        snapshot = self.snapshot(mission_id)
        return self.model_context_from_snapshot(
            snapshot, principal_id=principal_id, workcell_id=workcell_id,
        )

    @staticmethod
    def model_context_from_snapshot(snapshot: dict[str, Any] | None, *,
                                    principal_id: str,
                                    workcell_id: str) -> dict[str, Any] | None:
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
            mission_id=mission["mission_id"], workcell_id=workcell_id,
            snapshot_event_id=progress["snapshot_event_id"],
            mission_state=progress["mission"]["state"],
            step_state=progress["step"]["state"],
            action_state=progress["action"]["state"],
            action_reason=progress["action"]["reason"],
            goal_evidence_state=progress["goal_evidence"]["state"],
            goal_evidence_reason=progress["goal_evidence"]["reason"],
            stop_state=progress["stop"]["state"],
            stop_reason=progress["stop"]["reason"],
            active_phase=progress.get("active_phase"),
            phases=tuple(progress.get("phases", ())),
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
