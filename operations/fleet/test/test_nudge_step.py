"""The Fleet step route forwards an operator's 앞으로/뒤로 to CORE's nudge mission (D-2)."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import RobotApiError

OPERATOR, NAMED, VIEWER = "operator-secret", "named-secret", "viewer-secret"


def _users():
    from hashlib import sha256
    return {sha256(NAMED.encode()).hexdigest(): {"principal_id": "kim", "role": "operator"},
            sha256(VIEWER.encode()).hexdigest(): {"principal_id": "viewer-1", "role": "viewer"}}


def _app(tmp_path):
    robot = FakeRobot("r1", state={"robot_id": "r1"})
    console = FleetConsole([RobotEndpoint("r1", "http://127.0.0.1:8080", "robot-rest")], [robot])
    task_service = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids={"r1"})
    return create_app(console, console_token=OPERATOR, task_service=task_service,
                      start_task_dispatcher=False, site_users=_users()), robot


def _post(client, body=None, token=NAMED, robot="r1"):
    return client.post(f"/api/fleet/robots/{robot}/step",
                       json=body if body is not None else {"direction": "backward"},
                       headers={"Authorization": f"Bearer {token}"})


def test_a_step_needs_a_named_operator(tmp_path):
    app, robot = _app(tmp_path)
    with TestClient(app) as client:
        assert _post(client, token=OPERATOR).status_code in (401, 403)   # the shared token is not named
        assert _post(client, token=VIEWER).status_code == 403
        reply = _post(client)
        assert reply.status_code == 200, reply.text
        assert reply.json() == {"kind": "nudge_backward", "state": "running", "reason": None}
    assert robot.missions == [("nudge_backward", 0.10, pytest.approx(0.10 / 0.03 + 5.0), None)]


def test_a_forward_step_with_a_distance(tmp_path):
    app, robot = _app(tmp_path)
    with TestClient(app) as client:
        reply = _post(client, {"direction": "forward", "distance_m": 0.05})
        assert reply.status_code == 200
        assert reply.json()["kind"] == "nudge_forward"
    assert robot.missions == [("nudge_forward", 0.05, pytest.approx(0.05 / 0.03 + 5.0), None)]


def test_bad_direction_or_distance_is_rejected(tmp_path):
    app, _robot = _app(tmp_path)
    with TestClient(app) as client:
        assert _post(client, {"direction": "sideways"}).status_code == 422
        assert _post(client, {"direction": "forward", "distance_m": 0.0}).status_code == 422
        assert _post(client, {"direction": "forward", "distance_m": 0.11}).status_code == 422
        assert _post(client, {"direction": "forward", "distance_m": -0.05}).status_code == 422
        assert _post(client, {}).status_code == 422
        assert _post(client, robot="nope").status_code == 404


def test_a_busy_robot_is_refused(tmp_path, monkeypatch):
    from fleet.server.trip_runner import TripRunner
    monkeypatch.setattr(TripRunner, "robot_busy", lambda self, robot_id: True)
    app, robot = _app(tmp_path)
    with TestClient(app) as client:
        reply = _post(client)
        assert reply.status_code == 409 and reply.json()["detail"]["code"] == "STEP_ROBOT_BUSY"
    assert robot.missions == []

    app, robot = _app(tmp_path)          # a console holder (a formation) refuses the same way
    monkeypatch.setattr("fleet.server.nudge_routes.engaged", lambda console, robot_id: "formation")
    with TestClient(app) as client:
        reply = _post(client)
        assert reply.status_code == 409 and reply.json()["detail"]["code"] == "STEP_ROBOT_BUSY"
        assert "formation" in reply.json()["detail"]["message"]
    assert robot.missions == []


def test_core_refusals_pass_through_and_offline_is_a_409(tmp_path):
    app, robot = _app(tmp_path)
    with TestClient(app) as client:
        robot.mission_error = RobotApiError("r1", 409, "path_not_clear", "rear clearance 0.08 m")
        refused = _post(client)
        assert refused.status_code == 502, refused.text
        assert refused.json()["detail"]["code"] == "path_not_clear"
        robot.mission_error = httpx.ConnectError("refused")
        offline = _post(client)
        assert offline.status_code == 409 and offline.json()["detail"]["code"] == "ROBOT_OFFLINE"
    assert robot.missions == []


def test_a_step_is_a_site_map_event(tmp_path):
    app, _robot = _app(tmp_path)
    with TestClient(app) as client:
        assert _post(client).status_code == 200
    events = [e for e in app.state.site_maps.events() if e["action"] == "step"]
    assert events and events[0]["principal_id"] == "kim"
    assert events[0]["detail"]["robot_id"] == "r1"
    assert events[0]["detail"]["kind"] == "nudge_backward"
