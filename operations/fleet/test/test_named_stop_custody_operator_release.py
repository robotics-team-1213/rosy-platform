"""Fail-closed operator release of named-stop custody: CORE stop proof or uncontradicted physical isolation."""

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
from fleet.server.named_stop_motion import NamedStopMotion
from fleet.server.named_stop_store import NamedStopStore
from fleet.server.site_map_store import SiteMapStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint
from test_named_stop_motion import BOOT, RUN
from test_nudge_step import NAMED, OPERATOR, VIEWER, _users

REASON = "robot stopped at S3 after session end"


class Stoppable(FakeRobot):
    journal = None
    cancel_fails = False
    repark_stop_fails = False
    quiescent = True
    advance_zero_sample = True
    sample = 0

    async def navigation_cancel(self):
        assert self.journal.current() is not None, "the stop must go out before the claim is released"
        if self.cancel_fails:
            self._record("navigation_cancel_failed")
            raise TimeoutError("cancel lost on a flaky link")
        return await super().navigation_cancel()

    async def repark_stop(self):
        self._record("repark_stop")
        if self.repark_stop_fails:
            raise TimeoutError("repark stop lost")
        return {"accepted": True, "state": "aborted"}

    async def navigation_goal_lease(self, correlation_id, ttl_s):
        self._record("navigation_goal_lease", correlation_id)
        return {}

    async def _get(self, path: str):
        owner = {"boot_id": BOOT, "owner_generation": 8, "owner_run_id": None}
        op = {
            "kind": "navigate", "boot_id": BOOT, "run_id": RUN, "correlation_id": "s3",
            "phase": "TERMINAL", "result": "CANCELED", "reason": "CANCELED",
        }
        proof = {
            **owner, "requested_run_id": RUN, "transport_generation": 3, "quiescent": self.quiescent,
            "observed_at": "2026-11-20T00:00:00+00:00", "admitting": False,
            "pending_submission": False, "actuating_callback": False, "lease_active": False,
        }
        return {"lookup": "FOUND", "operation": op, "owner": owner, "quiescence": proof}

    async def state(self) -> dict:
        base = await super().state()
        if "mode" in base:
            return base
        if self.advance_zero_sample:
            self.sample += 1
        return {
            **base, "mode": "IDLE", "line_follow": {"mode": "OFF"},
            "velocity": {"linear": 0.0, "angular": 0.0},
            "evidence": {"velocity": {
                "evidence": "fresh",
                "sampled_at": f"2026-11-20T00:00:{self.sample:02d}+00:00",
            }},
        }


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


def good(claim, *, physical_isolation=None):
    body = {"reservation_id": claim.reservation_id, "reason": REASON}
    if physical_isolation is not None:
        body["physical_isolation"] = physical_isolation
    return body


def test_operator_release_stops_first_verifies_core_proof_releases_and_audits(tmp_path, caplog):
    app, robot, console, claim, maps = build(tmp_path)
    view = console.goal_leases.custody_view("r1")
    assert view["reservation_id"] == claim.reservation_id and "release" in view["operator_action"]
    with TestClient(app) as client, caplog.at_level(logging.WARNING, logger="fleet.goal_lease"):
        reply = release(client, good(claim))
    assert reply.status_code == 200, reply.text
    assert reply.json()["stop"] == "ok" and reply.json()["proof"] == "core_stop_proof"
    assert ("navigation_cancel",) in robot.calls and ("r1", "operator_cancel") in app.state.ended_trips
    assert robot.journal.current() is None
    assert "released it (core_stop_proof)" in caplog.text
    event = maps.events()[0]
    assert event["action"] == "named_stop_custody_release" and event["principal_id"] == "kim"
    assert event["detail"]["reason"] == REASON and event["detail"]["proof"] == "core_stop_proof"


