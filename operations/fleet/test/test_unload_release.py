"""A docked Pinky is released only when the ledger, the cell's camera and the measured arm fold agree (2026-11-19)."""
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet.server.sitemap.pipeline_unload_release import unload_release


def _state(n=3, done=3, objects=0, folded=True, age=5.0, phase="RELEASED", held=False, aborted=False):
    now = time.time()
    tasks = {}
    for i in range(n):
        status = "COMPLETED" if i < done else "QUEUED"
        if aborted and i == n - 1:
            status = "ABORTED"
        tasks[f"u-{i}"] = {"task_id": f"u-{i}", "robot_id": "rosy_46", "unload_batch_id": "u", "unload_expected": n,
                           "unload_index": i, "status": status, "created_at": now - 100 + i, "completed_at": now - 50 + i,
                           "stage_result": {"source_clearance": {"objects": objects if i == done - 1 else 1}}}
    return SimpleNamespace(
        omx_cell_tasks=tasks, omx_cell_states={"cell_s": {"phase": phase, "amr_motion_inhibited": False}},
        arm_live_states={"arm_s": {"folded": folded, "updated_at": now - age}},
        arm_holds={"arm_s": {"held": held}}, unload_releases={}), now


def reasons(**kw):
    state, now = _state(**kw)
    return unload_release(state, "rosy_46", now=now, human_detected=False)["reasons"]


def test_all_agree_is_ready():
    state, now = _state()
    out = unload_release(state, "rosy_46", now=now, human_detected=False)
    assert out["ready"] and out["expected"] == 3 and out["completed"] == 3 and out["reasons"] == []


def test_each_disagreement_holds_the_vehicle():
    assert "COUNT_MISMATCH" in reasons(done=1)  # first box placed must not release a 3-box Pinky (old per-job release)
    assert reasons(objects=1) == ["CARGO_NOT_EMPTY"]
    assert reasons(objects=None) == ["BED_NOT_OBSERVED"]
    assert reasons(folded=False) == ["ARM_NOT_HOME"]
    assert reasons(age=600.0) == ["ARM_NOT_HOME"]  # a stale fold is not a fold
    assert reasons(phase="ARM_IN_BED_ZONE") == ["CELL_NOT_RELEASED"]
    assert reasons(held=True) == ["ARM_HELD"]
    assert "UNLOAD_ABORTED" in reasons(aborted=True)
    state, now = _state()
    assert unload_release(state, "rosy_46", now=now, human_detected=True)["reasons"] == ["HUMAN_HOLD"]
    assert unload_release(state, "other", now=now, human_detected=False)["reasons"] == ["NO_UNLOAD_BATCH"]


def _client(tmp_path, monkeypatch):
    from tools.sim.bay_departure_sim import build_world_261026_site_map
    from fleet.server.sitemap import pipeline_routes as routes

    site, graph, _ = build_world_261026_site_map()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(routes, "_storage_dir", lambda: tmp_path)
    app = FastAPI()
    routes.install_pipeline_routes(app, site_maps=SimpleNamespace(active=lambda: (1, site, graph, None)))
    return app, TestClient(app)


def test_unload_batch_chains_one_task_per_container_and_depart_is_gated(tmp_path, monkeypatch):
    app, client = _client(tmp_path, monkeypatch)
    made = client.post("/api/fleet/pipeline/pinky-tasks", json={
        "action": "dock_and_unload_s3", "robot_id": "rosy_46", "container_count": 3})
    assert made.status_code == 200
    batch = [t for t in app.state.omx_cell_tasks.values() if t.get("unload_batch_id")]
    assert len(batch) == 3 and {t["unload_expected"] for t in batch} == {3}
    by_index = sorted(batch, key=lambda t: t["unload_index"])
    assert [t["depends_on"] for t in by_index] == [None, by_index[0]["task_id"], by_index[1]["task_id"]]
    assert client.post("/api/fleet/pipeline/pinky-tasks", json={
        "action": "dock_and_unload_s3", "robot_id": "rosy_46", "container_count": 0}).status_code == 422

    early = client.post("/api/fleet/pipeline/pinky-tasks", json={"action": "depart_s3", "robot_id": "rosy_46"})
    assert early.status_code == 409 and early.json()["detail"]["code"] == "DEPART_NOT_PERMITTED"
    assert "COUNT_MISMATCH" in early.json()["detail"]["reasons"]
    read = client.get("/api/fleet/pipeline/unload-release", params={"robot_id": "rosy_46"}).json()
    assert read["ready"] is False and read["expected"] == 3

    now = time.time()
    for i, task in enumerate(by_index):  # what three verified completions leave behind
        task.update(status="COMPLETED", completed_at=now - 3 + i,
                    stage_result={"source_clearance": {"objects": 0 if i == 2 else 1}})
    app.state.omx_cell_states["cell_s"] = {"phase": "RELEASED", "amr_motion_inhibited": False}
    app.state.arm_live_states["arm_s"] = {"folded": True, "updated_at": now}
    go = client.post("/api/fleet/pipeline/pinky-tasks", json={"action": "depart_s3", "robot_id": "rosy_46"})
    assert go.status_code == 200 and go.json()["pinky_task"]["target_place"] == "S3_DEPART"
    again = client.post("/api/fleet/pipeline/pinky-tasks", json={"action": "depart_s3", "robot_id": "rosy_46"})
    assert again.status_code == 409 and "RELEASE_ALREADY_USED" in again.json()["detail"]["reasons"]
