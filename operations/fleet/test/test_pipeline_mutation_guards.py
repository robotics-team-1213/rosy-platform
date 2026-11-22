"""Every pipeline mutation needs the operator or cell-service proposer role; a viewer is refused (403)."""
from hashlib import sha256
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from fleet.server.auth.site_auth import build_authorize, build_role_guards
from fleet.server.pipeline_routes import install_pipeline_routes
from core_common.protocol.arm_incident.arm_incidents import ArmIncidentReport
from fleet.server.arm_incidents import ArmIncidentStore
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
    ("POST", "/api/fleet/pipeline/cell-tasks/{task_id}/bed-observation"),
    ("POST", "/api/fleet/pipeline/cell-tasks/{task_id}/owner-evidence"),  # bed-confirm stays operator only
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


def test_arm_holds_clear_also_clears_open_arm_incident_rows():
    store = ArmIncidentStore()
    store.report(ArmIncidentReport.model_validate({
        "source_id": "omx_arm_b", "session_id": "6f1c2a3e-1b2d-4e5f-8a9b-0c1d2e3f4a5b",
        "facts": {"latched": {"13": {"hw_error": 32}}, "folded": True},
        "decision": {"hold": True, "reason": "latched ID 13 overload"}, "frames": []}))
    assert store.hold("omx_arm_b").held is True
    app = _app()
    app.state.arm_incidents = store
    client = TestClient(app)
    viewer = client.post("/api/fleet/pipeline/arm-holds/clear", json={"arm_id": "arm_b"},
                         headers={"Authorization": "Bearer viewer"})
    assert viewer.status_code == 403
    res = client.post("/api/fleet/pipeline/arm-holds/clear",
                      json={"arm_id": "arm_b", "note": "person verified", "cause": "snagged", "basis": "seen"},
                      headers={"Authorization": "Bearer operator"})
    assert res.status_code == 200 and res.json()["arm_holds"]["arm_b"]["held"] is False
    assert store.hold("omx_arm_b").held is False
    cleared = store.snapshot("omx_arm_b")[0]["cleared"]
    assert cleared["by"] == "operator" and cleared["note"] == "person verified"
    assert cleared["cause"] == "snagged" and cleared["basis"] == "seen"


def _aborted_cell_app(monkeypatch):
    import time
    from tools.sim.bay_departure_sim import build_world_261026_site_map

    monkeypatch.setenv("ROSY_FLEET_CELL_OWNERS", "cell_s=service;cell_ab=service")
    site, graph, _ = build_world_261026_site_map()
    principals = {
        sha256(t.encode()).hexdigest(): SitePrincipal(t, role)
        for t, role in (("service", "service"), ("operator", "operator"), ("bob", "operator"),
                        ("site-console", "operator"), ("development-local", "operator"))
    }
    authorize = build_authorize(None, principals, None)
    require_viewer, require_operator, _, require_proposer = build_role_guards(authorize, principals)
    app = FastAPI()
    app.state.operator_guard = [Depends(require_operator)]
    app.state.proposer_guard = [Depends(require_proposer)]
    maps = SimpleNamespace(active=lambda: (1, site, graph, None), rules=SimpleNamespace(active_rules=lambda: None))
    install_pipeline_routes(
        app,
        site_maps=maps,
        read_guard=[Depends(require_viewer)],
        amr_evidence_fn=lambda task: {
            "robot_id": task["robot_id"], "cell_id": task["cell_id"], "observed_at": time.time(),
            "wheel_brake_locked": True, "bed_ready": True, "v_cmd_mps": 0.0, "pose": dict(task["pose"]),
        },
    )
    return app


