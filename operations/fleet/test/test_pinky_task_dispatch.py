"""D-1060: a QUEUED pinky task drives once as a Fleet trip, refuses with a reason, and cancels through the trip."""
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
        self.trips, self.starts, self.cancels, self.refuse, self.epoch, self.cancel_fails = {}, [], [], refuse, 0, 0
        self.lease = SimpleNamespace(required=True)

    def view(self, trip_id):
        return self.trips.get(trip_id)

    def robot_busy(self, robot_id):
        return any(t["robot_id"] == robot_id and t["state"] in pd.TRIP_OPEN for t in self.trips.values())

    def _start_token(self, robot_id):
        return (self.epoch, 0)

    async def start(self, plan_id, principal_id, start_token=None, start_guard=None):
        if self.refuse:
            raise TripErr(self.refuse)
        if start_token is not None and start_token != self._start_token("rosy_46"):
            raise TripErr("TRIP_START_CANCELED")
        if start_guard is not None:
            await start_guard()
        self.starts.append((plan_id, principal_id))
        self.trips[plan_id] = {"trip_id": plan_id, "robot_id": "rosy_46", "state": "started", "lease": {"lease_id": "L"}}
        return self.trips[plan_id]

    async def cancel(self, trip_id, principal_id, reason=None):
        self.cancels.append((trip_id, reason))
        if self.cancel_fails:
            self.cancel_fails -= 1
            raise TripErr("LINK_LOST")
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

    async def start_then_cancel(plan_id, principal_id, start_token=None, start_guard=None):
        trip = await start(plan_id, principal_id, start_token=start_token, start_guard=start_guard)
        await pd.cancel_task(world.state, world.state.pinky_tasks["p1"], runner=world.runner, principal_id="op",
                             now=time.time())
        return trip
    world.runner.start = start_then_cancel
    world.tick()
    assert world.runner.trips["plan-1"]["state"] == "canceled"
    assert world.state.pinky_tasks["p1"]["status"] == "CANCELLED"


def test_cancel_landing_while_the_tick_awaits_the_snapshot_never_starts_the_trip():
    world = World(_state(_task()))
    snapshot = world.console.snapshot

    async def snapshot_then_cancel():
        result = await snapshot()
        await pd.cancel_task(world.state, world.state.pinky_tasks["p1"], runner=world.runner, principal_id="op",
                             now=time.time())
        return result
    world.console.snapshot = snapshot_then_cancel
    world.tick()
    assert world.runner.starts == [] and world.plans == []
    assert world.state.pinky_tasks["p1"]["status"] == "CANCELLED"
    assert world.state.pinky_tasks["p1"]["reason"] == "OPERATOR_CANCEL"


def test_a_cancel_the_trip_did_not_confirm_keeps_the_row_in_flight_until_the_trip_ends():
    world = World(_state(_task()))
    world.tick()
    task = world.state.pinky_tasks["p1"]
    world.runner.cancel_fails = 2
    asyncio.run(pd.cancel_task(world.state, task, runner=world.runner, principal_id="op", now=time.time()))
    assert task["status"] == "SENT" and task["cancel_requested"] and task["cancel_receipt"] == {"error": "LINK_LOST"}
    assert world.runner.trips["plan-1"]["state"] == "started"
    world.tick()  # the tick asks again; this one fails too, the row stays
    assert task["status"] == "SENT" and len(world.runner.cancels) == 2
    world.tick()  # the third ask lands: the trip is canceled and the row settles from it
    assert world.runner.trips["plan-1"]["state"] == "canceled"
    assert task["status"] == "CANCELLED" and len(world.runner.starts) == 1


def test_a_cancel_when_the_trip_already_arrived_does_not_claim_it_was_cancelled():
    world = World(_state(_task()))
    world.tick()
    task = world.state.pinky_tasks["p1"]
    world.runner.trips["plan-1"]["state"] = "arrived"

    async def gone(trip_id, principal_id, reason=None):
        raise TripErr("TRIP_NOT_RUNNING")
    world.runner.cancel = gone
    asyncio.run(pd.cancel_task(world.state, task, runner=world.runner, principal_id="op", now=time.time()))
    assert task["status"] == "ARRIVED"


