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


def forward_twist(cfg: Any, lateral: float, heading: float) -> float:
    """Forward (reseat) angular rate: the mirror of reverse_twist. Driving forward a ccw heading moves the body toward +y = -lateral, so a positive lateral
    wants a positive (ccw) target heading; the target is capped like the reverse one."""
    cap = cfg.bay_target_heading_max_rad
    target = max(-cap, min(cap, cfg.bay_gain_lateral / cfg.bay_gain_heading * lateral))
    return max(-cfg.max_angular, min(cfg.max_angular, -cfg.bay_gain_heading * (heading - target)))


def entry_ok(cfg: Any, lateral: float, heading: float) -> bool:
    """ALIGNING 에 들어가도 되는 오차인가(평평한 창). 횡 7 cm·방위 15° 안은 시뮬에서 접촉 0, 밖은 후진하지 않고
    스테이징부터 다시 한다. 맵 횡(통로선만 보일 때)은 수 cm 오차라 창을 4 cm 로 좁히면 맵 오차에 좌우된다."""
    return abs(lateral) <= cfg.bay_entry_lat_m and abs(heading) <= cfg.bay_entry_heading_max_rad


def rear_band_gap(points, rear_x: float, half_m: float = 0.03) -> Optional[float]:
    """뒤 정면 좁은 띠(|y| ≤ half_m)에서 짐칸 끝(rear_x, 음수)부터 가장 가까운 점까지. 띠 안 점이 없으면 None(막지
    않음). 옆 칸 몸통은 띠 밖이라 0.0 으로 오지 않는다(몸통 폭 띠의 translation_gap 은 이웃이 0.0 을 만든다)."""
    gaps = [rear_x - x for x, y in points if abs(y) <= half_m and rear_x - x > 0.0]
    return min(gaps) if gaps else None


def rear_blocked(cfg: Any, rear_gap: Optional[float], along: Optional[float]) -> bool:
    """LiDAR 뒤 여유(짐칸 끝~첫 점)가 카메라로 잰 멈춤면까지 남은 거리(along - 짐칸 돌출)보다 확실히 작으면 칸
    안에 뭔가 있다. 멈춤면 자체가 보여도 gap≈남은 거리라 막지 않는다. 여유 = 몸 스캔 지연 0.5 s×0.05 m/s 2.5 cm +
    LiDAR·카메라 오차 각 1~2 cm. 값이 없으면(띠 안 점 없음 포함) 판단하지 않는다(기존 동작)."""
    if rear_gap is None or along is None:
        return False
    return rear_gap < max(0.0, along - cfg.bay_turn_rear_overhang_m) - cfg.bay_rear_gap_margin_m


def heading_gate(cfg: Any, omega: float, age_s: float) -> float:
    """프레임당 방위 점프 게이트 + 관측 나이 동안 돈 양. 나이 든 정상 프레임이 회전 중 게이트에 걸리지 않게."""
    return cfg.bay_gate_jump_rad + abs(omega) * min(max(0.0, age_s), cfg.bay_obs_max_age_s)


