"""FleetConsole 의 교통 중재 — 경로 점유·양보·국소화 보류 (console.py 믹스인).

하는 일 하나: 로봇들이 같은 길을 두고 부딪히지 않게 **누가 지금 갈 수 있나**를 정하는 메서드 묶음이다.
계획 경로 읽기, 서 있는 로봇 비키기(`bays`), 대기 미션 풀기, 국소화 신뢰 판정, 군집 속도 조정, 취소.
상태(`_claims`, `_queued`, `_yielding`, `_seen`, `_trusted` …)는 `FleetConsole.__init__` 이 소유하고,
이 클래스는 그 상태를 `self` 로 읽고 쓴다. 메서드 이름·시그니처·동작은 console.py 에 있을 때와 같다
(2026-11-01 D-766 크기 래칫 때문에 옮김; 순수 이동). trip_guard 가 `cancel` 을 인스턴스 속성으로 감싸므로
메서드 해석 순서만 바뀌고 호출 지점은 그대로다.

FleetConsole 은 `goal`/`_goal`(전송 순서)을 소유하고, 이 믹스인의 `_route_of`·`_remember`·`_verdict` 등을 부른다.
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Optional, Sequence

from fleet.hub.hub import HubError
from fleet.localization import trust
from fleet.server import bays, goal_admission, traffic
from fleet.server.observe import observe_states
from fleet.server.degraded_reroute import reroute_degraded  # noqa: F401
from fleet.server.traffic_arbitration_helpers import (
    hold_robots_for_localization,
    manage_swarm_degraded_speed,
    read_trusted_map_pose,
    remember_traffic_states,
    resolve_robot_frame,
    run_snapshot_traffic,
)
from fleet.swarm.session_arming import require_capability

logger = logging.getLogger("fleet.console")


class TrafficArbitration:
    """Mixin of `FleetConsole`: traffic arbitration, yielding and localization holds."""

    def _intended_route(self, mover: str, route: Sequence, x: float, y: float) -> list:
        """계획 경로. 아직 없으면 지금 자리에서 목표까지 직선으로 대신한다."""
        if route:
            return traffic.thin(list(route))
        here = self._pose_of(mover)
        if here is None:
            return []
        span = math.dist(here, (x, y))
        steps = max(1, int(span / traffic.SAMPLE_STEP_M))
        return [(here[0] + (x - here[0]) * i / steps,
                 here[1] + (y - here[1]) * i / steps) for i in range(steps + 1)]

    def _standing_in_the_way(self, mover: str, route: Sequence, grid,
                             goal: tuple) -> list[str]:
        """이 경로 위에 **서서** 길을 막은 로봇들. 순서로는 풀리지 않는 쪽이다."""
        if not route:
            return []
        out = []
        here = self._pose_of(mover)
        for robot_id in self._order:
            if (robot_id == mover or robot_id in self._claims
                    or self._verdict(robot_id) == trust.UNTRUSTED):
                continue
            pose = self._pose_of(robot_id)
            if pose is None:
                continue
            if here is not None and traffic.coincident(pose, here):
                # 출발점과 같은 보고는 길을 막은 로봇이 아니라 측위가 안 된 겹침이다 (D-116).
                continue
            if self._map_mismatch(mover, robot_id):
                # D-1010: its pose is another frame's numbers, so this route-versus-pose
                # verdict would be fiction. It stays a blocker for a human, never moved.
                out.append(robot_id)
                continue
            nearest = bays.nearest_on_route(route, pose)
            if nearest is None or math.dist(nearest, pose) >= self._yield_keep_out_m:
                continue
            if grid is None and math.dist(pose, goal) >= self._goal_blocked_m:
                continue
            out.append(robot_id)
        return out

    async def _make_room(self, mover: str, x: float, y: float, yaw: float,
                         route: Sequence, standing: Sequence[str], *,
                         task_id: str | None = None, attempt_id: str | None = None,
                         attempt_seq: int | None = None) -> dict:
        """길을 막고 선 로봇들을 비켜세우고, 미션은 자리가 날 때까지 세워 둔다."""
        standing = list(standing)
        stop = self.goal_leases.stop_token(mover)
        grid = bays.Grid.from_payload(await self.map())
        self.goal_leases.check_stop(mover, stop)
        yielded, no_space = [], []
        for robot_id in standing:
            pose = self._pose_of(robot_id)
            bay = None if pose is None or self.trip_busy(robot_id) or robot_id in self._goal_busy \
                or self._map_mismatch(mover, robot_id) else await asyncio.to_thread(
                    bays.best_bay, grid, route, pose, keep_out_m=self._yield_keep_out_m)
            self.goal_leases.check_stop(mover, stop)
            if bay is None:
                no_space.append(robot_id)
                continue
            await self._send_to_bay(robot_id, bay, mover)
            self.goal_leases.check_stop(mover, stop)
            yielded.append(robot_id)

        stop = (stop[0], stop[1] + 1)
        cancel_receipt = await self.goal_leases.cancel(mover, self._client(mover))
        self.goal_leases.check_stop(mover, stop)
        if not self._cancel_confirmed(cancel_receipt):
            raise RuntimeError("navigation goal cancellation was not confirmed")
        self._goals.pop(mover, None)
        self._claims.pop(mover, None)
        reason = "NO_YIELD_SPACE" if no_space else "YIELDING"
        blocked_by = (no_space or yielded)[0]
        decision = goal_admission.standing_hold(blocked_by, standing, reason, route)
        self._queued[mover] = goal_admission.mission_of(
            decision, x, y, yaw, task_id=task_id, attempt_id=attempt_id,
            attempt_seq=attempt_seq)
        return {**goal_admission.response_of(decision),
                "yielding": yielded, "no_space": no_space}

    async def _send_to_bay(self, robot_id: str, bay: tuple, mover: str) -> None:
        if robot_id in self._goal_busy:
            raise HubError("COMMAND_REJECTED", f"{robot_id} has a goal pipeline in flight")
        self._goal_busy.add(robot_id)
        try:
            await self._bay_goal(robot_id, bay, mover)
        finally:
            self._goal_busy.discard(robot_id)

    async def _bay_goal(self, robot_id: str, bay: tuple, mover: str) -> None:
        """한 대를 비켜설 자리로. 제 미션이 있었다면 대기열에 넣어 돌아오게 한다."""
        client = self._client(robot_id)
        stop = self.goal_leases.stop_token(robot_id)
        mover_stop = self.goal_leases.stop_token(mover)
        caps = await require_capability(client, "navigation.goal_navigation")
        if self._clients.get(robot_id) is not client:
            raise RuntimeError("robot connection changed during capability check")
        if stop != self.goal_leases.stop_token(robot_id):
            raise HubError("COMMAND_REJECTED", f"{robot_id} stopped during yield admission")
        if robot_id in self._formation_members():
            raise HubError("FORMATION_ACTIVE", f"{robot_id} joined a formation while planning a yield")
        if busy := self.trip_refusal([robot_id]):
            raise busy
        self.goal_leases.check_stop(mover, mover_stop)
        try:
            result = await self.goal_leases.send(robot_id, client, caps, bay[0], bay[1], 0.0, None, "yield")
        except (Exception, asyncio.CancelledError):
            if mover_stop != self.goal_leases.stop_token(mover):
                try:
                    await self.goal_leases.cancel(robot_id, client)
                except Exception:
                    logger.exception("abandoned bay cancel for %s failed", robot_id)
            raise
        if mover_stop != self.goal_leases.stop_token(mover):
            await self.goal_leases.cancel(robot_id, client)
            self.goal_leases.check_stop(mover, mover_stop)
        if result["accepted"] is False:
            raise RuntimeError("navigation yield goal was rejected")
        own = self._goals.pop(robot_id, None)
        if own is not None and robot_id not in self._queued:
            self._queued[robot_id] = {**own, "blocked_by": mover, "waiting_on": [mover],
                                      "reason": "YIELDED"}
        self._claims.pop(robot_id, None)
        self._yielding[robot_id] = {"bay": {"x": bay[0], "y": bay[1]}, "for": mover}

    async def _observe(self) -> None:
        """미션을 내리는 순간의 좌표 읽기 — 활동/대기 로봇의 읽기 선택은 `observe.py`."""
        await observe_states(self)

    def _remember(self, robots: Sequence[dict]) -> None:
        remember_traffic_states(self, robots, trust_mod=trust)

    def _lapsed(self, robot_id: str) -> bool:
        """A robot that reported localization and is null inside its grace (a CORE restart)."""
        return self._loc_null_since.get(robot_id) is not None

    async def trusted_map_pose(self, robot_id: str) -> Optional[tuple[float, float, Optional[float]]]:
        """Fresh ``(x, y, yaw or None)`` only when this snapshot is LOCALIZED in the map frame."""
        return await read_trusted_map_pose(self, robot_id, trust_mod=trust)

    def _verdict(self, robot_id: str) -> str:
        """Trust only an explicit LOCALIZED map snapshot."""
        return trust.classify(self._seen.get(robot_id))

    def _map_mismatch(self, mover: str, robot_id: str) -> bool:
        """D-1010: only two robots on the same **known** map may share one crossing grid."""
        mover_map, other_map = self._frame_of(mover), self._frame_of(robot_id)
        return not (mover_map is not None and other_map is not None and mover_map == other_map)

    def _frame_of(self, robot_id: str) -> Optional[str]:
        return resolve_robot_frame(self, robot_id)

    def _claim_blocker(self, mover: str, route) -> tuple[Optional[str], bool]:
        """``(blocker, is_conflict)`` for a dispatched goal's route (D-1010)."""
        conflict = traffic.blocking_robot(route, self._claims, self._clearance_m, skip=(mover,))
        if conflict is not None:
            return conflict, True
        return next((rid for rid in sorted(self._claims)
                     if rid != mover and self._map_mismatch(mover, rid)), None), False

    def _untrusted_blocks(self, robot_id: str, route: Sequence) -> bool:
        return (self._verdict(robot_id) == trust.UNTRUSTED
                and trust.blocks(route, self._trusted.get(robot_id)))

    def _pose_of(self, robot_id: str) -> Optional[tuple]:
        if self._verdict(robot_id) == trust.UNTRUSTED:
            return self._trusted.get(robot_id)        # D-395 P2-2: skip the untrusted pose
        pose = (self._seen.get(robot_id) or {}).get("pose") or {}
        try:
            return float(pose["x"]), float(pose["y"])
        except (KeyError, TypeError, ValueError):
            return None

    async def _route_of(self, robot_id: str) -> list:
        """계획 경로. 읽지 못하면 빈 목록이다 — 모른다는 이유로 미션을 막지 않는다."""
        try:
            return traffic.route_points(await self._client(robot_id).navigation_path())
        except Exception:
            return []

    async def _manage_swarm_speed(self, robots: list) -> None:
        """ADR-1000: Down-sync swarm speed to the slowest degraded robot (FOR-004)."""
        await manage_swarm_degraded_speed(self, robots)

    async def _run_traffic(self, robots: list) -> None:
        """스냅샷마다 한 번: 끝난 로봇의 점유를 풀고, 풀린 자리의 대기 미션을 내려보낸다."""
        await run_snapshot_traffic(self, robots)

    def _release_order(self, candidates: Sequence[str]) -> list[str]:
        """대기 미션을 푸는 순서. 공유 충돌 지점까지 남은 경로 거리가 짧은 미션이 먼저 나간다."""
        def key(robot_id: str) -> tuple[float, str]:
            best = math.inf
            mine = self._queued[robot_id]
            mine_route = mine.get("route") or []
            mine_pose = self._pose_of(robot_id)
            for other in candidates:
                if other == robot_id:
                    continue
                pair = traffic.closest_points(mine_route, self._queued[other].get("route") or [])
                if pair is None:
                    continue
                d = traffic.remaining_distance(mine_route, mine_pose, pair[0])
                if d is not None and d < best:
                    best = d
            return (best, robot_id)

        return sorted(candidates, key=key)

    def _still_blocked(self, mission: dict) -> bool:
        """이 대기 미션이 아직 나가면 안 되는가. 묻기만 하고 아무것도 바꾸지 않는다."""
        if mission.get("reason") in ("YIELDING", "NO_YIELD_SPACE"):
            return self._route_still_occupied(mission)
        if mission.get("reason") == "LOCALIZATION_UNTRUSTED":
            return (self._verdict(mission["blocked_by"]) == trust.UNTRUSTED
                    if "route" not in mission
                    else self._untrusted_blocks(mission["blocked_by"], mission["route"]))
        blocker = mission["blocked_by"]
        return blocker in self._claims or blocker in self._queued

    def _check_yield_worked(self, mission: dict) -> None:
        """비켜섰는데도 길이 안 열렸으면, 화면이 그렇게 말하게 한다."""
        if any((self._seen.get(rid) or {}).get("navigation") == "NAVIGATING"
               for rid in mission.get("waiting_on", [])):
            return          # 아직 비켜서는 중이다
        mission["settled_ticks"] = mission.get("settled_ticks", 0) + 1
        if mission["settled_ticks"] >= self._yield_grace_ticks:
            mission["reason"] = "NO_YIELD_SPACE"

    def _route_still_occupied(self, mission: dict) -> bool:
        """비켜서라고 한 로봇들이 아직 내 경로 위에 있는가."""
        route = mission.get("route") or []
        if not route:
            return False
        for robot_id in mission.get("waiting_on", []):
            if (self._seen.get(robot_id) or {}).get("navigation") == "NAVIGATING":
                return True          # 아직 비켜서는 중이다
            pose = self._pose_of(robot_id)
            if pose is None:
                continue
            nearest = bays.nearest_on_route(route, pose)
            if nearest is not None and math.dist(nearest, pose) < self._yield_keep_out_m:
                return True
        return False

    async def cancel(self, robot_id: str) -> dict:
        result = await self.goal_leases.cancel(robot_id, self._client(robot_id))
        self._goals.pop(robot_id, None)
        self._held.get(robot_id) or self._claims.pop(robot_id, None)  # D-361: held keeps its claim
        self._queued.pop(robot_id, None)
        self._yielding.pop(robot_id, None)
        return result

    async def hold_for_localization(self, mover: str) -> list[str]:
        """D-395 P2-7: before CORE moves an unlocalized `mover`, stop the Fleet-driven robots
        its keep-out reaches (`trust.blocks`, the whole track when it was never trusted)."""
        return await hold_robots_for_localization(self, mover, trust_mod=trust)
