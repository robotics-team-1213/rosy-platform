from hashlib import sha256

from fastapi.testclient import TestClient
import pytest

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint
from test_control_unit_runtime import config_file


def application(tmp_path, share):
    console = FleetConsole([RobotEndpoint("a1", "http://robot.invalid", "device-token")], [FakeRobot("a1")])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.db"), robot_ids=console.robot_ids)
    users = {sha256(token.encode()).hexdigest(): {"principal_id": identity, "role": role}
             for token, identity, role in [
                 ("human-token", "operator-a1", "operator"),
                 ("viewer-token", "viewer-a1", "viewer"),
                 ("parent-token", "control-unit:A", "service"),
                 ("sibling-token", "control-unit:B", "service")
             ]}
    return create_app(console, task_service=tasks, site_users=users, start_task_dispatcher=False,
                      control_unit_config=config_file(tmp_path, share_information_with_parent=share))


@pytest.mark.parametrize("share", [False, True])
@pytest.mark.parametrize("token,allowed", [
    ("human-token", True), ("viewer-token", True), ("parent-token", None),
    ("sibling-token", False), (None, False),
])
def test_information_requires_local_viewer_or_explicit_direct_parent_grant(tmp_path, share, token, allowed):
    app = application(tmp_path, share)
    expected = 401 if token is None else 200 if (share if allowed is None else allowed) else 403
    headers = {"Authorization": "Bearer " + token} if token else {}
    with TestClient(app) as client:
        for path in ["overview", "units/A1"]:
            response = client.get("/api/fleet/control-unit/" + path, headers=headers)
            assert response.status_code == expected, response.text
            assert "parent.invalid" not in response.text and "service-token" not in response.text
        if expected == 200:
            detail = client.get("/api/fleet/control-unit/units/A1", headers=headers).json()
            assert detail["unit_id"] == "A1" and [r["robot_id"] for r in detail["robots"]] == ["a1"]
            assert detail["sampled_at"] is not None
            assert client.get("/api/fleet/control-unit/units/R", headers=headers).status_code == 404
            assert client.get("/api/fleet/control-unit/units/A1/map", headers=headers).status_code == 404


def test_information_scope_never_exposes_parent_or_sibling_to_parent_service(tmp_path):
    with TestClient(application(tmp_path, True)) as client:
        headers = {"Authorization": "Bearer parent-token"}
        response = client.get("/api/fleet/control-unit/overview", headers=headers)
        assert response.status_code == 200
        assert [r["unit_id"] for r in response.json()["units"]] == ["A1"]
        for unit_id in ["R", "A", "B", "unknown"]:
            assert client.get("/api/fleet/control-unit/units/" + unit_id, headers=headers).status_code == 404
