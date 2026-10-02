"""Fleet judges per-step item_at_pose evidence and advances the step ledger (D-403 §5).

The producer authenticates with its own goal-evidence token (registry scope, never the body),
reports a sim_model_pose and the gripper release readback, and Fleet decides satisfaction from
the step's predicate and configured tolerances. Only a satisfied verdict confirms the step; an
unsatisfied one leaves it ACTION_SUCCEEDED for the operator (D-328 §4).
"""

from __future__ import annotations

import time
from typing import Any, Callable, Mapping

from rosy.execution.site.item_pose import (
    ItemPoseEvidence, ItemPoseTolerance, item_pose_predicate, verify_item_at_pose,
)

from .cell_job_store import CellJobStore
from .goal_evidence_registry import GoalEvidenceRegistry


class CellStepGoalEvidence:
    def __init__(self, store: CellJobStore, registry: GoalEvidenceRegistry,
                 tolerance: ItemPoseTolerance, *, now: Callable[[], float] = time.time) -> None:
        if not isinstance(tolerance, ItemPoseTolerance):
            raise ValueError("configured item pose tolerances are required")
        self.store, self.registry, self.tolerance, self.now = store, registry, tolerance, now

    def submit(self, token: str, document: Mapping[str, Any]) -> dict[str, Any]:
        now = self.now()
        producer = self.registry.source_for_token(token, now=now)
        if producer is None or producer.evidence_source != "sim_model_pose":
            raise PermissionError("goal evidence producer is not authorized for sim_model_pose")
        evidence = ItemPoseEvidence.from_mapping(document)
        if evidence.producer_id != producer.producer_id:
            raise PermissionError("evidence names another producer")
        mission_id, _, raw_index = evidence.item_id.rpartition(":")
        if not raw_index.isdigit():
            raise ValueError("item_id must be <mission_id>:<step_index>")
        step_index = int(raw_index)
        job = self.store.get(mission_id)
        if job is None or step_index >= len(job["steps"]):
            raise KeyError(evidence.item_id)
        if job["workcell_id"] != producer.workcell_id:
            raise PermissionError("producer is scoped to another workcell")
        step = job["steps"][step_index]
        if (evidence.action_id, evidence.attempt_id) != (step["action_id"], step["attempt_id"]):
            raise PermissionError("evidence does not cite this step's Action attempt")
        predicate = item_pose_predicate(mission_id, step_index, step["step"]["inputs"], self.tolerance)
        verdict = verify_item_at_pose(predicate, evidence, now=now, max_age_s=producer.max_age_s)
        if not verdict.satisfied:
            return {"mission_id": mission_id, "step_index": step_index, "satisfied": False,
                    "reasons": list(verdict.reasons), "errors": dict(verdict.errors)}
        confirmed = self.store.confirm_step_goal(
            mission_id, step_index=step_index, action_id=evidence.action_id,
            attempt_id=evidence.attempt_id, evidence={
                "producer_id": producer.producer_id, "evidence_id": evidence.evidence_id,
                "evidence_source": "sim_model_pose", "action_id": evidence.action_id,
                "attempt_id": evidence.attempt_id, "satisfied": True,
                "gripper_state": evidence.gripper_state,
                "gripper_evidence_id": evidence.gripper_evidence_id,
                "model_name": evidence.model_name, "pose": dict(evidence.pose),
                "observed_at": evidence.observed_at, "predicate": predicate.to_dict(),
                "errors": dict(verdict.errors),
            },
        )
        return {"mission_id": mission_id, "step_index": step_index, "satisfied": True,
                "status": confirmed["status"]}


__all__ = ["CellStepGoalEvidence"]
