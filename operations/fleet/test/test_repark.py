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
    assert ok.status_code == 200, ok.text
    assert "c-1-rp1" in app.state.omx_cell_tasks
    assert client.post(path, json={"state": "DONE"}).status_code == 409


def test_done_clears_aborted_cell_only_when_safe_and_freshly_folded():
    task = _task(unload_batch_id="u-1", unload_index=1)
    for blocked_key, override in (
        ("unfolded", {"arm_live_states": {"arm_s": {"folded": False, "updated_at": NOW, "folded_updated_at": NOW}}}),
        ("missing_fold_ts", {"arm_live_states": {"arm_s": {"folded": True, "updated_at": NOW}}}),
        ("stale", {"arm_live_states": {"arm_s": {"folded": True, "updated_at": NOW, "folded_updated_at": NOW - 300.0}}}),
        ("nan", {"arm_live_states": {"arm_s": {"folded": True, "updated_at": NOW, "folded_updated_at": float("nan")}}}),
        ("future", {"arm_live_states": {"arm_s": {"folded": True, "updated_at": NOW, "folded_updated_at": NOW + 60.0}}}),
        ("held", {"arm_holds": {"arm_s": {"held": True}}}),
        ("human", {"human_detected": {"cell_s": True}}),
    ):
        st = SimpleNamespace(
            omx_cell_tasks={"c-1": dict(task)},
            omx_cell_states={"cell_s": {"phase": "ABORTED", "amr_motion_inhibited": True}},
            arm_live_states={"arm_s": {"folded": True, "updated_at": NOW, "folded_updated_at": NOW}},
            arm_holds={"arm_s": {"held": False}},
            human_detected={"cell_s": False},
        )
        for k, v in override.items():
            setattr(st, k, v)
        req = rp.on_abort(st, st.omx_cell_tasks["c-1"], {"reach_fix": FIX}, NOW)
        rp.close(st, req["request_id"], {"state": "DONE"}, _enqueue(st), NOW)
        assert st.omx_cell_states["cell_s"]["phase"] == "ABORTED", blocked_key

    # Sibling arm hold or unfolded sibling arm in cell_ab must also keep cell_ab ABORTED.
    st_ab = SimpleNamespace(
        omx_cell_tasks={"c-ab": {**dict(task), "task_id": "c-ab", "cell_id": "cell_ab", "arm_id": "arm_a"}},
        omx_cell_states={"cell_ab": {"phase": "ABORTED", "amr_motion_inhibited": True}},
        arm_live_states={
            "arm_a": {"folded": True, "updated_at": NOW, "folded_updated_at": NOW},
            "arm_b": {"folded": True, "updated_at": NOW, "folded_updated_at": NOW},
        },
        arm_holds={"arm_a": {"held": False}, "arm_b": {"held": True}},
        human_detected={"cell_ab": False},
    )
    req_ab = rp.on_abort(st_ab, st_ab.omx_cell_tasks["c-ab"], {"reach_fix": FIX}, NOW)
    rp.close(st_ab, req_ab["request_id"], {"state": "DONE"}, _enqueue(st_ab), NOW)
    assert st_ab.omx_cell_states["cell_ab"]["phase"] == "ABORTED"

    st_ab_unf = SimpleNamespace(
        omx_cell_tasks={"c-ab": {**dict(task), "task_id": "c-ab", "cell_id": "cell_ab", "arm_id": "arm_a"}},
        omx_cell_states={"cell_ab": {"phase": "ABORTED", "amr_motion_inhibited": True}},
        arm_live_states={
            "arm_a": {"folded": True, "updated_at": NOW, "folded_updated_at": NOW},
            "arm_b": {"folded": False, "updated_at": NOW, "folded_updated_at": NOW},
        },
        arm_holds={"arm_a": {"held": False}, "arm_b": {"held": False}},
        human_detected={"cell_ab": False},
    )
    req_ab_unf = rp.on_abort(st_ab_unf, st_ab_unf.omx_cell_tasks["c-ab"], {"reach_fix": FIX}, NOW)
    rp.close(st_ab_unf, req_ab_unf["request_id"], {"state": "DONE"}, _enqueue(st_ab_unf), NOW)
    assert st_ab_unf.omx_cell_states["cell_ab"]["phase"] == "ABORTED"

    safe_st = SimpleNamespace(
        omx_cell_tasks={"c-1": dict(task)},
        omx_cell_states={"cell_s": {"phase": "ABORTED", "prev_phase": "ABORTED", "amr_motion_inhibited": True}},
        arm_live_states={"arm_s": {"folded": True, "updated_at": NOW, "folded_updated_at": NOW}},
        arm_holds={"arm_s": {"held": False}},
        human_detected={"cell_s": False},
    )
    req_ok = rp.on_abort(safe_st, safe_st.omx_cell_tasks["c-1"], {"reach_fix": FIX}, NOW)
    rp.close(safe_st, req_ok["request_id"], {"state": "DONE"}, _enqueue(safe_st), NOW)
    assert safe_st.omx_cell_states["cell_s"]["phase"] == "CLAIMED"
    assert safe_st.omx_cell_states["cell_s"]["amr_motion_inhibited"] is False


def test_partial_cell_quality_cannot_manufacture_fresh_fold_for_repark(tmp_path, monkeypatch):
    from tools.sim.bay_departure_sim import build_world_261026_site_map
    from fleet.server.sitemap import pipeline_routes as routes

    site, graph, _ = build_world_261026_site_map()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(routes, "_storage_dir", lambda: tmp_path)
    app = FastAPI()
    routes.install_pipeline_routes(app, site_maps=SimpleNamespace(active=lambda: (1, site, graph, None)))
    client = TestClient(app)

    for payload in (
        {"arm_states": {"arm_s": {"folded": True, "updated_at": False}}},
        {"arm_states": {"arm_s": {"folded": True, "updated_at": None}}},
        {"arm_states": {"arm_s": {"folded": True, "updated_at": 10**309}}},
        {"arm_states": {"arm_s": {"folded": "false"}}},
    ):
        bad = client.post("/api/fleet/pipeline/cell-quality", json=payload)
        assert bad.status_code == 422 and bad.json()["detail"]["code"] == "INVALID_PIPELINE_NUMBER"

    # Partial update omitting "folded" must clear boot_default placeholder and never fake fresh fold evidence.
    client.post("/api/fleet/pipeline/cell-quality", json={"arm_states": {"arm_s": {"temp_c": 31.5}}})
    app.state.omx_cell_tasks["c-1"] = _task()
    app.state.omx_cell_states["cell_s"] = {"phase": "ABORTED", "amr_motion_inhibited": True}
    req = rp.on_abort(app.state, app.state.omx_cell_tasks["c-1"], {"reach_fix": FIX}, NOW)
    assert client.post(f"/api/fleet/pipeline/repark/{req['request_id']}", json={"state": "DONE"}).status_code == 200
    assert app.state.omx_cell_states["cell_s"]["phase"] == "ABORTED"
