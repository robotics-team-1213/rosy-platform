"""DNC-002~003: sensor-closed docking, without ROS or an assumed precision.
Docking owns DOCKING mode through Nav2 staging and local approach; NAVIGATION
cannot preempt it. ParkingPhases uses this owner's state/lock for pose parking.
Clock injection supports deterministic tests. Contracts/config live in model;
designs: 2026-09-02-docking-station and 2026-09-23-lane-network-parking.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional
from uuid import UUID

from core_common.protocol.native_receipts import NativeReceipts
from core_common.protocol.schemas import (
    BatteryLevel,
    DockingStatus,
    DockState,
    NavigationState,
)
from core_features.docking.admission import dock_target, undock_ready
from core_features.docking.bay_phases import BayPhases
from core_features.docking.charging import ChargingConfirmation
from core_features.docking.database import DockDatabase, DockError, DockInstance
from core_features.docking.detector import DockDetector
from core_features.docking.manager_helpers import DockingPhasesMixin
from core_features.docking.model import DockingConfig, DockingExecutor, DockPhase
from core_features.docking.native_status import owner_snapshot, readback
from core_features.docking.parking import DockPoseTracker
from core_features.docking.parking_phases import ParkingPhases
from core_features.docking.rear_phases import RearPhases
from core_features.docking.strategies import FullChargeStrategy, VoltageFullCharge

__all__ = [
    "DockingConfig",
    "DockingExecutor",
    "DockingManager",
    "DockingPhasesMixin",
    "DockPhase",
]


class DockingManager(DockingPhasesMixin):
    """도킹 시퀀스, 재시도, 인터록의 소유자."""

    def __init__(self, database: DockDatabase, safety: Any,
                 config: Optional[DockingConfig] = None,
                 clock: Callable[[], float] = time.monotonic,
                 events: Any = None,
                 detector_factory: Optional[Callable[..., DockDetector]] = None,
                 agent_factory: Optional[Callable[[DockInstance], Any]] = None,
                 capability_provider: Optional[Callable[[], bool]] = None,
                 map_id_provider: Optional[Callable[[], Optional[str]]] = None,
                 battery: Any = None,
                 pose_provider: Optional[Callable[[], Any]] = None,
                 line_follow_active_provider: Optional[Callable[[], bool]] = None,
                 take_mode: Optional[Callable[[], None]] = None,
                 release_mode: Optional[Callable[[], None]] = None,
                 motion_admission: Optional[Callable[..., None]] = None,
                 ) -> None:
        self._db = database
        self.motion_admission = motion_admission or (lambda *args: None)
        self._safety = safety
        self._cfg = config or DockingConfig()
        self._clock = clock
        self._events = events
        self._detector_factory, self._agent_factory = detector_factory, agent_factory
        self._capability_provider = capability_provider or (lambda: False)
        self._map_id_provider = map_id_provider or (lambda: None)
        self._battery = battery
        # 맵 포즈 (x, y, yaw) — 주차형의 진입 회전과 크리프 조준. 맵은 대략까지다.
        self._pose_provider = pose_provider or (lambda: None)
        self._line_follow_active = line_follow_active_provider or (lambda: False)
        # DOCKING 모드를 쥔다. 못 쥐면 DockError 로 거절한다 — 매니저를 건드리기
        # **전에** 부른다. API 와 배터리 복귀가 같은 이음새를 지난다.
        self._take_mode = take_mode or (lambda: None)
        # 도킹이 DOCKING/UNDOCKING 을 떠나는 바로 그 임계구역에서 모드를 놓는다
        # (락 안). 밖에서 따로 놓으면 그 틈에 들어온 undock 을 모드 이탈 리스너가
        # 취소해 버린다 (N1). 모드가 이미 DOCKING 이 아니면 아무것도 안 해야 한다.
        self._release_mode = release_mode or (lambda: None)
        # 주차형 단계의 전략. 자기 락·상태가 없고, 아래 필드와 이 락을 그대로 쓴다.
        self._parking_phases, self._rear_phases, self._bay_phases = ParkingPhases(self), RearPhases(self), BayPhases(self)
        # dock/undock/cancel 은 API 워커에서, tick 은 브리지 타이머에서 온다(D-1).
        # 재진입한다: tick 안의 배터리 복귀가 dock() 을, 모드 이탈 리스너가
        # cancel()/abort() 을 부른다.
        self._lock = threading.RLock()
        self.native = NativeReceipts()
        self._execution_binding = None

        self.executor: Optional[DockingExecutor] = None
        #: D-395: may docking drive (LOCALIZED, map frame)? CORE binds the localization
        #: assist; a robot without D-395 keeps this default.
        self.localization_ok: Callable[[], bool] = lambda: True

        self._state = DockState.UNDOCKED
        self._phase: Optional[DockPhase] = None
        self._dock: Optional[DockInstance] = None
        self._dock_type: Any = None
        self._dock_type_for: Optional[str] = None
        self._detector: Optional[DockDetector] = None
        self._agent: Any = None
        self._charging = ChargingConfirmation(
            clock=clock, window_s=self._cfg.charge_confirm_s,
            instrumented=self._cfg.instrumented)
        self._full_charge = VoltageFullCharge(
            enter_v=self._cfg.full_enter_v, exit_v=self._cfg.full_exit_v)
        self._full_announced = False  # D-350: docking.full 1회 방출 플래그

        self._phase_since, self._last_seen_at = 0.0, None
        self._nav_state = NavigationState.IDLE
        self._retries, self._reseats = 0, 0
        self._next_phase_after_backoff: Optional[DockPhase] = None
        self._error: Optional[str] = None
        self._manual_active = False
        self._return_pending = False

        # 주차형 단계 상태
        self._tracker: Optional[DockPoseTracker] = None
        self._turn_target: Optional[float] = None     # 오도메트리 yaw
        self._after_turn: Optional[str] = None        # "acquire" | "undocked"
        self._creep_from: Optional[tuple] = None
        self._creep_done_at: Optional[float] = None
        self._backoff_from: Optional[tuple] = None

    def _execution(self, event, *args):
        return True if self._execution_binding is None else self._execution_binding.check(event, *args)

    def _native_mutate(self, method, *args, **kwargs):
        if self._execution_binding is not None:
            return self._execution_binding.mutate(method, *args, **kwargs)
        return method(*args, **kwargs)

    # --- 조회 -----------------------------------------------------------------

    @property
    def database(self) -> DockDatabase:
        return self._db

    @property
    def state(self) -> DockState:
        with self._lock:
            return self._state

    @property
    def active(self) -> bool:
        """DOCKING/UNDOCKING 인가 — 락 없이 한 속성만 읽는다. 자기 락을 쥔 채
        묻는 쪽(swarm, navigation)용이다: 거기서 도킹 락을 잡으면 도킹 락 →
        항법 락 → swarm 락 순서가 뒤집힌다."""
        return self._state in (DockState.DOCKING, DockState.UNDOCKING)

    @property
    def phase(self) -> Optional[DockPhase]:
        with self._lock:
            return self._phase

    @property
    def retries(self) -> int:
        return self._retries

    @property
    def reseats(self) -> int:
        return self._reseats

    @property
    def fast_tick(self) -> bool:
        """주차·후진·칸형이 움직이는 동안 True — 틱 20 Hz(코스트맵·크리프·정렬은 5 Hz로는 거칠다)."""
        return (self._state in (DockState.DOCKING, DockState.UNDOCKING)
                and (self._parking() or self._rear_phases.active() or self._bay_phases.active()))

    def bind_clock(self, clock: Callable[[], float]) -> None:
        """시계를 바꾼다 (use_sim_time 의 sim 시계). 검출기 신선도와 같은 시계여야 한다."""
        self._clock = clock
        self._charging.bind_clock(clock)

    def now(self) -> float:
        return self._clock()

    @property
    def return_pending(self) -> bool:
        """복귀가 필요하지만 아직 시작하지 못했는가 (수동 조작 중 등)."""
        return self._return_pending

    def status(self) -> DockingStatus:
        with self._lock:
            return DockingStatus(
                state=self._state,
                dock_id=self._dock.id if self._dock else None,
                phase=self._phase.value if self._phase else None,
                retries=self._retries,
                error=self._error,
            )

    def capture_native_operation(self, run_id: UUID | None = None):
        return self.native.capture(self._lock, run_id)

    def native_owner(self, *, wait=True):
        return owner_snapshot(self.native, self._lock, wait=wait)

    def native_readback(self, run_id: UUID | None = None) -> dict:
        with self._lock:
            return readback(self.native, self.executor, self._state, run_id)

    def bind_station(self, bind, *, expected_boot_id, expected_owner_generation):
        """Fence the no-motion binding against concurrent local motion admission."""
        with self._lock:
            self.native.expect(expected_boot_id, expected_owner_generation)
            return bind()

    # --- 명령 -----------------------------------------------------------------

    def dock(self, dock_id: Optional[str] = None, *, correlation_id: str | None = None,
             expected_boot_id: UUID | None = None,
             expected_owner_generation: int | None = None,
             receipt_sink=None, _execution_ticket=None) -> DockInstance:
        with self._lock:
            self._execution('entry', locals())
            return self._dock_locked(dock_id, correlation_id=correlation_id,
                                     expected_boot_id=expected_boot_id,
                                     expected_owner_generation=expected_owner_generation,
                                     receipt_sink=receipt_sink)

    def _dock_locked(self, dock_id: Optional[str], *, correlation_id: str | None = None,
                     expected_boot_id: UUID | None = None,
                     expected_owner_generation: int | None = None,
                     receipt_sink=None) -> DockInstance:
        """도킹을 시작한다. 거부는 예외로 나간다 — API 가 그대로 코드에 매핑한다."""
        dock, dock_type = dock_target(
            self._db, self._safety, self._state, dock_id, supported=self._capability_provider,
            line_active=self._line_follow_active, localized=self.localization_ok, map_id=self._map_id_provider)
        self.motion_admission('dock', dock, dock_type, correlation_id)
        try:
            self.native.expect(expected_boot_id, expected_owner_generation)
        except ValueError as exc:
            raise DockError(str(exc), str(exc)) from exc
        self._execution('ready')
        self._take_mode()
        operation = self._native_mutate(self.native.admit, "dock", correlation_id)
        if receipt_sink is not None:
            receipt_sink(operation)

        self._dock = dock
        self._dock_type, self._dock_type_for = dock_type, dock.id
        self._retries = 0
        self._reseats = 0
        self._error = None
        self._charging.reset()
        self._agent = None  # 앞선 계측 도킹의 잔존 에이전트가 후진 확인을 가리지 않게
        self._state = DockState.DOCKING
        self._execution('activate')
        self._emit("docking.started", "info", {"dock_id": dock.id})
        self._begin_staging()
        return dock

    def undock(self, *, correlation_id: str | None = None,
               expected_boot_id: UUID | None = None,
               expected_owner_generation: int | None = None,
               receipt_sink=None, _execution_ticket=None) -> None:
        with self._lock:
            self._execution('entry', locals())
            self._undock_locked(correlation_id=correlation_id,
                                expected_boot_id=expected_boot_id,
                                expected_owner_generation=expected_owner_generation,
                                receipt_sink=receipt_sink)

    def _undock_locked(self, *, correlation_id: str | None = None,
                       expected_boot_id: UUID | None = None,
                       expected_owner_generation: int | None = None,
                       receipt_sink=None) -> None:
        undock_ready(self._state, self._safety, self._line_follow_active, self.executor)
        self.motion_admission('undock', self._dock, self._type(), correlation_id)
        try:
            self.native.expect(expected_boot_id, expected_owner_generation)
        except ValueError as exc:
            raise DockError(str(exc), str(exc)) from exc
        self._execution('ready')
        self._take_mode()
        operation = self._native_mutate(self.native.admit, "undock", correlation_id)
        if receipt_sink is not None:
            receipt_sink(operation)

        # Leave by odometry: dock proximity makes front sensors unreliable.
        self._stop_detector()
        self._charging.reset()
        self._state = DockState.UNDOCKING
        self._execution('activate')
        self._phase = None
        self._phase_since = self._clock()
        if self.executor is not None:
            self.executor.reset_odometry_mark()
        self._emit("docking.undock_started", "info",
                   {"dock_id": self._dock.id if self._dock else None})

    def departure_limits(self):
        """Installed native reverse geometry; callers must reject unmeasured defaults."""
        with self._lock:
            dock_type = self._type() if self._dock is not None else None
            if dock_type is None:
                raise DockError('NOT_DOCKED', 'departure requires the current dock')
            return dock_type.undock_distance_m, self._cfg.undock_speed, dock_type.undock_turn_rad

    def cancel(self, *, receipt_sink=None) -> None:
        """진행 중인 시퀀스를 접는다. 실패가 아니라 취소다."""
        with self._lock:
            try:
                self._cancel_locked(receipt_sink=receipt_sink)
            finally:
                self._release_mode_when_done()

    def _cancel_locked(self, *, receipt_sink=None) -> None:
        if self._state not in (DockState.DOCKING, DockState.UNDOCKING):
            return
        operation = self.native.current
        if operation is not None:
            closed = self._native_mutate(self.native.update, operation.run_id, phase="TERMINAL",
                                        result="CANCELED", reason="CANCELED")
            if receipt_sink is not None:
                receipt_sink(closed)
        self._release()
        self._state = DockState.UNDOCKED
        self._phase = None
        self._emit("docking.canceled", "info",
                   {"dock_id": self._dock.id if self._dock else None})

    def remove_dock(self, dock_id: str) -> None:
        """도크를 지운다. 도킹·언도킹 중인 도크는 지우지 않는다."""
        with self._lock:
            self._remove_dock_locked(dock_id)

    def _remove_dock_locked(self, dock_id: str) -> None:
        if (self._state in (DockState.DOCKING, DockState.UNDOCKING)
                and self._dock is not None and self._dock.id == dock_id):
            raise DockError("DOCKING_ACTIVE",
                            f"dock '{dock_id}' is in use ({self._state.value})")
        self._db.remove(dock_id)

    def abort(self, reason: str) -> None:
        """진행 중인 시퀀스를 실패로 접는다 (예: DOCKING 에서 EMERGENCY 로)."""
        with self._lock:
            try:
                if self._state in (DockState.DOCKING, DockState.UNDOCKING):
                    self._fail(reason, safety_stop=getattr(self._safety, "estop", False))
            finally:
                # _fail 은 상태를 먼저 적는다 — 정리가 예외를 내도 모드는 놓는다.
                self._release_mode_when_done()

    def on_navigation_state(self, state: NavigationState) -> None:
        self._nav_state = state

    def set_manual_active(self, active: bool) -> None:
        """수동 조작 세션의 유무. MANUAL(3)이 DOCKING(4)보다 위다 — 운영자가
        쥐고 있는 로봇을 배터리 정책이 빼앗지 않는다."""
        self._manual_active = bool(active)

    def on_estop(self) -> None:
        """D-502: e-stop or release drops a pending return; re-arming waits for safety."""
        self._return_pending = False

    def on_battery_level(self, level: BatteryLevel) -> None:
        """SAF-005 단계 변화 → 자동 복귀 (DNC-006)."""
        if level in (BatteryLevel.OK,):
            self._return_pending = False
            return
        if getattr(self._safety, "battery_return_suppressed", False):
            return
        if level not in (BatteryLevel.WARNING, BatteryLevel.CRITICAL,
                         BatteryLevel.DEEP):
            return

        if self._state is not DockState.UNDOCKED:
            return
        if not self._capability_provider():
            return
        if self._db.only() is None and len(self._db.list()) != 1:
            return

        self._return_pending = True
        self._try_pending_return()

    def _try_pending_return(self) -> bool:
        if not self._return_pending:
            return False
        if self._manual_active or getattr(self._safety, "estop", False):
            return False
        if self._state is not DockState.UNDOCKED:
            return False
        if not self.localization_ok():
            return False  # D-395: stays pending; the tick retries once LOCALIZED

        if self.executor is not None:
            self.executor.cancel_navigation()
        try:
            dock = self.dock()
        except DockError:
            return False
        self._return_pending = False
        self._emit("docking.return_started", "warning",
                   {"dock_id": dock.id, "reason": "battery"})
        return True

    # --- 틱 -------------------------------------------------------------------

    def tick(self, now: Optional[float] = None) -> None:
        with self._lock:
            try:
                self._tick_locked(now)
            finally:
                self._release_mode_when_done()

    def _release_mode_when_done(self) -> None:
        """도킹이 더는 로봇을 움직이지 않으면 DOCKING 을 놓는다. 락 안에서만 부른다."""
        if self._state not in (DockState.DOCKING, DockState.UNDOCKING):
            self._release_mode()

    def _tick_locked(self, now: Optional[float]) -> None:
        current = self._clock() if now is None else now

        # E-Stop 은 어느 단계에서든 즉시 중단시킨다.
        if getattr(self._safety, "estop", False) and self._state in (
                DockState.DOCKING, DockState.UNDOCKING):
            self._fail("estop during docking", safety_stop=True)
            return

        if self._return_pending and self._state is DockState.UNDOCKED:
            self._try_pending_return()

        if self._state is DockState.DOCKING:
            self._tick_docking(current)
        elif self._state is DockState.UNDOCKING:
            self._tick_undocking(current)
        elif self._state in (DockState.DOCKED, DockState.CHARGING):
            self._tick_docked(current)

    def _emit(self, type_: str, severity: str, data: dict) -> None:
        if self._events is not None:
            operation = self.native.current
            if operation is not None:
                data = {**data, "run_id": str(operation.run_id),
                        "boot_id": str(operation.boot_id)}
                if operation.phase == "TERMINAL" and type_ in (
                        "docking.docked", "docking.undocked", "docking.failed", "docking.canceled"):
                    data.update(kind=operation.kind, result=operation.result,
                                native_reason=operation.reason)
            self._events.publish(type_, severity=severity,
                                 source="docking_manager", data=data)
