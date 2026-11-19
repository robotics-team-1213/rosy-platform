"""Cell Real-to-Sim / Sim-to-Real closed-loop pipeline API tests (D-947, D-1012)."""
from pathlib import Path
import shutil
from types import SimpleNamespace
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from fleet.server.cell_app_routes import install_cell_app_routes
from fleet.server.cell_real2sim import ENV_PHYSICS, ENV_SNAPSHOTS, RUN_SCHEMA, SCHEMA, ROOT

VIEWER = {"Authorization": "Bearer viewer-secret"}
OPERATOR = {"Authorization": "Bearer operator-secret"}


def _client(tmp_path):
    app = FastAPI()

    def require_viewer(authorization: str | None = Header(None)):
        if authorization not in ("Bearer viewer-secret", "Bearer operator-secret"):
            raise HTTPException(401, detail={"code": "UNAUTHORIZED"})
        return SimpleNamespace(principal_id="viewer-1", role="viewer")

    def require_named_operator(authorization: str | None = Header(None)):
        if authorization != "Bearer operator-secret":
            raise HTTPException(403, detail={"code": "FORBIDDEN"})
        return SimpleNamespace(principal_id="operator-1", role="operator")

    mission_service = SimpleNamespace(store=SimpleNamespace(path=tmp_path / "missions.db"))
    install_cell_app_routes(
        app,
        mission_service=mission_service,
        compiler=None,
        service_id=None,
        principals={},
        proposal_create=None,
        proposal_resolve=None,
        require_viewer=require_viewer,
        require_named_operator=require_named_operator,
    )
    return TestClient(app)


def test_real2sim_pipeline_reads_snapshots_cad_inventory_sysid_and_stages(tmp_path):
    client = _client(tmp_path)
    response = client.get("/api/fleet/cell-app/real2sim-pipeline", headers=VIEWER)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema"] == SCHEMA
    assert len(body["snapshots"]) >= 3
    assert body["active"]["id"] == "20261112-1838"
    assert body["previous"]["id"] == "20261112-0254"
    fix = body["active"]["ship_fixation"]
    assert fix["berth_kit"] == "v16-modular"
    assert fix["temp_bridge"] == "v7"
    assert fix["stopper_drop_mm"] == 20.0
    assert "arm_a_gap_dy_mm" in fix and "belt_to_stopper_flat_mm" in fix
    cad = body["cad_inventory"]
    assert cad["berth_kit"] == "v16-modular"
    assert cad["mesh_count"] >= 14
    sysid = body["sysid_summary"]
    assert sysid["twin_camera_outline_px"] <= 3.0
    assert sysid["best_fit_id"] == "fit-servo-run3"
    assert sysid["best_holdout_rms_deg"] == 0.41
    assert len(sysid["fits"]) >= 2
    assert len(sysid["next_experiments"]) >= 5
    stages = {s["stage"]: s for s in body["stages"]}
    assert stages["mujoco"]["stage_order"] == 1
    assert stages["isaac"]["stage_order"] == 2
    assert stages["isaac"]["isaac_handoff"]["schema"] == "rosy.omx-isaac-handoff.v1"
    assert stages["gazebo"]["track"] == "ros2_execution_contract"
    assert len(body["loop_steps"]) == 7
    assert client.get("/api/fleet/cell-app/real2sim-pipeline").status_code == 401


def test_real2sim_pipeline_evaluate_and_queue_runs(tmp_path):
    client = _client(tmp_path)
    payload = {
        "snapshot_id": "20261110-1231",
        "prev_id": "20261108-2257",
        "berth_kit": "v16-modular",
        "ship_spacer_dy_mm": 43.0,
        "ship_stern_hook_mm": 5.0,
        "compensate_zero": True,
        "cam_jitter": True,
        "physics": "servo-antijitter-20261112",
    }
    assert client.post("/api/fleet/cell-app/real2sim-pipeline/evaluate", headers=VIEWER, json=payload).status_code == 403
    res = client.post("/api/fleet/cell-app/real2sim-pipeline/evaluate", headers=OPERATOR, json=payload)
    assert res.status_code == 200, res.text
    body = res.json()
    fix = body["active"]["ship_fixation"]
    assert fix["nominal_spacer_dy_mm"] == 43.0
    assert fix["stern_hook_mm"] == 5.0
    isaac = next(s for s in body["stages"] if s["stage"] == "isaac")
    assert isaac["isaac_handoff"]["physics"] == "servo-antijitter-20261112"

    assert client.post("/api/fleet/cell-app/real2sim-pipeline/runs", headers=VIEWER, json=payload).status_code == 403
    run_res = client.post("/api/fleet/cell-app/real2sim-pipeline/runs", headers=OPERATOR, json=payload)
    assert run_res.status_code == 200, run_res.text
    queued = run_res.json()
    assert queued["run"]["schema"] == RUN_SCHEMA
    assert queued["run"]["status"] == "QUEUED"
    assert queued["run"]["created_by"] == "operator-1"
    assert queued["run"]["isaac_handoff"]["schema"] == "rosy.omx-isaac-handoff.v1"
    assert len(queued["runs"]) == 1


def test_real2sim_pipeline_promote_physics_candidate(tmp_path, monkeypatch):
    client = _client(tmp_path)
    temp_phys = tmp_path / "cell_physics.yaml"
    shutil.copyfile(ROOT / "learning/envs/isaac/cell_physics.yaml", temp_phys)
    monkeypatch.setenv(ENV_PHYSICS, str(temp_phys))

    res = client.post(
        "/api/fleet/cell-app/real2sim-pipeline/promote-physics",
        headers=OPERATOR,
        json={"fit_id": "fit-servo-run3", "candidate_name": "servo-friction-promoted-test"},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["promoted"] == "servo-friction-promoted-test"
    names = [c["name"] for c in data["physics_candidates"]]
    assert "servo-friction-promoted-test" in names

    bad = client.post(
        "/api/fleet/cell-app/real2sim-pipeline/promote-physics",
        headers=OPERATOR,
        json={"fit_id": "fit-servo-run1", "candidate_name": "should-fail-bound"},
    )
    assert bad.status_code == 422


def test_real2sim_pipeline_handles_missing_or_empty_snapshot_dir(tmp_path, monkeypatch):
    client = _client(tmp_path)
    empty_dir = tmp_path / "empty_snaps"
    empty_dir.mkdir()
    monkeypatch.setenv(ENV_SNAPSHOTS, str(empty_dir))
    res = client.get("/api/fleet/cell-app/real2sim-pipeline", headers=VIEWER)
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "CELL_REAL2SIM_UNAVAILABLE"
