"""전체 비상정지의 전달: 모든 로봇에 동시에, 짧은 시도로 보낸다.

console.py 본체가 D-766 크기 래칫에 묶여 2026-11-01 이 판단과 함께 나왔다. 콘솔은 결과로
자기 목표·점유를 정리하고, 이 모듈은 "정지가 닿았는가"만 책임진다.

- 한 번의 긴 대기(5 s) 대신 1.5 s 시도를 세 번 한다. Wi-Fi가 한 번 튀어도 정지를 잃지 않는다.
  `POST /safety/stop` 은 래치라 다시 보내도 같은 결과다. 로봇이 오류로 답했으면(RobotApiError)
  그 답은 바뀌지 않으므로 다시 묻지 않는다.
- 대형 해제(팔로워 swarm/cancel, 대당 시한)는 정지와 나란히 돈다. 해제를 먼저 기다리면 닿지
  않는 팔로워 하나 때문에 모든 로봇의 정지가 늦는다. 릴레이는 해제의 첫 단계(로컬)라 곧 멈추고,
  늦게 닿은 참조는 EMERGENCY 래치가 막는다.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional, Sequence

from fleet.hub.hub import HubError
from fleet.swarm.api.ports import RobotApiError

logger = logging.getLogger("fleet.console")

#: 3 x 1.5 s stays inside the old single 5 s wait (HttpRobotClient default).
ESTOP_ATTEMPTS = 3
ESTOP_ATTEMPT_S = 1.5


async def deliver(scatter: Callable[[str], Awaitable[dict]], robot_id: str) -> dict:
    """One robot's stop, re-sent while it goes unanswered."""
    for attempt in range(1, ESTOP_ATTEMPTS + 1):
        try:
            return await asyncio.wait_for(scatter(robot_id), ESTOP_ATTEMPT_S)
        except (RobotApiError, HubError):
            raise
        except Exception:
            if attempt == ESTOP_ATTEMPTS:
                raise
            logger.warning("estop to %s not answered (attempt %d); sending again", robot_id, attempt)
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
