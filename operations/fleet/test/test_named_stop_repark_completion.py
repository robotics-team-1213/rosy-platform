"""The scoped repark shares the actual Fleet wire gate and restart custody."""

import asyncio
from contextlib import closing
import sqlite3

import httpx
import pytest

from fleet.server.console import FleetConsole
from fleet.server.goal_lease import NavigationStopped
from fleet.server.named_stop_store import NamedStopStore
from fleet.server.named_stop_motion import NamedStopMotion
from fleet.swarm.api.ports import RobotApiError
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import HttpRobotClient
from test_named_stop_motion import BOOT, RUN


REPARK = "b651061a-8f6c-4d70-ae58-b6d081a357af"
PATH = "/api/v1/motion/repark/run"


@pytest.mark.parametrize("lost_reply", [False, True])
def test_exact_repark_prevents_release_until_two_post_write_samples(tmp_path, lost_reply):
    async def exercise():
        journal = NamedStopStore(tmp_path / "fleet.db")
        claim = NamedStopMotion("pinky", BOOT, "s3", RUN)
        assert journal.claim(claim) and journal.bind_run(claim)
        operation = dict(kind="repark", boot_id=BOOT, run_id=REPARK,
                         correlation_id=f"repark-{claim.reservation_id}", phase="RUNNING")
        owner = dict(boot_id=BOOT, owner_generation=7, owner_run_id=REPARK)
        stamp = "2026-11-20T00:00:04+00:00"
        pose_stamp = "2026-11-20T00:00:07+00:00"
        pose_frame = "map"
        witness = None
        fresh = True
        swap_witness_after_state = False
        posts = []

        async def robot(request):
            nonlocal witness
            if request.method == "POST":
                posts.append(request.url.path)
                if request.url.path == PATH:
                    assert journal.current().repark_correlation_id == operation["correlation_id"]
                    if lost_reply:
                        raise httpx.ReadTimeout("reply lost", request=request)
                return httpx.Response(200, json={"operation": operation})
            if request.url.path == PATH:
                assert request.url.params["correlation_id"] == operation["correlation_id"]
                return httpx.Response(200, json=dict(lookup="FOUND", operation=operation, owner=owner,
                                                     idle_zero_write=witness))
            assert request.url.path == "/api/v1/robot/state"
            if swap_witness_after_state:
                witness = {**witness, "mode_epoch": witness["mode_epoch"] + 1}
            return httpx.Response(200, json={"mode": "IDLE", "line_follow": {"mode": "OFF"},
                "velocity": {"linear": 0.0, "angular": 0.0}, "evidence": {"velocity": {
                    "sampled_at": stamp, "evidence": "fresh" if fresh else "stale"},
                    "pose": {"evidence": "fresh", "received_at": pose_stamp}},
                "pose_frame": pose_frame, "localization": {"pose_frame": "map"}})

        endpoints = [RobotEndpoint(rid, f"http://{rid}", "operator") for rid in ("pinky", "peer")]
        async with httpx.AsyncClient(transport=httpx.MockTransport(robot), base_url="http://robot") as http:
            def start_fleet():
                named, peer = [HttpRobotClient(endpoint, http=http) for endpoint in endpoints]
                console = FleetConsole(endpoints, [named, peer])
                console.goal_leases.restore_named_stop(NamedStopStore(journal.path))
                return console.goal_leases, named, peer

            leases, named, peer = start_fleet()
            body = dict(expected_boot_id=BOOT, expected_nav_run_id=RUN, expected_nav_correlation_id="s3")
            with pytest.raises(NavigationStopped, match="admission changed"):
                await leases.send_named_repark("pinky", named, body, ready=lambda: False)
            assert journal.current().repark_correlation_id is None
            with pytest.raises(RobotApiError, match="NAMED_STOP_SITE_RESERVED"):
                await named._post(PATH, body)
            if lost_reply:
                with pytest.raises(httpx.ReadTimeout):
                    await leases.send_named_repark("pinky", named, body, ready=lambda: True)
            else:
                await leases.send_named_repark("pinky", named, body, ready=lambda: True)
            assert not journal.release(claim), "a pre-correction snapshot cannot release new custody"
            leases, named, peer = start_fleet()
            with pytest.raises(NavigationStopped, match="required for repark"):
                await leases.send_named_repark("pinky", named, body, ready=lambda: True)
            await leases.renew()
            assert journal.current().repark_run_id == REPARK
            leases, named, peer = start_fleet()
            operation.update(phase="TERMINAL", result="SUCCEEDED")
            owner["owner_run_id"] = None

            async def stays_held():
                await leases.renew()
                with pytest.raises(RobotApiError, match="NAMED_STOP_SITE_RESERVED"):
                    await peer._post("/api/v1/motion/rotate_to", {})
                assert journal.current() is not None

            await stays_held()  # terminal result alone
            witness = dict(run_id=REPARK, mode_epoch=11, observed_at="2026-11-20T00:00:05+00:00")
            await stays_held()  # current sample is older than zero publication
            stamp = "2026-11-20T00:00:06+00:00"
            owner["boot_id"] = REPARK
            await stays_held()
            owner["boot_id"] = BOOT
            fresh = False
            await stays_held()
            fresh = True
            await stays_held()
            await stays_held()  # duplicate encoder sample
            stamp = "2026-11-20T00:00:07+00:00"
            swap_witness_after_state = True
            await stays_held()  # changed during the final CORE recheck
            swap_witness_after_state = False
            await stays_held()  # establish first observation for the new stable proof
            stamp = "2026-11-20T00:00:08+00:00"
            await leases.renew()
            assert journal.current() is None
            nav = dict(boot_id=BOOT, run_id=RUN, correlation_id="s3")
            leases, named, peer = start_fleet()
            receipt = journal.repark_completion("pinky", nav)
            assert receipt["operation"]["run_id"] == REPARK
            assert receipt["navigation"] == {"boot_id": BOOT, "run_id": RUN, "correlation_id": nav["correlation_id"]}
            assert receipt["velocity_samples"] == ["2026-11-20T00:00:07+00:00", "2026-11-20T00:00:08+00:00"]
            assert not await leases.confirm_named_precision("pinky", nav, ready=lambda _: True)
            stamp = "2026-11-20T00:00:09+00:00"
            assert not await leases.confirm_named_precision("pinky", nav, ready=lambda _: True)
            pose_stamp = "2026-11-20T00:00:09+00:00"
            for pose_frame in ("odom", None):
                assert not await leases.confirm_named_precision("pinky", nav, ready=lambda _: True)
            pose_frame = "map"
            assert not await leases.confirm_named_precision("pinky", nav, ready=lambda _: False)
            assert await leases.confirm_named_precision("pinky", nav, ready=lambda _: True) == receipt
            swap_witness_after_state = True
            assert not await leases.confirm_named_precision("pinky", nav, ready=lambda _: True)
            assert not await leases.confirm_named_precision("pinky", {**nav, "run_id": REPARK}, ready=lambda _: True)
            await peer._post("/api/v1/motion/rotate_to", {})
            assert posts == [PATH, "/api/v1/motion/rotate_to"]

    asyncio.run(exercise())


