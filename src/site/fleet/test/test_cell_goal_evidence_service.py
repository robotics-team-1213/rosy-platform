"""Registered Cell evaluators must bind fresh observations to a persisted grant."""

from datetime import datetime, timezone

import pytest

from fleet.server.cell_goal_evidence_service import CellGoalEvidenceService
from fleet.server.cell_goal_evidence_registry import CellGoalProducer, CellGoalRegistry
from fleet.server.goal_evidence_service import GoalEvidenceSubmissionError
from fleet.server.goal_evidence_store import GoalEvidenceStore
from test_cell_job_dispatcher import _ready


def _setup(tmp_path, *, terminal=True, lose_submit=False):
    path, jobs, tasks, transport, dispatcher = _ready(tmp_path, lose_submit=lose_submit)
    dispatcher.dispatch_next()
    grant = transport.submissions[0]
    transport.set_receipt(grant, "SUCCEEDED", 8)
    completed = datetime.fromisoformat(transport.receipt["observed_at"]).timestamp()
    if terminal:
        dispatcher.dispatch_next()
    producer = CellGoalProducer(
        producer_id="gazebo-pose", token="pose-secret", workcell_id=grant.workcell_id,
        instance_id=grant.instance_id, recipe_sha256=grant.cell_transfer.recipe_sha256,
        cell_sha256=grant.cell_transfer.cell_sha256, evaluator_revisions=("placement-v1",),
        max_age_s=5.0, valid_until=datetime.fromtimestamp(completed + 1000, timezone.utc),
    )
    evidence = {
        "producer_id": producer.producer_id, "evidence_id": "cell-goal-0",
        "evidence_source": "sim_model_pose", "evaluator_revision": "placement-v1",
        "job_id": grant.cell_transfer.job_id, "step_id": grant.step_id, "step_index": 0,
        "action_id": grant.action_id, "attempt_id": grant.attempt_id,
        "request_digest": grant.request_digest, "recipe_sha256": grant.cell_transfer.recipe_sha256,
        "cell_sha256": grant.cell_transfer.cell_sha256, "model_id": "cell_" + grant.action_id,
        "observation_id": "model-pose-1", "observation_digest": "d" * 64,
        "evidence_revision": "world-base-v1", "observed_at": completed + .01,
        "model_pose_base": {"x_m": .4, "y_m": .5, "z_m": .3,
                            "roll_rad": 0., "pitch_rad": 0., "yaw_rad": 1.57},
        "initial_observation_id": "model-pose-0", "initial_observation_digest": "c" * 64,
        "initial_observed_at": grant.issued_at.timestamp(),
        "initial_model_pose_base": {"x_m": .1, "y_m": .2, "z_m": .3,
                                    "roll_rad": 0., "pitch_rad": 0., "yaw_rad": 0.},
        "gripper_state": "OPEN", "gripper_evidence_id": "gripper-0",
        "gripper_evidence_revision": "joint-readback-v1", "gripper_observed_at": completed + .01,
        "satisfied": True,
    }
    clock = [completed + .02]
    service = CellGoalEvidenceService(jobs, CellGoalRegistry((producer,)), GoalEvidenceStore(path),
                                      now=lambda: clock[0])
    return service, jobs, tasks, transport, dispatcher, evidence, clock


def test_authenticated_cell_goal_advances_only_matching_step_and_is_idempotent(tmp_path):
    service, jobs, tasks, _, _, evidence, _ = _setup(tmp_path)
    result = service.submit(token="pose-secret", mission_id="cell-mission-1", raw_evidence=evidence)
    assert result["state"] == "READY" and result["created"] is True
    saved = jobs.get("cell-mission-1")
    assert saved["current_step_index"] == 1 and saved["steps"][0]["goal_evidence"]["model_id"] == evidence["model_id"]
    assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01")
    duplicate = service.submit(token="pose-secret", mission_id="cell-mission-1", raw_evidence=evidence)
    assert duplicate["created"] is False and jobs.get("cell-mission-1") == saved


def test_cell_goal_can_arrive_before_terminal_readback_without_advancing(tmp_path):
    service, jobs, _, _, dispatcher, evidence, _ = _setup(tmp_path, terminal=False)
    assert service.submit(token="pose-secret", mission_id="cell-mission-1", raw_evidence=evidence)[
        "state"] == "PENDING_ACTION_TERMINAL"
    assert jobs.get("cell-mission-1")["status"] == "RUNNING"
    dispatcher.dispatch_next()
    assert service.on_action_terminal("cell-mission-1")["status"] == "READY"


