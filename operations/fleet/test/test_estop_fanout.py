"""전체 비상정지 전달: 닿지 않은 요청만 다시 보내고, 대형 해제를 기다리지 않는 정지."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from fakes import run
from fleet.hub.hub import HubError
from fleet.server import estop_fanout
from fleet.swarm.api.ports import RobotApiError


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(estop_fanout, "ESTOP_BUDGET_S", 0.2)


class Scatter:
    """Per robot, the outcomes of its attempts in order: an exception to raise, "hang", or an answer."""

    def __init__(self, plans: dict[str, list] | None = None):
        self.plans = {robot: list(plan) for robot, plan in (plans or {}).items()}
        self.calls: list[str] = []
        self.at: dict[str, float] = {}

    async def __call__(self, robot_id: str) -> dict:
        self.calls.append(robot_id)
        self.at.setdefault(robot_id, asyncio.get_running_loop().time())
        plan = self.plans.get(robot_id) or []
        step = plan.pop(0) if len(plan) > 1 else (plan[0] if plan else None)
        if isinstance(step, BaseException):
            raise step
        if step == "hang":
            await asyncio.sleep(10)
        return {"estop": True}


def _connect_error():
    return httpx.ConnectError("connection refused")


def test_a_stop_that_never_connected_is_sent_again_and_lands():
    scatter = Scatter({"rosy_02": [_connect_error(), None]})
    results = run(estop_fanout.stop_robots(scatter, ["rosy_01", "rosy_02"]))
    assert results == [{"estop": True}, {"estop": True}]
    assert scatter.calls.count("rosy_02") == 2 and scatter.calls.count("rosy_01") == 1


def test_a_robot_that_never_connects_ends_after_the_last_attempt():
    scatter = Scatter({"rosy_01": [_connect_error()]})
    [result] = run(estop_fanout.stop_robots(scatter, ["rosy_01"]))
    assert isinstance(result, httpx.ConnectError)
    assert scatter.calls.count("rosy_01") == estop_fanout.ESTOP_ATTEMPTS


@pytest.mark.parametrize("outcome", [httpx.ReadError("reply lost after CORE latched"), "hang"])
def test_a_stop_that_may_have_reached_core_is_not_sent_again(outcome):
    """D-271 5: a lost reply or a read timeout may already have latched CORE; it stays UNKNOWN."""
    scatter = Scatter({"rosy_01": [outcome]})
    [result] = run(estop_fanout.stop_robots(scatter, ["rosy_01"]))
    assert isinstance(result, (httpx.ReadError, TimeoutError))
    assert scatter.calls == ["rosy_01"]


@pytest.mark.parametrize("error", [RobotApiError("rosy_01", 409, "MODE_CONFLICT", "no"),
                                   HubError("UNKNOWN_ROBOT", "rosy_01")])
def test_an_answered_refusal_is_not_asked_again(error):
    scatter = Scatter({"rosy_01": [error]})
    [result] = run(estop_fanout.stop_robots(scatter, ["rosy_01"]))
    assert result is error and scatter.calls == ["rosy_01"]


def test_formation_release_runs_beside_the_stop_not_before_it():
    """A follower whose swarm/cancel hangs must not hold back every robot's stop."""
    scatter = Scatter()
    released = []

    async def release():
        await asyncio.sleep(0.3)
        released.append(asyncio.get_running_loop().time())

    async def go():
        start = asyncio.get_running_loop().time()
        results = await estop_fanout.stop_robots(scatter, ["rosy_01", "rosy_02"], release)
        return start, results
    start, results = run(go())
    assert results == [{"estop": True}, {"estop": True}]
    assert all(at - start < 0.1 for at in scatter.at.values())     # sent before the release ended
    assert released and released[0] - start >= 0.3                 # and the release still finished


def test_a_failed_formation_release_does_not_hide_the_stops():
    async def release():
        raise RuntimeError("follower unreachable")
    assert run(estop_fanout.stop_robots(Scatter(), ["rosy_01"], release)) == [{"estop": True}]
