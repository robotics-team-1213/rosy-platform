"""core_features.docking.bay_guards — 칸 후진 파킹 위치 맞춤 보강(패널 r1, 2026-11-19).
순수 함수(제어 법칙·진입 허용창·뒤 여유 판정)와 `BayPhases` 믹스인(맹목 예산·같은 사유 두 번 실패). 수치 근거:
운동학 시뮬(옆 칸 양쪽 채움, 시작 옆 오차 0~9 cm, 방위 ±15°, 진입 along 0.41 m; 전후 비교 접촉 30→0). 정지 우선: 어느 것도 가드 한계를 넓히지 않고, 넘으면 멈추고 다시 들어간다. ROS 무의존.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Optional


def reverse_twist(cfg: Any, lateral: float, heading: float) -> float:
    """후진 각속도. 옆 오차는 목표 방위로 바꾸고(상한 있음) 방위를 거기에 맞춘다.
    포화 전에는 예전 식 -(kl*횡 + kh*방위) 와 같다 — 다른 점은 kh 0.6→1.2(감쇠 ζ≈0.47→0.95, 끝 넘침 감소)와
    목표 방위 상한이다(5 cm·0° 시작: 방위 피크 20.5°→13.2°, 0.10 m 지점 횡 -8.5→+4.3 mm; 짐칸 끝이 옆 칸으로 쓸리는 양)."""
    cap = cfg.bay_target_heading_max_rad
    target = -max(-cap, min(cap, cfg.bay_gain_lateral / cfg.bay_gain_heading * lateral))
    return max(-cfg.max_angular, min(cfg.max_angular, -cfg.bay_gain_heading * (heading - target)))


def entry_ok(cfg: Any, along: float, lateral: float, heading: float) -> bool:
    """ALIGNING 에 들어가도 되는 오차인가. 허용 횡은 남은 거리가 길수록 넓다: 이 법칙이 그 거리 안에 0.10 m
    지점(가이드 목, ±6 mm)까지 수렴하는 한계(sim: 방위 10°에서 along 0.305→15 mm, 0.41→45 mm, 0.6→90 mm)를
    0.25*(along-0.25) 로 아래에서 근사했다. 앞으로 빠지면 along 이 늘어 같은 오차가 허용창에 들어올 수 있다."""
    lat_max = min(cfg.bay_entry_lat_max_m,
                  max(cfg.bay_entry_lat_base_m, cfg.bay_entry_lat_slope * (along - cfg.bay_entry_lat_from_m)))
    return abs(lateral) <= lat_max and abs(heading) <= cfg.bay_entry_heading_max_rad


def rear_blocked(cfg: Any, rear_gap: Optional[float], along: Optional[float]) -> bool:
    """LiDAR 뒤 여유(짐칸 끝~첫 점)가 카메라로 잰 멈춤면까지 남은 거리(along - 짐칸 돌출)보다 확실히 작으면 칸
    안에 뭔가 있다. 멈춤면 자체가 보여도 gap≈남은 거리라 막지 않는다. 여유 = 몸 스캔 지연 0.5 s×0.05 m/s 2.5 cm +
    LiDAR·카메라 오차 각 1~2 cm. 값이 없으면 판단하지 않는다(기존 동작). gap 0.0 은 '점 없음'과 '접촉'이 같이
    0 으로 오므로 정지 쪽으로 읽는다(정지 우선)."""
    if rear_gap is None or along is None:
        return False
    return rear_gap < max(0.0, along - cfg.bay_turn_rear_overhang_m) - cfg.bay_rear_gap_margin_m


def heading_gate(cfg: Any, omega: float, age_s: float) -> float:
    """프레임당 방위 점프 게이트 + 관측 나이 동안 돈 양. 나이 든 정상 프레임이 회전 중 게이트에 걸리지 않게."""
    return cfg.bay_gate_jump_rad + abs(omega) * max(0.0, age_s)


class BayGuardsMixin:
    """`BayPhases` 의 맹목 예산과 같은 사유 반복 기억. 상태는 여기, 락은 매니저의 것."""

    def _init_guards(self) -> None:
        self._blind_s = 0.0           # 횡을 못 잰 채(통로선만) 후진한 시간
        self._blind_m = 0.0           # 그 거리 — 추정값(맵·명령 적분)으로 리셋하지 않는다
        self._along_m: Optional[float] = None   # 이번 관측의 along(실측일 때만)
        self._obs_age = 0.0
        self._omega = 0.0             # 마지막 명령 각속도
        self._seen: dict[str, int] = {}         # 사유별 가드 실패 횟수(첫 시도에서만 비운다)

    def _blind_lateral(self, dt: float, speed: float) -> bool:
        """횡 맹목 예산: 실측 횡이 없는 프레임으로만 후진한 거리·시간(0.10 m / 2 s — 통로선→칸 선이 들어오는
        데 필요한 길이의 두 배쯤)을 넘으면 정지하고 재진입. 실측 횡 프레임이 오면 비운다. 프레임이 없을 땐 세지
        않는다(코스트·스캔 사다리가 맡는다)."""
        h, cfg = self._h, self._h._cfg
        raw = h._detector.relative_pose() if h._detector is not None else None
        if raw is None:
            return False
        if raw.lateral_measured:
            self._blind_s = self._blind_m = 0.0
            return False
        self._blind_s += dt
        self._blind_m += speed * dt
        if self._blind_m <= cfg.bay_blind_lat_m and self._blind_s <= cfg.bay_blind_lat_s:
            return False
        self._guard_fail("blind", "lateral unmeasured over the blind budget", h._retry)
        return True

    def _guard_fail(self, key: str, text: str, redo: Callable[[str], None]) -> None:
        """정지 후 재진입(redo). 같은 사유로 두 번째면 일찍 실패(사람 호출) — 같은 일을 반복하지 않는다."""
        self._stop()
        self._seen[key] = self._seen.get(key, 0) + 1
        if self._seen[key] >= 2:
            self._h._fail("bay %s (twice)" % text)
        else:
            redo("bay " + text)

    def _contact_off_axis(self) -> bool:
        """접촉 때 마지막 추정이 허용창 밖이면 전압 20 s 를 기다리지 않고 바로 재진입. True = 맡았다."""
        cfg = self._h._cfg
        est = self._est
        if est is None or (abs(est[0]) <= cfg.bay_contact_lat_m and abs(est[1]) <= cfg.bay_contact_heading_rad):
            return False
        self._guard_fail("contact", "contact off the line axis (lat %.0f mm, head %.0f deg)"
                         % (est[0] * 1000.0, math.degrees(est[1])), self._h._reseat)
        return True
