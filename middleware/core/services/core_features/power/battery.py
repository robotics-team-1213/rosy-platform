"""core_features.power.battery — SAF-005 배터리 무결성/저배터리 경보.

정책만 담당한다. 전압을 걸러 잔량으로 옮기고, 경보 단계를 판정하고, LED 표시
의도와 셧다운 요청을 선언할 뿐이다. LED 서비스도 파일 시스템 밖의 어떤 하드웨어도
직접 건드리지 않는다 — 조정은 ros_bridge가 한다.

ROS 무의존 — 시계는 주입되며 테스트가 시간을 직접 전진시킨다.

설계: docs/plans/2026-09-02-battery-integrity-low-battery-alert-design.md
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from core_common.protocol.schemas import BatteryLevel, BatteryStatus

# 2S Li-ion 개방회로 전압 곡선 (팩 전압, percent). 설정이 없으면 이것을 쓴다.
DEFAULT_CURVE_2S: tuple[tuple[float, float], ...] = (
    (8.40, 100.0), (8.12, 90.0), (7.96, 80.0), (7.84, 70.0),
    (7.74, 60.0), (7.64, 50.0), (7.58, 40.0), (7.50, 30.0),
    (7.42, 20.0), (7.32, 10.0), (6.60, 5.0), (6.40, 0.0),
)


class BatteryCurve:
    """전압 → 잔량 구간별 선형 보간.

    리튬이온은 선형으로 방전되지 않는다. 두 점 스팬으로 환산하면 방전 대부분을
    차지하는 평탄 구간이 실제보다 높게 보고되고, 그러다 임계까지 몇 분 만에
    떨어진다. SAF-005가 percent로 쓰여 있으므로 percent가 남은 에너지를 따라가야
    한다.
    """

    def __init__(self, points: Sequence[tuple[float, float]]) -> None:
        if len(points) < 2:
            raise ValueError("battery curve needs at least two points")

        # 설정 파일이 낮은 전압부터 쓰는 것도 흔하다 — 순서로 거부하지 않고 맞춘다.
        ordered = sorted(points, key=lambda p: float(p[0]), reverse=True)

        for (v_hi, _), (v_lo, _) in zip(ordered, ordered[1:]):
            if float(v_hi) == float(v_lo):
                raise ValueError(f"battery curve has a duplicate voltage: {v_hi}")

        # 전압 내림차순으로 정렬한 뒤에도 percent가 뒤집히면 보간이 무의미해진다.
        for (_, p_hi), (_, p_lo) in zip(ordered, ordered[1:]):
            if float(p_lo) > float(p_hi):
                raise ValueError(
                    f"battery curve is not monotonic: {p_lo} follows {p_hi}")

        self._points: tuple[tuple[float, float], ...] = tuple(
            (float(v), float(p)) for v, p in ordered)

    @classmethod
    def from_span(cls, full: float, empty: float) -> "BatteryCurve":
        """기존 two-point 스팬 — 곡선 설정이 없을 때의 폴백."""
        if float(full) <= float(empty):
            raise ValueError("battery_full_voltage must exceed battery_empty_voltage")
        return cls([(float(full), 100.0), (float(empty), 0.0)])

    @classmethod
    def default(cls) -> "BatteryCurve":
        return cls(DEFAULT_CURVE_2S)

    @property
    def points(self) -> tuple[tuple[float, float], ...]:
        return self._points

    def percent(self, voltage: float) -> float:
        value = float(voltage)
        points = self._points

        if value >= points[0][0]:
            return points[0][1]
        if value <= points[-1][0]:
            return points[-1][1]

        for (v_hi, p_hi), (v_lo, p_lo) in zip(points, points[1:]):
            if value >= v_lo:
                ratio = (value - v_lo) / (v_hi - v_lo)
                return p_lo + ratio * (p_hi - p_lo)

        return points[-1][1]      # 도달 불가 — 위 클램프가 이미 처리한다.


# 낮아지는 순서. 단계 이동은 이 배열에서 한 칸씩만 일어난다.
_LEVEL_ORDER: tuple[BatteryLevel, ...] = (
    BatteryLevel.OK,
    BatteryLevel.WARNING,
    BatteryLevel.CRITICAL,
    BatteryLevel.DEEP,
)

# 단계별 LED 의도 (R, G, B, blink_hz). 기존 _LED_STEPS 와 같은 밝기 대역(최대 60).
_LED_ALERTS: dict[BatteryLevel, tuple[int, int, int, float]] = {
    BatteryLevel.WARNING: (30, 20, 0, 0.0),     # 감광 주황, 상시
    BatteryLevel.CRITICAL: (60, 0, 0, 1.0),     # 빨강 1 Hz
    BatteryLevel.DEEP: (60, 0, 0, 2.0),         # 빨강 2 Hz
}


@dataclass(frozen=True)
class LedAlert:
    """LED 표시 의도. 서비스 호출은 ros_bridge가 한다 — 이 계층은 선언만 한다.

    깜빡임은 세 가지 이유로 상시 점등보다 낫다. 변하는 빛이 주변시에 훨씬 잘
    걸리고, 듀티 50%는 소모를 절반으로 줄이며(소모를 항의하는 표시가 소모를
    덜 쓴다), 30% 미만에서 빨강인 기존 게이지 색과 구분된다.
    """

    level: "BatteryLevel"
    r: int
    g: int
    b: int
    blink_hz: float

    def lit_at(self, now: float) -> bool:
        """이 시각에 켜져 있어야 하는가. 시계의 순수 함수 — 상태가 없다."""
        if self.blink_hz <= 0.0:
            return True
        return (float(now) * self.blink_hz) % 1.0 < 0.5


# 근접 정보창에서 보여주는 잔량 게이지 (percent 하한, R, G, B).
# ros_bridge 에 있던 _LED_STEPS 를 옮겨왔다 — LED 색을 정하는 곳은 하나여야 한다.
_LED_GAUGE: tuple[tuple[float, int, int, int], ...] = (
    (60.0, 0, 60, 0),
    (30.0, 60, 40, 0),
    (0.0, 60, 0, 0),
)


@dataclass(frozen=True)
class LedCommand:
    """LED 서비스에 그대로 넘길 명령. 동치 비교가 되어야 반복 호출을 건너뛴다."""

    command: str        # "fill" | "clear"
    r: int = 0
    g: int = 0
    b: int = 0


_LED_CLEAR = LedCommand("clear")


def resolve_led(alert: Optional[LedAlert], info_visible: bool,
                gauge_percent: Optional[float], now: float) -> LedCommand:
    """설계 §"표시 권한"의 우선순위를 한곳에서 결정한다.

    경보가 살아 있으면 정보창 게이지보다 위다. 깜빡임의 어두운 국면에도 게이지로
    떨어지지 않는다 — 그러면 깜빡임이 아니라 두 색의 교대로 보인다.
    """
    if alert is not None:
        if not alert.lit_at(now):
            return _LED_CLEAR
        return LedCommand("fill", alert.r, alert.g, alert.b)

    if info_visible and gauge_percent is not None:
        for floor, r, g, b in _LED_GAUGE:
            if gauge_percent >= floor:
                return LedCommand("fill", r, g, b)

    return _LED_CLEAR


@dataclass
class BatteryConfig:
    """SAF-005 임계와 필터 파라미터. 전부 `safety:` 블록에서 주입된다."""

    curve: BatteryCurve = field(default_factory=BatteryCurve.default)

    # 저역통과 시상수(s). 0이면 필터를 끈다.
    filter_tau_s: float = 5.0

    warning_percent: float = 20.0
    critical_percent: float = 10.0
    deep_percent: float = 5.0

    enter_samples: int = 3          # 한 단계 내려가는 데 필요한 연속 표본
    exit_samples: int = 5           # 한 단계 올라오는 데 필요한 연속 표본
    hysteresis_percent: float = 3.0  # 복귀는 임계 + 이 마진을 넘어야 시작된다

    # DEEP을 이만큼 유지해야 셧다운이 무장된다. 표본 수가 아니라 초다 —
    # 어떤 필터 튜닝으로도 순간값이 셧다운을 일으키지 못하게 한다.
    deep_dwell_s: float = 60.0

    # 센티넬 파일 경로. None이면 판정은 살아 있되 파일을 쓰지 않는다
    # (시뮬레이션·벤치에서 호스트를 끄지 않기 위한 기본값).
    sentinel_path: Optional[Path] = None

    # 센티넬에 적어 호스트 유닛에 전달할 유예 시간(s). 판정은 호스트가 한다.
    shutdown_grace_s: float = 120.0

    def threshold_for(self, level: BatteryLevel) -> float:
        return {
            BatteryLevel.WARNING: float(self.warning_percent),
            BatteryLevel.CRITICAL: float(self.critical_percent),
            BatteryLevel.DEEP: float(self.deep_percent),
        }[level]


class BatteryMonitor:
    """전압 필터 + 잔량 환산 (SAF-005).

    모터 전류 새그 한 발이 E-Stop까지 가지 못하게 막는 것이 이 계층의 존재 이유다.
    """

    def __init__(self, config: BatteryConfig,
                 clock: Callable[[], float] = time.monotonic,
                 events: Any = None) -> None:
        self._cfg = config
        self._clock = clock
        self._events = events
        self._lock = threading.Lock()

        self._voltage: Optional[float] = None
        self._last_sample_at: Optional[float] = None

        self._level = BatteryLevel.OK
        self._descend_count = 0
        self._ascend_count = 0
        self._deep_since: Optional[float] = None
        self._deep_announced = False
        self._sentinel_written = False
        self._charging = False

    def apply_thresholds(
        self,
        warning_percent: Optional[float] = None,
        critical_percent: Optional[float] = None,
        deep_percent: Optional[float] = None,
    ) -> None:
        """Runtime SAF-005 thresholds. Does not rewrite the OCV curve."""
        with self._lock:
            if warning_percent is not None:
                self._cfg.warning_percent = float(warning_percent)
            if critical_percent is not None:
                self._cfg.critical_percent = float(critical_percent)
            if deep_percent is not None:
                self._cfg.deep_percent = float(deep_percent)

    # --- 조회 -----------------------------------------------------------------

    @property
    def voltage(self) -> Optional[float]:
        """필터를 통과한 전압. 표본이 하나도 없으면 None."""
        with self._lock:
            return self._voltage

    @property
    def percent(self) -> Optional[float]:
        """필터된 전압에 대응하는 잔량 추정치. 전류 센싱이 없으므로 추정치다."""
        with self._lock:
            return self._percent_locked()

    def _percent_locked(self) -> Optional[float]:
        if self._voltage is None:
            return None
        return self._cfg.curve.percent(self._voltage)

    @property
    def level(self) -> BatteryLevel:
        with self._lock:
            return self._level

    @property
    def led_alert(self) -> Optional[LedAlert]:
        """표시 의도. OK이거나 표본이 없으면 None — 그때만 기존 게이지가 나온다.

        전원 모드를 보지 않는다. STANDBY에서도 경보는 살아 있어야 하고, 그것이
        이 기능의 존재 이유다.
        """
        with self._lock:
            if self._voltage is None:
                return None
            spec = _LED_ALERTS.get(self._level)
            if spec is None:
                return None
            r, g, b, blink_hz = spec
            return LedAlert(level=self._level, r=r, g=g, b=b, blink_hz=blink_hz)

    @property
    def shutdown_armed(self) -> bool:
        """DEEP을 dwell 만큼 유지했는가 — 셧다운 요청의 유일한 조건."""
        with self._lock:
            return self._shutdown_armed_locked()

    def status(self) -> BatteryStatus:
        """상태 스냅샷에 실리는 additive 필드."""
        with self._lock:
            return BatteryStatus(
                level=self._level,
                shutdown_armed=self._shutdown_armed_locked(),
                filtered_voltage=self._voltage,
                charging=self._charging,
            )

    def _shutdown_armed_locked(self) -> bool:
        # 충전 중이면 무장하지 않는다 (D-27 인터록). 4%에 도크에 도착한 로봇은
        # 수 분간 DEEP 을 유지하는데, 그 사이에 halt 하면 충전기 위에서 꺼지고
        # D-25 대로 전원 버튼 말고는 깨어날 방법이 없다.
        if self._charging:
            return False
        if self._level is not BatteryLevel.DEEP or self._deep_since is None:
            return False
        if self._last_sample_at is None:
            return False
        return self._last_sample_at - self._deep_since >= self._cfg.deep_dwell_s

    # --- 입력 -----------------------------------------------------------------

    def set_charging(self, confirmed: bool) -> None:
        """확인된 충전 여부를 반영한다 (D-27 인터록).

        `confirmed` 는 도크의 주장이 아니라 `ChargingConfirmation` 의 판정이다 —
        도크가 보고한 전류 *그리고* 떨어지지 않는 전압. LAN 의 장치 하나가
        말만으로 안전 경로를 끄지 못하게 하는 것이 그 이중화의 목적이다.

        충전이 끊기면 dwell 을 처음부터 다시 센다. 플러그가 빠졌다고 즉시
        꺼지면 안 된다.
        """
        pending: list[tuple] = []
        with self._lock:
            if bool(confirmed) == self._charging:
                return
            self._charging = bool(confirmed)
            if not self._charging and self._level is BatteryLevel.DEEP:
                self._deep_since = self._last_sample_at
            self._reconcile_sentinel_locked(pending)
        self._emit_all(pending)

    def on_voltage(self, voltage: float, now: Optional[float] = None) -> None:
        """ADC 표본 1건 반영. 유한하지 않은 값은 필터를 건드리지 않고 버린다."""
        try:
            value = float(voltage)
        except (TypeError, ValueError):
            return
        if not math.isfinite(value):
            return

        current = self._clock() if now is None else now
        pending: list[tuple] = []

        with self._lock:
            if self._voltage is None:
                # 첫 표본은 0에서 램프업하지 않고 그 값으로 필터를 앉힌다.
                self._voltage = value
            else:
                self._voltage = self._filtered_locked(value, current)
            self._last_sample_at = current

            self._evaluate_level_locked(current, pending)
            self._reconcile_sentinel_locked(pending)

        self._emit_all(pending)

    # --- 셧다운 센티넬 ---------------------------------------------------------

    def _reconcile_sentinel_locked(self, pending: list[tuple]) -> None:
        """무장 여부에 파일을 맞춘다. 명령이 아니라 관찰의 표식이다 — 판단과
        실행은 호스트 유닛이 한다. 회복하면 지워지므로, 유예 중 충전이 시작되면
        별도 신호 없이 셧다운이 취소된다.
        """
        path = self._cfg.sentinel_path
        if path is None:
            return

        armed = self._shutdown_armed_locked()
        if armed == self._sentinel_written:
            return

        try:
            if armed:
                self._write_sentinel_locked(path)
            else:
                path.unlink(missing_ok=True)
            self._sentinel_written = armed
        except OSError as error:
            # ROS 콜백 안에서 도는 코드다. 예외를 올리면 구독이 죽는다.
            pending.append(("battery.shutdown_request_failed", "error", {
                "path": str(path), "error": str(error), "armed": armed,
            }))

    def _write_sentinel_locked(self, path: Path) -> None:
        document = {
            "requested_at": datetime.now(timezone.utc).isoformat(
                timespec="milliseconds"),
            "reason": "battery_deep_discharge",
            "percent": round(self._percent_locked() or 0.0, 1),
            "voltage": round(self._voltage or 0.0, 2),
            "grace_seconds": float(self._cfg.shutdown_grace_s),
        }
        # 임시 파일 + rename — 호스트가 반쪽짜리 문서를 읽는 창이 없어야 한다.
        temp = path.with_name(path.name + ".tmp")
        temp.write_text(json.dumps(document, indent=2), encoding="utf-8")
        os.replace(temp, path)

    def _evaluate_level_locked(self, now: float, pending: list[tuple]) -> None:
        percent = self._percent_locked()
        if percent is None:
            return

        cfg = self._cfg
        index = _LEVEL_ORDER.index(self._level)

        # 한 칸 아래 단계의 임계를 밑돌고 있는가.
        lower = _LEVEL_ORDER[index + 1] if index + 1 < len(_LEVEL_ORDER) else None
        descending = lower is not None and percent <= cfg.threshold_for(lower)

        # 현재 단계의 임계 + 히스테리시스 마진을 넘어섰는가.
        ascending = (self._level is not BatteryLevel.OK
                     and percent > cfg.threshold_for(self._level) + cfg.hysteresis_percent)

        if descending:
            self._ascend_count = 0
            self._descend_count += 1
            if self._descend_count >= cfg.enter_samples:
                self._set_level_locked(lower, now, pending)
        elif ascending:
            self._descend_count = 0
            self._ascend_count += 1
            if self._ascend_count >= cfg.exit_samples:
                self._set_level_locked(_LEVEL_ORDER[index - 1], now, pending)
        else:
            # 히스테리시스 대역 — 어느 쪽으로도 세지 않고 현 단계를 유지한다.
            self._descend_count = 0
            self._ascend_count = 0

    def _set_level_locked(self, level: BatteryLevel, now: float,
                          pending: list[tuple]) -> None:
        self._level = level
        self._descend_count = 0
        self._ascend_count = 0

        if level is BatteryLevel.DEEP:
            self._deep_since = now
            # 진입 순간이 모터가 멈추는 순간이다. dwell 만료를 기다리면 감사
            # 로그가 실제 사건보다 늦게 남는다.
            if not self._deep_announced:
                self._deep_announced = True
                pending.append(("battery.deep", "critical", {
                    "percent": round(self._percent_locked() or 0.0, 1),
                    "voltage": round(self._voltage or 0.0, 2),
                    "dwell_s": self._cfg.deep_dwell_s,
                }))
        else:
            self._deep_since = None
            self._deep_announced = False

    def _emit_all(self, pending: list[tuple]) -> None:
        if self._events is None:
            return
        for type_, severity, data in pending:
            self._events.publish(type_, severity=severity,
                                 source="battery_monitor", data=data)

    def _filtered_locked(self, value: float, now: float) -> float:
        tau = float(self._cfg.filter_tau_s)
        if tau <= 0.0:
            return value

        previous_at = self._last_sample_at
        dt = 0.0 if previous_at is None else max(0.0, now - previous_at)
        if dt <= 0.0:
            # 같은 시각에 두 표본이 오면 시간이 흐르지 않았으므로 값도 움직이지 않는다.
            return self._voltage

        alpha = 1.0 - math.exp(-dt / tau)
        return self._voltage + alpha * (value - self._voltage)
