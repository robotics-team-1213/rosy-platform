"""Only the authenticated mapped owner can review and link channel requests."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet.server.channel_workflow import install_workflow_routes
from fleet.server.site_auth import SitePrincipal
from test_channel_workflow import fixture, GOAL, task


def client_for(workflow, principal, task_service=None, console=None):
    app = FastAPI()
    install_workflow_routes(app, workflow, require_operator=lambda: SitePrincipal(principal, "operator"),
                            read_guard=[], task_service=task_service, console=console)
    return TestClient(app)


def test_console_review_then_existing_task_link_is_owner_scoped(tmp_path):
    workflow, _, tasks, _, receipt = fixture(tmp_path)
    client = client_for(workflow, "op")
    path = f"/api/fleet/channel-requests/{receipt['request_id']}"
    body = {"expected_hash": receipt["content_hash"], "expected_revision": 0,
            "state": "READY", "candidate": GOAL, "reason": "confirmed original request"}
    assert client.put(path + "/review", json=body).json()["revision"] == 1
    assert tasks.get_task("task-one") is None
    created = task(tasks, receipt)
    link = {"expected_hash": receipt["content_hash"], "expected_revision": 1, "task_id": created["task_id"]}
    assert client.post(path + "/task", json=link).json()["work_id"] == "task-one"
    assert client.get(path + "/review").json()["state"] == "LINKED"
    other = client_for(workflow, "other")
    assert other.get(path + "/review").status_code == 404
    assert other.put(path + "/review", json=body).status_code == 404
    assert other.post(path + "/task", json=link).status_code == 404


@pytest.mark.parametrize("change", [
    {"principal_id": "other"}, {"expected_revision": True},
    {"state": "READY", "candidate": None}, {"state": "HOLD", "candidate": GOAL},
    {"reason": " "}, {"candidate": {**GOAL, "x": True}},
])
def test_invalid_review_body_is_rejected_before_mutation(tmp_path, change):
    workflow, _, _, _, receipt = fixture(tmp_path)
    client = client_for(workflow, "op")
    body = {"expected_hash": receipt["content_hash"], "expected_revision": 0,
            "state": "READY", "candidate": GOAL, "reason": "confirmed original request"}
    body.update(change)
    assert client.put(f"/api/fleet/channel-requests/{receipt['request_id']}/review", json=body).status_code == 422
    assert workflow.read(receipt["request_id"], "op")["revision"] == 0


def test_submit_route_reuses_task_owner_and_rejects_stale_review(tmp_path):
    from fleet.server.task_service import FleetTaskService
    workflow, _, tasks, _, receipt = fixture(tmp_path)
    service = FleetTaskService(tasks, robot_ids={"pinky"})
    client = client_for(workflow, "op", service)
    path = f"/api/fleet/channel-requests/{receipt['request_id']}"
    body = {"expected_hash": receipt["content_hash"], "expected_revision": 0,
            "state": "READY", "candidate": GOAL, "reason": "confirmed"}
    assert client.put(path + "/review", json=body).status_code == 200
    assert client.post(path + "/submit", json={"expected_hash": receipt["content_hash"],
                                               "expected_revision": 0}).status_code == 409
    submission = {"expected_hash": receipt["content_hash"], "expected_revision": 1}
    assert client_for(workflow, "other", service).post(path + "/submit", json=submission).status_code == 404
    first = client.post(path + "/submit", json=submission)
    assert first.status_code == 200 and first.json()["work_status"] == "QUEUED"
    assert client.post(path + "/submit", json=submission).json()["work_id"] == first.json()["work_id"]
    from contextlib import closing
    with closing(tasks._connect()) as conn:
        assert conn.execute("SELECT request_key FROM fleet_tasks WHERE task_id=?",
                            (first.json()["work_id"],)).fetchone()[0] == "discord-" + receipt["request_id"]


def test_submit_route_refuses_a_robot_on_a_trip_before_a_task_is_queued(tmp_path):
    """D-763 slice 1: the submit route asks the one holder check and keeps its plain-string 409."""
    from fleet.server.console_view import TripAware
    from fleet.server.task_service import FleetTaskService

    class OnTrip(TripAware):
        trip_busy = staticmethod(lambda robot_id: robot_id == "pinky")

    workflow, _, tasks, _, receipt = fixture(tmp_path)
    client = client_for(workflow, "op", FleetTaskService(tasks, robot_ids={"pinky"}), OnTrip())
    path = f"/api/fleet/channel-requests/{receipt['request_id']}"
    assert client.put(path + "/review", json={"expected_hash": receipt["content_hash"], "expected_revision": 0,
                                             "state": "READY", "candidate": GOAL, "reason": "confirmed"}).status_code == 200
    refused = client.post(path + "/submit", json={"expected_hash": receipt["content_hash"], "expected_revision": 1})
    assert (refused.status_code, refused.json()) == (409, {"detail": "TRIP_ROBOT_BUSY"})
    assert not tasks.queued_task_ids()
