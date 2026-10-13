"""core_features.power.presence — PWR-002 초음파 프레즌스 판정 (D-24, 2026-10-04 개정).

ROS 무의존. `PowerManager` 가 표본을 넘기고 상태 변화만 받는다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from core_common.protocol.schemas import PresenceState


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
    # D-24 개정(2026-10-04): 검출은 "연속 유효 표본 + 최소 체류 시간" 둘 다다.
    # 표본 수만 보면 20 Hz에서 0.05 s짜리 반사파 두 개로 깨어난다.
    min_presence_s: float = 0.4     # 연속 근접이 이만큼 이어져야 검출
    max_gap_s: float = 1.0          # 근접 표본 사이가 이보다 벌어지면 연속이 끊긴다


class PresenceDetector:
    """양방향 디바운스 + 히스테리시스 + 최소 체류 시간 (D-24 개정 2026-10-04).

    단발 반사파로 깨어나지 않고, 단발 드롭아웃으로 화면이 꺼지지 않는다.

    검출(NONE→NEAR/CONTACT)은 **정말로 연속된** 유효 근접 표본이 필요하다.
    무효 표본(NaN/Inf/센서 범위 밖)과 히스테리시스 대역 표본은 검출 연속을
    끊는다 — 예전에는 둘 다 카운터를 보존해서, 몇 분 떨어진 반사파 두 개가
    "연속 2표본"으로 합쳐져 proximity 웨이크를 냈다. 해제(→NONE)는 그대로
    대역 밖 표본만 세며, 무효 표본은 해제 카운터를 건드리지 않는다.

    `now`를 주면 시간 규칙도 적용한다: 연속 근접이 `min_presence_s` 이상
    이어져야 하고, 근접 표본 간격이 `max_gap_s`를 넘으면 연속이 끊긴다.
    `now`가 없으면 표본 수만 본다(시계 없는 호출자용).
    """

    def __init__(self, config: PresenceConfig) -> None:
        self._cfg = config
        self.state: PresenceState = PresenceState.NONE
        self._near_count = 0
        self._contact_count = 0
        self._far_count = 0
        self._near_since: Optional[float] = None
        self._contact_since: Optional[float] = None
        self._last_near_at: Optional[float] = None
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

    def _break_detection(self) -> None:
        self._near_count = 0
        self._contact_count = 0
        self._near_since = None
        self._contact_since = None
        self._last_near_at = None

    def _held(self, since: Optional[float], now: Optional[float]) -> bool:
        if now is None or since is None:
            return True
        return now - since >= self._cfg.min_presence_s - 1e-9   # float tolerance

    def update(self, range_m: float, now: Optional[float] = None) -> PresenceState:
        if not self.is_valid(range_m):
            # 드롭아웃은 해제가 아니다(far 카운터 보존). 검출 연속만 끊는다.
            self._break_detection()
            return self.state

        value = float(range_m)
        cfg = self._cfg
        self.last_valid_range = value
        self.last_inside = value <= cfg.near_m + cfg.hysteresis_m

        if value < cfg.near_m:
            if (now is not None and self._last_near_at is not None
                    and now - self._last_near_at > cfg.max_gap_s):
                self._break_detection()
            self._last_near_at = now
            self._near_count += 1
            if self._near_since is None:
                self._near_since = now
            if value < cfg.contact_m:
                self._contact_count += 1
                if self._contact_since is None:
                    self._contact_since = now
            else:
                self._contact_count = 0
                self._contact_since = None
            self._far_count = 0
        elif value > cfg.near_m + cfg.hysteresis_m:
            self._break_detection()
            self._far_count += 1
        else:
            # 히스테리시스 대역 — 현 상태를 유지하되, 검출 연속은 끊는다.
            self._break_detection()
            return self.state

        if (self._contact_count >= cfg.detect_samples
                and self._held(self._contact_since, now)):
            self.state = PresenceState.CONTACT
        elif (self._near_count >= cfg.detect_samples
                and self._held(self._near_since, now)):
            self.state = PresenceState.NEAR
        elif self._far_count >= cfg.release_samples:
            self.state = PresenceState.NONE

        return self.state

    def reset(self) -> None:
        self.state = PresenceState.NONE
        self._break_detection()
        self._far_count = 0
        self.last_inside = False
