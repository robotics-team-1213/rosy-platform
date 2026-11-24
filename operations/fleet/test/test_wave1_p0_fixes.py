"""Wave 1 P0 fixes: D-1072 cell_internal claim/release without a docked AMR (P0-1), the plan summary's cell
phase (P0-9), cell_ab cell-plan/ARM-transfer mutual exclusion (P0-2), and 1-based slot refs (P0-7)."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from types import SimpleNamespace

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from core_common.protocol.port_events import PortEvent, event_id
from fleet.server.auth.site_auth import build_authorize, build_role_guards
from fleet.server.sitemap.pipeline_routes import install_pipeline_routes
from fleet.server.intake_readings import SLOT  # fleet.server composes the work holder (D-798)
from rosy_account.principal import SitePrincipal
from tools.sim.bay_departure_sim import build_world_261026_site_map

# Shared rigs from the neighbouring suites (fixtures resolve through this module's namespace, so the whole
# chain — policy → geometry — is imported alongside installation and the two rig fixtures).
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

# The contract wheels are pip-installed on the test PC (D-584); on a bare Windows tree the sources resolve.
for _wheel_src in ("contracts/skill/src", "contracts/motion/src"):
    _p = str(Path(__file__).resolve().parents[3] / _wheel_src)
    if _p not in sys.path:
        sys.path.append(_p)

from test_arm_transfer_job_api import (  # noqa: F401, E402  (rig is a fixture)
    PATH, create as transfer_create, headers, rig)
from test_physical_transfer_evidence import geometry, policy  # noqa: F401, E402
from test_physical_transfer_store import (  # noqa: F401, E402
    PROPOSER, admit as admit_job, create as create_job, installation, rig as store_rig)

VIEW = {"Authorization": "Bearer viewer"}
SVC = {"Authorization": "Bearer harbor-svc"}
OWNER = {"Authorization": "Bearer cell-owner-svc"}
OP = {"Authorization": "Bearer operator"}

CLAIM = "/api/fleet/pipeline/cell-tasks/claim"
PLAN = "/api/fleet/pipeline/cell-plans"
TASKS = "/api/fleet/pipeline/cell-tasks"
T = datetime(2026, 11, 25, 3, 0, tzinfo=timezone.utc)

PLAN_PAYLOAD = {
    "request_key": "wave1-plan",
    "mode": "harbor_plan",
    "state": {"C1": "yard-r1-c1-l1", "C2": "yard-r1-c1-l2"},
    "steps": [
        {"cargo_id": "C2", "src_site": "yard-r1-c1-l2", "dst_site": "temp_a-r1-c1-l1", "arm_id": "arm_a", "phase_label": "재취급"},
        {"cargo_id": "C1", "src_site": "yard-r1-c1-l1", "dst_site": "stand-r1-c1-l1", "arm_id": "arm_a", "phase_label": "반출"},
        {"cargo_id": "C2", "src_site": "temp_a-r1-c1-l1", "dst_site": "yard-r1-c1-l1", "arm_id": "arm_a", "phase_label": "복귀"},
    ],
}


def _app(monkeypatch, *, amr=None, ab_release=True):
    monkeypatch.setenv("ROSY_FLEET_CELL_AB_RELEASE_ENABLED", "1" if ab_release else "0")
    monkeypatch.setenv("ROSY_FLEET_CELL_OWNERS", "cell_ab=cell-owner")
    site, graph, _ = build_world_261026_site_map()
    maps = SimpleNamespace(active=lambda: (1, site, graph, None), rules=SimpleNamespace(active_rules=lambda: None))
    owner_evidence: dict[str, dict] = {}
    app = FastAPI()
    principals = {hashlib.sha256(t.encode()).hexdigest(): SitePrincipal(p, r)
                  for t, p, r in (("viewer", "viewer-1", "viewer"), ("harbor-svc", "harbor-service", "service"),
                                  ("cell-owner-svc", "cell-owner", "service"), ("operator", "console-human", "operator"))}
    require_viewer, require_operator, _, require_proposer = build_role_guards(
        build_authorize(None, principals, None), principals)
    app.state.operator_guard = [Depends(require_operator)]
    app.state.proposer_guard = [Depends(require_proposer)]
    install_pipeline_routes(
        app, site_maps=maps, read_guard=[Depends(require_viewer)],
        amr_evidence_fn=(lambda t: None) if amr is None else amr,
        omx_evidence_fn=lambda t: owner_evidence.get(t["task_id"]))
    return app, owner_evidence


def _cell_ab_task(client, task_id="wave1-internal"):
    res = client.post(TASKS, headers=OP, json={
        "task_id": task_id, "cell_id": "cell_ab", "arm_id": "arm_a", "robot_id": "rosy_01",
        "src_site": "belt", "dst_site": "pallet-l0", "tier": 1})
    assert res.status_code == 200, res.text
    task = res.json()["task"]
    assert task["interlock_scope"] == "cell_internal"
    return task


def _complete_body(task_id, handoff):
    place = {"area": handoff["dst_area"], "site": handoff["dst_site"], "site_id": handoff.get("dst_site_id"),
             "tier": handoff["tier"], **(handoff.get("dst_slot") or {})}
    verification = {"verified": True, "basis": "predefined_side_and_top_target_zones",
                    "z_gate": {"verdict": "PASS"}, "target": dict(place)}
    stage = {"directive_id": task_id, "arm_id": handoff["arm_id"], "task_verified": True,
             "verification": verification, "place": place}
    hardware = {"stop_event": {"ok": True, "folded": True, "state": [0.0] * 6}}
    evidence = {"task_id": task_id, "lease": handoff["handoff_lease_id"], "stage_result": stage,
                "hardware_telemetry": hardware}
    digest = "sha256:" + hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
    receipt = {"handoff_lease_id": handoff["handoff_lease_id"], "cell_id": "cell_ab", "stage_id": task_id,
               "phase": "RELEASED", "physical_completion": True, "simulated_success": False,
               "goal_evidence_digest": digest}
    return {"receipt": receipt, "stage_result": stage, "hardware_telemetry": hardware,
            "phase": "RELEASED", "goal_evidence_digest": digest}


# --- P0-1: a cell_internal cell_ab task claims and completes without a docked AMR -----------------------------
def test_cell_internal_claim_and_complete_without_docked_amr(monkeypatch):
    app, owner_ev = _app(monkeypatch, amr=None)
    client = TestClient(app)
    task = _cell_ab_task(client)
    claimed = client.post(CLAIM, headers=OWNER, json={"cell_id": "cell_ab", "task_id": task["task_id"]}).json()
    assert claimed["claimed"] is True, claimed
    assert claimed["gate"]["cell_can_claim"] is True and claimed["gate"]["interlock_scope"] == "cell_internal"
    assert claimed["handoff"]["cell_id"] == "cell_ab" and claimed["handoff"]["handoff_lease_id"]
    stored = client.app.state.omx_cell_tasks[task["task_id"]]
    assert stored["status"] == "RUNNING" and stored["amr_claim_evidence"] is None
    body = _complete_body(task["task_id"], claimed["handoff"])
    owner_ev[task["task_id"]] = {k: body[k] for k in ("receipt", "stage_result", "hardware_telemetry")}
    done = client.post(f"{TASKS}/{task['task_id']}/complete", headers=OWNER, json=body)
    assert done.status_code == 200, done.text
    assert done.json()["task"]["status"] == "COMPLETED"
    assert client.app.state.omx_cell_states["cell_ab"]["docked_robot"] is None


def test_cell_internal_release_still_needs_owner_evidence_and_a_matching_receipt(monkeypatch):
    app, owner_ev = _app(monkeypatch, amr=None)
    client = TestClient(app)
    task = _cell_ab_task(client)
    claimed = client.post(CLAIM, headers=OWNER, json={"cell_id": "cell_ab", "task_id": task["task_id"]}).json()
    assert claimed["claimed"] is True
    refused = client.post(f"{TASKS}/{task['task_id']}/complete", headers=OWNER,
                          json={"phase": "RELEASED", "goal_evidence_digest": "sha256:" + "0" * 64})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "OMX_OWNER_EVIDENCE_UNAVAILABLE"
    body = _complete_body(task["task_id"], claimed["handoff"])
    owner_ev[task["task_id"]] = {k: body[k] for k in ("receipt", "stage_result", "hardware_telemetry")}
    wrong = _complete_body(task["task_id"], claimed["handoff"])
    wrong["receipt"]["handoff_lease_id"] = "other-lease"
    still_refused = client.post(f"{TASKS}/{task['task_id']}/complete", headers=OWNER, json=wrong)
    assert still_refused.status_code == 422 and still_refused.json()["detail"]["code"] == "OMX_OWNER_EVIDENCE_MISMATCH"


def test_d1057_release_gate_still_blocks_a_cell_internal_claim(monkeypatch):
    app, _ = _app(monkeypatch, amr=None, ab_release=False)
    client = TestClient(app)
    task = _cell_ab_task(client)
    res = client.post(CLAIM, headers=OWNER, json={"cell_id": "cell_ab", "task_id": task["task_id"]}).json()
    assert res["claimed"] is False and res["reason"] == "CELL_AB_EVIDENCE_NOT_ENABLED"
    assert client.app.state.omx_cell_tasks[task["task_id"]]["status"] == "QUEUED"


def test_only_the_registered_owner_claims_cell_internal(monkeypatch):
    app, _ = _app(monkeypatch, amr=None)
    client = TestClient(app)
    task = _cell_ab_task(client)
    res = client.post(CLAIM, headers=SVC, json={"cell_id": "cell_ab", "task_id": task["task_id"]}).json()
    assert res["claimed"] is False and res["reason"] == "OWNER_PRINCIPAL_NOT_REGISTERED"


# --- P0-9: the plan summary reads the cell phase the cell state actually carries ------------------------------
def test_plan_summary_reads_cell_phase_from_the_cell_state(monkeypatch):
    app, _ = _app(monkeypatch)
    client = TestClient(app)
    plan_id = client.post(PLAN, headers=SVC, json={**PLAN_PAYLOAD, "request_key": "p09-phase"}).json()["plan"]["plan_id"]
    assert client.get(f"{PLAN}/{plan_id}", headers=VIEW).json()["plan"]["cell_phase"] is None
    client.app.state.omx_cell_states["cell_ab"] = {"phase": "ARM_IN_BED_ZONE"}
    assert client.get(f"{PLAN}/{plan_id}", headers=VIEW).json()["plan"]["cell_phase"] == "ARM_IN_BED_ZONE"


# --- P0-2: a live ARM transfer job and a cell_ab cell plan exclude each other ---------------------------------
def test_cell_plan_conflicts_with_an_active_arm_transfer_job(monkeypatch):
    app, _ = _app(monkeypatch)
    app.state.arm_transfer_job_store = SimpleNamespace(has_active_transfer=lambda: True)
    client = TestClient(app)
    res = client.post(PLAN, headers=SVC, json={**PLAN_PAYLOAD, "request_key": "p02-blocked"})
    assert res.status_code == 409 and res.json()["detail"]["code"] == "CELL_WORK_CONFLICT"
    app.state.arm_transfer_job_store = SimpleNamespace(has_active_transfer=lambda: False)
    res = client.post(PLAN, headers=SVC, json={**PLAN_PAYLOAD, "request_key": "p02-free"})
    assert res.status_code == 200, res.text


def test_has_active_transfer_tracks_the_physical_job_lifecycle(store_rig):
    _, _, control, store = store_rig
    assert store.has_active_transfer() is False
    proposal = create_job(store, key="wave1-move")
    assert store.has_active_transfer() is True  # PROPOSED
    ready = admit_job(store, proposal, control)
    assert ready["status"] == "READY" and store.has_active_transfer() is True
    parked = create_job(store, key="wave1-parked")
    store.withdraw(parked["mission_id"], reason="origin canceled")
    assert store.has_active_transfer() is True  # the admitted job is still live


def test_arm_transfer_create_conflicts_with_an_active_cell_ab_task(rig):
    client, tasks, port, installed = rig
    assert transfer_create(rig).status_code == 200
    app = client.app
    for status in ("PROPOSED", "QUEUED", "RUNNING", "PAUSED_HUMAN"):
        app.state.omx_cell_tasks["busy"] = {"cell_id": "cell_ab", "status": status}
        blocked = transfer_create(rig, request_key="move-" + status)
        assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "CELL_WORK_CONFLICT"
    app.state.omx_cell_tasks["busy"] = {"cell_id": "cell_s", "status": "RUNNING"}
    assert transfer_create(rig, request_key="move-cell-s").status_code == 200  # cell S work does not own cell_ab
    app.state.omx_cell_tasks["busy"] = {"cell_id": "cell_ab", "status": "COMPLETED"}
    assert transfer_create(rig, request_key="move-done").status_code == 200


def test_arm_transfer_admit_conflicts_with_an_active_cell_ab_task(rig):
    client, tasks, port, installed = rig
    job = transfer_create(rig).json()["job"]
    client.app.state.omx_cell_tasks["busy"] = {"cell_id": "cell_ab", "status": "RUNNING"}
    res = client.post(f"{PATH}/{job['mission_id']}/admit", headers=headers("operator"), json={
        "expected_proposal_digest": job["proposal_digest"],
        "expected_generation": tasks.dispatch_control()["generation"]})
    assert res.status_code == 409 and res.json()["detail"]["code"] == "CELL_WORK_CONFLICT"
    assert client.app.state.arm_transfer_job_store.peek(job["mission_id"])["status"] == "PROPOSED"


# --- P0-7: slot refs are 1-based, like Harbor's SLOT_REF_RE ---------------------------------------------------
def _stored_event(**fields):
    defaults = {"object_ref": "CNTR-1", "slot_ref": "yard-r1-c2-l1", "identity": "attested"}
    return PortEvent(event_id=event_id("cell-supply", "obs-wave1", "container.stored"), kind="container.stored",
                     observation_ref="obs-wave1", observed_at=T, **{**defaults, **fields})


@pytest.mark.parametrize("slot", ["yard-r0-c1-l1", "yard-r1-c0-l1", "yard-r1-c1-l0", "yard-r0-c0-l0"])
def test_zero_based_slot_refs_are_rejected(slot):
    with pytest.raises(ValidationError):
        _stored_event(slot_ref=slot)
    assert _stored_event(slot_ref="yard-r1-c1-l1").slot_ref == "yard-r1-c1-l1"


def test_intake_slot_regex_is_one_based():
    assert SLOT.match("yard-r1-c1-l1") and SLOT.match("yard-r12-c3-l2")
    assert not SLOT.match("yard-r0-c1-l1") and not SLOT.match("yard-r1-c0-l1") and not SLOT.match("yard-r1-c1-l0")


def test_claim_cell_task_refuses_when_arm_transfer_is_active(monkeypatch):
    app, _ = _app(monkeypatch, amr=None)
    client = TestClient(app)
    task = _cell_ab_task(client, task_id="wave1-claim-conflict")
    app.state.arm_transfer_job_store = SimpleNamespace(has_active_transfer=lambda: True)
    refused = client.post(CLAIM, headers=OWNER, json={"cell_id": "cell_ab", "task_id": task["task_id"]}).json()
    assert refused["claimed"] is False and refused["reason"] == "CELL_WORK_CONFLICT"


def test_has_active_transfer_includes_action_succeeded_and_unreleased_hold_claims(store_rig):
    from contextlib import closing
    _, _, _, store = store_rig
    job = create_job(store, key="wave1-succ")
    mid = job["mission_id"]
    with closing(store._journal._connect()) as conn, conn:
        conn.execute("UPDATE fleet_cell_jobs SET status='ACTION_SUCCEEDED' WHERE mission_id=?", (mid,))
    assert store.has_active_transfer() is True
    with closing(store._journal._connect()) as conn, conn:
        conn.execute("UPDATE fleet_cell_jobs SET status='HOLD' WHERE mission_id=?", (mid,))
        conn.execute(
            "INSERT INTO fleet_action_claims "
            "(resource_key, resource_kind, resource_id, owner_kind, owner_id, generation, phase, created_at) "
            "VALUES ('res-1', 'arm', 'arm_a', 'mission', ?, 1, 'HELD', '2026-11-25T00:00:00Z')",
            (mid,),
        )
    assert store.has_active_transfer() is True
    with closing(store._journal._connect()) as conn, conn:
        conn.execute("DELETE FROM fleet_action_claims WHERE owner_id=?", (mid,))
    assert store.has_active_transfer() is False
