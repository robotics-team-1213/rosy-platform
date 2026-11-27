"""Unresolved motion needs later CORE proof; time and cached observations cannot clear it."""

import asyncio
from datetime import datetime, timezone

import pytest

from fakes import FakeClock, run
from fleet.server.goal_lease import GoalLeases, NavigationStopped
from fleet.server.named_stop_motion import NamedStopMotion
from fleet.swarm.dispatch_guard import check_dispatch

BOOT = "42ab4cdc-c6d6-4a6f-81ea-25b5714187c1"
RUN = "7716bf89-7ab4-458a-b342-30a1e25d3244"
CAPS = {"controls": {"items": [{"kind": "base_velocity", "goal_lease": True}]}}


def uncertain(leases, robot="r", admit_within_s=3.0, *, boot_id=BOOT, owner_generation=1):
    body = {}
    if admit_within_s is not None:
        body["admit_within_s"] = admit_within_s
    if boot_id is not None:
        body["expected_boot_id"] = boot_id
    if owner_generation is not None:
        body["expected_owner_generation"] = owner_generation
    with leases.motion_wire(robot, "POST", "/api/v1/navigation/goal", body) as unresolved:
        unresolved()


def setup(monkeypatch):
    mono, wall = FakeClock(), FakeClock()
    wall.now = 1800000000.0
    monkeypatch.setattr("fleet.server.goal_lease.time.time", wall)
    leases = GoalLeases(0, {}, clock=mono)
    return leases, mono, wall


def state(wall, **updates):
    return {"robot_id": "r", "mode": "IDLE", "navigation": "IDLE",
            "line_follow": {"mode": "OFF"}, "velocity": {"linear": 0., "angular": 0.},
            "evidence": {"velocity": {"evidence": "fresh", "sampled_at":
                                      datetime.fromtimestamp(wall(), timezone.utc).isoformat()}}, **updates}


class Robot:
    def __init__(self, wall):
        self.wall = wall
        self.boot_id = BOOT
        self.owner_generation = 1
        self.reply = {"navigation": "CANCELED", "operation": None}
        self.updates = {}

    async def _get(self, path):
        if path.split("?", 1)[0] == "/api/v1/navigation/state":
            return {"navigation": self.updates.get("navigation", "IDLE"),
                    "owner": {"boot_id": self.boot_id, "owner_run_id": None,
                              "owner_generation": self.owner_generation}}
        raise AssertionError(f"unexpected GET {path}")

    async def state(self):
        self.wall.advance(.25)  # Binary-exact wall time survives ISO microsecond round trips.
        return state(self.wall, **self.updates)

    async def navigation_cancel(self, *, advance_generation=False):
        if advance_generation:
            self.owner_generation += 1
            return {**self.reply, "owner": {"boot_id": self.boot_id, "owner_run_id": None,
                                            "owner_generation": self.owner_generation}}
        return self.reply

    async def navigation_goal(self, *_args, **_kwargs):
        check_dispatch(path="/api/v1/navigation/bound-goal")
        return {"accepted": True, "operation": {"boot_id": BOOT, "run_id": RUN, "kind": "navigate",
                "correlation_id": "s3", "phase": "SUBMITTED", "result": None, "reason": None}}


async def prepared(leases, robot):
    return await leases.send("r", robot, CAPS, 0., 0., 0., "s3", plan_id="plan",
                             owner_epoch={"expected_boot_id": BOOT})


def test_time_clear_and_unconfirmed_cancel_never_resolve(monkeypatch):
    leases, mono, wall = setup(monkeypatch)
    robot = Robot(wall)
    leases._clients["r"] = robot
    uncertain(leases)
    marker = leases._uncertain_motion["r"]
    assert marker["since"] == mono() and marker["wall_time"] == wall()
    assert marker["wire_version"] == leases.peer_wire_state(["r"])["r"][0]
    assert marker["motion_epoch"] == leases.motion_epoch
    leases.clear()
    mono.advance(100000.)
    robot.reply = {"accepted": True, "navigation": "IDLE"}
    run(leases.cancel("r", robot))
    assert leases._uncertain_motion["r"] is marker
    assert leases.idle_wire_epoch("r") is None
    with pytest.raises(NavigationStopped, match="no confirmed outcome"):
        run(prepared(leases, robot))