def test_migration_preserves_an_in_flight_navigation_row(tmp_path):
    path = tmp_path / "fleet.db"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("""CREATE TABLE named_stop_claim (
            slot INTEGER PRIMARY KEY, reservation_id TEXT NOT NULL, robot_id TEXT NOT NULL,
            boot_id TEXT NOT NULL, correlation_id TEXT NOT NULL, run_id TEXT)""")
        connection.execute("INSERT INTO named_stop_claim VALUES (1, 'original', 'pinky', ?, 's3', ?)", (BOOT, RUN))
    motion = NamedStopStore(path).current()
    assert motion.reservation_id == "original" and motion.run_id == RUN and motion.repark_correlation_id is None


@pytest.mark.parametrize("result", ["SUCCEEDED", "CANCELED"])
def test_commissioned_stop_keeps_claim_after_nav2_stops_until_aligned(tmp_path, result):
    async def exercise():
        journal = NamedStopStore(tmp_path / "site.db")
        motion = NamedStopMotion("pinky", BOOT, "s3", RUN, precision_required=True)
        assert journal.claim(motion) and journal.bind_run(motion)
        assert journal.current().precision_required
        operation = dict(kind="navigate", boot_id=BOOT, run_id=RUN, correlation_id="s3",
                         phase="TERMINAL", result=result, reason=None if result == "SUCCEEDED" else "CANCELED")
        owner = dict(boot_id=BOOT, owner_generation=8, owner_run_id=None)
        sample = pose_sample = 1
        pose_frame = "map"

        async def robot(request):
            if request.url.path == "/api/v1/navigation/state":
                assert request.url.params["run_id"] == RUN
                proof = dict(**owner, requested_run_id=RUN, transport_generation=3, quiescent=True,
                             observed_at="2026-11-20T00:00:00+00:00", admitting=False,
                             pending_submission=False, actuating_callback=False, lease_active=False)
                return httpx.Response(200, json=dict(lookup="FOUND", operation=operation, owner=owner, quiescence=proof))
            assert request.url.path == "/api/v1/robot/state"
            return httpx.Response(200, json=dict(mode="IDLE", line_follow={"mode": "OFF"},
                pose_frame=pose_frame, localization={"pose_frame": "map"}, velocity={"linear": 0., "angular": 0.},
                evidence={"velocity": {"evidence": "fresh", "sampled_at": f"2026-11-20T00:00:0{sample}+00:00"},
                          "pose": {"evidence": "fresh", "received_at": f"2026-11-20T00:00:0{pose_sample}+00:00"}}))

        endpoint = RobotEndpoint("pinky", "http://pinky", "operator")
        async with httpx.AsyncClient(transport=httpx.MockTransport(robot), base_url="http://pinky") as http:
            named = HttpRobotClient(endpoint, http=http)
            console = FleetConsole([endpoint], [named])
            leases = console.goal_leases
            leases.restore_named_stop(NamedStopStore(journal.path))
            await leases.renew()
            sample = 2
            await leases.renew()
            if result == "CANCELED":
                assert journal.current() is None
                return
            with pytest.raises(NavigationStopped):
                leases.check_motion()
            assert journal.current().run_id == RUN
            assert not await leases.confirm_named_precision("pinky", operation, ready=lambda *_: False)
            assert journal.current().run_id == RUN
            sample = 3
            assert not await leases.confirm_named_precision("pinky", operation, ready=lambda *_: True)
            pose_sample, pose_frame = 3, "odom"
            assert not await leases.confirm_named_precision("pinky", operation, ready=lambda *_: True)
            pose_frame = "map"
            assert await leases.confirm_named_precision("pinky", operation, ready=lambda *_: True)
            assert journal.current() is None

    asyncio.run(exercise())


