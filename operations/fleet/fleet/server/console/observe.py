"""목표 판정 직전의 로봇 상태 읽기.

console.py 본체가 D-766 크기 래칫에 묶여 2026-10-28 자원 경계 변경과 함께 나왔다.
활동 로봇(목표·claim·양보)은 판정 순간의 REST를, 대기 로봇은 hub 하트비트 스냅샷
(D-447 ``_gather_state``, 낡으면 REST 폴백)을 읽는다. 어느 쪽이든 ``_remember`` 가
모든 로봇의 판정(``_verdict``)을 갱신한다(D-395 P2-2 불변식)."""

from __future__ import annotations

import asyncio
from typing import Any


async def observe_states(console) -> None:
    """로봇 좌표를 새로 읽는다. 미션을 내리는 순간에만 부른다 - 폴링은 스냅샷이 한다."""
    order = list(console._order)
    results = await asyncio.gather(
        *(_read(console, rid) for rid in order), return_exceptions=True)
    console._remember([
        {"robot_id": rid, "state": None if isinstance(r, BaseException) else r}
        for rid, r in zip(order, results) if rid in console._clients])


async def _read(console, robot_id: str) -> Any:
    if robot_id in console._goals or robot_id in console._claims or robot_id in console._yielding:
        return await console.read_state(robot_id, 0.2)   # D-760 8: shared
    state, _source = await console._gather_state(robot_id)
    return state
