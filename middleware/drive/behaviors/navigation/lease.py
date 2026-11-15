"""D-550 10 goal lease renew/expire, split out of manager.py (size rule). Bound onto NavigationManager."""
from __future__ import annotations


def renew_goal_lease(self, correlation_id: str, ttl_s: float, owner: str | None = None) -> None:
    """D-550 10: renew only an unexpired lease for this exact goal and sender."""
    from .manager import _IDLE_STATES, NavigationError, _check_lease_ttl
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
