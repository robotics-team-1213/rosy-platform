"""D-512 display half: tether circles are read by viewers and set or cleared by a named operator."""
from hashlib import sha256

from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint

OPERATOR = {"Authorization": "Bearer operator-token"}
VIEWER = {"Authorization": "Bearer viewer-token"}
BODY = {"anchor_xy": [1.0, -0.5], "radius_m": 0.8}
URL = "/api/fleet/robots/rosy_60/tether"


def _client(tmp_path, raise_server_exceptions=True):
    console = FleetConsole([RobotEndpoint("rosy_60", "http://127.0.0.1:8080", "t")], [FakeRobot("rosy_60")])
    users = {sha256(b"operator-token").hexdigest(): {"principal_id": "bob", "role": "operator"},
             sha256(b"viewer-token").hexdigest(): {"principal_id": "vic", "role": "viewer"}}
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids={"rosy_60"})
    return TestClient(create_app(console, task_service=tasks, site_users=users, start_task_dispatcher=False),
                      raise_server_exceptions=raise_server_exceptions)


def test_tether_needs_a_named_operator_and_set_is_idempotent(tmp_path):
    with _client(tmp_path) as client:
        assert client.get("/api/fleet/tethers").status_code == 401
        assert client.post(URL, json=BODY).status_code == 401
        assert client.post(URL, json=BODY, headers=VIEWER).status_code == 403
        assert client.delete(URL, headers=VIEWER).status_code == 403
        first = client.post(URL, json=BODY, headers=OPERATOR)
        again = client.post(URL, json=BODY, headers=OPERATOR)
        assert first.status_code == again.status_code == 200 and first.json() == again.json()
        row = {"robot_id": "rosy_60", "anchor_xy": [1.0, -0.5], "radius_m": 0.8, "set_by": "bob"}
        assert client.get("/api/fleet/tethers", headers=VIEWER).json() == {"tethers": [row]}
        assert client.delete(URL, headers=OPERATOR).json() == {"robot_id": "rosy_60", "cleared": True}
        assert client.delete(URL, headers=OPERATOR).json() == {"robot_id": "rosy_60", "cleared": False}
        assert client.get("/api/fleet/tethers", headers=VIEWER).json() == {"tethers": []}


def test_tether_rejects_unknown_robots_and_bad_circles(tmp_path):
    with _client(tmp_path, raise_server_exceptions=False) as client:
        unknown = client.post("/api/fleet/robots/ghost/tether", json=BODY, headers=OPERATOR)
        assert unknown.status_code == 404 and unknown.json()["detail"]["code"] == "UNKNOWN_ROBOT"
        for bad in ({**BODY, "radius_m": 0}, {**BODY, "radius_m": 51}, {**BODY, "anchor_xy": [1.0]},
                    {**BODY, "anchor_xy": [True, 0.0]}, {**BODY, "extra": 1}):
            assert client.post(URL, json=bad, headers=OPERATOR).status_code == 422, bad
        # Non-JSON NaN is refused (the app's default 422 echo cannot encode it, so it surfaces as 500).
        nan = client.post(URL, content='{"anchor_xy": [NaN, 0], "radius_m": 1}', headers={
            **OPERATOR, "Content-Type": "application/json"})
        assert nan.status_code >= 400
        assert client.get("/api/fleet/tethers", headers=VIEWER).json() == {"tethers": []}