def test_cancel_stops_an_armed_named_stop_repark(tmp_path):
    async def exercise():
        calls = []

        async def robot(request):
            calls.append((request.method, request.url.path))
            return httpx.Response(200, json={"state": "aborted", "accepted": True})

        endpoints = [RobotEndpoint("pinky", "http://pinky", "operator")]
        async with httpx.AsyncClient(transport=httpx.MockTransport(robot), base_url="http://robot") as http:
            named = HttpRobotClient(endpoints[0], http=http)
            leases = FleetConsole(endpoints, [named]).goal_leases
            journal = NamedStopStore(tmp_path / "fleet.db")
            claim = NamedStopMotion("pinky", BOOT, "s3", RUN)
            assert journal.claim(claim) and journal.bind_run(claim)
            leases.restore_named_stop(NamedStopStore(journal.path))
            leases._named_stop_motion.repark_correlation_id = f"repark-{claim.reservation_id}"
            await leases.cancel("pinky", named)
        assert ("DELETE", "/api/v1/motion/repark") in calls
        assert calls.index(("DELETE", "/api/v1/motion/repark")) < len(calls) - 1  # before the Nav2 cancel

    asyncio.run(exercise())


def test_cancel_propagates_repark_stop_failure_after_canceling_navigation(tmp_path):
    async def exercise():
        calls = []

        async def robot(request):
            calls.append((request.method, request.url.path))
            if request.url.path == "/api/v1/motion/repark":
                raise httpx.ConnectError("repark stop timeout", request=request)
            return httpx.Response(200, json={"canceled": True})

        endpoints = [RobotEndpoint("pinky", "http://pinky", "operator")]
        async with httpx.AsyncClient(transport=httpx.MockTransport(robot), base_url="http://robot") as http:
            named = HttpRobotClient(endpoints[0], http=http)
            leases = FleetConsole(endpoints, [named]).goal_leases
            journal = NamedStopStore(tmp_path / "fleet.db")
            claim = NamedStopMotion("pinky", BOOT, "s3", RUN)
            assert journal.claim(claim) and journal.bind_run(claim)
            leases.restore_named_stop(NamedStopStore(journal.path))
            leases._named_stop_motion.repark_correlation_id = f"repark-{claim.reservation_id}"
            with pytest.raises(httpx.ConnectError):
                await leases.cancel("pinky", named)
        assert ("DELETE", "/api/v1/motion/repark") in calls
        assert ("POST", "/api/v1/navigation/cancel") in calls

    asyncio.run(exercise())
