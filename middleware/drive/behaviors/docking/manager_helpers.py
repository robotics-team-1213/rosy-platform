"""DNC-002~003: docking phase transitions, retry/backoff state machine, and charge settlement."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Optional

from core_common.protocol.schemas import DockState, NavigationState
from core_features.docking.model import DockPhase

if TYPE_CHECKING:
    from core_features.docking.charging import ChargingConfirmation


class DockingPhasesMixin:
    """Phase execution, retry/reseat backoff, and charge settlement for DockingManager."""

    _phase: Optional[DockPhase]
    _rear_phases: Any
    _bay_phases: Any
    _parking_phases: Any
    _nav_state: NavigationState
    _dock: Any
    _dock_type: Any
    _dock_type_for: Optional[str]
    _db: Any
    _cfg: Any
    _phase_since: float
    _last_seen_at: Optional[float]
    _detector_factory: Any
    _detector: Any
    _agent_factory: Any
    _agent: Any
    _battery: Any
    _state: DockState
    _retries: int
    _reseats: int
    _next_phase_after_backoff: Optional[DockPhase]
    _backoff_from: Optional[tuple]
    _error: Optional[str]
    _full_charge: Any
    _full_announced: bool
    _charging: Any
    _clock: Any
    executor: Any
    native: Any

    def _tick_docking(self, now: float) -> None:
        phase = self._phase
        if self._rear_phases.tick(phase, now) or self._bay_phases.tick(phase, now):
            return  # 후진형(D-950 후속)·칸형(D-1013)은 단계를 모두 맡는다
        if phase is DockPhase.STAGING:
            self._tick_staging(now)
        elif phase is DockPhase.ACQUIRING:
            self._tick_acquiring(now)
        elif phase is DockPhase.APPROACHING:
            self._tick_approaching(now)
        elif phase is DockPhase.SETTLING:
            self._tick_settling(now)
        elif phase is DockPhase.BACKOFF:
            self._tick_backoff(now)
        elif phase is DockPhase.TURNING:
            self._parking_phases.tick_turning(now)
        elif phase is DockPhase.ALIGNING:
            self._parking_phases.tick_aligning(now)

    # --- 단계 -----------------------------------------------------------------

    def _begin_staging(self) -> None:
        dock_type = self._type()
        if dock_type is not None and not dock_type.staging:
            self._parking_phases.begin_entry_turn()
            return
        self._enter(DockPhase.STAGING)
        self._nav_state = NavigationState.PLANNING
        if self.executor is not None and self._dock is not None:
            offset = self._type().staging_offset_m
            self.executor.navigate_to(
                self._rear_phases.staging_pose(self._dock, offset)
            )

    def _tick_staging(self, now: float) -> None:
        if self._nav_state is NavigationState.ARRIVED:
            self._begin_acquiring()
            return
        if self._nav_state in (NavigationState.FAILED, NavigationState.BLOCKED):
            self._retry("staging failed: " + self._nav_state.value)
            return
        if now - self._phase_since > self._cfg.staging_timeout_s:
            self._retry("staging timed out")

    def _begin_acquiring(self) -> None:
        self._enter(DockPhase.ACQUIRING)
        self._last_seen_at = None
        if self._detector_factory is not None and self._dock is not None:
            self._detector = self._detector_factory(self._dock, self._type())
            self._detector.start(self._dock)
        if self._parking():
            self._parking_phases.begin_acquiring()

    def _tick_acquiring(self, now: float) -> None:
        if self._parking():
            self._parking_phases.tick_acquiring(now)
            return
        if self._detector is not None and self._detector.relative_pose() is not None:
            self._enter(DockPhase.APPROACHING)
            self._last_seen_at = now
            # 도크는 맵에 장애물로 찍힌다. 면제가 없으면 로컬 코스트맵이
            # 도착하려는 대상을 벽으로 보고 접근을 거부한다.
            if self.executor is not None:
                self.executor.set_collision_exemption(True)
            return
        if now - self._phase_since > self._cfg.acquire_timeout_s:
            self._retry("dock not acquired")

    def _tick_approaching(self, now: float) -> None:
        if self._parking():
            self._parking_phases.tick_approaching(now)
            return
        observation = self._detector.relative_pose() if self._detector else None

        if observation is None:
            # 한 프레임 놓쳤다고 실패로 보지 않는다. 유예를 넘기면 재시도다.
            if (
                self._last_seen_at is None
                or now - self._last_seen_at > self._cfg.detector_lost_grace_s
            ):
                self._retry("dock lost during approach")
            return

        self._last_seen_at = now

        threshold = self._type().docking_threshold_m
        if observation.range_m <= threshold:
            self._begin_settling()
            return

        if now - self._phase_since > self._cfg.approach_timeout_s:
            self._retry("approach timed out")
            return

        if self.executor is not None:
            heading = math.atan2(observation.y, observation.x)
            angular = max(
                -self._cfg.max_angular,
                min(self._cfg.max_angular, self._cfg.approach_gain_yaw * heading),
            )
            self.executor.drive(self._cfg.approach_speed, angular)

    def _begin_settling(self) -> None:
        self._enter(DockPhase.SETTLING)
        if self.executor is not None:
            self.executor.stop()
            # 면제는 접근 구간 전용이다. 여기서 반드시 되돌린다.
            self.executor.set_collision_exemption(False)
        dock_type = self._type()
        if dock_type is not None and dock_type.settle == "pose":
            # 포즈 정착은 멈춘 뒤의 관측으로 판정한다. 검출기는 판정까지 켜 둔다.
            return
        self._stop_detector()
        if self._agent_factory is not None and self._dock is not None:
            self._agent = self._agent_factory(self._dock)

    def _tick_settling(self, now: float) -> None:
        dock_type = self._type()
        if dock_type is not None and dock_type.settle == "pose":
            self._parking_phases.tick_settling(now, dock_type)
            return
        status = self._agent.poll() if self._agent is not None else None
        if status is not None and status.answered and status.load_present:
            self._mark_docked()
            return
        if now - self._phase_since > self._cfg.settle_timeout_s:
            # D-351: 갈래를 가린다.
            if (
                status is not None
                and status.answered
                and status.load_present
                and not status.charging
            ):
                # 도달했는데 전류가 없다 — 산화·만충·보호보드 래치.
                self._fail("contact_no_current")
                return
            # 접점에 닿지 못했다. 재착좌로 충분하다.
            self._reseat("no contact after approach")

    def _tick_docked(self, now: float) -> None:
        """도크에 있는 동안 충전을 확인하고 배터리 정책에 알린다."""
        status = self._agent.poll() if self._agent is not None else None
        voltage = getattr(self._battery, "voltage", None) if self._battery else None
        confirmed, charging = self._bay_phases.docked_confirm(status, voltage, now)

        if self._battery is not None:
            self._battery.set_charging(
                confirmed and charging.source == "instrumented"
            )

        target = DockState.CHARGING if confirmed else DockState.DOCKED
        if target is not self._state:
            self._state = target
            self._emit(
                "docking.charging" if confirmed else "docking.charge_lost",
                "info",
                {
                    "dock_id": self._dock.id if self._dock else None,
                    "source": charging.source,
                },
            )

        # D-350: 만충 검출 — CHARGING→DOCKED 전이(전류 종단) 또는 전압 유지.
        self._check_full(charging)

    def _tick_undocking(self, now: float) -> None:
        if self.executor is None:
            self._fail("undock executor unavailable")
            return
        if self._phase is DockPhase.TURNING:
            self._parking_phases.tick_turning(now)
            return
        distance = self._type().undock_distance_m if self._dock else 0.35
        travelled = abs(self.executor.travelled_m())
        deadline = (
            2.0 * distance / self._cfg.undock_speed
            + self._cfg.undock_timeout_margin_s
        )
        if travelled < distance and now - self._phase_since > deadline:
            # 바퀴가 헛돌거나 무언가에 걸렸다. 무한히 후진하지 않는다.
            self._fail("undock timed out")
            return
        if travelled >= distance:
            self.executor.stop()
            # 주차형: 후진 뒤 차선 방향으로 돈다 (도크 yaw + undock_turn_rad).
            if self._parking_phases.begin_undock_turn():
                return
            self._finish_undock()
            return
        self.executor.drive(
            self._bay_phases.leave_sign() * self._cfg.undock_speed, 0.0
        )

    def _finish_undock(self) -> None:
        if self.executor is not None:
            self.executor.stop()
        self._state = DockState.UNDOCKED
        self._phase = None
        self._dock = None
        operation = self.native.current
        if operation is not None:
            self._native_mutate(
                self.native.update,
                operation.run_id,
                phase="TERMINAL",
                result="SUCCEEDED",
            )
        self._emit("docking.undocked", "info", {})

    def _tick_backoff(self, now: float) -> None:
        dock_type = self._type()
        if dock_type is not None and dock_type.backoff_m is not None:
            self._parking_phases.tick_backoff(now, dock_type.backoff_m)
            return
        if now - self._phase_since < self._cfg.backoff_s:
            if self.executor is not None:
                self.executor.drive(-self._cfg.undock_speed, 0.0)
            return
        if self.executor is not None:
            self.executor.stop()
        if self._next_phase_after_backoff is DockPhase.ACQUIRING:
            self._begin_acquiring()
        else:
            self._begin_staging()

    # --- 재시도와 실패 ---------------------------------------------------------

    def _retry(self, reason: str) -> None:
        """스테이징부터 다시. 도크에 도달하지 못한 실패에 쓴다."""
        limit = self._type().max_retries if self._dock else 0
        if self._retries >= limit:
            self._fail(reason)
            return
        self._retries += 1
        self._emit("docking.retry", "warning", {"reason": reason, "attempt": self._retries})
        self._begin_backoff(DockPhase.STAGING)

    def _reseat(self, reason: str) -> None:
        """접점만 다시 문다. 도착은 했으므로 스테이징까지 되돌아가지 않는다."""
        limit = self._type().max_retries if self._dock else 0
        if self._reseats >= limit:
            self._fail(reason)
            return
        self._reseats += 1
        self._emit("docking.reseat", "warning", {"reason": reason, "attempt": self._reseats})
        self._begin_backoff(DockPhase.ACQUIRING)

    def _begin_backoff(self, next_phase: DockPhase) -> None:
        self._next_phase_after_backoff = next_phase
        self._stop_detector()
        if self.executor is not None:
            self.executor.set_collision_exemption(False)
            self.executor.reset_odometry_mark()
        self._backoff_from = self._parking_phases.odometry()
        self._enter(DockPhase.BACKOFF)

    # --- 주차형 단계 ------------------------------------------------------------

    def _type(self):
        """The dock's type, cached when docking starts."""
        if self._dock is None:
            return None
        if self._dock_type is None or self._dock_type_for != self._dock.id:
            self._dock_type = self._db.type_of(self._dock.id)
            self._dock_type_for = self._dock.id
        return self._dock_type

    def _parking(self) -> bool:
        dock_type = self._type()
        return dock_type is not None and dock_type.approach == "pose"

    def _fail(self, reason: str, *, safety_stop: bool = False) -> None:
        """종착이다. 스스로 재시도하지 않는다."""
        self._state = DockState.DOCK_FAILED
        operation = self.native.current
        if operation is not None:
            self._native_mutate(
                self.native.update,
                operation.run_id,
                phase="TERMINAL",
                result="CANCELED" if safety_stop else "FAILED",
                reason="SAFETY_STOP" if safety_stop else "BACKEND_ERROR",
            )
        self._phase = None
        self._error = reason
        self._release()
        self._emit(
            "docking.failed",
            "error",
            {"reason": reason, "dock_id": self._dock.id if self._dock else None},
        )

    # --- 공통 -----------------------------------------------------------------

    def _mark_docked(self) -> None:
        self._state = DockState.DOCKED
        operation = self.native.current
        if operation is not None:
            self._native_mutate(
                self.native.update,
                operation.run_id,
                phase="TERMINAL",
                result="SUCCEEDED",
            )
        self._phase = None
        self._full_announced = False
        self._emit("docking.docked", "info", {"dock_id": self._dock.id})

    def _check_full(self, charging: "ChargingConfirmation") -> None:
        """D-350: DOCKED 상태에서 만충을 감지하면 `docking.full` 이벤트를 1회 낸다."""
        if self._state is not DockState.DOCKED:
            return
        voltage = charging.peak_v
        full = self._full_charge.check(voltage, docked=True)
        self._full_announced = self._full_charge.announced

        if full:
            self._phase = DockPhase.CHARGED_HOLD
            self._emit(
                "docking.full",
                "info",
                {
                    "dock_id": self._dock.id,
                    "source": charging.source,
                    "voltage_v": round(voltage, 2) if voltage is not None else None,
                },
            )

    def _enter(self, phase: DockPhase) -> None:
        self._execution("phase", phase)
        self._phase = phase
        self._phase_since = self._clock()

    def _release(self) -> None:
        self._stop_detector()
        if self.executor is not None:
            self.executor.stop()
            self.executor.set_collision_exemption(False)
            self.executor.cancel_navigation()
        self._charging.reset()
        if self._battery is not None:
            self._battery.set_charging(False)

    def _stop_detector(self) -> None:
        if self._detector is not None:
            self._detector.stop()


__all__ = ["DockingPhasesMixin"]
