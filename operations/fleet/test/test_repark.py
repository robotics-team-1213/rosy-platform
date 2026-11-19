"""An arm that cannot reach the cargo asks the vehicle to re-park closer, then retries by itself (2026-11-19)."""
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet.server.sitemap import pipeline_auto_events as ae
from fleet.server.sitemap import pipeline_repark as rp

NOW = time.time()
FIX = {"object_arm_xy_m": [-0.0156, 0.2214], "reach_mm": 222, "limit_mm": 200, "need_arm_dxdy_m": [0.0037, -0.0519]}


def _task(task_id="c-1", **extra):
    return {"task_id": task_id, "robot_id": "rosy_46", "cell_id": "cell_s", "arm_id": "arm_s", "preset": "s3_shuttle",
            "src_site": "pinky", "dst_site": "belt", "tier": 1, "status": "ABORTED", **extra}


def _state(*tasks):
    return SimpleNamespace(omx_cell_tasks={t["task_id"]: t for t in tasks})


def _enqueue(state):
    def enqueue(spec):
        state.omx_cell_tasks[spec["task_id"]] = {**spec, "status": "QUEUED"}
        return state.omx_cell_tasks[spec["task_id"]]
    return enqueue


def test_abort_with_a_reach_fix_opens_one_request_and_an_event():
    task = _task()
    state = _state(task)
    assert rp.on_abort(state, task, {}, NOW) is None and not getattr(state, "repark_requests", {})
    req = rp.on_abort(state, task, {"reach_fix": FIX}, NOW)
    assert state.repark_requests["rosy_46"] is req
    assert (req["state"], req["attempt"], req["need_arm_dxdy_m"], req["need_site_dxdy_m"]) == ("REQUESTED", 1, [0.0037, -0.0519], None)
    event, = state.cell_auto_events
    assert (event["kind"], event["result"], event["source"]) == ("auto_repark", "requested", "fleet")


def test_the_site_move_is_rotated_only_by_a_configured_yaw():
    rules = SimpleNamespace(arm_to_site={"cell_s": {"yaw_deg": 90.0}})
    task = _task()
    req = rp.on_abort(_state(task), task, {"reach_fix": {**FIX, "need_arm_dxdy_m": [1.0, 0.0]}}, NOW, rules=rules)
    assert req["need_site_dxdy_m"] == [0.0, 1.0]
    assert rp.to_site([1.0, 0.0], rules, "cell_x") is None


def test_done_queues_the_same_carry_and_the_second_retry_reaches_the_limit():
    task = _task()
    state = _state(task)
    req = rp.on_abort(state, task, {"reach_fix": FIX}, NOW)
    out = rp.close(state, req["request_id"], {"state": "DONE", "moved_robot_dxdy_m": [0.0, 0.038]}, _enqueue(state), NOW)
    retry = state.omx_cell_tasks["c-1-rp1"]
    assert out["retry_task_id"] == "c-1-rp1" and retry["repark_root"] == "c-1"
    assert (retry["robot_id"], retry["preset"], retry["src_site"], retry["tier"]) == ("rosy_46", "s3_shuttle", "pinky", 1)
    with __import__("pytest").raises(ValueError):
        rp.close(state, req["request_id"], {"state": "DONE"}, _enqueue(state), NOW)
    again = {**retry, "task_id": "c-1-rp1", "status": "ABORTED"}
    req2 = rp.on_abort(state, again, {"reach_fix": FIX}, NOW + 1)
    assert req2["attempt"] == 2
    rp.close(state, req2["request_id"], {"state": "DONE"}, _enqueue(state), NOW + 2)
    last = state.omx_cell_tasks["c-1-rp1-rp2"]
    assert rp.on_abort(state, {**last, "status": "ABORTED"}, {"reach_fix": FIX}, NOW + 3) is None
    event = state.cell_auto_events[-1]
    assert (event["result"], event["why"], event["person_needed"]) == ("held", "REPARK_LIMIT", True)


def test_failed_needs_a_person_and_unknown_ids_raise():
    task = _task()
    state = _state(task)
    req = rp.on_abort(state, task, {"reach_fix": FIX}, NOW)
    rp.close(state, req["request_id"], {"state": "FAILED"}, _enqueue(state), NOW + 1)
    event = state.cell_auto_events[-1]
    assert (event["result"], event["person_needed"]) == ("failed", True) and "c-1-rp1" not in state.omx_cell_tasks
    assert ae.NEEDS_PERSON >= {("auto_repark", "held"), ("auto_repark", "failed")}
    with __import__("pytest").raises(KeyError):
        rp.close(state, "nope", {"state": "DONE"}, _enqueue(state), NOW)


def test_route_404_409_and_done_through_the_ledger(tmp_path, monkeypatch):
    from tools.sim.bay_departure_sim import build_world_261026_site_map
    from fleet.server.sitemap import pipeline_routes as routes

    site, graph, _ = build_world_261026_site_map()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(routes, "_storage_dir", lambda: tmp_path)
    app = FastAPI()
    routes.install_pipeline_routes(app, site_maps=SimpleNamespace(active=lambda: (1, site, graph, None)))
    client = TestClient(app)
    assert client.post("/api/fleet/pipeline/repark/nope", json={"state": "DONE"}).status_code == 404
    task = _task()
    app.state.omx_cell_tasks["c-1"] = task
    req = rp.on_abort(app.state, task, {"reach_fix": FIX}, NOW)
    assert client.get("/api/fleet/pipeline/cell-tasks").json()["repark_requests"]["rosy_46"]["request_id"] == req["request_id"]
    path = f"/api/fleet/pipeline/repark/{req['request_id']}"
    ok = client.post(path, json={"state": "DONE"})
    assert ok.status_code == 200 and "c-1-rp1" in app.state.omx_cell_tasks
    assert client.post(path, json={"state": "DONE"}).status_code == 409
