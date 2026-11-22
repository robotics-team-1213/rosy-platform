"""Canonical 37-site coordinate lookup, Harbor wire conversion, and 1-3 tier Fleet task pipeline tests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from fleet.server.auth.site_auth import build_authorize, build_role_guards
from fleet.server.sitemap.pipeline_routes import install_pipeline_routes
from rosy_account.principal import SitePrincipal
from tools.sim.bay_departure_sim import build_world_261026_site_map

VIEW = {"Authorization": "Bearer viewer"}
SVC = {"Authorization": "Bearer service"}
OP = {"Authorization": "Bearer operator"}


def _app(monkeypatch, *, guarded: bool = False):
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
        require_viewer, require_operator, _, require_proposer = build_role_guards(
            build_authorize(None, principals, None), principals)
        app.state.operator_guard = [Depends(require_operator)]
        app.state.proposer_guard = [Depends(require_proposer)]
        read_guard = [Depends(require_viewer)]
    else:
        read_guard = ()

    def amr_ev(task):
        return {
            "robot_id": task["robot_id"], "cell_id": task["cell_id"], "observed_at": time.time(),
            "pose": dict(task["pose"]), "wheel_brake_locked": True, "bed_ready": True, "v_cmd_mps": 0.0,
        }

    install_pipeline_routes(
        app, site_maps=maps, read_guard=read_guard,
        amr_evidence_fn=amr_ev, omx_evidence_fn=lambda t: owner_evidence.get(t["task_id"]),
    )
    return app, owner_evidence


def _complete_payload(
    task_id: str, lease: str, arm_id: str, place: dict, *, z_verdict: str = "PASS", target: dict | None = None,
    include_target: bool = True,
):
    tgt = dict(place) if target is None else target
    verification = {
        "verified": True, "basis": "predefined_side_and_top_target_zones",
        "z_gate": {"verdict": z_verdict},
        **({"target": tgt} if include_target else {}),
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


def _complete_one(client, owner_evidence: dict, task_id: str, *, place: dict | None = None, z_verdict: str = "PASS"):
    claimed = client.post("/api/fleet/pipeline/cell-tasks/claim", json={"cell_id": "cell_ab", "task_id": task_id}).json()
    assert claimed["claimed"] is True
    handoff = claimed["handoff"]
    lease = handoff["handoff_lease_id"]
    resolved_place = place or {
        "area": handoff["dst_area"], "site": handoff["dst_site"], "site_id": handoff["dst_site_id"],
        "tier": handoff["tier"], **(handoff.get("dst_slot") or {}),
    }
    receipt, stage, hardware, digest = _complete_payload(task_id, lease, handoff["arm_id"], resolved_place, z_verdict=z_verdict)
    owner_evidence[task_id] = {"receipt": receipt, "stage_result": stage, "hardware_telemetry": hardware}
    return handoff, client.post(f"/api/fleet/pipeline/cell-tasks/{task_id}/complete", json={
        "phase": "RELEASED", "goal_evidence_digest": digest,
        "receipt": receipt, "stage_result": stage, "hardware_telemetry": hardware,
    })


def test_get_cell_sites_returns_all_37_sites_and_enforces_viewer_auth(monkeypatch):
    app, _ = _app(monkeypatch, guarded=True)
    client = TestClient(app)
    assert client.get("/api/fleet/pipeline/cell-sites").status_code == 401
    res = client.get("/api/fleet/pipeline/cell-sites", headers=VIEW)
    assert res.status_code == 200
    body = res.json()
    assert body["schema"] == "rosy.cell-site-map.v1" and body["count"] == 37
    zones = body["zones"]
    assert [z["id"] for z in zones] == ["yard", "temp_a", "temp_b", "stand"]
    assert all(set(z.keys()) == {"id", "label", "role", "grid", "slot_cells", "arms", "status"} for z in zones)
    assert {z["id"]: z["role"] for z in zones} == {"yard": "보관", "temp_a": "임시", "temp_b": "임시", "stand": "반출"}
    assert {z["id"]: z["label"] for z in zones} == {
        "yard": "장치 야드", "temp_a": "임시 장치 A", "temp_b": "임시 장치 B", "stand": "반출대",
    }
    assert {z["id"]: z["grid"] for z in zones} == {
        "yard": {"rows": 3, "columns": 6, "tiers": 3},
        "temp_a": {"rows": 3, "columns": 3, "tiers": 3},
        "temp_b": {"rows": 3, "columns": 3, "tiers": 3},
        "stand": {"rows": 1, "columns": 3, "tiers": 1},
    }
    assert all(z["slot_cells"] == 3 and z["status"] == "planned_unverified" for z in zones)
    assert {z["id"]: z["arms"] for z in zones} == {
        "yard": ["arm_a", "arm_b"], "temp_a": ["arm_a"], "temp_b": ["arm_b"], "stand": ["arm_a"],
    }
    by_id = {s["site_id"]: s for s in body["sites"]}
    assert len(by_id) == 37
    for zone in zones:
        area_sites = [s for s in body["sites"] if s["area"] == zone["id"]]
        expected_count = zone["grid"]["rows"] * (zone["grid"]["columns"] // zone["slot_cells"]) * zone["grid"]["tiers"]
        assert len(area_sites) == expected_count
        assert {arm for s in area_sites for arm in s["arms"]} == set(zone["arms"])
    assert by_id["yard:r1-s1-t1"]["wire_ref"] == "yard-r1-c1-l1" and by_id["yard:r1-s1-t1"]["sim_site"] == "ship-h2r0-l0"
    assert by_id["yard:r1-s2-t2"]["wire_ref"] == "yard-r1-c4-l2" and by_id["yard:r1-s2-t2"]["sim_site"] == "ship-h1r0-l1"
    assert by_id["yard:r1-s2-t2"]["col"] == 1
    assert by_id["temp_a:r2-s1-t3"]["arms"] == ["arm_a"] and by_id["temp_b:r3-s1-t2"]["arms"] == ["arm_b"]
    assert by_id["stand:r1-s1-t1"]["wire_ref"] == "stand-r1-c1-l1" and by_id["stand:r1-s1-t1"]["sim_site"] == "stand"


@pytest.mark.parametrize("dst_input, expected_sim, expected_id, expected_area, expected_tier, expected_arm", [
    ("yard:r1-s2-t2", "ship-h1r0-l1", "yard:r1-s2-t2", "yard", 2, "arm_b"),
    ("yard-r1-c4-l2", "ship-h1r0-l1", "yard:r1-s2-t2", "yard", 2, "arm_b"),
    ("ship-h1r0-l1", "ship-h1r0-l1", "yard:r1-s2-t2", "yard", 2, "arm_b"),
    ("temp_a:r2-s1-t3", "tmp-a-2-l2", "temp_a:r2-s1-t3", "temp_a", 3, "arm_a"),
    ("temp_b-r3-c1-l1", "tmp-b-3", "temp_b:r3-s1-t1", "temp_b", 1, "arm_b"),
    ("stand:r1-s1-t1", "stand", "stand:r1-s1-t1", "stand", 1, "arm_a"),
    ("stand-r1-c1-l1", "stand", "stand:r1-s1-t1", "stand", 1, "arm_a"),
    ("stand", "stand", "stand:r1-s1-t1", "stand", 1, "arm_a"),
])
def test_single_canonical_wire_and_sim_destinations_normalize_consistently(
    monkeypatch, dst_input, expected_sim, expected_id, expected_area, expected_tier, expected_arm,
):
    app, owner_ev = _app(monkeypatch)
    client = TestClient(app)
    res = client.post("/api/fleet/pipeline/cell-tasks", json={"cell_id": "cell_ab", "dst_site": dst_input})
    assert res.status_code == 200
    task = res.json()["task"]
    assert task["dst_site"] == expected_sim
    assert task["dst_site_id"] == expected_id
    assert task["dst_area"] == expected_area
    assert task["tier"] == expected_tier
    assert task["arm_id"] == expected_arm
    handoff, done = _complete_one(client, owner_ev, task["task_id"])
    assert handoff["dst_site_id"] == expected_id and handoff["dst_area"] == expected_area
    assert done.status_code == 200 and done.json()["task"]["status"] == "COMPLETED"


@pytest.mark.parametrize("slot_input, area, sim_sites, default_arms", [
    ("yard:r1-s2", "yard", ["ship-h1r0-l0", "ship-h1r0-l1", "ship-h1r0-l2"], ["arm_a", "arm_b", "arm_a"]),
    ("temp_a:r1-s1", "temp_a", ["tmp-a-1", "tmp-a-1-l1", "tmp-a-1-l2"], ["arm_a", "arm_a", "arm_a"]),
    ("temp_b:r2-s1", "temp_b", ["tmp-b-2", "tmp-b-2-l1", "tmp-b-2-l2"], ["arm_b", "arm_b", "arm_b"]),
])
def test_multi_tier_stack_enqueues_chained_tasks_and_enforces_tier_gate(
    monkeypatch, slot_input, area, sim_sites, default_arms,
):
    app, owner_ev = _app(monkeypatch)
    client = TestClient(app)
    res = client.post("/api/fleet/pipeline/cell-tasks", json={
        "task_id": f"stack-{area}", "cell_id": "cell_ab", "dst_site": slot_input, "tiers": [1, 2, 3],
    })
    assert res.status_code == 200
    tasks = res.json()["tasks"]
    assert [t["dst_site"] for t in tasks] == sim_sites
    assert [t["dst_site_id"] for t in tasks] == [f"{slot_input}-t1", f"{slot_input}-t2", f"{slot_input}-t3"]
    assert [t["arm_id"] for t in tasks] == default_arms
    assert [t["depends_on"] for t in tasks] == [None, tasks[0]["task_id"], tasks[1]["task_id"]]

    blocked = client.post("/api/fleet/pipeline/cell-tasks/claim", json={"cell_id": "cell_ab", "task_id": tasks[1]["task_id"]}).json()
    assert blocked["claimed"] is False and blocked["reason"] == "PREVIOUS_TIER_NOT_VERIFIED"

    for t in tasks:
        _, done = _complete_one(client, owner_ev, t["task_id"])
        assert done.status_code == 200 and done.json()["task"]["status"] == "COMPLETED"


@pytest.mark.parametrize("payload", [
    {"cell_id": "cell_ab", "arm_id": "arm_a"},  # bare cell_ab missing tier
    {"cell_id": "cell_ab", "dst_site": "yard:r1-s2"},  # slot without tier
    {"cell_id": "cell_ab", "dst_site": "yard:r1-s2-t2", "tier": 3},  # conflicting explicit tier
    {"cell_id": "cell_ab", "dst_site": "temp_a:r1-s1-t1", "arm_id": "arm_b"},  # wrong arm
    {"cell_id": "cell_ab", "dst_site": "temp_b:r1-s1-t1", "arm_id": "arm_a"},  # wrong arm
    {"cell_id": "cell_ab", "dst_site": "stand:r1-s1-t1", "arm_id": "arm_b"},  # wrong arm
    {"cell_id": "cell_ab", "src_site": "temp_a:r1-s1-t1", "dst_site": "temp_b:r1-s1-t1"},  # cross-plate single transfer
    {"cell_id": "cell_ab", "dst_site": "stand:r1-s1", "tier": 2},
    {"cell_id": "cell_ab", "dst_site": "stand:r1-s1", "tiers": [1, 2]},
    {"cell_id": "cell_ab", "dst_site": "yard:r1-s2-t1", "tiers": [1, 2]},  # conflicting fixed tier with multi tiers
    {"cell_id": "cell_ab", "dst_site": "yard:r1-s2", "tiers": []},
    {"cell_id": "cell_ab", "dst_site": "yard:r1-s2", "tiers": [2, 1]},
    {"cell_id": "cell_ab", "dst_site": "yard:r1-s2", "tiers": [1, 1]},
    {"cell_id": "cell_ab", "dst_site": "yard:r1-s2", "tiers": [True]},
    {"cell_id": "cell_s", "dst_site": "yard:r1-s2", "tiers": [1]},
    {"cell_id": "cell_s", "dst_site": "yard:r1-s2-t1"},
    {"cell_id": "cell_ab", "dst_site": "yard:r9-s1-t1"},
    {"cell_id": "cell_ab", "dst_site": "ship-stern-l0"},
    {"cell_id": "cell_ab", "src_site": "yard:r1-s1-t1", "dst_site": "yard:r1-s1-t1"},
])
def test_invalid_canonical_targets_arms_and_tiers_reject_with_422(monkeypatch, payload):
    app, _ = _app(monkeypatch)
    client = TestClient(app)
    res = client.post("/api/fleet/pipeline/cell-tasks", json=payload)
    assert res.status_code == 422 and not app.state.omx_cell_tasks


def test_complete_rejects_mismatched_area_site_tier_slot_or_z_gate(monkeypatch):
    app, owner_ev = _app(monkeypatch)
    client = TestClient(app)
    task = client.post("/api/fleet/pipeline/cell-tasks", json={
        "task_id": "yard-strict", "cell_id": "cell_ab", "dst_site": "yard:r1-s2-t2",
    }).json()["task"]
    claimed = client.post("/api/fleet/pipeline/cell-tasks/claim", json={"cell_id": "cell_ab", "task_id": "yard-strict"}).json()
    lease = claimed["handoff"]["handoff_lease_id"]
    for bad_place, zv, v_target, inc_tgt in (
        ({"area": "pallet", "site": "ship-h1r0-l1", "site_id": "yard:r1-s2-t2", "tier": 2, "col": 1, "row": 2}, "PASS", None, True),
        ({"area": "yard", "site": "ship-h1r0-l0", "site_id": "yard:r1-s2-t2", "tier": 2, "col": 1, "row": 2}, "PASS", None, True),
        ({"area": "yard", "site": "ship-h1r0-l1", "site_id": "yard:r1-s2-t2", "tier": 1, "col": 1, "row": 2}, "PASS", None, True),
        ({"area": "yard", "site": "ship-h1r0-l1", "site_id": "yard:r1-s2-t2", "tier": 2, "col": 2, "row": 2}, "PASS", None, True),
        ({"area": "yard", "site": "ship-h1r0-l1", "site_id": "yard:r1-s2-t2", "tier": 2}, "PASS", None, True),  # omitted col/row
        ({"area": "yard", "site": "ship-h1r0-l1", "tier": 2, "col": 1, "row": 2}, "PASS", None, True),  # omitted site_id
        ({"area": "yard", "site": "ship-h1r0-l1", "site_id": "yard:r2-s2-t2", "tier": 2, "col": 1, "row": 2}, "PASS", None, True),
        ({"area": "yard", "site": "ship-h1r0-l1", "site_id": "yard:r1-s2-t2", "tier": 2, "col": 1, "row": 2}, "PASS", None, False),
        ({"area": "yard", "site": "ship-h1r0-l1", "site_id": "yard:r1-s2-t2", "tier": 2, "col": 1, "row": 2}, "PASS",
         {"area": "yard", "site": "ship-h1r1-l1", "site_id": "yard:r2-s2-t2", "tier": 2, "col": 2, "row": 2}, True),
        ({"area": "yard", "site": "ship-h1r0-l1", "site_id": "yard:r1-s2-t2", "tier": 2, "col": 1, "row": 2}, "FAIL", None, True),
    ):
        receipt, stage, hw, digest = _complete_payload(
            "yard-strict", lease, task["arm_id"], bad_place, z_verdict=zv, target=v_target, include_target=inc_tgt)
        owner_ev["yard-strict"] = {"receipt": receipt, "stage_result": stage, "hardware_telemetry": hw}
        res = client.post("/api/fleet/pipeline/cell-tasks/yard-strict/complete", json={
            "phase": "RELEASED", "goal_evidence_digest": digest,
            "receipt": receipt, "stage_result": stage, "hardware_telemetry": hw,
        })
        assert res.status_code == 422 and res.json()["detail"]["code"] == "UNVERIFIED_CELL_COMPLETION"


def test_multi_tier_creation_is_atomic_when_later_tier_fails_and_retry_keeps_chain(monkeypatch):
    app, _ = _app(monkeypatch)
    client = TestClient(app)
    bad = client.post("/api/fleet/pipeline/cell-tasks", json={
        "task_id": "atomic-bad", "cell_id": "cell_ab", "dst_site": "yard:r1-s2", "tiers": [1, 2],
        "directive": {"schema": "rosy.omx-cell-area-xyz-directive.v1", "directive_id": "atomic-bad-t1", "arm_id": "arm_a"},
    })
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "INVALID_CELL_DIRECTIVE"
    assert app.state.omx_cell_tasks == {}

    ok = client.post("/api/fleet/pipeline/cell-tasks", json={
        "task_id": "atomic-ok", "cell_id": "cell_ab", "dst_site": "yard:r1-s2", "tiers": [1, 2],
    })
    assert ok.status_code == 200
    retried = client.post("/api/fleet/pipeline/cell-tasks/atomic-ok-t2/retry")
    assert retried.status_code == 200
    rt = retried.json()["task"]
    assert rt["depends_on"] == "atomic-ok-t1" and rt["dst_site_id"] == "yard:r1-s2-t2"


def test_end_to_end_fastapi_fleet_to_omx_worker_3tier_yard_and_stand(tmp_path: Path, monkeypatch):
    root = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(root / "deploy/robot/omx"))
    monkeypatch.syspath_prepend(str(root / "middleware/devices/omx/adapter"))
    import cell_fleet_pipeline as cfp
    import cell_site_target as cst
    import cell_task_worker as ctw

    app, owner_ev = _app(monkeypatch)
    client = TestClient(app)
    res = client.post("/api/fleet/pipeline/cell-tasks", json={
        "task_id": "e2e-yard", "cell_id": "cell_ab", "dst_site": "yard:r1-s2", "tiers": [1, 2, 3],
    })
    assert res.status_code == 200 and len(res.json()["tasks"]) == 3
    res_stand = client.post("/api/fleet/pipeline/cell-tasks", json={
        "task_id": "e2e-stand", "cell_id": "cell_ab",
        "src_site": "temp_a:r1-s1-t1", "dst_site": "stand:r1-s1-t1", "depends_on": "e2e-yard-t3",
    })
    assert res_stand.status_code == 200

    blocked = client.post("/api/fleet/pipeline/cell-tasks/claim", json={"cell_id": "cell_ab", "task_id": "e2e-yard-t2"}).json()
    assert blocked["claimed"] is False and blocked["reason"] == "PREVIOUS_TIER_NOT_VERIFIED"

    def request_fn(method: str, path: str, body=None):
        if method == "POST" and path.endswith("/owner-evidence"):
            tid = path.split("/")[-2]
            owner_ev[tid] = {
                "receipt": body["receipt"], "stage_result": body["stage_result"],
                "hardware_telemetry": body["hardware_telemetry"],
            }
            return {"recorded": True}
        r = client.request(method, path, json=body)
        assert r.status_code < 400, (method, path, r.status_code, r.text)
        return r.json()

    def live_act_fn(handoff: dict) -> dict:
        resolved = cst.resolve_cell_ab_site(handoff["dst_site"], handoff["tier"], allow_belt_temp=False)
        place_obj = {
            "area": resolved["area"], "site": resolved["sim_site"], "site_id": resolved["site_id"],
            "col": resolved["col"], "row": resolved["row"], "tier": resolved["tier"],
        }
        return {
            "arm": handoff["arm_id"], "measured_at": time.time(),
            "stop_event": {"command": "stop", "ok": True, "folded": True, "state": [0.0] * 6},
            "stage_result": {
                "handoff_lease_id": handoff["handoff_lease_id"],
                "directive_id": handoff["task_id"],
                "arm_id": handoff["arm_id"],
                "task_verified": True,
                "place": place_obj,
                "verification": {
                    "verified": True, "basis": "predefined_side_and_top_target_zones",
                    "z_gate": {"verdict": "PASS"}, "target": dict(place_obj),
                },
            },
        }

    pipe = cfp.FleetModelPipeline(tmp_path / "pipe")
    completed_ids = []
    for _ in range(4):
        if len(completed_ids) == 4:
            break
        runs = ctw.poll_and_execute_once(pipe, request_fn=request_fn, live_act_fn=live_act_fn, prep_dir=tmp_path)
        assert len(runs) >= 1
        completed_ids.extend(r["task_id"] for r in runs if r["task"]["status"] == "COMPLETED")
    tasks = app.state.omx_cell_tasks
    assert all(tasks[k]["status"] == "COMPLETED" for k in ("e2e-yard-t1", "e2e-yard-t2", "e2e-yard-t3", "e2e-stand"))
    assert tasks["e2e-yard-t2"]["arm_id"] == "arm_b" and tasks["e2e-stand"]["arm_id"] == "arm_a"
