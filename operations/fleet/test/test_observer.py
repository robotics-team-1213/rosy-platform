"""The vehicle queued behind the unload station looks at the unloading vehicle's stack; nothing moves (2026-11-19)."""
import asyncio
import math
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fleet.server.sitemap import pipeline_observer as ob

SITE = SimpleNamespace(places=[SimpleNamespace(id="S3", x=1.0, y=1.5, yaw=0.0),
                               SimpleNamespace(id="S2", x=1.0, y=2.0, yaw=0.0)], edges=[])
FACE = -math.pi / 2  # from S2 straight at the bay of a vehicle at S3 (heading +90 deg)
MAP = {"S3": "S2"}


def _row(rid, x, y, yaw=FACE):
    return {"robot_id": rid, "online": True, "state": {"pose": {"x": x, "y": y, "yaw": yaw}}}


class Console:
    async def goal(self, *a):
        raise AssertionError("the observer never moves a vehicle")

    def __init__(self, rows, client=None):
        self.rows, self.client = rows, client

    def clients(self):
        return {"obs": self.client} if self.client else {}

    async def snapshot(self):
        return {"robots": self.rows}


def _state():
    return SimpleNamespace(omx_cell_tasks={"t1": {"task_id": "t1", "robot_id": "docked", "arm_id": "arm_s"}},
                           observer_requests={}, arm_live_states={"arm_s": {"folded": True, "updated_at": 0.0}})


def _go(state, request, rows, now, judge=None, human=False, client=None):
    async def capture(_rid):
        return b"jpeg"

    async def default(_frame, _dist):
        return {"tiers": 2, "confidence": 0.9}

    return asyncio.run(ob.step(state, request, console=Console(rows, client), capture=capture, judge=judge or default,
                               now=now, site=SITE, human=human))


def _req(state, wait="S2", now=0.0):
    return ob.new_request(state, "t1", "S3", wait, now, unload_robot="docked")


def test_queued_robot_is_captured_judged_and_sets_the_hint():
    state = _state()
    request = _req(state)
    _go(state, request, [_row("docked", 1.0, 1.5, math.pi / 2), _row("obs", 1.02, 2.0), _row("far", 3, 3)], 1.0)
    assert request["state"] == "VERDICT" and request["verdict"] == 2 and request["observer_id"] == "obs"
    assert request["dist_m"] == 0.61 and request["turn"] is None
    assert state.omx_cell_tasks["t1"]["tier_hint"] == {"layers_below": 1, "source": "observer", "confidence": 0.9, "t": 1.0}
    assert [e["kind"] for e in state.cell_auto_events] == ["auto_observe"]


@pytest.mark.parametrize("rows,wait,why", [
    ([_row("docked", 1.0, 1.5, math.pi / 2), _row("far", 1.0, 2.3)], "S2", "NO_QUEUED_OBSERVER"),  # nobody at the wait place
    ([_row("docked", 1.0, 1.5), _row("obs", 1.0, 2.0)], None, "NO_OBSERVE_PLACE"),  # no mapping
])
def test_skips(rows, wait, why):
    state = _state()
    request = _req(state, wait)
    _go(state, request, rows, 1.0)
    assert (request["state"], request["why"]) == ("SKIPPED", why) and "tier_hint" not in state.omx_cell_tasks["t1"]


def test_observer_may_have_any_heading():
    assert ob.observer_for([_row("obs", 1.0, 2.0, 2.0)], SITE, "S3", "S2", "gone") == "obs"


def test_abstain_leaves_no_hint():
    state = _state()
    request = _req(state)

    async def abstain(_f, _d):
        return {"tiers": None, "confidence": None}

    _go(state, request, [_row("docked", 1.0, 1.5), _row("obs", 1.0, 2.0)], 1.0, judge=abstain)
    assert request["state"] == "VERDICT" and request["why"] == "ABSTAIN" and "tier_hint" not in state.omx_cell_tasks["t1"]


