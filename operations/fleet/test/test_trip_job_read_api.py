"""D-856: read transport execution facts without Cell or application semantics."""
from hashlib import sha256
import json

from fastapi.testclient import TestClient
import pytest

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.job_trip_rows import TripJobRows
from fleet.server.mission_service import MissionService
from fleet.server.mission_store import MissionStore
from fleet.server.proposal_store import ProposalStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint


ROBOT = "rosy_01"
STEPS = [{"to": "destination", "via": []}]
KEY = "harbor/이송?key=1"
USERS = {"owner-secret": ("owner", "operator"), "other-secret": ("other", "operator"),
         "viewer-secret": ("viewer", "viewer")}


def client_for(tmp_path, *, profile="simulation"):
    path = tmp_path / "fleet.sqlite3"
    tasks = FleetTaskService(FleetTaskStore(path), robot_ids=(ROBOT,))
    users = {sha256(token.encode()).hexdigest(): {"principal_id": principal, "role": role}
             for token, (principal, role) in USERS.items()}
    app = create_app(
        FleetConsole([RobotEndpoint(ROBOT, "http://127.0.0.1:8080", "robot-token")], [FakeRobot(ROBOT)]),
        task_service=tasks, site_users=users, deployment_profile=profile,
        mission_service=MissionService(MissionStore(path)), proposal_store=ProposalStore(path),
    )
    control = tasks.store.dispatch_control()
    tasks.store.rearm_dispatch(expected_generation=control["generation"], actor_id="owner")
    return TestClient(app), TripJobRows(app.state.cell_job_store)


def create(rows, *, key=KEY):
    digest = sha256(json.dumps({"candidates": [ROBOT], "steps": STEPS}, sort_keys=True,
                               separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    return rows.create("transport-job", ROBOT, "owner", STEPS,
                       request_key="trip-pool:" + key, request_digest=digest)


def get(client, path="/api/fleet/trip-jobs/transport-job", *, token="owner-secret", **kwargs):
    return client.get(path, headers={"Authorization": "Bearer " + token} if token else {}, **kwargs)


def test_owner_can_reconcile_by_id_and_original_request_key(tmp_path):
    client, rows = client_for(tmp_path)
    submitted = create(rows)
    by_id = get(client)
    by_key = get(client, "/api/fleet/trip-jobs", params={"request_key": KEY})
    assert by_id.status_code == by_key.status_code == 200
    job = by_id.json()["job"]
    assert by_key.json() == by_id.json()
    assert job["mission_id"] == submitted["mission_id"]
    assert job["request_key"] == KEY and job["request_digest"] == submitted["request_digest"]
    assert job["robot_id"] == ROBOT and job["status"] == "READY"
    assert job["steps"][0]["step"] == STEPS[0]
    assert job["steps"][0]["attempt_id"] is None
    assert set(job) == {"mission_id", "request_key", "request_digest", "robot_id", "status",
                        "current_step_index", "steps", "reason", "updated_at"}


@pytest.mark.parametrize("token", ["other-secret", "viewer-secret"])
def test_another_principal_cannot_discover_the_execution(tmp_path, token):
    client, rows = client_for(tmp_path)
    create(rows)
    for response in (get(client, token=token), get(client, "/api/fleet/trip-jobs", token=token,
                                                 params={"request_key": KEY})):
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "TRIP_JOB_NOT_FOUND"


def test_read_requires_authentication(tmp_path):
    client, rows = client_for(tmp_path)
    create(rows)
    assert get(client, token=None).status_code == 401


@pytest.mark.parametrize("key", ["", " padded", "bad\nkey", "x" * 129])
def test_request_lookup_rejects_invalid_key(tmp_path, key):
    client, _ = client_for(tmp_path)
    assert get(client, "/api/fleet/trip-jobs", params={"request_key": key}).status_code == 422


def test_legacy_robot_request_is_readable_without_inventing_a_candidate_key(tmp_path):
    client, rows = client_for(tmp_path)
    rows.create("transport-job", ROBOT, "owner", STEPS)
    response = get(client)
    assert response.status_code == 200
    assert response.json()["job"]["request_key"] is None


def test_cell_and_mixed_jobs_do_not_leak_through_transport_reads(tmp_path):
    client, rows = client_for(tmp_path)
    create(rows)
    with rows.store._connect() as connection:
        connection.execute("UPDATE fleet_cell_steps SET action_kind='CELL_TRANSFER' WHERE mission_id='transport-job'")
        connection.commit()
    assert get(client).status_code == 404
    assert get(client, "/api/fleet/trip-jobs", params={"request_key": KEY}).status_code == 404


def test_closed_profile_reads_the_fenced_job_without_installing_post_or_resuming_it(tmp_path):
    client, rows = client_for(tmp_path)
    create(rows)
    closed, current = client_for(tmp_path, profile="production")
    before = current.store.get("transport-job")
    assert before["status"] == "HOLD"
    response = get(closed)
    assert response.status_code == 200
    assert response.json()["job"]["status"] == "HOLD"
    assert closed.post("/api/fleet/trip-jobs", json={}).status_code == 405
    assert current.store.get("transport-job") == before


def test_reads_preserve_attempt_identity_and_do_not_write_the_ledger(tmp_path):
    client, rows = client_for(tmp_path)
    create(rows)
    assert rows.started("transport-job", 0, "trip-attempt-1", "owner")
    running = get(client).json()["job"]
    assert running["status"] == "RUNNING"
    assert running["steps"][0]["attempt_id"] == "trip-attempt-1"
    rows.arrived("transport-job", 0, "trip-attempt-1")
    with rows.store._connect() as connection:
        before = list(connection.iterdump())
    arrived = get(client).json()["job"]
    assert arrived["status"] == "GOAL_CONFIRMED"
    assert arrived["steps"][0]["attempt_id"] == running["steps"][0]["attempt_id"]
    with rows.store._connect() as connection:
        assert list(connection.iterdump()) == before
