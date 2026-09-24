"""사이트 오케스트레이터의 관제 표면 — 모음(gather)과 흩뿌림(scatter).

역할 경계는 [사이트 미들웨어 역할 패브릭 설계](../../../../docs/plans/2026-09-14-site-middleware-role-fabric-design.md)
§2 가 정한다. 이 모듈이 하는 일은 등록된 로봇의 상태를 모으고, 원자 액션
(goal / cancel / e-stop)을 내리는 것뿐이다. 하지 않는 일:

- 로봇 ROS 토픽 구독, `cmd_vel` 생산 — 최종 속도는 로봇 안 CORE 만 낸다 (D-59 §5).
- 미션 DSL 을 로봇에 내려보내기 — 미션은 Fleet 쪽에 남는다 (D-12).
- 로봇 로컬 대시보드를 대신하는 척하기 — 그쪽은 한 대의 현장 화면이다 (D-23).

**v1 의 gather 는 폴링이다.** 설계 §3 의 최종 모음 경로는 로봇 `FleetAgent` 가 여는
outbound WS(heartbeat/event)지만, 그 에이전트는 Fleet 서버가 생긴 뒤에야 소켓을 연다
(설계 §7 3단계). 그때까지는 같은 계약의 REST 상태를 주기적으로 읽는다. 읽기만 하므로
역할 경계는 같고, 에이전트가 붙으면 `snapshot()` 의 출처만 바뀐다.

전송은 `fleet.swarm.transport` 의 `RobotClient` 하나만 쓴다 — 로봇 계약을 부르는
자리는 거기 한 곳이다.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Any, Callable, Optional, Sequence

logger = logging.getLogger("fleet.console")

from core_common.succession import next_leader
from fleet.formation.geometry import DEFAULT_SPACING, Formation
from fleet.hub.hub import HubError, SiteHub
from fleet.server import bays, traffic
from fleet.swarm.session import (
    FormationSession,
    FormationSpec,
    SessionError,
    SessionState,
)
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import RobotApiError, RobotClient

#: 맵은 로봇마다 다시 받을 이유가 없다 — 한 사이트는 한 맵을 공유한다. 그래도 SLAM 으로
#: 맵이 바뀔 수 있으므로 무한정 붙들지는 않는다.
MAP_TTL_S = 10.0


#: 대기 미션에서 화면에 보내지 않는 것. `route` 는 폴리라인이라 매 폴링마다 실어 보내면
#: 스냅샷이 통째로 불어나고, `settled_ticks` 는 양보가 멈췄는지 세는 내부 계수기다.
_INTERNAL_MISSION_KEYS = ("route", "settled_ticks")


def _shown(mission: Optional[dict]) -> Optional[dict]:
    if mission is None:
        return None
    return {k: v for k, v in mission.items() if k not in _INTERNAL_MISSION_KEYS}


def _error_of(exc: BaseException) -> dict:
    """예외를 UI 가 그대로 읽을 수 있는 모양으로. 로봇이 거절한 것과 닿지 못한 것을 가른다."""
    if isinstance(exc, RobotApiError):
        return {"reachable": True, "code": exc.code, "message": str(exc)}
    return {"reachable": False, "code": type(exc).__name__, "message": str(exc) or type(exc).__name__}


class FleetConsole:
    """robots.yaml 한 장에 적힌 N대를 하나의 관제 표면으로 묶는다."""

    def __init__(
        self,
        endpoints: Sequence[RobotEndpoint],
        clients: Sequence[RobotClient],
        *,
        clock: Callable[[], float] = time.monotonic,
        map_ttl_s: float = MAP_TTL_S,
        fleet_name: str = "rosy-site",
        clearance_m: float = traffic.DEFAULT_CLEARANCE_M,
        yield_keep_out_m: float = bays.YIELD_KEEP_OUT_M,
        relay_factory=None,
        signal_console=None,
    ) -> None:
        if len(endpoints) != len(clients):
            raise ValueError("endpoints and clients must line up one for one")
        self._clients: dict[str, RobotClient] = {
            ep.robot_id: client for ep, client in zip(endpoints, clients)
        }
        self._order = [ep.robot_id for ep in endpoints]
        self._clock = clock
        self._map_ttl_s = map_ttl_s
        self._map: Optional[dict] = None
        self._map_at = 0.0
        # 하달한 목표는 Fleet 이 기억한다. 로봇 상태 스냅샷에는 목표가 없고, 있어서도 안 된다
        # — 미션은 Fleet 쪽 개념이고 로봇은 원자 액션만 받는다 (D-12). 화면의 목표 표시는
        # "내가 무엇을 시켰는가"이지 로봇이 되돌려 준 값이 아니다.
        self._goals: dict[str, dict] = {}
        #: 달리는 로봇이 점유한 경로. 교행 판정의 재료이자, 왜 기다리는지의 근거다.
        self._claims: dict[str, list] = {}
        #: 남의 경로와 부딪혀 아직 못 내려간 미션. 앞이 비면 그대로 다시 내려간다.
        self._queued: dict[str, dict] = {}
        self._clearance_m = clearance_m
        self._yield_keep_out_m = yield_keep_out_m
        #: 비켜서라고 한 뒤 "안 움직인다"고 판단하기까지 참아 주는 스냅샷 수. 목표를 막
        #: 받은 로봇은 아직 NAVIGATING 을 보고하지 않는다 - 한 틱만 보면 시작도 하기 전에
        #: 실패로 읽는다.
        self._yield_grace_ticks = 3
        #: 상대가 목표 자리를 깔고 앉았다고 보는 거리. 두 대의 풋프린트 반지름(0.12+0.12)에
        #: 측위 몫을 조금 더한다 - 이보다 가까우면 그 자리에 설 수 없다.
        self._goal_blocked_m = 0.35
        #: 비켜서 있는 로봇 → 어디로, 누구를 위해. 화면이 "왜 저리로 갔는지"를 말하려면
        #: 필요하고, 비켜서기가 끝났는지 판단하는 데도 쓴다.
        self._yielding: dict[str, dict] = {}
        #: 마지막으로 본 로봇의 pose 와 주행 상태. 길을 막고 선 로봇을 찾으려면 좌표가
        #: 있어야 하는데, 로봇 상태는 스냅샷으로 들어온다.
        self._seen: dict[str, dict] = {}
        #: 열려 있는 대형 세션. 한 사이트에 하나다 - 같은 로봇이 두 대형에 들어가면
        #: 어느 리더를 따라야 하는지 로봇 쪽에서 정할 방법이 없다.
        self._formation = None
        self._formation_leader = None
        #: 시험이 가짜 릴레이를 끼우는 자리. 운용에서는 None 이라 세션의 기본값을 쓴다.
        self._relay_factory = relay_factory
        self.fleet_name = fleet_name
        # e-stop 은 hub 의 scatter 를 그대로 쓴다 — 흩뿌림의 규칙을 두 군데 두지 않는다.
        self._hub = SiteHub(list(endpoints), dict(self._clients), fleet_name=fleet_name)
        #: 신호등 컨트롤러(ROSY-SIGNAL-001). signals.yaml 이 없는 사이트도 같은 서버로
        #: 뜬다 — 없으면 신호등 기능은 조용히 비어 있다("signals": {}).
        self._signals = signal_console

    @property
    def robot_ids(self) -> list[str]:
        return list(self._order)

    def _client(self, robot_id: str) -> RobotClient:
        client = self._clients.get(robot_id)
        if client is None:
            raise HubError("UNKNOWN_ROBOT", robot_id)
        return client

    # --- gather ---------------------------------------------------------------

    async def snapshot(self) -> dict:
        """N대 상태를 한 번에 모은다. 한 대가 죽어도 나머지는 그대로 온다."""
        results = await asyncio.gather(
            *(self._client(rid).state() for rid in self._order),
            return_exceptions=True,
        )
        robots = []
        for robot_id, result in zip(self._order, results):
            goal = self._goals.get(robot_id)
            queued = self._queued.get(robot_id)
            if isinstance(result, BaseException):
                robots.append({"robot_id": robot_id, "online": False, "goal": goal,
                               "queued": _shown(queued), "error": _error_of(result),
                               "state": None})
            else:
                robots.append({"robot_id": robot_id, "online": True, "goal": goal,
                               "queued": _shown(queued), "error": None, "state": result})
        self._remember(robots)
        await self._handoff_dead_leader(robots)
        await self._run_traffic(robots)
        await self._manage_swarm_speed(robots)
        # 교통 정리가 대기 미션을 내려보냈으면 이 스냅샷이 이미 그 뒤다. 행을 다시 읽지
        # 않으면 화면은 방금 출발한 미션을 한 주기 동안 계속 "대기 중"으로 보여 준다.
        for row in robots:
            row["queued"] = _shown(self._queued.get(row["robot_id"]))
            row["goal"] = self._goals.get(row["robot_id"])
            row["yielding"] = self._yielding.get(row["robot_id"])
        online = sum(1 for r in robots if r["online"])
        if self._signals is not None:
            # 신호등 갱신은 로봇 gather 뒤에서, 그리고 실패해도 로봇 상태를 흔들지 않는다.
            try:
                await self._signals.refresh()
            except Exception:
                pass
        return {
            "fleet": {"name": self.fleet_name, "online": online, "total": len(robots)},
            "robots": robots,
            "signals": self._signals.snapshot() if self._signals is not None else {},
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
        for robot_id in self._order:
            try:
                grid = await self._client(robot_id).map()
            except Exception:
                continue
            if grid:
                self._map = grid
                self._map_at = now
                return grid
        return None

    # --- scatter --------------------------------------------------------------

    async def goal(self, robot_id: str, x: float, y: float, yaw: float = 0.0) -> dict:
        """한 대에 목표 하나. 로봇은 원자 액션만 받는다 (D-12).

        내려간 뒤 그 로봇의 계획 경로를 읽어, 이미 달리는 다른 로봇의 경로와 부딪히면
        취소하고 대기열에 넣는다. 경로는 목표를 받은 뒤에야 생기므로 순서가 이렇다 —
        되돌리는 비용은 로봇이 아직 거의 움직이지 않았을 때 취소 한 번이다.

        양보는 늘 **나중에 내려온 미션** 쪽이다. 달리던 로봇을 세우면 좁은 통로 한가운데
        멈춘 장애물이 하나 생길 뿐이고, 그 로봇이 비켜설 자리는 애초에 없다.

        달리는 로봇이 아니라 **서 있는 로봇**이 길을 막고 있으면 순서로는 풀리지 않는다.
        그때는 `bays` 로 비켜설 자리를 찾아 그 로봇을 먼저 치운다 (`_make_room`).
        """
        if robot_id in self._formation_members():
            # 팔로워는 리더 pose 를 따라가는 중이다. 여기에 목표를 따로 내리면 로봇 안에서
            # 두 임자가 같은 바퀴를 두고 다툰다 - 대형을 풀고 보내라고 돌려준다.
            raise HubError("FORMATION_ACTIVE",
                           f"{robot_id} is in the running formation; stop it first")
        yielding = self._yielding.get(robot_id)
        if yielding is not None:
            # 이 로봇은 남을 지나가게 하려고 비켜서는 중이다. 지금 다른 데로 보내면 방금
            # 비운 통로를 다시 막고, 그 통로를 기다리던 미션은 영영 못 나간다. 세워 둔다.
            self._queued[robot_id] = {"x": x, "y": y, "yaw": yaw,
                                      "blocked_by": yielding["for"],
                                      "waiting_on": [yielding["for"]], "reason": "YIELDED"}
            return {"accepted": True, "queued": True, "blocked_by": yielding["for"],
                    "reason": "YIELDED"}
        result = await self._client(robot_id).navigation_goal(x, y, yaw)
        # 로봇이 받아들인 뒤에만 기억한다 — 거절된 목표가 화면에 남으면 운영자는 가지도
        # 않을 곳으로 로봇이 간다고 읽는다.
        self._goals[robot_id] = {"x": x, "y": y, "yaw": yaw}
        self._queued.pop(robot_id, None)

        route = await self._route_of(robot_id)
        blocker = traffic.blocking_robot(route, self._claims, self._clearance_m, skip=(robot_id,))
        if blocker is not None:
            await self._client(robot_id).navigation_cancel()
            self._goals.pop(robot_id, None)
            self._claims.pop(robot_id, None)
            self._queued[robot_id] = {"x": x, "y": y, "yaw": yaw, "blocked_by": blocker,
                                      "waiting_on": [blocker], "reason": "ROUTE_CONFLICT",
                                      # 선착 순서(누가 공유 충돌 지점에 먼저 도달하나)는
                                      # 이 경로 위의 남은 거리로 재 단다. 취소하면 로봇이
                                      # 경로를 잃으므로 여기에 묻어 둔다.
                                      "route": list(route)}
            return {"accepted": True, "queued": True, "blocked_by": blocker}

        await self._observe()
        intended = self._intended_route(robot_id, route, x, y)
        grid = bays.Grid.from_payload(await self.map())
        standing = self._standing_in_the_way(robot_id, intended, grid, (x, y))
        if standing:
            return await self._make_room(robot_id, x, y, yaw, intended, standing)
        self._claims[robot_id] = route
        return result

    def _intended_route(self, mover: str, route: Sequence, x: float, y: float) -> list:
        """계획 경로. 아직 없으면 지금 자리에서 목표까지 직선으로 대신한다.

        경로는 목표를 받은 **뒤** 계획기가 내야 생긴다. 그 틈에 물으면 빈 목록이 오고,
        빈 목록은 "아무도 안 막는다"로 읽힌다 - 실측에서 폭 1 m 방의 둘째 미션이 그
        틈으로 나가 상대 0.19 m 앞까지 밀고 들어갔다. 관제가 막았다고 말한 통로였다.

        어디로 갈지는 몰라도 **어디서 어디로** 가는지는 안다. 직선은 실제 경로보다
        넓게 잡힐 수 있다. 폭이 넓다고 해서 경로 위의 로봇을 무시하지 않는다 (D-93).
        """
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
        """이 경로 위에 **서서** 길을 막은 로봇들. 순서로는 풀리지 않는 쪽이다.

        거르는 조건은 하나다 - 달리는 로봇은 뺀다. 그쪽은 경로 대 경로 판정이 이미 봤고,
        곧 지나갈 것을 붙잡고 비켜서라 할 이유가 없다.

        **폭은 묻지 않는다 (D-93).** 한때 "넓으면 알아서 돌아 가니 빼자"는 조건이 있었다.
        실측이 그것을 부정했다 - 6 x 6 m 빈 방에서 마주 오는 두 대가 3 번 다 한가운데에서
        맞물려 섰다. 면제가 성립하는 폭은 없다.

        과잉 개입을 막는 것은 **경로 자체**다. 계획 경로는 이미 아는 장애물을 피해 나오므로,
        넓은 곳에 선 로봇 옆으로는 애초에 0.45 m 안을 지나지 않는다. 그런데도 지난다면
        돌아갈 자리가 없다는 뜻이고, 그때는 중재가 맞다.

        "길을 막았다"의 반경은 `_route_still_occupied` 가 "이제 비켰다"를 판단하는 반경과
        **같은 값**이어야 한다. 경로 대 경로의 `clearance_m`(0.7) 을 여기 쓰면, 0.45 만
        비켜선 로봇이 다시 "막고 있다"로 잡혀 벽감에서 또 밀려난다 - 로봇 하나가 맵
        바깥으로 밀려날 때까지 이 왕복이 이어진다.
        """
        if not route:
            return []
        out = []
        here = self._pose_of(mover)
        for robot_id in self._order:
            if robot_id == mover or robot_id in self._claims:
                continue
            pose = self._pose_of(robot_id)
            if pose is None:
                continue
            if here is not None and traffic.coincident(pose, here):
                # 출발점과 같은 보고는 길을 막은 로봇이 아니라 측위가 안 된 겹침이다 (D-116).
                continue
            nearest = bays.nearest_on_route(route, pose)
            if nearest is None or math.dist(nearest, pose) >= self._yield_keep_out_m:
                continue
            if grid is None and math.dist(pose, goal) >= self._goal_blocked_m:
                # 맵이 없으면 중재할 수 없다 - 비켜설 자리를 고를 근거가 없으므로, 여기서
                # 막으면 모든 미션이 이유 없이 대기열로 간다. 로봇 쪽 지역 코스트맵은
                # 살아 있으니 그쪽에 맡긴다.
                #
                # 예외는 **목표를 깔고 앉은 경우**다. 그 자리에 두 대가 설 수 없다는 것은
                # 맵을 몰라도 참이고, 보내 봐야 도착하지 못한다.
                continue
            out.append(robot_id)
        return out

    async def _make_room(self, mover: str, x: float, y: float, yaw: float,
                         route: Sequence, standing: Sequence[str]) -> dict:
        """길을 막고 선 로봇들을 비켜세우고, 미션은 자리가 날 때까지 세워 둔다.

        미션을 실패로 돌려주지 않는 이유가 있다. 비켜서기는 몇 초짜리 동작이고, 그 몇 초
        때문에 운영자가 같은 미션을 다시 내려야 한다면 관제가 일을 떠넘기는 것이다.
        비켜설 자리가 없을 때도 마찬가지로 세워 둔다 - 다만 이유를 `NO_YIELD_SPACE` 로
        적어, 사람이 손을 대야 풀린다는 것을 화면이 말하게 한다.
        """
        grid = bays.Grid.from_payload(await self.map())
        yielded, no_space = [], []
        for robot_id in standing:
            pose = self._pose_of(robot_id)
            # 거리장 계산은 순수 계산이고 맵이 커지면 몇백 ms 가 된다(40x40 m, 20 m 경로에서
            # 0.38 s). 이벤트 루프에서 돌리면 그동안 다른 로봇의 폴링까지 같이 멈춘다.
            bay = None if pose is None else await asyncio.to_thread(
                bays.best_bay, grid, route, pose, keep_out_m=self._yield_keep_out_m)
            if bay is None:
                no_space.append(robot_id)
                continue
            await self._send_to_bay(robot_id, bay, mover)
            yielded.append(robot_id)

        await self._client(mover).navigation_cancel()
        self._goals.pop(mover, None)
        self._claims.pop(mover, None)
        reason = "NO_YIELD_SPACE" if no_space else "YIELDING"
        blocked_by = (no_space or yielded)[0]
        self._queued[mover] = {"x": x, "y": y, "yaw": yaw, "blocked_by": blocked_by,
                               "waiting_on": list(standing), "reason": reason,
                               "route": list(route)}
        return {"accepted": True, "queued": True, "blocked_by": blocked_by,
                "reason": reason, "yielding": yielded, "no_space": no_space}

    async def _send_to_bay(self, robot_id: str, bay: tuple, mover: str) -> None:
        """한 대를 비켜설 자리로. 제 미션이 있었다면 대기열에 넣어 돌아오게 한다."""
        own = self._goals.pop(robot_id, None)
        if own is not None and robot_id not in self._queued:
            # 비켜서는 것은 잠깐 물러나는 것이지 미션 취소가 아니다. 지나가는 대가 끝나면
            # 제 목표로 돌아간다 - 그러지 않으면 운영자가 보낸 곳에서 로봇이 사라진다.
            self._queued[robot_id] = {**own, "blocked_by": mover, "waiting_on": [mover],
                                      "reason": "YIELDED"}
        self._claims.pop(robot_id, None)
        await self._client(robot_id).navigation_goal(bay[0], bay[1], 0.0)
        self._yielding[robot_id] = {"bay": {"x": bay[0], "y": bay[1]}, "for": mover}

    async def _observe(self) -> None:
        """로봇 좌표를 새로 읽는다. 미션을 내리는 순간에만 부른다 - 폴링은 스냅샷이 한다."""
        results = await asyncio.gather(
            *(self._client(rid).state() for rid in self._order), return_exceptions=True)
        self._remember([
            {"robot_id": rid, "state": None if isinstance(r, BaseException) else r}
            for rid, r in zip(self._order, results)])

    def _remember(self, robots: Sequence[dict]) -> None:
        for row in robots:
            state = row.get("state") or {}
            if state:
                self._seen[row["robot_id"]] = state

    def _pose_of(self, robot_id: str) -> Optional[tuple]:
        pose = (self._seen.get(robot_id) or {}).get("pose") or {}
        try:
            return float(pose["x"]), float(pose["y"])
        except (KeyError, TypeError, ValueError):
            # 좌표를 모르는 로봇은 길을 막았다고도 비켰다고도 말할 수 없다.
            return None

    async def _route_of(self, robot_id: str) -> list:
        """계획 경로. 읽지 못하면 빈 목록이다 — 모른다는 이유로 미션을 막지 않는다."""
        try:
            return traffic.route_points(await self._client(robot_id).navigation_path())
        except Exception:
            return []

    async def _manage_swarm_speed(self, robots: list) -> None:
        """ADR-1000: Down-sync swarm speed to the slowest degraded robot (FOR-004)."""
        session = self._formation
        if session is None or session.state != "RUNNING":
            return

        degraded_members = [
            row["robot_id"] for row in robots
            if row.get("state") and row["state"].get("capabilities_degraded")
            and row["robot_id"] in self._formation_members()
        ]

        if not degraded_members:
            return

        # If any member is degraded, reform the swarm with a lower speed limit
        # This is a naive implementation that halves the current speed
        current_speed = session.spec.max_speed
        degraded_speed = max(0.05, current_speed * 0.5)

        # We only want to reform once when degradation is detected
        if current_speed > degraded_speed + 0.01:
            try:
                await self.formation_reform(
                    formation=session.spec.formation, max_speed=degraded_speed)
            except Exception as exc:
                # 조용한 no-op 는 ADR-1000 을 죽인다 — 실패는 보이게, 재시도
                # 폭주는 current_speed 가득 가드가 이미 막는다.
                logger.warning("auto speed reform failed: %s", exc)

    async def _run_traffic(self, robots: list) -> None:
        """스냅샷마다 한 번: 끝난 로봇의 점유를 풀고, 풀린 자리의 대기 미션을 내려보낸다."""
        # ADR-1000: Mission Re-routing (MSN-004) - check for degraded capabilities
        for row in list(robots):
            state = row.get("state") or {}
            robot_id = row["robot_id"]
            if state.get("capabilities_degraded"):
                if robot_id in self._goals or robot_id in self._queued:
                    # Cancel the current mission
                    mission = self._queued.pop(robot_id, None)
                    goal = self._goals.pop(robot_id, None)
                    self._claims.pop(robot_id, None)
                    target = mission or goal
                    if target:
                        # Find an idle alternative
                        for alt_row in robots:
                            alt_id = alt_row["robot_id"]
                            alt_state = alt_row.get("state") or {}
                            busy = alt_id in self._goals or alt_id in self._queued
                            if (alt_id != robot_id and alt_row.get("online")
                                    and not alt_state.get("capabilities_degraded")
                                    and not busy):
                                # Re-assign to alternative
                                self._queued[alt_id] = target
                                break

        for row in robots:
            state = row.get("state") or {}
            if state.get("navigation") != "NAVIGATING":
                self._claims.pop(row["robot_id"], None)
        for robot_id in sorted(self._yielding):
            # 비켜설 이유가 사라졌으면 표시도 지운다. 남겨 두면 그 로봇은 다음 미션을
            # 계속 대기열로 돌리고, 화면은 끝난 양보를 계속 진행 중으로 보여 준다.
            waiting_for = self._yielding[robot_id]["for"]
            if waiting_for not in self._claims and waiting_for not in self._queued:
                self._yielding.pop(robot_id, None)
        release_candidates = []
        for robot_id in sorted(self._queued):
            mission = self._queued[robot_id]
            if self._still_blocked(mission):
                if mission.get("reason") == "YIELDING":
                    self._check_yield_worked(mission)
                continue
            release_candidates.append(robot_id)
        # 한 번에 여러 대가 풀리면 순서를 정한다 — 로터리 선착. 점유 클레임은 상한선으로
        # 남는다(달리는 로봇은 이 순서와 무관하게 이긴다. 여기서 고르는 것은 대기자
        # 사이의 순서다).
        for robot_id in self._release_order(release_candidates):
            mission = self._queued[robot_id]
            self._queued.pop(robot_id, None)
            try:
                await self.goal(robot_id, mission["x"], mission["y"], mission["yaw"])
            except Exception:
                # 재하달이 실패하면 대기열에 되돌린다. 조용히 사라지면 운영자는 자기가
                # 내린 미션이 어디로 갔는지 알 수 없다.
                self._queued[robot_id] = mission

    def _release_order(self, candidates: Sequence[str]) -> list[str]:
        """대기 미션을 푸는 순서. 공유 충돌 지점까지 남은 경로 거리가 짧은 미션이 먼저
        나간다 — 도로의 선착 우권이다.

        점유 클레임은 이 순서 위에 있다. 달리는 로봇(클레임 있는 로봇)은 결코 여기서
        밀려나지 않고, 고르는 것은 대기자들 사이의 순서다. 거리를 모르면(경로나 좌표
        없음) 무한대로 밀려 robot_id 순으로 떨어진다 - 같은 상황이면 늘 같은 순서여야
        운영자가 화면을 읽을 수 있다.
        """
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
        """이 대기 미션이 아직 나가면 안 되는가. 묻기만 하고 아무것도 바꾸지 않는다.

        **비켜서기를 기다리는 미션은 기하로만 판단한다.** 남이 비켜 주기를 기다리는 A 와
        A 가 지나가기를 기다리는 B 는 서로를 블로커로 가리킨다 - "앞이 대기열에 있으면
        기다린다"를 양쪽에 걸면 둘 다 영원히 선다. A 는 "내 경로가 비었는가"만 보고,
        B 는 A 가 나간 뒤 A 의 점유가 풀리기를 기다린다. 그래서 고리가 끊긴다.
        """
        if mission.get("reason") in ("YIELDING", "NO_YIELD_SPACE"):
            return self._route_still_occupied(mission)
        blocker = mission["blocked_by"]
        # 앞이 아직 못 나갔으면 그 뒤도 못 나간다. 점유만 보면, 대기열에 들어간 순간
        # 점유가 없는 블로커를 "끝났다"고 읽고 뒤가 먼저 튀어 나간다.
        return blocker in self._claims or blocker in self._queued

    def _check_yield_worked(self, mission: dict) -> None:
        """비켜섰는데도 길이 안 열렸으면, 화면이 그렇게 말하게 한다.

        **이유를 바꾸는 것 말고는 아무것도 하지 않는다.** 로봇을 더 밀어내지 않는 이유는,
        한 번 비켜서고도 부족했다는 것이 곧 이 맵에 자리가 없다는 뜻이기 때문이다. 더
        멀리 보내면 벽에 붙을 때까지 같은 일이 반복된다.

        이 검사가 없으면 화면은 "물러나면 자동 출발합니다"를 영원히 띄운다 - 실측에서
        2x1 m 방의 두 대가 그 문장 아래서 한없이 서 있었다. 대기 자체는 맞다(물리가
        그렇다). 거짓말은 곧 풀린다고 말한 쪽이다.
        """
        if any((self._seen.get(rid) or {}).get("navigation") == "NAVIGATING"
               for rid in mission.get("waiting_on", [])):
            return          # 아직 비켜서는 중이다
        # 상태가 아직 안 올라온 첫 몇 틱을 "멈췄다"로 읽지 않는다.
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
        result = await self._client(robot_id).navigation_cancel()
        self._goals.pop(robot_id, None)
        self._claims.pop(robot_id, None)
        self._queued.pop(robot_id, None)
        self._yielding.pop(robot_id, None)
        return result

    async def estop_all(self) -> dict:
        """전 대상 정지. 한 대가 거절해도 나머지에 계속 내린다.

        빨리 실패하면 안 된다 — 닿지 않는 한 대 때문에 멈출 수 있었던 나머지가 계속
        움직이는 것이 이 버튼에서 가장 나쁜 결과다. 로봇 쪽 e-stop 과 deadman 은 관제와
        무관하게 살아 있다(설계 §3).
        """
        # 대형이 살아 있으면 먼저 푼다. 릴레이가 참조를 계속 밀어 넣는 채로 로봇만 세우면,
        # e-stop 을 푸는 순간 팔로워가 밀린 참조를 향해 달려나간다.
        if self._formation is not None and self._formation_members():
            try:
                await self._formation.stop()
            except Exception:
                pass
            self._formation_leader = None
        # 신호등의 all_red 는 로봇 정지와 병렬이다 — 순서를 정하는 동안 한쪽이 늦게
        # 간다. 어느 쪽이 실패했는지는 본문이 대신 말한다.
        signals_task = (asyncio.ensure_future(self._signals.all_red())
                        if self._signals is not None else None)
        results = await asyncio.gather(
            *(self._hub.scatter_estop(rid) for rid in self._order),
            return_exceptions=True,
        )
        rows = []
        for robot_id, result in zip(self._order, results):
            if isinstance(result, BaseException):
                # 이 대는 서지 않았다. 목표를 지우면 화면에서 "아무 데도 안 간다"로 보이지만
                # 실제로는 아직 가고 있을 수 있다 — 남겨 둔다.
                rows.append({"robot_id": robot_id, "stopped": False, "error": _error_of(result)})
            else:
                self._goals.pop(robot_id, None)
                self._claims.pop(robot_id, None)
                self._queued.pop(robot_id, None)
                self._yielding.pop(robot_id, None)
                rows.append({"robot_id": robot_id, "stopped": True, "result": result})
        signal_result = None
        if signals_task is not None:
            # 신호등 쪽 문제가 로봇 정지 보고를 집어삼키지 않는다 — 본문으로만 남긴다.
            try:
                signal_result = await signals_task
            except Exception as exc:
                signal_result = {"all_red": 0, "total": 0, "signals": [],
                                 "error": _error_of(exc)}
        return {"stopped": sum(1 for r in rows if r["stopped"]), "total": len(rows),
                "robots": rows, "signals": signal_result}

    # --- 신호등 (ROSY-SIGNAL-001) -------------------------------------------------

    async def signals_detail(self) -> dict:
        """신호별 상세. 캐시가 나갸 있으면 한 틱 돌려서 채운다(주기 제한은 콘솔 안에)."""
        if self._signals is None:
            raise HubError("NO_SIGNALS", "signals are not configured")
        try:
            await self._signals.refresh()
        except Exception:
            pass
        return {"signals": self._signals.snapshot()}

    async def signal_command(self, signal_id: str, body: dict) -> dict:
        if self._signals is None:
            raise HubError("NO_SIGNALS", "signals are not configured")
        return await self._signals.command(signal_id, body)

    # --- 대형 (FOR-004) --------------------------------------------------------

    def _formation_members(self) -> set:
        """개별 미션을 받으면 안 되는 로봇 = 팔로워.

        **리더는 넣지 않는다.** 대형은 리더를 몰아서 움직이는 것이고(D-20: 오케스트레이션은
        Fleet, 폐루프 추종은 로봇), 리더가 목표를 못 받으면 대형은 무장만 된 채 아무 데도
        가지 못한다. 팔로워는 반대다 - 리더 pose 를 따라가는 중이라 목표를 따로 받으면
        로봇 안에서 두 임자가 같은 바퀴를 두고 다툰다.
        """
        session = self._formation
        if session is None or session.state in (SessionState.STOPPED, SessionState.IDLE):
            return set()
        return set(session.assignment)

    def formation_status(self) -> dict:
        """화면이 읽는 대형 상태. 세션이 없으면 `active: False` 하나다."""
        session = self._formation
        if session is None:
            return {"active": False, "state": "IDLE"}
        stats = session.relay.stats() if session.relay is not None else None
        return {
            "active": session.state in (SessionState.ARMING, SessionState.RUNNING,
                                        SessionState.HOLDING),
            "state": session.state.value,
            "leader": self._formation_leader,
            "formation": session.spec.formation.value,
            "spacing": session.spec.spacing,
            "assignment": {rid: {"distance": slot.distance, "lateral": slot.lateral}
                           for rid, slot in session.assignment.items()},
            # HOLDING 인데 이유가 비어 있으면 운영자는 왜 멈췄는지 알 길이 없다.
            "reason": list(session.reason) if session.reason else None,
            "pending_triggers": [list(t) for t in session.pending_triggers],
            "relay": None if stats is None else {
                "paused": stats.paused,
                "leader_rx_hz": round(stats.leader_rx_hz, 2),
                "leader_age_s": stats.leader_age_s,
                "leader_last_error": stats.leader_last_error,
                "follower_tx": {k: v for k, v in stats.follower_tx.items()},
                "follower_tx_hz": {k: round(v, 2) for k, v in stats.follower_tx_hz.items()},
                "follower_connected": dict(stats.follower_connected),
                # 0 Hz 에 이유가 없으면 화면은 "그냥 멈춘 릴레이"만 보여 준다 — 팔로워
                # 소켓의 마지막 오류가 진단의 첫 줄이다(D-92 값 관례와 무관한 계약).
                "follower_last_error": dict(stats.follower_last_error),
            },
        }

    def _spec(self, formation: str, spacing, max_speed) -> FormationSpec:
        try:
            shape = Formation(formation)
        except ValueError as exc:
            raise HubError("UNKNOWN_FORMATION", f"{formation} is not a formation") from exc
        current = self._formation.spec if self._formation is not None else None
        if max_speed is None:
            max_speed = current.max_speed if current is not None else 0.15
        return FormationSpec(
            formation=shape,
            spacing=DEFAULT_SPACING if spacing is None else spacing,
            max_speed=max_speed,
        )

    async def formation_start(self, leader_id: str, formation: str = "COLUMN",
                              spacing=None, max_speed=None, members=None) -> dict:
        """리더와 선택된 팔로워로 대형을 연다(FOR-001 Robot Selection).

        이미 열려 있으면 거절한다. 조용히 갈아치우면 앞 세션의 팔로워가 무장된 채로
        남고, 그 로봇은 아무도 보내지 않는 참조를 기다리며 서 있게 된다.

        `members` 가 None 이면 등록된 나머지 전원이 팔로워다(기존 동작). 리스트면
        리더를 반드시 포함해야 하고, 그 안의 로봇만 대형에 들어가며 미선택 로봇은
        개별 미션을 계속 받는다.
        """
        if self._formation_members():
            raise HubError("FORMATION_ACTIVE", "a formation is already running; stop it first")
        if members is None:
            follower_ids = [rid for rid in self._order if rid != leader_id]
        else:
            member_ids = list(members)
            if len(set(member_ids)) != len(member_ids):
                raise HubError("MEMBER_DUPLICATED", "a formation lists a robot twice")
            if leader_id not in member_ids:
                raise HubError("LEADER_NOT_IN_MEMBERS",
                               f"leader {leader_id} must be among the selected members")
            unknown = [rid for rid in member_ids if rid not in self._clients]
            if unknown:
                raise HubError("UNKNOWN_ROBOT", f"unknown members: {', '.join(unknown)}")
            follower_ids = [rid for rid in member_ids if rid != leader_id]
        if not follower_ids:
            raise HubError("NO_FOLLOWERS", "a formation needs at least one follower")
        leader = self._client(leader_id)
        followers = [self._clients[rid] for rid in follower_ids]
        kwargs = {} if self._relay_factory is None else {"relay_factory": self._relay_factory}
        member_order = [rid for rid in self._order if rid == leader_id or rid in follower_ids]
        session = FormationSession(leader, followers,
                                   self._spec(formation, spacing, max_speed),
                                   member_order=member_order, **kwargs)
        self._formation = session
        self._formation_leader = leader_id
        try:
            await session.start()
        except SessionError as exc:
            # 세션이 자기 안에서 이미 무장을 되돌렸다. 상태는 남겨 화면이 이유를 읽게 한다.
            raise HubError("ARMING_FAILED", str(exc)) from exc
        return self.formation_status()

    async def _handoff_dead_leader(self, robots: list) -> None:
        """리더 상태가 안 오면 대형을 풀고, 명단의 다음 생존자로 다시 연다.

        팔로워가 각자 다른 리더를 뽑지 않는다. `next_leader` 가 고른 한 명을
        관제가 `formation_start` 로 앉힌다. 살아있는 팔로워가 없으면 풀기만 한다.
        """
        if not self._formation_members():
            return
        leader_id = self._formation_leader
        session = self._formation
        if leader_id is None or session is None:
            return
        rows = {row["robot_id"]: row for row in robots}
        if rows.get(leader_id, {}).get("online"):
            return
        order = [rid for rid in self._order
                 if rid == leader_id or rid in session.assignment]
        dead = {rid for rid in order if not rows.get(rid, {}).get("online")}
        spec = session.spec
        chosen = next_leader(order, dead)
        living = [rid for rid in order if rid not in dead]
        await self.formation_stop()
        if chosen is None:
            return
        try:
            await self.formation_start(
                chosen, formation=spec.formation.value, spacing=spec.spacing,
                max_speed=spec.max_speed, members=living)
        except HubError:
            return

    async def formation_reform(self, formation: str, spacing=None, max_speed=None) -> dict:
        session = self._formation
        if session is None or session.state is SessionState.STOPPED:
            raise HubError("NO_FORMATION", "no formation to reform")
        try:
            await session.reform(self._spec(formation, spacing, max_speed))
        except SessionError as exc:
            raise HubError("REFORM_REFUSED", str(exc)) from exc
        return self.formation_status()

    async def formation_resume(self) -> dict:
        session = self._formation
        if session is None:
            raise HubError("NO_FORMATION", "no formation to resume")
        try:
            await session.resume()
        except SessionError as exc:
            raise HubError("RESUME_REFUSED", str(exc)) from exc
        return self.formation_status()

    async def formation_stop(self) -> dict:
        session = self._formation
        if session is None:
            return {"active": False, "state": "IDLE"}
        await session.stop()
        status = self.formation_status()
        self._formation_leader = None
        return status

    async def aclose(self) -> None:
        for client in self._clients.values():
            closer: Any = getattr(client, "aclose", None)
            if closer is not None:
                await closer()
        if self._signals is not None:
            await self._signals.aclose()
