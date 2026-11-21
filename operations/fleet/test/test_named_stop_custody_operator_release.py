"""An authenticated operator can end a named-stop custody CORE cannot prove stopped; every stale or unsafe ask is refused."""

from __future__ import annotations

import asyncio
import logging
import sqlite3

import pytest
from fastapi.testclient import TestClient

from fakes import FakeRobot
from fleet.routing.cost import RoutingConfig
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.ledger.named_stop_store import NamedStopStore
from fleet.server.named_stop_motion import NamedStopMotion
from fleet.server.site_map_store import SiteMapStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint
from test_named_stop_motion import BOOT, RUN
from test_nudge_step import NAMED, OPERATOR, VIEWER, _users

REASON = "robot is off and standing still"


class Stoppable(FakeRobot):
    journal = None
    cancel_fails = False

    async def navigation_cancel(self):
        assert self.journal.current() is not None, "the stop must go out before the claim is released"
        if self.cancel_fails:
            self._record("navigation_cancel_failed")
            raise TimeoutError("cancel lost on a flaky link")
        return await super().navigation_cancel()

    async def navigation_goal_lease(self, correlation_id, ttl_s):
        self._record("navigation_goal_lease", correlation_id)
        return {}


def build(tmp_path, *, audit_broken=False):
    robot = Stoppable("r1", state={"robot_id": "r1"})
    console = FleetConsole([RobotEndpoint("r1", "http://127.0.0.1:8080", "robot-rest")], [robot])
    maps = SiteMapStore(routing_config=RoutingConfig())
    if audit_broken:
        def broken(*_args):
            raise sqlite3.OperationalError("disk full")

        maps.record_event = broken  # the route captured the bound method at install time
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids={"r1"})
    app = create_app(console, console_token=OPERATOR, task_service=tasks, start_task_dispatcher=False,
                     site_users=_users(), site_maps=maps)
    app.state.ended_trips = ended = []

    async def end(robot_id, reason):
        ended.append((robot_id, reason))

    app.state.trip_runner.cancel_robot = end  # the trip_guard's end_trip reaches it by attribute
    robot.journal = NamedStopStore(tmp_path / "custody.db")
    claim = NamedStopMotion("r1", BOOT, "s3", RUN)
    assert robot.journal.claim(claim)
    console.goal_leases.restore_named_stop(robot.journal)
    return app, robot, console, claim, maps


def release(client, body, token=NAMED, robot="r1"):
    return client.post(f"/api/fleet/robots/{robot}/named-stop-custody/release", json=body,
                       headers={"Authorization": f"Bearer {token}"})


def good(claim):
    return {"reservation_id": claim.reservation_id, "operator_saw_robot_standing_still": True, "reason": REASON}


def test_operator_release_stops_the_robot_first_releases_and_audits(tmp_path, caplog):
    app, robot, console, claim, maps = build(tmp_path)
    view = console.goal_leases.custody_view("r1")
    assert view["reservation_id"] == claim.reservation_id and "release" in view["operator_action"]
    with TestClient(app) as client, caplog.at_level(logging.WARNING, logger="fleet.goal_lease"):
        reply = release(client, good(claim))
    assert reply.status_code == 200, reply.text
    assert reply.json()["stop"] == "ok"
    assert ("navigation_cancel",) in robot.calls and ("r1", "operator_cancel") in app.state.ended_trips
    assert robot.journal.current() is None
    assert "operator kim released it without CORE proof" in caplog.text
    event = maps.events()[0]
    assert event["action"] == "named_stop_custody_release" and event["principal_id"] == "kim"
    assert event["detail"]["reason"] == REASON and event["detail"]["reservation_id"] == claim.reservation_id


@pytest.mark.parametrize("case", ["wrong_reservation", "no_ack", "false_ack", "viewer", "shared_token", "pending"])
def test_operator_release_refusals_keep_the_claim_and_send_nothing(tmp_path, case):
    app, robot, console, claim, maps = build(tmp_path)
    body, token = good(claim), NAMED
    if case == "wrong_reservation":
        body["reservation_id"] = "older-claim"
    if case == "no_ack":
        del body["operator_saw_robot_standing_still"]
    if case == "false_ack":
        body["operator_saw_robot_standing_still"] = False
    if case in ("viewer", "shared_token"):
        token = VIEWER if case == "viewer" else OPERATOR
    if case == "pending":
        console.goal_leases.pending["r1"] = 1
    with TestClient(app) as client:
        reply = release(client, body, token)
    assert reply.status_code in (401, 403, 409, 422), reply.text
    if case == "pending":
        assert reply.json()["detail"]["code"] == "ROBOT_REQUEST_IN_FLIGHT"
    assert robot.journal.current() is not None
    assert not [call for call in robot.calls if call[0] in ("repark_stop", "navigation_cancel")]
    assert app.state.ended_trips == [] and maps.events() == []


def test_failed_cancel_still_stops_lease_renewal_and_ends_the_trip(tmp_path):
    app, robot, console, claim, maps = build(tmp_path)
    robot.cancel_fails = True
    leases = console.goal_leases
    leases["r1"] = {"state": "leased", "correlation_id": "trip-goal", "ttl_s": 5.0, "source": "trip", "task_id": None}
    before = leases.stop_token("r1")
    with TestClient(app) as client:
        reply = release(client, good(claim))
    assert reply.status_code == 200 and reply.json()["stop"].startswith("failed")
    assert robot.journal.current() is None
    assert leases.stop_token("r1") != before and "r1" not in leases
    assert ("r1", "operator_cancel") in app.state.ended_trips  # trip_guard.py guarded_cancel, even though the cancel failed
    asyncio.run(leases.renew("trip", "r1"))
    assert not [call for call in robot.calls if call[0] == "navigation_goal_lease"]


def test_release_is_refused_and_nothing_released_when_the_audit_cannot_be_written(tmp_path):
    app, robot, console, claim, maps = build(tmp_path, audit_broken=True)
    with TestClient(app, raise_server_exceptions=False) as client:
        reply = release(client, good(claim))
    assert reply.status_code == 503 and reply.json()["detail"]["code"] == "AUDIT_UNAVAILABLE"
    assert robot.journal.current() is not None
