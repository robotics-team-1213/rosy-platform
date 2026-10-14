"""D-763 item 7: approval by risk comes from the step-kind registry and the server enforces it."""

from hashlib import sha256

import pytest
from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.server import step_action_kinds
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.mission_service import MissionService
from fleet.server.mission_store import MissionStore
from fleet.server.proposal_store import ProposalStore
from fleet.server.step_action_kinds import APPROVALS, required_approval, step_action_kind
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint
from test_cell_job_api import FixedCellCompiler, _candidate as _cell_candidate
from test_mission_api import _candidate as _er2_candidate, _resolution

# Placeholder identities only (D-763 rev 2 Q6).
_USERS = {"cell-secret": ("cell-service", "service"), "op1-secret": ("operator-1", "operator"),
          "op2-secret": ("operator-2", "operator"), "viewer-secret": ("viewer-1", "viewer")}


def _app(tmp_path, *, named=True, console_token=None):
    db = tmp_path / "fleet.sqlite3"
    tasks = FleetTaskService(FleetTaskStore(db), robot_ids=("rosy_01",))
    users = {sha256(token.encode()).hexdigest(): {"principal_id": pid, "role": role}
             for token, (pid, role) in _USERS.items()} if named else None
    app = create_app(
        FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "robot-token")],
                     [FakeRobot("rosy_01")]),
        task_service=tasks, site_users=users, console_token=console_token,
        mission_service=MissionService(MissionStore(db)), proposal_store=ProposalStore(db),
        candidate_resolver=_resolution, cell_job_compiler=FixedCellCompiler(),
    )
    return TestClient(app), tasks


def _post(client, path, token, body=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post(path, headers=headers, json=body or {})


def _resolved(client, token, candidate, key="req-1"):
    created = _post(client, "/api/fleet/proposals", token, {
        "request_key": key, "workcell_id": "omx_01", "instance_id": "omx_01_control",
        "candidate": candidate})
    assert created.status_code == 200, created.text
    proposal_id = created.json()["proposal"]["proposal_id"]
    assert _post(client, f"/api/fleet/proposals/{proposal_id}/resolve", token).status_code == 200
    return proposal_id


def _generation(tasks):
    control = tasks.store.dispatch_control()
    return tasks.store.rearm_dispatch(expected_generation=control["generation"],
                                      actor_id="operator-1")["generation"]


def test_every_registered_kind_carries_an_approval():
    for name in step_action_kinds._KINDS:
        assert step_action_kind(name).approval in APPROVALS
    for name in step_action_kinds._LEGACY_APPROVALS:
        assert required_approval([name]) in APPROVALS


def test_arm_step_is_two_person_and_legacy_pick_place_stays_proposer_only():
    assert required_approval(["CELL_TRANSFER"]) == "two_person"
    # D-763 rev 2 Q5: own-proposer admission until the slice that connects its physical dispatch.
    assert required_approval(["PICK_PLACE"]) == "proposer_only"
    assert required_approval(["PICK_PLACE", "CELL_TRANSFER"]) == "two_person"


@pytest.mark.parametrize("kinds", [["FETCH"], ["CELL_TRANSFER", "FETCH"], []])
def test_unknown_or_missing_kind_is_refused(kinds):
    with pytest.raises(ValueError):
        required_approval(kinds)


def test_unknown_candidate_kind_is_refused_at_proposal(tmp_path):
    client, _ = _app(tmp_path)
    response = _post(client, "/api/fleet/proposals", "op1-secret", {
        "request_key": "req-x", "workcell_id": "omx_01", "instance_id": "omx_01_control",
        "candidate": {**_er2_candidate(), "kind": "fetch"}})
    assert response.status_code == 422


def test_two_person_kind_refuses_its_proposer_and_admits_another_operator(tmp_path):
    client, tasks = _app(tmp_path)
    job = _resolved(client, "cell-secret", _cell_candidate())
    with client.app.state.proposal_store._connect() as connection:  # proposer aliased to operator-1
        connection.execute("UPDATE fleet_proposals SET principal_id='operator-1' WHERE proposal_id=?",
                           (job,))
        connection.commit()
    body = {"expected_generation": _generation(tasks)}

    own = _post(client, f"/api/fleet/missions/{job}/admit", "op1-secret", body)
    other = _post(client, f"/api/fleet/missions/{job}/admit", "op2-secret", body)

    assert own.status_code == 403
    assert own.json()["detail"]["code"] == "CELL_JOB_APPROVER_MUST_DIFFER_FROM_PROPOSER"
    assert other.status_code == 200 and other.json()["mission"]["status"] == "READY"


def test_proposer_only_kind_is_hidden_from_other_operators_and_viewers(tmp_path):
    client, tasks = _app(tmp_path)
    mission = _resolved(client, "op1-secret", _er2_candidate())
    body = {"expected_generation": _generation(tasks)}

    other = _post(client, f"/api/fleet/missions/{mission}/admit", "op2-secret", body)
    viewer = _post(client, f"/api/fleet/missions/{mission}/admit", "viewer-secret", body)
    own = _post(client, f"/api/fleet/missions/{mission}/admit", "op1-secret", body)

    assert other.status_code == 404 and other.json()["detail"]["code"] == "MISSION_NOT_FOUND"
    assert viewer.status_code == 403
    assert own.status_code == 200 and own.json()["mission"]["status"] == "READY"


def test_shared_console_token_cannot_admit(tmp_path):
    client, tasks = _app(tmp_path, named=False, console_token="shared-secret")
    mission = _resolved(client, "shared-secret", _er2_candidate())
    response = _post(client, f"/api/fleet/missions/{mission}/admit", "shared-secret",
                     {"expected_generation": _generation(tasks)})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "OPERATOR_IDENTITY_REQUIRED"
