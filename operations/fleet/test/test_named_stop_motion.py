"""A prepared goal fences peer navigation from POST through exact stopped proof."""

import asyncio
from contextlib import closing
import sqlite3

import httpx
import pytest

from fleet.server.goal_lease import GoalLeases, NavigationStopped
from fleet.server.ledger.named_stop_store import NamedStopStore
from fleet.swarm.api.ports import RobotApiError
from fleet.swarm.dispatch_guard import check_dispatch
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import HttpRobotClient

BOOT = "42ab4cdc-c6d6-4a6f-81ea-25b5714187c1"
RUN = "7716bf89-7ab4-458a-b342-30a1e25d3244"
PLAN = "a1ec4bc9-30c0-48de-a5a5-42440c207e99"
CAPS = {"controls": {"items": [{"kind": "base_velocity", "goal_lease": True}]}}


@pytest.mark.parametrize("outcome", ["accepted", "lost_reply", "malformed_reply", "unproved_refusal"])
@pytest.mark.parametrize("restart", [False, True])
def test_named_stop_claim_survives_until_proved_stopped(outcome, restart, tmp_path):
    async def exercise():
        dispatched, reply = asyncio.Event(), asyncio.Event()
        sent = []
        operation = dict(boot_id=BOOT, run_id=RUN, kind="navigate", correlation_id="s3", phase="SUBMITTED",
                         result=None, reason=None)
        stopped = False
        fresh = False
        foreign = True
        post_terminal = 0

        class Named:
            async def navigation_goal(self, *_args, **kwargs):
                assert kwargs["plan_id"] == PLAN
                assert kwargs["lease_ttl_s"] == 5.0
                check_dispatch(path="/api/v1/navigation/bound-goal")
                if restart:
                    assert journal.current().correlation_id == "s3"
                dispatched.set()
                await reply.wait()
                if outcome == "lost_reply":
                    raise TimeoutError("reply lost")
                if outcome == "unproved_refusal":
                    return {"accepted": False}
                return {"accepted": True, "operation": operation if outcome == "accepted" else {}}

            async def state(self):
                return {"mode": "IDLE", "line_follow": {"mode": "OFF"},
                        "velocity": {"linear": 0, "angular": 0},
                        "evidence": {"velocity": {"evidence": "fresh" if fresh else "stale",
                                                  "received_at": "2026-11-20T00:00:03+00:00",
                                                  "sampled_at": (f"2026-11-20T00:00:0{post_terminal}+00:00" if post_terminal
                                                                 else "2026-11-19T23:59:59+00:00")}}}

            async def _get(self, path):
                latest = {**operation, "correlation_id": "other" if foreign else "s3"}
                if stopped:
                    latest.update(phase="TERMINAL", result="SUCCEEDED")
                return {"operation": latest, "lookup": "FOUND",
                        "owner": {"boot_id": BOOT, "owner_run_id": None, "owner_generation": 10},
                        "quiescence": {"boot_id": BOOT, "owner_run_id": None, "owner_generation": 10,
                                       "requested_run_id": RUN, "transport_generation": 3, "quiescent": stopped,
                                       "observed_at": "2026-11-20T00:00:00+00:00", "admitting": False,
                                       "pending_submission": False, "actuating_callback": False, "lease_active": False}}

            async def navigation_cancel(self):
                sent.append("stop")
                return {"accepted": True}

        class Peer:
            async def navigation_goal(self, *_args, **_kwargs):
                check_dispatch(path="/api/v1/navigation/goal")
                sent.append("peer")
                return {"accepted": True}

        named, peer = Named(), Peer()
        clients = {"pinky": named, "peer": peer}
        leases = GoalLeases(0, clients)
        if restart:
            journal = NamedStopStore(tmp_path / "fleet.db")
            leases.restore_named_stop(journal)
        request = asyncio.create_task(leases.send(
            "pinky", named, CAPS, 0.5, 0.0, 0.0, "s3", expected_map_grid_id="grid",
            owner_epoch={"expected_boot_id": BOOT, "expected_owner_generation": 8}, plan_id=PLAN))
        await asyncio.wait_for(dispatched.wait(), 1)
        with pytest.raises(NavigationStopped):
            await leases.send("peer", peer, {}, 0, 0, 0, None, "yield")
        reply.set()
        if outcome == "accepted":
            assert (await request)["accepted"]
        else:
            with pytest.raises((ValueError, TimeoutError, RuntimeError)):
                await request

        if restart:
            assert journal.current().run_id == (RUN if outcome == "accepted" else None)
            leases = GoalLeases(0, clients)
            leases.restore_named_stop(NamedStopStore(journal.path))
            with pytest.raises(NavigationStopped):
                await leases.send("peer", peer, {}, 0, 0, 0, None)
        # Transport ambiguity outlives an HTTP cancel acknowledgement and the lease table.
        await leases.cancel("pinky", named)
        leases.clear()
        for stopped, fresh in [(False, True), (True, False), (True, True)]:
            await leases.renew()
            with pytest.raises(NavigationStopped):
                await leases.send("peer", peer, {}, 0, 0, 0, None)
        assert sent == ["stop"]
        foreign = False
        await leases.renew()
        with pytest.raises(NavigationStopped):
            await leases.send("peer", peer, {}, 0, 0, 0, None)
        if restart:
            # The exact recovered run survives a second restart before terminal velocity samples.
            assert journal.current().run_id == RUN
            leases = GoalLeases(0, clients)
            leases.restore_named_stop(NamedStopStore(journal.path))
        post_terminal = 1
        for _ in range(2):
            await leases.renew()
            with pytest.raises(NavigationStopped):
                await leases.send("peer", peer, {}, 0, 0, 0, None)
        post_terminal = 2
        if restart:
            with closing(sqlite3.connect(journal.path)) as writer:
                writer.execute("BEGIN IMMEDIATE")
                await leases.renew()
                assert journal.current().run_id == RUN
                with pytest.raises(NavigationStopped):
                    await leases.send("peer", peer, {}, 0, 0, 0, None)
        await leases.renew()
        assert (await leases.send("peer", peer, {}, 0, 0, 0, None))["accepted"]
        assert sent == ["stop", "peer"]
        if restart:
            assert journal.current() is None

    asyncio.run(exercise())


