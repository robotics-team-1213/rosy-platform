"""D-760 stage 4 Safety-Review CONDITIONS: the trip loop's shared read is newer than its last step,
its last junction send and its link loss; hub and REST reads are kept apart; a robot's HTTP error on
the state read stops the trip with its own code."""

from __future__ import annotations

import asyncio

from fleet.server.map_pose_service import MapPoseService
from fleet.server.site_map_store import SiteMapStore
from fleet.server.trip_ports import TripConfig
from fleet.server.trip_runner import TripRunner
from fleet.site_map import from_lane_graph
from fleet.swarm.transport import RobotApiError
from test_shared_state_read import Clock, _shared_setup
from test_trip_link_wait import NEW, _running, _settle, _ticks
from test_trip_runner import LANE, LANE_GRAPH, Ports, _arc, _plan


class SnapshotPorts(Ports):
    """test_trip_runner's fake CORE behind one shared read: the trip sees CORE's junction as it was
    when the read started, as a REST state read does."""

    def __init__(self, caps=LANE):
        super().__init__(caps)
        self.reads = MapPoseService(lambda: ["rosy_60"], gather_rest=self._rest, clock=lambda: self.now)

    async def _rest(self, robot_id):
        return {"line_follow": {"junction": dict(self.core.status())}}

    async def refresh(self, robot_id, force_rest=False, after=0):
        assert force_rest
        self.refreshes += 1
        await self.reads.refresh(robot_id, force_rest=True, after=after)

    def read_number(self, robot_id):
        return self.reads.read_number(robot_id)

    async def junction_state(self, robot_id):
        return (await self.reads.state(robot_id))["line_follow"]["junction"]


def _snapshot_setup():
    ports = SnapshotPorts()
    store = SiteMapStore(None, clock=lambda: ports.now)
    store.import_if_empty(from_lane_graph(LANE_GRAPH), source="test")
    runner = TripRunner(store=store, routing_config=store.routing_config, caps=ports.caps_for, poses=ports,
                        junction=ports, goal=ports.goal, cancel_goal=ports.cancel_goal,
                        blocked=lambda: ports.blocked, clock=lambda: ports.now, config=TripConfig())
    return runner, store, ports


def _step(runner, ports, dt):
    ports.now += dt
    asyncio.run(runner.tick())


# --- 1 HIGH: never a read from before the last step or the last send ---------------------------

def test_a_step_0_43_s_after_a_send_reads_anew_and_sends_nothing_again():
    """Jittered periods: the step after the stop went out comes 0.43 s later, inside the 0.45 s age.
    The read from before the send says idle; reusing it would send the stop again."""
    runner, store, ports = _snapshot_setup()
    arc = _arc(store, "east:fwd")
    _plan(store, ports, "east:fwd", 0.5, "SE")
    asyncio.run(runner.start("p1", "bob"))
    _step(runner, ports, 0.5)
    ports.at(arc, arc.length_m - 0.55)
    _step(runner, ports, 0.5)
    assert ports.sent == [("stop", "SE", 0.55)]
    ports.at(arc, arc.length_m - 0.5)
    for dt in (0.43, 0.43, 0.5, 0.43):
        _step(runner, ports, dt)
    assert ports.sent == [("stop", "SE", 0.55)]


def test_every_trip_step_reads_after_the_last_one_even_inside_the_age():
    runner, store, ports = _snapshot_setup()
    _plan(store, ports, "east:fwd", 0.5, "SE")
    asyncio.run(runner.start("p1", "bob"))
    _step(runner, ports, 0.5)
    first = ports.read_number("rosy_60")
    for _ in range(4):
        _step(runner, ports, 0.3)
    assert ports.read_number("rosy_60") == first + 4


