"""D-760 8 (stage 4): one shared REST state read per robot, the reader states ``max_age_s``.

Fake robots and a fake clock: reads per robot per second, a slow robot, failures reaching the trip loop."""

from __future__ import annotations

import ast
import asyncio
import math
from pathlib import Path

import httpx
import pytest

from fakes import FakeRobot
from fleet.hub.hub import HubError
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.localization_service import build_localization_service
from fleet.server.map_pose_service import TRIP_READ_AGE_S, MapPoseService
from fleet.server.site_map_store import SiteMapStore
from fleet.server.trip_ports import HttpLaneJunction, TripConfig
from fleet.server.trip_runner import TripRunner
from fleet.swarm.robots import RobotEndpoint
from test_routing import demo_site
from test_trip_authority import AuthFleet
from test_trip_link_wait import NEW, LinkFleet, _running, _ticks

FLEET = Path(__file__).resolve().parents[1] / "fleet"


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def _service(gather_rest, clock, ids=("r1",)):
    return MapPoseService(lambda: list(ids), gather_rest=gather_rest, clock=clock)


# --- the shared read ------------------------------------------------------------------------

def test_a_read_is_shared_within_the_callers_max_age_counted_from_the_read_start():
    clock, calls = Clock(), []

    async def rest(robot_id):
        calls.append(clock.now)
        clock.now += 0.3                       # the read itself takes 0.3 s
        return {"robot_id": robot_id, "n": len(calls)}

    service = _service(rest, clock)

    async def go():
        assert (await service.state("r1", 0.45))["n"] == 1
        assert (await service.state("r1", 0.45))["n"] == 1     # started 0.3 s ago: shared
        assert (await service.state("r1", 0.25))["n"] == 2     # 0.3 s from its start: too old for 0.25
        clock.now += 0.5
        assert (await service.state("r1", 1.0))["n"] == 2
        assert (await service.state("r1"))["n"] == 3           # the trip loop's default age

    asyncio.run(go())
    assert TRIP_READ_AGE_S == 0.45 and len(calls) == 3


def test_concurrent_callers_join_the_read_in_flight():
    clock, calls = Clock(), []
    gate = {}

    async def rest(robot_id):
        calls.append(robot_id)
        await gate["e"].wait()
        return {"robot_id": robot_id}

    service = _service(rest, clock)

    async def go():
        gate["e"] = asyncio.Event()
        waiters = [asyncio.ensure_future(service.state("r1", age)) for age in (0.0, 0.45, 1.0)]
        await asyncio.sleep(0)
        gate["e"].set()
        return await asyncio.gather(*waiters)

    first, second, third = asyncio.run(go())
    assert calls == ["r1"] and first is second is third


@pytest.mark.parametrize("error", [HubError("UNREACHABLE", "r1"), OSError("no route to host"),
                                   httpx.ConnectError("refused"), httpx.ReadTimeout("slow"),
                                   ValueError("bad body")])
def test_a_failed_read_keeps_nothing_and_raises_its_own_exception_to_every_waiter(error):
    clock, calls = Clock(), []
    gate, fail = {}, {"on": False}

    async def rest(robot_id):
        calls.append(clock.now)
        await gate["e"].wait()
        if fail["on"]:
            raise error
        return {"robot_id": robot_id}

    service = _service(rest, clock)

    async def go():
        gate["e"] = asyncio.Event()
        gate["e"].set()
        await service.state("r1")                               # a good read at t=100
        clock.now += 0.5
        fail["on"], gate["e"] = True, asyncio.Event()
        waiters = [asyncio.ensure_future(service.state("r1", age)) for age in (0.45, 0.2)]
        await asyncio.sleep(0)
        gate["e"].set()
        results = await asyncio.gather(*waiters, return_exceptions=True)
        assert all(result is error for result in results)   # the same object, never wrapped
        with pytest.raises(type(error)) as raised:            # the 0.5 s old value is not handed out
            await service.state("r1", 0.45)
        assert raised.value is error
        assert (await service.state("r1", 1.0)) == {"robot_id": "r1"}   # within this caller's age

    asyncio.run(go())
    assert len(calls) == 3                                      # a failure is never cached


def test_a_read_feeds_the_odom_with_its_exact_stamp():
    clock = Clock()
    stamp = 1_800_000_000.123456

    async def rest(robot_id):
        return {"robot_id": robot_id, "odom_pose": {"x": 0.1, "y": 0.0, "yaw": 0.0, "stamp": stamp}}

    service = MapPoseService(lambda: ["r1"], gather_rest=rest, clock=clock, wall=lambda: stamp + 0.05)
    asyncio.run(service.refresh("r1", force_rest=True))
    assert service._trackers["r1"].latest_odom_stamp == stamp