@pytest.mark.parametrize("navigation", ["IDLE", "CANCELED"])
def test_cancel_of_already_terminal_navigation_keeps_uncertainty(monkeypatch, navigation):
    leases, mono, wall = setup(monkeypatch)
    robot = Robot(wall)
    leases._clients["r"] = robot
    uncertain(leases)
    marker = leases._uncertain_motion["r"]
    robot.reply = {"navigation": navigation, "operation": None}
    mono.advance(8.5)
    assert run(leases.cancel("r", robot)) == robot.reply
    assert leases._uncertain_motion["r"] is marker
    assert leases.idle_wire_epoch("r") is None
    with pytest.raises(NavigationStopped, match="no confirmed outcome"):
        run(prepared(leases, robot))


@pytest.mark.parametrize("kind", ["state", "cancel"])
def test_readback_exception_keeps_uncertainty(monkeypatch, kind):
    leases, mono, wall = setup(monkeypatch)
    robot = Robot(wall)
    leases._clients["r"] = robot
    uncertain(leases)
    marker = leases._uncertain_motion["r"]

    async def failed():
        raise RuntimeError("CORE readback failed")

    mono.advance(8.5)
    if kind == "state":
        robot.state = failed
        call = leases.read_motion_state("r", robot)
    else:
        robot.navigation_cancel = failed
        call = leases.cancel("r", robot)
    with pytest.raises(RuntimeError, match="CORE readback failed"):
        run(call)
    assert leases._uncertain_motion["r"] is marker
    assert leases.idle_wire_epoch("r") is None


@pytest.mark.parametrize("evidence", ["idle", "ended", "estop"])
def test_later_proof_restores_peer_epoch_and_prepared_admission(monkeypatch, evidence, caplog):
    leases, mono, wall = setup(monkeypatch)
    robot = Robot(wall)
    leases._clients["r"] = robot
    uncertain(leases)
    mono.advance(8.5)
    robot.updates = ({"mode": "EMERGENCY", "safety": {"estop": True}} if evidence == "estop"
                     else {"navigation": "ARRIVED", "mode": "NAVIGATION"} if evidence == "ended" else {})
    run(leases.read_motion_state("r", robot))
    assert not leases._uncertain_motion
    assert leases.idle_wire_epoch("r") is not None
    assert "uncertain motion of r resolved" in caplog.text
    assert run(prepared(leases, robot))["accepted"]


@pytest.mark.parametrize("updates", [
    {"velocity": {"linear": .1, "angular": 0.}}, {"navigation": "NAVIGATING"},
    {"line_follow": {"mode": "IR_LINE"}}, {"goal": {"x": 1.}},
    {"evidence": {}}, {"robot_id": "peer"},
    {"mode": "EMERGENCY", "safety": {"estop": False}},
    {"mode": "EMERGENCY", "safety": {"estop": True}, "velocity": {"linear": .001, "angular": 0.}},
])
def test_state_without_existing_stop_proof_keeps_uncertainty(monkeypatch, updates):
    leases, mono, wall = setup(monkeypatch)
    robot = Robot(wall)
    leases._clients["r"] = robot
    uncertain(leases)
    mono.advance(8.5)
    robot.updates = updates
    run(leases.read_motion_state("r", robot))
    assert "r" in leases._uncertain_motion


@pytest.mark.parametrize("kind", ["state", "cancel"])
@pytest.mark.parametrize("race", ["before_marker", "new_uncertainty", "new_wire", "pending_wire", "client_replaced"])
def test_inflight_observation_cannot_resolve_a_newer_motion(monkeypatch, kind, race):
    async def exercise():
        leases, mono, wall = setup(monkeypatch)
        robot = Robot(wall)
        leases._clients["r"] = robot
        entered, resume = asyncio.Event(), asyncio.Event()

        async def delayed(*_args, **_kwargs):
            entered.set()
            await resume.wait()
            wall.advance(.25)
            return state(wall) if kind == "state" else {"navigation": "CANCELED", "operation": None}

        if race != "before_marker":
            uncertain(leases)
        mono.advance(8.5)
        if kind == "state":
            robot.state = delayed
            task = asyncio.create_task(leases.read_motion_state("r", robot))
        else:
            robot.navigation_cancel = delayed
            task = asyncio.create_task(leases.cancel("r", robot))
        await entered.wait()
        mono.advance(8.5)
        if race in {"before_marker", "new_uncertainty"}:
            uncertain(leases)
        elif race == "client_replaced":
            leases._clients["r"] = Robot(wall)
        else:
            with leases.motion_wire("r", "POST", "/api/v1/navigation/goal", {}):
                if race == "pending_wire":
                    resume.set()
                    await task
        resume.set()
        await task
        assert "r" in leases._uncertain_motion
    run(exercise())