def test_arm_holds_clear_releases_aborted_cell_for_named_operator_and_allows_next_claim(monkeypatch):
    app = _aborted_cell_app(monkeypatch)
    client = TestClient(app)
    op = {"Authorization": "Bearer bob"}
    svc = {"Authorization": "Bearer service"}
    app.state.omx_cell_states["cell_s"] = {
        "phase": "ABORTED", "prev_phase": "ABORTED", "robot_id": "rosy_42",
        "amr_motion_inhibited": True, "reason": "MEASURED_PLACEMENT_MISSING",
        "docked_robot": {"robot_id": "rosy_42", "robot_kind": "pinky", "pose": {"x": 0.745, "y": -0.207, "yaw": 0.0},
                         "wheel_brake_locked": True, "bed_ready": True, "v_cmd_mps": 0.0},
    }
    app.state.arm_holds["arm_s"] = {"arm": "arm_s", "held": True, "reason": "fault", "incident_ids": []}
    created = client.post("/api/fleet/pipeline/cell-tasks", json={
        "task_id": "t-after-abort", "cell_id": "cell_s", "robot_id": "rosy_42",
    }, headers=op)
    assert created.status_code == 200
    blocked = client.post("/api/fleet/pipeline/cell-tasks/claim", json={"cell_id": "cell_s"}, headers=svc).json()
    assert blocked["claimed"] is False and blocked["reason"] == "CELL_BUSY_OR_HELD"

    for anon in ("site-console", "development-local"):
        refused = client.post("/api/fleet/pipeline/arm-holds/clear",
                              json={"cell_id": "cell_s", "note": "folded home"},
                              headers={"Authorization": f"Bearer {anon}"})
        assert refused.status_code == 403 and refused.json()["detail"]["code"] == "NAMED_OPERATOR_REQUIRED"
        assert app.state.omx_cell_states["cell_s"]["phase"] == "ABORTED"
        assert app.state.omx_cell_states["cell_s"]["amr_motion_inhibited"] is True
        assert app.state.arm_holds["arm_s"]["held"] is True

    app.state._pipeline_ledger_fault = True
    faulted = client.post("/api/fleet/pipeline/arm-holds/clear",
                          json={"cell_id": "cell_s", "note": "folded home"}, headers=op)
    assert faulted.status_code == 503 and faulted.json()["detail"]["code"] == "PIPELINE_LEDGER_UNAVAILABLE"
    assert app.state.omx_cell_states["cell_s"]["phase"] == "ABORTED"
    app.state._pipeline_ledger_fault = False

    clr = client.post("/api/fleet/pipeline/arm-holds/clear",
                      json={"cell_id": "cell_s", "note": "verified folded home"}, headers=op)
    assert clr.status_code == 200 and clr.json()["cleared_cells"] == ["cell_s"]
    cell_s = app.state.omx_cell_states["cell_s"]
    assert cell_s["phase"] == "IDLE" and cell_s["amr_motion_inhibited"] is False
    assert cell_s["docked_robot"]["wheel_brake_locked"] is False and cell_s["docked_robot"]["bed_ready"] is False
    assert "prev_phase" not in cell_s and cell_s["cleared_by"] == "bob"
    claimed = client.post("/api/fleet/pipeline/cell-tasks/claim", json={"cell_id": "cell_s"}, headers=svc).json()
    assert claimed["claimed"] is True


