"""GET /api/fleet/discovery/addresses: viewer reads why a pinned robot is unreachable."""

from __future__ import annotations

import logging
from hashlib import sha256

from fastapi.testclient import TestClient

from enrollment_fakes import AUTH, CODE, ISSUED, NAME, PINNED, FakeCore, build, scan_row
from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.discovery import DiscoveryStore
from fleet.swarm.robots import RobotEndpoint

OPERATOR = "op-" + "secret-2"
VIEWER = "view-" + "secret-2"
DISCOVERY = "disc-" + "secret-2"
RENUMBERED = "10.16.36.20:8080"


def _headers(token: str) -> dict:
    return {AUTH: "Bearer " + token}


def _users() -> dict:
    return {sha256(OPERATOR.encode()).hexdigest(): {"principal_id": "alice", "role": "operator"},
            sha256(VIEWER.encode()).hexdigest(): {"principal_id": "vic", "role": "viewer"}}


def _enrolled_app(tmp_path):
    service, network, console, discovery, store, tasks = build(
        tmp_path, {PINNED: FakeCore(), RENUMBERED: FakeCore()}, static=(FakeRobot("rosy_01"),))
    discovery.replace_scan([scan_row()])
    app = create_app(console, task_service=tasks, start_task_dispatcher=False,
                     site_users=_users(), enrollment=service, discovery=discovery,
                     discovery_token=DISCOVERY)
    client = TestClient(app)
    created = client.post("/api/fleet/enrollment/robots", headers=_headers(OPERATOR),
                          json={"discovery_name": NAME, "code": CODE})
    assert created.status_code == 201, created.text
    return client, store


def _by_id(body):
    return {entry["robot_id"]: entry for entry in body["robots"]}


def test_viewer_reads_address_reasons_after_the_site_renumbers(tmp_path):
    client, store = _enrolled_app(tmp_path)
    assert client.get("/api/fleet/discovery/addresses").status_code == 401
    before = client.get("/api/fleet/discovery/addresses", headers=_headers(VIEWER))
    assert before.status_code == 200
    assert _by_id(before.json())["rosy_09"]["status"] == "in_scanned_subnet"

    accepted = client.post("/api/fleet/discovery/scan", headers=_headers(DISCOVERY),
                           json={"devices": [scan_row(RENUMBERED)]})
    assert accepted.status_code == 200
    response = client.get("/api/fleet/discovery/addresses", headers=_headers(VIEWER))
    body = response.json()
    entries = _by_id(body)
    assert entries["rosy_09"]["status"] == "seen_at_other_address"
    assert entries["rosy_09"]["seen_addresses"] == [RENUMBERED]
    assert entries["rosy_09"]["origin"] == "enrolled"
    assert entries["rosy_09"]["movable"] is True
    assert entries["rosy_01"]["origin"] == "static"
    assert entries["rosy_01"]["status"] == "outside_scanned_subnets"
    assert body["all_outside"] is True
    assert body["scanner_state"] == "online"
    for secret in (ISSUED, CODE, "rest-0", OPERATOR, DISCOVERY):
        assert secret not in response.text
    assert store.get("rosy_09")["address"] == PINNED  # nothing followed the new address


def test_scanner_offline_reads_unknown():
    endpoint = RobotEndpoint("rosy_01", "http://192.168.1.10:8080", "rest")
    console = FleetConsole([endpoint], [FakeRobot("rosy_01")])
    client = TestClient(create_app(console, console_token="viewer", discovery=DiscoveryStore(),
                                   discovery_token="scanner"))
    body = client.get("/api/fleet/discovery/addresses",
                      headers={"Authorization": "Bearer viewer"}).json()
    assert body["scanner_state"] == "never_seen"
    assert _by_id(body)["rosy_01"]["status"] == "unknown"
    assert body["all_outside"] is False


def test_static_robot_outside_every_subnet_is_logged_once(caplog):
    endpoint = RobotEndpoint("rosy_01", "http://192.168.1.10:8080", "rest")
    console = FleetConsole([endpoint], [FakeRobot("rosy_01")])
    client = TestClient(create_app(console, console_token="viewer", discovery=DiscoveryStore(),
                                   discovery_token="scanner"))
    scan = {"devices": [{"name": "rosy-x", "address": "10.16.36.20", "port": 8080,
                         "network": "sta"}]}
    with caplog.at_level(logging.WARNING, logger="fleet.server.ingest_routes"):
        for _ in range(2):
            assert client.post("/api/fleet/discovery/scan", json=scan,
                               headers={"Authorization": "Bearer scanner"}).status_code == 200
    warnings = [r.getMessage() for r in caplog.records if "rosy_01" in r.getMessage()]
    assert len(warnings) == 1
    assert "outside every scanned subnet" in warnings[0]
    assert "192.168.1.10" in warnings[0]


def test_static_local_name_gets_a_suggestion_not_a_resolution(caplog):
    endpoint = RobotEndpoint("rosy_01", "http://rosy-a.local:8080", "rest")
    console = FleetConsole([endpoint], [FakeRobot("rosy_01")])
    client = TestClient(create_app(console, console_token="viewer", discovery=DiscoveryStore(),
                                   discovery_token="scanner"))
    scan = {"devices": [{"name": "rosy-a", "hostname": "rosy-a.local", "address": "10.16.36.20",
                         "port": 8080, "network": "sta"}]}
    with caplog.at_level(logging.WARNING, logger="fleet.server.ingest_routes"):
        client.post("/api/fleet/discovery/scan", json=scan,
                    headers={"Authorization": "Bearer scanner"})
    entry = _by_id(client.get("/api/fleet/discovery/addresses",
                              headers={"Authorization": "Bearer viewer"}).json())["rosy_01"]
    assert entry["status"] == "seen_at_other_address"
    assert entry["pinned"] == "rosy-a.local:8080"
    assert entry["pinned_is_name"] is True
    assert entry["seen_addresses"] == [RENUMBERED]
    assert entry["movable"] is False
    assert console.registered_endpoints["rosy_01"] == "http://rosy-a.local:8080"
    assert any("rosy_01" in r.getMessage() and "10.16.36.20:8080" in r.getMessage()
               for r in caplog.records)


def test_console_serves_the_address_module_and_wires_the_banner():
    endpoint = RobotEndpoint("rosy_01", "http://192.168.1.10:8080", "rest")
    console = FleetConsole([endpoint], [FakeRobot("rosy_01")])
    client = TestClient(create_app(console, console_token="viewer"))
    module = client.get("/console/assets/address-drift.js")
    assert module.status_code == 200
    assert "export function addressReason" in module.text
    page = client.get("/console").text
    assert 'id="address-banner"' in page and 'role="alert"' in page
    shell = client.get("/console/assets/console.js").text
    assert "/api/fleet/discovery/addresses" in shell
    roster = client.get("/console/assets/roster.js").text
    assert "addressReason(" in roster and "새 주소로 옮기기…" in roster


def test_bulk_move_button_is_wired_to_the_per_robot_move(tmp_path):
    client, _store = _enrolled_app(tmp_path)
    page = client.get("/console").text
    assert 'id="address-move-all"' in page and "새 주소로 옮기기 (전체)…" in page
    shell = client.get("/console/assets/console.js").text
    assert "runBulkMove(targets, enrollment.moveAddress)" in shell
    assert "confirmIrreversible({\n    message: bulkConfirmMessage(targets)" in shell.replace("\r\n", "\n")
    panel = client.get("/console/assets/enrollment.js").text
    assert "/move-address`, { method: \"POST\" })" in panel