def test_only_explicit_no_admission_refusal_releases_a_send_without_a_run():
    async def exercise():
        class Named:
            async def navigation_goal(self, *_args, **_kwargs):
                check_dispatch(path="/api/v1/navigation/bound-goal")
                raise RobotApiError("pinky", 409, "NAVIGATION_PLAN_CHANGED", "expired",
                                    {"plan_id": PLAN, "native_admitted": False})

        named = Named()
        leases = GoalLeases(0, {"pinky": named})
        with pytest.raises(RobotApiError):
            await leases.send(
                "pinky", named, CAPS, 0.5, 0.0, 0.0, "s3", expected_map_grid_id="grid",
                owner_epoch={"expected_boot_id": BOOT, "expected_owner_generation": 8}, plan_id=PLAN)
        leases.check_motion()

    asyncio.run(exercise())


@pytest.mark.parametrize("lost_path", [None, "/api/v1/line-follow/stuck/decision"])
def test_roster_transport_fences_other_starts_and_keeps_stops_available(lost_path):
    from fleet.hub.hub import HubError
    from fleet.server.console import FleetConsole

    async def exercise():
        sent = []
        starting = asyncio.Event()
        finish = asyncio.Event()
        operation = dict(boot_id=BOOT, run_id=RUN, kind="navigate", correlation_id="s3", phase="SUBMITTED")

        async def robot(request):
            path = request.url.path
            sent.append(path)
            if path == "/api/v1/motion/rotate_to":
                starting.set()
                await finish.wait()
            if path == lost_path:
                raise httpx.ReadTimeout("lost response", request=request)
            return httpx.Response(200, json={"accepted": True, "operation": operation})

        endpoints = [RobotEndpoint(rid, f"http://{rid}:8080", "operator") for rid in ("pinky", "peer")]
        async with httpx.AsyncClient(transport=httpx.MockTransport(robot), base_url="http://robot") as http:
            named, peer = [HttpRobotClient(endpoint, http=http) for endpoint in endpoints]
            console = FleetConsole(endpoints, [named, peer])
            leases = console.goal_leases
            resolver = HttpRobotClient(RobotEndpoint("peer", "http://peer:8080", "resolver"), http=http)
            console.bind_robot_motion(resolver)

            async def start_named():
                return await leases.send("pinky", named, CAPS, 0.5, 0.0, 0.0, "s3",
                                         expected_map_grid_id="grid", plan_id=PLAN,
                                         owner_epoch={"expected_boot_id": BOOT, "expected_owner_generation": 8})

            with pytest.raises(RobotApiError, match="NAMED_STOP_SITE_RESERVED"):
                await named.navigation_goal(0.5, 0.0, 0.0, correlation_id="s3",
                                            expected_map_grid_id="grid", plan_id=PLAN)
            rotate = asyncio.create_task(peer.rotate_to(20.0, "operator"))
            await asyncio.wait_for(starting.wait(), 1)
            with pytest.raises(NavigationStopped):
                await start_named()
            assert sent == ["/api/v1/motion/rotate_to"]
            finish.set()
            await rotate
            if lost_path is not None:
                with pytest.raises(httpx.ReadTimeout):
                    await resolver._request("POST", lost_path, {"decision": "BACK_AND_RETRY", "code": "test"})
                await peer._request("POST", "/api/v1/safety/stop")
                with pytest.raises(NavigationStopped, match="no confirmed outcome"):
                    await start_named()
                assert "/api/v1/navigation/bound-goal" not in sent
                return
            assert (await start_named())["accepted"]
            with pytest.raises(RobotApiError, match="NAMED_STOP_SITE_RESERVED"):
                await resolver._request("POST", "/api/v1/line-follow/stuck/decision", {"decision": "BACK_AND_RETRY"})
            with pytest.raises(HubError, match="site navigation reservation"):
                await console.formation_start("peer")
            with pytest.raises(RobotApiError, match="NAMED_STOP_SITE_RESERVED"):
                await peer.localization_mission("nudge_forward", max_distance_m=0.1, max_time_s=1.0)

            for path, body, method in [
                ("/api/v1/line-follow/mode", {"mode": "CAMERA_LINE"}, "PUT"),
                ("/api/v1/line-follow/junction", {}, "POST"),
                ("/api/v1/swarm/follow", {}, "POST"),
                ("/api/v1/motion/repark/run", {}, "POST"),
                ("/api/v1/docking/station-undock", {}, "POST"),
                ("/api/v1/docking/station-departure", {}, "PUT"),
                ("/api/v1/teleop", {"linear": 0.1, "angular": 0}, "POST"),
            ]:
                with pytest.raises(RobotApiError, match="NAMED_STOP_SITE_RESERVED"):
                    await peer._request(method, path, body)
            assert sent == ["/api/v1/motion/rotate_to", "/api/v1/navigation/bound-goal"]
            await peer.line_follow_mode("OFF")
            await peer._request("POST", "/api/v1/safety/stop")
            await peer._request("POST", "/api/v1/teleop", {"linear": 0, "angular": 0})
            assert sent[-3:] == ["/api/v1/line-follow/mode", "/api/v1/safety/stop", "/api/v1/teleop"]
            # CORE's release only moves EMERGENCY to IDLE and resumes nothing, so custody never blocks it.
            await peer.estop_release_code("test")
            await peer._request("POST", "/api/v1/safety/release")
            assert sent[-2:] == ["/api/v1/safety/release-code", "/api/v1/safety/release"]
            await named.navigation_goal_lease("s3", 5.0)
            with pytest.raises(RobotApiError, match="NAMED_STOP_SITE_RESERVED"):
                await peer.navigation_goal_lease("old", 5.0)

    asyncio.run(exercise())


