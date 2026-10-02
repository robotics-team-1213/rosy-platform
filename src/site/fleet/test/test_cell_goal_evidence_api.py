"""Independent producer ingress completes admitted Cell steps through app dispatch."""

from datetime import datetime, timezone

import pytest
from core_common.protocol.schemas import CellGoalEvidenceSubmission

from fleet.server.cell_goal_evidence_registry import CellGoalProducer, CellGoalRegistry
from test_cell_job_api import CELL_SHA, RECIPE_SHA, _candidate, _post, _setup
from test_cell_job_dispatcher import Transport


def _registry(token="pose-secret"):
    return CellGoalRegistry((CellGoalProducer(
        producer_id="gazebo-pose", token=token, workcell_id="omx_01", instance_id="omx_01_control",
        recipe_sha256=RECIPE_SHA, cell_sha256=CELL_SHA, evaluator_revisions=("placement-v1",),
        max_age_s=5, valid_until=datetime(2030, 1, 1, tzinfo=timezone.utc),
    ),))


def _admitted(tmp_path, *, lose_submit=False):
    transport = Transport(None, None, lose_submit=lose_submit)
    client, tasks, _ = _setup(
        tmp_path, cell_goal_registry=_registry(), enable_cell_job_dispatcher=True,
        omx_instances={"omx_01": "omx_01_control"}, omx_action_transport=transport,
        cell_job_config_revisions={"omx_01": "cell-config-v1"},
    )
    transport.store, transport.tasks = client.app.state.cell_job_store, tasks.store
    generation = tasks.store.rearm_dispatch(
        expected_generation=tasks.store.dispatch_control()["generation"], actor_id="operator-1",
    )["generation"]
    created = _post(client, "/api/fleet/proposals", "cell-secret", {
        "request_key": "cell-evidence", "workcell_id": "omx_01", "instance_id": "omx_01_control",
        "candidate": _candidate(),
    })
    identifier = created.json()["proposal"]["proposal_id"]
    assert _post(client, f"/api/fleet/proposals/{identifier}/resolve", "cell-secret").status_code == 200
    assert _post(client, f"/api/fleet/missions/{identifier}/admit", "operator-secret", {
        "expected_generation": generation,
    }).status_code == 200
    return client, tasks, transport, identifier


def _evidence(grant, completed):
    pose = {"x_m": .4, "y_m": .5, "z_m": .3, "roll_rad": 0., "pitch_rad": 0., "yaw_rad": 1.57}
    return {
        "producer_id": "gazebo-pose", "evidence_id": "goal-" + grant.action_id,
        "evidence_source": "sim_model_pose", "evaluator_revision": "placement-v1",
        "job_id": grant.cell_transfer.job_id, "step_id": grant.step_id,
        "step_index": grant.cell_transfer.step_index, "action_id": grant.action_id, "attempt_id": grant.attempt_id,
        "request_digest": grant.request_digest, "recipe_sha256": RECIPE_SHA, "cell_sha256": CELL_SHA,
        "model_id": "cell_" + grant.action_id, "observation_id": "final-" + grant.action_id,
        "observation_digest": "d" * 64, "evidence_revision": "world-base-v1", "observed_at": completed + .01,
        "model_pose_base": pose, "initial_observation_id": "initial-" + grant.action_id,
        "initial_observation_digest": "e" * 64, "initial_observed_at": grant.issued_at.timestamp(),
        "initial_model_pose_base": {**pose, "x_m": .1, "y_m": .2, "yaw_rad": 0.},
        "gripper_state": "OPEN", "gripper_evidence_id": "gripper-" + grant.action_id,
        "gripper_evidence_revision": "joint-readback-v1", "gripper_observed_at": completed + .01,
        "satisfied": True,
    }


def _submit(client, identifier, evidence, token="pose-secret"):
    body = CellGoalEvidenceSubmission(mission_id=identifier, evidence=evidence).model_dump(mode="json")
    return client.post("/api/fleet/cell-goal-evidence", headers={"X-Goal-Evidence-Token": token},
                       json=body)


def test_public_cell_evidence_completes_every_step_and_releases_claims(tmp_path):
    client, tasks, transport, identifier = _admitted(tmp_path)
    dispatcher = client.app.state.cell_job_dispatcher
    for index in range(2):
        assert dispatcher.dispatch_next()["state"] == "ACCEPTED"
        grant = transport.submissions[index]
        transport.set_receipt(grant, "SUCCEEDED", 8)
        completed = datetime.fromisoformat(transport.receipt["observed_at"]).timestamp()
        client.app.state.cell_goal_evidence_service.now = lambda: completed + .02
        assert dispatcher.dispatch_next()["state"] == "ACTION_SUCCEEDED"
        evidence = _evidence(grant, completed)
        result = _submit(client, identifier, evidence)
        assert result.status_code == 200
        assert result.json()["state"] == ("READY" if index == 0 else "GOAL_CONFIRMED")
        duplicate = _submit(client, identifier, evidence)
        assert duplicate.status_code == 200 and duplicate.json()["created"] is False
    assert tasks.store.resource_claims(resource_kind="workcell", resource_id="omx_01") == []
    assert len(transport.submissions) == 2 and dispatcher.dispatch_next() is None


