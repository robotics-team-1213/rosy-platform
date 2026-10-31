"""전체 비상정지 전달: 짧은 재시도와 대형 해제를 기다리지 않는 정지."""

from __future__ import annotations

import asyncio

import pytest

from fakes import run
from fleet.hub.hub import HubError
from fleet.server import estop_fanout
from fleet.swarm.api.ports import RobotApiError


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(estop_fanout, "ESTOP_ATTEMPT_S", 0.05)


class Scatter:
    """Per robot, how many first attempts hang before one answers."""

    def __init__(self, hangs: dict[str, int] | None = None, error: BaseException | None = None):
        self.hangs = dict(hangs or {})
        self.error = error
        self.calls: list[str] = []
        self.at: dict[str, float] = {}

    async def __call__(self, robot_id: str) -> dict:
        self.calls.append(robot_id)
        self.at.setdefault(robot_id, asyncio.get_running_loop().time())
        if self.error is not None:
            raise self.error
        if self.hangs.get(robot_id, 0) > 0:
            self.hangs[robot_id] -= 1
            await asyncio.sleep(10)
        return {"estop": True}


def test_an_unanswered_stop_is_sent_again_and_lands():
    scatter = Scatter({"rosy_02": 1})
    results = run(estop_fanout.stop_robots(scatter, ["rosy_01", "rosy_02"]))
    assert results == [{"estop": True}, {"estop": True}]
    assert scatter.calls.count("rosy_02") == 2 and scatter.calls.count("rosy_01") == 1


def test_a_robot_that_never_answers_ends_after_the_last_attempt():
    scatter = Scatter({"rosy_01": 99})
    [result] = run(estop_fanout.stop_robots(scatter, ["rosy_01"]))
    assert isinstance(result, asyncio.TimeoutError)
    assert scatter.calls.count("rosy_01") == estop_fanout.ESTOP_ATTEMPTS


def test_an_answered_refusal_is_not_asked_again():
    error = RobotApiError("rosy_01", 409, "MODE_CONFLICT", "no")
    scatter = Scatter(error=error)
    [result] = run(estop_fanout.stop_robots(scatter, ["rosy_01"]))
    assert result is error and scatter.calls == ["rosy_01"]


def test_an_unknown_robot_fails_without_waiting():
    error = HubError("UNKNOWN_ROBOT", "rosy_99")
    scatter = Scatter(error=error)
    [result] = run(estop_fanout.stop_robots(scatter, ["rosy_99"]))
    assert result is error and len(scatter.calls) == estop_fanout.ESTOP_ATTEMPTS


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
