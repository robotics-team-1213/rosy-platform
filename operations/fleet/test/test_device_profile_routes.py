"""Profile routes use injected site authority and never expose command routes."""

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
                 {"display_name": "robot", "device_kind": "manipulator", "arm_count": True}):
        response = client.put("/api/fleet/device-profiles/robot-1", headers=headers, json=body)
        assert response.status_code == 422
    assert client.put("/api/fleet/device-profiles/bad.id", headers=headers,
                      json={"display_name": "robot", "device_kind": "other"}).status_code == 422
    assert client.get("/api/fleet/device-profiles", headers=headers).json() == {"profiles": []}
