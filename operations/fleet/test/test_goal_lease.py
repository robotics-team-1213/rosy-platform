"""D-550 10: Fleet sends and renews navigation goal leases (default off, capability gated).

Each goal source renews only while its reason to move holds (Safety-Review 2026-10-09)."""

from __future__ import annotations

import asyncio
from functools import partial
from types import SimpleNamespace

import pytest

from fakes import FakeClock, FakeRobot, run
from fleet import cli
from fleet.server.background_workers import attempt_open
from fleet.server.console import FleetConsole
from fleet.server.goal_lease import goal_lease_supported
from fleet.server.trip_guard import install_trip_guard
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import RobotApiError
from fleet.hub.hub import HubError

LEASE_CAPS = {"navigation": {"goal_navigation": True},
              "controls": {"schema": "rosy.controls/1", "items": [
                  {"id": "base", "kind": "base_velocity", "goal_lease": True}]}}


class LeaseRobot(FakeRobot):
    def __init__(self, robot_id: str, *, lease: bool = True) -> None:
        super().__init__(robot_id)
        self.lease = lease
        self.renewals: list[tuple] = []
        self.active: str | None = None   # the correlation id CORE still holds

    async def capabilities(self) -> dict:
        return LEASE_CAPS if self.lease else await super().capabilities()

    async def navigation_goal(self, x, y, yaw, *, correlation_id=None, lease_ttl_s=None) -> dict:
        self._record("navigation_goal", x, y, yaw, correlation_id, lease_ttl_s)
        self.active = correlation_id
        return {"accepted": True}

    async def navigation_goal_lease(self, correlation_id, ttl_s) -> dict:
        self.renewals.append((correlation_id, ttl_s))
        if correlation_id != self.active:
            raise RobotApiError(self.robot_id, 409, "GOAL_LEASE_NOT_ACTIVE", "not active")
        return {"renewed": True}


def _console(*robots, ttl=0.0, clock=None) -> FleetConsole:
    endpoints = [RobotEndpoint(robot_id=r.robot_id, base_url=f"http://127.0.0.1:808{i}", token="t")
                 for i, r in enumerate(robots)]
    return FleetConsole(endpoints, list(robots), clock=clock or FakeClock(), goal_lease_ttl_s=ttl)


def _sent(robot):
    return [call for call in robot.calls if call[0] == "navigation_goal"]


def _goal(console):
    return run(console.snapshot())["robots"][0]["goal"]


def _leased(**attempt):
    """A leased operator goal (or dispatch goal with ``attempt``) on a 4 s lease, operator present."""
    robot, clock = LeaseRobot("rosy_01"), FakeClock()
    console = _console(robot, ttl=4.0, clock=clock)
    console.goal_leases.operator_present()
    run(console.goal("rosy_01", 1.0, 0.0, **attempt))
    return robot, console, clock


def test_off_by_default_sends_no_lease_and_shows_nothing():
    robot = LeaseRobot("rosy_01")
    console = _console(robot)
    console.goal_leases.operator_present()
    run(console.goal("rosy_01", 1.0, 0.0))
    assert _sent(robot) == [("navigation_goal", 1.0, 0.0, 0.0, None, None)]
    run(console.goal_leases.renew())
    assert robot.renewals == [] and _goal(console) == {"x": 1.0, "y": 0.0, "yaw": 0.0}


