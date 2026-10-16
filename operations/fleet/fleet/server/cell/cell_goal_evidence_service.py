"""Authenticate, persist and judge independent Cell observations before goal completion.

Ported from main (778f50294, 3ef12ca3e) onto the C4b step ledger: a producer registered for one
simulation cell, recipe and evaluator revision reports a ``sim_model_pose`` observation of one
attempt. The observation is bound to the persisted grant and must follow the durable device
success; Fleet then judges it against the step's stored ``item_at_pose`` predicate. Producers
cannot assert satisfaction (the wire model has no ``satisfied`` field). Evidence that arrives
before the terminal success is stored and applied when the dispatcher records that success.

A multi-arm Job (D-779 §3) is judged per step, not by ``current_step_index``: the evidence names
the Action of the arm the stored predicate was compiled for (the placement's first primary arm),
the producer is registered for the Job's cell and that arm's instance, and the step is confirmed
only after every assigned arm Action's durable success, observed after the last of them. A step
run by an alternate arm has no predicate in its frame yet and is refused (fail closed, D-779 open
question on alternate-arm goal tolerance).
"""

from __future__ import annotations

from datetime import datetime
import math
import time

from pydantic import ValidationError

from core_common.protocol.cell_goal_evidence import CellGoalEvidence
from rosy.execution.site.item_pose import ItemPoseEvidence, item_pose_predicate, verify_item_at_pose

from .cell_arm_store import ArmJobStore
from .goal_evidence_service import GoalEvidenceSubmissionError
from .goal_evidence_store import GoalEvidenceConflict
from .mission_store import MissionConflict


