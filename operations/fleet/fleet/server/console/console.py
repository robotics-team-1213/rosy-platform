"""사이트 오케스트레이터의 관제 표면 — 모음(gather)과 흩뿌림(scatter).

역할 경계는 [사이트 미들웨어 역할 패브릭 설계](../../../docs/plans/2026-09-14-site-middleware-role-fabric-design.md)
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
from hashlib import sha256
import hmac
import importlib
import logging
import time
from typing import Any, Callable, Optional, Sequence
from urllib.parse import urlsplit  # noqa: F401

from fleet.hub.hub import HubError, SiteHub
from fleet.localization import trust  # noqa: F401
from fleet.server import bays, goal_admission, goal_lease, traffic
from fleet.server.console_view import (  # noqa: F401
    CapabilityDisplay,
    TripAware,
    _error_of,
    _shown,
    _stream_evidence,
    classify_link,
    link_reason,
)
from fleet.server.estop_fanout import stop_robots
from fleet.server.formation_control import FormationControl  # SERVER_HOLDERS composes console/*.py as fleet.server.<name>
from fleet.server.traffic_arbitration import TrafficArbitration
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.session_arming import require_capability  # noqa: F401
from fleet.swarm.transport import RobotApiError, RobotClient  # noqa: F401

_helpers = importlib.import_module("fleet.server.console_helpers")

#: A robot whose read fails within this many seconds of its last answer is shown as
#: `degraded` (responding late), not `unreachable`; decisions still see online=False.
LINK_DEGRADED_S = _helpers.LINK_DEGRADED_S
logger = logging.getLogger("fleet.console")

#: 맵은 로봇마다 다시 받을 이유가 없다 — 한 사이트는 한 맵을 공유한다. 그래도 SLAM 으로
#: 맵이 바뀔 수 있으므로 무한정 붙들지는 않는다.
MAP_TTL_S = 10.0


class FleetConsole(TripAware, TrafficArbitration, FormationControl):
    """robots.yaml 한 장에 적힌 N대를 하나의 관제 표면으로 묶는다."""

    _goal_admission = goal_admission
    _cancel_confirmed = staticmethod(goal_admission.cancel_confirmed)

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
        event_store=None,
        hub_state_max_age_s: float = 3.0, goal_lease_ttl_s: float = 0.0,
    ) -> None:
        if len(endpoints) != len(clients):
            raise ValueError("endpoints and clients must line up one for one")
        self._clients: dict[str, RobotClient] = {ep.robot_id: client for ep, client in zip(endpoints, clients)}
        self._rest_tokens = {ep.robot_id: ep.token for ep in endpoints}
        self._agent_pairing_tokens = {ep.robot_id: ep.fleet_pairing_token for ep in endpoints
                                      if ep.fleet_pairing_token is not None}
        self._order = [ep.robot_id for ep in endpoints]
        self._registered_endpoints = {ep.robot_id: ep.base_url for ep in endpoints}
        self._clock = clock
        self._map_ttl_s = map_ttl_s
        self._map: Optional[dict] = None
        self._map_at = 0.0
        self._capability_display = CapabilityDisplay(self._clients, self._clock)
        self._capability_cache = self._capability_display.cache
        self._hub_state_max_age_s = hub_state_max_age_s
        #: Extra alarm rows from other watchers (D-526 tether watch): callables returning alarm dicts.
        self.alarm_sources: list = []
        # 하달한 목표는 Fleet 이 기억한다. 로봇 상태 스냅샷에는 목표가 없고, 있어서도 안 된다
        # — 미션은 Fleet 쪽 개념이고 로봇은 원자 액션만 받는다 (D-12). 화면의 목표 표시는
        # "내가 무엇을 시켰는가"이지 로봇이 되돌려 준 값이 아니다.
        self._goals: dict[str, dict] = {}
        self.goal_leases = goal_lease.GoalLeases(goal_lease_ttl_s, self._clients, clock, lambda r: r in self._yielding)
        #: 달리는 로봇이 점유한 경로. 교행 판정의 재료이자, 왜 기다리는지의 근거다.
        self._claims: dict[str, list] = {}
        #: 남의 경로와 부딪혀 아직 못 내려간 미션. 앞이 비면 그대로 다시 내려간다.
        self._queued: dict[str, dict] = {}
        self._task_queue_release_callback: Optional[Callable[[dict], Any]] = None
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
        #: 마지막으로 본 로봇의 pose와 주행 상태(막고 선 로봇을 찾으려면 좌표가 필요한데, 스냅숏으로 들어온다).
        self._seen: dict[str, dict] = {}
        self._robot_maps, self._robot_map_fallbacks = {}, {}  # D-1010: last confirmed map_id (+ fallback warned)
        # Console clock time of each robot's last answered state read (link grace below).
        self._last_ok: dict[str, float] = {}
        #: D-395 P2-2: last pose traffic may use, per robot (`trust.trusted_xy`): only
        #: from a LOCALIZED map snapshot, never from a legacy-null one (S2 Finding 1).
        self._trusted: dict[str, tuple] = {}
        #: Robots that have reported `localization` -> since when they report null (None
        #: while reporting). After `trust.LAPSED_GRACE_S` its cached position expires;
        #: missing localization stays untrusted.
        self._loc_null_since: dict[str, Optional[float]] = {}
        #: robot_id -> the localization service's view (needs_human), set by app.py.
        self._localization_view: Optional[Callable[[str], Optional[dict]]] = None
        #: D-494 3: every state read also feeds the trip-only map pose (its `odom_pose`).
        self._state_sink: Optional[Callable[[str, dict], None]] = None
        #: D-760 8: (robot_id, max_age_s) -> its REST state; app.py sets MapPoseService.state (one read per robot).
        self.read_state = lambda robot_id, max_age_s: self._client(robot_id).state()
        self._link_address_status = None
        #: Robots whose pinned address is unverified (D-361 3): stop-only, kept as a
        #: blocked obstacle in traffic, alarmed when they were moving.
        self._held: dict[str, dict] = {}
        self._goal_busy: set[str] = set()
        #: 경로 확인부터 점유 기록까지는 한 미션씩 지난다 - 동시에 검사하면 서로의 점유를 못 봐 마주 오는 두 대가 함께 나간다.
        self._traffic_lock = asyncio.Lock()
        #: 열려 있는 대형 세션. 한 사이트에 하나다 - 같은 로봇이 두 대형에 들어가면
        #: 어느 리더를 따라야 하는지 로봇 쪽에서 정할 방법이 없다.
        self._formation = None
        self._formation_leader = None
        #: 시험이 가짜 릴레이를 끼우는 자리. 운용에서는 None 이라 세션의 기본값을 쓴다.
        self._relay_factory = relay_factory
        self.formation_relay_factory = None  # D-581: app-injected factory
        self.fleet_name, self.control_unit = fleet_name, {}  # D-974: unit/root for the header
        # e-stop 은 hub 의 scatter 를 그대로 쓴다 — 흩뿌림의 규칙을 두 군데 두지 않는다.
        self._hub = SiteHub(list(endpoints), dict(self._clients), fleet_name=fleet_name,
                            event_store=event_store)
        #: 신호등 컨트롤러(ROSY-SIGNAL-001). signals.yaml 이 없는 사이트도 같은 서버로
        #: 뜬다 — 없으면 신호등 기능은 조용히 비어 있다("signals": {}).
        self._signals = signal_console

    @property
    def robot_ids(self) -> list[str]:
        return list(self._order)

    @property
    def registered_endpoints(self) -> dict[str, str]:
        return dict(self._registered_endpoints)

    def uses_rest_token(self, candidate: str) -> bool:
        """Check credential separation without exposing configured robot tokens."""
        matched = False
        for token in self._rest_tokens.values():
            matched |= hmac.compare_digest(candidate, token)
        return matched

    def uses_agent_pairing_token(self, candidate: str) -> bool:
        """Check credential separation without exposing CORE FleetAgent secrets."""
        matched = False
        for token in self._agent_pairing_tokens.values():
            matched |= hmac.compare_digest(candidate, token)
        return matched

    def user_credential_overlaps_robot_secret(self, user_token_digests: Sequence[str]) -> bool:
        """Reject user tokens reused for CORE REST or Agent pairing credentials."""
        matched = False
        for token in (*self._rest_tokens.values(), *self._agent_pairing_tokens.values()):
            digest = sha256(token.encode("utf-8")).hexdigest()
            for user_digest in user_token_digests:
                matched |= hmac.compare_digest(digest, user_digest)
        return matched

    @property
    def hub(self) -> SiteHub:
        """CORE Agent link owned by this console; transport routes are installed by app.py."""
        return self._hub

    def _add_robot(self, endpoint: RobotEndpoint, client: RobotClient) -> None:
        """SiteRoster only (D-361 5). Synchronous, so no gather sees half a robot."""
        robot_id = endpoint.robot_id
        if robot_id in self._clients:
            raise HubError("ROBOT_ID_CONFLICT", f"{robot_id} is already on the roster")
        self._clients[robot_id] = client
        self._order.append(robot_id)
        self._registered_endpoints[robot_id] = endpoint.base_url
        self._rest_tokens[robot_id] = endpoint.token
        self._hub.set_client(robot_id, client)
        if endpoint.fleet_pairing_token is not None:
            self._agent_pairing_tokens[robot_id] = endpoint.fleet_pairing_token
            self._hub.set_pairing_token(robot_id, endpoint.fleet_pairing_token)

    def _remove_robot(self, robot_id: str) -> RobotClient:
        """SiteRoster only. Returns the client so the caller can close it."""
        client = self._clients.pop(robot_id)
        self._order.remove(robot_id)
        self._registered_endpoints.pop(robot_id, None)
        self._capability_display.invalidate(robot_id)
        self._rest_tokens.pop(robot_id, None)
        self._agent_pairing_tokens.pop(robot_id, None)
        self._hub.drop(robot_id)
        for table in (self._goals, self._claims, self._queued, self._yielding, self._seen, self._held,
                      self._trusted, self._loc_null_since, self._robot_maps, self._robot_map_fallbacks, self.goal_leases):
            table.pop(robot_id, None)
        return client

    def _replace_client(self, endpoint: RobotEndpoint, client: RobotClient) -> RobotClient:
        """SiteRoster only: the same robot moved to a confirmed new address."""
        robot_id = endpoint.robot_id
        old = self._clients[robot_id]
        self._clients[robot_id] = client
        self._capability_display.invalidate(robot_id)
        self._registered_endpoints[robot_id] = endpoint.base_url
        self._rest_tokens[robot_id] = endpoint.token
        self._hub.set_client(robot_id, client)
        return old

    def clients(self) -> dict[str, RobotClient]:
        """The live roster's clients (the localization service polls these)."""
        return dict(self._clients)

    def set_localization_view(self, view: Optional[Callable[[str], Optional[dict]]]) -> None:
        self._localization_view = view

    def set_state_sink(self, sink: Optional[Callable[[str, dict], None]]) -> None:
        self._state_sink = sink

    def set_link_address_status(self, provider) -> None:
        """robot_id -> address status from the latest scan. None skips the lookup.

        The provider must not contact a robot. snapshot calls it once.
        """
        self._link_address_status = provider

    def _client(self, robot_id: str) -> RobotClient:
        client = self._clients.get(robot_id)
        if client is None:
            raise HubError("UNKNOWN_ROBOT", robot_id)
        return client

    # --- gather ---------------------------------------------------------------

    async def _shown_capabilities(self, robot_id: str) -> Optional[dict]:
        return await self._capability_display.shown(robot_id)

    async def _gather_state(self, robot_id: str) -> tuple[dict, str]:
        """D-447: 이미 열린 소켓이 먼저다. hub heartbeat(1 Hz, PRT-003)가 신선하면
        registry 의 ``StateSnapshot`` 으로 답하고 REST GET 은 미연결·stale 로봇의
        폴백이다. 응답 모양은 REST 와 같다(스키마 불변)."""
        row = self._hub.registry.find(robot_id)
        if (row is not None and row.online and row.snapshot is not None
                and row.last_heartbeat_monotonic is not None
                and self._clock() - row.last_heartbeat_monotonic
                < self._hub_state_max_age_s):
            return row.snapshot.model_dump(mode="json"), "hub"
        return await self.read_state(robot_id, 0.45), "rest"   # D-760 8: shared; the 2 Hz tether watch reads anew

    snapshot = _helpers.snapshot
    map = _helpers.map

    # --- scatter --------------------------------------------------------------

    def set_task_queue_release_callback(self, callback: Optional[Callable[[dict], Any]]) -> None:
        self._task_queue_release_callback = callback

    def discard_task_queue_entries(self, task_ids: set[str]) -> None:
        for robot_id, mission in list(self._queued.items()):
            if mission.get("task_id") in task_ids:
                self._queued.pop(robot_id, None)

    def prune_task_queue_entries(self, active_task_ids: set[str]) -> None:
        for robot_id, mission in list(self._queued.items()):
            task_id = mission.get("task_id")
            if task_id is not None and task_id not in active_task_ids:
                self._queued.pop(robot_id, None)

    async def line_follow_mode(self, robot_id: str, mode: str) -> dict:
        """Forward an explicit bounded line-follow selection to CORE."""
        if mode not in {"IR_LINE", "OFF"}:
            raise ValueError("unsupported Fleet line-follow mode")
        return await self._client(robot_id).line_follow_mode(mode)

    goal = _helpers.goal
    _goal = _helpers._goal

    # --- pinned-address holds (D-361 3) ------------------------------------------

    hold_robot = _helpers.hold_robot
    release_robot = _helpers.release_robot
    stop_held_formation = _helpers.stop_held_formation
    alarms = _helpers.alarms

    async def estop_all(self) -> dict:
        """전 대상 정지 요청. 한 대가 거절해도 나머지에 계속 내린다.

        빨리 실패하면 안 된다 — 닿지 않는 한 대 때문에 멈출 수 있었던 나머지가 계속
        움직이는 것이 이 버튼에서 가장 나쁜 결과다. 로봇 쪽 e-stop 과 deadman 은 관제와
        무관하게 살아 있다(설계 §3).
        """
        self.goal_leases.clear()  # D-550 10: a leased goal is never renewed past an E-stop
        # 신호등의 all_red 는 로봇 정지와 병렬이다 — 순서를 정하는 동안 한쪽이 늦게
        # 간다. 어느 쪽이 실패했는지는 본문이 대신 말한다.
        signals_task = (asyncio.ensure_future(self._signals.all_red())
                        if self._signals is not None else None)
        order = list(self._order)
        # 전달(동시·짧은 재시도)과 대형 해제(정지와 나란히)는 estop_fanout 이 맡는다.
        formation = self._formation if self._formation_members() else None
        results = await stop_robots(self._hub.scatter_estop, order, formation and formation.stop)
        if formation is not None:
            self._formation_leader = None
        rows = []
        for robot_id, result in zip(order, results):
            if isinstance(result, BaseException):
                # 응답을 받지 못했다. 실제로는 아직 가고 있을 수 있으므로 목표를 남긴다.
                rows.append({"robot_id": robot_id, "stopped": False, "error": _error_of(result)})
            else:
                self._goals.pop(robot_id, None)
                self._claims.pop(robot_id, None)
                self._queued.pop(robot_id, None)
                self._yielding.pop(robot_id, None)
                # legacy stopped=True는 CORE HTTP 응답 수신만 뜻한다.
                # 실제 속도 0·물리 비상정지는 여기서 검증하지 않는다.
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

    aclose = _helpers.aclose
