"""Regression tests for FleetConsole ``goal_in_flight`` projection and site idle gating."""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys

from fakes import FakeClock, FakeRobot, run
from fastapi.testclient import TestClient
import httpx

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core_common.protocol.localization import LocalizationStatus  # noqa: E402
from core_common.protocol.schemas import DockState, DockingStatus, NavigationState, RobotMode, StateSnapshot  # noqa: E402
from deploy.site.site_update_runtime import _robot_busy_reasons, site_busy_reasons  # noqa: E402
from fleet.server.app import create_app  # noqa: E402
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


def test_state_route_cached_gather_defers_immediately_after_redispatch(tmp_path):
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
    assert run(console.goal("rosy_45", 0.45, 0.22, 0.01))["accepted"] is True

    clock.now = 16.5
    hub_row.snapshot = _terminal_snapshot("rosy_45", NavigationState.CANCELED)
    hub_row.last_heartbeat_monotonic = 16.5

    client = TestClient(create_app(console, console_token="viewer", start_task_dispatcher=False))
    client.app.state.fleet_gather._clock = clock
    headers = {"Authorization": "Bearer viewer"}

    first_res = client.get("/api/fleet/state", headers=headers)
    assert first_res.status_code == 200
    first_body = first_res.json()
    assert first_body["robots"][0]["goal_in_flight"] is False
    assert _robot_busy_reasons(first_body["robots"][0]) == []

    # Re-dispatch identical coordinates while SharedGather's 1.0 s snapshot cache is still hot.
    clock.now = 16.8
    assert run(console.goal("rosy_45", 0.45, 0.22, 0.01))["accepted"] is True

    clock.now = 16.9
    second_res = client.get("/api/fleet/state", headers=headers)
    assert second_res.status_code == 200
    second_body = second_res.json()
    assert second_body["gathered_at"] == first_body["gathered_at"]
    assert second_body["robots"][0]["goal_in_flight"] is True

    token_file = tmp_path / "etc/rosy/site-secrets/site-update-viewer.token"
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text("viewer", encoding="utf-8")

    class _SiteHttp:
        def functional(self, url, ca, tok):
            if url.endswith("/api/fleet/state"):
                return second_body
            if url.endswith("/api/fleet/trips"):
                return {"open": [], "running": None, "trips": []}
            if url.endswith("/api/fleet/dispatch-control"):
                return {"queued_tasks": 0, "unresolved_actions": 0}
            if url.endswith("/api/fleet/formation"):
                return {"active": False, "state": "IDLE"}
            if url.endswith("/api/fleet/pipeline/cell-plans"):
                return {"ok": True, "plans": []}
            raise AssertionError(f"unexpected endpoint: {url}")

    assert site_busy_reasons({"health_url": "https://fleet.local:8443/healthz"}, _SiteHttp(), root=tmp_path) == [
        "rosy_45: goal active"
    ]


def test_state_route_refreshes_goal_in_flight_after_telemetry_await():
    async def scenario():
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
        assert (await console.goal("rosy_45", 0.45, 0.22, 0.01))["accepted"] is True

        clock.now = 16.5
        hub_row.snapshot = _terminal_snapshot("rosy_45", NavigationState.CANCELED)
        hub_row.last_heartbeat_monotonic = 16.5

        app = create_app(console, console_token="viewer", start_task_dispatcher=False)
        app.state.fleet_gather._clock = clock

        entered = asyncio.Event()
        release = asyncio.Event()

        async def paused_shown(robot_id: str, wait_s: float = 0.5):
            entered.set()
            await release.wait()
            return None

        app.state.power_health_display.shown = paused_shown

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as async_client:
            req_task = asyncio.create_task(
                async_client.get("/api/fleet/state", headers={"Authorization": "Bearer viewer"})
            )
            await entered.wait()
            clock.now = 16.8
            assert (await console.goal("rosy_45", 0.45, 0.22, 0.01))["accepted"] is True
            release.set()
            res = await req_task

        assert res.status_code == 200
        row = res.json()["robots"][0]
        assert "_state_mono" not in row
        assert row["goal_in_flight"] is True
        assert _robot_busy_reasons(row) == ["rosy_45: goal active"]

    asyncio.run(scenario())
