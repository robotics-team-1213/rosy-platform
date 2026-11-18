"""A docked Pinky leaves by itself only when the ledger, the cell's camera and the measured fold agree (2026-11-19)."""
import asyncio
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet.server.sitemap import pipeline_unload_release as ur


def _task(i, status="COMPLETED", objects=0, expected=None, done_at=None):
    now = time.time()
    return {"task_id": f"u-{i + 1}", "robot_id": "rosy_46", "unload_batch_id": "u", "unload_expected": expected,
            "unload_index": i, "status": status, "created_at": now - 100 + i,
            "completed_at": done_at if done_at is not None else now - 5 + i,
            "stage_result": {"source_clearance": {"objects": objects}}}


def _state(tasks, folded=True, age=2.0, phase="RELEASED", held=False):
    return SimpleNamespace(
        omx_cell_tasks={t["task_id"]: t for t in tasks},
        omx_cell_states={"cell_s": {"phase": phase, "amr_motion_inhibited": False}},
        arm_live_states={"arm_s": {"folded": folded, "updated_at": time.time() - age}},
        arm_holds={"arm_s": {"held": held}}, unload_releases={}, pinky_tasks={})


def reasons(state, **kw):
    return ur.unload_release(state, "rosy_46", now=time.time(), human_detected=False, **kw)["reasons"]


def test_camera_zero_after_the_last_carry_is_ready_without_any_count():
    assert reasons(_state([_task(0, objects=1), _task(1, objects=0)])) == []


def test_each_disagreement_holds_the_vehicle():
    assert reasons(_state([_task(0, objects=1)])) == ["CARGO_NOT_EMPTY"]
    assert reasons(_state([_task(0, objects=None)])) == ["BED_NOT_OBSERVED"]
    assert reasons(_state([_task(0, done_at=time.time() - 900)])) == ["BED_NOT_OBSERVED"]  # an old look is not this stop's
    assert reasons(_state([_task(0, objects=0, expected=2)])) == ["COUNT_MISMATCH"]  # Harbor said 2, camera saw 0 after 1
    assert reasons(_state([_task(0, objects=1), _task(1, status="RUNNING")])) == ["UNLOAD_IN_PROGRESS", "CARGO_NOT_EMPTY"]
    assert reasons(_state([_task(0)], folded=False)) == ["ARM_NOT_HOME"]
    assert reasons(_state([_task(0)], age=60.0), fold_max_age_s=ur.DEPART_FOLD_AGE_S) == ["ARM_NOT_HOME"]
    assert reasons(_state([_task(0)], phase="ARM_IN_BED_ZONE")) == ["CELL_NOT_RELEASED"]
    assert reasons(_state([_task(0)], held=True)) == ["ARM_HELD"]
    assert "UNLOAD_ABORTED" in reasons(_state([_task(0, status="ABORTED")]))
    state = _state([_task(0)])
    assert ur.unload_release(state, "rosy_46", now=time.time(), human_detected=True)["reasons"] == ["HUMAN_HOLD"]


def test_camera_still_seeing_a_box_adds_the_next_carry_up_to_the_cap():
    state = _state([_task(0, objects=2)])
    made = []
    enqueue = lambda spec: made.append(spec) or {"task_id": spec["task_id"]}
    assert ur.continue_unload(state, enqueue) == ["u-2"]
    assert made[0]["depends_on"] == "u-1" and made[0]["unload_batch_id"] == "u" and made[0]["unload_index"] == 1
    assert ur.continue_unload(_state([_task(0, objects=0)]), enqueue) == []  # empty: nothing more to carry
    full = _state([_task(i, objects=1) for i in range(ur.MAX_CONTAINERS)])
    assert ur.continue_unload(full, enqueue) == [] and "CARGO_NOT_EMPTY" in reasons(full)  # cap reached: held, not looped


class Place(SimpleNamespace):
    pass


SITE = SimpleNamespace(places=[Place(id="S1", x=3.0, y=0.5, yaw=1.57)])
RULES = SimpleNamespace(return_=SimpleNamespace(exit_place="S1"))


class Console:
    def __init__(self, fail=0):
        self.goals, self.fail = [], fail

    async def goal(self, robot_id, x, y, yaw=0.0, **kw):
        self.goals.append((robot_id, x, y, yaw))
        if self.fail:
            self.fail -= 1
            raise RuntimeError("robot offline")
        return {"accepted": True}