def test_a_cancel_all_while_planning_refuses_the_start():
    world = World(_state(_task()))
    plan = world.plan

    async def plan_then_cancel_all(*args):
        result = await plan(*args)
        world.runner.epoch += 1  # a cancel-all or E-stop moved the stop epoch during the plan
        return result
    world.plan = plan_then_cancel_all
    world.tick()
    task = world.state.pinky_tasks["p1"]
    assert world.runner.starts == [] and task["status"] == "FAILED" and task["reason"] == "TRIP_START_CANCELED"


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


def test_cancel_while_planning_stays_sending_unconfirmed_until_tick_ends_it():
    world = World(_state(_task()))
    plan = world.plan
    seen_during_plan = {}

    async def plan_then_cancel(*args):
        result = await plan(*args)
        cancelled = await pd.cancel_task(world.state, world.state.pinky_tasks["p1"], runner=world.runner,
                                         principal_id="op", now=time.time())
        seen_during_plan["status"] = cancelled["status"]
        seen_during_plan["confirmed"] = cancelled["status"] in pd.TERMINAL
        return result

    world.plan = plan_then_cancel
    world.tick()
    task = world.state.pinky_tasks["p1"]
    assert seen_during_plan == {"status": "SENDING", "confirmed": False}
    assert world.runner.starts == [] and (task["status"], task["reason"]) == ("CANCELLED", "OPERATOR_CANCEL")


def test_cancel_during_start_before_trip_opens_aborts_through_start_guard():
    world = World(_state(_task()))
    seen = {}

    async def start_aborted_by_cancel(plan_id, principal_id, start_token=None, start_guard=None):
        await asyncio.sleep(0)
        cancelled = await pd.cancel_task(world.state, world.state.pinky_tasks["p1"], runner=world.runner,
                                         principal_id="op", now=time.time())
        seen["status"] = cancelled["status"]
        if start_guard is not None:
            await start_guard()
        raise AssertionError("start_guard should have aborted before opening a trip")

    world.runner.start = start_aborted_by_cancel
    world.tick()
    task = world.state.pinky_tasks["p1"]
    assert seen["status"] == "SENDING"
    assert world.runner.starts == [] and (task["status"], task["reason"]) == ("CANCELLED", "OPERATOR_CANCEL")


@pytest.mark.parametrize("code, trigger", [
    ("HUMAN_HOLD", lambda w: setattr(w, "human", True)),
    ("DISPATCH_CLOSED", lambda w: setattr(w.store, "enabled", False)),
    ("CELL_BUSY", lambda w: w.state.omx_cell_states["cell_s"].update({"phase": "ARM_IN_BED_ZONE"})),
])
def test_hold_landing_during_plan_aborts_start_through_start_guard(code, trigger):
    world = World(_state(_task()))
    plan = world.plan

    async def plan_then_hold(*args):
        result = await plan(*args)
        trigger(world)
        return result

    world.plan = plan_then_hold
    # World.tick passes static bool for human; verify dynamic callable human_detected too.
    asyncio.run(pd.dispatch_tick(
        world.state, console=world.console, runner=world.runner, plan=world.plan,
        task_service=SimpleNamespace(store=world.store), active=world.active,
        human_detected=lambda: world.human, save=lambda: world.saves.append(dict(world.state.pinky_tasks["p1"])),
        now=time.time(), trip_request=lambda place: place))
    task = world.state.pinky_tasks["p1"]
    assert world.runner.starts == [] and (task["status"], task["reason"]) == ("FAILED", code)


def test_cancel_while_starting_with_failed_trip_cancel_never_falsely_confirms():
    world = World(_state(_task()))
    start = world.runner.start
    seen = {}

    async def start_then_unconfirmed_cancel(plan_id, principal_id, start_token=None, start_guard=None):
        trip = await start(plan_id, principal_id, start_token=start_token, start_guard=start_guard)
        world.runner.cancel_fails = 2  # both cancel_task and post-start retry lose the link
        cancelled = await pd.cancel_task(world.state, world.state.pinky_tasks["p1"], runner=world.runner,
                                         principal_id="op", now=time.time())
        seen["status"] = cancelled["status"]
        seen["confirmed"] = cancelled["status"] in pd.TERMINAL
        return trip

    world.runner.start = start_then_unconfirmed_cancel
    world.tick()
    task = world.state.pinky_tasks["p1"]
    assert seen == {"status": "SENDING", "confirmed": False}
    assert task["status"] == "SENT" and task["cancel_requested"] is True
    assert world.runner.trips["plan-1"]["state"] == "started"
    world.tick()  # next tick retries and confirms
    assert (task["status"], world.runner.trips["plan-1"]["state"]) == ("CANCELLED", "canceled")


