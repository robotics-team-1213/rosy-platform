"""core_features.swarm.manager — SWM-001~007 follow 상태머신 (D-20). ROS 무의존.

추종 계산은 로봇에 있고 Fleet 은 지정·릴레이만 한다(D-20). 이 모듈은 참조
pose 가 **어디서 왔는지 묻지 않는다**(SWM-007): `on_reference_pose` 를 부르는
쪽이 Fleet 릴레이든 peer 유니캐스트든 추종 로직은 같다. 그래서 여기에는
websocket 도 fleet 도 등장하지 않는다.

목표는 Nav2 moving goal 로 투입한다(SWM-001). 별도 cmd_vel 소스를 만들지
않으므로 장애물 회피와 SAF-004 클리핑이 그대로 적용된다.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Optional

from core_features.navigation.manager import NavGoalSpec, NavigationError
from core_common.protocol.schemas import (
    SwarmFollowParams,
    SwarmReferenceSource,
    SwarmRole,
    SwarmStatus,
)
from core_features.swarm.poses import ReferencePose, follow_goal

#: SWM-002 v1: moving goal 갱신 상한. 군집 속도(<=0.2 m/s)에서 충분하고,
#: 그 이상은 Nav2 플래너를 재시작시키기만 한다.
MAX_GOAL_RATE_HZ = 2.0
_MIN_GOAL_INTERVAL_S = 1.0 / MAX_GOAL_RATE_HZ


class SwarmError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SwarmManager:
    """SWM-002 follow 프리미티브와 SWM-004 단절 정책."""

    def __init__(self, events, state_manager, nav, safety, capability,
                 clock=time.monotonic, docking_active_provider=None,
                 map_id_provider=None) -> None:
        self._events = events
        self._state = state_manager
        self.nav = nav
        self._safety = safety
        self._capability = capability
        self._clock = clock
        # DOCKING(4) 이 NAVIGATION(5) 보다 우선한다(§8.1). 도킹은 같은 Nav2
        # 액션을 쓰므로, 추종이 계속 목표를 갈아끼우면 도크로 가던 주행을
        # 선점해버린다 — SAF-005 저배터리 복귀가 조용히 실패하는 경로다.
        self._docking_active = docking_active_provider or (lambda: False)
        # 참조 pose 가 우리 맵의 좌표인지 볼 수 있어야 한다. 웨이포인트에는
        # MAP-002 가드가 있는데(resolve_goal 의 MAP_MISMATCH) 추종에는 없었고,
        # 다른 맵의 리더를 따라가면 그럴듯해 보이는 엉뚱한 좌표로 간다.
        self._map_id = map_id_provider or (lambda: None)
        self._lock = threading.RLock()

        self._params: Optional[SwarmFollowParams] = None
        #: NavigationManager 가 발급한다. 목표에 붙여 보내면, 취소 뒤에 뒤늦게
        #: 도착한 목표가 저쪽 락 안에서 걸러진다 — 이쪽 락을 쥔 채로 저쪽을
        #: 부를 필요가 없어진다.
        self._session: Optional[int] = None
        self._last_sample_at: Optional[float] = None
        self._last_goal_at: Optional[float] = None
        self._pending: Optional[ReferencePose] = None
        self._holding = False
        #: 맞지 않는 맵 id. 스트림 단절과 원인은 다르지만 처신은 같다 —
        #: 목표를 거두고 세션은 살려 둔다.
        self._map_mismatch: Optional[str] = None

    # --- 조회 -----------------------------------------------------------------

    @property
    def active(self) -> bool:
        with self._lock:
            return self._params is not None

    @property
    def holding(self) -> bool:
        with self._lock:
            return self._holding

    def status(self) -> SwarmStatus:
        with self._lock:
            if self._params is None:
                return SwarmStatus()
            return SwarmStatus(
                role=SwarmRole.FOLLOWER,
                formation=self._formation_label(self._params),
                active=True,
            )

    def state_payload(self) -> dict:
        """GET /api/v1/swarm/state (SWM-002). 스냅샷의 swarm 필드보다 자세하다."""
        with self._lock:
            status = self.status()
            return {
                "role": status.role.value,
                "formation": status.formation,
                "active": status.active,
                "holding": self._holding,
                "target_robot_id": self._params.target_robot_id if self._params else None,
                "source": self._params.source.value if self._params else None,
                "max_speed": self._params.max_speed if self._params else None,
                "map_mismatch": self._map_mismatch,
                "stream_age_s": (
                    None if self._last_sample_at is None
                    else round(self._clock() - self._last_sample_at, 3)
                ),
            }

    @staticmethod
    def _formation_label(params: SwarmFollowParams) -> str:
        return f"follow:{params.target_robot_id}@{params.distance:.2f}/{params.lateral:.2f}"

    # --- SWM-002 follow / cancel ---------------------------------------------

    def check_follow(self, params: SwarmFollowParams) -> None:
        """follow() 가 받아들일지를 아무것도 바꾸지 않고 확인한다.

        상태를 바꾸고 이벤트를 낸 뒤에 다른 이유로 거절당하면 되돌릴 것이
        생긴다. 호출자가 먼저 물어볼 수 있게 게이트만 떼어 둔다.
        """
        if not self._capability.supports("swarm.follow"):
            raise SwarmError("CAPABILITY_NOT_SUPPORTED",
                             "this robot does not support swarm follow")
        if params.source is not SwarmReferenceSource.FLEET:
            # D-21 훅은 계약에만 있고 릴레이가 없다. 받아들이는 척하지 않는다.
            raise SwarmError(
                "CAPABILITY_NOT_SUPPORTED",
                f"reference source {params.source.value} is reserved, not implemented")
        if self._safety.estop:
            raise SwarmError("EMERGENCY_ACTIVE", "e-stop is active")
        if self._docking_active():
            # 받아들인 뒤 다음 틱에 조용히 푸는 것은 거절보다 나쁘다 —
            # 운영자는 200 을 보고, 로봇은 NAVIGATION 에 남는다.
            raise SwarmError("DOCKING_ACTIVE", "a docking run owns navigation")
        if self.nav.mapping_active:
            # 같은 이유. 맵핑 중에는 목표 투입이 MAPPING_ACTIVE 로 거절되는데,
            # 그 예외는 참조 소켓이 삼킨다 — 무장돼 보이면서 아무것도 못 하는
            # 대형이 남는다.
            raise SwarmError("MAPPING_ACTIVE", "a mapping session owns navigation")
        if not math.isfinite(params.distance) or params.distance <= 0:
            raise SwarmError("VALIDATION_ERROR", "distance must be a positive number")
        if not math.isfinite(params.lateral):
            raise SwarmError("VALIDATION_ERROR", "lateral must be a finite number")
        if params.stream_timeout_ms <= 0:
            raise SwarmError("VALIDATION_ERROR", "stream_timeout_ms must be positive")
        if not math.isfinite(params.max_speed) or params.max_speed <= 0:
            raise SwarmError("VALIDATION_ERROR", "max_speed must be a positive number")
        ceiling = self._safety.limits.max_linear
        if params.max_speed > ceiling:
            raise SwarmError(
                "VALIDATION_ERROR",
                f"max_speed {params.max_speed} exceeds the SAF-004 ceiling {ceiling}")


    def follow(self, params: SwarmFollowParams, source: str = "api") -> SwarmStatus:
        self.check_follow(params)
        with self._lock:
            # check_follow 와 무장 사이에도 e-stop 은 걸릴 수 있다. 여기서는
            # 평범한 읽기뿐이라 항법 락을 잡지 않는다.
            blocked = None
            if self._safety.estop:
                blocked = ("EMERGENCY_ACTIVE", "e-stop is active")
            elif self._docking_active():
                blocked = ("DOCKING_ACTIVE", "a docking run owns navigation")
            elif self.nav.mapping_active:
                blocked = ("MAPPING_ACTIVE", "a mapping session owns navigation")
            if blocked is None:
                # 세션은 여기서 연다. 락 밖에서 열면 그 사이에 도착한 cancel 이
                # 임자 없는 세션을 남긴다. `open_moving_session` 은 항법 락 안의
                # 카운터 증가일 뿐 executor 를 건드리지 않으므로, 이 한 줄은
                # 목표·취소를 락 밖으로 뺀 이유(R1)와 충돌하지 않는다.
                try:
                    # 항법 락 안에서 맵핑과의 배타를 확정한다. 위의 재확인은
                    # 운영자에게 이유를 먼저 알려주는 것이고, 진짜 결정은 여기다.
                    self._session = self.nav.open_moving_session()
                except NavigationError as exc:
                    blocked = (exc.code, str(exc))
                    self._session = None
            if blocked is None:
                # 세션을 여는 것과 무장은 한 구간이다. 여기서 락을 놓으면 그
                # 사이의 cancel 이 임자 없는 세션을 남긴다.
                self._params = params.model_copy()
                # 검증만 하고 흘려보내면 계약이 거짓이 된다. 실제로 바퀴에
                # 닿는 값을 줄인다 (D-2 의 단일 통로를 그대로 쓴다).
                self._safety.set_session_speed(params.max_speed)
                self._last_sample_at = None
                self._last_goal_at = None
                self._pending = None
                self._holding = False
                self._map_mismatch = None
                status = self.status()
        if blocked is not None:
            raise SwarmError(*blocked)

        self._state.set_swarm(status)
        self._events.publish(
            "swarm.role_assigned", source="swarm_manager",
            data={"role": SwarmRole.FOLLOWER.value,
                  "formation": self._formation_label(params),
                  "target_robot_id": params.target_robot_id,
                  "reference_source": params.source.value, "by": source},
        )
        return status

    def cancel(self, source: str = "api", reason: str = "canceled") -> SwarmStatus:
        with self._lock:
            was_active = self._params is not None
            formation = self._formation_label(self._params) if self._params else None
            target = self._params.target_robot_id if self._params else None
            session = self._session
            self._params = None
            self._last_sample_at = None
            self._last_goal_at = None
            self._pending = None
            self._holding = False
            self._map_mismatch = None
            self._session = None
            self._safety.set_session_speed(None)

        if not was_active:
            return SwarmStatus()

        # 우리 세션만 닫는다. 락을 놓은 사이에 운영자가 follow 를 다시 걸었다면
        # 그 새 세션은 우리 것이 아니다 — 닫으면 살아 있어 보이는데 목표는
        # 하나도 못 내는, A1 과 똑같은 상태가 새 대형에 생긴다.
        self.nav.cancel(source="swarm", session=session)
        self._state.set_swarm(SwarmStatus())
        self._events.publish(
            "swarm.aborted", severity="warning", source="swarm_manager",
            data={"formation": formation, "reason": reason, "by": source,
                  "robots": [target] if target else []})
        return SwarmStatus()

    # --- 참조 스트림 (SWM-007: 소스를 묻지 않는다) ----------------------------

    def on_reference_pose(self, reference: ReferencePose) -> bool:
        """참조 pose 한 표본. 목표를 실제로 보냈으면 True."""
        with self._lock:
            params = self._params
            if params is None or reference.robot_id != params.target_robot_id:
                return False
            now = self._clock()
            # 표본은 도착했다 — 스트림은 살아 있다. 맵이 맞지 않는 것은
            # 단절이 아니므로 SWM-004 타임아웃을 걸어서는 안 된다.
            self._last_sample_at = now

            # 락을 나가면 이 값들은 더 이상 우리 것이 아니다. 다른 스레드가
            # e-stop·docking·재무장으로 어느 것이든 바꿀 수 있으므로, 이 표본에
            # 대한 판단은 전부 여기서 지역 변수에 담아 나간다.
            ours = self._map_id()
            session = self._session
            formation = self._formation_label(params)
            mismatched = bool(reference.map_id and ours and reference.map_id != ours)
            announce = False
            resumed = False
            spec = None

            if mismatched:
                announce = self._map_mismatch != reference.map_id
                self._map_mismatch = reference.map_id
                self._pending = None
                # 프레임이 도착했으니 스트림은 살아 있다. 단절 HOLD 를 그대로
                # 두면 `holding: true` 와 갓 갱신된 `stream_age_s` 가 나란히
                # 보이고, 운영자는 무엇이 멈춘 것인지 알 수 없다. 이유는
                # 이제 map_mismatch 다.
                self._holding = False
            else:
                resumed = self._holding or self._map_mismatch is not None
                self._holding = False
                self._map_mismatch = None
                if (self._last_goal_at is not None
                        and now - self._last_goal_at < _MIN_GOAL_INTERVAL_S):
                    # SWM-002: <=2 Hz. 버리지 않고 들고 있다가 tick 에서 낸다.
                    self._pending = reference
                    return False
                self._last_goal_at = now
                self._pending = None
                spec = follow_goal(reference, params.distance, params.lateral)

        if mismatched:
            if not announce:
                # 이미 알렸다. 매 프레임 같은 말을 감사 로그에 쌓지 않는다.
                return False
            # 목표를 거둔다. 대형은 살려 둔다 — 리더가 우리 맵으로 돌아오면
            # 새 follow 명령 없이 이어간다. 토큰을 붙여, 그 사이에 운영자가
            # 다시 건 대형의 목표를 대신 거두지 않게 한다.
            self.nav.cancel(source="swarm", close_session=False, session=session)
            self._state.set_swarm(self.status())
            self._events.publish(
                "swarm.hold", severity="warning", source="swarm_manager",
                data={"reason": "map_mismatch", "formation": formation,
                      "reference_map_id": reference.map_id, "map_id": ours})
            return False

        if resumed:
            self._state.set_swarm(self.status())
        # 락 밖에서 부른다. 취소와 뒤바뀌어도 토큰이 맞지 않으면 저쪽이 버린다.
        return self.nav.moving_goal(spec, source="swarm", session=session)

    def tick(self, now: Optional[float] = None) -> None:
        """SWM-004 단절 판정, 밀린 목표 투입, 그리고 추종을 끝내야 할 사유들.

        follow() 의 게이트는 시작 시점만 본다. 대형은 몇 분씩 유지되고 그
        사이에 e-stop 이 걸리거나 저배터리 복귀가 시작될 수 있으므로, 여기서
        매 틱 다시 본다 — docking 매니저가 어느 단계에서든 e-stop 에 중단되는
        것과 같은 규칙이다.
        """
        if not self.active:
            return
        if self._safety.estop:
            # 해제 뒤 참조 프레임 하나만으로 다시 달리기 시작하면 안 된다.
            # 운영자가 다시 명령해야 한다.
            self.cancel(source="safety", reason="estop")
            return
        if self._docking_active():
            # DOCKING(4) > NAVIGATION(5). 같은 Nav2 액션을 두고 다투면
            # 추종이 도크 진입 주행을 계속 선점한다.
            self.cancel(source="docking", reason="docking")
            return
        current = self._clock() if now is None else now
        spec: Optional[NavGoalSpec] = None
        hold = False
        with self._lock:
            params = self._params
            if params is None:
                return
            timeout_ms = params.stream_timeout_ms
            formation = self._formation_label(params)
            if self._last_sample_at is not None:
                age_ms = (current - self._last_sample_at) * 1000.0
                if age_ms >= timeout_ms and not self._holding:
                    self._holding = True
                    self._pending = None
                    # 맵 불일치로 이미 서 있는 대형이면 다시 알리지 않는다.
                    # 서 있는 이유는 그쪽이고, 목표도 이미 거둬져 있다 —
                    # 알리면 감사 로그가 멈춘 원인을 되풀이해 잘못 말한다.
                    hold = self._map_mismatch is None
                elif not self._holding and self._pending is not None and (
                    self._last_goal_at is None
                    or current - self._last_goal_at >= _MIN_GOAL_INTERVAL_S
                ):
                    spec = follow_goal(self._pending, params.distance, params.lateral)
                    self._pending = None
                    self._last_goal_at = current
            session = self._session

        if hold:
            # 자리를 지킨다: 목표만 거두고 follow 는 살려 둔다. 스트림이 돌아오면
            # 새 follow 명령 없이 이어서 따라간다 — 그래서 세션은 닫지 않는다.
            self.nav.cancel(source="swarm", close_session=False, session=session)
            self._state.set_swarm(self.status())
            self._events.publish("swarm.hold", severity="warning", source="swarm_manager",
                                 data={"reason": "reference stream lost",
                                       "formation": formation,
                                       "stream_timeout_ms": timeout_ms})
        elif spec is not None:
            self.nav.moving_goal(spec, source="swarm", session=session)

    def on_estop(self) -> None:
        """안전 경로에서 직접 부를 수 있는 입구. tick 을 기다리지 않는다."""
        if self.active:
            self.cancel(source="safety", reason="estop")

    #: 세션을 닫은 주체 → swarm.aborted 에 실을 사유. 감사 로그를 읽는 사람이
    #: "주행을 취소했다"와 "누가 수동으로 잡았다"를 구분할 수 있어야 한다.
    _CLOSE_REASONS = (("stuck_detector", "stuck"), ("mode:", "manual"))

    def on_navigation_session_closed(self, source: str) -> None:
        """항법이 moving goal 세션을 닫았다. 추종도 여기서 끝난다.

        닫는 길은 여럿이다 — NAV-006 stuck, 운영자의 `/navigation/cancel`,
        MANUAL 전환. 어느 쪽이든 세션을 잃은 추종은 목표를 하나도 내지
        못하면서 스냅샷에는 `active: true` 로 남는다. 참조 프레임이 계속
        도착하니 스트림도 신선해 보이고 HOLD 도 걸리지 않아서, 대형이
        멀쩡해 보이는 채로 아무 일도 하지 않는다. 그 상태를 만들지 않는다.

        stuck 의 경우 세션을 살려두는 것은 곧 SRS 가 금지한 자동 재시도다:
        0.5 초 뒤 스트림이 목표를 다시 밀어넣는다.
        """
        if not self.active:
            return  # 우리가 부른 취소이거나, 이미 끝난 추종이다
        reason = "navigation_canceled"
        for prefix, mapped in self._CLOSE_REASONS:
            if source.startswith(prefix):
                reason = mapped
                break
        self.cancel(source="navigation", reason=reason)