class BayGuardsMixin:
    """`BayPhases` 의 맹목 예산과 같은 사유 반복 기억. 상태는 여기, 락은 매니저의 것."""

    def _init_guards(self) -> None:
        self._blind_s = 0.0           # 횡을 못 잰 채(통로선만) 후진한 시간
        self._blind_m = 0.0           # 그 거리 — 추정값(맵·명령 적분)으로 리셋하지 않는다
        self._blind_budget_m = 0.0    # 이번 진입의 예산(진입 along 에서 정해진다)
        self._along_m: Optional[float] = None   # 이번 관측의 along(실측일 때만)
        self._obs_age = 0.0
        self._omega = 0.0             # 마지막 명령 각속도
        self._seen: dict[str, int] = {}         # 사유별 가드 실패 횟수(첫 시도에서만 비운다)
        self._gap_hist: list = []     # ALIGNING: (scan stamp, LiDAR rear-band gap) — is the body really going back?
        self._ref_points: Optional[tuple] = None      # (dock id, the stored seated scan's body-filtered points)
        self._seat_gap: Optional[tuple] = None  # (dock id, rear-band gap of the stored seated reference scan)
        self._seat_gap_asked: Optional[str] = None
        self._bo_gap0: Optional[float] = None   # back-off: the LiDAR rear gap when it began

    def _backoff_stuck(self, now: float, travelled: float) -> bool:
        """Back-off: the wheels have travelled but the LiDAR rear gap did not grow with them: the body is held or pivoting."""
        cfg, body = self._h._cfg, self._body_fresh(now)
        gap = body[2] if body is not None else None
        if self._bo_gap0 is None:
            if gap is not None and travelled < 0.01:
                self._bo_gap0 = gap
            elif travelled >= cfg.bay_backoff_check_m and self._has_reference():
                # a dock with a reference scan backs out only with the LiDAR watching: no start gap by 2 cm of travel = stop
                self._stop()
                self._h._fail("bay back-off: no LiDAR rear gap at its start (wheels %.2f m): not driving out blind" % travelled)
                return True
            return False
        if gap is None or travelled < cfg.bay_backoff_check_m:
            return False
        grew = gap - self._bo_gap0
        if (cfg.bay_backoff_moving_ratio * travelled - cfg.bay_backoff_lower_slack_m <= grew
                <= cfg.bay_backoff_growth_max_ratio * travelled + cfg.bay_backoff_growth_slack_m):
            return False
        self._stop()
        self._h._fail("bay back-off: the body is not following the wheels (wheels %.2f m, LiDAR rear gap %+.2f m): held or turning in the rails"
                      % (travelled, grew))
        return True

    def _has_reference(self) -> bool:
        dock = self._h._dock
        return dock is not None and isinstance(getattr(dock, "metadata", {}).get("reference_scan"), dict)

    def seat_gap_request(self) -> Optional[tuple]:
        """CORE 가 LiDAR 콜백에서 묻는다(락 없음): 이 칸의 기준 스캔이 있고 뒤 여유를 아직 안 쟀으면 (칸 id, 스캔), 한 번."""
        dock = self._h._dock
        ref = getattr(dock, "metadata", {}).get("reference_scan") if dock is not None else None
        if not isinstance(ref, dict) or self._seat_gap_asked == dock.id:
            return None
        self._seat_gap_asked = dock.id
        return dock.id, ref

    def _ref_key(self):
        """Identity of the dock's CURRENT reference scan (a re-teach with a new reference_scan changes it)."""
        dock = self._h._dock
        ref = getattr(dock, "metadata", {}).get("reference_scan") if dock is not None else None
        if not isinstance(ref, dict):
            return None
        r = ref.get("ranges") or []
        return (dock.id, len(r), hash(tuple(round(float(v), 3) for v in list(r)[:60])), ref.get("source_stamp_ns"))

    def note_seat_gap(self, dock_id: str, gap: Optional[float], points=None) -> None:
        self._seat_key = self._ref_key()
        self._seat_gap = (dock_id, float(gap)) if gap is not None else None
        if points is not None:
            self._ref_points = (dock_id, [(float(p[0]), float(p[1])) for p in points])     # the stored scan's filtered points: the empty-bay depth model

    def _note_rear_gap(self, now: float) -> None:
        body = self._body_fresh(now)
        if body is not None and body[2] is not None and (not self._gap_hist or self._gap_hist[-1][0] != body[3]):
            self._gap_hist = [s for s in self._gap_hist if body[3] - s[0] <= 2.5] + [(body[3], float(body[2]))]

    def _lidar_moving(self, now: float) -> bool:
        """The LiDAR rear gap shrank by bay_gap_moving_m over the last 0.2-0.35 s AND the newest scan is fresh: the body is
        going back whatever the line's shape or the wheel odometry say. Cutting the scan feed ends this at once."""
        cfg, hist = self._h._cfg, self._gap_hist
        if not hist or now - hist[-1][0] > cfg.bay_scan_fresh_s:
            return False
        old = next((s for s in hist if hist[-1][0] - s[0] <= 0.35), None)
        return old is not None and hist[-1][0] - old[0] >= 0.2 and old[1] - hist[-1][1] >= cfg.bay_gap_moving_m

    def _lidar_stalled(self, now: float) -> bool:
        """In the rails (LiDAR steering): the rear gap changed by less than bay_lidar_stall_m over the last bay_lidar_stall_s while the robot
        reverses and the scan is fresh: the body is held (wheels turning). The slip rule is off there, this is its LiDAR form."""
        cfg, hist = self._h._cfg, self._gap_hist
        if not hist or now - hist[-1][0] > cfg.bay_scan_fresh_s:
            return False
        old = [s for s in hist if hist[-1][0] - s[0] <= cfg.bay_lidar_stall_s + 0.5]
        if not old or hist[-1][0] - old[0][0] < cfg.bay_lidar_stall_s:
            return False
        return abs(old[0][1] - hist[-1][1]) < cfg.bay_lidar_stall_m

    def _lidar_seated(self, now: float) -> bool:
        """A fresh rear gap at or inside the stored seated reference's: the reverse is at the stop face."""
        body, seat = self._body_fresh(now), self._seat_gap
        dock = self._h._dock
        return (body is not None and body[2] is not None and seat is not None and dock is not None
                and seat[0] == dock.id and body[2] <= seat[1] + self._h._cfg.bay_seat_gap_tol_m)

    def _blind_lateral(self, dt: float, speed: float) -> bool:
        """횡 맹목 예산: 실측 횡이 없는 프레임으로만 후진한 거리·시간. 예산 = (진입 along - 칸 선이 보이는 거리) + 여유로,
        정상 진입(along 0.41)의 맹목 0.105 m 는 통과하고 그보다 길면 정지하고 재진입(시간은 같은 비율). 실측 횡 프레임이 오면 비운다. 프레임이 없을 땐 세지
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
        if self._blind_m <= self._blind_budget_m and self._blind_s <= self._blind_budget_m / cfg.bay_reverse_speed:
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
