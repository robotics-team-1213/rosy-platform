"""D-454 1단계 — 중앙 레지스트리 뷰(API Ref §10.1 읽기 2경로) 계약.

로스터가 정본이고 hub·발견은 보강이다. Fleet은 상태를 다시 계산하지 않는다(D-309) —
스냅샷의 증거 필드가 그대로 흐른다. 네트워크 없음, 가짜 객체만.
"""

from __future__ import annotations

import base64
from hashlib import sha256

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from core_common.protocol.schemas import StateSnapshot
from fakes import FakeClock, FakeRobot
from fleet.server.app import create_app
from fleet.server.central_registry import CentralRegistry
from fleet.server.central_registry_routes import install_central_registry_routes
from fleet.server.console import FleetConsole
from fleet.server.discovery import DiscoveryStore
from fleet.server.roster import SiteRoster
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint, write_robots


def _registry():
    endpoint = RobotEndpoint("rosy_01", "http://10.0.0.7:8080", "fixture-token")
    console = FleetConsole([endpoint], [FakeRobot("rosy_01")])
    roster = SiteRoster(console)
    for index in (2, 3):
        rid = f"rosy_0{index}"
        roster.add(RobotEndpoint(rid, f"http://10.0.0.{index + 6}:8080", "fixture-token"),
                   FakeRobot(rid))
    record = console.hub.registry.record("rosy_01")
    record.online = True
    record.snapshot = StateSnapshot(robot_id="rosy_01", mode="NAVIGATION")
    console.hub.registry.record("rosy_02").snapshot = StateSnapshot(robot_id="rosy_02")
    discovery = DiscoveryStore(clock=FakeClock())
    discovery.replace_scan([{"name": "rosy_01", "hostname": "rosy-01.local",
                             "address": "10.0.0.7", "port": 8080}])
    return CentralRegistry(roster, console=console, discovery=discovery)


def test_rows_merge_roster_hub_and_discovery_in_id_order():
    rows = _registry().rows()
    assert [row["robot_id"] for row in rows] == ["rosy_01", "rosy_02", "rosy_03"]
    first, second, third = rows
    assert first["source"] == "static" and first["online"] is True
    assert first["state"]["mode"] == "NAVIGATION"
    assert first["address_last_seen"] == "10.0.0.7"
    assert second["source"] == "enrolled" and second["online"] is False
    assert third["state"] is None and third["capabilities"] is None


def test_row_passes_robot_made_evidence_without_recomputation():
    registry = _registry()
    original = registry._console.hub.registry.find("rosy_01").snapshot.model_dump(mode="json")
    assert registry.row("rosy_01")["state"] == original


def test_unknown_robot_is_none_roster_is_source_of_truth():
    assert _registry().row("rosy_99") is None


@pytest.fixture
def client():
    app = FastAPI()
    install_central_registry_routes(app, _registry(),
                                    require_viewer=lambda: "viewer")
    return TestClient(app)


def test_list_and_detail_round_trip(client):
    body = client.get("/api/v1/fleet/robots").json()
    assert [row["robot_id"] for row in body["robots"]] == ["rosy_01", "rosy_02", "rosy_03"]
    detail = client.get("/api/v1/fleet/robots/rosy_02").json()
    assert detail["source"] == "enrolled" and detail["online"] is False


def test_unknown_robot_detail_is_404_unknown_robot(client):
    response = client.get("/api/v1/fleet/robots/rosy_99")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "UNKNOWN_ROBOT"


def test_viewer_role_is_required():
    def refuse():
        raise HTTPException(status_code=401, detail={"code": "UNAUTHENTICATED"})

    app = FastAPI()
    install_central_registry_routes(app, _registry(), require_viewer=refuse)
    unauth = TestClient(app)
    assert unauth.get("/api/v1/fleet/robots").status_code == 401


def test_dynamic_approved_roster_membership_is_live_and_unknown_hints_do_not_enroll():
    registry = _registry()
    registry._discovery.replace_scan([{"name": "unknown", "hostname": "unknown.local",
                                      "address": "10.0.0.99", "port": 8080}])
    assert registry.row("unknown") is None
    registry._roster.add(RobotEndpoint("new-owner", "http://10.0.0.10:8080", "fixture-token"),
                         FakeRobot("new-owner"))
    assert registry.row("new-owner")["source"] == "enrolled"
    assert [row["robot_id"] for row in registry.rows()] == ["new-owner", "rosy_01", "rosy_02", "rosy_03"]
    assert all(not robot.calls for robot in registry._console._clients.values())


