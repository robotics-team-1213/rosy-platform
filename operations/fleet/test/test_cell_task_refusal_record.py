"""The cell-task ledger row keeps the last claim/complete refusal and shows the operator bed confirmation (console)."""
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet.server.pipeline_routes import install_pipeline_routes


def _client(**kwargs):
    from tools.sim.bay_departure_sim import build_world_261026_site_map

    site, graph, _ = build_world_261026_site_map()
    app = FastAPI()
    install_pipeline_routes(app, site_maps=SimpleNamespace(active=lambda: (1, site, graph, None)), **kwargs)
    return app, TestClient(app)


def _row(client, task_id):
    return next(t for t in client.get("/api/fleet/pipeline/cell-tasks").json()["tasks"] if t["task_id"] == task_id)


def test_claim_refusal_is_recorded_on_the_row_without_changing_the_answer():
    _, client = _client()
    client.post("/api/fleet/pipeline/cell-tasks", json={"task_id": "t1", "cell_id": "cell_s"})
    blocked = client.post("/api/fleet/pipeline/cell-tasks/claim", json={"cell_id": "cell_s"}).json()
    assert blocked["claimed"] is False and blocked["reason"] == "AMR_BRAKE_BED_VELOCITY_UNMEASURED"
    refusal = _row(client, "t1")["last_refusal"]
    assert refusal["code"] == "AMR_BRAKE_BED_VELOCITY_UNMEASURED" and refusal["op"] == "claim"
    assert _row(client, "t1")["status"] == "QUEUED"


def test_complete_refusal_is_recorded_and_a_successful_claim_clears_the_old_one():
    def measured(task):
        return {"robot_id": task["robot_id"], "cell_id": task["cell_id"], "observed_at": time.time(),
                "wheel_brake_locked": True, "bed_ready": True, "v_cmd_mps": 0.0, "pose": dict(task["pose"])}

    app, client = _client(amr_evidence_fn=measured)
    client.post("/api/fleet/pipeline/cell-tasks", json={"task_id": "t2", "cell_id": "cell_s"})
    app.state.cell_task_refusals["t2"] = {"code": "AMR_BRAKE_BED_VELOCITY_UNMEASURED", "op": "claim", "at": 1.0}
    assert client.post("/api/fleet/pipeline/cell-tasks/claim", json={"task_id": "t2", "cell_id": "cell_s"}).json()["claimed"]
    assert "last_refusal" not in _row(client, "t2")
    refused = client.post("/api/fleet/pipeline/cell-tasks/t2/complete", json={"phase": "RELEASED"})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "OMX_OWNER_EVIDENCE_UNAVAILABLE"
    row = _row(client, "t2")
    assert row["status"] == "RUNNING"
    assert row["last_refusal"]["code"] == "OMX_OWNER_EVIDENCE_UNAVAILABLE" and row["last_refusal"]["op"] == "complete"


def test_list_shows_bed_confirmation_age_and_void_without_storing_it_on_the_ledger():
    app, client = _client()
    client.post("/api/fleet/pipeline/cell-tasks", json={"task_id": "t3", "cell_id": "cell_s"})
    assert "bed_confirmation" not in _row(client, "t3")
    app.state.cell_bed_confirmations = {"t3": {"principal_id": "kim", "confirmed_at": time.time() - 30, "invalid": True}}
    bed = _row(client, "t3")["bed_confirmation"]
    assert bed["principal_id"] == "kim" and bed["invalid"] is True and 29 <= bed["age_s"] <= 31
    assert "bed_confirmation" not in app.state.omx_cell_tasks["t3"]


def test_malformed_completion_is_not_recorded_as_a_refusal():
    app, client = _client()
    client.post("/api/fleet/pipeline/cell-tasks", json={"task_id": "t4", "cell_id": "cell_s"})
    assert client.post("/api/fleet/pipeline/cell-tasks/t4/complete", json={"phase": "RELEASED"}).status_code == 409
    assert "last_refusal" not in _row(client, "t4") and "last_refusal" not in app.state.omx_cell_tasks["t4"]