def test_pending_ingress_is_completed_by_composed_terminal_callback(tmp_path):
    client, tasks, transport, identifier = _admitted(tmp_path)
    dispatcher = client.app.state.cell_job_dispatcher
    dispatcher.dispatch_next()
    grant = transport.submissions[0]
    transport.set_receipt(grant, "SUCCEEDED", 8)
    completed = datetime.fromisoformat(transport.receipt["observed_at"]).timestamp()
    client.app.state.cell_goal_evidence_service.now = lambda: completed + .02
    result = _submit(client, identifier, _evidence(grant, completed))
    assert result.status_code == 200 and result.json()["state"] == "PENDING_ACTION_TERMINAL"
    assert dispatcher.dispatch_next()["state"] == "READY"
    assert len(transport.submissions) == 1
    assert tasks.store.resource_claims(resource_kind="workcell", resource_id="omx_01")


def test_public_pending_goal_recovers_held_late_success_without_resubmission(tmp_path):
    client, tasks, transport, identifier = _admitted(tmp_path, lose_submit=True)
    dispatcher = client.app.state.cell_job_dispatcher
    assert dispatcher.dispatch_next()["state"] == "HOLD"
    grant = transport.submissions[0]
    transport.set_receipt(grant, "SUCCEEDED", 8)
    completed = datetime.fromisoformat(transport.receipt["observed_at"]).timestamp()
    client.app.state.cell_goal_evidence_service.now = lambda: completed + .02
    assert _submit(client, identifier, _evidence(grant, completed)).json()["state"] == "PENDING_ACTION_TERMINAL"
    assert dispatcher.dispatch_next()["state"] == "READY"
    assert len(transport.submissions) == 1
    assert tasks.store.resource_claims(resource_kind="workcell", resource_id="omx_01")


def test_rejected_pending_goal_does_not_rewrite_valid_terminal_success(tmp_path):
    client, tasks, transport, identifier = _admitted(tmp_path)
    dispatcher = client.app.state.cell_job_dispatcher
    dispatcher.dispatch_next()
    grant = transport.submissions[0]
    transport.set_receipt(grant, "SUCCEEDED", 8)
    completed = datetime.fromisoformat(transport.receipt["observed_at"]).timestamp()
    service = client.app.state.cell_goal_evidence_service
    service.now = lambda: completed + .02
    assert _submit(client, identifier, _evidence(grant, completed)).status_code == 200
    service.now = lambda: completed + 6
    assert dispatcher.dispatch_next()["state"] == "ACTION_SUCCEEDED"
    saved = client.app.state.cell_job_store.get(identifier)
    assert saved["steps"][0]["status"] == "ACTION_SUCCEEDED" and saved["steps"][1]["status"] == "WAITING"
    assert tasks.store.resource_claims(resource_kind="workcell", resource_id="omx_01")


def test_callback_storage_failure_preserves_the_durable_action_success(tmp_path):
    client, tasks, transport, identifier = _admitted(tmp_path)
    dispatcher = client.app.state.cell_job_dispatcher
    dispatcher.dispatch_next()
    grant = transport.submissions[0]
    transport.set_receipt(grant, "SUCCEEDED", 8)

    def unavailable(_):
        raise RuntimeError("goal storage unavailable")

    dispatcher.on_action_terminal = unavailable
    assert dispatcher.dispatch_next()["state"] == "ACTION_SUCCEEDED"
    saved = client.app.state.cell_job_store.get(identifier)
    assert saved["steps"][0]["status"] == "ACTION_SUCCEEDED" and saved["steps"][1]["status"] == "WAITING"
    assert tasks.store.resource_claims(resource_kind="workcell", resource_id="omx_01")


@pytest.mark.parametrize("token", ["operator-secret", "cell-secret", "robot-token"])
def test_user_and_robot_credentials_cannot_submit_cell_goal(tmp_path, token):
    client, _, transport, identifier = _admitted(tmp_path)
    client.app.state.cell_job_dispatcher.dispatch_next()
    grant = transport.submissions[0]
    result = _submit(client, identifier, _evidence(grant, grant.issued_at.timestamp()), token)
    assert result.status_code == 401
    assert client.app.state.cell_goal_evidence_service.store.get("goal-" + grant.action_id) is None


@pytest.mark.parametrize("token", ["operator-secret", "cell-secret", "robot-token"])
def test_cell_producer_credentials_must_be_distinct_from_users_and_robot(tmp_path, token):
    with pytest.raises(ValueError, match="credential"):
        _setup(tmp_path, cell_goal_registry=_registry(token))


def test_cell_goal_route_is_absent_without_registry(tmp_path):
    client, _, _ = _setup(tmp_path)
    assert client.post("/api/fleet/cell-goal-evidence", json={}).status_code == 404


def test_public_envelope_rejects_extra_and_nonfinite_fields_without_storing(tmp_path):
    client, _, transport, identifier = _admitted(tmp_path)
    client.app.state.cell_job_dispatcher.dispatch_next()
    grant = transport.submissions[0]
    evidence = _evidence(grant, grant.issued_at.timestamp())
    extra = client.post("/api/fleet/cell-goal-evidence", headers={"X-Goal-Evidence-Token": "pose-secret"},
                        json={"mission_id": identifier, "evidence": evidence, "allow_stale": True})
    assert extra.status_code == 422
    evidence["model_pose_base"]["yaw_rad"] = "NaN"
    invalid = client.post("/api/fleet/cell-goal-evidence", headers={"X-Goal-Evidence-Token": "pose-secret"},
                          json={"mission_id": identifier, "evidence": evidence})
    assert invalid.status_code == 422
    assert client.app.state.cell_goal_evidence_service.store.get(evidence["evidence_id"]) is None
