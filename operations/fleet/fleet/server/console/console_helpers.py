"""Gather, goal admission, and lifecycle helpers for ``FleetConsole``."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional
from urllib.parse import urlsplit

from fleet.hub.hub import HubError
from fleet.localization import trust
from fleet.server import bays
from fleet.server.console_view import _error_of, _shown, classify_link, link_reason
from fleet.swarm.session_arming import require_capability
from fleet.swarm.transport import RobotApiError

#: A robot whose read fails within this many seconds of its last answer is shown as
#: `degraded` (responding late), not `unreachable`; decisions still see online=False.
LINK_DEGRADED_S = 10.0
logger = logging.getLogger("fleet.console")


async def snapshot(self) -> dict:
    """N대 상태를 한 번에 모은다. 한 대가 죽어도 나머지는 그대로 온다."""
    order = list(self._order)
    results = await asyncio.gather(
        *(self._gather_state(rid) for rid in order),
        return_exceptions=True,
    )
    statuses = {}
    provider = self._link_address_status
    if provider is not None:
        try:
            statuses = provider() or {}
        except Exception:
            statuses = {}
    robots = []
    for robot_id, result in zip(order, results):
        goal_item = self._goals.get(robot_id)
        queued = self._queued.get(robot_id)
        if isinstance(result, BaseException):
            robots.append({"robot_id": robot_id, "online": False, "goal": goal_item,
                           "queued": _shown(queued), "error": _error_of(result),
                           "state": None, "gather_source": None})
            last_ok = self._last_ok.get(robot_id)
            if last_ok is not None and 0.0 <= self._clock() - last_ok <= LINK_DEGRADED_S:
                # One missed read is not a lost robot: the console showed every slow answer
                # (site 2026-10-09, 3-5 s gathers on loaded robots) as offline and back.
                # `online` stays False for every decision; only the link word changes.
                robots[-1]["link_degraded_s"] = round(self._clock() - last_ok, 1)
        else:
            state, source = result
            hub_row = self._hub.registry.find(robot_id) if source == "hub" else None
            if (hub_row is not None and hub_row.online and hub_row.snapshot is not None
                    and hub_row.last_heartbeat_monotonic is not None
                    and self._clock() - hub_row.last_heartbeat_monotonic
                    < self._hub_state_max_age_s):
                state = hub_row.snapshot.model_dump(mode="json")
            # D-493: 이 상태가 관찰된 단조 시각. gathered()가 나이로 바꾸고 지운다.
            observed = (hub_row.last_heartbeat_monotonic if hub_row is not None else None)
            if observed is None:
                observed = self._clock()
            self._last_ok[robot_id] = self._clock()
            robots.append({"robot_id": robot_id, "online": True, "goal": goal_item,
                           "queued": _shown(queued), "error": None,
                           "state": state, "gather_source": source,
                           "_state_mono": observed})
        row = robots[-1]
        scheme = urlsplit(self._registered_endpoints.get(robot_id, "")).scheme
        exc = result if isinstance(result, BaseException) else None
        link = classify_link(exc, scheme=scheme, address_status=statuses.get(robot_id))
        if link == "unreachable" and "link_degraded_s" in row:
            link = "degraded"
        if link is not None:
            row["link"] = link
        reason = link_reason(exc, scheme=scheme)
        if reason is not None:
            row["link_reason"] = reason
    self._remember(robots)
    shown = await asyncio.gather(*(self._shown_capabilities(r["robot_id"])
                                   for r in robots if r["online"]))
    caps = iter(shown)
    for row in robots:
        row["capabilities"] = next(caps) if row["online"] else None
    await self._handoff_dead_leader(robots)
    await self._run_traffic(robots)
    await self._manage_swarm_speed(robots)
    # 교통 정리가 대기 미션을 내려보냈으면 이 스냅샷이 이미 그 뒤다. 행을 다시 읽지
    # 않으면 화면은 방금 출발한 미션을 한 주기 동안 계속 "대기 중"으로 보여 준다.
    for row in robots:
        row["queued"] = _shown(self._queued.get(row["robot_id"]))
        row["goal"] = self.goal_leases.view(row["robot_id"], self._goals.get(row["robot_id"]))
        row["yielding"] = self._yielding.get(row["robot_id"])
        hold = self._held.get(row["robot_id"])
        row["held"] = hold["reason"] if hold is not None else None
        view = self._localization_view
        row["localization"] = trust.badge(
            row["state"], view(row["robot_id"]) if view is not None else None,
            lapsed=self._lapsed(row["robot_id"]))
    online = sum(1 for r in robots if r["online"])
    if self._signals is not None:
        # 신호등 갱신은 로봇 gather 뒤에서, 그리고 실패해도 로봇 상태를 흔들지 않는다.
        try:
            await self._signals.refresh()
        except Exception:
            pass
    return {
        "fleet": {"name": self.fleet_name, "online": online, "total": len(robots), **self.control_unit},
        "robots": robots,
        "signals": self._signals.snapshot() if self._signals is not None else {},
        "alarms": self.alarms(),
        "ts": self._clock(),
    }


async def map(self) -> Optional[dict]:
    """사이트가 공유하는 점유 격자. 응답한 첫 로봇 것을 쓰고 잠깐 물고 있는다.

    격자를 로봇마다 받아 오면 N배의 트래픽이 되고, 어차피 같은 맵이면 같은 그림이다.
    누구도 주지 못하면 `None` 이다 — UI 는 맵 없이도 목록을 띄워야 한다.
    """
    now = self._clock()
    if self._map is not None and now - self._map_at < self._map_ttl_s:
        return self._map
    for robot_id in list(self._order):
        if robot_id not in self._clients:
            continue
        try:
            grid = await self._client(robot_id).map()
        except Exception:
            continue
        if grid:
            self._map = grid
            self._map_at = now
            return grid
    return None


async def goal(self, robot_id: str, x: float, y: float, yaw: float = 0.0, *,
               task_id: str | None = None, attempt_id: str | None = None,
               attempt_seq: int | None = None, lease_source: str | None = None) -> dict:
    if robot_id in self._goal_busy:
        raise HubError("COMMAND_REJECTED", f"{robot_id} has a goal pipeline in flight")
    self._goal_busy.add(robot_id)
    try:
        return await self._goal(robot_id, x, y, yaw, task_id=task_id, attempt_id=attempt_id,
                                attempt_seq=attempt_seq, lease_source=lease_source)
    finally:
        self._goal_busy.discard(robot_id)


async def _goal(self, robot_id: str, x: float, y: float, yaw: float, *,
                task_id: str | None, attempt_id: str | None,
                attempt_seq: int | None, lease_source: str | None) -> dict:
    """한 대에 목표 하나. 로봇은 원자 액션만 받는다 (D-12).

    내려간 뒤 그 로봇의 계획 경로를 읽어, 이미 달리는 다른 로봇의 경로와 부딪히면
    취소하고 대기열에 넣는다. 경로는 목표를 받은 뒤에야 생기므로 순서가 이렇다 —
    되돌리는 비용은 로봇이 아직 거의 움직이지 않았을 때 취소 한 번이다.

    양보는 늘 **나중에 내려온 미션** 쪽이다. 달리던 로봇을 세우면 좁은 통로 한가운데
    멈춘 장애물이 하나 생길 뿐이고, 그 로봇이 비켜설 자리는 애초에 없다.

    달리는 로봇이 아니라 **서 있는 로봇**이 길을 막고 있으면 순서로는 풀리지 않는다.
    그때는 `bays` 로 비켜설 자리를 찾아 그 로봇을 먼저 치운다 (`_make_room`).
    """
    admission = self._goal_admission
    client = self._client(robot_id)
    stop = self.goal_leases.stop_token(robot_id)
    caps = await require_capability(client, "navigation.goal_navigation")
    if self._clients.get(robot_id) is not client:
        raise RuntimeError("robot connection changed during capability check")
    if stop != self.goal_leases.stop_token(robot_id):
        raise HubError("COMMAND_REJECTED", f"{robot_id} stopped during goal admission")
    if robot_id in self._formation_members():
        # 팔로워는 리더 pose 를 따라가는 중이다. 여기에 목표를 따로 내리면 로봇 안에서
        # 두 임자가 같은 바퀴를 두고 다툰다 - 대형을 풀고 보내라고 돌려준다.
        raise HubError("FORMATION_ACTIVE",
                       f"{robot_id} is in the running formation; stop it first")
    yielding = self._yielding.get(robot_id)
    decision = admission.yield_hold(yielding)
    if decision is not None:
        # 이 로봇은 남을 지나가게 하려고 비켜서는 중이다. 지금 다른 데로 보내면 방금
        # 비운 통로를 다시 막고, 그 통로를 기다리던 미션은 영영 못 나간다. 세워 둔다.
        self._queued[robot_id] = admission.mission_of(
            decision, x, y, yaw, task_id=task_id, attempt_id=attempt_id,
            attempt_seq=attempt_seq)
        return admission.response_of(decision)
    state, _source = await self._gather_state(robot_id)
    if self._clients.get(robot_id) is not client:
        raise RuntimeError("robot connection changed during localization check")
    if stop != self.goal_leases.stop_token(robot_id):
        raise HubError("COMMAND_REJECTED", f"{robot_id} stopped during goal admission")
    self._seen.pop(robot_id, None)
    self._remember([{"robot_id": robot_id, "state": state}])
    if self._verdict(robot_id) == trust.UNTRUSTED:
        # D-395: an unlocalized robot gets no goal (CORE would refuse it); it waits for LOCALIZED.
        self._claims.pop(robot_id, None)
        decision = admission.untrusted_self_hold(robot_id)
        self._queued[robot_id] = admission.mission_of(
            decision, x, y, yaw, task_id=task_id, attempt_id=attempt_id,
            attempt_seq=attempt_seq)
        return admission.response_of(decision)
    if robot_id in self._formation_members():
        raise HubError("FORMATION_ACTIVE", f"{robot_id} joined a formation during goal admission")
    if lease_source != "trip" and (busy := self.trip_refusal([robot_id])):
        raise busy
    result = await self.goal_leases.send(robot_id, client, caps, x, y, yaw, attempt_id, lease_source, task_id)
    if result["accepted"] is False:
        return result
    # 로봇이 받아들인 뒤에만 기억한다 — 거절된 목표가 화면에 남으면 운영자는 가지도
    # 않을 곳으로 로봇이 간다고 읽는다.
    self._goals[robot_id] = {"x": x, "y": y, "yaw": yaw}
    self._queued.pop(robot_id, None)

    async with self._traffic_lock:
        try:
            route = await self._route_of(robot_id)
            self.goal_leases.check_stop(robot_id, stop)
            blocker, conflict = self._claim_blocker(robot_id, route)
            if blocker is not None:
                stop = (stop[0], stop[1] + 1)  # Only this traffic cancel may advance the token.
                cancel_receipt = await self.goal_leases.cancel(robot_id, self._client(robot_id))
                self.goal_leases.check_stop(robot_id, stop)
                if not self._cancel_confirmed(cancel_receipt):
                    raise RuntimeError("navigation goal cancellation was not confirmed")
                self._goals.pop(robot_id, None)
                self._claims.pop(robot_id, None)
                decision = (admission.route_conflict_hold if conflict else admission.map_frame_hold)(blocker, route)
                # 선착 순서(누가 공유 충돌 지점에 먼저 도달하나)는 이 경로 위의 남은
                # 거리로 재 단다. 취소하면 로봇이 경로를 잃으므로 미션에 묻어 둔다.
                self._queued[robot_id] = admission.mission_of(
                    decision, x, y, yaw, task_id=task_id, attempt_id=attempt_id,
                    attempt_seq=attempt_seq)
                return admission.response_of(decision)

            await self._observe()
            self.goal_leases.check_stop(robot_id, stop)
            intended = self._intended_route(robot_id, route, x, y)
            untrusted = next((rid for rid in self._order
                              if rid != robot_id and self._untrusted_blocks(rid, intended)), None)
            if untrusted is not None:
                # D-395 P2-2: an unlocalized robot is a wide obstacle, never sent to a bay.
                stop = (stop[0], stop[1] + 1)
                cancel_receipt = await self.goal_leases.cancel(robot_id, self._client(robot_id))
                self.goal_leases.check_stop(robot_id, stop)
                if not self._cancel_confirmed(cancel_receipt):
                    raise RuntimeError("navigation goal cancellation was not confirmed")
                self._goals.pop(robot_id, None)
                self._claims.pop(robot_id, None)
                decision = admission.untrusted_blocker_hold(untrusted, intended)
                self._queued[robot_id] = admission.mission_of(
                    decision, x, y, yaw, task_id=task_id, attempt_id=attempt_id,
                    attempt_seq=attempt_seq)
                return admission.response_of(decision)
            grid = bays.Grid.from_payload(await self.map())
            self.goal_leases.check_stop(robot_id, stop)
            standing = self._standing_in_the_way(robot_id, intended, grid, (x, y))
            if standing:
                return await self._make_room(
                    robot_id, x, y, yaw, intended, standing,
                    task_id=task_id, attempt_id=attempt_id, attempt_seq=attempt_seq,
                )
            self._claims[robot_id] = route
            return result
        except (HubError, RobotApiError) as exc:
            raise RuntimeError("traffic refusal after mover dispatch; result remains unknown") from exc


def hold_robot(self, robot_id: str, reason: str) -> None:
    """The pinned address is unverified: the client sends stop requests only.

    Traffic keeps the robot as a blocked obstacle at its last pose/claimed route,
    so overlapping dispatches queue behind it; a moving robot raises an alarm.
    """
    if robot_id not in self._clients:
        return
    members = self._formation_members()
    in_formation = bool(members) and (robot_id in members
                                      or robot_id == self._formation_leader)
    moving = (robot_id in self._goals or robot_id in self._claims
              or robot_id in self._queued or in_formation)
    previous = self._held.get(robot_id) or {}
    if robot_id not in self._claims:
        pose = self._pose_of(robot_id)
        if pose is not None:
            self._claims[robot_id] = [pose]
    self._held[robot_id] = {
        "reason": reason, "alarm": bool(previous.get("alarm")) or moving,
        "formation": bool(previous.get("formation")) or in_formation,
    }


def release_robot(self, robot_id: str) -> None:
    if self._held.pop(robot_id, None) is not None:
        self._claims.pop(robot_id, None)


async def stop_held_formation(self) -> None:
    """A held formation member gets a stop request at its pinned address, then the
    formation is dissolved (D-361 3)."""
    members = self._formation_members()
    if not members:
        return
    held = [rid for rid, hold in list(self._held.items()) if hold.get("formation")
            and (rid in members or rid == self._formation_leader)]
    for hold in self._held.values():
        hold["formation"] = False  # a flag from an older formation must not end a new one
    if not held:
        return
    for robot_id in held:
        try:
            await self._client(robot_id).estop()
        except Exception as exc:
            logger.warning("stop request to held robot %s failed: %s", robot_id, exc)
    await self.formation_stop()


def alarms(self) -> list[dict]:
    rows = [{"robot_id": rid, "code": "ROBOT_ADDRESS_UNVERIFIED", "reason": hold["reason"]}
            for rid, hold in sorted(self._held.items()) if hold.get("alarm")]
    for source in self.alarm_sources:
        rows.extend(source())
    return rows


async def aclose(self) -> None:
    await self._capability_display.aclose()
    for client in list(self._clients.values()):
        closer: Any = getattr(client, "aclose", None)
        if closer is not None:
            await closer()
    if self._signals is not None:
        await self._signals.aclose()
