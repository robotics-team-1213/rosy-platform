"""core_features.docking.rear_phases — 후진 충전소(`approach="rear"`, D-950 후속)의 단계.

순서: Nav2 스테이징(뒤가 도크 쪽) → V 표지 관측(ACQUIRING) → 레일 입구 밖 후진 정렬
(ALIGNING) → 레일 안 곧은 후진(REVERSING, 각속도 0, 관측 없음) → 멈춤면 접촉(진행 멈춤)
→ 전압 상승으로 충전 확인(SETTLING) → DOCKED. 실패는 레일 밖으로 전진(BACKOFF) 뒤
스테이징부터, `max_retries` 뒤 DOCK_FAILED(매니저의 `_retry`).

레일 안에서 조향하지 않는 이유: 두 바퀴 로봇의 바퀴 옆면은 축 바로 옆에서 레일에 닿아
마찰이 로봇을 벽 쪽으로 돌린다. 조향은 그 벽과 다퉈 끼인다(연구
`dock_sim.py`, D-972: 조향 12 ~ 27/47, 곧게 44 ~ 45/47).

락은 매니저의 것이다: 모든 진입점은 매니저의 락 안, 틱·명령 경로에서만 불린다. 이
단계만의 상태(진행 기록·전압 기준·전압 확인)는 여기 둔다 — 매니저 크기 래칫(D-766).
ROS 무의존.

관측(`DockObservation`, base_link): x, y = 멈춤면 가운데, yaw = 도크 안쪽 축 방향.
뒤가 도크를 똑바로 볼 때 yaw = pi 다.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from core_features.docking.charging import ChargingConfirmation
from core_features.docking.database import Pose2D
from core_features.docking.model import DockPhase


def _wrap(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def rear_errors(observation) -> tuple[float, float, float]:
    """(도크 축 방향으로 멈춤면까지 남은 거리, 축에서 로봇의 횡 오차, 후진 방향과 축의 각 오차)."""
    ax, ay = math.cos(observation.yaw), math.sin(observation.yaw)
    along = observation.x * ax + observation.y * ay
    lateral = ay * observation.x - ax * observation.y
    heading = _wrap(math.pi - observation.yaw)
    return along, lateral, heading


class RearPhases:
    def __init__(self, host: Any) -> None:
        self._h = host
        self._progress: Optional[tuple] = None     # (travelled_m, at)
        self._baseline_v: Optional[float] = None
        # 전압 1소스(D-350 Phase 1) — D-27 억제 입력이 아니다. `update(now=…)` 로 매니저 시계를 쓴다.
        self._charging = ChargingConfirmation(window_s=host._cfg.charge_confirm_s, instrumented=False)

    # --- 매니저가 부르는 자리 ---------------------------------------------------

    def active(self) -> bool:
        dock_type = self._h._type()
        return dock_type is not None and dock_type.approach == "rear"

    def staging_pose(self, dock, offset_m: float) -> Pose2D:
        """스테이징 자리는 같고, 후진형은 뒤가 도크를 본다."""
        pose = dock.staging_pose(offset_m)
        if not self.active():
            return pose
        return Pose2D(x=pose.x, y=pose.y, yaw=_wrap(pose.yaw + math.pi))

    def leave_sign(self) -> float:
        """언도킹 방향: 도크가 로봇 뒤에 있으면 앞으로 떠난다."""
        return 1.0 if self.active() else -1.0

    def tick(self, phase, now: float) -> bool:
        """후진형이면 이 단계를 맡고 True."""
        if not self.active():
            return False
        if phase is DockPhase.STAGING:
            self._h._tick_staging(now)
        elif phase is DockPhase.ACQUIRING:
            self._tick_acquiring(now)
        elif phase is DockPhase.ALIGNING:
            self._tick_aligning(now)
        elif phase is DockPhase.REVERSING:
            self._tick_reversing(now)
        elif phase is DockPhase.SETTLING:
            self._tick_settling(now)
        elif phase is DockPhase.BACKOFF:
            self._tick_backoff(now)
        return True

    # --- 단계 -----------------------------------------------------------------

    def _drive(self, linear: float, angular: float) -> None:
        if self._h.executor is not None:
            self._h.executor.drive(linear, angular)

    def _stop(self) -> None:
        if self._h.executor is not None:
            self._h.executor.stop()

    def _tick_acquiring(self, now: float) -> None:
        h = self._h
        if h._detector is not None and h._detector.relative_pose() is not None:
            h._enter(DockPhase.ALIGNING)
            h._last_seen_at = now
            if h.executor is not None:
                # 도크는 맵에 장애물로 찍힌다 — 면제가 없으면 코스트맵이 접근을 막는다.
                h.executor.set_collision_exemption(True)
            return
        if now - h._phase_since > h._cfg.acquire_timeout_s:
            h._retry("dock not acquired")

    def _tick_aligning(self, now: float) -> None:
        """레일 입구 밖에서만 V 표지를 보고 조향한다."""
        h, cfg, dock_type = self._h, self._h._cfg, self._h._type()
        observation = h._detector.relative_pose() if h._detector is not None else None
        if observation is None:
            if h._last_seen_at is None or now - h._last_seen_at > cfg.detector_lost_grace_s:
                self._stop()
                h._retry("dock lost during rear alignment")
            return
        h._last_seen_at = now
        along, lateral, heading = rear_errors(observation)
        if along <= dock_type.rail_entry_m:
            if (abs(lateral) <= dock_type.rear_align_tolerance_m
                    and abs(heading) <= dock_type.rear_align_tolerance_rad):
                self._begin_reversing(now)
            else:
                self._stop()
                h._retry("misaligned at the rail entry")
            return
        travel = max(0.0, dock_type.staging_offset_m - dock_type.rail_entry_m)
        if now - h._phase_since > 2.0 * travel / cfg.rear_align_speed + cfg.undock_timeout_margin_s:
            self._stop()
            h._retry("rear alignment timed out")
            return
        # 후진하면 횡 오차는 sin(heading) 로 변한다: 목표 방위를 오차를 줄이는 쪽으로 기울인다.
        target = max(-cfg.rear_align_max_heading,
                     min(cfg.rear_align_max_heading, -cfg.rear_align_gain_lateral * lateral))
        angular = max(-cfg.max_angular,
                      min(cfg.max_angular, cfg.rear_align_gain_yaw * (target - heading)))
        self._drive(-cfg.rear_align_speed, angular)

    def _begin_reversing(self, now: float) -> None:
        h = self._h
        h._stop_detector()
        if h.executor is not None:
            h.executor.reset_odometry_mark()
        self._progress = (0.0, now)
        h._enter(DockPhase.REVERSING)

    def _tick_reversing(self, now: float) -> None:
        """레일 안: 각속도 0, 진행이 멈추면 멈춤면 접촉."""
        h, cfg = self._h, self._h._cfg
        if h.executor is None:
            h._fail("rear executor unavailable")
            return
        travelled = abs(h.executor.travelled_m())
        last, since = self._progress or (0.0, h._phase_since)
        if travelled - last >= cfg.contact_progress_m:
            self._progress = (travelled, now)
        elif now - since >= cfg.contact_stall_s:
            self._stop()
            h.executor.set_collision_exemption(False)
            self._charging.reset()
            self._baseline_v = None
            h._enter(DockPhase.SETTLING)
            return
        if now - h._phase_since > 2.0 * h._type().rail_entry_m / cfg.rear_speed \
                + cfg.undock_timeout_margin_s:
            self._stop()
            h._retry("no contact inside the rails")
            return
        self._drive(-cfg.rear_speed, 0.0)

    def _tick_settling(self, now: float) -> None:
        """전압 1소스 + 멈춘 뒤 기준에서의 상승. 도크 에이전트가 없다."""
        h, cfg = self._h, self._h._cfg
        voltage = getattr(h._battery, "voltage", None) if h._battery is not None else None
        valid = voltage is not None and math.isfinite(float(voltage))
        if self._baseline_v is None and valid and now - h._phase_since >= cfg.settle_still_s:
            # 멈춘 직후 부하가 빠져 오르는 전압을 충전으로 읽지 않도록 잠시 뒤 기준을 잡는다.
            self._baseline_v = float(voltage)
        confirmed = self._charging.update(None, voltage, now=now)
        peak = self._charging.peak_v
        if (confirmed and self._baseline_v is not None and peak is not None
                and peak - self._baseline_v >= cfg.rear_charge_rise_v):
            h._mark_docked()
            return
        if now - h._phase_since > cfg.settle_timeout_s:
            h._retry("no charge after contact")

    def _tick_backoff(self, now: float) -> None:
        """재시도: 레일 밖으로 곧게 전진한 뒤 스테이징부터."""
        h, cfg = self._h, self._h._cfg
        travelled = abs(h.executor.travelled_m()) if h.executor is not None else 0.0
        if travelled < cfg.rear_backoff_m:
            if now - h._phase_since > cfg.backoff_timeout_s:
                self._stop()
                h._fail("rear backoff blocked")
                return
            self._drive(cfg.undock_speed, 0.0)
            return
        self._stop()
        h._begin_staging()
