"""Real Fleet credential guards protect each control-unit HTTP operation."""

from hashlib import sha256

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from fleet.server.site_auth import build_authorize, build_role_guards, SitePrincipal
from test_control_unit_service import cluster, WORK


def client_for(nodes, unit):
    from fleet.server.control_unit_routes import install_control_unit_routes
    app = FastAPI()
    principals = {sha256(token.encode()).hexdigest(): SitePrincipal(identity, role)
                  for token, identity, role in [("op-token", "operator-" + unit, "operator"),
                                                ("view-token", "reader", "viewer")]
                  + [("peer-" + u, "control-unit:" + u, "service") for u in nodes]}
    authorize = build_authorize(None, principals, nodes[unit].tasks)
    viewer, _, named, _ = build_role_guards(authorize, principals)
    install_control_unit_routes(app, nodes[unit], authorize=authorize, require_viewer=viewer,
                                require_named_operator=named)
    return TestClient(app)


def headers(token="op-token"):
    return {"Authorization": "Bearer " + token}


def test_submission_uses_server_origin_and_leaf_named_approval(tmp_path):
    nodes, _ = cluster(tmp_path)
    root, leaf = client_for(nodes, "R"), client_for(nodes, "A1")
    response = root.post("/api/fleet/control-unit/delegations", headers=headers(), json=WORK)
    assert response.status_code == 200
    assert response.json()["delegation"]["origin_id"] == "R"
    path = "/api/fleet/control-unit/delegations/R/job-1/approve"
    assert leaf.post(path, headers=headers("peer-A"), json={"expected_revision": 1}).status_code == 403
    assert leaf.post(path, headers=headers("view-token"), json={"expected_revision": 1}).status_code == 403
    approved = leaf.post(path, headers=headers(), json={"expected_revision": 1})
    assert approved.status_code == 200
    assert approved.json()["delegation"]["local_actor"] == "operator-A1"


@pytest.mark.parametrize("token", [None, "view-token", "peer-A", "peer-B", "op-token"])
def test_inbox_only_accepts_direct_parent_service(tmp_path, token):
    nodes, _ = cluster(tmp_path)
    leaf = client_for(nodes, "A")
    body = dict(WORK, origin_id="R", config_revision="v1")
    response = leaf.post("/api/fleet/control-unit/inbox", json=body,
                         headers=headers(token) if token else {})
    assert response.status_code == (200 if token == "peer-R" else 401 if token is None else 403)


def test_child_service_reads_only_its_assigned_identity_and_never_the_ledger(tmp_path):
    nodes, _ = cluster(tmp_path)
    root = client_for(nodes, "R")
    root.post("/api/fleet/control-unit/delegations", headers=headers(), json=WORK)
    path = "/api/fleet/control-unit/delegations/R/job-1"
    assert root.get(path, headers=headers("peer-A")).status_code == 200
    assert root.get(path, headers=headers("peer-B")).status_code == 403
    assert root.get("/api/fleet/control-unit/delegations", headers=headers("peer-A")).status_code == 403
    assert root.post(path + "/cancel", headers=headers("peer-A"), json={}).status_code == 403


def test_request_cannot_supply_actor_origin_or_peer_address(tmp_path):
    nodes, _ = cluster(tmp_path)
    root = client_for(nodes, "R")
    for extra in [{"actor_id": "someone"}, {"origin_id": "B"}, {"url": "http://elsewhere.invalid"}]:
        assert root.post("/api/fleet/control-unit/delegations", headers=headers(),
                         json=WORK | extra).status_code == 422