def test_cancel_while_starting_when_trip_already_arrived_settles_arrived():
    world = World(_state(_task()))
    start = world.runner.start

    async def start_then_immediate_arrive(plan_id, principal_id, start_token=None, start_guard=None):
        trip = await start(plan_id, principal_id, start_token=start_token, start_guard=start_guard)
        trip["state"] = "arrived"
        return trip

    world.runner.start = start_then_immediate_arrive
    world.state.pinky_tasks["p1"]["cancel_requested"] = False

    async def gone(trip_id, principal_id, reason=None):
        raise TripErr("TRIP_NOT_RUNNING")

    orig_plan = world.plan

    async def plan_then_flag(*args):
        return await orig_plan(*args)

    # Mark cancel during start right after trip opens in arrived state
    inner = start_then_immediate_arrive

    async def start_arrive_and_cancel(plan_id, principal_id, start_token=None, start_guard=None):
        trip = await inner(plan_id, principal_id, start_token=start_token, start_guard=start_guard)
        await pd.cancel_task(world.state, world.state.pinky_tasks["p1"], runner=world.runner,
                             principal_id="op", now=time.time())
        return trip

    world.runner.cancel = gone
    world.runner.start = start_arrive_and_cancel
    world.plan = plan_then_flag
    world.tick()
    assert world.state.pinky_tasks["p1"]["status"] == "ARRIVED"


def test_multitask_tick_rechecks_dispatch_latch_between_tasks():
    t1 = _task(task_id="p1", robot_id="rosy_46", place_id="S5", created_at=time.time() - 2)
    t2 = _task(task_id="p2", robot_id="rosy_45", place_id="S1", created_at=time.time() - 1)
    console = Console()
    rows = [{"robot_id": "rosy_46", "online": True, "state": {"safety": {"estop": False}}},
            {"robot_id": "rosy_45", "online": True, "state": {"safety": {"estop": False}}}]

    async def snap():
        return {"robots": rows}

    console.snapshot = snap
    world = World(_state(t1, t2), console=console)
    orig_plan = world.plan

    async def plan_closes_latch(*args):
        res = await orig_plan(*args)
        world.store.enabled = False
        return res

    world.plan = plan_closes_latch
    world.tick()
    assert t1["status"] == "FAILED" and t1["reason"] == "DISPATCH_CLOSED"
    assert (t2["status"], t2["reason"]) == ("REFUSED", "DISPATCH_CLOSED")


def test_multitask_tick_skips_queued_task_cancelled_during_prior_plan():
    t1 = _task(task_id="p1", robot_id="rosy_46", place_id="S5", created_at=time.time() - 2)
    t2 = _task(task_id="p2", robot_id="rosy_45", place_id="S1", created_at=time.time() - 1)
    console = Console()
    rows = [{"robot_id": "rosy_46", "online": True, "state": {"safety": {"estop": False}}},
            {"robot_id": "rosy_45", "online": True, "state": {"safety": {"estop": False}}}]

    async def snap():
        return {"robots": rows}

    console.snapshot = snap
    world = World(_state(t1, t2), console=console)
    orig_plan = world.plan

    async def plan_cancels_second(*args):
        res = await orig_plan(*args)
        await pd.cancel_task(world.state, t2, runner=world.runner, principal_id="op", now=time.time())
        return res

    world.plan = plan_cancels_second
    world.tick()
    assert t1["status"] == "SENT" and (t2["status"], t2["reason"]) == ("CANCELLED", "OPERATOR_CANCEL")
    assert len(world.plans) == 1 and len(world.runner.starts) == 1


def test_runner_none_with_in_flight_cancel_does_not_crash():
    task = _task(status="SENT", plan_id="plan-1", trip_id="plan-1")
    world = World(_state(task))
    world.state.omx_cell_states = {}
    asyncio.run(pd.cancel_task(world.state, task, runner=None, principal_id="op", now=time.time()))
    assert task["status"] == "SENT" and task["cancel_receipt"] == {"error": "TRIP_PATH_UNAVAILABLE"}
    res = asyncio.run(pd.dispatch_tick(
        world.state, console=world.console, runner=None, plan=None,
        task_service=SimpleNamespace(store=world.store), active=world.active, human_detected=False,
        save=lambda: None, now=time.time(), trip_request=lambda p: p))
    assert res == [] and (task["status"], task["reason"]) == ("FAILED", "TRIP_UNKNOWN")