@pytest.mark.parametrize("case", [
    "wrong_reservation", "legacy_ack", "false_isolation", "bad_method", "blank_evidence",
    "viewer", "shared_token", "pending",
])
def test_operator_release_refusals_keep_the_claim_and_send_nothing(tmp_path, case):
    app, robot, console, claim, maps = build(tmp_path)
    body, token = good(claim), NAMED
    if case == "wrong_reservation":
        body["reservation_id"] = "older-claim"
    if case == "legacy_ack":
        body["operator_saw_robot_standing_still"] = True
    if case == "false_isolation":
        body["physical_isolation"] = {
            "method": "power_off", "robot_physically_isolated": False, "evidence": "breaker off",
        }
    if case == "bad_method":
        body["physical_isolation"] = {
            "method": "saw_it", "robot_physically_isolated": True, "evidence": "eyeballed it",
        }
    if case == "blank_evidence":
        body["physical_isolation"] = {
            "method": "power_off", "robot_physically_isolated": True, "evidence": "   ",
        }
    if case in ("viewer", "shared_token"):
        token = VIEWER if case == "viewer" else OPERATOR
    if case == "pending":
        console.goal_leases.pending["r1"] = 1
    with TestClient(app) as client:
        reply = release(client, body, token)
    if case in ("legacy_ack", "false_isolation", "bad_method", "blank_evidence"):
        assert reply.status_code == 422, reply.text
    else:
        assert reply.status_code in (401, 403, 409), reply.text
    if case == "pending":
        assert reply.json()["detail"]["code"] == "ROBOT_REQUEST_IN_FLIGHT"
    assert robot.journal.current() is not None
    assert not [call for call in robot.calls if call[0] in ("repark_stop", "navigation_cancel")]
    assert app.state.ended_trips == [] and maps.events() == []


def test_failed_cancel_retains_custody_while_stopping_lease_renewal_and_trip(tmp_path):
    app, robot, console, claim, maps = build(tmp_path)
    robot.cancel_fails = True
    leases = console.goal_leases
    leases["r1"] = {"state": "leased", "correlation_id": "trip-goal", "ttl_s": 5.0, "source": "trip", "task_id": None}
    before = leases.stop_token("r1")
    with TestClient(app) as client:
        reply = release(client, good(claim))
    assert reply.status_code == 409 and reply.json()["detail"]["code"] == "NAMED_STOP_CANCEL_FAILED"
    assert robot.journal.current() is not None
    assert leases.stop_token("r1") != before and "r1" not in leases
    assert ("r1", "operator_cancel") in app.state.ended_trips
    assert maps.events() == []
    asyncio.run(leases.renew("trip", "r1"))
    assert not [call for call in robot.calls if call[0] == "navigation_goal_lease"]


def test_repark_stop_failure_refuses_release_and_still_cancels_navigation(tmp_path):
    app, robot, console, claim, maps = build(tmp_path)
    console.goal_leases._named_stop_motion.repark_correlation_id = f"repark-{claim.reservation_id}"
    robot.repark_stop_fails = True
    with TestClient(app) as client:
        reply = release(client, good(claim))
    assert reply.status_code == 409 and reply.json()["detail"]["code"] == "NAMED_STOP_CANCEL_FAILED"
    names = [call[0] for call in robot.calls]
    assert "repark_stop" in names and "navigation_cancel" in names
    assert robot.journal.current() is not None


def test_release_refuses_when_core_has_not_proved_standstill(tmp_path):
    app, robot, console, claim, maps = build(tmp_path)
    robot.quiescent = False
    with TestClient(app) as client:
        reply = release(client, good(claim))
    assert reply.status_code == 409 and reply.json()["detail"]["code"] == "NAMED_STOP_PROOF_REQUIRED"
    assert ("navigation_cancel",) in robot.calls
    assert robot.journal.current() is not None and maps.events() == []


@pytest.mark.parametrize("method", ["power_off", "removed_from_site", "hardware_estop_latched"])
def test_valid_physical_isolation_releases_and_audits(tmp_path, method):
    app, robot, console, claim, maps = build(tmp_path)
    if method in ("power_off", "removed_from_site"):
        robot.cancel_fails = True
        robot.state_error = TimeoutError("robot offline")
    else:
        robot._state = {
            "robot_id": "r1", "mode": "EMERGENCY", "safety": {"estop": True},
            "line_follow": {"mode": "OFF"}, "velocity": {"linear": 0.0, "angular": 0.0},
            "evidence": {"velocity": {"evidence": "fresh", "sampled_at": "2026-11-20T00:00:05+00:00"}},
        }
    isolation = {"method": method, "robot_physically_isolated": True, "evidence": f"verified {method}"}
    with TestClient(app) as client:
        reply = release(client, good(claim, physical_isolation=isolation))
    assert reply.status_code == 200, reply.text
    assert reply.json()["proof"] == f"physical_isolation:{method}"
    assert robot.journal.current() is None
    event = maps.events()[0]
    assert event["detail"]["proof"] == f"physical_isolation:{method}"
    assert event["detail"]["physical_isolation"] == isolation


