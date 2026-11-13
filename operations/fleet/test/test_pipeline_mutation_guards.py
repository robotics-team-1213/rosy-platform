"""Every pipeline mutation needs the operator role; a viewer is refused (403)."""
from hashlib import sha256
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from fleet.server.auth.site_auth import build_authorize, build_role_guards
from fleet.server.pipeline_routes import install_pipeline_routes
from rosy_account.principal import SitePrincipal

# Reads/compute-only, or called by the OMX cell with a machine token whose role is set only in the
# host's site-users file (unknown from the repo): left on read_guard on purpose.
VIEWER_MAY_POST = {
    ("POST", "/api/fleet/pipeline/evaluate"),
    ("POST", "/api/fleet/pipeline/cell-quality"),
    ("POST", "/api/fleet/pipeline/cell-handoff"),
    ("POST", "/api/fleet/pipeline/cell-tasks/claim"),
    ("POST", "/api/fleet/pipeline/cell-tasks/{task_id}/complete"),
}


def _app():
    principals = {sha256(t.encode()).hexdigest(): SitePrincipal(t, t) for t in ("viewer", "operator")}
    authorize = build_authorize(None, principals, None)
    require_viewer, require_operator, _, _ = build_role_guards(authorize, principals)
    app = FastAPI()
    app.state.operator_guard = [Depends(require_operator)]
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
        operator = client.request(method, url, json={}, headers={"Authorization": "Bearer operator"})
        if (method, path) in VIEWER_MAY_POST:
            assert viewer.status_code != 403, (method, path)
        else:
            assert viewer.status_code == 403, (method, path, viewer.status_code)
        assert operator.status_code not in (401, 403), (method, path, operator.status_code)
