"""D-1078 opt-in autonomous (no-approval) cell dispatch & safety preservation tests."""
from __future__ import annotations

import hashlib
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

from fleet.hub.registry import RobotRegistry  # noqa: E402
from fleet.pipeline import resolve_omx_cells  # noqa: E402
from fleet.server.auth.site_auth import build_authorize, build_role_guards  # noqa: E402
from fleet.server.sitemap.pipeline_evidence import amr_evidence, omx_owner_evidence  # noqa: E402
from fleet.server.sitemap.pipeline_routes import install_pipeline_routes  # noqa: E402
from rosy_account.principal import SitePrincipal  # noqa: E402
from tools.sim.bay_departure_sim import build_world_261026_site_map  # noqa: E402

SVC = {"Authorization": "Bearer service"}
ALICE = {"Authorization": "Bearer alice"}
OBS = {"Authorization": "Bearer aiobs"}


def _build_env(tmp_path: Path):
    site, graph, _ = build_world_261026_site_map()
    station = resolve_omx_cells(site, graph)["cell_s"].station_xy
    principals = {
        hashlib.sha256(b"service").hexdigest(): SitePrincipal("service", "service"),
        hashlib.sha256(b"alice").hexdigest(): SitePrincipal("alice", "operator"),
        hashlib.sha256(b"aiobs").hexdigest(): SitePrincipal("ai-obs", "ai_observer"),
    }
    auth = build_authorize(None, principals, None)
    req_view, req_op, _, req_prop = build_role_guards(auth, principals)
    app = FastAPI()
    app.state.pipeline_governance_db_path = tmp_path / "gov.sqlite"
    app.state.operator_guard = [Depends(req_op)]
    app.state.proposer_guard = [Depends(req_prop)]
    app.state.amr_still_autostart = False
    app.state.console = SimpleNamespace(hub=SimpleNamespace(registry=RobotRegistry()), _state_sink=None)
    app.state.console.set_state_sink = lambda _s: None
    app.state.map_pose = SimpleNamespace(
        arbitrated_pose=lambda _r: SimpleNamespace(state="LOCALIZED", source="sighting", x=station[0], y=station[1], yaw=0.0, age_s=0.1, map_id="m1"),
        active_map_id=lambda: "m1",
    )
    app.state.site_maps = SimpleNamespace(active=lambda: (1, site, graph, None), rules=SimpleNamespace(active_rules=lambda: None))
    amr_fn = lambda t: {
        "robot_id": t["robot_id"], "cell_id": t["cell_id"], "observed_at": time.time(),
        "wheel_brake_locked": True, "bed_ready": True, "v_cmd_mps": 0.0, "pose": dict(t["pose"]),
    }
    install_pipeline_routes(
        app, site_maps=app.state.site_maps, read_guard=[Depends(req_view)],
        amr_evidence_fn=amr_fn, omx_evidence_fn=lambda t: omx_owner_evidence(app, t),
    )
    return app, TestClient(app, raise_server_exceptions=False)