def test_old_velocity_sample_is_not_post_marker_proof(monkeypatch):
    leases, mono, wall = setup(monkeypatch)
    robot = Robot(wall)
    leases._clients["r"] = robot
    robot.updates = {"evidence": state(wall)["evidence"]}
    uncertain(leases)
    mono.advance(8.5)
    wall.advance(.25)
    run(leases.read_motion_state("r", robot))
    assert "r" in leases._uncertain_motion


def test_future_velocity_sample_is_not_stop_proof(monkeypatch):
    leases, mono, wall = setup(monkeypatch)
    robot = Robot(wall)
    leases._clients["r"] = robot
    uncertain(leases)
    mono.advance(8.5)
    robot.updates = {"evidence": {"velocity": {"evidence": "fresh", "sampled_at":
                       datetime.fromtimestamp(wall() + 1., timezone.utc).isoformat()}}}
    run(leases.read_motion_state("r", robot))
    assert "r" in leases._uncertain_motion


def test_readback_started_during_a_pending_wire_cannot_resolve_it(monkeypatch):
    leases, mono, wall = setup(monkeypatch)
    robot = Robot(wall)
    leases._clients["r"] = robot
    body = {"admit_within_s": 3.0, "expected_boot_id": BOOT, "expected_owner_generation": 1}
    with leases.motion_wire("r", "POST", "/api/v1/navigation/goal", body) as unresolved:
        unresolved()
        mono.advance(8.5)
        run(leases.read_motion_state("r", robot))
        assert "r" in leases._uncertain_motion
    run(leases.read_motion_state("r", robot))
    assert not leases._uncertain_motion


@pytest.mark.parametrize("estop", [False, True])
def test_fresh_post_marker_encoder_sample_can_precede_the_get(monkeypatch, estop):
    leases, mono, wall = setup(monkeypatch)
    robot = Robot(wall)
    leases._clients["r"] = robot
    uncertain(leases)
    mono.advance(8.5)
    assert run(leases._verify_uncertain_release_fence("r", robot))
    wall.advance(.25)
    robot.updates = {"evidence": state(wall)["evidence"]}
    if estop:
        robot.updates.update(mode="EMERGENCY", safety={"estop": True})
    wall.advance(.25)
    run(leases.read_motion_state("r", robot))
    assert not leases._uncertain_motion


def test_peer_uncertainty_still_blocks_site_wide_admission(monkeypatch):
    leases, mono, wall = setup(monkeypatch)
    robot = Robot(wall)
    leases._clients["r"] = robot
    uncertain(leases)
    uncertain(leases, "peer")
    mono.advance(8.5)
    run(leases.read_motion_state("r", robot))
    assert set(leases._uncertain_motion) == {"peer"}
    with pytest.raises(NavigationStopped, match="no confirmed outcome"):
        run(prepared(leases, robot))


def test_navigation_cancel_does_not_settle_non_navigation_uncertainty(monkeypatch):
    leases, mono, wall = setup(monkeypatch)
    robot = Robot(wall)
    leases._clients["r"] = robot
    with leases.motion_wire("r", "POST", "/api/v1/teleop", {"linear": .1, "angular": 0.}) as unresolved:
        unresolved()
    uncertain(leases)  # A later lost navigation reply still requires measured stop proof.
    mono.advance(8.5)
    run(leases.cancel("r", robot))
    assert "r" in leases._uncertain_motion
    run(leases.read_motion_state("r", robot))
    assert "r" in leases._uncertain_motion  # An earlier unbounded teleop cannot be erased by a bounded goal.