def test_a_read_in_flight_from_before_the_fence_is_waited_out_and_not_handed_out():
    clock, gate, served = Clock(), {}, []

    async def rest(robot_id):
        served.append(len(served) + 1)
        number = len(served)
        if number == 1:
            await gate["e"].wait()
        return {"read": number}

    service = MapPoseService(lambda: ["r1"], gather_rest=rest, clock=clock)

    async def go():
        gate["e"] = asyncio.Event()
        early = asyncio.ensure_future(service.state("r1", 0.0))    # in flight when the instruction goes out
        await asyncio.sleep(0)
        sent_after = service.read_number("r1")
        late = asyncio.ensure_future(service.state("r1", 10.0, after=sent_after))
        await asyncio.sleep(0)
        gate["e"].set()
        return await early, await late, service.read_number("r1")

    early, late, number = asyncio.run(go())
    assert early == {"read": 1} and late == {"read": 2} and number == 2
    assert asyncio.run(service.state("r1", 10.0, after=1)) == {"read": 2}   # newer and young: shared


# --- 2 MEDIUM: link back only on a read that started after the loss ---------------------------

def test_a_read_in_flight_from_before_the_loss_does_not_bring_the_trip_back():
    runner, store, fleet = _running(*_shared_setup({"a": NEW}, port_timeout_s=0.05))

    async def go():
        fleet.gate = asyncio.Event()
        fleet.advance(0.5)
        early = asyncio.ensure_future(fleet.reads.state("a", 0.0))  # got through, answers late
        for _ in range(3):
            await asyncio.sleep(0)
        assert fleet.calls[-1][:2] == ("a", "state")
        fleet.fail["state"] = OSError("no route to host")           # every later read fails
        await runner.tick()                                          # the step's read times out
        await _settle(runner)
        assert runner.view("a")["state"] == "link_wait"
        fleet.gate.set()
        await early                                                   # the old read lands after the loss
        fleet.gate = None
        for _ in range(3):
            fleet.advance(0.2)                                        # inside its 0.45 s age
            await runner.tick()
            await _settle(runner)
        return runner.view("a")["state"]

    assert asyncio.run(go()) == "link_wait"
    del fleet.fail["state"]
    _ticks(runner, fleet, 2)
    assert runner.view("a")["state"] == "running"


# --- 3 hub and REST reads are kept apart --------------------------------------------------------

def test_hub_and_rest_reads_are_kept_and_joined_separately():
    clock, calls = Clock(), []

    async def hub(robot_id):
        calls.append("hub")
        return {"from": "hub"}

    async def rest(robot_id):
        calls.append("rest")
        return {"from": "rest"}

    service = MapPoseService(lambda: ["r1"], gather=hub, gather_rest=rest, clock=clock)

    async def go():
        await service.refresh("r1")
        assert await service.state("r1") == {"from": "rest"}
        await service.refresh("r1", force_rest=True)
        await service.refresh("r1")
        assert calls == ["hub", "rest"]                     # each kept on its own
        clock.now += 1.0
        _, rest_state = await asyncio.gather(service.refresh("r1"), service.state("r1"))
        assert rest_state == {"from": "rest"}               # never joined into the hub read

    asyncio.run(go())
    assert calls.count("hub") == 2 and calls.count("rest") == 2


# --- 4 an HTTP error on the state read is an answer ---------------------------------------------

def test_a_robot_http_error_on_the_state_read_stops_the_trip_with_its_code():
    runner, store, fleet = _running(*_shared_setup({"a": NEW}))
    fleet.fail["state"] = RobotApiError("a", 503, "HTTP_503", "busy")
    _ticks(runner, fleet)
    view = runner.view("a")
    assert (view["state"], view["reason"], view["detail"].get("status")) == ("failed", "HTTP_503", 503)


# --- minors ---------------------------------------------------------------------------------------

def test_a_robot_that_leaves_the_roster_drops_its_kept_reads():
    clock, roster = Clock(), ["r1", "r2"]

    async def rest(robot_id):
        return {"robot_id": robot_id}

    service = MapPoseService(lambda: list(roster), gather_rest=rest, clock=clock)
    asyncio.run(service.refresh("r1", force_rest=True))
    asyncio.run(service.refresh("r2", force_rest=True))
    roster.remove("r1")
    service.arbitrated_pose("r2")
    assert {key[0] for key in service._kept} == {"r2"}
