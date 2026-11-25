"""Regression tests for FleetConsole ``goal_in_flight`` projection and site idle gating."""

from __future__ import annotations

from pathlib import Path
import sys

from fakes import FakeClock, FakeRobot, run

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core_common.protocol.localization import LocalizationStatus  # noqa: E402
from core_common.protocol.schemas import DockState, DockingStatus, NavigationState, RobotMode, StateSnapshot  # noqa: E402
from deploy.site.site_update_runtime import _robot_busy_reasons  # noqa: E402
from fleet.server.console import FleetConsole  # noqa: E402
from fleet.swarm.robots import RobotEndpoint  # noqa: E402


def _terminal_snapshot(robot_id: str, nav: NavigationState = NavigationState.CANCELED) -> StateSnapshot:
    return StateSnapshot(
        robot_id=robot_id,
        mode=RobotMode.IDLE,
        navigation=nav,
        docking=DockingStatus(state=DockState.UNDOCKED),
        localization=LocalizationStatus(state="LOCALIZED", pose_frame="map"),
    )


def test_goal_in_flight_stays_true_across_cached_heartbeat_and_settle_window():
    clock = FakeClock()
    clock.now = 10.0
    robot = FakeRobot("rosy_45")
    console = FleetConsole(
        [RobotEndpoint(robot_id="rosy_45", base_url="http://127.0.0.1:8080", token="t")],
        [robot],
        clock=clock,
        hub_state_max_age_s=3.0,
        goal_lease_ttl_s=0.0,
    )
    hub_row = console.hub.registry.record("rosy_45")
    hub_row.online = True
    hub_row.snapshot = _terminal_snapshot("rosy_45", NavigationState.CANCELED)
    hub_row.last_heartbeat_monotonic = 10.0

    clock.now = 11.0
    accepted = run(console.goal("rosy_45", 0.45, 0.22, 0.01))
    assert accepted["accepted"] is True

    # Codex P1 scenario: immediate snapshot at t=11.5 reuses the t=10.0 cached hub heartbeat
    # (IDLE / CANCELED), yet the newly accepted unleased goal must keep goal_in_flight=True.
    clock.now = 11.5
    row = run(console.snapshot())["robots"][0]
    assert row["goal"] == {"x": 0.45, "y": 0.22, "yaw": 0.01}
    assert row["goal_in_flight"] is True
    assert _robot_busy_reasons(row) == ["rosy_45: goal active"]

    # Fresh heartbeat within settle window (observed - sent_at = 2.0 < 5.0) stays busy.
    clock.now = 13.0
    hub_row.snapshot = _terminal_snapshot("rosy_45", NavigationState.CANCELED)
    hub_row.last_heartbeat_monotonic = 13.0
    row = run(console.snapshot())["robots"][0]
    assert row["goal_in_flight"] is True
    assert _robot_busy_reasons(row) == ["rosy_45: goal active"]

    # After settle window (observed - sent_at = 5.5 >= 5.0) across all terminal nav states.
    for nav_state in (NavigationState.CANCELED, NavigationState.ARRIVED, NavigationState.FAILED):
        clock.now = 16.5
        hub_row.snapshot = _terminal_snapshot("rosy_45", nav_state)
        hub_row.last_heartbeat_monotonic = 16.5
        row = run(console.snapshot())["robots"][0]
        assert row["goal_in_flight"] is False
        assert _robot_busy_reasons(row) == []

    # Re-dispatching the exact same goal coordinates immediately marks goal_in_flight=True again.
    clock.now = 19.0
    hub_row.last_heartbeat_monotonic = 19.0
    clock.now = 20.0
    accepted_again = run(console.goal("rosy_45", 0.45, 0.22, 0.01))
    assert accepted_again["accepted"] is True

    clock.now = 20.5
    row = run(console.snapshot())["robots"][0]
    assert row["goal_in_flight"] is True
    assert _robot_busy_reasons(row) == ["rosy_45: goal active"]

    clock.now = 25.5
    hub_row.snapshot = _terminal_snapshot("rosy_45", NavigationState.ARRIVED)
    hub_row.last_heartbeat_monotonic = 25.5
    row = run(console.snapshot())["robots"][0]
    assert row["goal_in_flight"] is False
    assert _robot_busy_reasons(row) == []
