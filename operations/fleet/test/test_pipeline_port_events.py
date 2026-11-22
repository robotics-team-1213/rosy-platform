"""Tests for bridging verified OMX cell-task completions into D-996 port events."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from types import SimpleNamespace

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
import pytest

from core_common.protocol.port_events import PortEvent
from fleet.server.auth.site_auth import build_authorize, build_role_guards
from fleet.server.sitemap.pipeline_port_events import (
    CLAIM_STRIP_FIELDS,
    flush_pending_port_events,
)
from fleet.server.sitemap.pipeline_routes import install_pipeline_routes
from fleet.server.work.port_event_routes import install_port_event_routes
from fleet.server.work.port_event_store import PortEventConflict
from rosy_account.principal import SitePrincipal
from tools.sim.bay_departure_sim import build_world_261026_site_map

VIEW = {"Authorization": "Bearer viewer"}
SVC = {"Authorization": "Bearer service"}
OP = {"Authorization": "Bearer operator"}


def _build_app(monkeypatch, tmp_path, *, guarded: bool = False):
    monkeypatch.setenv("ROSY_FLEET_CELL_AB_RELEASE_ENABLED", "1")
    site, graph, _ = build_world_261026_site_map()
    maps = SimpleNamespace(active=lambda: (1, site, graph, None), rules=SimpleNamespace(active_rules=lambda: None))
    owner_evidence: dict[str, dict] = {}
    app = FastAPI()
    if guarded:
        principals = {
            hashlib.sha256(t.encode()).hexdigest(): SitePrincipal(t, t)
            for t in ("viewer", "service", "operator")
        }
        authorize = build_authorize(None, principals, None)
        require_viewer, require_operator, _, require_proposer = build_role_guards(authorize, principals)
        app.state.operator_guard = [Depends(require_operator)]
        app.state.proposer_guard = [Depends(require_proposer)]
        read_guard = [Depends(require_viewer)]
        port_auth, port_view = authorize, require_viewer
    else:
        read_guard = ()

        def open_viewer(x_who: str = Header("harbor")):
            return SitePrincipal(x_who, "service")

        port_auth, port_view = open_viewer, open_viewer

    def amr_ev(task):
        return {
            "robot_id": task["robot_id"], "cell_id": task["cell_id"], "observed_at": time.time(),
            "pose": dict(task["pose"]), "wheel_brake_locked": True, "bed_ready": True, "v_cmd_mps": 0.0,
        }

    install_port_event_routes(
        app, None, SimpleNamespace(store=SimpleNamespace(path=tmp_path / "fleet.sqlite3")),
        authorize=port_auth, require_viewer=port_view,
    )
    install_pipeline_routes(
        app, site_maps=maps, read_guard=read_guard,
        amr_evidence_fn=amr_ev, omx_evidence_fn=lambda t: owner_evidence.get(t["task_id"]),
    )
    return app, owner_evidence


def _complete_ab_payload(task_id: str, lease: str, arm_id: str, place: dict):
    verification = {
        "verified": True, "basis": "predefined_side_and_top_target_zones",
        "z_gate": {"verdict": "PASS"}, "target": dict(place),
    }
    stage = {"directive_id": task_id, "arm_id": arm_id, "task_verified": True, "verification": verification, "place": place}
    hardware = {"stop_event": {"ok": True, "folded": True, "state": [0.0] * 6}}
    evidence = {"task_id": task_id, "lease": lease, "stage_result": stage, "hardware_telemetry": hardware}
    digest = "sha256:" + hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
    receipt = {
        "handoff_lease_id": lease, "cell_id": "cell_ab", "stage_id": task_id,
        "phase": "RELEASED", "physical_completion": True, "simulated_success": False,
        "goal_evidence_digest": digest,
    }
    return receipt, stage, hardware, digest


def _complete_s_payload(task_id: str, lease: str, objects: int):
    verification = {"verified": True, "basis": "top_camera_only_target_zone"}
    stage = {
        "directive_id": task_id, "arm_id": "arm_s", "task_verified": True,
        "verification": verification, "source_clearance": {"objects": objects},
    }
    hardware = {"stop_event": {"ok": True, "folded": True, "state": [0.0] * 6}}
    evidence = {"task_id": task_id, "lease": lease, "stage_result": stage, "hardware_telemetry": hardware}
    digest = "sha256:" + hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
    receipt = {
        "handoff_lease_id": lease, "cell_id": "cell_s", "stage_id": task_id,
        "phase": "RELEASED", "physical_completion": True, "simulated_success": False,
        "goal_evidence_digest": digest,
    }
    return receipt, stage, hardware, digest


def _run_ab_task(client, owner_ev: dict, task_id: str, headers=None):
    kw = {"headers": headers} if headers else {}
    claimed = client.post("/api/fleet/pipeline/cell-tasks/claim", json={"cell_id": "cell_ab", "task_id": task_id}, **kw)
    body = claimed.json()
    assert body["claimed"] is True
    handoff = body["handoff"]
    place = {
        "area": handoff["dst_area"], "site": handoff["dst_site"], "site_id": handoff["dst_site_id"],
        "tier": handoff["tier"], **(handoff.get("dst_slot") or {}),
    }
    if handoff["dst_site_id"] is None:
        place.pop("site_id", None)
    receipt, stage, hardware, digest = _complete_ab_payload(task_id, handoff["handoff_lease_id"], handoff["arm_id"], place)
    owner_ev[task_id] = {"receipt": receipt, "stage_result": stage, "hardware_telemetry": hardware}
    done = client.post(f"/api/fleet/pipeline/cell-tasks/{task_id}/complete", json={
        "phase": "RELEASED", "goal_evidence_digest": digest,
        "receipt": receipt, "stage_result": stage, "hardware_telemetry": hardware,
    }, **kw)
    return body, done


def test_backwards_compatibility_and_legacy_pallet_emit_no_events(monkeypatch, tmp_path):
    app, owner_ev = _build_app(monkeypatch, tmp_path)
    client = TestClient(app)
    r1 = client.post("/api/fleet/pipeline/cell-tasks", json={
        "task_id": "plain-canonical", "cell_id": "cell_ab", "dst_site": "yard:r1-s1-t1",
    })
    assert r1.status_code == 200 and r1.json()["task"]["dst_wire_ref"] == "yard-r1-c1-l1"
    _, d1 = _run_ab_task(client, owner_ev, "plain-canonical")
    assert d1.status_code == 200

    r2 = client.post("/api/fleet/pipeline/cell-tasks", json={
        "task_id": "legacy-pallet", "cell_id": "cell_ab", "dst_site": "pallet-l0",
        "object_ref": "CNTR-LEG", "identity": "attested",
    })
    assert r2.status_code == 200 and r2.json()["task"]["dst_wire_ref"] is None
    _, d2 = _run_ab_task(client, owner_ev, "legacy-pallet")
    assert d2.status_code == 200
    assert client.get("/api/fleet/port-events").json()["events"] == []


@pytest.mark.parametrize("payload, expected_code", [
    ({"cell_id": "cell_ab", "dst_site": "yard:r1-s1-t1", "object_ref": "CNTR-1"}, "INVALID_CELL_TASK_INPUT"),
    ({"cell_id": "cell_ab", "dst_site": "yard:r1-s1-t1", "identity": "attested"}, "INVALID_CELL_TASK_INPUT"),
    ({"cell_id": "cell_ab", "dst_site": "yard:r1-s1-t1", "object_ref": None, "identity": "attested"}, "INVALID_CELL_TASK_INPUT"),
    ({"cell_id": "cell_ab", "dst_site": "yard:r1-s1-t1", "object_ref": " bad ", "identity": "attested"}, "INVALID_CELL_TASK_INPUT"),
    ({"cell_id": "cell_ab", "dst_site": "yard:r1-s1-t1", "object_ref": "X" * 129, "identity": "attested"}, "INVALID_CELL_TASK_INPUT"),
    ({"cell_id": "cell_ab", "dst_site": "yard:r1-s1-t1", "object_ref": "C\n1", "identity": "attested"}, "INVALID_CELL_TASK_INPUT"),
    ({"cell_id": "cell_ab", "dst_site": "yard:r1-s1-t1", "object_ref": "CNTR-1", "identity": "inferred"}, "INVALID_CELL_TASK_INPUT"),
    ({"cell_id": "cell_ab", "dst_site": "yard:r1-s1-t1", "object_ref": "CNTR-1", "identity": "observed"}, "IDENTITY_EVIDENCE_REQUIRED"),
    ({"cell_id": "cell_ab", "dst_site": "yard:r1-s1", "tiers": [1, 2], "object_ref": "CNTR-1", "identity": "attested"}, "INVALID_CELL_TASK_INPUT"),
    ({"preset": "full_s3_to_s5_pipeline", "object_ref": "CNTR-1", "identity": "attested"}, "INVALID_CELL_TASK_INPUT"),
    ({"cell_id": "cell_ab", "dst_site": "yard:r1-s1-t1", "emit_release_permit": True}, "INVALID_CELL_TASK_INPUT"),
    ({"cell_id": "cell_s", "emit_release_permit": "yes"}, "INVALID_CELL_TASK_INPUT"),
])
def test_identity_and_permit_validation_errors(monkeypatch, tmp_path, payload, expected_code):
    app, _ = _build_app(monkeypatch, tmp_path)
    client = TestClient(app)
    res = client.post("/api/fleet/pipeline/cell-tasks", json=payload)
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == expected_code
    assert app.state.omx_cell_tasks == {}


def test_claim_isolates_cargo_identity_and_complete_emits_container_stored(monkeypatch, tmp_path):
    app, owner_ev = _build_app(monkeypatch, tmp_path, guarded=True)
    client = TestClient(app)
    res = client.post("/api/fleet/pipeline/cell-tasks", json={
        "task_id": "store-c1", "cell_id": "cell_ab", "dst_site": "yard:r1-s1-t1",
        "object_ref": "CNTR-101", "identity": "attested",
    }, headers=OP)
    assert res.status_code == 200
    created_task = res.json()["task"]
    assert created_task["identity_attested_by"] == "operator"
    assert created_task["dst_wire_ref"] == "yard-r1-c1-l1"

    # Enqueue a blocked dependent task to verify refusal branches also strip identity fields
    res_obs = client.post("/api/fleet/pipeline/cell-tasks", json={
        "task_id": "store-c2", "cell_id": "cell_ab", "dst_site": "yard:r1-s1-t2",
        "depends_on": "store-c1",
        "object_ref": "CNTR-102", "identity": "observed", "identity_observation_ref": "wrist-reading-2",
    }, headers=OP)
    assert res_obs.status_code == 200

    refused = client.post("/api/fleet/pipeline/cell-tasks/claim", json={"cell_id": "cell_ab", "task_id": "store-c2"}, headers=SVC).json()
    assert refused["claimed"] is False
    assert CLAIM_STRIP_FIELDS.isdisjoint(refused["task"])

    claim_body, done = _run_ab_task(client, owner_ev, "store-c1", headers=SVC)
    assert CLAIM_STRIP_FIELDS.isdisjoint(claim_body["task"])
    assert CLAIM_STRIP_FIELDS.isdisjoint(claim_body["handoff"])
    assert done.status_code == 200
    assert "pending_port_events" not in app.state.omx_cell_tasks["store-c1"]

    _, done2 = _run_ab_task(client, owner_ev, "store-c2", headers=SVC)
    assert done2.status_code == 200

    page = client.get("/api/fleet/port-events", headers=VIEW).json()
    assert page["complete"] is True and len(page["events"]) == 2
    ev1, ev2 = [PortEvent.model_validate(e) for e in page["events"]]
    assert ev1.kind == "container.stored" and ev1.object_ref == "CNTR-101"
    assert ev1.slot_ref == "yard-r1-c1-l1" and ev1.identity == "attested"
    assert ev1.observation_ref.startswith("cell-task:") and "arm_a" not in ev1.observation_ref
    assert ev2.object_ref == "CNTR-102" and ev2.slot_ref == "yard-r1-c1-l2" and ev2.identity == "observed"


def test_aborted_retry_repark_and_durable_outbox_fault_tolerance(monkeypatch, tmp_path):
    app, owner_ev = _build_app(monkeypatch, tmp_path)
    client = TestClient(app)
    client.post("/api/fleet/pipeline/cell-tasks", json={
        "task_id": "ab-err", "cell_id": "cell_ab", "dst_site": "yard:r1-s2-t1",
        "object_ref": "CNTR-202", "identity": "observed", "identity_observation_ref": "conv-read-9",
    })
    claimed = client.post("/api/fleet/pipeline/cell-tasks/claim", json={"cell_id": "cell_ab", "task_id": "ab-err"}).json()
    assert claimed["claimed"] is True
    abort_res = client.post("/api/fleet/pipeline/cell-tasks/ab-err/complete", json={
        "phase": "ABORTED",
        "stage_result": {"reach_fix": {"need_arm_dxdy_m": [0.02, 0.0]}},
    })
    assert abort_res.status_code == 200
    assert client.get("/api/fleet/port-events").json()["events"] == []

    # Retry preserves identity fields
    retried = client.post("/api/fleet/pipeline/cell-tasks/ab-err/retry").json()["task"]
    assert retried["object_ref"] == "CNTR-202"
    assert retried["identity"] == "observed"
    assert retried["identity_observation_ref"] == "conv-read-9"

    # Repark DONE also carries over identity fields
    repark_req = app.state.repark_requests["rosy_01"]
    closed = client.post(f"/api/fleet/pipeline/repark/{repark_req['request_id']}", json={"state": "DONE"}).json()
    rp_task = app.state.omx_cell_tasks[closed["request"]["retry_task_id"]]
    assert rp_task["object_ref"] == "CNTR-202" and rp_task["identity_observation_ref"] == "conv-read-9"

    # Simulated SQLite outage on first append retains pending_port_events; retry flush drains it
    real_append = app.state.port_event_store.append

    def broken_append(source, ev):
        raise sqlite3.OperationalError("disk busy")

    monkeypatch.setattr(app.state.port_event_store, "append", broken_append)
    _, done = _run_ab_task(client, owner_ev, retried["task_id"])
    assert done.status_code == 200
    assert len(app.state.omx_cell_tasks[retried["task_id"]].get("pending_port_events", [])) == 1

    monkeypatch.setattr(app.state.port_event_store, "append", real_append)
    assert flush_pending_port_events(app) == 1
    assert "pending_port_events" not in app.state.omx_cell_tasks[retried["task_id"]]
    assert len(client.get("/api/fleet/port-events").json()["events"]) == 1

    # PortEventConflict drops conflicting pending entry without raising
    def conflict_append(source, ev):
        raise PortEventConflict("conflict")

    app.state.omx_cell_tasks[retried["task_id"]]["pending_port_events"] = [
        {"source": "cell_ab", "event": client.get("/api/fleet/port-events").json()["events"][0]},
    ]
    monkeypatch.setattr(app.state.port_event_store, "append", conflict_append)
    assert flush_pending_port_events(app) == 1
    assert "pending_port_events" not in app.state.omx_cell_tasks[retried["task_id"]]


def test_cell_s_opt_in_release_permit_gating(monkeypatch, tmp_path):
    app, owner_ev = _build_app(monkeypatch, tmp_path)
    client = TestClient(app)

    def run_s(task_id: str, objects: int, *, emit: bool = False, batch: bool = False):
        spec = {
            "task_id": task_id, "cell_id": "cell_s", "arm_id": "arm_s", "robot_id": "rosy_46",
            "src_site": "pinky", "dst_site": "belt", "tier": 1,
        }
        if emit:
            spec["emit_release_permit"] = True
        if batch:
            spec.update(unload_batch_id="batch-1", unload_index=0 if task_id.endswith("1") else 1)
        assert client.post("/api/fleet/pipeline/cell-tasks", json=spec).status_code == 200
        claimed = client.post("/api/fleet/pipeline/cell-tasks/claim", json={"cell_id": "cell_s", "task_id": task_id}).json()
        assert claimed["claimed"] is True
        lease = claimed["handoff"]["handoff_lease_id"]
        receipt, stage, hardware, digest = _complete_s_payload(task_id, lease, objects)
        owner_ev[task_id] = {"receipt": receipt, "stage_result": stage, "hardware_telemetry": hardware}
        res = client.post(f"/api/fleet/pipeline/cell-tasks/{task_id}/complete", json={
            "phase": "RELEASED", "goal_evidence_digest": digest,
            "receipt": receipt, "stage_result": stage, "hardware_telemetry": hardware,
        })
        assert res.status_code == 200

    # 1. Default omits emit_release_permit -> emits nothing
    run_s("s-default", 0, emit=False)
    assert client.get("/api/fleet/port-events").json()["events"] == []

    # 2. When app.state.intake exists -> does not double-emit
    app.state.intake = object()
    run_s("s-with-intake", 0, emit=True)
    assert client.get("/api/fleet/port-events").json()["events"] == []
    delattr(app.state, "intake")

    # 3. Unload batch with remaining cargo (objects=1) stays CLAIMED and emits nothing; objects=0 releases once
    run_s("s-b1", 1, emit=True, batch=True)
    assert client.get("/api/fleet/port-events").json()["events"] == []
    run_s("s-b2", 0, emit=True, batch=True)
    events = client.get("/api/fleet/port-events").json()["events"]
    assert len(events) == 1
    assert events[0]["kind"] == "vehicle.release_permitted" and events[0]["vehicle_id"] == "rosy_46"

    # 4. Single non-batch cell_s task with src_site="pinky" and emit_release_permit=True also emits once
    run_s("s-single", 0, emit=True, batch=False)
    events = client.get("/api/fleet/port-events").json()["events"]
    assert len(events) == 2
    assert events[1]["kind"] == "vehicle.release_permitted" and events[1]["vehicle_id"] == "rosy_46"