def test_default_flag_off_keeps_fail_closed_gates(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ROSY_FLEET_AUTONOMOUS_CELL_DISPATCH", raising=False)
    monkeypatch.setenv("ROSY_FLEET_CELL_OWNERS", "cell_s=service;cell_ab=service")
    app, client = _build_env(tmp_path)
    res = client.post("/api/fleet/pipeline/cell-tasks", headers=SVC, json={
        "task_id": "t-def-1", "cell_id": "cell_s", "execution_mode": "act_policy",
    })
    assert res.status_code == 200
    assert res.json()["task"]["status"] == "PROPOSED"

    act_q = client.post("/api/fleet/pipeline/cell-tasks", headers=ALICE, json={
        "task_id": "t-def-act", "cell_id": "cell_s", "execution_mode": "act_policy",
    })
    assert act_q.status_code == 200 and act_q.json()["task"]["status"] == "QUEUED"
    claim = client.post("/api/fleet/pipeline/cell-tasks/claim", headers=SVC, json={
        "cell_id": "cell_s", "task_id": "t-def-act",
    })
    assert claim.json()["claimed"] is False and claim.json()["reason"] == "PRESENCE_CONFIRMATION_REQUIRED"

    app.state.omx_cell_tasks["t-def-act"]["status"] = "ABORTED"
    fb = client.post("/api/fleet/pipeline/cell-tasks", headers=SVC, json={
        "task_id": "t-def-fb", "cell_id": "cell_s", "fallback_from_task_id": "t-def-act", "auto_admit": True,
    })
    assert fb.status_code == 403 and fb.json()["detail"]["code"] == "POLICY_FALLBACK_REQUIRES_NAMED_APPROVAL"


def test_autonomous_dispatch_allows_immediate_queue_fallback_and_preserves_safety(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ROSY_FLEET_AUTONOMOUS_CELL_DISPATCH", "1")
    monkeypatch.setenv("ROSY_FLEET_CELL_OWNERS", "cell_s=service;cell_ab=service")
    monkeypatch.delenv("ROSY_FLEET_CELL_AB_RELEASE_ENABLED", raising=False)
    app, client = _build_env(tmp_path)

    # 1. Explicit propose: true still forces PROPOSED.
    p = client.post("/api/fleet/pipeline/cell-tasks", headers=SVC, json={
        "task_id": "t-explicit-prop", "cell_id": "cell_s", "propose": True,
    })
    assert p.status_code == 200 and p.json()["task"]["status"] == "PROPOSED"

    # 2. Service without propose=True goes directly to QUEUED and claims ACT without presence.
    act = client.post("/api/fleet/pipeline/cell-tasks", headers=SVC, json={
        "task_id": "t-auto-act", "cell_id": "cell_s", "execution_mode": "act_policy",
    })
    assert act.status_code == 200
    t_act = act.json()["task"]
    assert t_act["status"] == "QUEUED" and t_act["approval_mode"] == "autonomous_policy" and t_act["approved_by"] == "autonomous_policy"

    # Non-terminal parent fallback is still blocked (409 POLICY_PARENT_NOT_TERMINAL).
    bad_fb = client.post("/api/fleet/pipeline/cell-tasks", headers=SVC, json={
        "task_id": "t-bad-fb", "cell_id": "cell_s", "fallback_from_task_id": "t-auto-act", "auto_admit": True,
    })
    assert bad_fb.status_code == 409 and bad_fb.json()["detail"]["code"] == "POLICY_PARENT_NOT_TERMINAL"

    # Claim ACT task directly without presence-confirm.
    claimed = client.post("/api/fleet/pipeline/cell-tasks/claim", headers=SVC, json={
        "cell_id": "cell_s", "task_id": "t-auto-act",
    }).json()
    assert claimed["claimed"] is True and claimed["handoff"]["approval_mode"] == "autonomous_policy"

    # Simulate terminal parent & release cell_s, then AI policy->IK fallback goes directly QUEUED.
    app.state.omx_cell_tasks["t-auto-act"]["status"] = "ABORTED"
    app.state.omx_cell_states["cell_s"] = {"phase": "IDLE", "amr_motion_inhibited": False}
    fb = client.post("/api/fleet/pipeline/cell-tasks", headers=SVC, json={
        "task_id": "t-auto-fb", "cell_id": "cell_s", "fallback_from_task_id": "t-auto-act",
        "execution_mode": "guarded_pick", "auto_admit": True,
    })
    assert fb.status_code == 200 and fb.json()["task"]["status"] == "QUEUED"

    # Depth > 2 is still blocked.
    app.state.omx_cell_tasks["t-auto-fb"]["status"] = "ABORTED"
    fb2 = client.post("/api/fleet/pipeline/cell-tasks", headers=SVC, json={
        "task_id": "t-auto-fb2", "cell_id": "cell_s", "fallback_from_task_id": "t-auto-fb",
    })
    assert fb2.status_code == 200
    fb3 = client.post("/api/fleet/pipeline/cell-tasks", headers=SVC, json={
        "task_id": "t-auto-fb3", "cell_id": "cell_s", "fallback_from_task_id": "t-auto-fb2",
    })
    assert fb3.status_code == 409 and fb3.json()["detail"]["code"] == "FALLBACK_RETRY_LIMIT_EXCEEDED"

    # Safety gates remain intact: cell_ab flag off refuses claim; human_detected refuses claim.
    ab = client.post("/api/fleet/pipeline/cell-tasks", headers=SVC, json={
        "task_id": "t-ab-1", "cell_id": "cell_ab", "arm_id": "arm_a", "dst_site": "yard:r1-s1-t1", "tier": 1,
    })
    assert ab.status_code == 200 and ab.json()["task"]["status"] == "QUEUED"
    ab_claim = client.post("/api/fleet/pipeline/cell-tasks/claim", headers=SVC, json={
        "cell_id": "cell_ab", "task_id": "t-ab-1",
    }).json()
    assert ab_claim["claimed"] is False and ab_claim["reason"] == "CELL_AB_EVIDENCE_NOT_ENABLED"

    monkeypatch.setenv("ROSY_FLEET_CELL_AB_RELEASE_ENABLED", "1")
    app.state.human_detected["cell_ab"] = True
    ab_human = client.post("/api/fleet/pipeline/cell-tasks/claim", headers=SVC, json={
        "cell_id": "cell_ab", "task_id": "t-ab-1",
    }).json()
    assert ab_human["claimed"] is False and ab_human["reason"] == "HUMAN_DETECTED_ESTOP"

    # Tasks explicitly requiring presence must not receive autonomous_policy mode or bypass claim presence.
    req_p = client.post("/api/fleet/pipeline/cell-tasks", headers=SVC, json={
        "task_id": "t-req-pres", "cell_id": "cell_s", "requires_presence_confirm": True,
    })
    assert req_p.status_code == 200
    assert "approval_mode" not in req_p.json()["task"]
    req_claim = client.post("/api/fleet/pipeline/cell-tasks/claim", headers=SVC, json={
        "cell_id": "cell_s", "task_id": "t-req-pres",
    }).json()
    assert req_claim["claimed"] is False and req_claim["reason"] == "PRESENCE_CONFIRMATION_REQUIRED"