def test_named_stop_fails_closed_when_site_journal_cannot_commit(tmp_path):
    async def exercise():
        class Named:
            async def navigation_goal(self, *_args, **_kwargs):
                check_dispatch(path="/api/v1/navigation/bound-goal")
                pytest.fail("motion dispatched before reservation could commit")

        named = Named()
        leases = GoalLeases(0, {"pinky": named})
        journal = NamedStopStore(tmp_path / "fleet.db")
        leases.restore_named_stop(journal)
        with closing(sqlite3.connect(journal.path)) as writer:
            writer.execute("BEGIN IMMEDIATE")
            with pytest.raises(NavigationStopped, match="could not be durably stored"):
                await leases.send("pinky", named, CAPS, 0.5, 0.0, 0.0, "s3",
                                  expected_map_grid_id="grid", plan_id=PLAN,
                                  owner_epoch={"expected_boot_id": BOOT, "expected_owner_generation": 8})
        assert journal.current() is None

    asyncio.run(exercise())


def test_persisted_release_requires_the_current_reservation_id(tmp_path):
    from fleet.server.named_stop_motion import NamedStopMotion

    journal = NamedStopStore(tmp_path / "fleet.db")
    first = NamedStopMotion("pinky", BOOT, "s3")
    replacement = NamedStopMotion("pinky", BOOT, "s3")
    assert journal.claim(first)
    assert not journal.claim(replacement)
    assert journal.release(first)
    assert journal.claim(replacement)
    assert not journal.release(first)
    assert journal.current().reservation_id == replacement.reservation_id


def test_fleet_app_restores_site_journal_before_dispatch(tmp_path):
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.server.named_stop_motion import NamedStopMotion
    from fleet.server.sitemap.site_map_store import SiteMapStore

    site_maps = SiteMapStore(tmp_path / "site-fleet.db")
    try:
        motion = NamedStopMotion("pinky", BOOT, "s3")
        assert NamedStopStore(site_maps.path).claim(motion)
        console = FleetConsole([], [])
        create_app(console, site_maps=site_maps)
        with pytest.raises(NavigationStopped, match="holds the site navigation reservation"):
            console.goal_leases.check_motion()
    finally:
        site_maps.close()
