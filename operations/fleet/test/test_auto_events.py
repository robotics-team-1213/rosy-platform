"""What the cell S automation did by itself, success or not, lands in one Fleet list (2026-11-19)."""
import asyncio
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet.server.sitemap import pipeline_auto_events as ae
from fleet.server.sitemap import pipeline_unload_release as ur

NOW = time.time()


def test_clean_rejects_what_is_not_an_event():
    assert ae.clean({"kind": "mystery", "t": NOW}) is None  # unknown kind
    assert ae.clean({"kind": "auto_fold"}) is None  # no t
    assert ae.clean({"kind": "auto_fold", "t": "now"}) is None  # t is not a number
    assert ae.clean({"kind": "auto_fold", "t": float("nan")}) is None


def test_clean_bounds_what_it_keeps():
    row = ae.clean({"kind": "auto_fold", "arm": "arm_s", "t": 5, "why": "w" * 500,
                    "candidate": float("inf"), "shaped": ["not", "flat"]})
    assert row["t"] == 5.0  # an int t is kept as a float
    assert len(row["why"]) == ae.TEXT_MAX
    assert "candidate" not in row and "shaped" not in row  # non-finite numbers and unknown shapes are dropped


def test_only_a_failure_that_needs_a_person_is_flagged():
    needs_person = (
        {"kind": "auto_clear", "result": False, "t": NOW},
        {"kind": "auto_fold", "result": "held", "t": NOW},
        {"kind": "auto_fold", "result": "not_cleared", "t": NOW},
        {"kind": "auto_fold", "result": "failed", "t": NOW},
        {"kind": "auto_depart", "result": "HELD", "t": NOW},
    )
    assert all(ae.clean(row)["person_needed"] is True for row in needs_person)
    fine = ({"kind": "auto_clear", "result": True, "t": NOW},
            {"kind": "auto_fold", "result": "cleared", "t": NOW},
            {"kind": "auto_depart", "result": "SENT", "t": NOW})
    assert all(ae.clean(row)["person_needed"] is False for row in fine)


def test_add_counts_only_new_rows_and_merges_duplicates():
    state = SimpleNamespace()
    rows = [{"kind": "auto_clear", "arm": "arm_s", "incident_id": "inc-1", "result": True, "t": 1.0},
            {"kind": "auto_fold", "arm": "arm_s", "incident_id": "inc-2", "result": "failed", "t": 2.0}]
    assert ae.add(state, rows, "cell") == 2
    assert state.cell_auto_events[0]["source"] == "cell"
    assert ae.add(state, rows, "cell") == 0  # the same kind/arm/incident/t again adds nothing
    assert ae.add(state, [{**rows[0], "t": 3.0}, {"kind": "mystery", "t": 4.0}], "cell") == 1
    assert ae.add(state, "not-a-list", "cell") == 0
    assert [e["t"] for e in state.cell_auto_events] == [1.0, 2.0, 3.0]


def test_add_keeps_only_the_newest_max_events():
    state = SimpleNamespace()
    ae.add(state, [{"kind": "auto_depart", "robot_id": "rosy_46", "batch_id": "b", "result": "SENT", "t": float(i)}
                   for i in range(ae.MAX_EVENTS + 5)], "fleet")
    events = state.cell_auto_events
    assert len(events) == ae.MAX_EVENTS  # the oldest five are dropped
    assert events[0]["t"] == 5.0 and events[-1]["t"] == float(ae.MAX_EVENTS + 4)


def _task(i, status="COMPLETED", objects=0, expected=None, done_at=None):
    now = time.time()
    return {"task_id": f"u-{i + 1}", "robot_id": "rosy_46", "unload_batch_id": "u", "unload_expected": expected,
            "unload_index": i, "status": status, "created_at": now - 100 + i,
            "completed_at": done_at if done_at is not None else now - 5 + i,
            "stage_result": {"source_clearance": {"objects": objects}}}