@pytest.mark.parametrize("stage", ["yielded", "untrusted", "route", "observe", "map", "bay_map", "bay_calc", "bay_cap", "bay_receipt", "bay_timeout", "bay_malformed", "traffic_cancel"])
@pytest.mark.parametrize("stop_all", [False, True])
def test_stop_cannot_resurrect_queue_claim_or_yield(stage, stop_all, monkeypatch):
    async def main():
        robot, other = LeaseRobot("rosy_01"), LeaseRobot("rosy_02")
        console = _console(robot, other)
        entered, release = asyncio.Event(), asyncio.Event()

        async def pause(value):
            entered.set()
            await release.wait()
            return value

        if stage == "yielded":
            async def yielded():
                caps = await pause(LEASE_CAPS)
                console._yielding["rosy_01"] = {"for": "rosy_02"}
                return caps

            robot.capabilities = yielded
        elif stage == "untrusted":
            console._gather_state = lambda _rid: pause(({}, "rest"))
        elif stage == "route":
            console._route_of = lambda _rid: pause([(0.0, 0.0), (1.0, 0.0)])
            console._claims["rosy_02"] = [(0.0, 0.0), (1.0, 0.0)]
        elif stage == "observe":
            console._observe = lambda: pause(None)
        elif stage == "map":
            console.map = lambda: pause(None)
        elif stage == "traffic_cancel":
            robot._path = [(0.0, 0.0), (1.0, 0.0)]
            console._claims["rosy_02"] = list(robot._path)
            cancels = 0

            async def canceled():
                nonlocal cancels
                cancels += 1
                return await pause({"canceled": True}) if cancels == 1 else {"canceled": True}

            robot.navigation_cancel = canceled
        else:
            console._standing_in_the_way = lambda *_args: ["rosy_02"]
            console._pose_of = lambda _rid: (0.0, 0.0)
            from fleet.server import console as console_module
            monkeypatch.setattr(console_module.bays, "best_bay", lambda *_args, **_kw: (1.0, 1.0))
            if stage == "bay_map":
                calls = 0

                async def mapped():
                    nonlocal calls
                    calls += 1
                    return await pause(None) if calls == 2 else None

                console.map = mapped
            elif stage == "bay_cap":
                other.capabilities = lambda: pause(LEASE_CAPS)
            elif stage == "bay_calc":
                monkeypatch.setattr(console_module.asyncio, "to_thread", lambda *_args, **_kw: pause((1.0, 1.0)))
            else:
                async def bay_reply(*_args, **_kw):
                    await pause(None)
                    if stage == "bay_timeout":
                        raise TimeoutError("receipt lost")
                    return {} if stage == "bay_malformed" else {"accepted": True}

                other.navigation_goal = bay_reply
        goal = asyncio.create_task(console.goal("rosy_01", 1.0, 0.0))
        await entered.wait()
        try:
            await (console.estop_all() if stop_all else console.cancel("rosy_01"))
        finally:
            release.set()
        with pytest.raises((HubError, RuntimeError, TimeoutError)):
            await goal
        assert "rosy_01" not in console._queued
        assert "rosy_01" not in console._claims
        assert "rosy_01" not in console._goals
        assert not _sent(other)
        assert "rosy_02" not in console._yielding
        if stage in {"bay_receipt", "bay_timeout", "bay_malformed"}:
            assert ("navigation_cancel",) in other.calls

    run(main())


def test_formation_cannot_arm_a_follower_with_a_goal_in_flight():
    async def main():
        from fakes import FakeRelay

        leader, follower = LeaseRobot("rosy_01"), LeaseRobot("rosy_02")
        console = _console(leader, follower)
        console._relay_factory = lambda *_args, **_kw: FakeRelay()
        entered, release = asyncio.Event(), asyncio.Event()
        original = follower.navigation_goal

        async def sending(*args, **kw):
            entered.set()
            await release.wait()
            return await original(*args, **kw)

        follower.navigation_goal = sending
        goal = asyncio.create_task(console.goal("rosy_02", 1.0, 0.0))
        await entered.wait()
        try:
            with pytest.raises(HubError):
                await console.formation_start("rosy_01")
            assert not any(call[0] == "follow" for call in follower.calls)
            assert console._formation is None
        finally:
            release.set()
            await goal

    run(main())


@pytest.mark.parametrize("ttl,leased", [(0.0, False), (4.0, False), (4.0, True)])
@pytest.mark.parametrize("receipt", [{"accepted": False}, {}, {"accepted": "true"}])
def test_only_an_explicit_acceptance_records_goal_or_lease(ttl, leased, receipt):
    robot = LeaseRobot("rosy_01", lease=leased)
    console = _console(robot, ttl=ttl)

    async def refuse(*args, **kwargs):
        return receipt

    robot.navigation_goal = refuse
    if receipt.get("accepted") is False:
        assert run(console.goal("rosy_01", 1.0, 0.0)) == receipt
    else:
        with pytest.raises(RuntimeError):
            run(console.goal("rosy_01", 1.0, 0.0))
    assert "rosy_01" not in console._goals
    assert "rosy_01" not in console.goal_leases
    assert "rosy_01" not in console._claims


def test_rejected_bay_goal_does_not_claim_a_successful_yield():
    robot = LeaseRobot("rosy_01")
    console = _console(robot, ttl=4.0)

    async def refuse(*args, **kwargs):
        return {"accepted": False}

    robot.navigation_goal = refuse
    with pytest.raises(RuntimeError):
        run(console._send_to_bay("rosy_01", (1.0, 1.0), "rosy_02"))
    assert "rosy_01" not in console._yielding
    assert "rosy_01" not in console.goal_leases


