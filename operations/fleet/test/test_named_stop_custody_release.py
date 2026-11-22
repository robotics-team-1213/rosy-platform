"""Named-stop custody always has a way out: an e-stop, a reboot or a removed robot cannot strand the site."""

import asyncio
import logging

import httpx
import pytest

from fleet.server.console import FleetConsole
from fleet.server.named_stop_store import NamedStopStore
from fleet.server.named_stop_motion import NamedStopMotion
from fleet.server.roster import RosterConflict, SiteRoster
from fleet.swarm.api.ports import RobotApiError
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import HttpRobotClient
from test_named_stop_motion import BOOT, RUN
from test_named_stop_repark_completion import PATH as REPARK_PATH, REPARK

NEW_BOOT = "9f0c1d2e-3a4b-4c5d-8e6f-0a1b2c3d4e5f"
NAV = "/api/v1/navigation/state"
RESERVED = "NAMED_STOP_SITE_RESERVED"


class World:
    """One mutable CORE answer: the tests change fields between Fleet's readback cycles."""

    def __init__(self, tmp_path, *, repark, robot="pinky"):
        self.journal = NamedStopStore(tmp_path / "fleet.db")
        claim = NamedStopMotion(robot, BOOT, "s3", RUN)
        assert self.journal.claim(claim) and self.journal.bind_run(claim)
        self.repark_id = f"repark-{claim.reservation_id}"
        if repark:
            assert self.journal.arm_repark(claim, self.repark_id)
        self.mode, self.velocity, self.sample, self.unreachable = "IDLE", 0.0, 0, False
        self.boot, self.owner_run = BOOT, None
        self.operation = dict(kind="repark", boot_id=BOOT, run_id=REPARK, correlation_id=self.repark_id,
                              phase="TERMINAL", result="FAILED", reason="REPARK_STOPPED")
        self.zero_write = None
        self.sent = []

    async def robot(self, request):
        if self.unreachable:
            raise httpx.ConnectError("no route", request=request)
        path = request.url.path
        if request.method == "POST":
            self.sent.append(path)
            return httpx.Response(200, json={})
        owner = dict(boot_id=self.boot, owner_generation=3, owner_run_id=self.owner_run)
        if path == REPARK_PATH and self.boot != BOOT:  # a rebooted CORE has no history for the old re-park
            return httpx.Response(200, json=dict(lookup="UNKNOWN", operation=None, owner=owner, quiescence=None))
        if path == REPARK_PATH:
            return httpx.Response(200, json=dict(lookup="FOUND", operation=self.operation, owner=owner,
                                                 idle_zero_write=self.zero_write))
        if path == NAV:  # a rebooted CORE has no history for the old run
            return httpx.Response(200, json=dict(lookup="UNKNOWN", operation=None, owner=owner, quiescence=None))
        assert path == "/api/v1/robot/state"
        return httpx.Response(200, json={"mode": self.mode, "line_follow": {"mode": "OFF"},
            "velocity": {"linear": self.velocity, "angular": 0.0}, "evidence": {"velocity": {
                "evidence": "fresh", "sampled_at": f"2026-11-20T00:00:{self.sample:02d}+00:00"}}})

    async def renew(self, leases, times=1):
        for _ in range(times):
            self.sample += 1
            await leases.renew()


def exercise(tmp_path, scenario, *, repark=False, robot="pinky"):
    async def run():
        world = World(tmp_path, repark=repark, robot=robot)
        endpoints = [RobotEndpoint(rid, f"http://{rid}", "operator") for rid in ("pinky", "peer")]
        async with httpx.AsyncClient(transport=httpx.MockTransport(world.robot), base_url="http://robot") as http:
            named, peer = [HttpRobotClient(endpoint, http=http) for endpoint in endpoints]
            console = FleetConsole(endpoints, [named, peer])
            leases = console.goal_leases
            leases.restore_named_stop(NamedStopStore(world.journal.path))
            await scenario(world, console, leases, peer)

    asyncio.run(run())


async def refused(peer, path="/api/v1/motion/rotate_to"):
    with pytest.raises(RobotApiError, match=RESERVED):
        await peer._post(path, {})


def test_estop_during_repark_ends_custody_and_its_release_is_never_refused(tmp_path, caplog):
    async def scenario(world, console, leases, peer):
        world.mode = "EMERGENCY"  # the operator pressed the e-stop; CORE ended the run with no idle zero write
        await refused(peer)
        await peer._request("POST", "/api/v1/safety/release")  # the deadlock: custody used to refuse this
        await peer.estop_release_code("test")
        world.mode, world.velocity = "EMERGENCY", 0.2
        await world.renew(leases, 3)
        assert world.journal.current() is not None, "EMERGENCY with measured velocity is not stopped"
        world.velocity = 0.0
        await world.renew(leases)
        assert world.journal.current() is not None, "one zero sample is not two"
        with caplog.at_level(logging.WARNING, logger="fleet.goal_lease"):
            await world.renew(leases)
        assert world.journal.current() is None
        assert "named-stop custody of pinky released" in caplog.text
        await peer._post("/api/v1/motion/rotate_to", {})

    exercise(tmp_path, scenario, repark=True)


def test_a_successful_repark_without_its_idle_zero_write_is_not_released_by_the_estop_rule(tmp_path):
    async def scenario(world, console, leases, peer):
        world.operation["result"], world.operation["reason"], world.mode = "SUCCEEDED", None, "EMERGENCY"
        await world.renew(leases, 4)
        assert world.journal.current() is not None

    exercise(tmp_path, scenario, repark=True)