@pytest.mark.parametrize("case", ["power_off_online", "removed_online", "estop_false", "estop_wrong_mode", "estop_nonzero_vel"])
def test_contradicted_physical_isolation_refuses_and_retains_custody(tmp_path, case):
    app, robot, console, claim, maps = build(tmp_path)
    method = "removed_from_site" if case == "removed_online" else "power_off" if case == "power_off_online" else "hardware_estop_latched"
    if method == "hardware_estop_latched":
        robot._state = {
            "robot_id": "r1",
            "mode": "IDLE" if case == "estop_wrong_mode" else "EMERGENCY",
            "safety": {"estop": False if case == "estop_false" else True},
            "line_follow": {"mode": "OFF"},
            "velocity": {"linear": 0.1 if case == "estop_nonzero_vel" else 0.0, "angular": 0.0},
            "evidence": {"velocity": {"evidence": "fresh", "sampled_at": "2026-11-20T00:00:05+00:00"}},
        }
    isolation = {"method": method, "robot_physically_isolated": True, "evidence": "checked at bay"}
    with TestClient(app) as client:
        reply = release(client, good(claim, physical_isolation=isolation))
    assert reply.status_code == 409 and reply.json()["detail"]["code"] == "PHYSICAL_ISOLATION_CONTRADICTED"
    assert robot.journal.current() is not None and maps.events() == []


def test_release_is_refused_and_nothing_released_when_the_audit_cannot_be_written(tmp_path):
    app, robot, console, claim, maps = build(tmp_path, audit_broken=True)
    with TestClient(app, raise_server_exceptions=False) as client:
        reply = release(client, good(claim))
    assert reply.status_code == 503 and reply.json()["detail"]["code"] == "AUDIT_UNAVAILABLE"
    assert robot.journal.current() is not None


def test_concurrent_release_keeps_pending_until_finished_and_audits_once(tmp_path):
    app, robot, console, claim, maps = build(tmp_path)
    orig_get = robot._get
    events = {}

    async def slow_get(path: str):
        events["entered"].set()
        await events["gate"].wait()
        return await orig_get(path)

    robot._get = slow_get

    async def run_both():
        from fleet.server.goal_lease import CustodyReleaseRefused

        events["entered"], events["gate"] = asyncio.Event(), asyncio.Event()

        def audit(stop, proof):
            maps.record_event("named_stop_custody_release", "kim", {"stop": stop, "proof": proof})

        first = asyncio.create_task(console.goal_leases.release_by_operator(
            "r1", claim.reservation_id, "kim", REASON, stop=console.cancel, audit=audit))
        await events["entered"].wait()
        assert "r1" in console.goal_leases.pending
        with pytest.raises(CustodyReleaseRefused) as err:
            await console.goal_leases.release_by_operator(
                "r1", claim.reservation_id, "lee", REASON, stop=console.cancel, audit=audit)
        assert err.value.code == "ROBOT_REQUEST_IN_FLIGHT"
        events["gate"].set()
        assert (await first)["released"] is True

    asyncio.run(run_both())
    assert len(maps.events()) == 1 and robot.journal.current() is None


def test_failed_release_still_persists_discovered_run_id(tmp_path):
    app, robot, console, _old, maps = build(tmp_path)
    robot.journal._connect().execute("DELETE FROM named_stop_claim").connection.commit()
    claim = NamedStopMotion("r1", BOOT, "s3")
    assert robot.journal.claim(claim)
    console.goal_leases.restore_named_stop(robot.journal)
    robot.quiescent = False
    with TestClient(app) as client:
        reply = release(client, good(claim))
    assert reply.status_code == 409 and reply.json()["detail"]["code"] == "NAMED_STOP_PROOF_REQUIRED"
    assert robot.journal.current().run_id == RUN and maps.events() == []


