"""FleetConsole 교통 중재 보조 함수 — 상태 기억·군집 저하 감속·스냅샷 대기열 해제·국소화 보류."""

from __future__ import annotations

import logging
import math
from typing import Optional, Sequence

from fleet.server.degraded_reroute import reroute_degraded

logger = logging.getLogger("fleet.console")


def remember_traffic_states(console, robots: Sequence[dict], *, trust_mod) -> None:
    for row in robots:
        if row["robot_id"] not in console._clients:
            continue
        state = row.get("state") or {}
        if state:
            robot_id = row["robot_id"]
            console._seen[robot_id] = state
            if state.get("map_id") is not None:  # D-1010: the last frame this robot confirmed
                console._robot_maps[robot_id] = state["map_id"]
            if console._state_sink is not None:
                try:
                    console._state_sink(robot_id, state)
                except Exception:   # never let the sink skip the trust update below
                    logger.debug("state sink failed for %s", robot_id, exc_info=True)
            if state.get("localization") is not None:
                console._loc_null_since[robot_id] = None
            elif robot_id in console._loc_null_since:
                since = console._loc_null_since[robot_id]
                if since is None:
                    console._loc_null_since[robot_id] = console._clock()
                elif console._clock() - since >= trust_mod.LAPSED_GRACE_S:
                    # Expire the stale position; missing localization remains untrusted.
                    del console._loc_null_since[robot_id]
                    console._trusted.pop(robot_id, None)
            trusted = trust_mod.trusted_xy(state)
            if trusted is not None:
                console._trusted[robot_id] = trusted


async def read_trusted_map_pose(
    console, robot_id: str, *, trust_mod,
) -> Optional[tuple[float, float, Optional[float]]]:
    state, _source = await console._gather_state(robot_id)
    console._remember([{"robot_id": robot_id, "state": state or {}}])
    if console._verdict(robot_id) != trust_mod.TRUSTED:
        return None
    pose = (state or {}).get("pose") or {}
    try:
        x, y = float(pose["x"]), float(pose["y"])
    except (KeyError, TypeError, ValueError):
        return None
    if not math.isfinite(x) or not math.isfinite(y):
        return None
    try:
        yaw = float(pose["yaw"])
    except (KeyError, TypeError, ValueError):
        yaw = None
    return x, y, (yaw if yaw is not None and math.isfinite(yaw) else None)


def resolve_robot_frame(console, robot_id: str) -> Optional[str]:
    current = (console._seen.get(robot_id) or {}).get("map_id")
    if current is not None:
        return current
    remembered = console._robot_maps.get(robot_id)
    if remembered is not None and robot_id not in console._robot_map_fallbacks:
        console._robot_map_fallbacks[robot_id] = True
        logger.warning("traffic: %s reports no map_id; comparing on its last confirmed %s",
                       robot_id, remembered)
    return remembered


async def manage_swarm_degraded_speed(console, robots: list) -> None:
    """ADR-1000: Down-sync swarm speed to the slowest degraded robot (FOR-004)."""
    session = console._formation
    if session is None or session.state != "RUNNING":
        return

    degraded_members = [
        row["robot_id"] for row in robots
        if row.get("state") and row["state"].get("capabilities_degraded")
        and row["robot_id"] in console._formation_members()
    ]
    if not degraded_members:
        return

    current_speed = session.spec.max_speed
    degraded_speed = max(0.05, current_speed * 0.5)
    if current_speed > degraded_speed + 0.01:
        try:
            await console.formation_reform(
                formation=session.spec.formation, max_speed=degraded_speed)
        except Exception as exc:
            logger.warning("auto speed reform failed: %s", exc)


async def run_snapshot_traffic(console, robots: list) -> None:
    """스냅샷마다 한 번: 끝난 로봇의 점유를 풀고, 풀린 자리의 대기 미션을 내려보낸다."""
    degraded = await reroute_degraded(console, robots)  # ADR-1000 MSN-004

    for row in robots:
        state = row.get("state") or {}
        if state.get("navigation") != "NAVIGATING" and row["robot_id"] not in console._held:
            console._claims.pop(row["robot_id"], None)
    for robot_id in sorted(console._yielding):
        waiting_for = console._yielding[robot_id]["for"]
        if waiting_for not in console._claims and waiting_for not in console._queued:
            console._yielding.pop(robot_id, None)
    release_candidates = []
    for robot_id in sorted(console._queued):
        mission = console._queued[robot_id]
        if console._still_blocked(mission):
            if mission.get("reason") == "YIELDING":
                console._check_yield_worked(mission)
            continue
        if robot_id in degraded and mission.get("task_id") is None:
            continue
        release_candidates.append(robot_id)
    for robot_id in console._release_order(release_candidates):
        mission = console._queued.pop(robot_id, None)
        if mission is None or robot_id not in console._clients:
            continue
        if mission.get("task_id") is not None:
            if console._task_queue_release_callback is None:
                console._queued[robot_id] = mission
                continue
            try:
                await console._task_queue_release_callback(dict(mission))
            except Exception:
                console._queued[robot_id] = mission
            continue
        try:
            await console.goal(robot_id, mission["x"], mission["y"], mission["yaw"])
        except Exception:
            console._queued[robot_id] = mission


async def hold_robots_for_localization(console, mover: str, *, trust_mod) -> list[str]:
    held, last = [], console._trusted.get(mover)
    for robot_id in list(console._order):
        goal = console._goals.get(robot_id)
        here = console._pose_of(robot_id)
        route = ([here] if here is not None else []) + list(console._claims.get(robot_id) or [])
        if robot_id == mover or goal is None or not trust_mod.blocks(route, last):
            continue
        if not console._cancel_confirmed(await console.goal_leases.cancel(robot_id, console._client(robot_id))):
            raise RuntimeError("navigation goal cancellation was not confirmed")
        console._goals.pop(robot_id, None)
        console._claims.pop(robot_id, None)
        console._queued[robot_id] = {**goal, "blocked_by": mover, "waiting_on": [mover],
                                     "reason": "LOCALIZATION_UNTRUSTED"}
        held.append(robot_id)
    for robot_id, yielding in list(console._yielding.items()):     # on the way to a bay
        here, bay = console._pose_of(robot_id), (yielding["bay"]["x"], yielding["bay"]["y"])
        if robot_id == mover or not trust_mod.blocks(([here] if here else []) + [bay], last):
            continue
        if not console._cancel_confirmed(await console.goal_leases.cancel(robot_id, console._client(robot_id))):
            raise RuntimeError("navigation goal cancellation was not confirmed")
        console._yielding.pop(robot_id, None)
        held.append(robot_id)
    riders = console._formation_members() | ({console._formation_leader} - {None})
    if riders and (last is None or any(p is not None and trust_mod.blocks([p], last)
                                       for p in map(console._pose_of, riders))):
        await console.formation_stop()
        held.append("formation")
    return held