def test_released_estop_with_a_still_running_repark_owner_stays_held(tmp_path):
    async def scenario(world, console, leases, peer):
        world.owner_run = REPARK
        world.operation["phase"], world.operation["result"], world.operation["reason"] = "RUNNING", None, None
        await world.renew(leases, 4)
        assert world.journal.current() is not None

    exercise(tmp_path, scenario, repark=True)


@pytest.mark.parametrize("repark", [False, True])
def test_reboot_with_proven_standstill_releases_custody(tmp_path, caplog, repark):
    async def scenario(world, console, leases, peer):
        world.boot = NEW_BOOT
        await world.renew(leases)
        await refused(peer)
        with caplog.at_level(logging.WARNING, logger="fleet.goal_lease"):
            await world.renew(leases)
        assert world.journal.current() is None
        assert "new boot_id" in caplog.text

    exercise(tmp_path, scenario, repark=repark)


@pytest.mark.parametrize("repark", [False, True])
@pytest.mark.parametrize("fault", ["velocity", "same_boot", "owner_run", "navigating"])
def test_reboot_without_proven_standstill_keeps_custody(tmp_path, fault, repark):
    async def scenario(world, console, leases, peer):
        world.boot = BOOT if fault == "same_boot" else NEW_BOOT
        if fault == "same_boot" and repark:  # same boot: a stopped re-park would release, so keep it running
            world.owner_run, world.operation["phase"], world.operation["result"] = REPARK, "RUNNING", None
        if fault == "velocity":
            world.velocity = 0.1
        if fault == "owner_run":
            world.owner_run = REPARK
        if fault == "navigating":
            world.mode = "NAVIGATION"
        await world.renew(leases, 4)
        assert world.journal.current() is not None
        await refused(peer)

    exercise(tmp_path, scenario, repark=repark)


def test_roster_refuses_removal_while_custody_is_held_and_allows_it_after_release(tmp_path):
    async def scenario(world, console, leases, peer):
        roster = SiteRoster(console)
        roster.static_ids = frozenset()
        blocker = roster.removal_blockers("pinky")
        assert blocker is not None and blocker.code == "NAMED_STOP_CUSTODY"
        assert roster.removal_blockers("peer") is None
        with pytest.raises(RosterConflict, match="custody"):
            await roster.remove("pinky")
        with pytest.raises(RosterConflict, match="custody"):
            await roster.replace_endpoint(RobotEndpoint("pinky", "http://elsewhere", "operator"), peer)
        assert "pinky" in console.robot_ids and world.journal.current() is not None
        world.boot = NEW_BOOT
        await world.renew(leases, 2)  # CORE proves it stopped, custody ends
        assert world.journal.current() is None
        assert roster.removal_blockers("pinky") is None
        await roster.remove("pinky")
        assert "pinky" not in console.robot_ids

    exercise(tmp_path, scenario)


def test_restored_claim_of_a_robot_without_a_client_stays_held(tmp_path):
    async def scenario(world, console, leases, peer):
        await world.renew(leases, 3)
        assert world.journal.current() is not None
        assert "no client" in leases.custody_view("ghost")["missing_proof"]
        await refused(peer)

    exercise(tmp_path, scenario, robot="ghost")


def test_one_old_boot_sample_plus_one_new_boot_sample_does_not_release(tmp_path):
    async def scenario(world, console, leases, peer):
        world.mode = "EMERGENCY"
        await world.renew(leases)  # old boot: interrupted re-park, first zero sample
        world.boot = NEW_BOOT
        await world.renew(leases)  # first sample under the new boot
        assert world.journal.current() is not None
        await world.renew(leases)  # second sample under the same new boot
        assert world.journal.current() is None

    exercise(tmp_path, scenario, repark=True)


def test_new_boot_samples_too_far_apart_do_not_pair(tmp_path):
    async def scenario(world, console, leases, peer):
        world.boot = NEW_BOOT
        await world.renew(leases)
        world.sample += 20  # the first sample is long stale (core_common STALE_POSE_S)
        await world.renew(leases)
        assert world.journal.current() is not None
        await world.renew(leases)
        assert world.journal.current() is None

    exercise(tmp_path, scenario)


def test_samples_from_two_different_new_boots_do_not_release(tmp_path):
    async def scenario(world, console, leases, peer):
        world.boot = NEW_BOOT
        await world.renew(leases)
        world.boot = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
        await world.renew(leases)
        assert world.journal.current() is not None
        await world.renew(leases)
        assert world.journal.current() is None

    exercise(tmp_path, scenario)


def test_successful_repark_without_its_zero_write_says_so(tmp_path):
    async def scenario(world, console, leases, peer):
        world.operation["result"], world.operation["reason"] = "SUCCEEDED", None
        await world.renew(leases, 2)
        assert "idle zero write" in leases.custody_view("pinky")["missing_proof"]

    exercise(tmp_path, scenario, repark=True)


def test_unreachable_robot_keeps_custody_and_shows_what_is_missing(tmp_path):
    async def scenario(world, console, leases, peer):
        world.unreachable = True
        await world.renew(leases, 4)
        assert world.journal.current() is not None
        await refused(peer)
        view = leases.custody_view("pinky")
        assert "unreachable" in view["missing_proof"] and view["age_s"] >= 0
        assert leases.custody_view("peer") is None
        rows = {row["robot_id"]: row for row in (await console.snapshot())["robots"]}
        assert rows["pinky"]["named_stop_custody"] == view
        assert "named_stop_custody" not in rows["peer"]

    exercise(tmp_path, scenario)
