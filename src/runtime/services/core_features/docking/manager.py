"""core_features.docking.manager — 도킹 상태머신 (DNC-002~003).

**맵은 대략까지, 마지막은 센서가.** 로컬라이제이션 오차는 ±10 cm 이고 접점은
수 mm 안에서 물린다. 두 자릿수 차이라, 도크의 맵 좌표로 주행해 멈추는 제어기는
결코 도킹하지 못한다. 스테이징 이후의 모든 단계는 *관측된* 도크에 폐루프를 건다.

이 액션은 Nav2 구간까지 스스로 소유한다. 모드 전이표가 `NAVIGATION → DOCKING`
을 막고 있어서인데, 표에 간선을 더하는 대신 도킹이 처음부터 끝까지 `DOCKING`
모드를 쥐면 표를 건드릴 필요가 없고 우선순위도 공짜로 맞는다 — `DOCKING`(4)이
`NAVIGATION`(5)보다 위라 도크에 반쯤 들어간 로봇을 Fleet 주행 명령이 밀어내지
못한다.

ROS 무의존 — 시계는 주입되며 테스트가 시간을 직접 전진시킨다.

주차형 기종(`approach="pose"`, 차선망 미션 3단계)은 같은 상태머신을 기종 설정으로
갈라 쓴다. 그 단계 로직은 `parking_phases.ParkingPhases` 에 있고, 상태·락·순서는
여기 남는다. 단계·모션 계약·설정 정의는 `model` 에 있다.

설계: docs/plans/2026-09-02-docking-station-design.md,
      docs/plans/2026-09-23-lane-network-parking-design.md
"""

from __future__ import annotations

import math
import threading
import time
from typing import Any, Callable, Optional

from core_features.docking.charging import ChargingConfirmation
from core_features.docking.database import DockDatabase, DockError, DockInstance
from core_features.docking.detector import DockDetector
from core_features.docking.model import DockingConfig, DockingExecutor, DockPhase
from core_features.docking.parking import DockPoseTracker
from core_features.docking.parking_phases import ParkingPhases
from core_common.protocol.schemas import (
    BatteryLevel,
    DockingStatus,
    DockState,
    NavigationState,
)

__all__ = ["DockingConfig", "DockingExecutor", "DockingManager", "DockPhase"]


