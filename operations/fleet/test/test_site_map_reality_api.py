"""The map reality check over HTTP: judge the map on the drive, then move the draft onto it."""

from __future__ import annotations

from hashlib import sha256

from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.site_map import SiteMap
from fleet.swarm.robots import RobotEndpoint

OPERATOR = {"Authorization": "Bearer operator-token"}
VIEWER = {"Authorization": "Bearer viewer-token"}
ROBOT = "rosy_60"
W = 0.2


def _map_body() -> dict:
    return SiteMap(
        map_id="site",
        places=[{"id": "A", "name": "A", "x": 0, "y": 0, "yaw": 0.0, "kind": "start"},
                {"id": "B", "name": "B", "x": 6, "y": 0, "kind": "junction"},
                {"id": "C", "name": "C", "x": 12, "y": 0, "kind": "junction"}],
        edges=[{"id": "ab", "from": "A", "to": "B", "polyline": [[0, 0], [6, 0]],
                "width_m": W, "speed_cap_mps": 1.0},
               {"id": "bc", "from": "B", "to": "C", "polyline": [[6, 0], [12, 0]],
                "width_m": W, "speed_cap_mps": 1.0}]).body()


def _client(tmp_path) -> TestClient:
    robot = FakeRobot(ROBOT, state={"robot_id": ROBOT, "mode": "IDLE"})
    console = FleetConsole([RobotEndpoint(ROBOT, "http://127.0.0.1:8080", "t")], [robot])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids={ROBOT})
    users = {sha256(b"operator-token").hexdigest(): {"principal_id": "bob", "role": "operator"},
             sha256(b"viewer-token").hexdigest(): {"principal_id": "vic", "role": "viewer"}}
    return TestClient(create_app(console, task_service=tasks, site_users=users))


def _save_draft(client: TestClient) -> dict:
    response = client.put("/api/fleet/site-map/draft", json={"map": _map_body()}, headers=OPERATOR)
    assert response.status_code == 200, response.text
    return response.json()


def _seed_drive(client: TestClient, *, y: float = 0.0, x0: float = 0.0, x1: float = 12.0) -> None:
    """D-594 rows as the recorder would have written them (a dense track in the map frame)."""
    recorder = client.app.state.paths
    until = recorder.wall()
    count = int((x1 - x0) / 0.1)
    recorder.store.append([{"robot_id": ROBOT, "t": until - 60.0 + 0.1 * k,
                            "x": x0 + (x1 - x0) * k / count, "y": y, "state": "LOCALIZED",
                            "source": "robot", "seg": 1, "map_id": "site",
                            "trip_id": None, "formation_id": None} for k in range(count + 1)])


def test_a_drive_on_the_draft_lanes_reports_a_match(tmp_path):
    client = _client(tmp_path)
    revision = _save_draft(client)["revision"]
    _seed_drive(client)

    response = client.get("/api/fleet/site-map/reality-check", headers=OPERATOR)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verdict"] == "match"
    assert body["map"] == {"source": "draft", "revision": revision}
    assert body["evidence"]["robots"] == [ROBOT]
    assert body["fit"]["accepted"] is False


def test_a_viewer_cannot_apply_a_correction(tmp_path):
    client = _client(tmp_path)
    revision = _save_draft(client)["revision"]
    _seed_drive(client, y=0.4)

    response = client.post("/api/fleet/site-map/reality-check/apply",
                           json={"expected_revision": revision}, headers=VIEWER)

    assert response.status_code == 403, response.text


def test_apply_moves_the_draft_onto_the_drive(tmp_path):
    client = _client(tmp_path)
    revision = _save_draft(client)["revision"]
    _seed_drive(client, y=0.4)
    assert client.get("/api/fleet/site-map/reality-check", headers=OPERATOR).json()["verdict"] == "offset"

    response = client.post("/api/fleet/site-map/reality-check/apply",
                           json={"expected_revision": revision}, headers=OPERATOR)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["report"]["fit"]["accepted"] is True
    assert body["draft"]["revision"] != revision
    places = {place["id"]: place for place in body["draft"]["map"]["places"]}
    assert abs(places["A"]["y"] - 0.4) < 0.01 and abs(places["B"]["y"] - 0.4) < 0.01
    after = client.get("/api/fleet/site-map/reality-check", headers=OPERATOR).json()
    assert after["verdict"] == "match"
    assert after["fit"]["accepted"] is False
    assert any(event["action"] == "reality_corrected" for event in client.app.state.site_maps.events())


def test_apply_refuses_a_stale_revision(tmp_path):
    client = _client(tmp_path)
    revision = _save_draft(client)["revision"]
    _seed_drive(client, y=0.4)
    client.put("/api/fleet/site-map/draft", json={"map": _map_body(), "expected_revision": revision},
               headers=OPERATOR)

    response = client.post("/api/fleet/site-map/reality-check/apply",
                           json={"expected_revision": revision}, headers=OPERATOR)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SITE_MAP_DRAFT_CHANGED"


def test_apply_refuses_without_a_draft(tmp_path):
    client = _client(tmp_path)
    _seed_drive(client, y=0.4)

    response = client.post("/api/fleet/site-map/reality-check/apply",
                           json={"expected_revision": "none"}, headers=OPERATOR)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SITE_MAP_NO_DRAFT"


def test_apply_refuses_when_the_drive_does_not_give_a_correction(tmp_path):
    client = _client(tmp_path)
    revision = _save_draft(client)["revision"]

    response = client.post("/api/fleet/site-map/reality-check/apply",
                           json={"expected_revision": revision}, headers=OPERATOR)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "SITE_MAP_NO_CORRECTION"
    assert "no robot drive" in detail["detail"]["message"]