def test_real_trip_runner_and_pipeline_routes_e2e(tmp_path, monkeypatch):
    import httpx
    from fastapi import FastAPI, Request
    from fakes import fresh_battery
    from fleet.server.site_auth import SitePrincipal, build_role_guards
    from fleet.server.site_map_store import SiteMapStore
    from fleet.server.sitemap import pipeline_routes as routes
    from fleet.server.task_service import FleetTaskService
    from fleet.server.task_store import FleetTaskStore
    from fleet.server.trip_ports import MapPose, TripConfig
    from fleet.server.trip_runner import TripRunner
    from fleet.server.trips.trip_routes import install_trip_routes
    from fleet.server.console_view import TripCaps
    from fleet.site_map import SiteMap

    site_map = SiteMap.model_validate({
        "places": [
            {"id": "S1", "name": "S1", "x": 0.0, "y": 0.0, "kind": "junction"},
            {"id": "S3", "name": "S3", "x": 1.0, "y": 0.0, "kind": "junction"},
        ],
        "edges": [{
            "id": "s1-s3", "from": "S1", "to": "S3", "polyline": [[0.0, 0.0], [1.0, 0.0]],
            "width_m": 0.4, "speed_cap_mps": 0.2, "drive_mode": "free",
        }],
    })

    class RealPorts:
        poses_in_robot_frame = True

        def __init__(self):
            self.pose = MapPose(0.0, 0.0, 0.0, "LOCALIZED", "sighting", 0.0, 0.1, 0.1, None)
            self.caps = TripCaps("pinky_pro", frozenset({"free"}), 0.2, trip_lease=True)
            self.leases_opened = 0
            self.on_caps = None

        async def caps_for(self, _rid):
            if self.on_caps is not None:
                await self.on_caps()
            return self.caps

        async def arbitrated_pose(self, _rid):
            return self.pose

        async def refresh(self, _rid, force_rest=False):
            return None

        async def trip_lease(self, _rid, body):
            self.leases_opened += 1
            return {"lease_id": body["lease_id"]}

        async def trip_lease_release(self, _rid, _lease_id):
            return {"released": True}

        async def hold(self, _rid):
            return {"mode": "OFF"}

        async def goal(self, _rid, _x, _y, _yaw):
            return {"accepted": True}

        async def cancel_goal(self, _rid):
            return {"canceled": True}

    def build_stack(name):
        ports = RealPorts()
        maps = SiteMapStore(tmp_path / f"{name}-maps.sqlite3")
        maps.import_if_empty(site_map, source="test")
        task_store = FleetTaskStore(tmp_path / f"{name}-fleet.sqlite3")
        task_service = FleetTaskService(task_store, robot_ids={"rosy_46"})
        task_store.rearm_dispatch(expected_generation=task_store.dispatch_control()["generation"], actor_id="op-kim")
        runner = TripRunner(
            store=maps, routing_config=maps.routing_config, caps=ports.caps_for, battery=fresh_battery,
            poses=ports, junction=ports, goal=ports.goal, cancel_goal=ports.cancel_goal,
            lease={"required": True}, config=TripConfig(period_s=0.1),
        )
        console = SimpleNamespace(
            robot_ids={"rosy_46"},
            snapshot=lambda: asyncio.sleep(0, result={
                "robots": [{"robot_id": "rosy_46", "online": True, "state": {"safety": {"estop": False}}}]
            }),
        )
        principal = SitePrincipal("op-kim", "operator")
        _viewer, operator, named, _proposer = build_role_guards(lambda: principal, {"h": principal})
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        ledger_dir = tmp_path / name
        ledger_dir.mkdir()
        monkeypatch.setattr(routes, "_storage_dir", lambda: ledger_dir)
        app = FastAPI()

        @app.middleware("http")
        async def as_op(request: Request, call_next):
            request.state.site_principal = principal
            return await call_next(request)

        app.state.trip_requester_guards = (operator, named)
        app.state.task_service = task_service
        install_trip_routes(
            app, console=console, site_maps=maps, caps_for=ports.caps_for, routing_config=maps.routing_config,
            require_operator=operator, require_named_operator=named, runner=runner, read_guard=[])
        routes.install_pipeline_routes(app, console=console, site_maps=maps)
        return app, runner, ports

    async def scenario_normal_to_arrived():
        app, runner, ports = build_stack("normal")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/fleet/pipeline/pinky-tasks", json={"action": "dock_s3", "robot_id": "rosy_46"})
            assert r.status_code == 200, r.text
            tid = r.json()["pinky_task"]["task_id"]
            sent = await app.state.task_dispatch_tick()
            assert len(sent) == 1 and app.state.pinky_tasks[tid]["status"] == "SENT", app.state.pinky_tasks[tid]
            assert ports.leases_opened == 1 and app.state.pinky_tasks[tid]["receipt"]["lease"]
            ports.pose = MapPose(1.0, 0.0, 0.0, "LOCALIZED", "sighting", 0.0, 0.1, 0.1, None)
            await runner.tick()
            await app.state.task_dispatch_tick()
            assert app.state.pinky_tasks[tid]["status"] == "ARRIVED", app.state.pinky_tasks[tid]

    async def scenario_estop_during_plan():
        app, runner, ports = build_stack("estop")
        orig_plan = app.state.trip_plan

        async def plan_then_close_all(*args):
            res = await orig_plan(*args)
            runner.close_all("estop")
            return res

        app.state.trip_plan = plan_then_close_all
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/fleet/pipeline/pinky-tasks", json={"action": "dock_s3", "robot_id": "rosy_46"})
            assert r.status_code == 200, r.text
            tid = r.json()["pinky_task"]["task_id"]
            await app.state.task_dispatch_tick()
            task = app.state.pinky_tasks[tid]
            assert (task["status"], task["reason"]) == ("FAILED", "TRIP_START_CANCELED"), task
            assert ports.leases_opened == 0 and runner.open_trips() == []

    async def scenario_http_cancel_during_real_start_caps():
        app, runner, ports = build_stack("cancel")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/api/fleet/pipeline/pinky-tasks", json={"action": "dock_s3", "robot_id": "rosy_46"})
            assert r.status_code == 200, r.text
            tid = r.json()["pinky_task"]["task_id"]
            cancel_replies = []

            async def fire_http_cancel():
                if app.state.pinky_tasks[tid]["status"] == "SENDING" and app.state.pinky_tasks[tid].get("plan_id"):
                    ports.on_caps = None  # fire once inside TripRunner.start (after plan_id, before _guard_start)
                    resp = await ac.post(f"/api/fleet/pipeline/pinky-tasks/{tid}/cancel")
                    cancel_replies.append((resp.status_code, resp.json()["confirmed"], resp.json()["pinky_task"]["status"]))

            ports.on_caps = fire_http_cancel
            await app.state.task_dispatch_tick()
            task = app.state.pinky_tasks[tid]
            assert cancel_replies == [(200, False, "SENDING")], (cancel_replies, task)
            assert (task["status"], task["reason"]) == ("CANCELLED", "OPERATOR_CANCEL"), task
            assert ports.leases_opened == 0 and runner.open_trips() == []

    asyncio.run(scenario_normal_to_arrived())
    asyncio.run(scenario_estop_during_plan())
    asyncio.run(scenario_http_cancel_during_real_start_caps())


