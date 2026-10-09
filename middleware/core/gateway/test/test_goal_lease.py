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


@pytest.mark.parametrize("ttl", [0, -1, 5.01, 60])
def test_bad_ttl_is_400(robot, ttl):
    tc, svc, executor, _clock = robot
    reply = _goal(tc, correlation_id="a-1", lease_ttl_s=ttl)
    assert reply.status_code == 400 and executor.sent == []
    _goal(tc, correlation_id="a-1", lease_ttl_s=2.0)
    svc.nav.on_goal_accepted()
    assert _renew(tc, "a-1", ttl).status_code == 400


def test_lease_needs_a_correlation_id(robot):
    tc, _svc, executor, _clock = robot
    assert _goal(tc, lease_ttl_s=2.0).status_code == 400 and executor.sent == []


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
