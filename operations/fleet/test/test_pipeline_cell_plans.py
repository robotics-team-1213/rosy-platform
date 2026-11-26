"""Dual-mode Fleet cell-plan tests: explicit Harbor order/coordinates vs autonomous ROSY directive."""
from __future__ import annotations

import hashlib
import json
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
SVC = {"Authorization": "Bearer harbor-svc"}
OWNER = {"Authorization": "Bearer cell-owner-svc"}
OP = {"Authorization": "Bearer operator"}


def _app(monkeypatch, *, guarded: bool = True):
    monkeypatch.setenv("ROSY_FLEET_CELL_AB_RELEASE_ENABLED", "1")
    monkeypatch.setenv("ROSY_FLEET_CELL_OWNERS", "cell_ab=cell-owner;cell_s=cell-owner")
    site, graph, _ = build_world_261026_site_map()
    maps = SimpleNamespace(active=lambda: (1, site, graph, None), rules=SimpleNamespace(active_rules=lambda: None))
    owner_evidence: dict[str, dict] = {}
    app = FastAPI()
    if guarded:
        principals = {
            hashlib.sha256(t.encode()).hexdigest(): SitePrincipal(p, r)
            for t, p, r in (
                ("viewer", "viewer-1", "viewer"),
                ("harbor-svc", "harbor-service", "service"),
                ("cell-owner-svc", "cell-owner", "service"),
                ("operator", "console-human", "operator"),
            )
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


def _admit_all(client: TestClient, tasks: list[dict]):
    gov = client.app.state.pipeline_governance
    for t in tasks:
        rdy = client.get("/api/fleet/pipeline/cells/cell_ab/readiness", headers=VIEW).json()
        snap = gov.snapshot()
        res = client.post(f"/api/fleet/pipeline/cell-tasks/{t['task_id']}/admit", headers=OP, json={
            "expected_dispatch_generation": snap["dispatch_generation"],
            "expected_stop_generation": snap["stop_generation"],
            "expected_readiness_digest": rdy["readiness_digest"],
        })
        assert res.status_code == 200, res.text


def _complete_one(client: TestClient, owner_ev: dict, task_id: str):
    claimed = client.post("/api/fleet/pipeline/cell-tasks/claim", headers=OWNER, json={"cell_id": "cell_ab", "task_id": task_id}).json()
    assert claimed["claimed"] is True, claimed
    handoff = claimed["handoff"]
    lease = handoff["handoff_lease_id"]
    place = {
        "area": handoff["dst_area"], "site": handoff["dst_site"], "site_id": handoff["dst_site_id"],
        "tier": handoff["tier"], **(handoff.get("dst_slot") or {}),
    }
    verification = {"verified": True, "basis": "predefined_side_and_top_target_zones", "z_gate": {"verdict": "PASS"}, "target": dict(place)}
    stage = {"directive_id": task_id, "arm_id": handoff["arm_id"], "task_verified": True, "verification": verification, "place": place}
    hardware = {"stop_event": {"ok": True, "folded": True, "state": [0.0] * 6}}
    digest = "sha256:" + hashlib.sha256(json.dumps({"task_id": task_id, "lease": lease, "stage_result": stage, "hardware_telemetry": hardware}, sort_keys=True).encode()).hexdigest()
    receipt = {
        "handoff_lease_id": lease, "cell_id": "cell_ab", "stage_id": task_id,
        "phase": "RELEASED", "physical_completion": True, "simulated_success": False,
        "goal_evidence_digest": digest,
    }
    owner_ev[task_id] = {"receipt": receipt, "stage_result": stage, "hardware_telemetry": hardware}
    done = client.post(f"/api/fleet/pipeline/cell-tasks/{task_id}/complete", headers=OWNER, json={
        "phase": "RELEASED", "goal_evidence_digest": digest,
        "receipt": receipt, "stage_result": stage, "hardware_telemetry": hardware,
    })
    assert done.status_code == 200, done.text
    return done.json()["task"]


def test_mode1_harbor_plan_executes_exact_sequence_and_enforces_admit_and_dependency(monkeypatch):
    app, owner_ev = _app(monkeypatch)
    client = TestClient(app)
    payload = {
        "request_key": "harbor-plan-1",
        "mode": "harbor_plan",
        "state": {"C1": "yard-r1-c1-l1", "C2": "yard-r1-c1-l2"},
        "steps": [
            {"cargo_id": "C2", "src_site": "yard-r1-c1-l2", "dst_site": "temp_a-r1-c1-l1", "arm_id": "arm_a", "phase_label": "재취급"},
            {"cargo_id": "C1", "src_site": "yard-r1-c1-l1", "dst_site": "stand-r1-c1-l1", "arm_id": "arm_a", "phase_label": "반출"},
            {"cargo_id": "C2", "src_site": "temp_a-r1-c1-l1", "dst_site": "yard-r1-c1-l1", "arm_id": "arm_a", "phase_label": "복귀"},
        ],
    }
    res = client.post("/api/fleet/pipeline/cell-plans", headers=SVC, json=payload)
    assert res.status_code == 200, res.text
    body = res.json()
    plan = body["plan"]
    tasks = body["tasks"]
    assert plan["order_source"] == "harbor"
    assert plan["mode"] == "harbor_plan"
    assert plan["status"] == "PROPOSED"
    assert [t["dst_wire_ref"] for t in tasks] == ["temp_a-r1-c1-l1", "stand-r1-c1-l1", "yard-r1-c1-l1"]
    assert [t["depends_on"] for t in tasks] == [None, tasks[0]["task_id"], tasks[1]["task_id"]]
    assert all(t["status"] == "PROPOSED" and "cargo_id" not in t for t in tasks)
    assert all("cargo_id" not in m for m in plan["moves"])

    _admit_all(client, tasks)
    assert client.get(f"/api/fleet/pipeline/cell-plans/{plan['plan_id']}", headers=VIEW).json()["plan"]["status"] == "QUEUED"

    blocked = client.post("/api/fleet/pipeline/cell-tasks/claim", headers=OWNER, json={"cell_id": "cell_ab", "task_id": tasks[1]["task_id"]}).json()
    assert blocked["claimed"] is False and blocked["reason"] == "PREVIOUS_TIER_NOT_VERIFIED"

    for t in tasks:
        _complete_one(client, owner_ev, t["task_id"])
    final = client.get(f"/api/fleet/pipeline/cell-plans/{plan['plan_id']}", headers=VIEW).json()["plan"]
    assert final["status"] == "COMPLETED" and final["completed_steps"] == 3


@pytest.mark.parametrize("payload, code", [
    ({
        "mode": "harbor_plan",
        "state": {"C1": "yard-r1-c1-l1", "C2": "yard-r1-c1-l2"},
        "steps": [{"cargo_id": "C1", "src_site": "yard-r1-c1-l1", "dst_site": "stand-r1-c1-l1"}],
    }, "BLOCKED_SOURCE_CARGO"),
    ({
        "mode": "harbor_plan",
        "state": {"C1": "yard-r1-c1-l1", "C2": "yard-r1-c1-l2"},
        "steps": [{"cargo_id": "C2", "src_site": "yard-r1-c1-l2", "dst_site": "yard-r1-c1-l1"}],
    }, "OCCUPIED_DESTINATION"),
    ({
        "mode": "harbor_plan",
        "state": {"C1": "yard-r1-c1-l1"},
        "steps": [{"cargo_id": "C1", "src_site": "yard-r1-c1-l1", "dst_site": "yard-r1-c4-l2"}],
    }, "UNSUPPORTED_DESTINATION_TIER"),
    ({
        "mode": "harbor_plan",
        "steps": [{"src_site": "temp_a-r1-c1-l1", "dst_site": "temp_b-r1-c1-l1"}],
    }, "INVALID_CELL_SITE_ARM"),
    ({
        "mode": "outbound",
        "state": {"C1": "yard-r1-c1-l1"},
        "cargo_id": "C1",
        "steps": [{"src_site": "yard-r1-c1-l1", "dst_site": "stand-r1-c1-l1"}],
    }, "AMBIGUOUS_PLAN_MODE"),
    ({
        "mode": "harbor_plan",
        "steps": [{"src_site": "belt", "dst_site": "belt"}],
    }, "INVALID_CELL_SITE"),
    ({
        "mode": "goal",
        "state": {"C1": "yard-r1-c1-l1"},
        "goal": {"yard:r1-s1": ["C1"], "yard:r1-s2": ["C1"]},
    }, "DUPLICATE_GOAL_CARGO"),
    ({
        "mode": "goal",
        "state": {"C1": "yard-r1-c1-l1"},
        "goal": {"yard:r1-s1": ["C1"]},
    }, "GOAL_ALREADY_SATISFIED"),
    ({
        "mode": "harbor_plan",
        "steps": [{"src_site": "yard-r1-c1-l1", "dst_site": "stand-r1-c1-l1"}],
        "proposer": "spoofed-user",
    }, "CLIENT_PROPOSER_FORBIDDEN"),
])
def test_mode1_and_ambiguous_invalid_plans_reject_with_422_and_write_nothing(monkeypatch, payload, code):
    app, _ = _app(monkeypatch)
    client = TestClient(app)
    before_decisions = len(app.state.pipeline_decisions)
    res = client.post("/api/fleet/pipeline/cell-plans", headers=SVC, json=payload)
    assert res.status_code == 422 and res.json()["detail"]["code"] == code
    assert not app.state.omx_cell_plans and not app.state.omx_cell_tasks
    assert len(app.state.pipeline_decisions) == before_decisions


def test_create_cell_plan_does_not_mutate_decisions_when_later_validation_fails(monkeypatch):
    app, _ = _app(monkeypatch)
    client = TestClient(app)
    res = client.post("/api/fleet/pipeline/cell-plans", headers=SVC, json={
        "mode": "harbor_plan",
        "propose": "yes",
        "steps": [
            {"src_site": "yard-r1-c1-l2", "dst_site": "temp_a-r1-c1-l1"},
            {"src_site": "yard-r1-c1-l1", "dst_site": "stand-r1-c1-l1"},
        ],
    })
    assert res.status_code == 422 and res.json()["detail"]["code"] == "INVALID_CELL_TASK_INPUT"
    assert not app.state.pipeline_decisions
    assert not app.state.omx_cell_plans and not app.state.omx_cell_tasks


def test_mode2_rosy_directive_plans_outbound_rehandle_and_goal_autonomously(monkeypatch):
    app, owner_ev = _app(monkeypatch)
    client = TestClient(app)

    outbound = {
        "request_key": "rosy-outbound-1",
        "mode": "outbound",
        "state": {"C1": "yard-r1-c1-l1", "C2": "yard-r1-c1-l2"},
        "cargo_id": "C1",
        "destination": "stand",
    }
    r1 = client.post("/api/fleet/pipeline/cell-plans", headers=SVC, json=outbound)
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    assert b1["plan"]["order_source"] == "rosy_r"
    assert [t["phase_label"] for t in b1["tasks"]] == ["재취급", "반출", "복귀"]
    assert b1["tasks"][1]["dst_wire_ref"] == "stand-r1-c1-l1"
    assert b1["tasks"][2]["dst_wire_ref"] == "yard-r1-c1-l1"

    # Idempotent replay returns exact same plan; conflicting body returns 409.
    assert client.post("/api/fleet/pipeline/cell-plans", headers=SVC, json=outbound).json()["plan"]["plan_id"] == b1["plan"]["plan_id"]
    conflict = client.post("/api/fleet/pipeline/cell-plans", headers=SVC, json={**outbound, "cargo_id": "C2"})
    assert conflict.status_code == 409 and conflict.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"

    _admit_all(client, b1["tasks"])
    for t in b1["tasks"]:
        _complete_one(client, owner_ev, t["task_id"])
    assert client.get(f"/api/fleet/pipeline/cell-plans/{b1['plan']['plan_id']}", headers=VIEW).json()["plan"]["status"] == "COMPLETED"

    rehandle = {
        "mode": "rehandle",
        "state": {"C1": "yard-r1-c1-l1", "C2": "yard-r1-c1-l2", "C3": "yard-r1-c1-l3"},
        "cargo_id": "C1",
    }
    r2 = client.post("/api/fleet/pipeline/cell-plans/dry-run", headers=VIEW, json=rehandle)
    assert r2.status_code == 200, r2.text
    assert r2.json()["order_source"] == "rosy_r"
    assert r2.json()["final_state"] == {"C1": "yard:r1-s1-t1", "C3": "yard:r1-s1-t2", "C2": "yard:r1-s1-t3"}

    goal = {
        "mode": "goal",
        "state": {"C1": "yard-r1-c1-l1", "C2": "yard-r1-c1-l2"},
        "goal": {"yard:r1-s2": ["C1", "C2"]},
    }
    r3 = client.post("/api/fleet/pipeline/cell-plans/dry-run", headers=VIEW, json=goal)
    assert r3.status_code == 200, r3.text
    assert r3.json()["final_state"] == {"C1": "yard:r1-s2-t1", "C2": "yard:r1-s2-t2"}

    no_stand = client.post("/api/fleet/pipeline/cell-plans", headers=SVC, json={
        "mode": "outbound",
        "state": {"C1": "yard-r1-c1-l1", "C_BLOCK": "stand-r1-c1-l1"},
        "cargo_id": "C1",
        "destination": "stand",
    })
    assert no_stand.status_code == 422 and no_stand.json()["detail"]["code"] == "NO_FREE_OUTBOUND_LANE"


def test_get_cell_plans_by_request_key_reconciles_and_isolates_service_principal(monkeypatch):
    app, _ = _app(monkeypatch)
    client = TestClient(app)
    res = client.post("/api/fleet/pipeline/cell-plans", headers=SVC, json={
        "request_key": "harbor-reconcile-key-1",
        "mode": "harbor_plan",
        "state": {"C1": "yard-r1-c1-l1"},
        "steps": [{"cargo_id": "C1", "src_site": "yard-r1-c1-l1", "dst_site": "stand-r1-c1-l1", "arm_id": "arm_a"}],
    })
    assert res.status_code == 200, res.text
    created = res.json()

    # Same service principal recovers the exact plan + tasks via ?request_key=
    found = client.get("/api/fleet/pipeline/cell-plans", params={"request_key": "harbor-reconcile-key-1"}, headers=SVC)
    assert found.status_code == 200, found.text
    assert found.json()["plan"]["plan_id"] == created["plan"]["plan_id"]
    assert found.json()["plan"]["request_key"] == "harbor-reconcile-key-1"
    assert [t["task_id"] for t in found.json()["tasks"]] == [t["task_id"] for t in created["tasks"]]

    # Another service principal cannot see the first service's request_key (Rule 8 coded 404).
    other_svc = client.get("/api/fleet/pipeline/cell-plans", params={"request_key": "harbor-reconcile-key-1"}, headers=OWNER)
    assert other_svc.status_code == 404
    assert other_svc.json()["detail"]["code"] == "UNKNOWN_CELL_PLAN"

    # Non-existent request_key returns coded 404 for capability probe (Rule 8).
    missing = client.get("/api/fleet/pipeline/cell-plans", params={"request_key": "missing-probe-key"}, headers=SVC)
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "UNKNOWN_CELL_PLAN"


def test_cancel_cell_plan_and_refusal_visibility_and_pydantic_contracts(monkeypatch):
    from pydantic import ValidationError as PydanticValidationError
    from core_common.protocol.cell_plans import CellPlanCancelRequest, CellPlanStepInput

    with pytest.raises(PydanticValidationError):
        CellPlanStepInput(src_site="yard-r1-c1-l1", dst_site="stand-r1-c1-l1", extra_bad="x")  # type: ignore[call-arg]
    with pytest.raises(PydanticValidationError):
        CellPlanCancelRequest(reason="   ")

    app, owner_ev = _app(monkeypatch)
    client = TestClient(app)

    res = client.post("/api/fleet/pipeline/cell-plans", headers=SVC, json={
        "request_key": "cancel-test-1",
        "mode": "harbor_plan",
        "state": {"C1": "yard-r1-c1-l1", "C2": "yard-r1-c1-l2"},
        "steps": [
            {"cargo_id": "C2", "src_site": "yard-r1-c1-l2", "dst_site": "temp_a-r1-c1-l1", "arm_id": "arm_a"},
            {"cargo_id": "C1", "src_site": "yard-r1-c1-l1", "dst_site": "stand-r1-c1-l1", "arm_id": "arm_a"},
        ],
    })
    assert res.status_code == 200
    body = res.json()
    plan_id = body["plan"]["plan_id"]
    tasks = body["tasks"]

    # Another service principal cannot cancel a plan it did not propose.
    forbidden = client.post(f"/api/fleet/pipeline/cell-plans/{plan_id}/cancel", headers=OWNER, json={"reason": "hijack"})
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["code"] == "CELL_PLAN_CANCEL_FORBIDDEN"

    # Invalid empty reason is rejected with 422 INVALID_CANCEL_REASON.
    bad_reason = client.post(f"/api/fleet/pipeline/cell-plans/{plan_id}/cancel", headers=SVC, json={"reason": "  "})
    assert bad_reason.status_code == 422
    assert bad_reason.json()["detail"]["code"] == "INVALID_CANCEL_REASON"

    # Per-step refusal is surfaced on plan.hold_reason and task.last_refusal.
    app.state.cell_task_refusals = {tasks[0]["task_id"]: {"code": "ARM_BUSY_RETRY"}}
    with_refusal = client.get(f"/api/fleet/pipeline/cell-plans/{plan_id}", headers=VIEW).json()
    assert with_refusal["plan"]["hold_reason"] == "ARM_BUSY_RETRY"
    assert with_refusal["tasks"][0]["last_refusal"] == {"code": "ARM_BUSY_RETRY"}

    # Owning service cancels pending steps atomically; plan transitions to CANCELLED with hold_reason.
    cancelled = client.post(f"/api/fleet/pipeline/cell-plans/{plan_id}/cancel", headers=SVC, json={"reason": "operator aborted order"})
    assert cancelled.status_code == 200, cancelled.text
    cbody = cancelled.json()
    assert cbody["cancelled_task_ids"] == [t["task_id"] for t in tasks]
    assert cbody["plan"]["status"] == "CANCELLED"
    assert cbody["plan"]["hold_reason"] == "operator aborted order"

    # Re-cancelling already-cancelled plan returns 409 CELL_PLAN_NOT_CANCELLABLE.
    again = client.post(f"/api/fleet/pipeline/cell-plans/{plan_id}/cancel", headers=SVC, json={"reason": "retry"})
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "CELL_PLAN_NOT_CANCELLABLE"

    # Completed plan also cannot be cancelled.
    res2 = client.post("/api/fleet/pipeline/cell-plans", headers=SVC, json={
        "request_key": "cancel-done-1",
        "mode": "harbor_plan",
        "state": {"C1": "yard-r1-c1-l1"},
        "steps": [{"cargo_id": "C1", "src_site": "yard-r1-c1-l1", "dst_site": "stand-r1-c1-l1", "arm_id": "arm_a"}],
    }).json()
    _admit_all(client, res2["tasks"])
    _complete_one(client, owner_ev, res2["tasks"][0]["task_id"])
    completed_cancel = client.post(f"/api/fleet/pipeline/cell-plans/{res2['plan']['plan_id']}/cancel", headers=OP, json={"reason": "late cancel"})
    assert completed_cancel.status_code == 409
    assert completed_cancel.json()["detail"]["code"] == "CELL_PLAN_NOT_CANCELLABLE"

@pytest.mark.parametrize(("receipt_reason", "hardware_error", "expected"), [
    ("SITE_NOT_CALIBRATED", None, "SITE_NOT_CALIBRATED"),
    ("SITE_NOT_MEASURED", None, "SITE_NOT_MEASURED"),
    ("POLICY_STATE_OUT_OF_RANGE", None, "POLICY_STATE_OUT_OF_RANGE"),
    ("POLICY_START_POSE_MISMATCH", None, "POLICY_START_POSE_MISMATCH"),
    ("MEASURED_PLACEMENT_MISSING", "STAND_NOT_CALIBRATED", "STAND_NOT_CALIBRATED"),
    ("internal operator diagnostic", "/devices/private/tty:error", "MEASURED_PLACEMENT_MISSING"),
])
def test_completed_abort_reason_stays_with_its_task(monkeypatch, tmp_path, receipt_reason, hardware_error, expected):
    from test_pipeline_port_events import _build_app

    app, _ = _build_app(monkeypatch, tmp_path)
    client = TestClient(app)
    plans = "/api/fleet/pipeline/cell-plans"
    res = client.post(plans, json={"mode": "harbor_plan", "steps": [
        {"src_site": "belt", "dst_site": "yard-r1-c1-l1", "cargo_id": "C-1"}]})
    assert res.status_code == 200, res.text
    plan = res.json()["plan"]
    tid, = plan["task_ids"]
    tasks = "/api/fleet/pipeline/cell-tasks"
    claim = client.post(tasks + "/claim", json={"cell_id": "cell_ab", "task_id": tid})
    assert claim.json()["claimed"], claim.text
    done = client.post(f"{tasks}/{tid}/complete", json={"phase": "ABORTED", "reason": receipt_reason,
        "receipt": {"phase":"ABORTED", "reason": receipt_reason}, "hardware_telemetry": {"error": hardware_error}})
    assert done.status_code == 200, done.text
    app.state.cell_task_refusals.clear()
    app.state.omx_cell_states["cell_ab"] = {"phase": "ABORTED", "stage_id": "unrelated", "reason": "another task"}
    detail = client.get(f"{plans}/{plan['plan_id']}").json()
    assert detail["plan"]["hold_reason"] == expected
    assert detail["tasks"][0]["last_refusal"] == {"code": expected, "op": "complete"}