@pytest.mark.parametrize("case", ["timeout", "absent", "line_follow_on", "stale_vel", "malformed_safety"])
def test_estop_isolation_fails_closed_when_unconfirmed(tmp_path, case):
    app, robot, console, claim, maps = build(tmp_path)
    if case == "timeout":
        robot.state_error = TimeoutError("status timeout")
    elif case == "absent":
        console._clients.clear()
    elif case == "malformed_safety":
        robot._state = {"robot_id": "r1", "mode": "EMERGENCY", "safety": "bad", "line_follow": {"mode": "OFF"}}
    else:
        robot._state = {
            "robot_id": "r1", "mode": "EMERGENCY", "safety": {"estop": True},
            "line_follow": {"mode": "ON" if case == "line_follow_on" else "OFF"},
            "velocity": {"linear": 0.0, "angular": 0.0},
            "evidence": {"velocity": {"evidence": "stale" if case == "stale_vel" else "fresh",
                                      "sampled_at": "2026-11-20T00:00:05+00:00"}},
        }
    isolation = {"method": "hardware_estop_latched", "robot_physically_isolated": True, "evidence": "estop pushed"}
    with TestClient(app) as client:
        reply = release(client, good(claim, physical_isolation=isolation))
    assert reply.status_code == 409 and reply.json()["detail"]["code"] == "PHYSICAL_ISOLATION_CONTRADICTED"
    assert robot.journal.current() is not None and maps.events() == []


@pytest.mark.parametrize("case", ["stop_ok_state_timeout", "flaky_second_probe_alive"])
def test_power_off_rejects_transient_timeout_after_online_response(tmp_path, case):
    app, robot, console, claim, maps = build(tmp_path)
    if case == "stop_ok_state_timeout":
        robot.state_error = TimeoutError("read timeout")
    else:
        robot.cancel_fails = True
        probes, orig_state = 0, robot.state

        async def flaky_state():
            nonlocal probes
            probes += 1
            if probes == 1:
                raise TimeoutError("first probe dropped")
            return await orig_state()

        robot.state = flaky_state
    isolation = {"method": "power_off", "robot_physically_isolated": True, "evidence": "breaker off"}
    with TestClient(app) as client:
        reply = release(client, good(claim, physical_isolation=isolation))
    assert reply.status_code == 409 and reply.json()["detail"]["code"] == "PHYSICAL_ISOLATION_CONTRADICTED"
    assert robot.journal.current() is not None and maps.events() == []


def test_absent_client_behavior_and_strict_isolation_and_unconfirmed_cancel(tmp_path):
    app, robot, console, claim, maps = build(tmp_path)
    before = console.goal_leases.stop_token("r1")
    console._clients.clear()
    with TestClient(app) as client:
        no_iso = release(client, good(claim))
        int_bool = release(client, good(claim, physical_isolation={
            "method": "power_off", "robot_physically_isolated": 1, "evidence": "breaker off"}))
        with_iso = release(client, good(claim, physical_isolation={
            "method": "power_off", "robot_physically_isolated": True, "evidence": "breaker off"}))
    assert no_iso.status_code == 409 and no_iso.json()["detail"]["code"] == "NAMED_STOP_CANCEL_FAILED"
    assert console.goal_leases.stop_token("r1") != before and ("r1", "operator_cancel") in app.state.ended_trips
    assert int_bool.status_code == 422
    assert with_iso.status_code == 200 and with_iso.json()["stop"] == "absent"

    app2, robot2, _c2, claim2, _m2 = build(tmp_path / "unconfirmed")

    async def unconfirmed():
        return {"canceled": False}

    robot2.navigation_cancel = unconfirmed
    with TestClient(app2) as client2:
        bad = release(client2, good(claim2))
    assert bad.status_code == 409 and bad.json()["detail"]["code"] == "NAMED_STOP_CANCEL_FAILED"