def test_depart_s3_dispatch_revalidation_and_reservation_cleanup():
    now = time.time()

    def depart_world(*, folded=True):
        task = _task(task_id="p1", action="depart_s3", place_id="S1", target_place="S1", unload_batch_id="u-1")
        state = _state(task)
        state.omx_cell_tasks = {
            "u-1-1": {"task_id": "u-1-1", "robot_id": "rosy_46", "unload_batch_id": "u-1", "unload_index": 0,
                      "status": "COMPLETED", "completed_at": now, "stage_result": {"source_clearance": {"objects": 0}}}
        }
        state.omx_cell_states = {"cell_s": {"phase": "RELEASED", "amr_motion_inhibited": False}}
        state.arm_live_states = {"arm_s": {"folded": folded, "updated_at": now}}
        state.unload_releases = {"u-1": {"robot_id": "rosy_46", "task_id": "p1", "state": "OPERATOR", "target": "S1"}}
        return state, task, World(state)

    # 1. Valid OPERATOR reservation + ready release dispatches normally to S1.
    st_ok, t_ok, w_ok = depart_world(folded=True)
    sent = w_ok.tick()
    assert len(sent) == 1 and t_ok["status"] == "SENT" and w_ok.plans[0][1] == "S1"
    w_ok.runner.trips[t_ok["trip_id"]]["state"] = "arrived"
    w_ok.tick()
    assert t_ok["status"] == "ARRIVED" and "u-1" in st_ok.unload_releases

    # 1b. Mismatched place_id against reserved target must refuse and release OPERATOR reservation.
    st_mis, t_mis, w_mis = depart_world(folded=True)
    t_mis["place_id"] = "S3"
    w_mis.tick()
    assert (t_mis["status"], t_mis["reason"]) == ("REFUSED", "DEPART_RESERVATION_MISMATCH")
    assert w_mis.plans == [] and "u-1" not in st_mis.unload_releases

    # 2. If arm_s unfolds before tick, refusal() rejects and clears OPERATOR reservation.
    st_ref, t_ref, w_ref = depart_world(folded=False)
    w_ref.tick()
    assert (t_ref["status"], t_ref["reason"]) == ("REFUSED", "ARM_NOT_HOME")
    assert "u-1" not in st_ref.unload_releases

    # 3. If arm_s unfolds during plan(), start_guard rejects before start and clears OPERATOR reservation.
    st_grd, t_grd, w_grd = depart_world(folded=True)
    orig_plan = w_grd.plan

    async def unfold_during_plan(robot_id, request, principal_id):
        res = await orig_plan(robot_id, request, principal_id)
        st_grd.arm_live_states["arm_s"]["folded"] = False
        return res

    w_grd.plan = unfold_during_plan
    w_grd.tick()
    assert (t_grd["status"], t_grd["reason"]) == ("FAILED", "ARM_NOT_HOME")
    assert w_grd.runner.starts == [] and "u-1" not in st_grd.unload_releases


