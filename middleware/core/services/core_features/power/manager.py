"""core_features.power.manager — PWR-001~004 절전 모드/근접 웨이크 (D-24).

정책만 담당한다. 센서 샘플링 주기와 디스플레이 상태, 기기별 전원 수준을 선언한다.
E-Stop·cmd_vel 먹서·워치독에는 권한이 없다. 바퀴에 닿는 것은 `motion_ready()`
하나다(D-440 5): CORE 최종 cmd_vel 주기가 이 값이 False 인 동안 0 을 낸다.
ROS 무의존 — 시계는 주입되며 테스트가 시간을 직접 전진시킨다.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from core_common.protocol.schemas import (
    DevicePowerState,
    PowerMode,
    PowerStatus,
    PresenceState,
    RobotMode,
    Severity,
)
from core_features.power.devices import DeviceLevel, DevicePolicy, DevicePolicyConfig
from core_features.power.presence import PresenceConfig, PresenceDetector  # noqa: F401

# 웨이크 사유 — 이벤트/REST 페이로드에 그대로 실린다.
WAKE_PROXIMITY = "proximity"
WAKE_CONTACT = "contact"
WAKE_ACTIVITY = "activity"
WAKE_API = "api"
WAKE_BATTERY = "battery"
WAKE_COMMAND = "command"


@dataclass
class LidarPolicy:
    """STANDBY LiDAR 모터 정지 (PWR-005) — 기기별 정책 이전의 개별 스위치.

    `standby_stop: true`는 기기별 정책(`devices.py`)의 lidar 항목을 이 로봇에서
    벤치 스위치와 무관하게 켠다(호환용). 새 설정은 `power.device_policy`를 쓴다.

    기본 비활성이다. 인터록상 안전하지만(STANDBY는 로봇 모드 IDLE에서만 진입,
    모든 웨이크가 재기동을 선행한다) 5분간 스캔이 끊겼을 때 Nav2 라이프사이클이
    어떻게 반응하는지는 실기에서 관찰해야 할 통합 동작이다. 벤치 승인 후 켠다.
    """

    standby_stop: bool = False      # STANDBY에서 stop_motor 호출 여부
    spinup_s: float = 2.0           # start_motor 후 스캔을 신뢰하기까지의 시간


@dataclass
class PowerConfig:
    enabled: bool = True
    idle_after_s: float = 600.0
    standby_after_s: float = 1800.0
    warning_idle_after_s: float = 60.0
    warning_standby_after_s: float = 300.0
    critical_idle_after_s: float = 30.0
    critical_standby_after_s: float = 120.0
    info_hold_s: float = 15.0
    active_rate_hz: float = 20.0
    idle_rate_hz: float = 5.0
    standby_rate_hz: float = 2.0
    presence: PresenceConfig = field(default_factory=PresenceConfig)
    lidar: LidarPolicy = field(default_factory=LidarPolicy)
    device_policy: DevicePolicyConfig = field(default_factory=DevicePolicyConfig)


LIDAR = "lidar"


def _effective_devices(cfg: PowerConfig) -> dict[str, DevicePolicy]:
    """Declared devices plus the legacy `lidar.standby_stop` opt-in."""
    devices = dict(cfg.device_policy.devices)
    if cfg.lidar.standby_stop:
        declared = devices.get(LIDAR)
        if declared is None:
            devices[LIDAR] = DevicePolicy(
                name=LIDAR, standby=DeviceLevel.OFF, wake_ready_s=cfg.lidar.spinup_s,
                required_for_motion=True, enabled=True)
        else:
            devices[LIDAR] = DevicePolicy(
                name=LIDAR, idle=declared.idle, standby=declared.standby,
                wake_ready_s=declared.wake_ready_s,
                required_for_motion=declared.required_for_motion, enabled=True)
    return devices


_RATE_ATTR = {
    PowerMode.ACTIVE: "active_rate_hz",
    PowerMode.IDLE: "idle_rate_hz",
    PowerMode.STANDBY: "standby_rate_hz",
}


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
        self._battery_alert = "ok"

        # 기기별 정책. 기기는 core 기동 시점에 이미 켜져 있다 — 준비 페널티 없이
        # 시작한다. `_on_since` None = 처음부터 켜져 있음, 실수 = 그 시각에 다시 켰다.
        # `_reported` None = 꺼진 적 없음, False = 깨운 뒤 확인 보고를 기다리는 중
        # (또는 기기가 준비 안 됨을 알림), True = 기기가 준비를 알렸다.
        # 정책이 실제로 움직이는 기기는 예외다: CORE가 절전 중에 다시 떴다면 그 기기는
        # 꺼져 있을 수 있다. 그래서 켜는 명령을 다시 보내고(브리지) 확인 보고를 기다린다.
        self._devices = _effective_devices(config)
        managed = {name for name, policy in self._devices.items()
                   if config.enabled and config.device_policy.active(policy)}
        self._levels: dict[str, DeviceLevel] = {name: DeviceLevel.ON for name in self._devices}
        self._on_since: dict[str, Optional[float]] = {
            name: self._last_activity if name in managed else None for name in self._devices}
        self._reported: dict[str, Optional[bool]] = {
            name: False if name in managed else None for name in self._devices}

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
        return self.device_level(LIDAR) != DeviceLevel.OFF

    def lidar_ready(self, now: Optional[float] = None) -> bool:
        """스캔을 신뢰할 수 있는가 — 회전 중이며 스핀업이 끝났을 때만 참."""
        return self.device_ready(LIDAR, now)

    # --- 기기별 정책 -----------------------------------------------------------

    @property
    def devices(self) -> dict[str, DevicePolicy]:
        """선언된 기기(유효 정책). 선언되지 않은 기기는 항상 켜져 있다."""
        return dict(self._devices)

    def managed_devices(self) -> set[str]:
        """정책이 실제로 움직이는 기기 (전원 정책 켜짐 + 벤치 스위치/기기 스위치)."""
        return {name for name, policy in self._devices.items()
                if self._cfg.enabled and self._cfg.device_policy.active(policy)}

    def device_level(self, name: str) -> DeviceLevel:
        with self._lock:
            return self._levels.get(name, DeviceLevel.ON)

    def device_levels(self) -> dict[str, DeviceLevel]:
        with self._lock:
            return dict(self._levels)

    def device_ready(self, name: str, now: Optional[float] = None) -> bool:
        current = self._clock() if now is None else now
        with self._lock:
            return self._device_ready_locked(name, current)

    def report_device_ready(self, name: str, ready: bool) -> None:
        """어댑터가 기기의 실제 준비 상태를 알린다.

        꺼졌다 켜진 기기는 이 보고(True)가 와야 준비된다 — 타이머만으로는 준비되지
        않는다. 깨우는 명령이 기기에 닿지 않았으면 보고도 없으므로 주행은 0에 머문다.
        꺼져 있는 동안 온 보고는 버린다(멈추기 직전의 마지막 스캔이 확인이 되면 안 된다).
        꺼진 적이 없는 기기의 보고도 버린다 — 정책이 꺼진 로봇에서는 어떤 보고도
        주행을 막지 못한다.
        """
        with self._lock:
            if (self._reported.get(name) is not None
                    and self._levels[name] != DeviceLevel.OFF):
                self._reported[name] = bool(ready)

    def device_restarted(self, name: str, now: Optional[float] = None) -> None:
        """어댑터가 켜는 명령을 실제로 내보낸 시각 — 준비 시계를 거기서 다시 센다.

        명령이 늦게 나가면(서비스가 아직 없음) 수준이 바뀐 시각부터 센 시계는 이미
        지나 있다. 그러면 첫 보고가 곧바로 준비가 되어 스핀업 구간을 건너뛴다.
        명령이 나가기 전에 온 보고(멈추는 중에 남은 스캔)는 확인이 아니므로 지운다.
        """
        current = self._clock() if now is None else now
        with self._lock:
            if self._on_since.get(name) is not None:
                self._on_since[name] = current
                self._reported[name] = False

    def motion_ready(self, now: Optional[float] = None) -> bool:
        """주행에 필요한 기기(required_for_motion)가 모두 준비됐는가 (S3 게이트)."""
        current = self._clock() if now is None else now
        with self._lock:
            return self._motion_ready_locked(current)

    def _motion_ready_locked(self, now: float) -> bool:
        return all(self._device_ready_locked(name, now)
                   for name, policy in self._devices.items() if policy.required_for_motion)

    def _device_ready_locked(self, name: str, now: float) -> bool:
        policy = self._devices.get(name)
        if policy is None:
            return True
        if self._levels[name] == DeviceLevel.OFF:
            return False
        if self._reported[name] is False:      # 깨운 뒤 확인이 아직 없다 — fail safe
            return False
        since = self._on_since[name]
        return since is None or now - since >= policy.wake_ready_s

    def _desired_level(self, name: str, mode: PowerMode) -> DeviceLevel:
        policy = self._devices[name]
        if not (self._cfg.enabled and self._cfg.device_policy.active(policy)):
            return DeviceLevel.ON
        return policy.level_for(mode)

    def info_visible(self, now: Optional[float] = None) -> bool:
        current = self._clock() if now is None else now
        with self._lock:
            return current < self._info_until

    def status(self, now: Optional[float] = None) -> PowerStatus:
        current = self._clock() if now is None else now
        managed = self.managed_devices()
        with self._lock:
            return PowerStatus(
                mode=self._mode,
                presence=self._detector.state,
                info_visible=current < self._info_until,
                sample_rate_hz=self._rate_for(self._mode),
                last_wake_reason=self._last_wake_reason,
                idle_seconds=max(0.0, current - self._last_activity),
                lidar_spinning=self._levels.get(LIDAR, DeviceLevel.ON) != DeviceLevel.OFF,
                lidar_ready=self._device_ready_locked(LIDAR, current),
                devices=[
                    DevicePowerState(
                        name=name, level=self._levels[name].value,
                        ready=self._device_ready_locked(name, current),
                        managed=name in managed,
                        required_for_motion=policy.required_for_motion)
                    for name, policy in sorted(self._devices.items())],
                motion_ready=self._motion_ready_locked(current),
            )

    # --- 입력 -----------------------------------------------------------------

    def on_range(self, range_m: float, now: Optional[float] = None) -> None:
        """초음파 표본 1건 반영 (PWR-002)."""
        current = self._clock() if now is None else now
        if not self._detector.is_valid(range_m):
            self._detector.update(range_m, now=current)    # 검출 연속만 끊는다
            return

        previous = self._detector.state
        state = self._detector.update(range_m, now=current)
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

    def on_command(self, source: str, now: Optional[float] = None) -> None:
        """명령 1건 (D-24 개정 2026-10-04) — 무명령 타이머를 리셋하고 즉시 ACTIVE.

        "명령"은 로봇에게 무언가를 하라는 요청이 받아들여진 것이다: teleop,
        목표/내비게이션, 미션, 모드 전환, Fleet 작업, 0이 아닌 최종 cmd_vel.
        GET·텔레메트리·WS 구독은 명령이 아니다 — 대시보드를 열어 두기만 해서
        로봇이 영영 잠들지 못하면 안 된다. 정보 창은 열지 않는다(사람이 앞에
        있다는 증거가 아니다). 절전 중이었다면 웨이크 사유를 남긴다.
        """
        current = self._clock() if now is None else now
        pending: list[tuple] = []
        with self._lock:
            self._last_activity = current
            if self._mode != PowerMode.ACTIVE:
                self._last_wake_reason = WAKE_COMMAND
                pending.append(("power.wake", Severity.INFO,
                                {"reason": WAKE_COMMAND, "source": source}))
        self._emit_all(pending)
        self._evaluate(current, reason=f"command:{source}")

    def on_battery_alert(self, state: str, now: Optional[float] = None) -> None:
        """SAF-005 임계 통과 — 로봇 본체에서 바로 보이도록 깨운다."""
        with self._lock:
            previous, self._battery_alert = self._battery_alert, state
        if state != previous and state in ("warning", "critical", "deep"):
            self.wake(WAKE_BATTERY, now=now)

    def _dwell_limits(self) -> tuple[float, float]:
        cfg = self._cfg
        normal = (cfg.idle_after_s, cfg.standby_after_s)
        if self._battery_alert == "warning":
            return (min(normal[0], cfg.warning_idle_after_s), min(normal[1], cfg.warning_standby_after_s))
        if self._battery_alert in ("critical", "deep"):
            return (min(normal[0], cfg.critical_idle_after_s), min(normal[1], cfg.critical_standby_after_s))
        return normal

    def health(self) -> dict:
        with self._lock:
            blockers = []
            if not self._cfg.enabled:
                blockers.append("power_policy_disabled")
            if self._hold_active:
                blockers.append("robot_mode_not_idle")
            if self._clock() < self._info_until:
                blockers.append("information_hold")
            return {
                "sleep_blockers": blockers,
                "deepest_available_mode": "ACTIVE" if blockers else "STANDBY", "deepest_mode_basis": "policy_target",
                "effective_idle_after_s": self._dwell_limits()[0],
                "effective_standby_after_s": self._dwell_limits()[1],
                "battery_alert": self._battery_alert,
                "idle_after_s": self._cfg.idle_after_s, "standby_after_s": self._cfg.standby_after_s,
                "wake_sources": ["api", "proximity", "contact", "activity", "battery_level_change"],
                "wake_sources_basis": "policy_supported_not_hardware_verified",
                "api_wake_requires_running_os": True,
                "os_halt_remote_wake": "not_verified",
                "lidar_standby_stop_enabled": self._cfg.lidar.standby_stop, "lidar_state_basis": "policy_intent",
            }

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
            dwell = self._dwell_limits()[1 if mode == PowerMode.STANDBY else 0]
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
                idle_after, standby_after = self._dwell_limits()
                if dwell >= standby_after:
                    target = PowerMode.STANDBY
                elif dwell >= idle_after:
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

            # 기기 수준은 모드의 순수 함수다. 모드가 그대로여도 설정 변경으로
            # 어긋날 수 있으므로 조기 반환 없이 매번 조정한다.
            for name, policy in self._devices.items():
                desired = self._desired_level(name, self._mode)
                previous_level = self._levels[name]
                if desired == previous_level:
                    continue
                self._levels[name] = desired
                # OFF에서 돌아올 때만 준비 시계를 건다. 켜진 채 수준만 바뀌면 그대로다.
                # 돌아온 기기는 확인 보고가 올 때까지 준비되지 않는다(fail safe).
                if previous_level == DeviceLevel.OFF:
                    self._on_since[name] = now
                    self._reported[name] = False
                pending.append(("power.device_changed", Severity.INFO, {
                    "device": name, "from": previous_level.value, "to": desired.value,
                    "reason": reason, "wake_ready_s": policy.wake_ready_s,
                }))
                was_off, now_off = previous_level == DeviceLevel.OFF, desired == DeviceLevel.OFF
                if name == LIDAR and was_off != now_off:
                    pending.append(("power.lidar_changed", Severity.INFO, {
                        "spinning": not now_off, "reason": reason,
                        "spinup_s": 0.0 if now_off else policy.wake_ready_s,
                    }))

        self._emit_all(pending)

    def _emit_all(self, pending: list[tuple]) -> None:
        if self._events is None:
            return
        for type_, severity, data in pending:
            self._events.publish(type_, severity=severity,
                                 source="power_manager", data=data)