def test_console_gather_bypasses_shared_and_heartbeat_caches_while_uncertain(monkeypatch):
    from core_common.protocol.schemas import StateSnapshot
    from fleet.server.console import FleetConsole
    from fleet.swarm.robots import RobotEndpoint

    _, mono, wall = setup(monkeypatch)
    robot = Robot(wall)
    console = FleetConsole([RobotEndpoint("r", "http://127.0.0.1:8080", "t")], [robot], clock=mono)
    row = console.hub.registry.record("r")
    row.online, row.last_heartbeat_monotonic = True, mono()
    row.snapshot = StateSnapshot(robot_id="r")

    async def cached(*_args):
        raise AssertionError("shared cache cannot prove uncertainty resolved")

    console.read_state = cached
    uncertain(console.goal_leases)
    mono.advance(8.5)
    robot.updates = {"velocity": {"linear": .1, "angular": 0.}}
    observed, source = run(console._gather_state("r"))
    assert source == "rest" and observed["velocity"]["linear"] == .1
    assert "r" in console.goal_leases._uncertain_motion
    robot.updates = {}
    run(console._gather_state("r"))
    assert not console.goal_leases._uncertain_motion


@pytest.mark.parametrize("old_first_sample", [False, True])
def test_exact_custody_stop_requires_post_marker_velocity_samples(monkeypatch, old_first_sample):
    leases, mono, wall = setup(monkeypatch)
    robot = Robot(wall)
    leases._clients["r"] = robot
    terminal = datetime.fromtimestamp(wall() - 10., timezone.utc)
    operation = {"boot_id": BOOT, "run_id": RUN, "kind": "navigate", "correlation_id": "s3",
                 "phase": "TERMINAL", "result": "CANCELED", "reason": "CANCELED"}

    async def navigation(_path):
        return {"navigation": "CANCELED", "operation": operation, "lookup": "FOUND",
                "owner": {"boot_id": BOOT, "owner_run_id": None, "owner_generation": robot.owner_generation},
                "quiescence": {"boot_id": BOOT, "requested_run_id": RUN, "owner_run_id": None,
                               "owner_generation": robot.owner_generation, "transport_generation": 1,
                               "quiescent": True, "observed_at": terminal.isoformat(), "admitting": False,
                               "pending_submission": False, "actuating_callback": False, "lease_active": False}}

    robot._get = navigation
    uncertain(leases)
    claim = NamedStopMotion("r", BOOT, "s3", run_id=RUN)
    if old_first_sample:
        claim.stopped_epoch, claim.terminal_at = (2, 1), terminal
        claim.zero_at = datetime.fromtimestamp(wall() - 1., timezone.utc)
    leases._named_stop_motion = claim
    mono.advance(8.5)
    run(leases._reconcile_named_stop())
    assert "r" in leases._uncertain_motion  # one new zero sample or an old first sample is insufficient
    if old_first_sample:
        assert leases._named_stop_motion is None
    else:
        assert leases._named_stop_motion is claim
        mono.advance(8.5)
        run(leases._reconcile_named_stop())
        assert not leases._uncertain_motion and leases._named_stop_motion is None


@pytest.mark.parametrize("started, cleared", [(8.499, False), (8.5, True), (8.501, True)])
def test_admission_window_requires_readback_started_at_or_after_boundary(monkeypatch, started, cleared):
    leases, mono, wall = setup(monkeypatch)
    robot = Robot(wall)
    leases._clients["r"] = robot
    t0 = mono()  # FakeClock does not start at 0
    uncertain(leases)
    marker = leases._uncertain_motion["r"]
    assert (marker["sent_at"] - t0, marker["timeout_s"], marker["admit_within_s"]) == (0., 5., 3.)
    mono.advance(started)
    run(leases.read_motion_state("r", robot))
    assert ("r" not in leases._uncertain_motion) is cleared


def test_readback_finishing_after_deadline_cannot_clear_if_started_before_it(monkeypatch):
    leases, mono, wall = setup(monkeypatch)
    robot = Robot(wall)
    leases._clients["r"] = robot
    original = robot.state

    async def delayed():
        mono.advance(1.)
        return await original()

    robot.state = delayed
    uncertain(leases)
    mono.advance(8.)
    run(leases.read_motion_state("r", robot))
    assert "r" in leases._uncertain_motion


def test_old_core_cannot_clear_even_with_late_measured_stop(monkeypatch, caplog):
    leases, mono, wall = setup(monkeypatch)
    robot = Robot(wall)
    leases._clients["r"] = robot
    uncertain(leases, admit_within_s=None)
    mono.advance(1000.)
    run(leases.read_motion_state("r", robot))
    assert leases._uncertain_motion["r"]["admit_within_s"] is None
    assert "기한 없는 CORE라 해제 불가" in caplog.text


