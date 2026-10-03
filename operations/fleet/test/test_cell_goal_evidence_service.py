"""Registered Cell evaluators bind fresh observations to a persisted grant; Fleet judges the pose.

Ported from main (778f50294) onto the C4b StepJobDispatcher and the per-step stored predicate.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from fleet.server.cell_goal_evidence import attach_goal_predicates
from fleet.server.cell_goal_evidence_registry import CellGoalProducer, CellGoalRegistry
from fleet.server.cell_goal_evidence_service import CellGoalEvidenceService
from fleet.server.cell_job_store import CellJobStore
from fleet.server.goal_evidence_service import GoalEvidenceSubmissionError
from fleet.server.goal_evidence_store import GoalEvidenceStore
from fleet.server.mission_store import MissionConflict
from fleet.server.step_dispatcher import StepJobDispatcher
from rosy.execution.site.item_pose import ItemPoseTolerance

from test_cell_job_store import _stores, _submission
from test_step_dispatcher import REVISIONS, Transport, _receipt

ROOT = Path(__file__).resolve().parents[3]
GEOMETRY = {"box": {"grasp_depth_m": 0.015, "height_m": 0.03},
            "slip_sheet": {"grasp_depth_m": 0.0, "height_m": 0.002}}


def _tolerance():
    return ItemPoseTolerance.from_mapping(yaml.safe_load(
        (ROOT / "deploy/robot/omx/sim/item_pose_goal.yaml").read_text(encoding="utf-8")))


def _setup(tmp_path, *, terminal=True, lose_submit=False, predicates=True):
    path, tasks, _, enabled = _stores(tmp_path)
    jobs = CellJobStore(path)
    submission = _submission()
    if predicates:
        attach_goal_predicates(submission, GEOMETRY, _tolerance())
    jobs.create(mission_id="cell-mission-1", proposal_principal_id="cell-service",
                request_key="cell-request-1", request_digest="d" * 64, submission=submission)
    jobs.admit("cell-mission-1", actor_id="operator-1", expected_generation=enabled["generation"])
    transport = Transport()
    if lose_submit:
        def lost(grant):
            transport.submissions.append(grant)
            raise TimeoutError("response lost")
        transport.submit = lost
    holder = {}
    dispatcher = StepJobDispatcher(
        jobs, tasks, transport, {"omx_01": "omx_01_control"}, REVISIONS, deployment_profile="simulation",
        on_step_action_succeeded=lambda job, index: (
            holder["service"].on_action_terminal(job["mission_id"]) if "service" in holder else None))
    dispatcher.dispatch_next()
    grant = transport.submissions[0]
    success = _receipt(grant, "SUCCEEDED", 8)
    completed = success.observed_at.timestamp()
    transport.on_get = lambda _: success
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
    }
    clock = [completed + .02]
    service = CellGoalEvidenceService(jobs, CellGoalRegistry((producer,)), GoalEvidenceStore(path),
                                      now=lambda: clock[0])
    holder["service"] = service
    return service, jobs, tasks, transport, dispatcher, evidence, clock


def test_authenticated_cell_goal_advances_only_matching_step_and_is_idempotent(tmp_path):
    service, jobs, tasks, _, _, evidence, _ = _setup(tmp_path)
    result = service.submit(token="pose-secret", mission_id="cell-mission-1", raw_evidence=evidence)
    assert result["state"] == "READY" and result["created"] is True
    saved = jobs.get("cell-mission-1")
    recorded = saved["steps"][0]["goal_evidence"]
    assert saved["current_step_index"] == 1 and recorded["model_id"] == evidence["model_id"]
    assert recorded["predicate"]["tolerance"]["xy_m"] == 0.005
    assert recorded["gripper_state_source"] == "producer_asserted"
    assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01")
    duplicate = service.submit(token="pose-secret", mission_id="cell-mission-1", raw_evidence=evidence)
    assert duplicate["created"] is False and jobs.get("cell-mission-1") == saved


def test_cell_goal_can_arrive_before_terminal_readback_without_advancing(tmp_path):
    service, jobs, _, _, dispatcher, evidence, _ = _setup(tmp_path, terminal=False)
    assert service.submit(token="pose-secret", mission_id="cell-mission-1", raw_evidence=evidence)[
        "state"] == "PENDING_ACTION_TERMINAL"
    assert jobs.get("cell-mission-1")["status"] == "RUNNING"
    dispatcher.dispatch_next()  # the terminal success applies the stored evidence (dispatcher hook)
    assert jobs.get("cell-mission-1")["status"] == "READY"


def test_registered_goal_completes_a_read_back_late_success_without_resubmission(tmp_path):
    # Main's "held late success" case: here the readback of the HOLD/UNKNOWN Job turns it into
    # ACTION_SUCCEEDED (fence unchanged), so evidence confirms it; nothing is resent.
    service, jobs, tasks, transport, _, evidence, _ = _setup(tmp_path, lose_submit=True)
    assert jobs.get("cell-mission-1")["status"] == "ACTION_SUCCEEDED"
    assert service.submit(token="pose-secret", mission_id="cell-mission-1", raw_evidence=evidence)["state"] == "READY"
    assert len(transport.submissions) == 1
    assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01")


@pytest.mark.parametrize("mutation", ["token", "producer", "attempt", "digest", "model", "recipe",
                                      "revision", "stale", "future", "pre_terminal", "gripper_stale",
                                      "initial_pre_grant", "bool_index", "pose_nan", "off_pose",
                                      "satisfied_field", "frame_tilt"])
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
    elif mutation == "off_pose":  # Fleet judges the stored predicate: 1 cm off is not at pose
        evidence["model_pose_base"]["x_m"] += 0.01
    elif mutation == "frame_tilt":
        evidence["model_pose_base"]["roll_rad"] = 1.571
    else:  # a producer cannot assert satisfaction: the field does not exist
        evidence["satisfied"] = True
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


def test_goal_completion_rejects_a_stop_between_validation_and_commit(tmp_path, monkeypatch):
    # Main's interleaving case on this ledger: a site stop lands after validation; the confirm
    # refuses the held Job and the claims stay parked.
    service, jobs, tasks, _, _, evidence, _ = _setup(tmp_path)
    confirm = jobs.confirm_step_goal

    def interleave(*args, **kwargs):
        tasks.trip_stop_latch(actor_id="operator-1")
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
    clock[0] += 6
    dispatcher.dispatch_next()  # the hook fails closed on stale evidence; the success stays recorded
    assert jobs.get("cell-mission-1")["status"] == "ACTION_SUCCEEDED"
    with pytest.raises(GoalEvidenceSubmissionError):
        service.on_action_terminal("cell-mission-1")
    clock[0] += 1000
    assert service.on_action_terminal("cell-mission-1") is None
    assert jobs.get("cell-mission-1")["status"] == "ACTION_SUCCEEDED"
    assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01")


def test_a_step_without_a_stored_predicate_cannot_be_confirmed(tmp_path):
    service, jobs, _, _, _, evidence, _ = _setup(tmp_path, predicates=False)
    with pytest.raises(GoalEvidenceSubmissionError, match="predicate"):
        service.submit(token="pose-secret", mission_id="cell-mission-1", raw_evidence=evidence)
    assert jobs.get("cell-mission-1")["steps"][0]["status"] == "ACTION_SUCCEEDED"


def test_durable_success_is_required_for_the_exact_attempt(tmp_path):
    # Port of main 64b4b1faa: the latest device outcome must be this attempt's SUCCEEDED.
    service, jobs, _, _, _, evidence, _ = _setup(tmp_path)
    with jobs._connect() as connection:
        connection.execute("UPDATE fleet_cell_events SET event_type='CELL_STEP_ACTION_UNKNOWN' "
                           "WHERE event_type='CELL_STEP_ACTION_SUCCEEDED'")
        connection.commit()
    with pytest.raises(MissionConflict, match="terminal Action success"):
        jobs.confirm_step_goal("cell-mission-1", step_index=0, action_id=evidence["action_id"],
                               attempt_id=evidence["attempt_id"], evidence={
                                   **evidence, "satisfied": True})
