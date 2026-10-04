"""Authenticate, persist and judge independent Cell observations before goal completion.

Ported from main (778f50294, 3ef12ca3e) onto the C4b step ledger: a producer registered for one
simulation cell, recipe and evaluator revision reports a ``sim_model_pose`` observation of one
attempt. The observation is bound to the persisted grant and must follow the durable device
success; Fleet then judges it against the step's stored ``item_at_pose`` predicate. Producers
cannot assert satisfaction (the wire model has no ``satisfied`` field). Evidence that arrives
before the terminal success is stored and applied when the dispatcher records that success.
"""

from __future__ import annotations

from datetime import datetime
import math
import time

from pydantic import ValidationError

from core_common.protocol.cell_goal_evidence import CellGoalEvidence
from rosy.execution.site.item_pose import ItemPoseEvidence, item_pose_predicate, verify_item_at_pose

from .goal_evidence_service import GoalEvidenceSubmissionError
from .goal_evidence_store import GoalEvidenceConflict
from .mission_store import MissionConflict


class CellGoalEvidenceService:
    def __init__(self, jobs, registry, store, *, now=None):
        if jobs.path.resolve() != store.path.resolve():
            raise ValueError("Cell goals and Jobs must share the persistent journal database")
        self.jobs, self.registry, self.store = jobs, registry, store
        self.now = now or time.time

    def _validate(self, producer, job, raw, now):
        try:
            evidence = CellGoalEvidence.model_validate(raw)
        except ValidationError as exc:
            raise GoalEvidenceSubmissionError("CELL_GOAL_EVIDENCE_INVALID", str(exc)) from exc
        index = evidence.step_index
        if index >= len(job["steps"]):
            raise GoalEvidenceSubmissionError("EVIDENCE_SCOPE_MISMATCH", "Cell step does not exist")
        step = job["steps"][index]
        grant = step["grant"]
        if grant is None:
            raise GoalEvidenceSubmissionError("EVIDENCE_SCOPE_MISMATCH", "Cell step has no submitted grant")
        if (producer.producer_id != evidence.producer_id or producer.workcell_id != job["workcell_id"]
                or producer.instance_id != job["instance_id"] or producer.recipe_sha256 != job["recipe_digest"]
                or producer.cell_sha256 != job["cell_digest"]
                or evidence.evaluator_revision not in producer.evaluator_revisions):
            raise GoalEvidenceSubmissionError("PRODUCER_SCOPE_MISMATCH", "producer is not registered for this Cell")
        if (evidence.job_id != job["job_id"] or evidence.step_id != step["step_id"]
                or evidence.recipe_sha256 != job["recipe_digest"] or evidence.cell_sha256 != job["cell_digest"]
                or evidence.action_id != step["action_id"] or evidence.attempt_id != step["attempt_id"]
                or evidence.request_digest != step["request_digest"] or evidence.model_id != "cell_" + step["action_id"]
                or (index != job["current_step_index"] and step["status"] != "GOAL_CONFIRMED")):
            raise GoalEvidenceSubmissionError("EVIDENCE_SCOPE_MISMATCH", "evidence does not match the Cell attempt")
        issued = datetime.fromisoformat(grant["issued_at"].replace("Z", "+00:00")).timestamp()
        if (not math.isfinite(now) or evidence.initial_observed_at < issued
                or evidence.initial_observed_at > evidence.observed_at
                or any(not 0 <= now - observed <= producer.max_age_s
                       for observed in (evidence.observed_at, evidence.gripper_observed_at))):
            raise GoalEvidenceSubmissionError("CELL_GOAL_EVIDENCE_INVALID",
                                              "Cell observations are stale or out of order")
        if step["step"].get("goal_predicate") is None:
            raise GoalEvidenceSubmissionError("CELL_GOAL_PREDICATE_MISSING",
                                              "the step has no stored item_at_pose predicate")
        return evidence, step

    @staticmethod
    def _terminal_proof(job, step, evidence):
        """The latest device outcome of the step must be this attempt's durable success, and the
        observations must follow it (64b4b1faa). Returns None while no terminal success exists."""
        terminal = next((event for event in reversed(job["events"])
                         if event["step_index"] == step["step_index"]
                         and event["event_type"].startswith("CELL_STEP_ACTION_")), None)
        if (terminal is None or terminal["event_type"] != "CELL_STEP_ACTION_SUCCEEDED"
                or terminal["detail"]["action_id"] != step["action_id"]
                or terminal["detail"]["attempt_id"] != step["attempt_id"]):
            return None
        try:
            terminal_at = datetime.fromisoformat(terminal["detail"]["result"]["observed_at"].replace(
                "Z", "+00:00")).timestamp()
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise GoalEvidenceSubmissionError("CELL_GOAL_EVIDENCE_INVALID",
                                              "local terminal timestamp is missing") from exc
        if (evidence.observed_at < terminal_at or evidence.gripper_observed_at < terminal_at
                or evidence.initial_observed_at > terminal_at):
            raise GoalEvidenceSubmissionError("CELL_GOAL_EVIDENCE_INVALID",
                                              "Cell goal must be observed after terminal success")
        return terminal["event_id"]

    def _judge(self, job, step, evidence, producer, now):
        pose = evidence.model_pose_base
        item_id = f"{job['mission_id']}:{step['step_index']}"
        observed = ItemPoseEvidence.from_mapping({
            "predicate_id": f"{item_id}:item_at_pose", "item_id": item_id,
            "evidence_source": "sim_model_pose", "evidence_id": evidence.evidence_id,
            "producer_id": evidence.producer_id, "model_name": evidence.model_id, "frame": "robot_base",
            "pose": {"x": pose.x_m, "y": pose.y_m, "z": pose.z_m,
                     "roll": pose.roll_rad, "pitch": pose.pitch_rad, "yaw": pose.yaw_rad},
            "observed_at": evidence.observed_at, "action_id": evidence.action_id,
            "attempt_id": evidence.attempt_id, "gripper_state": evidence.gripper_state,
            "gripper_evidence_id": evidence.gripper_evidence_id,
        })
        predicate = item_pose_predicate(job["mission_id"], step["step_index"], step["step"]["goal_predicate"])
        return predicate, verify_item_at_pose(predicate, observed, now=now, max_age_s=producer.max_age_s)

    def on_action_terminal(self, mission_id):
        """Apply stored evidence once the step's durable success is recorded (dispatcher hook)."""
        job = self.jobs.get(mission_id)
        if job is None or job["status"] != "ACTION_SUCCEEDED":
            return None
        step = job["steps"][job["current_step_index"]]
        stored = self.store.latest_for_attempt(mission_id=mission_id, action_id=step["action_id"],
                                               attempt_id=step["attempt_id"])
        if stored is None:
            return None
        now = self.now()
        producer = next((item for item in self.registry.producers
                         if item.producer_id == stored["producer_id"] and now < item.valid_until.timestamp()), None)
        if producer is None:
            return None
        evidence, step = self._validate(producer, job, stored["evidence"], now)
        if self._terminal_proof(job, step, evidence) is None:
            return None
        predicate, verdict = self._judge(job, step, evidence, producer, now)
        if not verdict.satisfied:
            raise GoalEvidenceSubmissionError("CELL_GOAL_NOT_AT_POSE",
                                              "Cell placement is not at the step pose: " + ",".join(verdict.reasons))
        return self.jobs.confirm_step_goal(
            mission_id, step_index=step["step_index"], action_id=step["action_id"],
            attempt_id=step["attempt_id"], evidence={
                **evidence.model_dump(mode="json"), "satisfied": True,
                "gripper_state_source": "producer_asserted", "predicate": predicate.to_dict(),
                "errors": dict(verdict.errors)})

    def submit(self, *, token, mission_id, raw_evidence):
        now = self.now()
        producer = self.registry.source_for_token(token, now=now)
        if producer is None:
            raise GoalEvidenceSubmissionError("PRODUCER_UNAUTHORIZED", "producer credential is invalid or expired",
                                              status_code=401)
        job = self.jobs.get(mission_id)
        if job is None:
            raise GoalEvidenceSubmissionError("MISSION_NOT_FOUND", "Cell Job was not found", status_code=404)
        evidence, step = self._validate(producer, job, raw_evidence, now)
        if self._terminal_proof(job, step, evidence) is not None and step["status"] != "GOAL_CONFIRMED":
            predicate, verdict = self._judge(job, step, evidence, producer, now)
            if not verdict.satisfied:  # rejected before storage, so a corrected same id can follow
                raise GoalEvidenceSubmissionError(
                    "CELL_GOAL_NOT_AT_POSE", "Cell placement is not at the step pose: " + ",".join(verdict.reasons))
        try:
            stored = self.store.submit(evidence.model_dump(mode="json"), received_at=now, mission_id=mission_id)
            result = self.on_action_terminal(mission_id) if step["status"] != "GOAL_CONFIRMED" else job
        except (GoalEvidenceConflict, MissionConflict) as exc:
            raise GoalEvidenceSubmissionError("EVIDENCE_ID_CONFLICT", str(exc)) from exc
        return {"accepted": True, "created": stored["created"], "evidence_id": evidence.evidence_id,
                "mission_id": mission_id,
                "state": result["status"] if result is not None else "PENDING_ACTION_TERMINAL"}


__all__ = ["CellGoalEvidenceService"]
