"""core_features.power.manager — PWR-001~004 절전 모드/근접 웨이크 (D-24).

정책만 담당한다. 센서 샘플링 주기와 디스플레이 상태를 선언할 뿐,
모터·E-Stop·cmd_vel 먹서·워치독 경로에는 어떤 권한도 갖지 않는다.
ROS 무의존 — 시계는 주입되며 테스트가 시간을 직접 전진시킨다.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from core_common.protocol.schemas import (
    PowerMode,
    PowerStatus,
    PresenceState,
    RobotMode,
    Severity,
)

# 웨이크 사유 — 이벤트/REST 페이로드에 그대로 실린다.
WAKE_PROXIMITY = "proximity"
WAKE_CONTACT = "contact"
WAKE_ACTIVITY = "activity"
WAKE_API = "api"
WAKE_BATTERY = "battery"


@dataclass
class PresenceConfig:
    """초음파 프레즌스 판정 파라미터 (단위: m, 표본 수)."""

    near_m: float = 0.25            # 이보다 가까우면 접근
    contact_m: float = 0.05         # 이보다 가까우면 접촉으로 간주
    hysteresis_m: float = 0.10      # near_m + 이 값을 넘어야 해제 판정 시작
    detect_samples: int = 2         # 검출에 필요한 연속 표본 수
    release_samples: int = 3        # 해제에 필요한 연속 표본 수
    min_valid_m: float = 0.02       # 센서 min_range — 미만은 무효 표본
    max_valid_m: float = 3.0        # 센서 max_range — 초과는 무효 표본


@dataclass
class LidarPolicy:
    """STANDBY LiDAR 모터 정지 (PWR-005).

    기본 비활성이다. 인터록상 안전하지만(STANDBY는 로봇 모드 IDLE에서만 진입,
    모든 웨이크가 재기동을 선행한다) 5분간 스캔이 끊겼을 때 Nav2 라이프사이클이
    어떻게 반응하는지는 실기에서 관찰해야 할 통합 동작이다. 벤치 승인 후 켠다.
    """

    standby_stop: bool = False      # STANDBY에서 stop_motor 호출 여부
    spinup_s: float = 2.0           # start_motor 후 스캔을 신뢰하기까지의 시간


@dataclass
class PowerConfig:
    enabled: bool = True
    idle_after_s: float = 60.0
    standby_after_s: float = 300.0
    info_hold_s: float = 15.0
    active_rate_hz: float = 20.0
    idle_rate_hz: float = 5.0
    standby_rate_hz: float = 2.0
    presence: PresenceConfig = field(default_factory=PresenceConfig)
    lidar: LidarPolicy = field(default_factory=LidarPolicy)


_RATE_ATTR = {
    PowerMode.ACTIVE: "active_rate_hz",
    PowerMode.IDLE: "idle_rate_hz",
    PowerMode.STANDBY: "standby_rate_hz",
}


class PresenceDetector:
    """양방향 디바운스 + 히스테리시스.

    단발 반사파로 깨어나지 않고, 단발 드롭아웃으로 화면이 꺼지지 않는다.
    무효 표본(NaN/Inf/센서 범위 밖)은 카운터를 건드리지 않고 버린다.
    """

    def __init__(self, config: PresenceConfig) -> None:
        self._cfg = config
        self.state: PresenceState = PresenceState.NONE
        self._near_count = 0
        self._contact_count = 0
        self._far_count = 0
        self.last_valid_range: Optional[float] = None
        # 마지막 유효 표본이 해제 임계(near_m + hysteresis_m) 안이었는가.
        # 정보 창 연장은 이 값만 보고 결정한다 — 프레즌스 상태와 분리한다.
        self.last_inside: bool = False

    def is_valid(self, range_m: float) -> bool:
        try:
            value = float(range_m)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(value):
            return False
        return self._cfg.min_valid_m <= value <= self._cfg.max_valid_m

    def update(self, range_m: float) -> PresenceState:
        if not self.is_valid(range_m):
            return self.state

        value = float(range_m)
        cfg = self._cfg
        self.last_valid_range = value
        self.last_inside = value <= cfg.near_m + cfg.hysteresis_m

        if value < cfg.contact_m:
            self._contact_count += 1
            self._near_count += 1
            self._far_count = 0
        elif value < cfg.near_m:
            self._contact_count = 0
            self._near_count += 1
            self._far_count = 0
        elif value > cfg.near_m + cfg.hysteresis_m:
            self._contact_count = 0
            self._near_count = 0
            self._far_count += 1
        else:
            # 히스테리시스 대역 — 어느 쪽으로도 카운트하지 않고 현 상태를 유지한다.
            return self.state

        if self._contact_count >= cfg.detect_samples:
            self.state = PresenceState.CONTACT
        elif self._near_count >= cfg.detect_samples:
            self.state = PresenceState.NEAR
        elif self._far_count >= cfg.release_samples:
            self.state = PresenceState.NONE

        return self.state

    def reset(self) -> None:
        self.state = PresenceState.NONE
        self._near_count = 0
        self._contact_count = 0
        self._far_count = 0
        self.last_inside = False


class PowerManager:
    """ACTIVE/IDLE/STANDBY 모드 머신과 웨이크 조정 (PWR-001~004).

    안전 인터록: 활동·비 IDLE 로봇 모드·배터리 경보는 즉시 ACTIVE로 복귀시키며,
    `enabled=False`이면 항상 ACTIVE로 고정되어 기존 동작과 동일해진다.
    """

    def __init__(self, config: PowerConfig, events: Any = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._cfg = config
        self._events = events
        self._clock = clock
        self._lock = threading.Lock()

        self._detector = PresenceDetector(config.presence)
        self._mode = PowerMode.ACTIVE
        self._last_activity = clock()
        self._info_until = 0.0
        self._last_wake_reason: Optional[str] = None
        self._hold_active = False       # 로봇 모드가 IDLE이 아닐 때 절전 금지

        # LiDAR는 core 기동 시점에 이미 돌고 있다 — 스핀업 페널티 없이 시작한다.
        # None = 정상 회전 중, 실수 = 그 시각에 재기동을 요청했다.
        self._lidar_spinning = True
        self._lidar_spinup_at: Optional[float] = None

    # --- 조회 -----------------------------------------------------------------

    @property
    def mode(self) -> PowerMode:
        with self._lock:
            return self._mode

    @property
    def presence(self) -> PresenceState:
        return self._detector.state

    @property
    def last_wake_reason(self) -> Optional[str]:
        with self._lock:
            return self._last_wake_reason

    @property
    def info_hold_s(self) -> float:
        return float(self._cfg.info_hold_s)

    @property
    def sample_rate_hz(self) -> float:
        with self._lock:
            return self._rate_for(self._mode)

    def _rate_for(self, mode: PowerMode) -> float:
        return float(getattr(self._cfg, _RATE_ATTR[mode]))

    @property
    def lidar_spinning(self) -> bool:
        """LiDAR 모터 회전 의도 (PWR-005). 실제 구동은 ros_bridge가 조정한다."""
        with self._lock:
            return self._lidar_spinning

    def lidar_ready(self, now: Optional[float] = None) -> bool:
        """스캔을 신뢰할 수 있는가 — 회전 중이며 스핀업이 끝났을 때만 참."""
        current = self._clock() if now is None else now
        with self._lock:
            return self._lidar_ready_locked(current)

    def _lidar_ready_locked(self, now: float) -> bool:
        if not self._lidar_spinning:
            return False
        if self._lidar_spinup_at is None:
            return True
        return now - self._lidar_spinup_at >= self._cfg.lidar.spinup_s

    def _lidar_desired(self, mode: PowerMode) -> bool:
        cfg = self._cfg
        return not (cfg.enabled and cfg.lidar.standby_stop and mode == PowerMode.STANDBY)

    def info_visible(self, now: Optional[float] = None) -> bool:
        current = self._clock() if now is None else now
        with self._lock:
            return current < self._info_until

    def status(self, now: Optional[float] = None) -> PowerStatus:
        current = self._clock() if now is None else now
        with self._lock:
            return PowerStatus(
                mode=self._mode,
                presence=self._detector.state,
                info_visible=current < self._info_until,
                sample_rate_hz=self._rate_for(self._mode),
                last_wake_reason=self._last_wake_reason,
                idle_seconds=max(0.0, current - self._last_activity),
                lidar_spinning=self._lidar_spinning,
                lidar_ready=self._lidar_ready_locked(current),
            )

    # --- 입력 -----------------------------------------------------------------

    def on_range(self, range_m: float, now: Optional[float] = None) -> None:
        """초음파 표본 1건 반영 (PWR-002)."""
        current = self._clock() if now is None else now
        if not self._detector.is_valid(range_m):
            return

        previous = self._detector.state
        state = self._detector.update(range_m)
        pending: list[tuple] = []

        if state != previous:
            if state == PresenceState.NONE:
                pending.append(("presence.cleared", Severity.INFO,
                                {"range": self._detector.last_valid_range}))
            else:
                pending.append(("presence.detected", Severity.INFO,
                                {"state": state.value,
                                 "range": self._detector.last_valid_range}))
        self._emit_all(pending)

        if state != PresenceState.NONE:
            # 계속 앞에 있으면 정보 창을 연장한다.
            if state != previous:
                reason = WAKE_CONTACT if state == PresenceState.CONTACT else WAKE_PROXIMITY
                self.wake(reason, now=current)
            elif self._detector.last_inside:
                self._extend_info(current)
            else:
                self._evaluate(current)
        else:
            self._evaluate(current)

    def on_activity(self, source: str, now: Optional[float] = None) -> None:
        """모터·내비게이션·API 활동 — 즉시 ACTIVE (정보 창은 열지 않는다)."""
        current = self._clock() if now is None else now
        with self._lock:
            self._last_activity = current
        self._evaluate(current, reason=f"activity:{source}")

    def on_robot_mode(self, mode: RobotMode, now: Optional[float] = None) -> None:
        """로봇 모드가 IDLE이 아니면 절전 진입을 금지한다 (안전 인터록)."""
        current = self._clock() if now is None else now
        hold = mode != RobotMode.IDLE
        with self._lock:
            self._hold_active = hold
            if hold:
                self._last_activity = current
        self._evaluate(current, reason=f"robot_mode:{mode.value}")

    def on_battery_alert(self, state: str, now: Optional[float] = None) -> None:
        """SAF-005 임계 통과 — 로봇 본체에서 바로 보이도록 깨운다."""
        if state in ("warning", "critical"):
            self.wake(WAKE_BATTERY, now=now)

    def wake(self, reason: str, now: Optional[float] = None) -> None:
        current = self._clock() if now is None else now
        with self._lock:
            self._last_activity = current
            self._info_until = current + self._cfg.info_hold_s
            self._last_wake_reason = reason
        self._emit_all([("power.wake", Severity.INFO, {"reason": reason})])
        self._evaluate(current, reason=f"wake:{reason}")

    def request_mode(self, mode: PowerMode, source: str = "api",
                     now: Optional[float] = None) -> None:
        """운영자 강제 전환. ACTIVE 요청은 웨이크와 동일하게 정보 창을 연다."""
        current = self._clock() if now is None else now
        if mode == PowerMode.ACTIVE:
            self.wake(WAKE_API, now=current)
            return
        with self._lock:
            # 자연 만료 시각으로 되돌려 즉시 강등이 가능하게 한다.
            dwell = (self._cfg.standby_after_s if mode == PowerMode.STANDBY
                     else self._cfg.idle_after_s)
            self._last_activity = current - dwell
            self._info_until = 0.0
        self._evaluate(current, reason=f"request:{source}")

    def tick(self, now: Optional[float] = None) -> None:
        self._evaluate(self._clock() if now is None else now)

    # --- 내부 -----------------------------------------------------------------

    def _extend_info(self, now: float) -> None:
        with self._lock:
            self._info_until = max(self._info_until, now + self._cfg.info_hold_s)
        self._evaluate(now)

    def _evaluate(self, now: float, reason: str = "dwell") -> None:
        with self._lock:
            if not self._cfg.enabled:
                target = PowerMode.ACTIVE
            elif self._hold_active or now < self._info_until:
                target = PowerMode.ACTIVE
            else:
                dwell = now - self._last_activity
                if dwell >= self._cfg.standby_after_s:
                    target = PowerMode.STANDBY
                elif dwell >= self._cfg.idle_after_s:
                    target = PowerMode.IDLE
                else:
                    target = PowerMode.ACTIVE

            pending: list[tuple] = []
            if target != self._mode:
                previous, self._mode = self._mode, target
                pending.append(("power.mode_changed", Severity.INFO, {
                    "from": previous.value, "to": target.value,
                    "reason": reason, "sample_rate_hz": self._rate_for(target),
                }))

            # LiDAR 의도는 모드의 순수 함수다. 모드가 그대로여도 설정 변경으로
            # 어긋날 수 있으므로 조기 반환 없이 매번 조정한다.
            desired = self._lidar_desired(self._mode)
            if desired != self._lidar_spinning:
                self._lidar_spinning = desired
                # 재기동일 때만 스핀업 시계를 건다. 이미 회전 중이면 손대지 않는다.
                self._lidar_spinup_at = now if desired else None
                pending.append(("power.lidar_changed", Severity.INFO, {
                    "spinning": desired, "reason": reason,
                    "spinup_s": self._cfg.lidar.spinup_s if desired else 0.0,
                }))

        self._emit_all(pending)

    def _emit_all(self, pending: list[tuple]) -> None:
        if self._events is None:
            return
        for type_, severity, data in pending:
            self._events.publish(type_, severity=severity,
                                 source="power_manager", data=data)
