"""Configured HTTP success paths missing from the frontend's initial receipts."""

from hashlib import sha256

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from fleet.server.console import FleetConsole
from fleet.server.site_auth import SitePrincipal, build_authorize, build_role_guards
from test_policy_governance import client as policy_client


def test_named_operator_closes_an_approved_policy_window(policy_client):
    from test_policy_governance import BASE, auth, lease, open_window, to_l3

    to_l3(policy_client)
    window = open_window(policy_client)
    assert lease(policy_client).status_code == 200
    path = f"{BASE}/windows/{window['window_id']}/close"
    body = {"operator_confirmed": True, "reason": "operator finished the supervised run"}
    assert policy_client.post(path, headers=auth("viewer-a"), json=body).status_code == 403
    response = policy_client.post(path, headers=auth("operator-a"), json=body)
    assert response.status_code == 200, response.text
    assert response.json()["closed_ns"] is not None
    assert response.json()["closed_reason"] == "closed by operator-a: " + body["reason"]
    assert lease(policy_client).status_code == 409


def test_named_operator_confirms_a_real_trip_replan():
    from asyncio import run

    from fleet.server.trip_routes import install_trip_routes
    from test_trip_runner import _arc, _plan, _setup, _ticks

    runner, maps, ports = _setup()
    _plan(maps, ports, "ring_s:fwd", 0.1, "NW")
    run(runner.start("p1", "bob"))
    ports.blocked = frozenset({"ring_e"})
    _ticks(runner, ports)
    assert runner.running()["hold"]["reason"] == "replan"
    arc = _arc(maps, "ring_s:fwd")
    ports.at(arc, arc.length_m - 0.05)
    _ticks(runner, ports, 4)

    principals = {sha256(token.encode()).hexdigest(): SitePrincipal(token, role)
                  for token, role in (("read", "viewer"), ("write", "operator"))}
    authorize = build_authorize(console_token=None, principals=principals, task_service=None)
    viewer, operator, named, _ = build_role_guards(authorize, principals)
    app = FastAPI()
    install_trip_routes(app, console=FleetConsole([], []), site_maps=maps,
                        routing_config=maps.routing_config, caps_for=ports.caps_for, runner=runner,
                        require_operator=operator, require_named_operator=named,
                        read_guard=[Depends(viewer)])
    with TestClient(app) as client:
        path = "/api/fleet/trips/p1/confirm-replan"
        assert client.post(path, headers={"Authorization": "Bearer read"}).status_code == 403
        response = client.post(path, headers={"Authorization": "Bearer write"})
        assert response.status_code == 200, response.text
        view = response.json()
        assert view["hold"] is None
        assert [segment["edge_id"] for segment in view["plan"]["segments"]][:2] == ["ring_s", "east"]
        assert runner.running()["hold"] is None
        _ticks(runner, ports)
        assert ports.sent[-1][0] != "stop"


def test_named_operator_reconciles_a_lost_cell_action_without_resubmitting(tmp_path):
    from test_cell_goal_evidence_api import _admitted
    from test_step_dispatcher import _receipt

    client, _, transport, identifier = _admitted(tmp_path, lose_submit=True)
    dispatcher = client.app.state.cell_job_dispatcher
    assert dispatcher.dispatch_next()["state"] == "HOLD"
    transport.on_get = lambda grant: _receipt(grant, "SUCCEEDED", 20)
    path = f"/api/fleet/cell-jobs/{identifier}/reconcile"
    assert client.post(path, headers={"Authorization": "Bearer viewer-secret"}).status_code == 403
    response = client.post(path, headers={"Authorization": "Bearer operator-secret"})
    assert response.status_code == 200, response.text
    assert response.json()["job"]["steps"][0]["status"] == "ACTION_SUCCEEDED"
    assert len(transport.submissions) == 1
    assert len(transport.lookups) == 1
    assert client.app.state.cell_job_store.get(identifier)["steps"][0]["status"] == "ACTION_SUCCEEDED"


def test_named_operator_unenrolls_an_idle_robot_and_records_the_actor(tmp_path):
    from test_enrollment_api import CODE, NAME, OPERATOR, VIEWER, _app, _headers

    client, _, _, store = _app(tmp_path)
    created = client.post("/api/fleet/enrollment/robots", headers=_headers(OPERATOR),
                          json={"discovery_name": NAME, "code": CODE})
    assert created.status_code == 201, created.text
    path = "/api/fleet/enrollment/robots/rosy_09"
    assert client.delete(path, headers=_headers(VIEWER)).status_code == 403
    response = client.delete(path, headers=_headers(OPERATOR))
    assert response.status_code == 200, response.text
    assert client.get("/api/fleet/enrollment/robots", headers=_headers(VIEWER)).json()["robots"] == []
    assert store.get("rosy_09") is None
    assert store.audit_rows()[-1]["principal_id"] == "alice"


def test_named_operator_rejects_a_pending_legacy_camera_request(tmp_path):
    from test_pairing_api import BASE, OPERATOR, VIEWER, Phone, _app, _auth

    client, _, store, _ = _app(tmp_path)
    phone = Phone()
    created = client.post(BASE + "/requests", content=phone.request_bytes())
    assert created.status_code == 201, created.text
    identifier = created.json()["request_id"]
    path = f"{BASE}/requests/{identifier}/reject"
    assert client.post(path, headers=_auth(VIEWER)).status_code == 403
    response = client.post(path, headers=_auth(OPERATOR))
    assert response.status_code == 200, response.text
    assert response.json() == {"request_id": identifier, "state": "rejected"}
    status = client.get(f"{BASE}/requests/{identifier}", headers={"Authorization": phone.bearer})
    assert status.status_code == 200 and status.json()["state"] == "rejected"
    assert store.audit_rows()[-1]["principal_id"] == "alice"


def test_named_operator_deletes_a_start_point_with_its_current_revision(tmp_path):
    from test_overhead_tracking_api import APPROVAL, OPERATOR_TOKEN, VIEWER_TOKEN, _auth, _client

    with _client(tmp_path, calibration_path=tmp_path / "cal.sqlite3") as client:
        auth = _auth(OPERATOR_TOKEN)
        approved = client.post("/api/fleet/calibrations", headers=auth, json=APPROVAL)
        assert approved.status_code == 200, approved.text
        path = "/api/fleet/start-points/ceiling_north"
        saved = client.put(path, headers=auth, json={
            "map_id": "map_v2_fleet", "calibration_revision": approved.json()["calibration_revision"],
            "expected_revision": None, "x": 1.0, "y": 0.5, "yaw": 0.0,
        })
        assert saved.status_code == 200, saved.text
        query = {"expected_revision": saved.json()["revision"]}
        assert client.delete(path, headers=_auth(VIEWER_TOKEN), params=query).status_code == 403
        assert client.delete(path, headers=auth, params={"expected_revision": "old"}).status_code == 409
        response = client.delete(path, headers=auth, params=query)
        assert response.status_code == 200, response.text
        assert response.json() == {"deleted": True, "source_id": "ceiling_north"}
        assert client.get("/api/fleet/start-points", headers=auth).json()["start_points"] == []
