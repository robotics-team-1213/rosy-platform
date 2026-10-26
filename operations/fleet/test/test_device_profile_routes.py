"""Profile routes use injected site authority and never expose command routes."""

import sqlite3
from hashlib import sha256

import pytest
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from fleet.server.device_profiles import DeviceProfileStore
from fleet.server.device_profile_routes import install_device_profile_routes
from fleet.server.site_auth import SitePrincipal


@pytest.fixture
def client(tmp_path):
    principals = {"viewer": SitePrincipal("viewer:kim", "viewer"),
                  "operator": SitePrincipal("operator:lee", "operator"),
                  "shared": SitePrincipal("legacy", "operator"),
                  "service": SitePrincipal("service:camera", "service")}

    def authorize(authorization: str = Header(default="")):
        if authorization not in principals:
            raise HTTPException(401)
        return principals[authorization]

    def viewer(principal=Depends(authorize)):
        if principal.role not in {"viewer", "operator"}:
            raise HTTPException(403)
        return principal

    def operator(principal=Depends(viewer)):
        if principal.role != "operator" or principal.principal_id == "legacy":
            raise HTTPException(403)
        return principal

    app = FastAPI()
    store = DeviceProfileStore(tmp_path / "tasks.sqlite3")
    install_device_profile_routes(app, store, require_viewer=viewer, require_named_operator=operator)
    with TestClient(app) as browser:
        yield browser


@pytest.mark.parametrize("credential,read_status,write_status", [
    ("", 401, 401), ("viewer", 200, 403), ("operator", 200, 200),
    ("shared", 200, 403), ("service", 403, 403),
])
def test_authorization(client, credential, read_status, write_status):
    headers = {"Authorization": credential}
    assert client.get("/api/fleet/device-profiles", headers=headers).status_code == read_status
    response = client.put("/api/fleet/device-profiles/robot-1", headers=headers,
                          json={"display_name": "실험용 로봇", "device_kind": "manipulator", "arm_count": 2})
    assert response.status_code == write_status
    profiles = client.get("/api/fleet/device-profiles", headers={"Authorization": "viewer"}).json()["profiles"]
    assert len(profiles) == (1 if write_status == 200 else 0)
    if write_status == 200:
        assert profiles[0]["updated_by"] == "operator:lee"
        assert profiles[0]["connection_status"] == "not_checked"
        assert profiles[0]["control_enabled"] is False
        assert client.get("/api/fleet/device-profiles/robot-1", headers=headers).json() == profiles[0]


def test_missing_invalid_and_forbidden_fields(client):
    headers = {"Authorization": "operator"}
    assert client.get("/api/fleet/device-profiles/missing", headers=headers).status_code == 404
    for body in ({}, [], {"display_name": "robot", "device_kind": "other", "control_enabled": True},
                 {"display_name": "robot", "device_kind": {}},
                 {"display_name": "robot", "device_kind": "other", "hardware_ids": [{}]},
                 {"display_name": "robot", "device_kind": "other", "hardware_ids": [[]]},
                 {"display_name": "robot", "device_kind": "manipulator", "arm_count": True}):
        response = client.put("/api/fleet/device-profiles/robot-1", headers=headers, json=body)
        assert response.status_code == 422
    assert client.put("/api/fleet/device-profiles/bad.id", headers=headers,
                      json={"display_name": "robot", "device_kind": "other"}).status_code == 422
    assert client.get("/api/fleet/device-profiles", headers=headers).json() == {"profiles": []}


@pytest.mark.parametrize("operation,method,path", [
    ("list_profiles", "GET", "/api/fleet/device-profiles"),
    ("get_profile", "GET", "/api/fleet/device-profiles/robot-1"),
    ("put_profile", "PUT", "/api/fleet/device-profiles/robot-1"),
])
def test_storage_failure_is_unavailable(client, monkeypatch, operation, method, path):
    def unavailable(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(DeviceProfileStore, operation, unavailable)
    response = client.request(method, path, headers={"Authorization": "operator"},
                              json={"display_name": "robot", "device_kind": "other"} if method == "PUT" else None)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "DEVICE_PROFILE_STORAGE_UNAVAILABLE"


@pytest.mark.parametrize("body", [r'{"display_name":"\ud800","device_kind":"other"}',
                                 r'{"display_name":"\udfff","device_kind":"other"}'])
def test_surrogates_rejected_but_unicode_allowed(client, body):
    headers = {"Authorization": "operator", "Content-Type": "application/json"}
    assert client.put("/api/fleet/device-profiles/robot-1", headers=headers, content=body).status_code == 422
    response = client.put("/api/fleet/device-profiles/robot-1", headers=headers,
                          json={"display_name": "한글 🙂", "device_kind": "other"})
    assert response.status_code == 200
    assert response.json()["display_name"] == "한글 🙂"


def test_real_app_profiles_persist_without_enrollment_or_control(tmp_path):
    from fakes import FakeRobot
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.server.roster import SiteRoster
    from fleet.server.task_service import FleetTaskService
    from fleet.server.task_store import FleetTaskStore
    from fleet.swarm.robots import RobotEndpoint

    robot = FakeRobot("seed")
    console = FleetConsole([RobotEndpoint("seed", "http://10.0.0.7:8080", "fixture-token")], [robot])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite3"), robot_ids={"seed"})
    roster = SiteRoster(console, task_service=tasks)
    token = "fixture-operator"
    users = {sha256(token.encode()).hexdigest(): {"principal_id": "operator-1", "role": "operator"}}
    headers = {"Authorization": f"Bearer {token}"}
    before_endpoints = dict(console.registered_endpoints)
    before_clients = dict(console._clients)
    app = create_app(console, task_service=tasks, site_users=users)
    browser = TestClient(app)
    assert browser.get("/api/fleet/device-profiles").status_code == 401
    assert app.state.device_profiles.path == tasks.store.path
    response = browser.put("/api/fleet/device-profiles/unconnected-arm", headers=headers,
                           json={"display_name": "한글 🙂", "device_kind": "manipulator", "arm_count": 2})
    assert response.status_code == 200
    profile = response.json()
    assert profile["updated_by"] == "operator-1"
    assert profile["connection_status"] == "not_checked"
    assert profile["control_enabled"] is False
    restarted = TestClient(create_app(console, task_service=tasks, site_users=users))
    assert restarted.get("/api/fleet/device-profiles/unconnected-arm", headers=headers).json() == profile
    assert restarted.get("/api/fleet/device-profiles", headers=headers).json() == {"profiles": [profile]}
    assert roster.robot_ids == ["seed"]
    assert tasks.robot_ids == {"seed"}
    assert console.registered_endpoints == before_endpoints
    assert console._clients == before_clients
    assert robot.calls == []


def test_real_app_without_task_store_does_not_mount_profile_routes():
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole

    app = create_app(FleetConsole([], []))
    assert not any(route.path.startswith("/api/fleet/device-profiles") for route in app.routes)
