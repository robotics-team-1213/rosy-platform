"""D-550 10: Fleet navigation goal lease through the REST surface and the real NavigationManager."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class Executor:
    def __init__(self) -> None:
        self.sent = []
        self.cancelled = 0

    def send_goal(self, spec, *, correlation_id=None):
        self.sent.append(correlation_id)

    def cancel_goal(self):
        self.cancelled += 1


@pytest.fixture
def robot(core_client, monkeypatch):
    tc, svc = core_client()
    # Same bypass as test_fleet_loss_wiring: the core runtime mode withholds goals.
    monkeypatch.setattr("core_api_web.api.v1.navigation.require_kept", lambda *_: None)
    executor, clock = Executor(), Clock()
    svc.nav.executor = executor
    svc.nav.lease_clock = clock
    return tc, svc, executor, clock


def _goal(tc, **extra):
    return tc.post("/api/v1/navigation/goal", json={"x": 1.0, "y": 0.5, "yaw": 0.0, **extra},
                   headers=OPERATOR)


def _renew(tc, correlation_id, ttl_s=2.0):
    return tc.post("/api/v1/navigation/goal/lease",
                   json={"correlation_id": correlation_id, "ttl_s": ttl_s}, headers=OPERATOR)


def _canceled(svc):
    return [ev.data for ev in svc.events.history() if ev.type == "nav.canceled"]


def test_expired_lease_cancels_and_clears_so_a_new_goal_is_taken(robot):
    tc, svc, executor, clock = robot
    assert _goal(tc, correlation_id="a-1", lease_ttl_s=2.0).status_code == 200
    svc.nav.on_goal_accepted()
    clock.now += 1.9
    assert svc.nav.expire_goal_lease() is False and executor.cancelled == 0
    clock.now += 0.2
    assert svc.nav.expire_goal_lease() is True
    assert executor.cancelled == 1
    assert svc.nav.fleet_goal() is None
    assert _canceled(svc) == [{"source": "goal_lease", "correlation_id": "a-1"}]
    assert svc.nav.expire_goal_lease() is False          # once
    assert _goal(tc, correlation_id="a-2").status_code == 200   # no NAVIGATION_ACTIVE


def test_renewal_extends_the_lease(robot):
    tc, svc, executor, clock = robot
    _goal(tc, correlation_id="a-1", lease_ttl_s=2.0)
    svc.nav.on_goal_accepted()
    for _ in range(5):
        clock.now += 1.5
        assert _renew(tc, "a-1").json() == {"renewed": True, "correlation_id": "a-1", "ttl_s": 2.0}
        svc.nav.expire_goal_lease()
    assert executor.cancelled == 0
    clock.now += 2.0
    assert svc.nav.expire_goal_lease() is True


@pytest.mark.parametrize("end", ["cancel", "arrive", "fail", "expire"])
def test_renewal_after_the_goal_ended_is_409_and_sends_nothing(robot, end):
    tc, svc, executor, clock = robot
    _goal(tc, correlation_id="a-1", lease_ttl_s=2.0)
    svc.nav.on_goal_accepted()
    if end == "cancel":
        tc.post("/api/v1/navigation/cancel", headers=OPERATOR)
    elif end == "arrive":
        svc.nav.on_result(True, correlation_id="a-1")
    elif end == "fail":
        svc.nav.on_result(False, "ABORTED", correlation_id="a-1")
    else:
        clock.now += 2.5
        svc.nav.expire_goal_lease()
    sent = list(executor.sent)
    reply = _renew(tc, "a-1")
    assert reply.status_code == 409 and reply.json()["error"]["code"] == "GOAL_LEASE_NOT_ACTIVE"
    assert executor.sent == sent and svc.nav.fleet_goal() is None   # never revived


def test_newer_goal_invalidates_the_old_lease(robot):
    tc, svc, executor, clock = robot
    _goal(tc, correlation_id="a-1", lease_ttl_s=2.0)
    svc.nav.on_goal_accepted()
    svc.nav.on_result(True, correlation_id="a-1")
    _goal(tc, correlation_id="a-2", lease_ttl_s=2.0)
    svc.nav.on_goal_accepted()
    assert _renew(tc, "a-1").status_code == 409
    assert _renew(tc, "a-2").status_code == 200
    clock.now += 1.5
    _renew(tc, "a-2")
    clock.now += 1.5
    assert svc.nav.expire_goal_lease() is False and executor.cancelled == 0


def test_newer_unleased_goal_is_not_cancelled_by_an_old_lease(robot):
    tc, svc, executor, clock = robot
    _goal(tc, correlation_id="a-1", lease_ttl_s=2.0)
    svc.nav.on_goal_accepted()
    svc.nav.on_result(True, correlation_id="a-1")
    _goal(tc, correlation_id="a-2")
    svc.nav.on_goal_accepted()
    clock.now += 10.0
    assert svc.nav.expire_goal_lease() is False and executor.cancelled == 0


def test_goal_without_lease_is_unchanged(robot):
    tc, svc, executor, clock = robot
    assert _goal(tc, correlation_id="a-1").status_code == 200
    svc.nav.on_goal_accepted()
    clock.now += 3600.0
    assert svc.nav.expire_goal_lease() is False and executor.cancelled == 0
    assert svc.nav.fleet_goal()[0] == "a-1"
    assert _renew(tc, "a-1").status_code == 409            # renewal never leases a goal


# NaN/Infinity are refused by the model too (allow_inf_nan=False), but the shared 400 handler cannot
# serialise a non-finite `input` today (pre-existing, every float field): that case is a 500, no goal.
@pytest.mark.parametrize("ttl", [0, -1, 5.01, 60])
def test_bad_ttl_is_400_and_leaves_the_mode(robot, ttl):
    tc, svc, executor, _clock = robot
    mode = svc.modes.mode
    reply = tc.post("/api/v1/navigation/goal", headers={**OPERATOR, "Content-Type": "application/json"}, content=(
        '{"x": 1.0, "y": 0.5, "correlation_id": "a-1", "lease_ttl_s": %s}' % ttl).encode())
    assert reply.status_code == 400 and executor.sent == [] and svc.modes.mode is mode
    _goal(tc, correlation_id="a-1", lease_ttl_s=2.0)
    svc.nav.on_goal_accepted()
    assert _renew(tc, "a-1", ttl).status_code == 400


def test_lease_needs_a_correlation_id_and_leaves_the_mode(robot):
    tc, svc, executor, _clock = robot
    mode = svc.modes.mode
    assert _goal(tc, lease_ttl_s=2.0).status_code == 400
    assert executor.sent == [] and svc.modes.mode is mode


def test_renewal_racing_expiry_is_refused_and_the_goal_still_stops(robot, monkeypatch):
    """A renewal landing between the expiry dropping the lease and its cancel never revives it."""
    from core_features.navigation.manager import NavigationError
    tc, svc, executor, clock = robot
    _goal(tc, correlation_id="a-1", lease_ttl_s=2.0)
    svc.nav.on_goal_accepted()
    cancel, raced = svc.nav.cancel, []

    def cancel_after_a_racing_renewal(**kwargs):
        with pytest.raises(NavigationError) as err:
            svc.nav.renew_goal_lease("a-1", 2.0)
        raced.append(err.value.code)
        return cancel(**kwargs)

    monkeypatch.setattr(svc.nav, "cancel", cancel_after_a_racing_renewal)
    clock.now += 2.1
    assert svc.nav.expire_goal_lease() is True
    assert raced == ["GOAL_LEASE_NOT_ACTIVE"] and executor.cancelled == 1
    assert svc.nav.fleet_goal() is None


def test_lease_expiry_precedes_a_pending_saf003_return_home(core_client, monkeypatch):
    """D-550 J1 precedence: a lease shorter than fleet_loss_timeout_s stops the goal first (STOP,
    whatever the policy); SAF-003 then has no goal to act on: no home drive, no safety.fleet_lost."""
    fleet = {"hub_url": "ws://127.0.0.1:1/ws/robots", "pairing_token": "pair-token"}
    tc, svc = core_client(config_overrides={"fleet": fleet})
    monkeypatch.setattr("core_api_web.api.v1.navigation.require_kept", lambda *_: None)
    executor, clock = Executor(), Clock()
    svc.nav.executor, svc.nav.lease_clock, svc.fleet_loss.clock = executor, clock, clock
    svc.safety.fleet_loss_policy = "RETURN_HOME"
    homes = []
    monkeypatch.setattr(svc.nav, "home", lambda **kwargs: homes.append(kwargs))
    svc.fleet_agent.connected, svc.fleet_agent.last_rx = True, clock.now
    svc.fleet_loss.tick()
    assert _goal(tc, correlation_id="a-1", lease_ttl_s=2.0).status_code == 200
    svc.nav.on_goal_accepted()
    svc.fleet_agent.connected = False        # Fleet gone: no renewal, link lost
    svc.fleet_loss.tick()
    clock.now += 2.1
    svc.fleet_loss.tick()
    assert svc.nav.expire_goal_lease() is True
    clock.now += 3.0                         # past the 5 s SAF-003 timeout
    svc.fleet_loss.tick()
    assert executor.cancelled == 1 and homes == []
    assert _canceled(svc) == [{"source": "goal_lease", "correlation_id": "a-1"}]
    assert [ev for ev in svc.events.history() if ev.type == "safety.fleet_lost"] == []


def test_power_timer_expires_leases_inside_a_guard():
    """Structural (bridge timers are not driven in host tests): `_tick_power` calls
    `nav.expire_goal_lease()` inside `try/except Exception`."""
    source = (Path(__file__).resolve().parents[1] / "core" / "bridge" / "ros_bridge.py").read_text(
        encoding="utf-8")
    func = next(node for node in ast.walk(ast.parse(source))
                if isinstance(node, ast.FunctionDef) and node.name == "_tick_power")
    guarded = [
        node for node in ast.walk(func) if isinstance(node, ast.Try)
        and any(isinstance(h.type, ast.Name) and h.type.id == "Exception" for h in node.handlers)
        and any(isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and call.func.attr == "expire_goal_lease"
                for stmt in node.body for call in ast.walk(stmt))
    ]
    assert len(guarded) == 1
    # Safety-Review: both motion stops run before the unguarded power/calibration/trip-lease calls.
    calls = {ast.unparse(call.func): call.lineno for call in ast.walk(func) if isinstance(call, ast.Call)}
    first_other = min(calls["power.tick"], calls["self._svc.calibration.expire_due"],
                      calls["self._svc.trip_lease.expire_due"])
    assert calls["self._svc.nav.expire_goal_lease"] < first_other
    assert calls["self._svc.fleet_loss.tick"] < first_other
