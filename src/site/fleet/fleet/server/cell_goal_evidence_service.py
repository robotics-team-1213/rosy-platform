"""Authenticate and persist independent Cell observations before goal completion."""

from datetime import datetime
import math
import time

from pydantic import ValidationError

from core_common.protocol.cell_goal_evidence import CellGoalEvidence
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
        if evidence.satisfied is not True:
            raise GoalEvidenceSubmissionError("CELL_GOAL_EVIDENCE_INVALID", "Cell placement is not satisfied")
        issued = datetime.fromisoformat(grant["issued_at"].replace("Z", "+00:00")).timestamp()
        if (not math.isfinite(now) or evidence.initial_observed_at < issued
                or evidence.initial_observed_at > evidence.observed_at
                or any(not 0 <= now - observed <= producer.max_age_s
                       for observed in (evidence.observed_at, evidence.gripper_observed_at))):
            raise GoalEvidenceSubmissionError("CELL_GOAL_EVIDENCE_INVALID",
                                              "Cell observations are stale or out of order")
        if step["status"] == "GOAL_CONFIRMED" and step["goal_evidence"] != evidence.model_dump(mode="json"):
            raise GoalEvidenceSubmissionError("EVIDENCE_ID_CONFLICT", "confirmed Cell goal cannot be rewritten")
        return evidence, step

    def _terminal_proof(self, job, step, evidence):
        terminal = next((event for event in reversed(job["events"])
                         if event["step_index"] == step["step_index"] and event["event_type"] in {
                             "CELL_STEP_ACTION_SUCCEEDED", "CELL_STEP_ACTION_UNKNOWN"}), None)
        if terminal is None or terminal["detail"]["outcome"] != "SUCCEEDED":
            return None
        try:
            terminal_at = datetime.fromisoformat(terminal["detail"]["result"]["observed_at"].replace(
                "Z", "+00:00")).timestamp()
        except (KeyError, TypeError, ValueError) as exc:
            raise GoalEvidenceSubmissionError("CELL_GOAL_EVIDENCE_INVALID",
                                              "local terminal timestamp is missing") from exc
        if (evidence.observed_at < terminal_at or evidence.gripper_observed_at < terminal_at
                or evidence.initial_observed_at > terminal_at):
            raise GoalEvidenceSubmissionError("CELL_GOAL_EVIDENCE_INVALID",
                                              "Cell goal must be observed after terminal success")
        return terminal["event_id"]

    def on_action_terminal(self, mission_id):
        job = self.jobs.get(mission_id)
        if job is None or job["status"] not in {"ACTION_SUCCEEDED", "HOLD"}:
            return None
        step = job["steps"][job["current_step_index"]]
        if not self.jobs.terminal_step_succeeded(mission_id, step_index=step["step_index"],
                                                 action_id=step["action_id"], attempt_id=step["attempt_id"]):
            return None
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
        terminal_id = self._terminal_proof(job, step, evidence)
        if terminal_id is None:
            return None
        return self.jobs.confirm_step_goal(mission_id, step_index=step["step_index"], action_id=step["action_id"],
                                           attempt_id=step["attempt_id"], evidence=evidence.model_dump(mode="json"),
                                           expected_terminal_event_id=terminal_id)

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
        self._terminal_proof(job, step, evidence)
        try:
            stored = self.store.submit(evidence.model_dump(mode="json"), received_at=now, mission_id=mission_id)
            result = self.on_action_terminal(mission_id) if step["status"] != "GOAL_CONFIRMED" else job
        except (GoalEvidenceConflict, MissionConflict) as exc:
            raise GoalEvidenceSubmissionError("EVIDENCE_ID_CONFLICT", str(exc)) from exc
        return {"accepted": True, "created": stored["created"], "evidence_id": evidence.evidence_id,
                "mission_id": mission_id,
                "state": result["status"] if result is not None else "PENDING_ACTION_TERMINAL"}