class DockingManager:
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
                 ) -> None:
        self._db = database
        self._safety = safety
        self._cfg = config or DockingConfig()
        self._clock = clock
        self._events = events
        self._detector_factory = detector_factory
        self._agent_factory = agent_factory
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
        self._parking_phases = ParkingPhases(self)
        # dock/undock/cancel 은 API 워커에서, tick 은 브리지 타이머에서 온다(D-1).
        # 재진입한다: tick 안의 배터리 복귀가 dock() 을, 모드 이탈 리스너가
        # cancel()/abort() 을 부른다.
        self._lock = threading.RLock()

        self.executor: Optional[DockingExecutor] = None

        self._state = DockState.UNDOCKED
        self._phase: Optional[DockPhase] = None
        self._dock: Optional[DockInstance] = None
        self._dock_type: Any = None
        self._dock_type_for: Optional[str] = None
        self._detector: Optional[DockDetector] = None
        self._agent: Any = None
        self._charging = ChargingConfirmation(
            clock=clock, window_s=self._cfg.charge_confirm_s)

        self._phase_since = 0.0
        self._last_seen_at: Optional[float] = None
        self._nav_state = NavigationState.IDLE
        self._retries = 0
        self._reseats = 0
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
        """주차형이 움직이는 동안 True — 브리지가 틱을 20 Hz 로 올린다. nav 슬롯은
        0.5 s 에 만료되고, 크리프·정렬은 5 Hz 로는 거칠다."""
        return (self._state in (DockState.DOCKING, DockState.UNDOCKING)
                and self._parking())

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

    # --- 명령 -----------------------------------------------------------------

    def dock(self, dock_id: Optional[str] = None) -> DockInstance:
        with self._lock:
            return self._dock_locked(dock_id)

    def _dock_locked(self, dock_id: Optional[str]) -> DockInstance:
        """도킹을 시작한다. 거부는 예외로 나간다 — API 가 그대로 코드에 매핑한다."""
        if not self._capability_provider():
            raise DockError("CAPABILITY_NOT_SUPPORTED",
                            "docking is not supported on this robot")
        if getattr(self._safety, "estop", False):
            raise DockError("EMERGENCY_ACTIVE", "e-stop is active")
        if self._state in (DockState.DOCKING, DockState.UNDOCKING):
            raise DockError("DOCKING_ACTIVE",
                            f"docking already in progress ({self._state.value})")
        # 라인 추종도 같은 nav 슬롯에 20 Hz 로 쓴다. 둘이 번갈아 쓰면 바퀴가 둘 중
        # 아무것도 따르지 않는다 — 먼저 끄게 한다.
        if self._line_follow_active():
            raise DockError("LINE_FOLLOW_ACTIVE", "stop line following first")

        if dock_id is None:
            dock = self._db.only()
            if dock is None:
                raise DockError("DOCK_REQUIRED",
                                "dock id required — zero or several docks configured")
        else:
            dock = self._db.get(dock_id)

        dock.require_map(self._map_id_provider())
        dock_type = self._db.type_of(dock.id)
        self._take_mode()

        self._dock = dock
        self._dock_type, self._dock_type_for = dock_type, dock.id
        self._retries = 0
        self._reseats = 0
        self._error = None
        self._charging.reset()
        self._state = DockState.DOCKING
        self._emit("docking.started", "info", {"dock_id": dock.id})
        self._begin_staging()
        return dock

    def undock(self) -> None:
        with self._lock:
            self._undock_locked()

    def _undock_locked(self) -> None:
        if self._state not in (DockState.DOCKED, DockState.CHARGING):
            raise DockError("NOT_DOCKED", f"not docked ({self._state.value})")
        if getattr(self._safety, "estop", False):
            raise DockError("EMERGENCY_ACTIVE", "e-stop is active")
        if self._line_follow_active():
            raise DockError("LINE_FOLLOW_ACTIVE", "stop line following first")
        available = getattr(self.executor, "odometry_available", None)
        if callable(available) and not available():
            # 후진은 오도메트리만 본다. 기준점이 없으면 이동 거리가 0 에 머물러
            # 벽(57 mm 뒤)에 닿을 때까지 후진한다.
            raise DockError("NO_ODOMETRY", "no odometry to measure the reverse")
        self._take_mode()

        # 도크에 반쯤 물린 상태에서는 LiDAR 도 카메라도 벽을 3 cm 앞에서 보고
        # 있다. 믿을 게 없으므로 검출기를 끄고 오도메트리만으로 빠져나온다.
        self._stop_detector()
        self._charging.reset()
        self._state = DockState.UNDOCKING
        self._phase = None
        self._phase_since = self._clock()
        if self.executor is not None:
            self.executor.reset_odometry_mark()
        self._emit("docking.undock_started", "info",
                   {"dock_id": self._dock.id if self._dock else None})

    def cancel(self) -> None:
        """진행 중인 시퀀스를 접는다. 실패가 아니라 취소다."""
        with self._lock:
            try:
                self._cancel_locked()
            finally:
                self._release_mode_when_done()

    def _cancel_locked(self) -> None:
        if self._state not in (DockState.DOCKING, DockState.UNDOCKING):
            return
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
                    self._fail(reason)
            finally:
                # _fail 은 상태를 먼저 적는다 — 정리가 예외를 내도 모드는 놓는다.
                self._release_mode_when_done()

    def on_navigation_state(self, state: NavigationState) -> None:
        self._nav_state = state

    def set_manual_active(self, active: bool) -> None:
        """수동 조작 세션의 유무. MANUAL(3)이 DOCKING(4)보다 위다 — 운영자가
        쥐고 있는 로봇을 배터리 정책이 빼앗지 않는다."""
        self._manual_active = bool(active)

    def on_battery_level(self, level: BatteryLevel) -> None:
        """SAF-005 단계 변화 → 자동 복귀 (DNC-006).

        임계는 크리티컬(10%)이 아니라 경고(20%)다. 10%는 2S 팩의 절벽 구간이라
        거기서 출발하면 도크까지 못 갈 수 있고, 전류 센싱이 없어 "갈 수 있는가"를
        계산할 방법도 없다. 로봇은 임무를 더 일찍 포기하고, 그것이 의도한 거래다.
        """
        if level in (BatteryLevel.OK,):
            self._return_pending = False
            return
        if level not in (BatteryLevel.WARNING, BatteryLevel.CRITICAL,
                         BatteryLevel.DEEP):
            return

        # 이미 도크에 있거나 가는 중이면 할 일이 없다. DOCK_FAILED 도 마찬가지다 —
        # 실패한 도킹을 배터리 경고로 되풀이하면 지키려던 팩을 마저 비운다.
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

        # 진행 중이던 주행을 접는다. 임무는 포기되고, 그 사실은 이벤트로 남는다.
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
            self._fail("estop during docking")
            return

        if self._return_pending and self._state is DockState.UNDOCKED:
            self._try_pending_return()

        if self._state is DockState.DOCKING:
            self._tick_docking(current)
        elif self._state is DockState.UNDOCKING:
            self._tick_undocking(current)
        elif self._state in (DockState.DOCKED, DockState.CHARGING):
            self._tick_docked(current)

    def _tick_docking(self, now: float) -> None:
        phase = self._phase
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
            self.executor.navigate_to(self._dock.staging_pose(offset))

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
            self._detector = self._detector_factory(
                self._dock, self._type())
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
            if self._last_seen_at is None or now - self._last_seen_at > \
                    self._cfg.detector_lost_grace_s:
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
            angular = max(-self._cfg.max_angular,
                          min(self._cfg.max_angular,
                              self._cfg.approach_gain_yaw * heading))
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
            # 접점에 닿지 못했다. 스테이징까지 돌아갈 일은 아니고 재착좌면 된다.
            self._reseat("no contact after approach")

    def _tick_docked(self, now: float) -> None:
        """도크에 있는 동안 충전을 확인하고 배터리 정책에 알린다."""
        status = self._agent.poll() if self._agent is not None else None
        voltage = getattr(self._battery, "voltage", None) if self._battery else None
        confirmed = False
        if status is not None:
            confirmed = self._charging.update(status, voltage, now=now)

        if self._battery is not None:
            self._battery.set_charging(confirmed)

        target = DockState.CHARGING if confirmed else DockState.DOCKED
        if target is not self._state:
            self._state = target
            self._emit("docking.charging" if confirmed else "docking.charge_lost",
                       "info", {"dock_id": self._dock.id if self._dock else None})

    def _tick_undocking(self, now: float) -> None:
        if self.executor is None:
            self._state = DockState.UNDOCKED
            return
        if self._phase is DockPhase.TURNING:
            self._parking_phases.tick_turning(now)
            return
        distance = self._type().undock_distance_m \
            if self._dock else 0.35
        travelled = abs(self.executor.travelled_m())
        deadline = (2.0 * distance / self._cfg.undock_speed
                    + self._cfg.undock_timeout_margin_s)
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
        self.executor.drive(-self._cfg.undock_speed, 0.0)

    def _finish_undock(self) -> None:
        if self.executor is not None:
            self.executor.stop()
        self._state = DockState.UNDOCKED
        self._phase = None
        self._dock = None
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
        self._emit("docking.retry", "warning",
                   {"reason": reason, "attempt": self._retries})
        self._begin_backoff(DockPhase.STAGING)

    def _reseat(self, reason: str) -> None:
        """접점만 다시 문다. 도착은 했으므로 스테이징까지 되돌아가지 않는다."""
        limit = self._type().max_retries if self._dock else 0
        if self._reseats >= limit:
            self._fail(reason)
            return
        self._reseats += 1
        self._emit("docking.reseat", "warning",
                   {"reason": reason, "attempt": self._reseats})
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
        """The dock's type, cached when docking starts: a dock or type deleted
        mid-run (another API worker, a hand-edited docks.json) must not raise
        NOT_FOUND out of the tick."""
        if self._dock is None:
            return None
        if self._dock_type is None or self._dock_type_for != self._dock.id:
            self._dock_type = self._db.type_of(self._dock.id)
            self._dock_type_for = self._dock.id
        return self._dock_type

    def _parking(self) -> bool:
        dock_type = self._type()
        return dock_type is not None and dock_type.approach == "pose"

    def _fail(self, reason: str) -> None:
        """종착이다. 스스로 재시도하지 않는다.

        무인 상태로 스무 번 실패한 로봇은 물리적 문제를 갖고 있다. 자동 루프는
        그것을 숨기면서, 지키려던 팩을 마저 비운다.

        상태를 먼저 적는다 — 정리(_release)가 예외를 내도 도킹은 끝난 것이다.
        """
        self._state = DockState.DOCK_FAILED
        self._phase = None
        self._error = reason
        self._release()
        self._emit("docking.failed", "error",
                   {"reason": reason, "dock_id": self._dock.id if self._dock else None})

    # --- 공통 -----------------------------------------------------------------

    def _mark_docked(self) -> None:
        self._state = DockState.DOCKED
        self._phase = None
        self._emit("docking.docked", "info", {"dock_id": self._dock.id})

    def _enter(self, phase: DockPhase) -> None:
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

    def _emit(self, type_: str, severity: str, data: dict) -> None:
        if self._events is not None:
            self._events.publish(type_, severity=severity,
                                 source="docking_manager", data=data)
