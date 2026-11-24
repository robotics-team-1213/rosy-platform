"""Wave 2 & Wave 3 Harbor-ROSY integration regression tests (P1-1, P1-3, P1-8, P2-2, P2-4)."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from core_common.protocol.port_events import PortEvent, event_id
from fakes import FakeRobot
from fleet.pipeline.cell_site_targets import list_canonical_sites
from fleet.server.app import create_app
from fleet.server.auth.site_auth import build_authorize, build_role_guards
from fleet.server.console import FleetConsole, RobotEndpoint
from fleet.server.mission_service import MissionService
from fleet.server.mission_store import MissionStore
from fleet.server.work.port_event_routes import install_port_event_routes, read_page
from fleet.server.port_event_store import PortEventStore
from fleet.server.proposal_store import ProposalStore
from fleet.server.site_map_store import SiteMapStore
from fleet.server.sitemap.pipeline_routes import install_pipeline_routes
from fleet.server.task_service import FleetTaskService, FleetTaskStore
from fleet.site_map import SiteMap
from fleet.site_rules import SiteRules
from rosy_account.principal import SitePrincipal
from tools.sim.bay_departure_sim import build_world_261026_site_map

VIEW = {"Authorization": "Bearer viewer"}
SVC = {"Authorization": "Bearer harbor-svc"}
OWNER = {"Authorization": "Bearer cell-owner-svc"}
OP = {"Authorization": "Bearer operator"}
ROBOT = "rosy_01"
T = datetime(2026, 11, 25, 0, 0, tzinfo=timezone.utc)


def _cell_plan_app(monkeypatch, *, tmp_path=None):
    monkeypatch.setenv("ROSY_FLEET_CELL_AB_RELEASE_ENABLED", "1")
    monkeypatch.setenv("ROSY_FLEET_CELL_OWNERS", "cell_ab=cell-owner;cell_s=cell-owner")
    site, graph, _ = build_world_261026_site_map()
    maps = SimpleNamespace(active=lambda: (1, site, graph, None), rules=SimpleNamespace(active_rules=lambda: None))
    owner_evidence: dict[str, dict] = {}
    app = FastAPI()
    principals = {
        hashlib.sha256(t.encode()).hexdigest(): SitePrincipal(p, r)
        for t, p, r in (
            ("viewer", "viewer-1", "viewer"),
            ("harbor-svc", "harbor-service", "service"),
            ("cell-owner-svc", "cell-owner", "service"),
            ("operator", "console-human", "operator"),
        )
    }
    authorize = build_authorize(None, principals, None)
    require_viewer, require_operator, _, require_proposer = build_role_guards(authorize, principals)
    app.state.operator_guard = [Depends(require_operator)]
    app.state.proposer_guard = [Depends(require_proposer)]
    if tmp_path is not None:
        app.state.pipeline_governance_db_path = tmp_path / "gov.sqlite3"
        install_port_event_routes(
            app, None, SimpleNamespace(store=SimpleNamespace(path=tmp_path / "fleet.sqlite3")),
            authorize=authorize, require_viewer=require_viewer,
        )
    install_pipeline_routes(
        app, site_maps=maps, read_guard=[Depends(require_viewer)],
        omx_evidence_fn=lambda t: owner_evidence.get(t["task_id"]),
    )
    return app, owner_evidence


def _complete_step(client: TestClient, owner_ev: dict, task_id: str):
    claimed = client.post(
        "/api/fleet/pipeline/cell-tasks/claim", headers=OWNER,
        json={"cell_id": "cell_ab", "task_id": task_id},
    ).json()
    assert claimed["claimed"] is True, claimed
    handoff = claimed["handoff"]
    assert "object_ref" not in handoff and "identity" not in handoff
    place = {
        "area": handoff["dst_area"], "site": handoff["dst_site"], "site_id": handoff["dst_site_id"],
        "tier": handoff["tier"], **(handoff.get("dst_slot") or {}),
    }
    stage = {
        "directive_id": task_id, "arm_id": handoff["arm_id"], "task_verified": True,
        "verification": {"verified": True, "basis": "predefined_side_and_top_target_zones", "z_gate": {"verdict": "PASS"}, "target": dict(place)},
        "place": place,
    }
    hardware = {"stop_event": {"ok": True, "folded": True, "state": [0.0] * 6}}
    digest = "sha256:" + hashlib.sha256(json.dumps({
        "task_id": task_id, "lease": handoff["handoff_lease_id"], "stage_result": stage, "hardware_telemetry": hardware,
    }, sort_keys=True).encode()).hexdigest()
    owner_ev[task_id] = {
        "receipt": {
            "handoff_lease_id": handoff["handoff_lease_id"], "cell_id": "cell_ab", "stage_id": task_id,
            "phase": "RELEASED", "physical_completion": True, "simulated_success": False,
            "goal_evidence_digest": digest,
        },
        "stage_result": stage, "hardware_telemetry": hardware,
    }
    done = client.post(f"/api/fleet/pipeline/cell-tasks/{task_id}/complete", headers=OWNER, json={
        "phase": "RELEASED",
        "goal_evidence_digest": digest,
        "receipt": owner_ev[task_id]["receipt"],
        "stage_result": stage,
        "hardware_telemetry": hardware,
    })
    assert done.status_code == 200 and done.json()["task"]["status"] == "COMPLETED", done.text


def test_p1_1_cell_plan_tasks_carry_identity_and_emit_container_stored_while_stripping_service_views(monkeypatch, tmp_path):
    app, owner_ev = _cell_plan_app(monkeypatch, tmp_path=tmp_path)
    client = TestClient(app)

    created = client.post("/api/fleet/pipeline/cell-plans", headers=SVC, json={
        "mode": "harbor_plan",
        "request_key": "p1-1-identity-plan",
        "steps": [
            {"cargo_id": "CNTR-P1-1", "src_site": "yard-r1-c1-l1", "dst_site": "temp_a-r1-c1-l1", "arm_id": "arm_a"},
        ],
    })
    assert created.status_code == 200, created.text
    svc_task = created.json()["tasks"][0]
    assert "object_ref" not in svc_task and "identity" not in svc_task

    op_plan = client.get(f"/api/fleet/pipeline/cell-plans/{created.json()['plan']['plan_id']}", headers=VIEW).json()
    assert op_plan["tasks"][0]["object_ref"] == "CNTR-P1-1"
    assert op_plan["tasks"][0]["identity"] == "attested"

    rdy = client.get("/api/fleet/pipeline/cells/cell_ab/readiness", headers=VIEW).json()
    snap = app.state.pipeline_governance.snapshot()
    admitted = client.post(f"/api/fleet/pipeline/cell-plans/{created.json()['plan']['plan_id']}/admit", headers=OP, json={
        "expected_dispatch_generation": snap["dispatch_generation"],
        "expected_stop_generation": snap["stop_generation"],
        "expected_readiness_digest": rdy["readiness_digest"],
    })
    assert admitted.status_code == 200, admitted.text
    _complete_step(client, owner_ev, svc_task["task_id"])

    events = client.get("/api/fleet/port-events", headers=VIEW).json()["events"]
    assert len(events) == 1
    assert events[0]["kind"] == "container.stored"
    assert events[0]["object_ref"] == "CNTR-P1-1"
    assert events[0]["slot_ref"] == "temp_a-r1-c1-l1"
    assert events[0]["identity"] == "attested"


def test_p1_1_does_not_promote_synthetic_inbound_cargo_id_without_caller_cargo(monkeypatch):
    app, _ = _cell_plan_app(monkeypatch)
    client = TestClient(app)
    res = client.post("/api/fleet/pipeline/cell-plans", headers=OP, json={
        "mode": "harbor_plan",
        "state": {"C_EX": "yard-r1-c1-l1"},
        "steps": [{"src_site": "belt", "dst_site": "yard-r1-c4-l1", "arm_id": "arm_a"}],
    })
    assert res.status_code == 200, res.text
    task = res.json()["tasks"][0]
    assert "object_ref" not in task and "identity" not in task


def test_p1_3_batch_plan_admit_guards_atomicity_and_cancel_health(monkeypatch, tmp_path):
    app, _ = _cell_plan_app(monkeypatch, tmp_path=tmp_path)
    client = TestClient(app)
    created = client.post("/api/fleet/pipeline/cell-plans", headers=SVC, json={
        "mode": "rehandle",
        "state": {"C1": "yard-r1-c1-l1", "C2": "yard-r1-c1-l2"},
        "cargo_id": "C1",
    })
    assert created.status_code == 200, created.text
    plan_id = created.json()["plan"]["plan_id"]
    tasks = created.json()["tasks"]
    assert len(tasks) >= 2 and all(t["status"] == "PROPOSED" for t in tasks)

    rdy = client.get("/api/fleet/pipeline/cells/cell_ab/readiness", headers=VIEW).json()
    snap = app.state.pipeline_governance.snapshot()
    cas_body = {
        "expected_dispatch_generation": snap["dispatch_generation"],
        "expected_stop_generation": snap["stop_generation"],
        "expected_readiness_digest": rdy["readiness_digest"],
    }

    assert client.post(f"/api/fleet/pipeline/cell-plans/{plan_id}/admit", headers=SVC, json=cas_body).status_code == 403

    op_plan = client.post("/api/fleet/pipeline/cell-plans", headers=OP, json={
        "mode": "harbor_plan",
        "propose": True,
        "steps": [{"src_site": "yard-r1-c4-l1", "dst_site": "temp_a-r1-c1-l1", "arm_id": "arm_a"}],
    }).json()["plan"]["plan_id"]
    assert client.post(f"/api/fleet/pipeline/cell-plans/{op_plan}/admit", headers=OP, json=cas_body).status_code == 403

    stale = client.post(f"/api/fleet/pipeline/cell-plans/{plan_id}/admit", headers=OP, json={
        **cas_body, "expected_dispatch_generation": snap["dispatch_generation"] + 99,
    })
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "STALE_FAILURE_CONTEXT"

    app.state.arm_transfer_job_store = SimpleNamespace(has_active_transfer=lambda: True)
    conflict = client.post(f"/api/fleet/pipeline/cell-plans/{plan_id}/admit", headers=OP, json=cas_body)
    assert conflict.status_code == 409 and conflict.json()["detail"]["code"] == "CELL_WORK_CONFLICT"
    app.state.arm_transfer_job_store = None

    rdy = client.get("/api/fleet/pipeline/cells/cell_ab/readiness", headers=VIEW).json()
    snap = app.state.pipeline_governance.snapshot()
    cas_body = {
        "expected_dispatch_generation": snap["dispatch_generation"],
        "expected_stop_generation": snap["stop_generation"],
        "expected_readiness_digest": rdy["readiness_digest"],
    }

    admitted = client.post(f"/api/fleet/pipeline/cell-plans/{plan_id}/admit", headers=OP, json=cas_body)
    assert admitted.status_code == 200, admitted.text
    body = admitted.json()
    assert body["plan"]["status"] == "QUEUED"
    assert len(body["admitted_task_ids"]) == len(tasks)
    assert all(t["status"] == "QUEUED" for t in body["tasks"])
    assert body["dispatch_generation"] == snap["dispatch_generation"] + 1

    cancelled = client.post(f"/api/fleet/pipeline/cell-plans/{plan_id}/cancel", headers=SVC, json={"reason": "test cancel"})
    assert cancelled.status_code == 200
    assert cancelled.json()["plan"]["status"] == "CANCELLED"
    assert all("health_summary" in t for t in cancelled.json()["tasks"])


def test_p2_4_dry_run_redacts_cargo_id_for_service_only(monkeypatch):
    app, _ = _cell_plan_app(monkeypatch)
    client = TestClient(app)
    payload = {
        "mode": "rehandle",
        "state": {"C1": "yard-r1-c1-l1", "C2": "yard-r1-c1-l2"},
        "cargo_id": "C1",
    }
    svc_res = client.post("/api/fleet/pipeline/cell-plans/dry-run", headers=SVC, json=payload)
    assert svc_res.status_code == 200
    assert svc_res.json()["final_state"] is None
    assert all("cargo_id" not in m for m in svc_res.json()["moves"])

    view_res = client.post("/api/fleet/pipeline/cell-plans/dry-run", headers=VIEW, json=payload)
    assert view_res.status_code == 200
    assert isinstance(view_res.json()["final_state"], dict)


def test_p1_8_cell_site_targets_reloads_on_mtime_change(tmp_path):
    src = list_canonical_sites()
    target = tmp_path / "cell-site-map.json"
    raw = json.loads(
        (list_canonical_sites.__globals__["_map_path"]()).read_text(encoding="utf-8")
    )
    raw["revision"] = 101
    target.write_text(json.dumps(raw), encoding="utf-8")
    first = list_canonical_sites(web_common=tmp_path)
    assert first["revision"] == 101 and first["count"] == src["count"]

    raw["revision"] = 202
    target.write_text(json.dumps(raw) + "\n", encoding="utf-8")
    second = list_canonical_sites(web_common=tmp_path)
    assert second["revision"] == 202


def test_p2_4_trip_precheck_rejects_charge_and_unverified_exit_while_allowing_junction_via(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    site_maps = SiteMapStore(path)
    tasks = FleetTaskService(FleetTaskStore(path), robot_ids=(ROBOT,))
    users = {hashlib.sha256(t.encode()).hexdigest(): {"principal_id": p, "role": r} for t, (p, r) in {
        "viewer-s": ("viewer-1", "viewer"),
        "harbor-s": ("harbor-service", "service"),
        "op-s": ("operator-1", "operator"),
    }.items()}
    app = create_app(
        FleetConsole([RobotEndpoint(ROBOT, "http://127.0.0.1:8080", "robot-token")], [FakeRobot(ROBOT)]),
        task_service=tasks, site_users=users, deployment_profile="simulation", site_maps=site_maps,
        mission_service=MissionService(MissionStore(path)), proposal_store=ProposalStore(path),
    )
    tasks.store.rearm_dispatch(expected_generation=tasks.store.dispatch_control()["generation"], actor_id="operator-1")
    site_map = SiteMap.model_validate({
        "schema": "rosy.site_map/1",
        "map_id": "test",
        "places": [
            {"id": "J1", "kind": "junction", "name": "분기", "x": 0.0, "y": 0.0},
            {"id": "C1", "kind": "charge", "name": "충전1", "x": 0.2, "y": 0.0, "yaw": 0.0, "pinned": True},
            {"id": "S_OUT", "kind": "stop", "name": "반출", "x": 0.5, "y": 0.0, "yaw": 0.0, "pinned": True,
             "stop_zone": [[0.4, -0.1], [0.6, -0.1], [0.6, 0.1], [0.4, 0.1]], "approach_m": 0.15},
            {"id": "S_EXIT", "kind": "stop", "name": "출구", "x": 0.8, "y": 0.0, "yaw": 0.0, "pinned": True},
        ],
        "edges": [
            {"id": "e1", "from": "J1", "to": "S_OUT", "polyline": [[0.0, 0.0], [0.5, 0.0]],
             "direction": "two_way", "width_m": 0.2, "speed_cap_mps": 0.1, "drive_mode": "free", "pinned": True},
        ],
    })
    d = site_maps.save_draft(site_map, expected_revision=site_maps.draft_view()["revision"], principal_id="operator-1")
    site_maps.activate(expected_revision=d["revision"], principal_id="operator-1", route_active=False)
    rules = SiteRules.model_validate({"return": {"exit_place": "S_EXIT"}, "stops": [{"place": "S_OUT", "role": "load"}]})
    rd = site_maps.rules.save_draft(rules, expected_revision=site_maps.rules.draft_view()["revision"], principal_id="operator-1")
    site_maps.rules.activate(expected_revision=rd["revision"], principal_id="operator-1", route_active=False)

    client = TestClient(app)
    hdr = {"Authorization": "Bearer harbor-s", "X-Request-Id": "req-wave23-1"}
    r_charge = client.post("/api/fleet/trip-proposals", headers=hdr, json={
        "candidate_robot_ids": [ROBOT], "request_key": "charge-dest", "steps": [{"to": "C1", "via": ["J1"]}],
    })
    assert r_charge.status_code == 422 and r_charge.json()["detail"]["code"] == "TRIP_STOP_NOT_DISPATCHABLE"
    assert r_charge.headers.get("X-Request-Id") == "req-wave23-1"

    r_exit = client.post("/api/fleet/trip-proposals", headers=hdr, json={
        "candidate_robot_ids": [ROBOT], "request_key": "exit-unverified", "steps": [{"to": "S_EXIT", "via": ["J1"]}],
    })
    assert r_exit.status_code == 422 and r_exit.json()["detail"]["code"] == "TRIP_STOP_NOT_DISPATCHABLE"

    r_ok = client.post("/api/fleet/trip-proposals", headers={"Authorization": "Bearer harbor-s"}, json={
        "candidate_robot_ids": [ROBOT], "request_key": "sout-via-junction", "steps": [{"to": "S_OUT", "via": ["J1"]}],
    })
    assert r_ok.status_code == 200, r_ok.text
    assert len(r_ok.headers.get("X-Request-Id", "")) >= 16


def test_p2_2_port_events_fair_budget_prevents_child_starvation(tmp_path):
    import asyncio

    store = PortEventStore(tmp_path / "local.sqlite3")
    for i in range(1, 7):
        store.append("local", PortEvent(
            event_id=event_id("local", f"loc-{i}", "container.stored"),
            kind="container.stored", observation_ref=f"loc-{i}",
            object_ref=f"CNTR-L{i}", slot_ref="yard-r1-c1-l1", identity="attested", observed_at=T,
        ))
    child_rows = [
        {
            "seq": i,
            "event": PortEvent(
                event_id=event_id("cell-a", f"c-{i}", "container.stored"),
                kind="container.stored", observation_ref=f"c-{i}",
                object_ref=f"CNTR-C{i}", slot_ref="yard-r1-c2-l1", identity="attested", observed_at=T,
            ).model_dump(mode="json"),
        }
        for i in range(1, 5)
    ]

    async def _peer_events(source, after, budget):
        return {"rows": [r for r in child_rows if r["seq"] > after][:budget]}

    control = SimpleNamespace(
        unit=SimpleNamespace(unit_id="root", children=[SimpleNamespace(unit_id="cell-a", resources=("workcell:a",))]),
        topology=SimpleNamespace(units={"cell-a": SimpleNamespace(unit_id="cell-a", parent="root", resources=("workcell:a",))}),
        peer=SimpleNamespace(port_events=_peer_events),
    )
    page = asyncio.run(read_page(store, control, cursor=None, limit=4))
    objs = [ev["object_ref"] for ev in page["events"]]
    assert page["complete"] is False
    assert any(o.startswith("CNTR-L") for o in objs) and any(o.startswith("CNTR-C") for o in objs)
