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


@pytest.mark.parametrize("token", [None, "view-token", "peer-R", "peer-A", "peer-B", "op-token"])
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


def test_http_summary_listing_read_and_canceled_task_projection(tmp_path):
    nodes, _ = cluster(tmp_path)
    root, leaf = client_for(nodes, "R"), client_for(nodes, "A1")
    summary = root.get("/api/fleet/control-unit", headers=headers())
    assert summary.status_code == 200 and summary.json()["children"] == ["A", "B"]
    assert summary.json()["child_origins"] == {} and summary.json()["child_arm_units"] == []
    listing = root.get("/api/fleet/control-unit/delegations", headers=headers())
    assert listing.status_code == 200 and listing.json()["delegations"] == []
    assert root.post("/api/fleet/control-unit/delegations", headers=headers(), json=WORK).status_code == 200
    path = "/api/fleet/control-unit/delegations/R/job-1"
    read = leaf.get(path, headers=headers())
    assert read.status_code == 200 and read.json()["delegation"]["request"]["robot_id"] == "a1"
    approved = leaf.post(path + "/approve", headers=headers(), json={"expected_revision": 1})
    assert approved.status_code == 200 and approved.json()["delegation"]["local_task_id"]
    canceled = leaf.post(path + "/cancel", headers=headers(), json={})
    assert canceled.status_code == 200 and canceled.json()["delegation"]["cancel_requested"]
    assert leaf.get(path, headers=headers()).json()["delegation"]["status"] == "CANCELED"


@pytest.mark.parametrize("path,token,method", [
    ("/api/fleet/control-unit/delegations", "view-token", "list"),
    ("/api/fleet/control-unit/delegations/R/job-1", "view-token", "get"),
    ("/api/fleet/control-unit/delegations/R/job-1", "peer-A", "get"),
])
def test_unavailable_journal_returns_stable_503(tmp_path, monkeypatch, path, token, method):
    import sqlite3
    nodes, _ = cluster(tmp_path)
    root = client_for(nodes, "R")
    def unavailable(*args, **kwargs):
        raise sqlite3.OperationalError("injected journal unavailable")
    monkeypatch.setattr(nodes["R"].store, method, unavailable)
    response = root.get(path, headers=headers(token))
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "CONTROL_UNIT_JOURNAL_UNAVAILABLE"


def test_summary_lists_https_child_origins_and_arm_children_without_credentials(tmp_path):
    from types import SimpleNamespace
    from fleet.server.control_unit_config import ControlUnitTopology
    from fleet.server.control_unit_service import ControlUnitService
    from fleet.server.control_unit_store import ControlUnitStore
    from fleet.server.task_service import FleetTaskService
    from fleet.server.task_store import FleetTaskStore
    from test_control_unit_service import Console
    manifest = {"revision": "v1", "units": [
        {"id": "R"},
        {"id": "A", "parent": "R"},
        {"id": "B", "parent": "R", "resources": ["workcell:cell_ab"]},
        {"id": "A1", "parent": "A", "resources": ["workcell:cell_s", "robot:a1"]}]}
    topology = ControlUnitTopology.from_mapping(manifest)
    nodes = {}
    for unit_id in topology.units:
        path = tmp_path / (unit_id + ".db")
        robots = {r[6:] for r in topology.unit(unit_id).resources if r.startswith("robot:")}
        nodes[unit_id] = ControlUnitService(topology, ControlUnitStore(path, unit_id=unit_id),
                                            FleetTaskService(FleetTaskStore(path), robot_ids=robots),
                                            Console(), peer=None)
    nodes["R"].peer = SimpleNamespace(config=SimpleNamespace(peers={
        "A": SimpleNamespace(url="https://cell-a.example.test:8443/ignored?query#frag", token="secret-a"),
        "B": SimpleNamespace(url="http://plain.invalid:8080", token="secret-b")}))
    summary = client_for(nodes, "R").get("/api/fleet/control-unit", headers=headers())
    assert summary.status_code == 200
    body = summary.json()
    assert body["child_origins"] == {"A": "https://cell-a.example.test:8443"}
    # A1's workcell sits in A's subtree, B owns one directly: both map to direct children.
    assert body["child_arm_units"] == ["A", "B"]
    assert "secret-a" not in summary.text and "secret-b" not in summary.text
    assert "plain.invalid" not in summary.text