def _state(tasks, folded=True, age=2.0, phase="RELEASED", held=False):
    last = max(tasks, key=lambda t: t.get("completed_at", 0), default={})
    return SimpleNamespace(
        omx_cell_tasks={t["task_id"]: t for t in tasks},
        omx_cell_states={"cell_s": {"phase": phase, "amr_motion_inhibited": False, "robot_id": last.get("robot_id"),
                                    "stage_id": last.get("task_id"), "unload_batch_id": last.get("unload_batch_id")}},
        arm_live_states={"arm_s": {"folded": folded, "updated_at": time.time() - age}},
        arm_holds={"arm_s": {"held": held}}, unload_releases={}, pinky_tasks={})


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

    async def cancel(self, robot_id):
        return {"canceled": True}


def tick(state, console, rules=RULES, human=False):
    asyncio.run(ur.depart_tick(state, console=console, rules=rules, site=SITE,
                               enqueue=lambda spec: {"task_id": spec["task_id"]}, human_detected=human,
                               save=lambda: None, now=time.time()))


def departs(state):
    return [e for e in state.cell_auto_events if e["kind"] == "auto_depart"]


def test_no_exit_place_is_one_held_depart_event():
    state, console = _state([_task(0)]), Console()
    no_exit = SimpleNamespace(return_=SimpleNamespace(exit_place=None))
    tick(state, console, rules=no_exit)
    tick(state, console, rules=no_exit)
    event, = departs(state)
    assert (event["result"], event["why"], event["batch_id"]) == ("HELD", "NO_EXIT_PLACE", "u")
    assert event["person_needed"] is True and event["source"] == "fleet"


def test_a_sent_departure_is_recorded_without_a_person():
    state, console = _state([_task(0)]), Console()
    tick(state, console)
    tick(state, console)
    event, = departs(state)
    assert (event["result"], event["why"]) == ("SENT", "S1") and event["person_needed"] is False


def test_three_failed_sends_end_in_one_held_depart_event():
    state, console = _state([_task(0)]), Console(fail=5)
    for _ in range(6):
        tick(state, console)
    event, = departs(state)
    assert (event["result"], event["why"]) == ("HELD", "DEPART_SEND_FAILED")
    assert event["person_needed"] is True and len(console.goals) == ur.MAX_SEND_ATTEMPTS


def _client(tmp_path, monkeypatch):
    from tools.sim.bay_departure_sim import build_world_261026_site_map
    from fleet.server.sitemap import pipeline_routes as routes

    site, graph, _ = build_world_261026_site_map()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(routes, "_storage_dir", lambda: tmp_path)
    app = FastAPI()
    routes.install_pipeline_routes(app, site_maps=SimpleNamespace(active=lambda: (1, site, graph, None)))
    return app, TestClient(app)


def test_cell_quality_events_land_in_the_cell_tasks_answer(tmp_path, monkeypatch):
    _app, client = _client(tmp_path, monkeypatch)
    now = time.time()
    posted = client.post("/api/fleet/pipeline/cell-quality", json={"auto_events": [
        {"kind": "auto_clear", "arm": "arm_s", "incident_id": "inc-ok", "result": True, "t": now},
        {"kind": "auto_fold", "arm": "arm_s", "incident_id": "inc-bad", "result": "failed", "t": now},
        {"kind": "mystery", "arm": "arm_s", "t": now},
    ]})
    assert posted.status_code == 200 and posted.json()["ok"] is True
    listed = client.get("/api/fleet/pipeline/cell-tasks").json()["auto_events"]
    by_kind = {e["kind"]: e for e in listed}
    assert set(by_kind) == {"auto_clear", "auto_fold"}  # the garbage row never lands
    assert by_kind["auto_clear"]["person_needed"] is False and by_kind["auto_clear"]["source"] == "cell"
    assert by_kind["auto_fold"]["person_needed"] is True  # the failure row is the one a person must see