def test_failed_dock_and_unload_cancels_queued_cell_task_only():
    t_q = _task(task_id="p1", action="dock_and_unload_s3", spawned_cell_task_id="c-q")
    st_q = _state(t_q)
    st_q.omx_cell_tasks = {"c-q": {"task_id": "c-q", "cell_id": "cell_s", "status": "QUEUED"}}
    w_q = World(st_q, console=Console(online=False))
    w_q.tick()
    assert (t_q["status"], t_q["reason"]) == ("REFUSED", "ROBOT_OFFLINE")
    assert st_q.omx_cell_tasks["c-q"]["status"] == "CANCELLED"
    assert st_q.omx_cell_tasks["c-q"]["cancel_reason"] == "PINKY_TASK_REFUSED"

    t_r = _task(task_id="p1", action="dock_and_unload_s3", spawned_cell_task_id="c-r")
    st_r = _state(t_r)
    st_r.omx_cell_tasks = {"c-r": {"task_id": "c-r", "cell_id": "cell_s", "status": "RUNNING"}}
    w_r = World(st_r, console=Console(online=False))
    w_r.tick()
    assert t_r["status"] == "REFUSED" and st_r.omx_cell_tasks["c-r"]["status"] == "RUNNING"


def test_pinky_dispatch_enabled_exposed_on_list_endpoints(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from fleet.server.sitemap import pipeline_routes as routes
    from tools.sim.bay_departure_sim import build_world_261026_site_map

    site, graph, _ = build_world_261026_site_map()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(routes, "_storage_dir", lambda: tmp_path)
    app = FastAPI()
    routes.install_pipeline_routes(app, site_maps=SimpleNamespace(active=lambda: (1, site, graph, None)))
    client = TestClient(app)

    monkeypatch.setenv(pd.FLAG, "1")
    assert client.get("/api/fleet/pipeline/cell-tasks").json()["pinky_dispatch_enabled"] is True
    assert client.get("/api/fleet/pipeline/pinky-tasks").json()["pinky_dispatch_enabled"] is True

    monkeypatch.delenv(pd.FLAG, raising=False)
    assert client.get("/api/fleet/pipeline/cell-tasks").json()["pinky_dispatch_enabled"] is False
    assert client.get("/api/fleet/pipeline/pinky-tasks").json()["pinky_dispatch_enabled"] is False
