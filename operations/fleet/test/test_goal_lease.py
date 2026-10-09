"""D-550 10: Fleet sends and renews navigation goal leases (default off, capability gated)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from fakes import FakeClock, FakeRobot, run
from fleet import cli
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


def _console(robot, ttl=0.0) -> FleetConsole:
    endpoint = RobotEndpoint(robot_id=robot.robot_id, base_url="http://127.0.0.1:8080", token="t")
    return FleetConsole([endpoint], [robot], clock=FakeClock(), goal_lease_ttl_s=ttl)


def _sent(robot):
    return [call for call in robot.calls if call[0] == "navigation_goal"]


def _goal(console):
    return run(console.snapshot())["robots"][0]["goal"]


def test_off_by_default_sends_no_lease_and_shows_nothing():
    robot = LeaseRobot("rosy_01")
    console = _console(robot)
    run(console.goal("rosy_01", 1.0, 0.0))
    assert _sent(robot) == [("navigation_goal", 1.0, 0.0, 0.0, None, None)]
    run(console.goal_leases.renew())
    assert robot.renewals == [] and _goal(console) == {"x": 1.0, "y": 0.0, "yaw": 0.0}


def test_with_config_and_capability_the_goal_is_leased_and_renewed():
    robot = LeaseRobot("rosy_01")
    console = _console(robot, ttl=2.0)
    run(console.goal("rosy_01", 1.0, 0.0))
    (_, _, _, _, correlation_id, ttl), = _sent(robot)
    assert correlation_id.startswith("fleet-lease-") and ttl == 2.0
    run(console.goal_leases.renew())
    assert robot.renewals == [(correlation_id, 2.0)]
    assert _goal(console)["goal_lease"] == "leased"


def test_dispatch_attempt_id_is_the_lease_correlation_id():
    robot = LeaseRobot("rosy_01")
    console = _console(robot, ttl=2.0)
    run(console.goal("rosy_01", 1.0, 0.0, task_id="t-1", attempt_id="attempt-9", attempt_seq=1))
    assert _sent(robot)[0][4:] == ("attempt-9", 2.0)
    run(console.goal_leases.renew())
    assert robot.renewals == [("attempt-9", 2.0)]


def test_without_capability_the_goal_is_unbounded():
    robot = LeaseRobot("rosy_01", lease=False)
    console = _console(robot, ttl=2.0)
    run(console.goal("rosy_01", 1.0, 0.0))
    assert _sent(robot) == [("navigation_goal", 1.0, 0.0, 0.0, None, None)]
    run(console.goal_leases.renew())
    assert robot.renewals == [] and _goal(console)["goal_lease"] == "unbounded"


def test_renewal_stops_after_cancel():
    robot = LeaseRobot("rosy_01")
    console = _console(robot, ttl=2.0)
    run(console.goal("rosy_01", 1.0, 0.0))
    run(console.cancel("rosy_01"))
    run(console.goal_leases.renew())
    assert robot.renewals == [] and _goal(console) is None


def test_renewal_stops_once_core_answers_409():
    robot = LeaseRobot("rosy_01")
    console = _console(robot, ttl=2.0)
    run(console.goal("rosy_01", 1.0, 0.0))
    robot.active = None                      # arrived (or expired) on the robot
    run(console.goal_leases.renew())
    run(console.goal_leases.renew())
    assert len(robot.renewals) == 1


def test_renewal_survives_a_network_error():
    robot = LeaseRobot("rosy_01")
    console = _console(robot, ttl=2.0)
    run(console.goal("rosy_01", 1.0, 0.0))

    async def down(correlation_id, ttl_s):
        raise ConnectionError("no route")

    robot.navigation_goal_lease = down
    run(console.goal_leases.renew())         # left to CORE's expiry, not raised
    assert _goal(console)["goal_lease"] == "leased"


def test_estop_stops_every_renewal():
    robot = LeaseRobot("rosy_01")
    console = _console(robot, ttl=2.0)
    run(console.goal("rosy_01", 1.0, 0.0))
    run(console.estop_all())
    run(console.goal_leases.renew())
    assert robot.renewals == []


def test_trip_goals_are_renewed_by_the_trip_loop_not_the_console_loop():
    robot = LeaseRobot("rosy_01")
    console = _console(robot, ttl=2.0)
    install_trip_guard(console, SimpleNamespace(robot_busy=lambda _robot_id: True))
    run(console.goal("rosy_01", 1.0, 0.0, trip=True))
    run(console.goal_leases.renew("console"))
    assert robot.renewals == []
    run(console.goal_leases.renew("trip", "rosy_01"))
    assert len(robot.renewals) == 1


@pytest.mark.parametrize("value,expected", [(None, 0.0), (0, 0.0), (2, 2.0), (5, 5.0)])
def test_config_key_defaults_off(tmp_path, value, expected):
    path = tmp_path / "site.yaml"
    path.write_text("fleet: {}\n" if value is None else f"fleet: {{goal_lease_ttl_s: {value}}}\n",
                    encoding="utf-8")
    assert cli._goal_lease_ttl_s(SimpleNamespace(site_config=path)) == expected
    assert cli._goal_lease_ttl_s(SimpleNamespace(site_config=None)) == 0.0


@pytest.mark.parametrize("value", [1, 6, -1, "true", "yes"])
def test_config_key_out_of_range_exits(tmp_path, value):
    path = tmp_path / "site.yaml"
    path.write_text(f"fleet: {{goal_lease_ttl_s: {value}}}\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        cli._goal_lease_ttl_s(SimpleNamespace(site_config=path))


def test_capability_is_read_from_the_base_velocity_control_only():
    assert goal_lease_supported(LEASE_CAPS)
    for caps in (None, {}, {"controls": {"items": [{"kind": "joint_jog", "goal_lease": True}]}},
                 {"controls": {"items": [{"kind": "base_velocity", "goal_lease": "true"}]}}):
        assert not goal_lease_supported(caps)
