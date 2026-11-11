"""core_features.docking.bay_phases — 충전 칸 분홍 유도선 접안(`approach="line"`, D-1013).
순서: Nav2 스테이징(교차점, 도크를 정면으로 본다) → TURNING 제자리 180°(오도메트리 상대,
뒤가 칸으로) → ACQUIRING(선 관측 획득 + 캐스터 정착 크립 + 두 번 일치) → ALIGNING(선
가운데·평행 유지하며 후진, 코스트·스캔·점프 게이트, 접촉 3중 판정) → SETTLING(전압 1소스,
D-941 숫자) → DOCKED. 실패는 전진 백오프 뒤 스테이징부터, `max_retries` 뒤 DOCK_FAILED.

선 관측은 선을 가상 도크로 본다(`DockObservation`): x·y = 칸 중심선 멈춤면 가운데의
base_link 상대 위치, yaw = 칸 안쪽 축. `rear_errors` 와 같은 분해(along·lateral·heading)를
쓴다. 소스는 CAMERA_LINE(`bay_line_observer_node`, 다음 단계)이 `dock/observation` 에 싣는다.

끊김은 예측(오도메트리)이 메운다: 프레임은 게이트를 통과할 때만 증거다(점프 게이트 ±2 cm·
5 deg), 무효 프레임은 코스트 예산(0.5–1 s) 안 제어량 유지, 넘으면 정지 후 ±5° 스캔(게이트
우회 재동기화), 실패는 전진 백오프 재시도. 접촉은 진행 멈춤 + 거리 상한 + 진행 발산(오도메트리는
가는데 선 모양이 그대로면 슬립·정지) 3중으로 본다 — 마지막 구간은 발산 검출이 포화해 거리
상한이 유일한 방어다(bay_pit_sim 발견). 캐스터는 180° 회전 뒤 뒤집혀 몸을 비튼다(2026-11-03
조사) — ACQUIRING 의 정착 크립(전진)이 몸통 축으로 정렬해 없앤다(킥 6° 에 0.8 mm → 0.1 mm).

락은 매니저의 것이고 이 단계만의 상태는 여기 둔다(매니저 크기 래칫, D-766). ROS 무의존.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from core_common.protocol.schemas import NavigationState
from core_features.docking.charging import ChargingConfirmation
from core_features.docking.model import DockPhase
from core_features.docking.parking import ParkingGains, turn_twist
from core_features.docking.rear_phases import rear_errors

_TURN_GAINS = ParkingGains()


class BayPhases:
    """The pink guide-line charge bay, under the manager's lock (D-1013)."""

    def __init__(self, host: Any) -> None:
        self._h = host
        # 전압 1소스(D-941 숫자: 20 s 창) — D-27 억제 입력이 아니다.
        self._charging = ChargingConfirmation(clock=host._clock,
                                              window_s=host._cfg.bay_charge_confirm_s,
                                              instrumented=False)
        self._est: Optional[tuple[float, float]] = None   # (횡, 방위) 추정 — 예측이 메운다
        self._no_obs_s = 0.0
        self._scan_s: Optional[float] = None
        self._resync = False
        self._turn_target: Optional[float] = None
        self._creep_from: Optional[float] = None          # 정착 크립 시작 travelled
        self._crept = False
        self._match: Optional[tuple[float, float]] = None  # 크립 전 관측(두 번 일치용)
        self._travel_cap_m: Optional[float] = None        # 거리 상한 = 진입 잔여 + 여유
        self._progress: Optional[tuple[float, float]] = None
        self._slip: Optional[tuple[float, float]] = None   # (travelled, along) 창 시작
        self._backoff = False
        self._last_tick: Optional[float] = None
        self._baseline_v: Optional[float] = None

    # --- 매니저가 부르는 자리 ---------------------------------------------------

    def active(self) -> bool:
        dock_type = self._h._type()
        return dock_type is not None and dock_type.approach == "line"

    def docked_confirm(self, status, voltage, now):
        """DOCKED 유지 중 충전 확인: 칸은 여기 전압 1소스, 나머지는 후진형 규칙에 위임."""
        if status is not None:
            return self._h._charging.update(status, voltage, now=now), self._h._charging
        if self.active():
            return self._charging.update(None, voltage, now=now), self._charging
        return self._h._rear_phases.docked_confirm(status, voltage, now)

    def leave_sign(self) -> float:
        """칸 언도킹은 전진(도크가 뒤에 있다). 나머지는 후진형 규칙에 위임."""
        return 1.0 if self.active() else self._h._rear_phases.leave_sign()

    def tick(self, phase, now: float) -> bool:
        """칸형이면 이 단계를 맡고 True."""
        if not self.active():
            return False
        if phase is DockPhase.STAGING:
            self._tick_staging(now)
        elif phase is DockPhase.TURNING:
            self._tick_turning(now)
        elif phase is DockPhase.ACQUIRING:
            self._tick_acquiring(now)
        elif phase is DockPhase.ALIGNING:
            self._tick_aligning(now)
        elif phase is DockPhase.SETTLING:
            self._tick_settling(now)
        elif phase is DockPhase.BACKOFF:
            self._tick_backoff(now)
        self._last_tick = now
        return True

    # --- 단계 -----------------------------------------------------------------

    def _drive(self, linear: float, angular: float) -> None:
        if self._h.executor is not None:
            self._h.executor.drive(linear, angular)

    def _stop(self) -> None:
        if self._h.executor is not None:
            self._h.executor.stop()

    def _observation(self):
        return self._h._detector.relative_pose() if self._h._detector is not None else None

    def _tick_staging(self, now: float) -> None:
        """스테이징(교차점) 도착 → 선반 180° 회전부터. Nav2 실패는 후진형과 같은 재시도."""
        h = self._h
        if h._nav_state is not NavigationState.ARRIVED:
            h._tick_staging(now)
            return
        pose = self._odometry()
        if pose is None:
            h._fail("bay odometry unavailable")
            return
        self._stop()
        self._reset_line_state()
        self._turn_target = pose[2] + math.pi
        h._enter(DockPhase.TURNING)

    def _tick_turning(self, now: float) -> None:
        h = self._h
        pose = self._odometry()
        if pose is None:
            h._fail("bay odometry unavailable")
            return
        error = _wrap(self._turn_target - pose[2])
        angular, done = turn_twist(error, _TURN_GAINS)
        if done:
            self._stop()
            h._begin_acquiring()      # 검출기 시작 + ACQUIRING (매니저 규칙 그대로)
            return
        if now - h._phase_since > h._cfg.turn_timeout_s:
            self._stop()
            h._retry("bay turn timed out")
            return
        self._drive(0.0, angular)

    def _tick_acquiring(self, now: float) -> None:
        """선 포획 + 캐스터 정착 크립 + 두 번 일치. 크립 없이는 후진 첫 cm 에 킥이 온다."""
        h, cfg = self._h, self._h._cfg
        along, lateral, heading = self._line_errors()
        if self._crept:
            if (along, lateral, heading) == (None, None, None):
                if h._last_seen_at is None or now - h._last_seen_at > cfg.detector_lost_grace_s:
                    self._stop()
                    h._retry("bay line lost after the settle creep")
                return
            if self._match is not None and (
                    abs(lateral - self._match[0]) > cfg.bay_gate_jump_m
                    or abs(heading - self._match[1]) > cfg.bay_gate_jump_rad):
                self._stop()
                h._retry("bay line observation jumped after the creep")
                return
            self._est = (lateral, heading)
            self._no_obs_s = 0.0
            if h.executor is not None:
                h.executor.reset_odometry_mark()
                h.executor.set_collision_exemption(True)
            self._travel_cap_m = along + cfg.bay_travel_margin_m
            self._progress = None
            self._slip = None
            h._enter(DockPhase.ALIGNING)
            return
        if (along, lateral, heading) == (None, None, None):
            if now - h._phase_since > cfg.acquire_timeout_s:
                h._retry("bay line not acquired")
            return
        # 첫 포획: 정착 크립 — 전진해 캐스터를 몸통 축으로 정렬하고 다시 본다.
        self._match = (lateral, heading)
        if h.executor is None:
            h._fail("bay executor unavailable")
            return
        if self._creep_from is None:
            h.executor.reset_odometry_mark()
            self._creep_from = 0.0
        if abs(h.executor.travelled_m()) < cfg.bay_settle_creep_m:
            self._drive(h._cfg.undock_speed, 0.0)
            return
        self._stop()
        self._crept = True
        h._last_seen_at = now

    def _tick_aligning(self, now: float) -> None:
        """선 가운데·평행 유지하며 후진. 관측은 게이트를 통과할 때만 증거다."""
        h, cfg = self._h, self._h._cfg
        if h.executor is None:
            h._fail("bay executor unavailable")
            return
        dt = now - self._last_tick if self._last_tick is not None else 0.0
        self._ingest_observation(dt)
        speed = cfg.bay_reverse_speed
        if self._scan_s is not None:
            # 스캔은 정지 상태에서 천천히 ±bay_scan_rad — 회전 중 병진이 흐르면 눈감고 접촉한다.
            # 주기: +폭 0.25 s → 정지 → −2×폭 0.25 s → 정지(대칭 복귀), 2.5 s 주기.
            self._scan_s += dt
            self._stop()
            phase_t = self._scan_s % 2.5
            rate = cfg.bay_scan_rad / 0.25
            if phase_t < 0.25:
                self._drive(0.0, rate)
            elif 1.25 <= phase_t < 1.5:
                self._drive(0.0, -2.0 * rate)
            if self._est is not None and self._no_obs_s == 0.0:
                self._scan_s = None
            elif self._scan_s > cfg.bay_scan_s:
                self._scan_s = None
                h._retry("bay line lost during alignment")
            return
        if self._no_obs_s > cfg.bay_coast_stop_s:
            self._scan_s = 0.0
            self._resync = True
            return
        if cfg.bay_coast_slow_s < self._no_obs_s:
            speed = 0.02
        lateral, heading = self._est
        angular = max(-cfg.max_angular, min(cfg.max_angular,
                                            -(cfg.bay_gain_lateral * lateral
                                              + cfg.bay_gain_heading * heading)))
        self._drive(-speed, angular)
        # 추정은 오도메트리 명령으로 전파(프레임 사이를 메운다)
        self._est = (lateral + speed * math.sin(heading) * dt,
                     _wrap(heading + angular * dt))
        travelled = abs(h.executor.travelled_m())
        if self._contact(travelled, now):
            return
        if self._travel_cap_m is not None and travelled > self._travel_cap_m + 0.10:
            self._stop()
            h._retry("bay alignment overran the travel cap")
            return

    def _ingest_observation(self, dt: float) -> None:
        """게이트가 증거를 판다: 점프는 이웃 칸 선이나 잡음, 통과만 관측이다."""
        h, cfg = self._h, self._h._cfg
        along, lateral, heading = self._line_errors()
        if (along, lateral, heading) != (None, None, None):
            if (not self._resync and self._est is not None and (
                    abs(lateral - self._est[0]) > cfg.bay_gate_jump_m
                    or abs(heading - self._est[1]) > cfg.bay_gate_jump_rad)):
                self._no_obs_s += dt          # 물리적으로 불가능한 점프: 무관측
            else:
                self._est, self._no_obs_s, self._resync = (lateral, heading), 0.0, False
                h._last_seen_at = h.now()
                if self._slip is not None and self._h.executor is not None:
                    t0, along0 = self._slip
                    travelled = abs(self._h.executor.travelled_m())
                    # 창은 선 모양이 움직일 때만 재앵커 — 정지한 그림에서 오도메트리가
                    # 3 cm 넘게 쌓이면 슬립·정지다(시뮬의 고정 가장자리 회귀와 같은 근거).
                    if abs(along0 - along) >= 0.01:
                        self._slip = (travelled, along)
                    elif travelled - t0 > 0.03:
                        self._slip = ("contact", 0.0)
                        return
                elif self._h.executor is not None:
                    self._slip = (abs(self._h.executor.travelled_m()), along)
        else:
            self._no_obs_s += dt

    def _contact(self, travelled: float, now: float) -> bool:
        """접촉 3중 판정: 진행 멈춤 · 슬립 발산 · 거리 상한."""
        h, cfg = self._h, self._h._cfg
        if self._slip is not None and self._slip[0] == "contact":
            self._begin_settling()
            return True
        last, since = self._progress or (travelled, now)
        if travelled - last >= cfg.contact_progress_m:
            self._progress = (travelled, now)
        elif now - since >= cfg.contact_stall_s:
            self._begin_settling()
            return True
        if self._travel_cap_m is not None and travelled >= self._travel_cap_m:
            self._begin_settling()
            return True
        return False

    def _begin_settling(self) -> None:
        h = self._h
        self._stop()
        if h.executor is not None:
            h.executor.set_collision_exemption(False)
        self._charging.reset()
        self._baseline_v = None
        h._enter(DockPhase.SETTLING)

    def _tick_settling(self, now: float) -> None:
        """전압 1소스(D-941): 멈춘 뒤 2 s 기준, 20 s 안 +0.05 V 상승."""
        h, cfg = self._h, self._h._cfg
        voltage = getattr(h._battery, "voltage", None) if h._battery is not None else None
        valid = voltage is not None and math.isfinite(float(voltage))
        if self._baseline_v is None and valid and now - h._phase_since >= cfg.bay_settle_baseline_s:
            self._baseline_v = float(voltage)
        confirmed = self._charging.update(None, voltage, now=now)
        peak = self._charging.peak_v
        if (confirmed and self._baseline_v is not None and peak is not None
                and peak - self._baseline_v >= cfg.bay_charge_rise_v):
            h._mark_docked()
            return
        if now - h._phase_since > cfg.settle_timeout_s + cfg.bay_charge_confirm_s:
            h._retry("no charge after bay contact")

    def _tick_backoff(self, now: float) -> None:
        """재시도: 교차점 쪽으로 전진한 뒤 스테이징부터."""
        h, cfg = self._h, self._h._cfg
        if h.executor is None:
            h._fail("bay executor unavailable")
            return
        if not self._backoff:
            h.executor.reset_odometry_mark()
            self._backoff = True
        if abs(h.executor.travelled_m()) < cfg.bay_backoff_m:
            if now - h._phase_since > cfg.backoff_timeout_s:
                self._stop()
                h._fail("bay backoff blocked")
                return
            self._drive(cfg.undock_speed, 0.0)
            return
        self._stop()
        self._reset_line_state()
        h._begin_staging()

    # --- 보조 -----------------------------------------------------------------

    def _reset_line_state(self) -> None:
        self._est = None
        self._no_obs_s = 0.0
        self._scan_s = None
        self._resync = False
        self._creep_from = None
        self._crept = False
        self._match = None
        self._travel_cap_m = None
        self._progress = None
        self._slip = None
        self._backoff = False
        self._turn_target = None

    def _odometry(self):
        pose = getattr(self._h.executor, "odometry_pose", None) if self._h.executor else None
        return pose() if callable(pose) else None

    def _line_errors(self):
        observation = self._observation()
        if observation is None:
            return None, None, None
        return rear_errors(observation)


def _wrap(angle: float) -> float:
    while angle > math.pi:
        angle -= 2.0 * math.pi
    while angle < -math.pi:
        angle += 2.0 * math.pi
    return angle
