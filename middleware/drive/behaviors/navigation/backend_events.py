"""Navigation state and receipt updates from the action backend."""
from typing import Optional
from uuid import UUID

from core_common.protocol.schemas import NavigationState

from .route import route_continue, route_progress_kept


def on_goal_accepted(self, *, native_run_id: UUID | None = None) -> None:
    with self._lock:
        if not self._execution('callback', native_run_id): return
        if native_run_id is not None:
            active = self.native.current
            if active is None or active.run_id != native_run_id or active.phase == "TERMINAL":
                return
            self._native_mutate(self.native.update, native_run_id, phase="RUNNING")
        self._set_state(NavigationState.NAVIGATING)
        if (self._moving_session is not None and self._last_progress_pos is not None
                or route_progress_kept(self)):
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
    sent = route_continue(self, succeeded, error, native_run_id)
    if sent is True:
        return  # a route leg ended and the next leg is out: still the same run
    if sent:  # the next leg could not be sent: the run fails, whatever the leg that just ended did
        succeeded, error = False, sent
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
