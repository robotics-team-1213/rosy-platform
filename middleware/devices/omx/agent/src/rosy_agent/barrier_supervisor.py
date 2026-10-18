"""Barrier gate, barrier timeouts and coordinator liveness for one OMX owner (D-780 §3, §4).

``BarrierSupervisor`` answers the tri-state phase gate (``True`` / ``PHASE_WAIT`` / ``False``).
The cell owner builds it only when it has coordinator peers; without it the owner keeps
today's always-allow gate and no barrier code runs.
"""

from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from typing import Any, Callable

from core_common.protocol.cell_transfer import FleetCellTransferGrant
from core_common.protocol.schemas import LocalStopRequest, StopRequestSource
from core_common.protocol.workcell_barrier import BarrierState, CoordinatorStopReason

from omx_adapter.action_store import ActionStore, InvalidActionTransition
from omx_adapter.phase_gate import PHASE_WAIT

from .barrier_journal import BarrierJournal

#: Lower bound for coordinator liveness: well above the 0.25 s UDS round-trip budget (D-780 §4).
MIN_COORDINATOR_LIVENESS_S = 0.5
_HOLDABLE = frozenset({"SUBMITTING", "ACCEPTED", "RUNNING", "CANCEL_REQUESTED", "UNKNOWN"})
_IN_FLIGHT_PHASE = frozenset({"SUBMITTING", "ACCEPTED", "RUNNING", "CANCEL_REQUESTED"})
_TERMINAL = frozenset({"SUCCEEDED", "FAILED", "CANCELED", "HOLD", "UNKNOWN"})
#: Action reason when the stop latch or authority fence closed on an Action waiting at a barrier.
STOP_FENCED_AT_BARRIER = "STOP_FENCED_AT_BARRIER"


def make_coordinator_hold(stop, store: ActionStore, *, cancel_active: Callable[[], object],
                          now: Callable[[], datetime] | None = None):
    """Owner HOLD on the coordinator's behalf: COORDINATOR stop latch plus Action HOLD."""
    clock = now or (lambda: datetime.now(timezone.utc))

    def hold_action(grant: FleetCellTransferGrant, reason: str) -> None:
        action = store.get_action(grant.action_id)
        if action is not None and action["state"] in _HOLDABLE:
            try:
                store.hold_action(grant.action_id, grant.attempt_id, reason=reason)
            except InvalidActionTransition:
                pass

    def hold(grant: FleetCellTransferGrant, reason: CoordinatorStopReason) -> None:
        reason = CoordinatorStopReason(reason).value
        phases = store.action_phases(grant.action_id, attempt_id=grant.attempt_id)
        if not any(phase["state"] in _IN_FLIGHT_PHASE for phase in phases):
            hold_action(grant, reason)  # no goal to cancel: keep the specific reason on the Action
        request = LocalStopRequest(
            workcell_id=grant.workcell_id, instance_id=grant.instance_id,
            authority_epoch=grant.authority_epoch, dispatch_generation=grant.dispatch_generation,
            requested_at=clock(), reason=reason)
        try:
            stop.trip(request, source=StopRequestSource.COORDINATOR, cancel_active=cancel_active)
        finally:
            hold_action(grant, reason)
    return hold


