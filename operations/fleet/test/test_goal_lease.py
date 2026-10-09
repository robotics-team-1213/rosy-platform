"""D-550 10: Fleet sends and renews navigation goal leases (default off, capability gated).

Each goal source renews only while its reason to move holds (Safety-Review 2026-10-09)."""

from __future__ import annotations

from functools import partial
from types import SimpleNamespace

import pytest

from fakes import FakeClock, FakeRobot, run
from fleet import cli
from fleet.server import app as fleet_app
from fleet.server.background_workers import attempt_open
from fleet.server.console import FleetConsole
from fleet.server.goal_lease import goal_lease_supported
from fleet.server.trip_guard import install_trip_guard
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import RobotApiError

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

    monkeypatch.setattr(fleet_app, "goal_lease_renew_loop", loop)
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