@pytest.mark.parametrize("stop", ["cancel", "estop"])
def test_a_receipt_after_a_stop_cannot_recreate_a_goal_or_renew_its_lease(stop):
    robot = LeaseRobot("rosy_01")
    console = _console(robot, ttl=4.0)
    console.goal_leases.operator_present()

    async def late_accept(*args, **kwargs):
        if stop == "cancel":
            await console.cancel("rosy_01")
        else:
            await console.estop_all()
        return {"accepted": True}

    robot.navigation_goal = late_accept
    with pytest.raises(RuntimeError):
        run(console.goal("rosy_01", 1.0, 0.0))
    assert "rosy_01" not in console._goals
    assert "rosy_01" not in console.goal_leases
    assert [call for call in robot.calls if call[0] == "navigation_cancel"]
    run(console.goal_leases.renew())
    assert robot.renewals == []


@pytest.mark.parametrize("stop", ["cancel", "estop"])
@pytest.mark.parametrize("phase", ["capabilities", "state", "bay"])
def test_stop_during_admission_prevents_any_later_goal_send(stop, phase):
    robot = LeaseRobot("rosy_01")
    console = _console(robot, ttl=4.0)
    method = "capabilities" if phase == "bay" else phase
    original = getattr(robot, method)

    async def interrupted():
        result = await original()
        if stop == "cancel":
            await console.cancel("rosy_01")
        else:
            await console.estop_all()
        return result

    setattr(robot, method, interrupted)
    with pytest.raises(HubError):
        if phase == "bay":
            run(console._send_to_bay("rosy_01", (1.0, 1.0), "rosy_02"))
        else:
            run(console.goal("rosy_01", 1.0, 0.0))
    assert _sent(robot) == []
    assert "rosy_01" not in console.goal_leases


def test_concurrent_goal_is_refused_until_the_first_goal_pipeline_finishes():
    robot = LeaseRobot("rosy_01")
    console = _console(robot, ttl=4.0)

    async def main():
        entered, release = asyncio.Event(), asyncio.Event()
        original = robot.navigation_goal

        async def blocked(*args, **kwargs):
            if args[0] == 1.0:
                entered.set()
                await release.wait()
            return await original(*args, **kwargs)

        robot.navigation_goal = blocked
        first = asyncio.create_task(console.goal("rosy_01", 1.0, 0.0))
        await entered.wait()
        try:
            with pytest.raises(HubError):
                await console.goal("rosy_01", 2.0, 0.0)
        finally:
            release.set()
            await first
        assert console._goals["rosy_01"]["x"] == 1.0
        assert len(_sent(robot)) == 1

    run(main())


def test_operator_goal_is_leased_and_renewed_while_an_operator_is_present():
    robot, console, _clock = _leased()
    (_, _, _, _, correlation_id, ttl), = _sent(robot)
    assert correlation_id.startswith("fleet-lease-") and ttl == 4.0
    assert console.goal_leases["rosy_01"]["source"] == "operator"
    run(console.goal_leases.renew())
    assert robot.renewals == [(correlation_id, 4.0)]
    assert _goal(console)["goal_lease"] == "leased"


def test_operator_presence_lapses_so_renewal_stops_and_core_expires_it():
    robot, console, clock = _leased()
    clock.advance(3.9)
    run(console.goal_leases.renew())
    assert len(robot.renewals) == 1
    clock.advance(0.2)                       # no presence for longer than the ttl
    run(console.goal_leases.renew())
    assert len(robot.renewals) == 1
    console.goal_leases.operator_present()   # back before CORE expired it: renewed again
    run(console.goal_leases.renew())
    assert len(robot.renewals) == 2


def test_dispatch_goal_is_renewed_only_while_its_attempt_is_open():
    robot, console, _clock = _leased(task_id="t-1", attempt_id="attempt-9", attempt_seq=1)
    assert _sent(robot)[0][4:] == ("attempt-9", 4.0)
    assert console.goal_leases["rosy_01"]["source"] == "dispatch"
    run(console.goal_leases.renew())
    assert robot.renewals == []              # no task store: a dispatch lease is never renewed
    tasks = {"t-1": {"attempt_id": "attempt-9", "status": "RUNNING"}}
    console.goal_leases.attempt_open = partial(attempt_open, SimpleNamespace(get_task=tasks.get))
    run(console.goal_leases.renew())
    assert robot.renewals == [("attempt-9", 4.0)]
    tasks["t-1"]["status"] = "HOLD"          # attempt closed
    run(console.goal_leases.renew())
    tasks["t-1"].update(status="RUNNING", attempt_id="attempt-10")   # a newer attempt
    run(console.goal_leases.renew())
    assert len(robot.renewals) == 1