def test_later_shorter_deadline_does_not_reduce_earlier_uncertainty(monkeypatch):
    leases, mono, _wall = setup(monkeypatch)
    t0 = mono()
    uncertain(leases, admit_within_s=10.)
    mono.advance(.5)
    uncertain(leases, admit_within_s=3.)
    assert leases._uncertain_motion["r"]["release_after"] - t0 == 15.5


@pytest.mark.parametrize("path", ["/api/v1/teleop", "/api/v1/localization/mission"])
def test_deadline_field_on_unsupported_motion_is_not_a_release_contract(monkeypatch, path):
    leases, _mono, _wall = setup(monkeypatch)
    with leases.motion_wire("r", "POST", path, {"linear": .1, "admit_within_s": 3.}) as unresolved:
        unresolved()
    assert leases._uncertain_motion["r"]["admit_within_s"] is None


@pytest.mark.parametrize("case", ["old_core_no_fence", "changed_boot"])
def test_cached_capability_with_old_core_or_changed_boot_does_not_release(monkeypatch, case):
    import httpx
    from fleet.swarm.robots import RobotEndpoint
    from fleet.swarm.transport import HttpRobotClient

    OTHER_BOOT = "99ab4cdc-c6d6-4a6f-81ea-25b5714187c9"
    leases, mono, wall = setup(monkeypatch)
    boot = [BOOT]
    gen = [3]

    async def handler(request):
        if request.url.path == "/api/v1/system/capabilities":
            return httpx.Response(200, json={"navigation": {"admit_deadline": True, "generation_fence": True}})
        if request.url.path == "/api/v1/navigation/state":
            return httpx.Response(200, json={"navigation": "IDLE",
                                             "owner": {"boot_id": boot[0], "owner_generation": gen[0]}})
        if request.url.path == "/api/v1/robot/state":
            wall.advance(.25)
            return httpx.Response(200, json=state(wall))
        if request.url.path == "/api/v1/navigation/cancel":
            # Old CORE ignores advance_generation and stays at the same owner_generation when idle.
            return httpx.Response(200, json={"navigation": "IDLE", "operation": None,
                                             "idle_owner": {"boot_id": boot[0], "owner_generation": gen[0]}})
        raise httpx.ReadTimeout("timed out", request=request)

    async def exercise():
        async with httpx.AsyncClient(base_url="http://robot", transport=httpx.MockTransport(handler)) as http:
            client = HttpRobotClient(RobotEndpoint("r", "http://robot", "test"), http=http, timeout_s=5.)
            leases._clients["r"] = client
            client.bind_motion_wire(leases.motion_wire)
            await client.capabilities()
            with pytest.raises(httpx.ReadTimeout):
                await client._post("/api/v1/navigation/goal", {"x": 1., "y": 0.})
            assert "r" in leases._uncertain_motion
            if case == "changed_boot":
                boot[0] = OTHER_BOOT
                gen[0] = 0
            mono.advance(8.5)
            await leases.read_motion_state("r", client)
            assert "r" in leases._uncertain_motion
            if case == "changed_boot":
                assert client._admit_deadline is False and client._admit_boot_id is None

    run(exercise())


def test_release_requires_and_records_advanced_generation_fence(monkeypatch):
    import json
    import httpx
    from fleet.swarm.robots import RobotEndpoint
    from fleet.swarm.transport import HttpRobotClient

    leases, mono, wall = setup(monkeypatch)
    gen = [5]
    cancel_bodies = []

    async def handler(request):
        if request.url.path == "/api/v1/system/capabilities":
            return httpx.Response(200, json={"navigation": {"admit_deadline": True, "generation_fence": True}})
        if request.url.path == "/api/v1/navigation/state":
            return httpx.Response(200, json={"navigation": "IDLE",
                                             "owner": {"boot_id": BOOT, "owner_generation": gen[0]}})
        if request.url.path == "/api/v1/robot/state":
            wall.advance(.25)
            return httpx.Response(200, json=state(wall))
        if request.url.path == "/api/v1/navigation/cancel":
            body = json.loads(request.content) if request.content else {}
            cancel_bodies.append(body)
            if body.get("advance_generation") is True:
                gen[0] += 1
            return httpx.Response(200, json={"navigation": "IDLE", "operation": None,
                                             "owner": {"boot_id": BOOT, "owner_generation": gen[0]}})
        raise httpx.ReadTimeout("timed out", request=request)

    async def exercise():
        async with httpx.AsyncClient(base_url="http://robot", transport=httpx.MockTransport(handler)) as http:
            client = HttpRobotClient(RobotEndpoint("r", "http://robot", "test"), http=http, timeout_s=5.)
            leases._clients["r"] = client
            client.bind_motion_wire(leases.motion_wire)
            await client.capabilities()
            with pytest.raises(httpx.ReadTimeout):
                await client._post("/api/v1/navigation/goal", {"x": 1., "y": 0.})
            marker = leases._uncertain_motion["r"]
            assert marker["boot_id"] == BOOT and marker["owner_generation"] == 5
            mono.advance(8.5)
            await leases.read_motion_state("r", client)
            assert "r" not in leases._uncertain_motion
            assert cancel_bodies == [{"advance_generation": True}]
            assert marker["fenced_generation"] == 6

    run(exercise())