def test_registered_goal_recovers_held_late_success_without_resubmission(tmp_path):
    service, jobs, tasks, transport, _, evidence, _ = _setup(tmp_path, lose_submit=True)
    assert jobs.get("cell-mission-1")["status"] == "HOLD"
    assert service.submit(token="pose-secret", mission_id="cell-mission-1", raw_evidence=evidence)["state"] == "READY"
    assert len(transport.submissions) == 1
    assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01")


@pytest.mark.parametrize("mutation", ["token", "producer", "attempt", "digest", "model", "recipe",
                                      "revision", "stale", "future", "pre_terminal", "gripper_stale",
                                      "initial_pre_grant", "bool_index", "pose_nan", "unsatisfied"])
def test_invalid_cell_goal_preserves_claims_and_ordered_step(tmp_path, mutation):
    service, jobs, tasks, _, _, evidence, clock = _setup(tmp_path)
    token = "pose-secret"
    if mutation == "token":
        token = "operator-secret"
    elif mutation == "producer":
        evidence["producer_id"] = "different-producer"
    elif mutation == "attempt":
        evidence["attempt_id"] = "different-attempt"
    elif mutation == "digest":
        evidence["request_digest"] = "e" * 64
    elif mutation == "model":
        evidence["model_id"] = "different-model"
    elif mutation == "recipe":
        evidence["recipe_sha256"] = "e" * 64
    elif mutation == "revision":
        evidence["evaluator_revision"] = "unregistered-v2"
    elif mutation == "stale":
        evidence["observed_at"] = clock[0] - 6
    elif mutation == "future":
        evidence["observed_at"] = clock[0] + 1
    elif mutation == "pre_terminal":
        evidence["observed_at"] -= 1
    elif mutation == "gripper_stale":
        evidence["gripper_observed_at"] = clock[0] - 6
    elif mutation == "initial_pre_grant":
        evidence["initial_observed_at"] -= 1
    elif mutation == "bool_index":
        evidence["step_index"] = False
    elif mutation == "pose_nan":
        evidence["model_pose_base"]["x_m"] = float("nan")
    else:
        evidence["satisfied"] = False
    previous = jobs.get("cell-mission-1")
    with pytest.raises(GoalEvidenceSubmissionError):
        service.submit(token=token, mission_id="cell-mission-1", raw_evidence=evidence)
    assert jobs.get("cell-mission-1") == previous
    assert service.store.get(evidence["evidence_id"]) is None
    assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01")


def test_preterminal_gripper_rejection_allows_corrected_same_evidence_id(tmp_path):
    service, jobs, _, _, _, evidence, _ = _setup(tmp_path)
    valid_time = evidence["gripper_observed_at"]
    evidence["gripper_observed_at"] = evidence["initial_observed_at"]
    with pytest.raises(GoalEvidenceSubmissionError):
        service.submit(token="pose-secret", mission_id="cell-mission-1", raw_evidence=evidence)
    assert service.store.get(evidence["evidence_id"]) is None
    evidence["gripper_observed_at"] = valid_time
    assert service.submit(token="pose-secret", mission_id="cell-mission-1", raw_evidence=evidence)["state"] == "READY"


def test_goal_completion_rejects_newer_terminal_between_validation_and_commit(tmp_path, monkeypatch):
    service, jobs, tasks, transport, _, evidence, clock = _setup(tmp_path, lose_submit=True)
    confirm = jobs.confirm_step_goal

    def interleave(*args, **kwargs):
        receipt = {**transport.receipt, "journal_event_id": 9,
                   "observed_at": datetime.fromtimestamp(clock[0], timezone.utc).isoformat()}
        jobs.record_action_receipt("cell-mission-1", step_index=0, receipt=receipt)
        return confirm(*args, **kwargs)

    monkeypatch.setattr(jobs, "confirm_step_goal", interleave)
    with pytest.raises(GoalEvidenceSubmissionError):
        service.submit(token="pose-secret", mission_id="cell-mission-1", raw_evidence=evidence)
    saved = jobs.get("cell-mission-1")
    assert saved["status"] == "HOLD" and saved["steps"][1]["status"] == "WAITING"
    assert saved["steps"][0]["goal_evidence"] is None
    assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01")


def test_pending_goal_is_rechecked_for_freshness_and_expired_credentials(tmp_path):
    service, jobs, tasks, _, dispatcher, evidence, clock = _setup(tmp_path, terminal=False)
    service.submit(token="pose-secret", mission_id="cell-mission-1", raw_evidence=evidence)
    dispatcher.dispatch_next()
    clock[0] += 6
    with pytest.raises(GoalEvidenceSubmissionError):
        service.on_action_terminal("cell-mission-1")
    clock[0] += 1000
    assert service.on_action_terminal("cell-mission-1") is None
    assert jobs.get("cell-mission-1")["status"] == "ACTION_SUCCEEDED"
    assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01")