def test_the_junction_state_and_the_trip_refresh_share_one_read():
    clock = Clock()
    robot = FakeRobot("r1", state={"robot_id": "r1", "line_follow": {
        "junction": {"state": "idle", "seq": 3}, "reason": "ok"}})
    service = _service(lambda rid: robot.state(), clock)
    port = HttpLaneJunction(lambda: {"r1": robot}, service.state)

    async def go():
        await service.refresh("r1", force_rest=True)
        return await port.junction_state("r1")

    junction = asyncio.run(go())
    assert junction["seq"] == 3 and [c[0] for c in robot.calls].count("state") == 1


# --- slow robot ------------------------------------------------------------------------------

def test_a_slow_read_of_one_robot_does_not_delay_the_others():
    """Robot a's read hangs across three trip periods (1.5 s on the fake clock); b reads every period,
    a's callers time out (link loss) while its one read stays in flight, and nothing piles up."""
    clock = Clock()
    a, b = FakeRobot("a", state={"robot_id": "a"}), FakeRobot("b", state={"robot_id": "b"})
    robots = {"a": a, "b": b}
    service = _service(lambda rid: robots[rid].state(), clock, ids=("a", "b"))

    async def go():
        a.state_gate = asyncio.Event()
        timeouts = 0
        for _ in range(3):
            clock.now += 0.5
            done, pending = await asyncio.wait(
                [asyncio.ensure_future(service.refresh(rid, force_rest=True)) for rid in ("a", "b")],
                timeout=0.05)
            assert len(done) == 1                               # b finished within its period
            for task in pending:
                task.cancel()
                timeouts += 1
        a.state_gate.set()
        await asyncio.sleep(0.01)                               # the hung read ends
        clock.now += 0.5
        await service.refresh("a", force_rest=True)
        return timeouts

    assert asyncio.run(go()) == 3
    assert [c[0] for c in b.calls].count("state") == 3
    assert [c[0] for c in a.calls].count("state") == 2         # the hung read, then one after it ended


# --- the trip loop -----------------------------------------------------------------------------

class SharedFleet(LinkFleet):
    """LinkFleet whose pose refresh and junction read go through one ``MapPoseService`` read (app.py)."""

    def __init__(self, ids, caps):
        super().__init__(ids, caps)
        self.reads = MapPoseService(lambda: list(ids), gather_rest=self._rest, clock=lambda: self.now)
        self.gate: asyncio.Event | None = None  # set: a read that got through waits here

    async def _rest(self, robot_id):
        self._call(robot_id, "state")
        if self.gate is not None:
            await self.gate.wait()
        return {"robot_id": robot_id}

    async def refresh(self, robot_id, force_rest=False, after=0):
        await self.reads.refresh(robot_id, force_rest=force_rest, after=after)

    def read_number(self, robot_id):
        return self.reads.read_number(robot_id)

    async def junction_state(self, robot_id, after=0):
        await self.reads.state(robot_id, after=after)
        return await AuthFleet.junction_state(self, robot_id)


def _shared_setup(caps, **config):
    fleet = SharedFleet(tuple(caps), caps)
    store = SiteMapStore(None, clock=lambda: fleet.now)
    store.import_if_empty(demo_site(), source="test")
    runner = TripRunner(store=store, routing_config=store.routing_config, caps=fleet.caps_for, poses=fleet,
                        junction=fleet, goal=fleet.goal, cancel_goal=fleet.cancel_goal,
                        blocked=lambda: fleet.blocked, clock=lambda: fleet.now, config=TripConfig(**config),
                        authority=True, lease={"required": True})
    runner.lease._clock = lambda: fleet.now
    runner.authority._clock, runner.authority.quiet_until = (lambda: fleet.now), -math.inf
    return runner, store, fleet


def _state_reads(fleet, robot_id):
    return sum(1 for r, kind, _ in fleet.calls if r == robot_id and kind == "state")


def test_a_trip_step_reads_the_robot_state_once():
    runner, store, fleet = _running(*_shared_setup({"a": NEW}))
    before = _state_reads(fleet, "a")
    _ticks(runner, fleet, 10)
    assert _state_reads(fleet, "a") - before == 10


@pytest.mark.parametrize("error", [HubError("UNREACHABLE", "a"), OSError("no route to host"),
                                   httpx.ConnectError("refused")])