def test_yield_goal_is_renewed_only_while_the_yield_is_active():
    robot, console, _clock = _leased()
    run(console.goal_leases.send("rosy_01", robot, LEASE_CAPS, 2.0, 0.0, 0.0, None, "yield"))
    run(console.goal_leases.renew())
    assert robot.renewals == []
    console._yielding["rosy_01"] = {"bay": {"x": 2.0, "y": 0.0}, "for": "rosy_02"}
    run(console.goal_leases.renew())
    assert len(robot.renewals) == 1


def test_without_capability_the_goal_is_unbounded():
    robot = LeaseRobot("rosy_01", lease=False)
    console = _console(robot, ttl=4.0)
    console.goal_leases.operator_present()
    run(console.goal("rosy_01", 1.0, 0.0))
    assert _sent(robot) == [("navigation_goal", 1.0, 0.0, 0.0, None, None)]
    run(console.goal_leases.renew())
    assert robot.renewals == [] and _goal(console)["goal_lease"] == "unbounded"


def test_renewal_stops_after_cancel():
    robot, console, _clock = _leased()
    run(console.cancel("rosy_01"))
    run(console.goal_leases.renew())
    assert robot.renewals == [] and _goal(console) is None


def test_internal_route_conflict_cancel_stops_renewal():
    """A goal Fleet cancels itself (ROUTE_CONFLICT) is never renewed; CORE would answer 409."""
    robot, other = LeaseRobot("rosy_01"), FakeRobot("rosy_02")
    console = _console(robot, other, ttl=4.0)
    console.goal_leases.operator_present()
    line = [(0.1 * i, 0.0) for i in range(21)]
    robot._path = line
    console._claims["rosy_02"] = list(line)
    reply = run(console.goal("rosy_01", 2.0, 0.0))
    assert reply["reason"] == "ROUTE_CONFLICT" and ("navigation_cancel",) in robot.calls
    run(console.goal_leases.renew())
    assert robot.renewals == [] and "rosy_01" not in console.goal_leases


def test_view_follows_the_lease_table_not_the_send_time_copy():
    robot, console, _clock = _leased()
    robot.active = None                      # arrived on the robot
    run(console.goal_leases.renew())         # 409: renewal stops
    assert "goal_lease" not in _goal(console)


def test_renewal_survives_a_network_error():
    robot, console, _clock = _leased()

    async def down(correlation_id, ttl_s):
        raise ConnectionError("no route")

    robot.navigation_goal_lease = down
    run(console.goal_leases.renew())         # left to CORE's expiry, not raised
    assert _goal(console)["goal_lease"] == "leased"


def test_estop_stops_every_renewal():
    robot, console, _clock = _leased()
    run(console.estop_all())
    run(console.goal_leases.renew())
    assert robot.renewals == []


def test_trip_goals_are_renewed_by_the_trip_loop_not_the_console_loop():
    robot = LeaseRobot("rosy_01")
    console = _console(robot, ttl=4.0)
    console.goal_leases.operator_present()
    install_trip_guard(console, SimpleNamespace(robot_busy=lambda _robot_id: True))
    run(console.goal("rosy_01", 1.0, 0.0, trip=True))
    run(console.goal_leases.renew("console"))
    assert robot.renewals == []
    run(console.goal_leases.renew("trip", "rosy_01"))
    assert len(robot.renewals) == 1


def test_presence_route_needs_a_named_operator_and_dispatch_check_is_wired(tmp_path):
    from test_trip_runner import OPERATOR, VIEWER, Ports, _app

    client, _tasks, _store, _robot, console = _app(tmp_path, Ports())
    url = "/api/fleet/goal-lease/presence"
    assert client.post(url).status_code in (401, 403)
    assert client.post(url, headers=VIEWER).status_code in (401, 403)
    assert console.goal_leases._present_at is None
    assert client.post(url, headers=OPERATOR).json() == {"present": True}
    assert console.goal_leases._present_at is not None
    assert console.goal_leases.attempt_open is not None


