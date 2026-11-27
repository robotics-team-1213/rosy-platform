"""PR-5 governance tests: PROPOSE->QUEUED admit CAS, SQLite generations, interlock_scope, cell readiness, and tools."""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
for _p in (ROOT, ROOT / "contracts/foundation", ROOT / "operations/decision/src", ROOT / "operations/fleet", ROOT / "operations/account"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from core_common.intent import IntentError, interpret  # noqa: E402
from core_common.protocol.cell_failure_context import FALLBACK_VERBS  # noqa: E402
from fleet.hub.registry import RobotRegistry  # noqa: E402
from fleet.pipeline import resolve_omx_cells  # noqa: E402
from fleet.server.assistant.context import build_context  # noqa: E402
from fleet.server.auth.site_auth import build_authorize, build_role_guards  # noqa: E402
from fleet.server.sitemap.pipeline_evidence import amr_evidence, omx_owner_evidence  # noqa: E402
from fleet.server.sitemap.pipeline_routes import install_pipeline_routes  # noqa: E402
from rosy.decision.model_tool_catalog import MODEL_TOOL_CATALOG, provider_tool_schemas  # noqa: E402
from rosy_account.principal import SitePrincipal  # noqa: E402
from tools.sim.bay_departure_sim import build_world_261026_site_map  # noqa: E402

SVC = {"Authorization": "Bearer service"}
ALICE = {"Authorization": "Bearer alice"}
BOB = {"Authorization": "Bearer bob"}
OBS = {"Authorization": "Bearer aiobs"}
CONSOLE = {"Authorization": "Bearer console"}
VIEW = {"Authorization": "Bearer viewer"}


def _build_env(tmp_path: Path, *, db_path: Path | str | None = None, amr_ok: bool = False):
    site, graph, _ = build_world_261026_site_map()
    station = resolve_omx_cells(site, graph)["cell_s"].station_xy
    principals = {
        hashlib.sha256(b"service").hexdigest(): SitePrincipal("service", "service"),
        hashlib.sha256(b"alice").hexdigest(): SitePrincipal("alice", "operator"),
        hashlib.sha256(b"bob").hexdigest(): SitePrincipal("bob", "operator"),
        hashlib.sha256(b"aiobs").hexdigest(): SitePrincipal("ai-obs", "ai_observer"),
        hashlib.sha256(b"console").hexdigest(): SitePrincipal("site-console", "operator"),
        hashlib.sha256(b"viewer").hexdigest(): SitePrincipal("viewer", "viewer"),
    }
    auth = build_authorize(None, principals, None)
    req_view, req_op, _, req_prop = build_role_guards(auth, principals)
    app = FastAPI()
    if db_path is not None:
        app.state.pipeline_governance_db_path = db_path
    app.state.operator_guard = [Depends(req_op)]
    app.state.proposer_guard = [Depends(req_prop)]
    app.state.amr_still_autostart = False
    reg = RobotRegistry()
    app.state.console = SimpleNamespace(hub=SimpleNamespace(registry=reg), _state_sink=None)
    app.state.console.set_state_sink = lambda _s: None
    app.state.map_pose = SimpleNamespace(
        arbitrated_pose=lambda _r: SimpleNamespace(state="LOCALIZED", source="sighting", x=station[0], y=station[1], yaw=0.0, age_s=0.1, map_id="m1"),
        active_map_id=lambda: "m1",
    )
    app.state.site_maps = SimpleNamespace(active=lambda: (1, site, graph, None), rules=SimpleNamespace(active_rules=lambda: None))
    amr_fn = (
        (lambda t: {"robot_id": t["robot_id"], "cell_id": t["cell_id"], "observed_at": time.time(),
                    "wheel_brake_locked": True, "bed_ready": True, "v_cmd_mps": 0.0, "pose": dict(t["pose"])})
        if amr_ok else (lambda t: amr_evidence(app, t))
    )
    install_pipeline_routes(app, site_maps=app.state.site_maps, read_guard=[Depends(req_view)],
                            amr_evidence_fn=amr_fn, omx_evidence_fn=lambda t: omx_owner_evidence(app, t))
    return app, TestClient(app, raise_server_exceptions=False)


def test_cell_readiness_reports_folded_only_from_a_recent_report(tmp_path):
    app, client = _build_env(tmp_path)

    def arm():
        return client.get("/api/fleet/pipeline/cells/cell_s/readiness", headers=VIEW).json()["arms"]["arm_s"]

    assert arm()["folded"] is None  # the boot default pose says folded; nobody observed it
    assert arm()["state_unknown"] == {"reason": "never_observed", "last_observed_at": None}
    live = app.state.arm_live_states["arm_s"]
    live.update(folded=True, updated_at=time.time(), folded_updated_at=time.time(), source="live_stream")
    assert arm()["folded"] is True and arm()["state_unknown"] is None
    old = time.time() - 3600
    live.update(folded_updated_at=old, updated_at=time.time())  # a later row without a fold report refreshes nothing
    assert arm()["folded"] is None and arm()["state_unknown"] == {"reason": "stale", "last_observed_at": old}


def test_propose_admit_cas_and_interlock_scope(tmp_path):
    app, client = _build_env(tmp_path)
    sha = "a" * 64
    rdy = client.get("/api/fleet/pipeline/cells/cell_s/readiness", headers=VIEW).json()
    assert rdy["schema"] == "rosy.fleet-cell-readiness.v1" and rdy["readiness_digest"]

    # Client-supplied proposer & non-bool propose are rejected; invalid fallback_verb rejected.
    assert client.post("/api/fleet/pipeline/cell-tasks", headers=ALICE, json={"cell_id": "cell_s", "propose": True, "proposer": "other"}).status_code == 422
    assert client.post("/api/fleet/pipeline/cell-tasks", headers=ALICE, json={"cell_id": "cell_s", "propose": "true"}).status_code == 422
    assert client.post("/api/fleet/pipeline/cell-tasks", headers=ALICE, json={"cell_id": "cell_s", "fallback_verb": "invented"}).status_code == 422

    # Service creates PROPOSED (does not bump dispatch_generation); interlock_scope derived server-side.
    dg_before = app.state.pipeline_governance.snapshot()["dispatch_generation"]
    created = client.post("/api/fleet/pipeline/cell-tasks", headers=SVC, json={
        "task_id": "t-prop-1", "cell_id": "cell_s", "src_site": "pinky", "dst_site": "belt",
        "interlock_scope": "cell_internal", "failure_bundle_id": "b1", "failure_context_sha256": sha,
    })
    assert created.status_code == 200
    assert app.state.pipeline_governance.snapshot()["dispatch_generation"] == dg_before
    t = created.json()["task"]
    assert t["status"] == "PROPOSED" and t["interlock_scope"] == "amr_bed" and t["approved_by"] is None

    # Service/ai_observer/site-console cannot admit; empty CAS, bad CAS types, or malformed JSON fail closed.
    assert client.post("/api/fleet/pipeline/cell-tasks/claim", headers=SVC, json={"cell_id": "cell_s"}).json()["claimed"] is False
    assert client.post("/api/fleet/pipeline/cell-tasks/t-prop-1/admit", headers=SVC, json={}).status_code == 403
    assert client.post("/api/fleet/pipeline/cell-tasks/t-prop-1/admit", headers=OBS, json={}).status_code == 403
    assert client.post("/api/fleet/pipeline/cell-tasks/t-prop-1/admit", headers=CONSOLE, json={}).status_code == 403
    assert client.post("/api/fleet/pipeline/cell-tasks/t-prop-1/admit", headers=BOB, json={}).status_code == 409
    assert client.post("/api/fleet/pipeline/cell-tasks/t-prop-1/admit", headers=BOB, content=b"{bad-json").status_code == 422

    # Self-proposed task cannot be admitted by same principal_id; multi-step preset honors propose=True.
    self_t = client.post("/api/fleet/pipeline/cell-tasks", headers=ALICE, json={
        "task_id": "t-self", "cell_id": "cell_ab", "dst_site": "yard:r1-s1-t1", "propose": True,
    })
    assert self_t.json()["task"]["status"] == "PROPOSED" and self_t.json()["task"]["interlock_scope"] == "cell_internal"
    assert client.post("/api/fleet/pipeline/cell-tasks/t-self/admit", headers=ALICE, json={
        "expected_readiness_digest": rdy["readiness_digest"], "expected_dispatch_generation": rdy["dispatch_generation"],
        "expected_stop_generation": rdy["stop_generation"],
    }).status_code == 403
    multi = client.post("/api/fleet/pipeline/cell-tasks", headers=ALICE, json={"preset": "full_s3_to_s5_pipeline", "propose": True})
    assert multi.status_code == 200 and all(row["status"] == "PROPOSED" for row in multi.json()["tasks"])
    assert client.post(f"/api/fleet/pipeline/cell-tasks/{multi.json()['task']['task_id']}/cancel", headers=ALICE).status_code == 200

    # Bool/bad types in CAS fail 409 (not 500); stale SHA fails 409 without mutating task.
    bad_type = client.post("/api/fleet/pipeline/cell-tasks/t-prop-1/admit", headers=BOB, json={
        "expected_context_sha256": sha, "expected_readiness_digest": rdy["readiness_digest"],
        "expected_dispatch_generation": True, "expected_stop_generation": "0",
    })
    assert bad_type.status_code == 409 and app.state.omx_cell_tasks["t-prop-1"]["status"] == "PROPOSED"

    # Bump stop_generation via cell-quality, human-safety-gate, & vision-auto-check -> old stop_generation fails 409.
    rdy_before = client.get("/api/fleet/pipeline/cells/cell_s/readiness", headers=VIEW).json()
    client.post("/api/fleet/pipeline/cell-quality", headers=SVC, json={"arm_holds": {"arm_s": {"local_held": True}}})
    client.post("/api/fleet/pipeline/human-safety-gate", headers=ALICE, json={"cell_id": "cell_s", "human_detected": True})
    rdy_gate = client.get("/api/fleet/pipeline/cells/cell_s/readiness", headers=VIEW).json()
    assert rdy_gate["stop_generation"] >= rdy_before["stop_generation"] + 2 and "active_estop" in rdy_gate["blocking_refusals"]
    client.post("/api/fleet/pipeline/vision-auto-check", headers=ALICE, json={"cell_id": "cell_s", "intrusion_score": 0.9})
    rdy_vis = client.get("/api/fleet/pipeline/cells/cell_s/readiness", headers=VIEW).json()
    assert rdy_vis["stop_generation"] == rdy_gate["stop_generation"] + 1
    assert client.post("/api/fleet/pipeline/cell-tasks/t-prop-1/admit", headers=BOB, json={
        "expected_context_sha256": sha, "expected_readiness_digest": rdy_before["readiness_digest"],
        "expected_dispatch_generation": rdy_before["dispatch_generation"], "expected_stop_generation": rdy_before["stop_generation"],
    }).status_code == 409

    # Ledger fault during admit rolls back status & admitted lock; clearing fault lets admit succeed cleanly.
    rdy_now = client.get("/api/fleet/pipeline/cells/cell_s/readiness", headers=VIEW).json()
    cas_body = {
        "expected_context_sha256": sha, "expected_readiness_digest": rdy_now["readiness_digest"],
        "expected_dispatch_generation": rdy_now["dispatch_generation"], "expected_stop_generation": rdy_now["stop_generation"],
    }
    app.state._pipeline_ledger_fault = True
    assert client.post("/api/fleet/pipeline/cell-tasks/t-prop-1/admit", headers=BOB, json=cas_body).status_code == 503
    assert app.state.omx_cell_tasks["t-prop-1"]["status"] == "PROPOSED"
    app.state._pipeline_ledger_fault = False

    admitted = client.post("/api/fleet/pipeline/cell-tasks/t-prop-1/admit", headers=BOB, json=cas_body)
    assert admitted.status_code == 200 and admitted.json()["task"]["status"] == "QUEUED"
    assert admitted.json()["task"]["approved_by"] == "bob"


def test_idempotency_sqlite_persistence_and_fallback_limits(tmp_path):
    db_file = tmp_path / "gov.sqlite3"
    app1, client1 = _build_env(tmp_path, db_path=db_file)
    p = {"task_id": "idem-1", "cell_id": "cell_s", "request_key": "rk-001"}
    r1 = client1.post("/api/fleet/pipeline/cell-tasks", headers=ALICE, json=p)
    r2 = client1.post("/api/fleet/pipeline/cell-tasks", headers=ALICE, json=p)
    assert r1.status_code == 200 and r2.status_code == 200 and r2.json()["task"]["task_id"] == "idem-1"
    assert client1.post("/api/fleet/pipeline/cell-tasks", headers=ALICE, json={**p, "task_id": "idem-2"}).status_code == 409
    # Principal-scoped idempotency prevents cross-principal replay; multi-tier single-bump CAS works; failed create preserves displaced_site.
    svc_same_key = client1.post("/api/fleet/pipeline/cell-tasks", headers=SVC, json={**p, "task_id": "idem-svc-1"})
    assert svc_same_key.status_code == 200 and svc_same_key.json()["task"]["status"] == "PROPOSED"
    rdy_t = client1.get("/api/fleet/pipeline/cells/cell_ab/readiness", headers=VIEW).json()
    tiers_ok = client1.post("/api/fleet/pipeline/cell-tasks", headers=ALICE, json={
        "task_id": "tiers-1", "cell_id": "cell_ab", "dst_site": "pallet",
        "tiers": [1, 2], "expected_dispatch_generation": rdy_t["dispatch_generation"],
    })
    assert tiers_ok.status_code == 200 and len(tiers_ok.json()["tasks"]) == 2
    assert app1.state.pipeline_governance.snapshot()["dispatch_generation"] == rdy_t["dispatch_generation"] + 1
    app1.state.detected_displaced_site = "belt_far"
    assert client1.post("/api/fleet/pipeline/cell-tasks", headers=ALICE, json={"cell_id": "cell_s", "fallback_verb": "bad"}).status_code == 422
    assert app1.state.detected_displaced_site == "belt_far"

    # Bed confirmation is NOT resurrected across process restart (D-1057); presence reloads safely while valid.
    client1.post("/api/fleet/pipeline/cell-tasks/idem-1/bed-confirm", headers=ALICE, json={"robot_id": "rosy_01"})
    snap1 = app1.state.pipeline_governance.snapshot()
    app1.state.pipeline_governance.save_confirmation("presence", "idem-1", {"task_id": "idem-1", "principal_id": "alice", "confirmed_at": time.time()})
    app2, client2 = _build_env(tmp_path, db_path=db_file)
    snap2 = app2.state.pipeline_governance.snapshot()
    assert snap2["authority_epoch"] == snap1["authority_epoch"] + 1
    assert snap2["dispatch_generation"] == snap1["dispatch_generation"]
    assert app2.state.cell_bed_confirmations == {}
    assert "idem-1" in app2.state.cell_presence

    # act_policy -> guarded_pick requires terminal parent, named operator, retry <= 1, and immutable server depth <= 2.
    client2.post("/api/fleet/pipeline/cell-tasks", headers=ALICE, json={
        "task_id": "act-parent", "cell_id": "cell_s", "execution_mode": "act_policy", "max_chunks": 2,
    })
    assert client2.post("/api/fleet/pipeline/cell-tasks", headers=ALICE, json={
        "task_id": "fb-nonterm", "cell_id": "cell_s", "fallback_from_task_id": "act-parent",
    }).status_code == 409
    app2.state.omx_cell_tasks["act-parent"]["status"] = "ABORTED"
    bad_swap = client2.post("/api/fleet/pipeline/cell-tasks", headers=ALICE, json={
        "task_id": "fb-auto", "cell_id": "cell_s", "fallback_from_task_id": "act-parent", "auto_admit": True,
    })
    assert bad_swap.status_code == 403 and bad_swap.json()["detail"]["code"] == "POLICY_FALLBACK_REQUIRES_NAMED_APPROVAL"
    fb1 = client2.post("/api/fleet/pipeline/cell-tasks", headers=ALICE, json={
        "task_id": "fb-1", "cell_id": "cell_s", "fallback_from_task_id": "act-parent",
    })
    assert fb1.status_code == 200 and fb1.json()["task"]["requires_named_approval"] is True
    assert client2.post("/api/fleet/pipeline/cell-tasks", headers=ALICE, json={
        "task_id": "fb-2", "cell_id": "cell_s", "fallback_from_task_id": "act-parent",
    }).status_code == 409
    d1 = client2.post("/api/fleet/pipeline/cell-tasks", headers=ALICE, json={
        "task_id": "fb-d1", "cell_id": "cell_s", "fallback_from_task_id": "fb-1",
    })
    assert d1.status_code == 200 and d1.json()["task"]["fallback_chain_depth"] == 2
    assert client2.post("/api/fleet/pipeline/cell-tasks", headers=ALICE, json={
        "task_id": "fb-cheat", "cell_id": "cell_s", "fallback_from_task_id": "fb-1", "fallback_chain_depth": 0,
    }).status_code == 409
    assert client2.post("/api/fleet/pipeline/cell-tasks", headers=ALICE, json={
        "task_id": "fb-d2", "cell_id": "cell_s", "fallback_from_task_id": "fb-d1",
    }).status_code == 409


def test_assistant_context_cell_tool_catalog_and_intent_keys(tmp_path):
    app, client = _build_env(tmp_path)
    app.state.omx_cell_states = {"cell_s": {"phase": "IDLE"}, "cell_ab": {"phase": "ARM_IN_BED_ZONE"}}
    client.post("/api/fleet/pipeline/cell-tasks", headers=SVC, json={"task_id": "p-ctx", "cell_id": "cell_s"})

    class _Gather:
        _snapshot = {"robots": [{"robot_id": "pinky_1", "online": True, "state": {"mode": "IDLE", "safety": {"estop": False}}}]}
        gathered_at = time.time()
        _console = SimpleNamespace(_clock=lambda: time.time())

        async def __call__(self):
            return self._snapshot

    app.state.fleet_gather = _Gather()
    import asyncio
    facts = asyncio.run(build_context(app, SitePrincipal("alice", "operator"), None, locale="en-US"))
    refs = {f.ref for f in facts}
    assert "cell:cell_s" in refs and "cell:cell_ab" in refs

    cell_tools = provider_tool_schemas(scope="cell")
    assert [t["name"] for t in cell_tools] == ["get_cell_readiness", "get_cell_failure_context", "propose_cell_fallback"]
    prop_params = MODEL_TOOL_CATALOG["propose_cell_fallback"].parameters
    assert prop_params["properties"]["verb"]["enum"] == list(FALLBACK_VERBS)
    assert {"expected_readiness_digest", "expected_dispatch_generation", "expected_stop_generation"} <= set(prop_params["required"])
    assert [t["name"] for t in provider_tool_schemas(scope="mission")] == ["get_mission_status", "propose_replan"]
    assert all(MODEL_TOOL_CATALOG[t["name"]].device_action_api is False for t in cell_tools)

    for bad_key in ("joints", "pwm", "torque", "coil", "plc_register", "chunk_cmd"):
        with pytest.raises(IntentError) as exc_info:
            interpret({"do": "home", "robot": "r1", bad_key: 1})
        assert exc_info.value.code == "FORBIDDEN"