def test_late_admission_between_stop_sample_and_verify_does_not_release(monkeypatch):
    leases, mono, wall = setup(monkeypatch)
    robot = Robot(wall)
    leases._clients["r"] = robot
    uncertain(leases, owner_generation=5)
    robot.owner_generation = 5
    original_state = robot.state

    async def state_then_late_admit():
        observed = await original_state()
        # A late request admits right after the standstill sample and bumps CORE's owner_generation.
        robot.owner_generation += 2
        return observed

    robot.state = state_then_late_admit
    mono.advance(8.5)
    run(leases.read_motion_state("r", robot))
    assert "r" in leases._uncertain_motion


def test_missing_expected_generation_keeps_uncertain_marker_unbounded(monkeypatch):
    leases, mono, wall = setup(monkeypatch)
    robot = Robot(wall)
    leases._clients["r"] = robot
    uncertain(leases, owner_generation=None)
    assert leases._uncertain_motion["r"]["release_after"] is None
    mono.advance(8.5)
    run(leases.read_motion_state("r", robot))
    assert "r" in leases._uncertain_motion


def test_active_navigation_is_not_canceled_by_fence_until_inactive(monkeypatch):
    leases, mono, wall = setup(monkeypatch)
    robot = Robot(wall)
    leases._clients["r"] = robot
    cancels = []
    original_cancel = robot.navigation_cancel

    async def tracked_cancel(*, advance_generation=False):
        cancels.append(advance_generation)
        return await original_cancel(advance_generation=advance_generation)

    robot.navigation_cancel = tracked_cancel
    uncertain(leases, owner_generation=3)
    robot.owner_generation = 4  # A new navigation goal started normally after the uncertain marker.
    robot.updates = {"navigation": "NAVIGATING", "mode": "NAVIGATION"}
    mono.advance(8.5)
    run(leases.read_motion_state("r", robot))
    robot.owner_generation = 5  # Even across another active generation change, fence must not cancel it.
    run(leases.read_motion_state("r", robot))
    assert cancels == [] and "r" in leases._uncertain_motion
    robot.updates = {"navigation": "IDLE", "mode": "IDLE"}
    run(leases.read_motion_state("r", robot))
    assert cancels == [True] and "r" not in leases._uncertain_motion


@pytest.mark.parametrize("mode", ["type_error", "missing_owner"])
def test_fence_rejects_external_generation_bump_without_cancel_owner(monkeypatch, mode):
    leases, mono, wall = setup(monkeypatch)
    robot = Robot(wall)
    leases._clients["r"] = robot
    uncertain(leases, owner_generation=2)
    robot.owner_generation = 2
    plain_calls = []

    async def no_kwarg_cancel():
        plain_calls.append(True)
        robot.owner_generation = 9
        return {"navigation": "IDLE", "operation": None}

    async def ownerless_cancel(*, advance_generation=False):
        assert advance_generation is True
        robot.owner_generation = 9  # Generation rose for another reason, not proved by cancel reply owner.
        return {"navigation": "IDLE", "operation": None}

    robot.navigation_cancel = no_kwarg_cancel if mode == "type_error" else ownerless_cancel
    mono.advance(8.5)
    run(leases.read_motion_state("r", robot))
    assert plain_calls == [] and "r" in leases._uncertain_motion