@pytest.mark.parametrize("ttl,started", [(0.0, False), (4.0, True)])
def test_renew_task_runs_only_when_leases_are_on(tmp_path, monkeypatch, ttl, started):
    from test_trip_runner import Ports, _app

    calls = []

    async def loop(console, logger):
        calls.append(console)

    # The loop lives in fleet.server.loop_supervision since the D-766 extraction.
    from fleet.server import loop_supervision

    monkeypatch.setattr(loop_supervision, "goal_lease_renew_loop", loop)
    client, _tasks, _store, _robot, console = _app(tmp_path, Ports())
    console.goal_leases.ttl_s = ttl
    with client:
        pass
    assert bool(calls) is started


@pytest.mark.parametrize("value,expected", [(None, 0.0), (0, 0.0), (3.5, 3.5), (5, 5.0)])
def test_config_key_defaults_off(tmp_path, value, expected):
    path = tmp_path / "site.yaml"
    path.write_text("fleet: {}\n" if value is None else f"fleet: {{goal_lease_ttl_s: {value}}}\n",
                    encoding="utf-8")
    assert cli._goal_lease_ttl_s(SimpleNamespace(site_config=path)) == expected
    assert cli._goal_lease_ttl_s(SimpleNamespace(site_config=None)) == 0.0


@pytest.mark.parametrize("value", [1, 2, 3.4, 6, -1, "true", "yes"])
def test_config_key_below_the_trip_floor_or_out_of_range_exits(tmp_path, value):
    """Floor = 2 x trip port_timeout_s (1.5) + period_s (0.5) = 3.5 s by default."""
    path = tmp_path / "site.yaml"
    path.write_text(f"fleet: {{goal_lease_ttl_s: {value}}}\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        cli._goal_lease_ttl_s(SimpleNamespace(site_config=path))


def test_capability_is_read_from_the_base_velocity_control_only():
    assert goal_lease_supported(LEASE_CAPS)
    for caps in (None, {}, {"controls": {"items": [{"kind": "joint_jog", "goal_lease": True}]}},
                 {"controls": {"items": [{"kind": "base_velocity", "goal_lease": "true"}]}}):
        assert not goal_lease_supported(caps)


class SenderRobot(LeaseRobot):
    """CORE's D-760 9 rule in the fake: only the client (token) that sent the goal renews it."""

    def __init__(self, robot_id: str, core: dict) -> None:
        super().__init__(robot_id)
        self.core = core                     # one robot's CORE state, shared by its clients

    async def navigation_goal(self, x, y, yaw, **options) -> dict:
        self.core["sender"] = self
        return await super().navigation_goal(x, y, yaw, **options)

    async def navigation_goal_lease(self, correlation_id, ttl_s) -> dict:
        self._record("navigation_goal_lease", correlation_id)
        if self.core.get("sender") is not self:
            raise RobotApiError(self.robot_id, 403, "FORBIDDEN", "not the token that sent the goal")
        return await super().navigation_goal_lease(correlation_id, ttl_s)


@pytest.mark.parametrize("source", ["operator", "dispatch", "yield", "trip"])
def test_every_renewal_path_renews_with_the_client_that_sent_the_goal(source):
    """D-760 9: CORE refuses a renewal from another token, so each renewer must use the sender."""
    core = {}
    robot = SenderRobot("rosy_01", core)
    console = _console(robot, ttl=4.0)
    console.goal_leases.operator_present()
    tasks = {"t-1": {"attempt_id": "attempt-9", "status": "RUNNING"}}
    console.goal_leases.attempt_open = partial(attempt_open, SimpleNamespace(get_task=tasks.get))
    if source == "trip":
        install_trip_guard(console, SimpleNamespace(robot_busy=lambda _robot_id: True))
    send = {"operator": lambda: console.goal("rosy_01", 1.0, 0.0),
            "dispatch": lambda: console.goal("rosy_01", 1.0, 0.0, task_id="t-1",
                                             attempt_id="attempt-9", attempt_seq=1),
            "yield": lambda: console._bay_goal("rosy_01", (2.0, 0.0), "rosy_02"),
            "trip": lambda: console.goal("rosy_01", 1.0, 0.0, trip=True)}[source]
    run(send())
    assert console.goal_leases["rosy_01"]["source"] == source and core["sender"] is robot
    renew = partial(console.goal_leases.renew, *(("trip", "rosy_01") if source == "trip" else ("console",)))
    run(renew())
    assert len(robot.renewals) == 1          # accepted: renewed by the sender
    console._clients["rosy_01"] = other = SenderRobot("rosy_01", core)   # another token (control)
    run(renew())
    assert other.renewals == [] and "rosy_01" not in console.goal_leases   # 403 drops the lease
    run(renew())
    assert len(other.calls) == 1             # dropped once: no further renewal attempts