def tick(state, console, rules=RULES, human=False):
    saves = []
    sent = asyncio.run(ur.depart_tick(state, console=console, rules=rules, site=SITE,
                                      enqueue=lambda spec: {"task_id": spec["task_id"]}, human_detected=human,
                                      save=lambda: saves.append(1), now=time.time()))
    return sent, saves


def test_ready_on_two_ticks_sends_once_to_the_exit_and_records_before_it():
    state, console = _state([_task(0)]), Console()
    assert tick(state, console)[0] == [] and console.goals == []  # one sample is not enough
    sent, saves = tick(state, console)
    assert len(sent) == 1 and console.goals == [("rosy_46", 3.0, 0.5, 1.57)] and saves
    assert state.unload_releases["u"]["state"] == "SENT" and state.pinky_tasks["depart-u"]["auto"] is True
    tick(state, console)
    assert len(console.goals) == 1  # never twice for one batch


def test_no_exit_place_holds_instead_of_guessing():
    state, console = _state([_task(0)]), Console()
    no_exit = SimpleNamespace(return_=SimpleNamespace(exit_place=None))
    tick(state, console, rules=no_exit)
    tick(state, console, rules=no_exit)
    assert console.goals == [] and state.unload_releases["u"]["state"] == "HELD"
    assert state.unload_releases["u"]["reason"] == "NO_EXIT_PLACE"


def test_failed_sends_retry_then_hold():
    state, console = _state([_task(0)]), Console(fail=5)
    for _ in range(6):
        tick(state, console)
    assert len(console.goals) == ur.MAX_SEND_ATTEMPTS
    assert state.unload_releases["u"]["state"] == "HELD" and state.unload_releases["u"]["reason"] == "DEPART_SEND_FAILED"


def test_person_or_stale_fold_stops_the_automatic_send():
    state, console = _state([_task(0)]), Console()
    tick(state, console, human=True)
    tick(state, console, human=True)
    stale = _state([_task(0)], age=60.0)
    tick(stale, console)
    tick(stale, console)
    assert console.goals == []


def _client(tmp_path, monkeypatch):
    from tools.sim.bay_departure_sim import build_world_261026_site_map
    from fleet.server.sitemap import pipeline_routes as routes

    site, graph, _ = build_world_261026_site_map()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(routes, "_storage_dir", lambda: tmp_path)
    app = FastAPI()
    routes.install_pipeline_routes(app, site_maps=SimpleNamespace(active=lambda: (1, site, graph, None)))
    return app, TestClient(app)


def test_dock_and_unload_needs_no_count_and_an_operator_depart_is_gated(tmp_path, monkeypatch):
    app, client = _client(tmp_path, monkeypatch)
    made = client.post("/api/fleet/pipeline/pinky-tasks", json={"action": "dock_and_unload_s3", "robot_id": "rosy_46"})
    assert made.status_code == 200
    batch = [t for t in app.state.omx_cell_tasks.values() if t.get("unload_batch_id")]
    assert len(batch) == 1 and batch[0]["unload_expected"] is None
    bad = client.post("/api/fleet/pipeline/pinky-tasks", json={
        "action": "dock_and_unload_s3", "robot_id": "rosy_46", "cargo_manifest": []})
    assert bad.status_code == 422
    early = client.post("/api/fleet/pipeline/pinky-tasks", json={"action": "depart_s3", "robot_id": "rosy_46"})
    assert early.status_code == 409 and "UNLOAD_IN_PROGRESS" in early.json()["detail"]["reasons"]
    now = time.time()
    batch[0].update(status="COMPLETED", completed_at=now, stage_result={"source_clearance": {"objects": 0}})
    app.state.omx_cell_states["cell_s"] = {"phase": "RELEASED", "amr_motion_inhibited": False}
    app.state.arm_live_states["arm_s"] = {"folded": True, "updated_at": now}
    read = client.get("/api/fleet/pipeline/unload-release", params={"robot_id": "rosy_46"}).json()
    assert read["ready"] is True and read["departure"] is None
    go = client.post("/api/fleet/pipeline/pinky-tasks", json={"action": "depart_s3", "robot_id": "rosy_46"})
    assert go.status_code == 200
    again = client.post("/api/fleet/pipeline/pinky-tasks", json={"action": "depart_s3", "robot_id": "rosy_46"})
    assert again.status_code == 409 and "RELEASE_ALREADY_USED" in again.json()["detail"]["reasons"]
    console = Console()
    asyncio.run(ur.depart_tick(app.state, console=console, rules=RULES, site=SITE, enqueue=lambda s: s,
                               human_detected=False, save=lambda: None, now=time.time()))
    assert console.goals == []  # an operator's departure is not sent again by the loop
