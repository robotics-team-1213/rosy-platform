"""D-1059: a QUEUED pinky task drives once as a Fleet trip, refuses with a reason, and cancels through the trip."""
import asyncio
import sqlite3
import time
from types import SimpleNamespace

import pytest

from fleet.server.sitemap import pipeline_pinky_dispatch as pd

GRAPH = SimpleNamespace(places={"S3": object(), "S5": object(), "S1": object()})
ACTIVE = (7, None, GRAPH, None)


class TripErr(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class Runner:
    def __init__(self, refuse=None):
        self.trips, self.starts, self.cancels, self.refuse = {}, [], [], refuse
        self.lease = SimpleNamespace(required=True)

    def view(self, trip_id):
        return self.trips.get(trip_id)

    def robot_busy(self, robot_id):
        return any(t["robot_id"] == robot_id and t["state"] in pd.TRIP_OPEN for t in self.trips.values())

    async def start(self, plan_id, principal_id):
        if self.refuse:
            raise TripErr(self.refuse)
        self.starts.append((plan_id, principal_id))
        self.trips[plan_id] = {"trip_id": plan_id, "robot_id": "rosy_46", "state": "started", "lease": {"lease_id": "L"}}
        return self.trips[plan_id]

    async def cancel(self, trip_id, principal_id, reason=None):
        self.cancels.append((trip_id, reason))
        self.trips[trip_id].update(state="canceled", reason=reason)
        return self.trips[trip_id]


class Store:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.db = sqlite3.connect(":memory:")
        self.db.execute("CREATE TABLE fleet_cancel_all (cancel_all_id TEXT, opened_at TEXT)")

    def dispatch_control(self):
        return {"dispatch_enabled": self.enabled}

    def _connect(self):
        store = self

        class Conn:  # closing() must not close the shared in-memory db
            def execute(self, *a):
                return store.db.execute(*a)

            def close(self):
                pass
        return Conn()


class Console:
    def __init__(self, online=True, estop=False):
        self.row = {"robot_id": "rosy_46", "online": online, "state": {"safety": {"estop": estop}}}

    async def snapshot(self):
        return {"robots": [self.row]}


def _task(**kw):
    row = {"task_id": "p1", "robot_id": "rosy_46", "action": "dock_s3", "status": "QUEUED", "place_id": "S3",
           "map_version": 7, "requested_by": "op-kim", "requester_named": True, "created_at": time.time()}
    return {**row, **kw}


def _state(*tasks, cell=None, held=False):
    return SimpleNamespace(pinky_tasks={t["task_id"]: t for t in tasks}, omx_cell_tasks={},
                           omx_cell_states={"cell_s": cell or {"phase": "RELEASED"}},
                           arm_holds={"arm_s": {"held": held}})


class World:
    def __init__(self, state, *, runner=None, console=None, store=None, human=False, active=ACTIVE):
        self.state, self.runner = state, runner or Runner()
        self.console, self.store = console or Console(), store or Store()
        self.human, self.active, self.plans, self.saves = human, active, [], []

    async def plan(self, robot_id, request, principal_id):
        self.plans.append((robot_id, request, principal_id))
        plan_id = f"plan-{len(self.plans)}"
        return {"plan_id": plan_id}

    def tick(self):
        return asyncio.run(pd.dispatch_tick(
            self.state, console=self.console, runner=self.runner, plan=self.plan,
            task_service=SimpleNamespace(store=self.store), active=self.active, human_detected=self.human,
            save=lambda: self.saves.append(dict(self.state.pinky_tasks["p1"])), now=time.time(),
            trip_request=lambda place: place))


@pytest.fixture(autouse=True)
def flag_on(monkeypatch):
    monkeypatch.setenv(pd.FLAG, "1")


def test_flag_off_leaves_the_task_queued_and_moves_nothing(monkeypatch):
    monkeypatch.delenv(pd.FLAG)
    world = World(_state(_task()))
    assert world.tick() == [] and world.plans == [] and world.runner.starts == []
    assert world.state.pinky_tasks["p1"]["status"] == "QUEUED"


def test_queued_task_is_one_trip_to_its_place_and_sending_is_on_disk_first():
    world = World(_state(_task()))
    assert len(world.tick()) == 1
    assert world.plans == [("rosy_46", "S3", "op-kim")] and world.runner.starts == [("plan-1", "op-kim")]
    assert world.saves[0]["status"] == "SENDING" and world.saves[0]["plan_id"] is None
    assert world.saves[1]["plan_id"] == "plan-1"  # the plan id is saved before the start
    task = world.state.pinky_tasks["p1"]
    assert task["status"] == "SENT" and task["trip_id"] == "plan-1" and task["receipt"]["lease"] == "L"
    world.tick()
    world.tick()  # double tick: no second plan or start
    assert len(world.plans) == 1 and len(world.runner.starts) == 1


def test_arrived_comes_only_from_the_trip_state():
    world = World(_state(_task()))
    world.tick()
    world.tick()
    assert world.state.pinky_tasks["p1"]["status"] == "SENT"
    world.runner.trips["plan-1"]["state"] = "arrived"
    world.tick()
    assert world.state.pinky_tasks["p1"]["status"] == "ARRIVED"


def test_failed_or_canceled_trip_ends_the_task_with_its_reason():
    world = World(_state(_task()))
    world.tick()
    world.runner.trips["plan-1"].update(state="failed", reason="TRIP_POSE_LOST")
    world.tick()
    assert world.state.pinky_tasks["p1"]["status"] == "FAILED"
    assert world.state.pinky_tasks["p1"]["reason"] == "TRIP_POSE_LOST"


def test_restart_with_a_stored_plan_id_never_plans_or_starts_again():
    runner = Runner()
    runner.trips["plan-9"] = {"trip_id": "plan-9", "robot_id": "rosy_46", "state": "running"}
    world = World(_state(_task(status="SENDING", plan_id="plan-9", trip_id=None)), runner=runner)
    world.tick()
    task = world.state.pinky_tasks["p1"]
    assert task["status"] == "SENT" and task["trip_id"] == "plan-9" and world.plans == [] and runner.starts == []


def test_restart_without_a_started_trip_fails_instead_of_resending():
    world = World(_state(_task(status="SENDING", plan_id=None, trip_id=None)))
    world.tick()
    assert world.state.pinky_tasks["p1"]["status"] == "FAILED"
    assert world.state.pinky_tasks["p1"]["reason"] == "DISPATCH_INTERRUPTED" and world.plans == []


def test_trip_path_refusal_is_recorded_and_nothing_started():
    world = World(_state(_task()), runner=Runner(refuse="TRIP_POSE_UNTRUSTED"))
    world.tick()
    assert world.state.pinky_tasks["p1"]["status"] == "FAILED"
    assert world.state.pinky_tasks["p1"]["reason"] == "TRIP_POSE_UNTRUSTED"


@pytest.mark.parametrize("why, kw", [
    ("ACTION_NOT_DISPATCHABLE", dict(task=dict(place_id=None, action="micro_forward_2cm"))),
    ("REQUESTER_UNKNOWN", dict(task=dict(requested_by=None))),
    ("REQUESTER_NOT_NAMED", dict(task=dict(requester_named=False))),
    ("REQUESTER_NOT_NAMED", dict(task=dict(requester_named=None))),  # an old row without the field
    ("REQUEST_STALE", dict(task=dict(created_at=time.time() - 600))),
    ("MAP_VERSION_CHANGED", dict(task=dict(map_version=6))),
    ("MAP_VERSION_CHANGED", dict(task=dict(map_version=None))),
    ("PLACE_NOT_ON_MAP", dict(task=dict(place_id="S9"))),
    ("NO_ACTIVE_MAP", dict(world=dict(active=None))),
    ("ROBOT_UNKNOWN", dict(task=dict(robot_id="rosy_99"))),
    ("ROBOT_OFFLINE", dict(world=dict(console=Console(online=False)))),
    ("ROBOT_ESTOP", dict(world=dict(console=Console(estop=True)))),
    ("DISPATCH_CLOSED", dict(world=dict(store=Store(enabled=False)))),
    ("HUMAN_HOLD", dict(world=dict(human=True))),
    ("HUMAN_HOLD", dict(state=dict(cell={"phase": "HUMAN_HOLD"}))),
    ("CELL_HOLD", dict(state=dict(cell={"phase": "ABORTED"}))),
    ("CELL_HOLD", dict(state=dict(held=True))),
    ("CELL_BUSY", dict(state=dict(cell={"phase": "RELEASED", "amr_motion_inhibited": True}))),
    ("CELL_BUSY", dict(state=dict(cell={"phase": "ARM_IN_BED_ZONE"}))),
    ("CELL_BUSY", dict(state=dict(cell={"phase": "RELEASED", "docked_robot": {"robot_id": "rosy_45"}}))),
])
def test_each_refusal_records_its_reason_and_moves_nothing(why, kw):
    world = World(_state(_task(**kw.get("task", {})), **kw.get("state", {})), **kw.get("world", {}))
    world.tick()
    task = world.state.pinky_tasks["p1"]
    assert (task["status"], task["reason"]) == ("REFUSED", why)
    assert world.plans == [] and world.runner.starts == []


def test_a_cancel_all_after_the_request_refuses_it():
    store = Store()
    store.db.execute("INSERT INTO fleet_cancel_all VALUES ('c', ?)", (pd._iso(time.time() + 1),))
    world = World(_state(_task()), store=store)
    world.tick()
    assert world.state.pinky_tasks["p1"]["reason"] == "CANCEL_ALL_AFTER_REQUEST" and world.plans == []


def test_another_dispatch_for_the_robot_in_flight_refuses():
    other = _task(task_id="p0", status="SENT", plan_id="plan-0", trip_id="plan-0")
    runner = Runner()
    runner.trips["plan-0"] = {"trip_id": "plan-0", "robot_id": "rosy_46", "state": "running"}
    world = World(_state(_task(), other), runner=runner)
    world.tick()
    assert world.state.pinky_tasks["p1"]["reason"] == "ROBOT_DISPATCH_IN_FLIGHT" and runner.starts == []


def test_an_auto_depart_row_is_not_ours_and_blocks_nothing():
    depart = {"task_id": "depart-u", "robot_id": "rosy_46", "status": "SENT", "auto": True, "created_at": 0}
    world = World(_state(_task(), depart))
    world.tick()
    assert depart["status"] == "SENT" and world.state.pinky_tasks["p1"]["status"] == "SENT"


def test_no_trip_lease_or_journal_refuses():
    runner = Runner()
    runner.lease.required = False
    world = World(_state(_task()), runner=runner)
    world.tick()
    assert world.state.pinky_tasks["p1"]["reason"] == "TRIP_PATH_UNAVAILABLE" and world.plans == []


def test_cancel_queued_ends_it_and_cancel_sent_cancels_the_trip():
    state = _state(_task())
    asyncio.run(pd.cancel_task(state, state.pinky_tasks["p1"], runner=Runner(), principal_id="op", now=time.time()))
    assert state.pinky_tasks["p1"]["status"] == "CANCELLED"
    world = World(_state(_task()))
    world.tick()
    task = world.state.pinky_tasks["p1"]
    asyncio.run(pd.cancel_task(world.state, task, runner=world.runner, principal_id="op", now=time.time()))
    assert world.runner.cancels == [("plan-1", "pinky_task_cancel")] and task["status"] == "CANCELLED"
    world.tick()
    assert task["status"] == "CANCELLED" and len(world.runner.starts) == 1


def test_cancel_during_the_start_cancels_the_trip_it_opened():
    world = World(_state(_task()))
    start = world.runner.start

    async def start_then_cancel(plan_id, principal_id):
        trip = await start(plan_id, principal_id)
        await pd.cancel_task(world.state, world.state.pinky_tasks["p1"], runner=world.runner, principal_id="op",
                             now=time.time())
        return trip
    world.runner.start = start_then_cancel
    world.tick()
    assert world.runner.trips["plan-1"]["state"] == "canceled"
    assert world.state.pinky_tasks["p1"]["status"] == "CANCELLED"


def test_route_rows_carry_place_map_and_cancel(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from tools.sim.bay_departure_sim import build_world_261026_site_map
    from fleet.server.sitemap import pipeline_routes as routes

    site, graph, _ = build_world_261026_site_map()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(routes, "_storage_dir", lambda: tmp_path)
    app = FastAPI()
    routes.install_pipeline_routes(app, site_maps=SimpleNamespace(active=lambda: (3, site, graph, None)))
    client = TestClient(app)
    row = client.post("/api/fleet/pipeline/pinky-tasks", json={"action": "dock_s3", "robot_id": "rosy_46"}).json()
    task = row["pinky_task"]
    assert (task["place_id"], task["map_version"], task["status"]) == ("S3", 3, "QUEUED")
    micro = client.post("/api/fleet/pipeline/pinky-tasks", json={"action": "micro_forward_2cm"}).json()
    assert micro["pinky_task"]["place_id"] is None
    done = client.post(f"/api/fleet/pipeline/pinky-tasks/{task['task_id']}/cancel")
    assert done.status_code == 200 and done.json()["pinky_task"]["status"] == "CANCELLED"
    assert client.post(f"/api/fleet/pipeline/pinky-tasks/{task['task_id']}/cancel").status_code == 409


def _guarded_app(tmp_path, monkeypatch, principal, *, named_config=True):
    """A pipeline app whose rows see the real site_auth guards and a fixed principal."""
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from tools.sim.bay_departure_sim import build_world_261026_site_map
    from fleet.server.site_auth import build_role_guards
    from fleet.server.sitemap import pipeline_routes as routes

    site, graph, _ = build_world_261026_site_map()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(routes, "_storage_dir", lambda: tmp_path)
    app = FastAPI()

    @app.middleware("http")
    async def as_principal(request: Request, call_next):
        request.state.site_principal = principal
        return await call_next(request)

    principals = {"h": principal} if named_config else {}
    _viewer, operator, named, _proposer = build_role_guards(lambda: principal, principals)
    app.state.trip_requester_guards = (operator, named)
    routes.install_pipeline_routes(app, site_maps=SimpleNamespace(active=lambda: (7, site, graph, None)))
    return app, TestClient(app)


@pytest.mark.parametrize("role, named_config, named", [
    ("operator", True, True),     # a configured named operator credential: the trip routes admit it
    ("operator", False, False),   # operator, but the site has no named operator identity
    ("service", True, False),     # a service principal is not an operator for the trip routes
])
def test_requester_named_follows_the_trip_route_guards(tmp_path, monkeypatch, role, named_config, named):
    from fleet.server.site_auth import SitePrincipal

    app, client = _guarded_app(tmp_path, monkeypatch, SitePrincipal("op-kim", role), named_config=named_config)
    row = client.post("/api/fleet/pipeline/pinky-tasks", json={"action": "dock_s3", "robot_id": "rosy_46"})
    task = row.json()["pinky_task"]
    assert task["requester_named"] is named and task["requested_by"] == "op-kim"
    task.update(task_id="p1", created_at=time.time())
    world = World(SimpleNamespace(pinky_tasks={"p1": task}, omx_cell_tasks={},
                                  omx_cell_states={"cell_s": {"phase": "RELEASED"}}, arm_holds={}))
    world.tick()
    if named:
        assert task["status"] == "SENT" and world.runner.starts == [("plan-1", "op-kim")]
    else:
        assert (task["status"], task["reason"]) == ("REFUSED", "REQUESTER_NOT_NAMED") and world.plans == []