def test_expired_and_conflicting_discovery_never_claim_an_owner_address():
    registry = _registry()
    assert registry.row("rosy_01")["address_last_seen"] == "10.0.0.7"
    registry._discovery._clock.advance(46)
    assert registry.row("rosy_01")["address_last_seen"] is None
    registry._discovery.replace_scan([
        {"name": "rosy_01", "hostname": "rosy-01.local", "address": address, "port": 8080}
        for address in ("10.0.0.7", "10.0.0.9")])
    assert registry.row("rosy_01")["address_last_seen"] is None
    assert registry._console.registered_endpoints["rosy_01"] == "http://10.0.0.7:8080"


def test_real_app_mount_uses_existing_named_viewer_guard_for_both_read_paths(tmp_path):
    registry = _registry()
    token = "fixture-viewer"
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"),
                             robot_ids=set(registry._roster.robot_ids))
    app = create_app(registry._console, central_registry=registry, task_service=tasks,
                     site_users={sha256(token.encode()).hexdigest(): {"principal_id": "viewer-1", "role": "viewer"}})
    client = TestClient(app)
    for path in ("/api/v1/fleet/robots", "/api/v1/fleet/robots/rosy_01"):
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert client.get("/api/v1/fleet/robots/not-approved",
                      headers={"Authorization": f"Bearer {token}"}).status_code == 404
    assert all(not robot.calls for robot in registry._console._clients.values())


def test_default_site_profile_does_not_mount_central_routes():
    registry = _registry()
    client = TestClient(create_app(registry._console))
    assert client.get("/api/v1/fleet/robots").status_code == 404
    assert client.get("/api/v1/fleet/robots/rosy_01").status_code == 404


def test_real_app_central_delete_is_unmounted_and_cannot_mutate_approved_roster(tmp_path):
    registry = _registry()
    token = "fixture-operator"
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"),
                             robot_ids=set(registry._roster.robot_ids))
    app = create_app(registry._console, central_registry=registry, task_service=tasks,
                     site_users={sha256(token.encode()).hexdigest(): {
                         "principal_id": "operator-1", "role": "operator"}})
    assert not any("DELETE" in (getattr(route, "methods", None) or set())
                   and route.path == "/api/v1/fleet/robots/{robot_id}" for route in app.routes)
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}
    before_rows = registry.rows()
    before_endpoints = dict(registry._console.registered_endpoints)
    before_clients = dict(registry._console._clients)
    for request_headers in ({}, headers):
        for robot_id in ("rosy_01", "rosy_02", "not-approved"):
            response = client.delete(f"/api/v1/fleet/robots/{robot_id}", headers=request_headers)
            assert response.status_code == 405
    assert client.get("/api/v1/fleet/robots", headers=headers).json() == {"robots": before_rows}
    assert registry._roster.robot_ids == ["rosy_01", "rosy_02", "rosy_03"]
    assert registry._console.registered_endpoints == before_endpoints
    assert registry._console._clients == before_clients
    assert all(not robot.calls for robot in before_clients.values())


def test_central_cli_wires_actual_roster_without_starting_listener(tmp_path, monkeypatch):
    from fleet import cli
    robots = tmp_path / "robots.yaml"
    write_robots(robots, [RobotEndpoint("seed", "http://10.0.0.7:8080", "fixture-token")])
    key = tmp_path / "credential-key"
    key.write_bytes(base64.b64encode(b"x" * 32))
    mounted = []
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: mounted.append(app))
    args = cli.parse_args(["console", "--central", "--robots", str(robots),
                          "--robot-credential-key-file", str(key), "--tasks-db", str(tmp_path / "fleet.sqlite3")])
    cli.run_console(args)
    response = TestClient(mounted[0]).get("/api/v1/fleet/robots")
    assert response.status_code == 200
    assert response.json()["robots"][0]["robot_id"] == "seed"
    assert response.json()["robots"][0]["source"] == "static"


def test_central_cli_missing_store_names_existing_configuration_flags(tmp_path):
    from fleet import cli
    robots = tmp_path / "robots.yaml"
    write_robots(robots, [RobotEndpoint("seed", "http://10.0.0.7:8080", "fixture-token")])
    args = cli.parse_args(["console", "--central", "--robots", str(robots)])
    with pytest.raises(SystemExit, match="--robot-credential-key-file and --tasks-db"):
        cli.run_console(args)