class CellGoalEvidenceService:
    def __init__(self, jobs, registry, store, *, now=None):
        if jobs.path.resolve() != store.path.resolve():
            raise ValueError("Cell goals and Jobs must share the persistent journal database")
        self.jobs, self.registry, self.store = jobs, registry, store
        self.arms = ArmJobStore(jobs)
        self.now = now or time.time

    @staticmethod
    def _arm_step(job, step, action_id):
        """Multi-arm: the step seen through the predicate arm's Action that the evidence names."""
        placement = next(item for item in job["placements"] if item["step_index"] == step["step_index"])
        frame_arm = placement["arms"][0]
        mine = [action for action in job["step_actions"] if action["step_index"] == step["step_index"]]
        action = next((item for item in mine if item["action_id"] == action_id), None)
        peers = [item for item in mine if item["arm_role"] in placement["assigned"]]
        if (action is None or action["arm_role"] != frame_arm or frame_arm not in placement["assigned"]
                or sorted(item["arm_role"] for item in peers) != sorted(placement["assigned"])
                or any(item["grant"] is None for item in peers)):
            raise GoalEvidenceSubmissionError("EVIDENCE_SCOPE_MISMATCH",
                                              "evidence does not name the predicate arm's started Action")
        instance = next(arm["instance_id"] for arm in job["arms"] if arm["arm_role"] == frame_arm)
        return {**step, "action_id": action["action_id"], "attempt_id": action["attempt_id"],
                "request_digest": action["request_digest"], "grant": action["grant"],
                "instance_id": instance, "peers": peers}

    def _validate(self, producer, job, raw, now):
        try:
            evidence = CellGoalEvidence.model_validate(raw)
        except ValidationError as exc:
            raise GoalEvidenceSubmissionError("CELL_GOAL_EVIDENCE_INVALID", str(exc)) from exc
        index = evidence.step_index
        if index >= len(job["steps"]):
            raise GoalEvidenceSubmissionError("EVIDENCE_SCOPE_MISMATCH", "Cell step does not exist")
        step = job["steps"][index]
        multi = "arms" in job
        if multi:
            step = self._arm_step(job, step, evidence.action_id)
        grant = step["grant"]
        if grant is None:
            raise GoalEvidenceSubmissionError("EVIDENCE_SCOPE_MISMATCH", "Cell step has no submitted grant")
        if (producer.producer_id != evidence.producer_id or producer.workcell_id != job["workcell_id"]
                or producer.instance_id != (step["instance_id"] if multi else job["instance_id"])
                or producer.recipe_sha256 != job["recipe_digest"]
                or producer.cell_sha256 != job["cell_digest"]
                or evidence.evaluator_revision not in producer.evaluator_revisions):
            raise GoalEvidenceSubmissionError("PRODUCER_SCOPE_MISMATCH", "producer is not registered for this Cell")
        if (evidence.job_id != job["job_id"] or evidence.step_id != step["step_id"]
                or evidence.recipe_sha256 != job["recipe_digest"] or evidence.cell_sha256 != job["cell_digest"]
                or evidence.action_id != step["action_id"] or evidence.attempt_id != step["attempt_id"]
                or evidence.request_digest != step["request_digest"] or evidence.model_id != "cell_" + step["action_id"]
                or (not multi and index != job["current_step_index"] and step["status"] != "GOAL_CONFIRMED")):
            raise GoalEvidenceSubmissionError("EVIDENCE_SCOPE_MISMATCH", "evidence does not match the Cell attempt")
        issued = max(datetime.fromisoformat(item["issued_at"].replace("Z", "+00:00")).timestamp()
                     for item in ([peer["grant"] for peer in step["peers"]] if multi else [grant]))
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
        observations must follow it (64b4b1faa). Returns None while no terminal success exists.
        Multi-arm: every assigned arm Action's latest outcome is its attempt's success, and the
        observations follow the last of them (the initial one precedes the first)."""
        terminals = []
        for action in step.get("peers") or [step]:
            terminal = next((event for event in reversed(job["events"])
                             if event["step_index"] == step["step_index"]
                             and event["event_type"].startswith("CELL_STEP_ACTION_")
                             and ("peers" not in step or event["detail"].get("action_id") == action["action_id"])),
                            None)
            if (terminal is None or terminal["event_type"] != "CELL_STEP_ACTION_SUCCEEDED"
                    or terminal["detail"]["action_id"] != action["action_id"]
                    or terminal["detail"]["attempt_id"] != action["attempt_id"]):
                return None
            terminals.append(terminal)
        try:
            times = [datetime.fromisoformat(terminal["detail"]["result"]["observed_at"].replace(
                "Z", "+00:00")).timestamp() for terminal in terminals]
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise GoalEvidenceSubmissionError("CELL_GOAL_EVIDENCE_INVALID",
                                              "local terminal timestamp is missing") from exc
        terminal_at = max(times)
        terminal = terminals[times.index(terminal_at)]
        if (evidence.observed_at < terminal_at or evidence.gripper_observed_at < terminal_at
                or evidence.initial_observed_at > min(times)):
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

    def on_action_terminal(self, mission_id, step_index=None):
        """Apply stored evidence once the step's durable success is recorded (dispatcher hook).

        A multi-arm Job tries ``step_index`` (or every ACTION_SUCCEEDED step); the first refusal is
        raised after the others were tried, so one stale step does not block another."""
        job = self.jobs.get(mission_id)
        if job is not None and "arms" in job:
            return self._arm_terminal(job, step_index)
        if job is None or job["status"] != "ACTION_SUCCEEDED":
            return None
        step = job["steps"][job["current_step_index"]]
        stored = self.store.latest_for_attempt(mission_id=mission_id, action_id=step["action_id"],
                                               attempt_id=step["attempt_id"])
        if stored is None:
            return None
        return self._apply_stored(job, stored, self.jobs)

    def _arm_terminal(self, job, step_index):
        result, refused = None, None
        for index in range(len(job["steps"])):
            step = job["steps"][index]
            if step["status"] != "ACTION_SUCCEEDED" or step_index not in {None, index}:
                continue
            placement = next(item for item in job["placements"] if item["step_index"] == index)
            action = next((item for item in job["step_actions"] if item["step_index"] == index
                           and item["arm_role"] == placement["arms"][0] and item["action_id"] is not None), None)
            stored = action and self.store.latest_for_attempt(
                mission_id=job["mission_id"], action_id=action["action_id"], attempt_id=action["attempt_id"])
            if not stored:
                continue
            try:
                result = self._apply_stored(job, stored, self.arms) or result
            except (GoalEvidenceSubmissionError, MissionConflict) as exc:
                refused = refused or exc
                continue
            job = self.jobs.get(job["mission_id"])
        if refused is not None:
            raise refused
        return result

    def _apply_stored(self, job, stored, ledger):
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
        return ledger.confirm_step_goal(
            job["mission_id"], step_index=step["step_index"], action_id=step["action_id"],
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
            result = (self.on_action_terminal(mission_id, evidence.step_index)
                      if step["status"] != "GOAL_CONFIRMED" else job)
        except (GoalEvidenceConflict, MissionConflict) as exc:
            raise GoalEvidenceSubmissionError("EVIDENCE_ID_CONFLICT", str(exc)) from exc
        return {"accepted": True, "created": stored["created"], "evidence_id": evidence.evidence_id,
                "mission_id": mission_id,
                "state": result["status"] if result is not None else "PENDING_ACTION_TERMINAL"}


__all__ = ["CellGoalEvidenceService"]
