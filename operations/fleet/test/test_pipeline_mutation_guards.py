"""Every pipeline mutation needs the operator or cell-service proposer role; a viewer is refused (403)."""
from hashlib import sha256
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from fleet.server.auth.site_auth import build_authorize, build_role_guards
from fleet.server.pipeline_routes import install_pipeline_routes
from rosy_account.principal import SitePrincipal

# Pure compute/preview endpoint without server state mutation.
VIEWER_MAY_POST = {
    ("POST", "/api/fleet/pipeline/evaluate"),
}
SERVICE_MAY_POST = VIEWER_MAY_POST | {
    ("POST", "/api/fleet/pipeline/cell-quality"),
    ("POST", "/api/fleet/pipeline/cell-handoff"),
    ("POST", "/api/fleet/pipeline/cell-tasks/claim"),
    ("POST", "/api/fleet/pipeline/cell-tasks/{task_id}/complete"),
}


def _app():
    principals = {
        sha256(t.encode()).hexdigest(): SitePrincipal(t, t)
        for t in ("viewer", "service", "operator")
    }
    authorize = build_authorize(None, principals, None)
    require_viewer, require_operator, _, require_proposer = build_role_guards(authorize, principals)
    app = FastAPI()
    app.state.operator_guard = [Depends(require_operator)]
    app.state.proposer_guard = [Depends(require_proposer)]
    maps = SimpleNamespace(active=lambda: None, rules=SimpleNamespace(active_rules=lambda: None))
    install_pipeline_routes(app, site_maps=maps, read_guard=[Depends(require_viewer)])
    return app


def _mutations(app):
    return sorted((m, r.path) for r in app.routes if r.path.startswith("/api/fleet/pipeline/")
                  for m in r.methods if m in ("POST", "PUT", "DELETE"))


def test_pipeline_mutations_reject_viewer_and_admit_operator():
    app = _app()
    client = TestClient(app, raise_server_exceptions=False)
    muts = _mutations(app)
    assert len(muts) >= 15
    for method, path in muts:
        url = path.replace("{task_id}", "t1")
        viewer = client.request(method, url, json={}, headers={"Authorization": "Bearer viewer"})
        service = client.request(method, url, json={}, headers={"Authorization": "Bearer service"})
        operator = client.request(method, url, json={}, headers={"Authorization": "Bearer operator"})
        if (method, path) in VIEWER_MAY_POST:
            assert viewer.status_code != 403, (method, path)
        else:
            assert viewer.status_code == 403, (method, path, viewer.status_code)
        if (method, path) in SERVICE_MAY_POST:
            assert service.status_code != 403, (method, path)
        else:
            assert service.status_code == 403, (method, path, service.status_code)
        assert operator.status_code not in (401, 403), (method, path, operator.status_code)


def test_install_pipeline_routes_fails_closed_when_operator_guard_is_missing():
    principals = {sha256(t.encode()).hexdigest(): SitePrincipal(t, t) for t in ("viewer", "operator")}
    authorize = build_authorize(None, principals, None)
    require_viewer, _, _, _ = build_role_guards(authorize, principals)
    app = FastAPI()
    maps = SimpleNamespace(active=lambda: None, rules=SimpleNamespace(active_rules=lambda: None))
    install_pipeline_routes(app, site_maps=maps, read_guard=[Depends(require_viewer)])
    client = TestClient(app, raise_server_exceptions=False)
    res = client.post("/api/fleet/pipeline/cell-quality", json={}, headers={"Authorization": "Bearer viewer"})
    assert res.status_code == 403


def test_cell_quality_arm_holds_are_raise_only_and_pending_clear_waits_for_ack():
    app = _app()
    client = TestClient(app)
    svc = {"Authorization": "Bearer service"}
    op = {"Authorization": "Bearer operator"}

    raised = client.post("/api/fleet/pipeline/cell-quality",
                         json={"arm_holds": {"arm_b": {"local_held": True, "local_reason": "stuck"}}}, headers=svc)
    assert raised.status_code == 200 and raised.json()["arm_holds"]["arm_b"]["held"] is True

    # Telemetry ingest alone cannot downgrade an already-latched hold to False.
    downgrade = client.post("/api/fleet/pipeline/cell-quality",
                            json={"arm_holds": {"arm_b": {"local_held": False}}}, headers=svc)
    assert downgrade.status_code == 200 and downgrade.json()["arm_holds"]["arm_b"]["held"] is True

    # Only operator /arm-holds/clear clears the Fleet hold; pending clear survives an empty/held poll until acked.
    clr = client.post("/api/fleet/pipeline/arm-holds/clear",
                      json={"arm_id": "arm_b", "note": "verified clear"}, headers=op)
    assert clr.status_code == 200 and clr.json()["arm_holds"]["arm_b"]["held"] is False
    still_held = client.post("/api/fleet/pipeline/cell-quality",
                             json={"arm_holds": {"arm_b": {"local_held": True}}}, headers=svc)
    assert "arm_b" in still_held.json()["pending_clear_arms"]

    acked = client.post("/api/fleet/pipeline/cell-quality",
                        json={"arm_holds": {"arm_b": {"local_held": False}}}, headers=svc)
    assert "arm_b" not in acked.json()["pending_clear_arms"]
