"""core_features.docking.charging — 충전 확인 (DNC-005).

**독립된 두 소스를 요구한다: 도크가 보고한 전류 그리고 떨어지지 않는 팩 전압.**

LAN 의 어떤 장치가 `charging: true` 라고 우기는 것만으로 충전 판정이 서면 안
되는 이유는, 이 판정이 D-27 deep 셧다운 억제의 입력이기 때문이다. 거짓 충전
보고 하나로 안전 경로가 꺼지고, 로봇은 죽어가는 팩 위에서 가만히 앉아 있게 된다.

전압을 두 번째 소스로 고른 것은 그것이 이미 있어서다 — `BatteryMonitor` 가
필터를 통과한 전압을 소유한다. 새 하드웨어도 새 신호도 필요 없다.

비대칭이 의도적이다. 확정은 창 전체를 요구하고 해제는 즉시다. 안전한 방향으로만
빠르게 움직인다.

설계: docs/plans/2026-09-02-docking-station-design.md §"도크만 믿지 않는다"
"""

from __future__ import annotations

import math
import time
from typing import Callable, Optional

from core_features.docking.agent import DockStatus


class ChargingConfirmation:
    """도크 보고와 전압 추세를 겹쳐 충전을 확정한다."""

    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 window_s: float = 10.0,
                 fall_tolerance_v: float = 0.02) -> None:
        self._clock = clock
        self._window_s = float(window_s)
        # 이보다 더 떨어지면 "전압이 내려가고 있다"로 본다. 표본 하나가 튀었다고
        # 판정이 무너지지 않게 하는 여유이기도 하다.
        self._fall_tolerance_v = float(fall_tolerance_v)

        self._since: Optional[float] = None      # 두 조건이 함께 성립한 시각
        self._peak_v: Optional[float] = None     # 그 구간의 최고 전압
        self._confirmed = False

    def bind_clock(self, clock: Callable[[], float]) -> None:
        """시계를 바꾼다 (도킹 매니저의 sim 시계와 같게)."""
        self._clock = clock

    def now(self) -> float:
        return self._clock()

    @property
    def confirmed(self) -> bool:
        return self._confirmed

    @property
    def holding_since(self) -> Optional[float]:
        return self._since

    def reset(self) -> None:
        self._since = None
        self._peak_v = None
        self._confirmed = False

    def update(self, status: DockStatus, voltage: Optional[float],
               now: Optional[float] = None) -> bool:
        """폴링 1회 반영. 확정 여부를 돌려준다."""
        current = self._clock() if now is None else now

        # 첫 번째 소스: 도크가 답했고, 전류가 흐른다고 말하는가.
        dock_says_charging = status.answered and status.charging

        # 두 번째 소스: 전압이 유효한가.
        has_voltage = voltage is not None and math.isfinite(float(voltage))

        if not dock_says_charging or not has_voltage:
            # 해제는 즉시다 — 창을 기다리지 않는다.
            self.reset()
            return False

        value = float(voltage)

        if self._since is None:
            self._since = current
            self._peak_v = value
            self._confirmed = False
            return False

        self._peak_v = max(self._peak_v if self._peak_v is not None else value, value)

        # 두 번째 소스의 판정: 구간 최고점 대비 허용치 이상 떨어졌는가.
        # 충전 중이라면 전압은 오르거나 최소한 유지된다. 내려간다면 전류가
        # 팩까지 도달하지 못하고 있거나 도크가 거짓말을 하고 있다.
        if self._peak_v - value > self._fall_tolerance_v:
            self.reset()
            return False

        self._confirmed = (current - self._since) >= self._window_s
        return self._confirmed
