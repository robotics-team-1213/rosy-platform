"""D-454 1c — §10.1 나머지 경로 계약 (PATCH·token/revoke·pending·pairing-tokens).

PATCH는 등록 저장소의 discovery_name을, token/revoke는 상태 전환을, pending은
비-active 목록을 돌려준다. pairing-tokens는 501(설계 대기).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet.server.central_registry import CentralRegistry
from fleet.server.central_registry_routes import install_central_registry_routes


class FakeRoster:
    def robot_ids(self):
        return ["rosy_01"]

    def source_of(self, robot_id):
        return "static" if robot_id == "rosy_01" else None


class FakeStore:
    def __init__(self):
        self.rows_data = {"rosy_01": {"robot_id": "rosy_01", "discovery_name": "old",
                                      "state": "active"}}
        self.updates: list[tuple[str, dict]] = []

    def update(self, robot_id, **fields):
        if robot_id not in self.rows_data:
            raise KeyError(robot_id)
        self.rows_data[robot_id].update(fields)
        self.updates.append((robot_id, fields))


class FakeEnrollment:
    def __init__(self):
        self._store = FakeStore()

    def listing(self):
        return {"robots": list(self._store.rows_data.values())}


@pytest.fixture
def client():
    app = FastAPI()
    registry = CentralRegistry(FakeRoster())
    enrollment = FakeEnrollment()
    install_central_registry_routes(app, registry,
                                    require_viewer=lambda: "viewer",
                                    require_operator=lambda: "operator",
                                    enrollment=enrollment)
    return TestClient(app), enrollment


def test_patch_updates_discovery_name(client):
    c, enrollment = client
    response = c.patch("/api/v1/fleet/robots/rosy_01", json={"name": "새 이름"})
    assert response.status_code == 200
    assert response.json() == {"robot_id": "rosy_01", "name": "새 이름"}
    assert enrollment._store.rows_data["rosy_01"]["discovery_name"] == "새 이름"


def test_patch_unknown_robot_404(client):
    c, _ = client
    assert c.patch("/api/v1/fleet/robots/rosy_99", json={"name": "x"}).status_code == 404


def test_patch_empty_name_422(client):
    c, _ = client
    assert c.patch("/api/v1/fleet/robots/rosy_01", json={"name": "  "}).status_code == 422


def test_token_revoke_marks_needs_new_code(client):
    c, enrollment = client
    response = c.post("/api/v1/fleet/robots/rosy_01/token/revoke")
    assert response.status_code == 200
    assert response.json()["token_state"] == "revoked"
    assert enrollment._store.rows_data["rosy_01"]["state"] == "needs_new_code"


def test_token_revoke_unknown_404(client):
    c, _ = client
    assert c.post("/api/v1/fleet/robots/rosy_99/token/revoke").status_code == 404


def test_pending_robots_lists_non_active(client):
    c, enrollment = client
    enrollment._store.rows_data["rosy_01"]["state"] = "needs_new_code"
    body = c.get("/api/v1/fleet/pending-robots").json()
    assert len(body["pending"]) == 1
    assert body["pending"][0]["robot_id"] == "rosy_01"


def test_pending_robots_empty_when_all_active(client):
    c, _ = client
    body = c.get("/api/v1/fleet/pending-robots").json()
    assert body["pending"] == []


def test_pairing_tokens_501(client):
    c, _ = client
    response = c.post("/api/v1/fleet/pairing-tokens")
    assert response.status_code == 501
    assert response.json()["detail"]["code"] == "NOT_IMPLEMENTED"


def test_patch_without_enrollment_501():
    app = FastAPI()
    install_central_registry_routes(app, CentralRegistry(FakeRoster()),
                                    require_viewer=lambda: "v",
                                    require_operator=lambda: "o")
    c = TestClient(app)
    assert c.patch("/api/v1/fleet/robots/rosy_01", json={"name": "x"}).status_code == 501