def test_a_transport_failure_of_the_shared_read_is_link_loss(error):
    runner, store, fleet = _running(*_shared_setup({"a": NEW}))
    fleet.fail["state"] = error
    _ticks(runner, fleet, 4)
    assert runner.view("a")["state"] == "link_wait"
    del fleet.fail["state"]
    _ticks(runner, fleet, 2)
    assert runner.view("a")["state"] == "running"


def test_a_non_transport_failure_of_the_shared_read_ends_the_trip_failed():
    runner, store, fleet = _running(*_shared_setup({"a": NEW}))
    fleet.fail["state"] = ValueError("bad body")
    _ticks(runner, fleet, 2)
    assert runner.view("a")["state"] == "failed"


# --- rates with every periodic reader ------------------------------------------------------------

@pytest.mark.parametrize("count", [2, 10])
def test_every_fleet_loop_together_reads_a_robot_at_most_3_times_a_second(tmp_path, count):
    """A lane trip for 60 s (fake clock): trip loop (pose + junction, 0.5 s), lane compliance (0.5 s),
    localization (0.5 s), task dispatch snapshot (0.25 s) and path history (1 s), wired by create_app."""
    clock = Clock()
    ids = [f"r{i}" for i in range(count)]
    robots = [FakeRobot(rid, state={"robot_id": rid}) for rid in ids]
    reads = {rid: [] for rid in ids}
    for robot in robots:
        def state(robot=robot, raw=robot.state):
            reads[robot.robot_id].append(clock.now)
            return raw()
        robot.state = state
    console = FleetConsole([RobotEndpoint(rid, "http://127.0.0.1:8080", "robot-rest") for rid in ids],
                           robots, clock=clock)
    localization = build_localization_service(console, None)
    app = create_app(console, start_task_dispatcher=False, localization_service=localization)
    map_pose = app.state.map_pose
    map_pose._clock = clock
    junction = app.state.trip_runner._junction
    assert console.read_state == map_pose.state             # app.py wiring: one read for every caller
    assert junction.read_number == map_pose.read_number     # the trip fences the read its junction uses

    async def go():
        for step in range(60 * 20):                         # 50 ms steps
            clock.now = 100.0 + step * 0.05
            if step % 10 == 0:                              # trip loop: pose refresh, then the junction
                for rid in ids:
                    await map_pose.refresh(rid, force_rest=True)
                    await junction.junction_state(rid)
            if step % 10 == 4:                              # lane compliance, its own phase
                for rid in ids:
                    await map_pose.refresh(rid, force_rest=True)    # the monitor's call (0.45 s)
            if step % 10 == 7:
                await localization.tick()
            if step % 5 == 2:                               # the task dispatch loop's snapshot
                await console.snapshot()
            if step % 20 == 13:                             # path history (hub or REST)
                for rid in ids:
                    await console._gather_state(rid)

    asyncio.run(go())
    for rid, times in reads.items():
        assert len(times) <= 3 * 60, (rid, len(times))
        worst = max(sum(1 for t in times if start <= t < start + 1.0) for start in times)
        assert worst <= 3, (rid, worst)
        assert len(times) == 2 * 60                         # one read per trip period: 2.0/s measured


# --- guard -------------------------------------------------------------------------------------

#: Fleet's periodic loops (D-760 8). Excluded: swarm/session.py (K3) and one-off command paths.
PERIODIC = ("server/app.py", "server/pose/map_pose_service.py", "server/trips/trip_runner.py",
            "server/trips/trip_ports.py", "server/pose/lane_compliance_service.py",
            "server/pose/localization_service.py", "server/sitemap/path_history.py", "swarm/anchor.py",
            "server/tether_routes.py", "server/tether_watch.py",
            "server/trips/trip_steps.py", "server/trips/trip_replan.py", "server/trips/trip_geometry.py",
            "server/trips/trip_live.py",
            "server/console/console.py", "server/trips/trip_preview.py")
#: Where a direct read may stay: a constructor's fallback without the shared read, and app.py's
#: ``_rest_state``, the shared read's own transport.
ALLOWED = {"__init__", "_rest_state"}


def test_periodic_loops_make_no_direct_state_call():
    found = []
    for rel in PERIODIC:
        tree = ast.parse((FLEET / rel).read_text(encoding="utf-8"))

        def visit(node, owner):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                owner = node.name
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "state" and not node.args and not node.keywords
                    and owner not in ALLOWED):
                found.append(f"{rel}:{node.lineno} in {owner}")
            for child in ast.iter_child_nodes(node):
                visit(child, owner)

        visit(tree, None)
    assert found == []
