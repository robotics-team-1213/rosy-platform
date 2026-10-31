"""MSN-004: 능력이 저하된 로봇의 목표를 세우고 옮긴다(ADR-1000).

console.py 본체가 D-766 크기 래칫에 묶여 2026-10-31 이 판단과 함께 나왔다.
점유를 지우기 전에 로봇을 세운다. 세우지 못했는데 지우면 달리는 로봇이 다른 로봇의
경로 판단에서 사라진다. 확인이 없으면 다음 스냅샷에 다시 한다."""

from __future__ import annotations

import logging

logger = logging.getLogger("fleet.console")


async def reroute_degraded(console, robots: list) -> set[str]:
    """저하된 로봇을 세우고 그 목표를 다시 놓는다. 저하된 로봇 id를 돌려준다."""
    degraded = set()
    for row in list(robots):
        robot_id = row["robot_id"]
        if not (row.get("state") or {}).get("capabilities_degraded"):
            continue
        degraded.add(robot_id)
        if robot_id not in console._goals and robot_id not in console._queued:
            continue
        lease = console.goal_leases.get(robot_id) or {}  # cancel() pops it
        if robot_id in console._goals:
            try:
                receipt = await console.goal_leases.cancel(robot_id, console._client(robot_id))
            except Exception as exc:
                logger.warning("degraded %s: cancel failed: %s", robot_id, exc)
                continue
            if not console._cancel_confirmed(receipt):
                continue
        mission = console._queued.pop(robot_id, None)
        goal = console._goals.pop(robot_id, None)
        console._held.get(robot_id) or console._claims.pop(robot_id, None)  # D-361: held keeps its claim
        if goal is not None and lease.get("task_id") is not None:
            # 작업 목표는 즉석 목표로 다른 로봇에 넘기지 않고 작업 대기열로 돌린다.
            goal = {**goal, "task_id": lease["task_id"]}
        target = mission or goal
        if not target:
            continue
        # _goals 항목에는 대기 필드가 없다. 없으면 _still_blocked가 KeyError를 낸다.
        target = {"blocked_by": None, "waiting_on": [], "reason": "CAPABILITIES_DEGRADED", **target}
        if target.get("task_id") is None:
            for alt_row in robots:
                alt_id = alt_row["robot_id"]
                busy = alt_id in console._goals or alt_id in console._queued or console.trip_busy(alt_id)
                if (alt_id != robot_id and alt_row.get("online") and not busy
                        and not (alt_row.get("state") or {}).get("capabilities_degraded")):
                    console._queued[alt_id] = target
                    break
            else:
                # 대신 갈 로봇이 없으면 버리지 않는다. 운영자가 대기열에서 본다.
                console._queued[robot_id] = target
            continue
        console._queued[robot_id] = target
    return degraded
