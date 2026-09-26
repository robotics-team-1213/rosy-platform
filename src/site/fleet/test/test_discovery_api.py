"""The host scanner has write-only discovery access, separate from Fleet users."""

from fastapi.testclient import TestClient
from argparse import Namespace

import uvicorn

from fakes import FakeRobot
from fleet import cli
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.discovery import DiscoveryStore
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.robots import write_robots
from core_common.protocol.schemas import Envelope, EnvelopeType, HelloPayload


def test_scanner_token_cannot_read_or_issue_a_goal_and_viewer_cannot_scan():
    endpoint = RobotEndpoint("rosy_01", "http://192.168.1.10:8080", "rest")
    console = FleetConsole([endpoint], [FakeRobot("rosy_01")])
    app = create_app(console, console_token="viewer", discovery=DiscoveryStore(),
                     discovery_token="scanner")
    client = TestClient(app)
    scan = {"devices": [{"name": "rosy-a", "address": "192.168.1.10", "port": 8080,
                         "network": "sta", "stage": "CORE_READY"}]}
    assert client.post("/api/fleet/discovery/scan", json=scan).status_code == 401
    assert client.post("/api/fleet/discovery/scan", json=scan,
                       headers={"Authorization": "Bearer viewer"}).status_code == 401
    assert client.post("/api/fleet/discovery/scan", json=scan,
                       headers={"Authorization": "Bearer scanner"}).status_code == 200
    assert client.get("/api/fleet/discovery", headers={"Authorization": "Bearer scanner"}).status_code == 401
    assert client.post("/api/fleet/robots/rosy_01/goal", json={"x": 1, "y": 1},
                       headers={"Authorization": "Bearer scanner"}).status_code == 401
    body = client.get("/api/fleet/discovery",
                      headers={"Authorization": "Bearer viewer"}).json()
    assert body["devices"][0]["status"] == "pairing_pending"


def test_discovery_api_does_not_expose_robot_or_scanner_tokens():
    endpoint = RobotEndpoint("rosy_01", "http://192.168.1.10:8080", "rest-secret",
                             "pair-secret")
    console = FleetConsole([endpoint], [FakeRobot("rosy_01")])
    client = TestClient(create_app(console, console_token="viewer-secret",
                                   discovery=DiscoveryStore(), discovery_token="scanner-secret"))
    response = client.get("/api/fleet/discovery",
                          headers={"Authorization": "Bearer viewer-secret"})
    assert response.status_code == 200
    assert all(secret not in response.text for secret in
               ("rest-secret", "pair-secret", "scanner-secret"))


def test_cli_enables_discovery_only_with_dedicated_environment_token(tmp_path, monkeypatch):
    robots = tmp_path / "robots.yaml"
    write_robots(robots, [RobotEndpoint("rosy_01", "http://192.168.1.10:8080", "rest")])
    captured = {}
    monkeypatch.setenv("ROSY_SITE_DISCOVERY_TOKEN", "scanner-secret")
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: captured.update(app=app))
    cli.run_console(Namespace(host="127.0.0.1", port=8090, robots=robots,
                              signals=None, token="viewer-secret", web_common=None,
                              discovery_token_env="ROSY_SITE_DISCOVERY_TOKEN"))
    response = TestClient(captured["app"]).get("/api/fleet/discovery",
                                               headers={"Authorization": "Bearer viewer-secret"})
    assert response.status_code == 200
    assert response.json() == {"devices": [], "scanner_online": False}


def test_authenticated_hello_promotes_only_the_matching_discovery_row():
    endpoint = RobotEndpoint("rosy_01", "http://rosy-a.local:8080", "rest", "pair")
    console = FleetConsole([endpoint], [FakeRobot("rosy_01")])
    client = TestClient(create_app(console, console_token="viewer", hub=console.hub,
                                   discovery=DiscoveryStore(), discovery_token="scanner"))
    scan = {"devices": [{"name": "rosy-a", "hostname": "rosy-a.local",
                         "address": "192.168.1.10", "port": 8080,
                         "network": "sta", "stage": "CORE_READY"}]}
    assert client.post("/api/fleet/discovery/scan", json=scan,
                       headers={"Authorization": "Bearer scanner"}).status_code == 200
    before = client.get("/api/fleet/discovery",
                        headers={"Authorization": "Bearer viewer"}).json()
    assert before["devices"][0]["status"] == "pairing_pending"
    hello = HelloPayload(robot_id="rosy_01", pairing_token="pair", device_uid="uid-a",
                         device_name="rosy-a")
    assert console.hub.handle(Envelope(type=EnvelopeType.HELLO,
                                       payload=hello.model_dump())).type is EnvelopeType.WELCOME
    after = client.get("/api/fleet/discovery",
                       headers={"Authorization": "Bearer viewer"}).json()
    assert after["devices"][0]["status"] == "verified_online"