class BarrierSupervisor:
    """Per-owner barrier gate and tick; reads the journal, never waits inside a lock."""

    def __init__(self, journal: BarrierJournal, store: ActionStore, *,
                 coordinator_liveness_s: float,
                 hold_owner: Callable[[FleetCellTransferGrant, CoordinatorStopReason], None],
                 fence_current: Callable[[int, int], bool] | None = None,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        if (isinstance(coordinator_liveness_s, bool)
                or not isinstance(coordinator_liveness_s, (int, float))
                or not math.isfinite(coordinator_liveness_s)
                or coordinator_liveness_s < MIN_COORDINATOR_LIVENESS_S):
            raise ValueError("coordinator_liveness_s must be finite and at least 0.5 s")
        if not callable(hold_owner) or not callable(monotonic):
            raise ValueError("owner hold and monotonic clock providers are required")
        self.journal = journal
        self.store = store
        self.coordinator_liveness_s = float(coordinator_liveness_s)
        self.hold_owner = hold_owner
        # Stop latch plus Fleet fence of the grant's generation; None means always current.
        self.fence_current = fence_current or (lambda _epoch, _generation: True)
        self.monotonic = monotonic
        self._last_contact: float | None = None

    def contact(self) -> None:
        """Any request from an authenticated coordinator peer counts as contact."""
        self._last_contact = self.monotonic()

    @staticmethod
    def _barriers(grant: FleetCellTransferGrant):
        return getattr(grant, "cell_transfer", None) and grant.cell_transfer.barriers or ()

    def phase_gate(self, grant: FleetCellTransferGrant, phase_id: str):
        """``True`` to submit, ``PHASE_WAIT`` to record arrival and return, ``False`` to deny."""
        barrier = next((item for item in self._barriers(grant) if item.gated_phase == phase_id), None)
        if barrier is None:
            return True
        row = self.journal.arrive(grant, barrier)
        if row["state"] == BarrierState.RELEASED.value:
            return True
        return PHASE_WAIT if row["state"] == BarrierState.WAITING.value else False

    def first_phase_released(self, grant: FleetCellTransferGrant) -> bool:
        """A before-first-phase barrier is released and no phase was submitted yet."""
        first = next((item for item in self._barriers(grant) if item.before_first_phase), None)
        if first is None:
            return False
        row = self.journal.rows(grant.action_id, grant.attempt_id).get(first.barrier_id)
        return (row is not None and row["state"] == BarrierState.RELEASED.value
                and not self.store.action_phases(grant.action_id, attempt_id=grant.attempt_id))

    def coupling_now(self, grant: FleetCellTransferGrant, rows: dict[str, Any]) -> tuple[str, float | None]:
        """Coupling after the last released barrier, and when it was released."""
        coupling, released = "independent", None
        for barrier in self._barriers(grant):
            row = rows.get(barrier.barrier_id)
            if row is None or row["state"] != BarrierState.RELEASED.value:
                break
            coupling, released = barrier.coupling_after, row["released_monotonic"]
        return coupling, released

    def fence_open(self, grant: FleetCellTransferGrant) -> bool:
        try:
            return self.fence_current(grant.authority_epoch, grant.dispatch_generation) is True
        except Exception:
            return False

    def _end_wait(self, grant: FleetCellTransferGrant, barrier_id: str, reason: str,
                  *, hold_with_stop: bool) -> str:
        """End an Action waiting at a barrier: FAILED if nothing moved, otherwise HOLD.

        Expiry and the unmoved FAILED are one journal transaction; if that fails the Action is
        held instead, so a waiting arm never stays SUBMITTING with its partner unaware."""
        try:
            if self.journal.expire(grant.action_id, grant.attempt_id, barrier_id,
                                   fail_unmoved_reason=reason):
                return "FAILED"
        except Exception:
            pass
        if hold_with_stop:
            self.hold_owner(grant, CoordinatorStopReason(reason))
        else:
            action = self.store.get_action(grant.action_id)
            if action is not None and action["state"] in _HOLDABLE:
                try:
                    self.store.hold_action(grant.action_id, grant.attempt_id, reason=reason)
                except InvalidActionTransition:
                    pass
        return "HOLD"

    def end_fenced_waits(self) -> list[str]:
        """Stop sweep: every Action waiting at a barrier whose fence closed ends at once (FAILED
        if nothing moved, else HOLD), so the partner reads a failure instead of a silent wait.
        ``cancel_unresolved`` skips SUBMITTING Actions, which is where a first-phase wait sits."""
        ended = []
        for row in self.journal.waiting():
            action = self.store.get_action(row["action_id"])
            payload = (action or {}).get("request", {}).get("payload")
            if action is None or action["state"] in _TERMINAL or not isinstance(payload, dict):
                continue
            grant = FleetCellTransferGrant.model_validate(payload)
            if not self.fence_open(grant):
                self._end_wait(grant, row["barrier_id"], STOP_FENCED_AT_BARRIER, hold_with_stop=False)
                ended.append(grant.action_id)
        return ended

    def tick(self, grant: FleetCellTransferGrant) -> str | None:
        """Owner-side decisions: ``FAILED``/``HOLD`` when this tick ended the Action, else None."""
        barriers = self._barriers(grant)
        if not barriers:
            return None
        action = self.store.get_action(grant.action_id)
        if action is None or action["state"] in _TERMINAL:
            return None
        rows = self.journal.rows(grant.action_id, grant.attempt_id)
        now = self.monotonic()
        fence_open = self.fence_open(grant)
        for barrier in barriers:
            row = rows.get(barrier.barrier_id)
            if row is None or row["state"] != BarrierState.WAITING.value:
                continue
            if not fence_open:  # stop latch or authority closed while waiting
                return self._end_wait(grant, barrier.barrier_id, STOP_FENCED_AT_BARRIER, hold_with_stop=False)
            stale = row["boot_id"] != self.journal.boot_id  # earlier boot: its clock is not ours
            if stale or now - row["arrived_monotonic"] > barrier.max_wait_s:
                return self._end_wait(grant, barrier.barrier_id, CoordinatorStopReason.BARRIER_TIMEOUT.value,
                                      hold_with_stop=True)
        coupling, released = self.coupling_now(grant, rows)
        if coupling == "tight":
            last = max(value for value in (self._last_contact, released) if value is not None)
            if now - last > self.coordinator_liveness_s:
                self.hold_owner(grant, CoordinatorStopReason.PARTNER_LINK_LOST)
                return "HOLD"
        return None


__all__ = ["BarrierSupervisor", "MIN_COORDINATOR_LIVENESS_S", "STOP_FENCED_AT_BARRIER", "make_coordinator_hold"]
