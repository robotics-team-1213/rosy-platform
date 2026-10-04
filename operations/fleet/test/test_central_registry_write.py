"""D-454 central writes remain unmounted until their authority owner is implemented.

The documented Admin and named EnrollmentService contract is unresolved. Updating
an enrollment flag is not a token revocation or an approved discovery-identity edit.
These real-app tests preserve the reviewed GET-only boundary; no device calls.
"""

from hashlib import sha256

import pytest
from fastapi.testclient import TestClient

from fleet.server.app import create_app
from fleet.server.enrollment import EnrollmentService
from fleet.server.enrollment_store import EnrollmentStore, seal
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from test_central_registry import _registry


@pytest.mark.parametrize("identity", ["anonymous", "viewer", "operator"])
@pytest.mark.parametrize("robot_id", ["rosy_01", "rosy_02", "not-approved"])
def test_proposed_central_writes_cannot_change_real_approved_registry(tmp_path, identity, robot_id):
    registry = _registry()  # Real FleetConsole/SiteRoster/DiscoveryStore; fixture robot clients.
    key = b"x" * 32
    store = EnrollmentStore(tmp_path / "enrollment.sqlite3")
    store.insert({"robot_id": "rosy_02", "hostname": "rosy-02", "discovery_name": "rosy_02",
                  "address": "10.0.0.8:8080", "token_id": "fixture-token-id", "role": "operator",
                  "source": "screen_code", "principal_id": "enroller-1", "state": "active"},
                 seal(key, "fixture-robot-secret", slot="rest", robot_id="rosy_02",
                      token_id="fixture-token-id"))
    enrollment = EnrollmentService(store, registry._roster, key=key, discovery=registry._discovery)
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"),
                             robot_ids=set(registry._roster.robot_ids))
    users = {sha256(f"fixture-{role}".encode()).hexdigest(): {
        "principal_id": f"{role}-1", "role": role} for role in ("viewer", "operator")}
    app = create_app(registry._console, central_registry=registry, enrollment=enrollment,
                     task_service=tasks, site_users=users)
    proposed = [("PATCH", "/api/v1/fleet/robots/{robot_id}"),
                ("DELETE", "/api/v1/fleet/robots/{robot_id}"),
                ("POST", "/api/v1/fleet/robots/{robot_id}/token/revoke"),
                ("GET", "/api/v1/fleet/pending-robots"),
                ("POST", "/api/v1/fleet/pending-robots/{robot_id}/approve"),
                ("POST", "/api/v1/fleet/pairing-tokens")]
    mounted = app.openapi()["paths"]
    for method, path in proposed:
        assert method.lower() not in mounted.get(path, {})
    before_rows = registry.rows()
    before_ids = list(registry._roster.robot_ids)
    before_endpoints = dict(registry._console.registered_endpoints)
    before_clients = dict(registry._console._clients)
    before_enrollment = store.rows()
    before_ciphertext = store.ciphertext("rosy_02")
    before_audit = store.audit_rows()
    client = TestClient(app)
    headers = {} if identity == "anonymous" else {"Authorization": f"Bearer fixture-{identity}"}
    for method, path in proposed:
        response = client.request(method, path.format(robot_id=robot_id), headers=headers,
                                  json={"name": "unapproved discovery alias", "group": "unapproved"})
        assert response.status_code in (404, 405), (method, path, response.text)
    assert registry.rows() == before_rows
    assert registry._roster.robot_ids == before_ids
    assert registry._console.registered_endpoints == before_endpoints
    assert registry._console._clients == before_clients
    # Reload SQLite, not an in-memory fake, to prove durable credentials and identity are unchanged.
    reopened = EnrollmentStore(store.path)
    assert reopened.rows() == before_enrollment
    assert reopened.ciphertext("rosy_02") == before_ciphertext
    assert reopened.audit_rows() == before_audit
    assert registry.row("rosy_01")["address_last_seen"] == "10.0.0.7"
    assert registry.row("not-approved") is None
    assert all(not robot.calls for robot in before_clients.values())
    read = client.get("/api/v1/fleet/robots", headers=headers)
    assert read.status_code == (401 if identity == "anonymous" else 200)
    if identity != "anonymous":
        assert read.json() == {"robots": before_rows}
        assert client.get("/api/v1/fleet/robots/not-approved", headers=headers).status_code == 404
