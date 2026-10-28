"""core_features.navigation.manager — NAV-001~004/006 (P1-7, P1-20). ROS 무의존.

실행(Nav2 액션)은 executor 인터페이스 뒤로 격리 — bridge가 구현 (ROS-101/HWA-002 원칙).
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Optional, Protocol
from uuid import UUID
from uuid import uuid4

from core_common.protocol.schemas import NavigationState
from core_common.protocol.native_receipts import NativeReceipts
from .native_handover import native_readback, with_terminal_navigation


@dataclass
class NavGoalSpec:
    x: float
    y: float
    yaw: float
    frame: str = "map"


class NavExecutor(Protocol):
    def send_goal(self, spec: NavGoalSpec, *, correlation_id: str | None = None) -> None: ...
    def cancel_goal(self) -> None: ...
    def send_initial_pose(self, x: float, y: float, yaw: float) -> None: ...
    def save_map(self, name: str) -> str: ...   # map_id 반환 (D-13, 브리지가 체크섬/대체 해시 산출)
    def reset_mapping(self) -> None: ...        # NAV-005 세션 초기화


class NavigationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


_IDLE_STATES = {NavigationState.IDLE, NavigationState.ARRIVED,
                NavigationState.CANCELED, NavigationState.FAILED}

#: D-550 10: largest goal lease (s); the API reference row pins 0 < ttl_s <= 5.
GOAL_LEASE_MAX_S = 5.0


def _check_lease_ttl(ttl_s: float) -> None:
    if not (isinstance(ttl_s, (int, float)) and math.isfinite(ttl_s) and 0 < ttl_s <= GOAL_LEASE_MAX_S):
        raise NavigationError("VALIDATION_ERROR", f"lease ttl must be 0 < ttl_s <= {GOAL_LEASE_MAX_S:g}")


class NavigationManager:
    def __init__(self, events, state_manager, waypoints, safety,
                 map_id_provider=None, stuck_timeout_s: float = 30.0,
                 stuck_min_progress: float = 0.05, readiness=None,
                 clock=time.monotonic, lease_clock=time.monotonic) -> None:
        self._events = events
        self._state = state_manager
        self._waypoints = waypoints
        self._safety = safety
        # Optional ROS-free gate supplied by CoreServices.  The bridge updates
        # it from lifecycle/adapter observations; keeping the dependency
        # duck-typed preserves the host-testable navigation facade.
        self._readiness = readiness
        self._map_id_provider = map_id_provider or (lambda: self._state.map_id)
        self.executor: Optional[NavExecutor] = None
        self._nav_state = NavigationState.IDLE
        self._active_correlation_id: str | None = None
        #: The goal that `goal()` sent last; read only while a correlation id is active (D-419).
        self._active_spec: Optional[NavGoalSpec] = None
        self.mapping_active = False
        self._stuck_timeout = stuck_timeout_s
        self._stuck_min_progress = stuck_min_progress
        #: NAV-006 의 시계. 기본은 벽시계지만 브리지가 ROS 시계로 갈아끼운다 — `use_sim_time`
        #: 이 켜진 시뮬에서 벽시계로 재면, RTF 0.1 인 기계에서 "30 초 무진척"이 실제로는
        #: 시뮬 3 초가 되어 제자리 회전만 하던 로봇이 곧바로 stuck 으로 잘린다.
        #: 실기에서는 ROS 시계가 곧 시스템 시계라 동작이 같다.
        self.clock = clock
        self._last_progress_pos: Optional[tuple[float, float]] = None
        self._last_progress_ts: float = 0.0
        #: D-550 10 goal lease: ``(correlation_id, expires_at)`` on ``lease_clock``, the host
        #: monotonic clock (not ``clock``, which the bridge may swap for sim time). It counts only
        #: while that correlation id is still the active goal.
        self.lease_clock = lease_clock
        self._lease: Optional[tuple[str, float, UUID, str | None]] = None
        # 목표는 uvicorn 워커(REST·WS)와 rclpy executor(브리지 타이머) 양쪽에서
        # 건드려진다(D-1). check-send-set 이 쪼개지면 취소가 목표를 놓친다.
        self._lock = threading.RLock()
        self.native = NativeReceipts()
        self._execution_binding = None
        self._map_evidence = None  # Original navigation map observations, never render/adoption authority.
        self._admitting: UUID | None = None
        #: moving goal 세션이 열려 있으면 목표의 임자는 그쪽이다 (SWM-001).
        #: 토큰을 여기서 발급해, 추종자가 자기 락을 쥔 채 이쪽을 부르지 않아도
        #: 취소 뒤에 뒤늦은 목표가 새어 들어오지 못한다.
        self._moving_session: Optional[int] = None
        self._session_counter = 0
        #: 열린 moving goal 세션이 닫힐 때 임자에게 알린다. 세션을 닫는 길은
        #: 여럿이고(운영자의 /navigation/cancel, MANUAL 전환, NAV-006 stuck),
        #: 알리지 않으면 추종자는 자기가 살아 있다고 계속 광고하면서 목표를
        #: 하나도 내지 못하는 상태로 남는다.
        self.session_closed_listener = None
        #: 도킹이 주행을 쥐고 있는가 (CoreServices 가 주입). 그동안 목표는 거절한다 —
        #: Nav2 목표가 도크 진입을 선점하면 안 된다 (DOCKING 4 > NAVIGATION 5).
        self.docking_active_provider = lambda: False

    def _execution(self, event, *args):
        return True if self._execution_binding is None else self._execution_binding.check(event, *args)

    def _native_mutate(self, method, *args, **kwargs):
        if self._execution_binding is not None:
            return self._execution_binding.mutate(method, *args, **kwargs)
        return method(*args, **kwargs)

    def _advance_generation(self):
        self.native.generation += 1

    def set_readiness_gate(self, readiness) -> None:
        """Attach the runtime readiness gate after construction if needed."""
        self._readiness = readiness

    def require_ready(self) -> None:
        """Reject a motion request while the hardware readiness gate is HOLD."""
        if self._readiness is None:
            return
        snapshot = self._readiness.snapshot()
        if not snapshot.ready:
            raise NavigationError("HARDWARE_NOT_READY", f"navigation readiness HOLD: {snapshot.reason}")

    @property
    def nav_state(self) -> NavigationState:
        return self._nav_state

    def _set_state(self, new: NavigationState) -> None:
        if new is not self._nav_state:
            self._nav_state = new
            self._state.set_navigation(new)

    def _require_executor(self) -> NavExecutor:
        if self.executor is None:
            raise NavigationError("CAPABILITY_NOT_SUPPORTED", "navigation executor unavailable")
        return self.executor

    def reserve_goal(self, *, expected_boot_id: UUID | None = None,
                     expected_owner_generation: int | None = None) -> UUID:
        self._execution('unsupported')
        self._refuse_while_docking()
        with self._lock:
            self._execution('unsupported')
            try:
                self.native.expect(expected_boot_id, expected_owner_generation)
            except ValueError as exc:
                raise NavigationError(str(exc), str(exc)) from exc
            if (self._admitting is not None or self._moving_session is not None
                    or self._nav_state not in _IDLE_STATES
                    or self.native.current is not None and self.native.current.phase != "TERMINAL"):
                raise NavigationError("NAVIGATION_ACTIVE", "navigation owner is busy")
            token = uuid4()
            self._admitting = token
            self._native_mutate(self._advance_generation)
            return token

    def release_goal_reservation(self, token: UUID) -> None:
        with self._lock:
            if self._admitting == token:
                self._admitting = None
                self._native_mutate(self._advance_generation)

    def resolve_goal(self, *, x=None, y=None, yaw=None, waypoint=None) -> NavGoalSpec:
        if waypoint is not None:
            wp = self._waypoints.get(waypoint)
            current_map = self._map_id_provider()
            if wp.map_id and current_map and wp.map_id != current_map:
                raise NavigationError("MAP_MISMATCH",
                                      f"waypoint map '{wp.map_id}' != current '{current_map}'")
            return NavGoalSpec(x=wp.x, y=wp.y, yaw=wp.yaw)
        if x is None or y is None:
            raise NavigationError("VALIDATION_ERROR", "x,y or waypoint required")
        return NavGoalSpec(x=float(x), y=float(y), yaw=float(yaw or 0.0))

    def goal(self, spec: NavGoalSpec, source: str = "api",
             correlation_id: str | None = None, lease_ttl_s: float | None = None,
             *, kind: str = "navigate", receipt_sink=None, lease_owner: str | None = None,
             expected_boot_id: UUID | None = None,
             expected_owner_generation: int | None = None,
             reservation: UUID | None = None, _execution_ticket=None) -> None:
        with self._lock:
            self._execution('entry', locals())
        if lease_ttl_s is not None:
            # D-550 10: a lease is renewed by correlation id, so a leased goal needs one.
            _check_lease_ttl(lease_ttl_s)
            if correlation_id is None:
                raise NavigationError("VALIDATION_ERROR", "lease_ttl_s needs a correlation_id")
        self.require_ready()
        executor = self._require_executor()
        if self._safety.estop:
            raise NavigationError("EMERGENCY_ACTIVE", "e-stop is active")
        if self.mapping_active:
            raise NavigationError("MAPPING_ACTIVE", "mapping session active")
        self._refuse_while_docking()
        with self._lock:
            if reservation is None:
                if self._admitting is not None:
                    raise NavigationError("NAVIGATION_ACTIVE", "navigation admission in progress")
                try:
                    self.native.expect(expected_boot_id, expected_owner_generation)
                except ValueError as exc:
                    raise NavigationError(str(exc), str(exc)) from exc
            elif self._admitting != reservation:
                raise NavigationError("OWNER_GENERATION_CHANGED", "navigation admission was revoked")
            if self._moving_session is not None:
                # 추종 중에 들어온 단발 목표는 0.5 초 뒤 스트림에 덮인다.
                # 조용히 덮이느니 거절하는 편이 낫다.
                raise NavigationError("NAVIGATION_ACTIVE",
                                      "a moving-goal session owns the goal — cancel it first")
            if self._nav_state not in _IDLE_STATES:
                raise NavigationError(
                    "NAVIGATION_ACTIVE",
                    f"navigation in progress ({self._nav_state.value}) — cancel first")
            if self.native.current is not None and self.native.current.phase != "TERMINAL":
                raise NavigationError("NAVIGATION_ACTIVE", "native run has unresolved backend evidence")
            if reservation is not None:
                self._admitting = None
                self._native_mutate(self._advance_generation)
            operation = self._native_mutate(self.native.admit, kind, correlation_id)
            if receipt_sink is not None:
                receipt_sink(operation)
            self._set_state(NavigationState.PLANNING)
            self._active_correlation_id = correlation_id
            self._active_spec = spec
            self._lease = (None if lease_ttl_s is None
                           else (correlation_id, self.lease_clock() + lease_ttl_s,
                                 operation.run_id, lease_owner))
            try:
                native_send = getattr(executor, "send_native_goal", None)
                if native_send is not None:
                    native_send(spec, operation.run_id, correlation_id=correlation_id)
                elif correlation_id is None:
                    executor.send_goal(spec)
                else:
                    executor.send_goal(spec, correlation_id=correlation_id)
            except Exception:
                current = self.native.current
                if current is not None:
                    self._native_mutate(self.native.update, operation.run_id, phase=current.phase,
                                       reason="BACKEND_RESULT_UNKNOWN")
                raise
        self._events.publish("nav.started", source="navigation_manager",
                             data={"goal": {"x": spec.x, "y": spec.y, "yaw": spec.yaw},
                                   "by": source, "correlation_id": correlation_id})

    def external_goal_sent(self) -> None:
        """Mirror docking's staging goal; never retain an earlier terminal state."""
        with self._lock:
            self._execution('staging')
            self._set_state(NavigationState.PLANNING)
            self._active_correlation_id = None

    def fleet_goal(self) -> Optional[tuple[str, NavGoalSpec]]:
        """`(correlation_id, spec)` of the Fleet goal in progress, else None (SAF-003, D-419).

        A goal is Fleet's when it carries a dispatch-attempt correlation id (D-316); local
        dashboard goals, docking staging and moving-goal sessions carry none."""
        with self._lock:
            if (self._active_correlation_id is None or self._active_spec is None
                    or self._nav_state in _IDLE_STATES):
                return None
            return self._active_correlation_id, self._active_spec

    def renew_goal_lease(self, correlation_id: str, ttl_s: float, owner: str | None = None) -> None:
        """D-550 10: renew only an unexpired lease for this exact goal and sender."""
        _check_lease_ttl(ttl_s)
        with self._lock:
            now = self.lease_clock()
            if (self._lease is None or now >= self._lease[1] or self._nav_state in _IDLE_STATES
                    or correlation_id != self._lease[0] or correlation_id != self._active_correlation_id):
                raise NavigationError("GOAL_LEASE_NOT_ACTIVE", f"no active leased goal {correlation_id!r}")
            if owner != self._lease[3]:  # D-760 9: only the token that sent the goal (lease_owner)
                raise NavigationError("FORBIDDEN", "only the token that sent this leased goal may renew it")
            self._lease = (correlation_id, now + ttl_s, self._lease[2], self._lease[3])
            self._native_mutate(self._advance_generation)

    def expire_goal_lease(self) -> bool:
        """D-550 10: cancel a leased goal whose lease ran out, on the SAF-003 STOP cancel path.
        Ticked by the bridge (5 Hz). True when a goal was cancelled."""
        with self._lock:
            lease = self._lease
            if lease is None or self.lease_clock() < lease[1]:
                return False
            # Dropped first: a renewal racing this expiry is refused, not revived.
            self._lease = None
        # A goal that already ended or was replaced is left alone (correlation id check).
        return self.cancel(source="goal_lease", correlation_id=lease[0], run_id=lease[2])

    def _refuse_while_docking(self) -> None:
        if self.docking_active_provider():
            raise NavigationError("DOCKING_ACTIVE", "a docking run owns the robot")

    def open_moving_session(self) -> int:
        """Open a token-owned session, mutually exclusive with mapping under the lock."""
        self._execution('unsupported')
        with self._lock:
            self._execution('unsupported')
            if self._admitting is not None:
                raise NavigationError("NAVIGATION_ACTIVE", "navigation admission in progress")
            if self.mapping_active:
                raise NavigationError("MAPPING_ACTIVE",
                                      "a mapping session owns navigation")
            self._session_counter += 1
            self._moving_session = self._session_counter
            # 새 세션의 무진척 시계는 여기서 시작한다. `on_goal_accepted` 는 SWM-002 때문에
            # 추종 중에는 기준점을 지우지 않는데, 그 규칙이 세션이 열리는 순간까지 걸리면
            # 직전 주행에서 남은 낡은 기준시각을 그대로 물려받는다. 한참 서 있던 로봇은
            # 첫 참조 pose 하나에 30 초 조건이 이미 성립해 무장 직후 stuck 으로 끊긴다.
            self._last_progress_pos = None
            self._last_progress_ts = self.clock()
            return self._moving_session

    def moving_goal(self, spec: NavGoalSpec, source: str = "moving",
                    session: Optional[int] = None) -> bool:
        """SWM-001: token-owned replacement; retain e-stop/mapping/readiness gates.

        Nav2 preempts the old goal without an intervening cancel/stop.
        """
        self._execution('unsupported')
        self.require_ready()
        executor = self._require_executor()
        if self._safety.estop:
            raise NavigationError("EMERGENCY_ACTIVE", "e-stop is active")
        if self.mapping_active:
            raise NavigationError("MAPPING_ACTIVE", "mapping session active")
        self._refuse_while_docking()
        with self._lock:
            self._execution('unsupported')
            if self._admitting is not None:
                return False
            if session is not None and self._moving_session != session:
                # 취소된 세션의 뒤늦은 목표. 내보내면 아무도 거두지 않는다.
                return False
            if self._active_correlation_id is not None:
                raise NavigationError(
                    "NAVIGATION_ACTIVE",
                    "a Fleet-correlated navigation task owns the current goal",
                )
            if session is None:
                self._session_counter += 1
                self._moving_session = self._session_counter
            executor.send_goal(spec)
            started = self._nav_state not in (NavigationState.NAVIGATING,
                                              NavigationState.PLANNING)
            if started:
                self._set_state(NavigationState.PLANNING)
        if started:
            self._events.publish(
                "nav.started", source="navigation_manager",
                data={"goal": {"x": spec.x, "y": spec.y, "yaw": spec.yaw}, "by": source})
        return True

    def home(self, source: str = "api", correlation_id: str | None = None,
             lease_ttl_s: float | None = None, *, receipt_sink=None, lease_owner: str | None = None,
             expected_boot_id: UUID | None = None,
             expected_owner_generation: int | None = None,
             reservation: UUID | None = None) -> None:
        spec = self.resolve_goal(waypoint="__home__")
        self.goal(spec, source=source, correlation_id=correlation_id, lease_owner=lease_owner,
                  lease_ttl_s=lease_ttl_s, kind="home", receipt_sink=receipt_sink,
                  expected_boot_id=expected_boot_id,
                  expected_owner_generation=expected_owner_generation,
                  reservation=reservation)

    # --- NAV-005 Mapping 세션 -------------------------------------------------

    def start_mapping(self, source: str = "api") -> None:
        self._execution('unsupported')
        self.require_ready()
        if self._safety.estop:
            raise NavigationError("EMERGENCY_ACTIVE", "e-stop is active")
        with self._lock:
            self._execution('unsupported')
            if self._admitting is not None:
                raise NavigationError("NAVIGATION_ACTIVE", "navigation admission in progress")
            if self._moving_session is not None:
                # `moving_goal` refuses during a mapping session; this is the
                # other direction. `_nav_state` alone does not see a follow in
                # HOLD — no goal is out, but the formation still owns the goal
                # and resumes the moment its stream returns.
                raise NavigationError(
                    "NAVIGATION_ACTIVE",
                    "a moving-goal session owns the goal — cancel it first")
            if self._nav_state not in _IDLE_STATES:
                raise NavigationError("NAVIGATION_ACTIVE",
                                      f"navigation in progress ({self._nav_state.value})")
            # 확인과 같은 락 안에서 쓴다. 밖에 두면 그 사이에 열린 추종 세션과
            # 맵핑이 함께 주행의 임자가 된다.
            self.mapping_active = True
        self._events.publish("slam.started", source="navigation_manager", data={"by": source})

    def stop_mapping(self, source: str = "api") -> None:
        self.mapping_active = False
        self._events.publish("slam.stopped", source="navigation_manager", data={"by": source})

    def save_map(self, name: str = "rosy_map", source: str = "api") -> str:
        executor = self._require_executor()
        if not self.mapping_active:
            raise NavigationError("VALIDATION_ERROR", "no active mapping session")
        map_id = executor.save_map(name)
        self._state.set_map_id(map_id)
        self._events.publish("map.saved", source="navigation_manager", data={"map_id": map_id})
        return map_id

    def reset_mapping(self, source: str = "api") -> None:
        # save_map 과 같은 순서다: 능력 답변이 세션 답변보다 먼저 온다.
        # 뒤집으면 실행기가 없는 경우가 400 으로 나가 CAP-003 을 어긴다.
        executor = self._require_executor()
        if not self.mapping_active:
            raise NavigationError("VALIDATION_ERROR", "no active mapping session")
        executor.reset_mapping()
        # 도달 불가 — 위 두 가드가 모두 먼저 raise 하고, 브리지의 reset_mapping
        # 도 아직 항상 raise 한다. 실물 slam_toolbox Reset 이 붙을 때 리셋이
        # 무엇을 발행할지 함께 정한다 (D-32, follow-up 1). 그때까지 지우지 않는다.
        self._events.publish("slam.started", source="navigation_manager",
                             data={"by": source, "reset": True})

    def cancel(self, source: str = "api", close_session: bool = True,
               session: Optional[int] = None,
               correlation_id: Optional[str] = None, *, run_id: UUID | None = None,
               expected_boot_id: UUID | None = None, receipt_sink=None) -> bool:
        """Cancel only the matching run/session/correlation; True iff sent.

        Moving sessions cancel even from an idle facade state (a preempted
        abort may leave a live backend goal). SWM-004 close_session=False
        preserves the session so fresh references can resume it. A plain
        cancel also revokes reservation-only admission, without a backend run.
        """
        with self._lock:
            closed_receipt = None
            if expected_boot_id is not None and (
                    self.native.current is None or self.native.current.phase == "TERMINAL"
                    or self.native.current.boot_id != expected_boot_id):
                return False
            if run_id is not None and (self.native.current is None
                                       or self.native.current.run_id != run_id):
                return False
            if session is not None and self._moving_session != session:
                return False
            if correlation_id is not None and (
                    self._active_correlation_id != correlation_id
                    or self._nav_state in _IDLE_STATES):
                return False
            if self._admitting is not None and run_id is None and session is None and correlation_id is None:
                self._admitting = None
                self._native_mutate(self._advance_generation)
            session = self._moving_session
            closed = close_session and session is not None
            if close_session:
                self._moving_session = None
            if self._nav_state in _IDLE_STATES and session is None:
                return False
            self._execution('cancel')
            if self.executor is not None:
                self.executor.cancel_goal()
            active = self.native.current
            if active is not None and active.phase != "TERMINAL":
                result = "EXPIRED" if source == "goal_lease" else "FAILED" if source == "stuck_detector" else "CANCELED"
                reason = "LEASE_EXPIRED" if source == "goal_lease" else "STUCK" if source == "stuck_detector" else "SAFETY_STOP" if source.startswith("safety") else "CANCELED"
                closed_receipt = self._native_mutate(self.native.update, active.run_id, phase="TERMINAL", result=result, reason=reason)
                if receipt_sink is not None:
                    receipt_sink(closed_receipt)
            self._lease = None
            self._set_state(NavigationState.CANCELED)
            correlation_id = self._active_correlation_id
            self._active_correlation_id = None
            # 다음 목표는 새 기준점에서 시작한다. 남겨 두면 이미 만료된
            # 기준으로 곧장 다시 stuck 판정이 나 취소-재목표를 반복한다.
            self._last_progress_pos = None
            self._last_progress_ts = self.clock()
        self._events.publish("nav.canceled", source="navigation_manager",
                             data={"source": source, "correlation_id": correlation_id,
                                   **({"run_id": str(closed_receipt.run_id),
                                       "boot_id": str(closed_receipt.boot_id)}
                                      if closed_receipt is not None else {})})
        if closed:
            self._notify_session_closed(source)
        return True

    def _notify_session_closed(self, source: str) -> None:
        listener = self.session_closed_listener
        if listener is None:
            return
        try:
            listener(source)
        except Exception:
            # 임자의 실패가 취소 경로를 막으면 안 된다.
            pass

    def on_goal_accepted(self, *, native_run_id: UUID | None = None) -> None:
        with self._lock:
            if not self._execution('callback', native_run_id): return
            if native_run_id is not None:
                active = self.native.current
                if active is None or active.run_id != native_run_id or active.phase == "TERMINAL":
                    return
                self._native_mutate(self.native.update, native_run_id, phase="RUNNING")
            self._set_state(NavigationState.NAVIGATING)
            if self._moving_session is not None and self._last_progress_pos is not None:
                # SWM-002 는 NAV-006 이 그대로 적용된다고 못박았다. 0.5 초마다
                # 기준점을 초기화하면 30 초 무진척 조건은 영원히 성립하지 않고,
                # 문틀에 낀 팔로워가 아무 신호 없이 계속 밀어붙인다.
                return
            self._last_progress_pos = None
            self._last_progress_ts = self.clock()

    def on_result(self, succeeded: bool, error: Optional[str] = None, *,
                  correlation_id: str | None = None,
                  native_run_id: UUID | None = None) -> None:
        closed_receipt = None
        with self._lock:
            if not self._execution('callback', native_run_id): return
            if native_run_id is not None:
                active = self.native.current
                if active is None or active.run_id != native_run_id or active.phase == "TERMINAL":
                    return
                closed_receipt = self._native_mutate(self.native.update,
                    native_run_id, phase="TERMINAL",
                    result="SUCCEEDED" if succeeded else "FAILED",
                    reason=None if succeeded else "BACKEND_REJECTED" if error == "REJECTED" else "BACKEND_ERROR")
                self._lease = None
            self._set_state(NavigationState.ARRIVED if succeeded
                            else NavigationState.FAILED)
            if correlation_id == self._active_correlation_id:
                self._active_correlation_id = None
        if succeeded:
            self._events.publish("nav.completed", source="navigation_manager",
                                 data={"correlation_id": correlation_id,
                                       **({"run_id": str(closed_receipt.run_id),
                                           "boot_id": str(closed_receipt.boot_id)}
                                          if closed_receipt is not None else {})})
        else:
            self._events.publish("nav.failed", severity="error", source="navigation_manager",
                                 data={"error_code": error or "UNKNOWN",
                                       "correlation_id": correlation_id,
                                       **({"run_id": str(closed_receipt.run_id),
                                           "boot_id": str(closed_receipt.boot_id)}
                                          if closed_receipt is not None else {})})

    def on_backend_unknown(self, native_run_id: UUID) -> None:
        with self._lock:
            current = self.native.current
            if current is not None and current.run_id == native_run_id:
                self._native_mutate(self.native.update, native_run_id, phase=current.phase,
                                   reason="BACKEND_RESULT_UNKNOWN")

    def capture_native_operation(self, run_id: UUID | None = None): return self.native.capture(self._lock, run_id)

    native_readback = native_readback
    with_terminal_navigation = with_terminal_navigation

    def on_correlated_result(self, succeeded: bool, *,
                             correlation_id: str,
                             error: Optional[str] = None) -> None:
        """Publish a canceled goal result without changing the current nav state."""
        if succeeded:
            self._events.publish(
                "nav.completed", source="navigation_manager",
                data={"correlation_id": correlation_id})
        else:
            self._events.publish(
                "nav.failed", severity="error", source="navigation_manager",
                data={"error_code": error or "CANCELED",
                      "correlation_id": correlation_id})

    def on_pose_progress(self, x: float, y: float) -> None:
        """NAV-006 stuck: NAVIGATING 중 진척 없으면 자동 취소."""
        if self._nav_state is not NavigationState.NAVIGATING:
            return
        now = self.clock()
        if self._last_progress_pos is not None:
            dist = math.hypot(x - self._last_progress_pos[0], y - self._last_progress_pos[1])
            if dist >= self._stuck_min_progress:
                self._last_progress_pos = (x, y)
                self._last_progress_ts = now
                return
        else:
            self._last_progress_pos = (x, y)
            self._last_progress_ts = now
            return
        if now - self._last_progress_ts > self._stuck_timeout:
            # 원인을 먼저 싣는다. 취소가 세션 임자에게 알리고 그쪽도 이벤트를
            # 내므로, 순서를 바꾸면 감사 로그에 결과가 원인보다 앞선다.
            self._events.publish("nav.stuck", severity="error", source="navigation_manager",
                                 data={"timeout_s": self._stuck_timeout})
            self.cancel(source="stuck_detector")
            # NAV-006 자동 재시도 금지는 위의 cancel 이 세션을 닫고 임자에게
            # 알리는 것으로 지켜진다 — 알리지 않으면 0.5 초 뒤 스트림이 목표를
            # 다시 밀어넣고, 그것이 곧 자동 재시도다.
