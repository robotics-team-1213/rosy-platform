"""전체 비상정지의 전달: 모든 로봇에 동시에, 짧은 시도로 보낸다.

console.py 본체가 D-766 크기 래칫에 묶여 2026-11-01 이 판단과 함께 나왔다. 콘솔은 결과로
자기 목표·점유를 정리하고, 이 모듈은 "정지가 닿았는가"만 책임진다.

- 요청이 CORE에 닿지 않은 것이 확실할 때(연결 실패·연결 시한)만 다시 보낸다. 응답을 잃었거나
  읽기 시한이 지났으면 CORE가 이미 걸었을 수 있으므로 다시 보내지 않고 UNKNOWN으로 남긴다
  (D-271 5: timeout 뒤 물리 명령을 무조건 재실행하지 않는다; 정지 원장은 POST 한 번을 고정한다).
  전체 시한은 예전 한 번의 대기와 같은 5 s다. 로봇이 오류로 답했으면 다시 묻지 않는다.
- 대형 해제(팔로워 swarm/cancel, 대당 시한)는 정지와 나란히 돈다. 해제를 먼저 기다리면 닿지
  않는 팔로워 하나 때문에 모든 로봇의 정지가 늦는다. 릴레이는 해제의 첫 단계(로컬)라 곧 멈추고,
  늦게 닿은 참조는 EMERGENCY 래치가 막는다.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional, Sequence

import httpx

logger = logging.getLogger("fleet.console")

#: Same total wait as the old single attempt (HttpRobotClient default timeout).
ESTOP_BUDGET_S = 5.0
ESTOP_ATTEMPTS = 3
#: Failures that prove the request never reached CORE; only these are sent again.
UNSENT = (httpx.ConnectError, httpx.ConnectTimeout)


async def deliver(scatter: Callable[[str], Awaitable[dict]], robot_id: str) -> dict:
    """One robot's stop; re-sent only while the connection itself fails, inside ESTOP_BUDGET_S."""
    async with asyncio.timeout(ESTOP_BUDGET_S):
        for attempt in range(1, ESTOP_ATTEMPTS + 1):
            try:
                return await scatter(robot_id)
            except UNSENT:
                if attempt == ESTOP_ATTEMPTS:
                    raise
                logger.warning("estop to %s could not connect (attempt %d); sending again", robot_id, attempt)
    raise AssertionError("unreachable")


async def stop_robots(scatter: Callable[[str], Awaitable[dict]], order: Sequence[str],
                      release_formation: Optional[Callable[[], Awaitable[None]]] = None) -> list:
    """Per robot, its answer or the exception that ended its last attempt (order kept)."""
    formation = asyncio.ensure_future(release_formation()) if release_formation else None
    results = await asyncio.gather(*(deliver(scatter, rid) for rid in order), return_exceptions=True)
    if formation is not None:
        # 해제가 실패해도 정지 보고를 막지 않는다 — 해제는 거절하지 않는 동작이다.
        await asyncio.gather(formation, return_exceptions=True)
    return list(results)