def test_timeout_and_human_hold_skip():
    state = _state()
    rows = [_row("docked", 1.0, 1.5), _row("obs", 1.0, 2.0)]
    slow, held = _req(state), _req(state, now=100.0)
    _go(state, slow, rows, 61.0)
    assert (slow["state"], slow["why"]) == ("SKIPPED", "TIMEOUT")
    _go(state, held, rows, 101.0, human=True)
    assert held["why"] == "HUMAN_HOLD"


def test_without_a_vision_judge_nothing_turns_or_captures():
    state = _state()
    request = _req(state)

    async def capture(_rid):
        raise AssertionError("no judge: no frame enters Fleet")

    asyncio.run(ob.step(state, request, console=Console([_row("docked", 1.0, 1.5), _row("obs", 1.0, 2.0)]),
                        capture=capture, judge=None, now=1.0, site=SITE))
    assert (request["state"], request["why"], request["turn"]) == ("SKIPPED", "NO_JUDGE", None)


def _client(tasks=True, human=False, rules=None):
    app = FastAPI()
    app.state.omx_cell_tasks = {"t1": {"task_id": "t1", "robot_id": "docked"}} if tasks else {}
    app.state.omx_cell_states = {"cell_s": {"phase": "HUMAN_HOLD" if human else "IDLE"}}
    if rules is None:
        app.state.observe_from = MAP
    ctx = SimpleNamespace(operator_guard=(), read_guard=(), console=None, _is_human_detected=lambda: False,
                          active_map=lambda: (1, SITE), _save_ledger=lambda: None, rules=lambda: rules)
    ob.install_observer_routes(app, ctx)
    return TestClient(app)


def test_routes_create_read_cancel_404_and_409():
    c = _client()
    row = c.post("/api/fleet/pipeline/observer-requests", json={"cell_task_id": "t1"}).json()["request"]
    assert row["unload_place"] == "S3" and row["wait_place"] == "S2" and row["state"] == "REQUESTED"
    url = f"/api/fleet/pipeline/observer-requests/{row['request_id']}"
    assert c.get(url).json()["request_id"] == row["request_id"]
    assert c.post(url + "/cancel").status_code == 200
    assert c.post(url + "/cancel").status_code == 200  # still REQUESTED: cancel only flags it
    assert c.get("/api/fleet/pipeline/observer-requests/nope").status_code == 404
    assert c.post("/api/fleet/pipeline/observer-requests/nope/cancel").status_code == 404
    assert _client(tasks=False).post("/api/fleet/pipeline/observer-requests", json={"cell_task_id": "t1"}).status_code == 404
    assert _client(human=True).post("/api/fleet/pipeline/observer-requests", json={"cell_task_id": "t1"}).status_code == 409


def test_mapping_comes_from_the_rules_first():
    c = _client(rules=SimpleNamespace(observe_from={"S4": "S3"}))
    row = c.post("/api/fleet/pipeline/observer-requests", json={"cell_task_id": "t1", "unload_place": "S4"}).json()["request"]
    assert row["wait_place"] == "S3"
    row = c.post("/api/fleet/pipeline/observer-requests", json={"cell_task_id": "t1"}).json()["request"]
    assert row["wait_place"] is None


def test_bay_point_from_the_edge_geometry_and_the_live_pose():
    site = SimpleNamespace(places=[SimpleNamespace(id="S3", x=0.745, y=-0.207, yaw=0.0)])
    edge = SimpleNamespace(to="S3", polyline=[(1.2, 0.0), (0.926, -0.2524), (0.745, -0.207)])
    x, y = ob.bay_point(site, "S3", edge)
    assert (round(x, 3), round(y, 3)) == (0.852, -0.234)
    assert ob.bay_point(site, "S3", None) is None
    assert ob.bay_point(site, "S3", edge, unload_pose=(1.0, 1.5, math.pi / 2)) == pytest.approx((1.0, 1.39))