def test_arm_holds_clear_rolls_back_and_rejects_unknown_target_or_missing_principal(tmp_path, monkeypatch):
    from fleet.server.sitemap import pipeline_routes as routes

    monkeypatch.setenv("ROSY_FLEET_CELL_OWNERS", "cell_s=service")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(routes, "_storage_dir", lambda: tmp_path)
    app = _aborted_cell_app(monkeypatch)
    store = ArmIncidentStore()
    store.report(ArmIncidentReport.model_validate({
        "source_id": "omx_arm_s", "session_id": "6f1c2a3e-1b2d-4e5f-8a9b-0c1d2e3f4a5b",
        "facts": {"latched": {"13": {"hw_error": 32}}, "folded": True},
        "decision": {"hold": True, "reason": "latched ID 13 overload"}, "frames": []}))
    app.state.arm_incidents = store
    client = TestClient(app)
    op = {"Authorization": "Bearer bob"}
    app.state.omx_cell_states["cell_s"] = {"phase": "ABORTED", "robot_id": "rosy_42", "amr_motion_inhibited": True}
    app.state.arm_holds["arm_s"] = {"arm": "arm_s", "held": True, "reason": "fault", "incident_ids": []}

    bad_target = client.post("/api/fleet/pipeline/arm-holds/clear",
                             json={"cell_id": "cell_unknown", "note": "folded home"}, headers=op)
    assert bad_target.status_code == 422 and bad_target.json()["detail"]["code"] == "UNKNOWN_ARM_OR_CELL"
    assert app.state.omx_cell_states["cell_s"]["phase"] == "ABORTED"

    monkeypatch.setattr(routes.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    failed = client.post("/api/fleet/pipeline/arm-holds/clear",
                         json={"cell_id": "cell_s", "note": "folded home"}, headers=op)
    assert failed.status_code == 503 and failed.json()["detail"]["code"] == "PIPELINE_LEDGER_UNAVAILABLE"
    assert app.state.omx_cell_states["cell_s"]["phase"] == "ABORTED"
    assert app.state.omx_cell_states["cell_s"]["amr_motion_inhibited"] is True
    assert app.state.arm_holds["arm_s"]["held"] is True
    assert "arm_s" not in app.state.pending_clear_arms
    assert store.hold("omx_arm_s").held is True

    # Bare app with no site_principal fails closed on ABORTED clear.
    bare = FastAPI()
    maps = SimpleNamespace(active=lambda: None, rules=SimpleNamespace(active_rules=lambda: None))
    install_pipeline_routes(bare, site_maps=maps)
    bare.state.omx_cell_states["cell_s"] = {"phase": "ABORTED", "robot_id": "rosy_42", "amr_motion_inhibited": True}
    bare_client = TestClient(bare)
    no_principal = bare_client.post("/api/fleet/pipeline/arm-holds/clear",
                                    json={"cell_id": "cell_s", "note": "folded home"})
    assert no_principal.status_code == 403 and no_principal.json()["detail"]["code"] == "NAMED_OPERATOR_REQUIRED"
    assert bare.state.omx_cell_states["cell_s"]["phase"] == "ABORTED"


def test_arm_holds_clear_keeps_aborted_cell_locked_when_human_running_or_sibling_arm_held(monkeypatch):
    app = _aborted_cell_app(monkeypatch)
    client = TestClient(app)
    op = {"Authorization": "Bearer bob"}

    for phase in ("HUMAN_HOLD", "ARM_IN_BED_ZONE", "CLAIMED"):
        app.state.omx_cell_states["cell_s"] = {"phase": phase, "robot_id": "rosy_42", "amr_motion_inhibited": True}
        res = client.post("/api/fleet/pipeline/arm-holds/clear",
                          json={"cell_id": "cell_s", "note": "folded home"}, headers=op)
        assert res.status_code == 200 and res.json()["cleared_cells"] == []
        assert app.state.omx_cell_states["cell_s"]["phase"] == phase
        assert app.state.omx_cell_states["cell_s"]["amr_motion_inhibited"] is True

    app.state.omx_cell_states["cell_s"] = {"phase": "ABORTED", "robot_id": "rosy_42", "amr_motion_inhibited": True}
    app.state.human_detected["cell_s"] = True
    assert client.post("/api/fleet/pipeline/arm-holds/clear",
                       json={"cell_id": "cell_s", "note": "folded home"}, headers=op).json()["cleared_cells"] == []
    assert app.state.omx_cell_states["cell_s"]["phase"] == "ABORTED"
    app.state.human_detected["cell_s"] = False

    for status in ("RUNNING", "PAUSED_HUMAN"):
        app.state.omx_cell_tasks["t-active"] = {"task_id": "t-active", "cell_id": "cell_s", "status": status}
        assert client.post("/api/fleet/pipeline/arm-holds/clear",
                           json={"cell_id": "cell_s", "note": "folded home"}, headers=op).json()["cleared_cells"] == []
        assert app.state.omx_cell_states["cell_s"]["phase"] == "ABORTED"
    app.state.omx_cell_tasks.pop("t-active")

    app.state.omx_cell_states["cell_ab"] = {"phase": "ABORTED", "robot_id": "rosy_46", "amr_motion_inhibited": True}
    app.state.arm_holds["arm_a"] = {"arm": "arm_a", "held": True, "reason": "a", "incident_ids": []}
    app.state.arm_holds["arm_b"] = {"arm": "arm_b", "held": True, "reason": "b", "incident_ids": []}
    partial = client.post("/api/fleet/pipeline/arm-holds/clear",
                          json={"arm_id": "arm_a", "note": "cleared a"}, headers=op)
    assert partial.status_code == 200 and partial.json()["cleared_cells"] == []
    assert app.state.arm_holds["arm_a"]["held"] is False and app.state.arm_holds["arm_b"]["held"] is True
    assert app.state.omx_cell_states["cell_ab"]["phase"] == "ABORTED"

    done = client.post("/api/fleet/pipeline/arm-holds/clear",
                       json={"arm_id": "arm_b", "note": "cleared b"}, headers=op)
    assert done.status_code == 200 and done.json()["cleared_cells"] == ["cell_ab"]
    assert app.state.omx_cell_states["cell_ab"]["phase"] == "IDLE"
    assert app.state.omx_cell_states["cell_ab"]["amr_motion_inhibited"] is False
