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
        marker_clearance = getattr(console, "_site_marker_clearance", None)
        if marker_clearance is not None:
            marker_clearance.link(row)
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
            getattr(console, "_site_claims", {}).pop(row["robot_id"], None)
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


def _finite_number(val) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(val)


def site_route_for(console, mover: str, route: Sequence, *, trust_mod) -> Optional[tuple[str, list[tuple[float, float]]]]:
    """Map `mover`'s CORE-frame `route` onto the active site map when both frames are LOCALIZED."""
    provider = getattr(console, "_site_mover_pose", None)
    if provider is None or not route or console._verdict(mover) != trust_mod.TRUSTED:
        return None
    mover_site = provider(mover)
    pose = (console._seen.get(mover) or {}).get("pose")
    if mover_site is None or not isinstance(pose, dict):
        return None
    vals = (pose.get("x"), pose.get("y"), pose.get("yaw"))
    if not all(_finite_number(v) for v in vals):
        return None
    active_map_id, sx, sy, syaw = mover_site
    lx, ly, lyaw = float(pose["x"]), float(pose["y"]), float(pose["yaw"])
    dyaw = syaw - lyaw
    c, s = math.cos(dyaw), math.sin(dyaw)
    pts_site = []
    for pt in route:
        try:
            px, py = pt[0], pt[1]
        except (TypeError, IndexError):
            return None
        if not (_finite_number(px) and _finite_number(py)):
            return None
        dx, dy = float(px) - lx, float(py) - ly
        pts_site.append((sx + c * dx - s * dy, sy + s * dx + c * dy))
    return active_map_id, pts_site


def site_frame_clear(console, other_id: str, site_route: Optional[tuple[str, list[tuple[float, float]]]],
                     keep_out_m: float, *, trust_mod) -> Optional[bool]:
    """Whether `other_id` is measured clear of `site_route` on the same active site map (None = unproven)."""
    provider = getattr(console, "_site_obstacle_pose", None)
    marker_clearance = getattr(console, "_site_marker_clearance", None)
    if site_route is None or provider is None:
        return marker_clearance.clear(console, other_id, None, keep_out_m, None) if marker_clearance is not None else None
    other = provider(other_id)
    if marker_clearance is not None:
        result = marker_clearance.clear(console, other_id, site_route, keep_out_m, other)
        if result is not None:
            return result
    if other is None or other[0] != site_route[0]:
        return None
    return not trust_mod.blocks(site_route[1], (other[1], other[2]), keep_out_m=keep_out_m)


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
        getattr(console, "_site_claims", {}).pop(robot_id, None)
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


def peer_proof(self, peers):
    provider = getattr(self, "_site_marker_clearance", None)
    if provider is None:
        return {}
    return {"peer_evidence": {rid: sample for rid in peers if (sample := provider.evidence(rid))}}


async def guarded_road_send(self, robot_id, points, goal, stop, site_route_of, send, *, grid_from, check_wait_prefix):
    from fleet.swarm.dispatch_guard import dispatch_guard

    await self._observe()
    grid = grid_from(await self.map()) if len(self._order) > 1 else None

    class PeerWait(Exception):
        pass

    def check():
        self.goal_leases.check_stop(robot_id, stop)
        wait = road_peer_wait(self, robot_id, points, goal, site_route_of, grid)
        if wait is not None:
            raise PeerWait(wait)
        if not check_wait_prefix(self, robot_id, points, site_route_of):
            raise PeerWait({"accepted": False, "queued": False, "dispatch_attempted": False,
                            "stage": "pre_dispatch_peer_check", "reason": "WAIT_PREFIX_UNVERIFIED"})

    try:
        check()
        with dispatch_guard(check, paths={"/api/v1/navigation/route", "/api/v1/navigation/bound-route"}):
            return await send()
    except PeerWait as exc:
        return exc.args[0]


def road_peer_wait(self, robot_id, route_points, goal, site_route_of, grid):

    here = self._pose_of(robot_id)
    if here is None or self._verdict(robot_id) != "trusted":
        return {"accepted": False, "queued": False, "reason": "LOCALIZATION_UNTRUSTED",
                "command_robot_id": robot_id, "blocked_by": robot_id, "waiting_on": [robot_id],
                "dispatch_attempted": False, "cancel_confirmed": False}
    route = [here] + [(p["x"], p["y"]) for p in route_points]
    site_route = site_route_of(route)
    peers = [rid for rid in self._order if rid != robot_id
             and self._untrusted_blocks(rid, route, site_route=site_route)]
    reason = "LOCALIZATION_UNTRUSTED"
    if not peers:
        blocker, conflict = self._claim_blocker(robot_id, route, site_route=site_route)
        if blocker is not None:
            peers = [blocker]
            reason = "ROUTE_CONFLICT" if conflict else "MAP_FRAME_MISMATCH"
        elif len(self._order) > 1:
            peers = self._standing_in_the_way(robot_id, route, grid, goal, site_route=site_route)
            reason = "YIELDING"
    if peers:
        return {"accepted": False, "queued": False, "reason": reason, **peer_proof(self, peers),
                "command_robot_id": robot_id, "blocked_by": peers[0], "waiting_on": peers,
                "stage": "pre_dispatch_peer_check", "site_route_map": site_route[0] if site_route else None,
                "dispatch_attempted": False, "cancel_confirmed": False}