class Core:
    """Fake robot CORE client: records the calls, answers the turn status from a script."""

    def __init__(self, statuses=("running", "done")):
        self.calls, self.statuses, self.n = [], list(statuses), 0

    async def _post(self, path, body):
        self.calls.append(("POST", body["delta_deg"], body["tol_deg"], body["operator_name"]))
        self.n = 0
        return {}

    async def rotate_to_status(self):
        s = self.statuses[min(self.n, len(self.statuses) - 1)]
        self.n += 1
        return {"state": s}

    async def rotate_to_stop(self):
        self.calls.append(("DELETE",))


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(ob, "ROTATE_POLL_S", 0.0)



def test_no_turn_within_25_degrees():
    state, core = _state(), Core()
    request = _req(state)
    _go(state, request, [_row("docked", 1.0, 1.5, math.pi / 2), _row("obs", 1.0, 2.0, FACE + 0.3)], 1.0, client=core)
    assert request["state"] == "VERDICT" and core.calls == []


def test_turn_capture_turn_back():
    state, core = _state(), Core()
    request = _req(state)
    _go(state, request, [_row("docked", 1.0, 1.5, math.pi / 2), _row("obs", 1.0, 2.0, 0.0)], 1.0, client=core)
    assert request["state"] == "VERDICT" and request["turn"] == "done" and request["turn_back"] == "done"
    first, back = (c for c in core.calls if c[0] == "POST")
    assert first[1] == -back[1] and first[2:] == (3.0, "fleet-observer") and request["delta_deg"] == first[1]
    assert f"delta={first[1]}" in state.cell_auto_events[-1]["why"] and "turn=done/done" in state.cell_auto_events[-1]["why"]


def test_bay_107_degrees_from_s5():
    me, bay = (0.0, 0.0, 0.0), (-0.073, 0.239)
    assert ob.look_delta_deg(me, bay) == pytest.approx(107.0, abs=0.5)


def test_capture_failure_still_turns_back():
    state, core = _state(), Core()
    request = _req(state)

    async def boom(_f, _d):
        raise RuntimeError("x")

    _go(state, request, [_row("docked", 1.0, 1.5, math.pi / 2), _row("obs", 1.0, 2.0, 0.0)], 1.0, judge=boom, client=core)
    assert request["why"].startswith("CAPTURE_FAILED") and request["turn_back"] == "done"
    assert len([c for c in core.calls if c[0] == "POST"]) == 2


def test_human_hold_mid_turn_stops_and_skips():
    state, core = _state(), Core(statuses=("running",))
    request = _req(state)
    asked = iter([False, False, True])
    _go(state, request, [_row("docked", 1.0, 1.5, math.pi / 2), _row("obs", 1.0, 2.0, 0.0)], 1.0,
        human=lambda: next(asked, True), client=core)
    assert (request["state"], request["why"]) == ("SKIPPED", "HUMAN_HOLD") and ("DELETE",) in core.calls
    assert len([c for c in core.calls if c[0] == "POST"]) == 1


@pytest.mark.parametrize("arm", [{"folded": False, "updated_at": 0.0}, {"folded": True, "updated_at": -100.0}, {}])
def test_arm_not_folded_or_stale_never_turns(arm):
    state, core = _state(), Core()
    state.arm_live_states["arm_s"] = arm
    request = _req(state)
    _go(state, request, [_row("docked", 1.0, 1.5, math.pi / 2), _row("obs", 1.0, 2.0, 0.0)], 1.0, client=core)
    assert (request["state"], request["why"]) == ("SKIPPED", "ARM_NOT_FOLDED") and core.calls == []


def test_rotate_timeout_turns_back_and_skips(monkeypatch):
    monkeypatch.setattr(ob, "ROTATE_TIMEOUT_S", 0.0)
    state, core = _state(), Core(statuses=("running",))
    request = _req(state)
    _go(state, request, [_row("docked", 1.0, 1.5, math.pi / 2), _row("obs", 1.0, 2.0, 0.0)], 1.0, client=core)
    assert (request["state"], request["why"]) == ("SKIPPED", "ROTATE_TIMEOUT") and request["turn_back"] == "ROTATE_TIMEOUT"
    assert len([c for c in core.calls if c[0] == "POST"]) == 2
