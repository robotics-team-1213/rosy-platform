"""Only the authenticated mapped owner can review and link channel requests."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet.server.channel_workflow import install_workflow_routes
from fleet.server.site_auth import SitePrincipal
from test_channel_workflow import fixture, GOAL, task


def client_for(workflow, principal):
    app = FastAPI()
    install_workflow_routes(app, workflow, require_operator=lambda: SitePrincipal(principal, "operator"),
                            read_guard=[])
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
