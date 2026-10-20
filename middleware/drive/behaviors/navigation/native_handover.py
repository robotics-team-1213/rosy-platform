"""Locked native transport evidence and passive handover of a completed navigation owner."""
from uuid import UUID

from core_common.protocol.schemas import NavigationState


def native_readback(self, run_id: UUID | None = None) -> dict:
    with self._lock:
        snapshot = getattr(self.executor, 'native_transport_snapshot', None)
        before = snapshot() if snapshot is not None else None
        after = snapshot() if snapshot is not None else None
        stable = before is not None and before == after
        return self.native.readback(
            run_id, admitting=self._admitting is not None,
            pending_submission=before[1] if before else True,
            actuating_callback=before[2] if before else True,
            lease_active=self._lease is not None,
            transport_generation=before[0] if stable else None)


def with_terminal_navigation(self, expected_boot_id: str, handover, *, expected_run_id=None,
                             expected_owner_generation=None, expected_correlation_id=None, admission=None) -> bool:
    """Run a no-motion callback while new goal/admission cannot replace the proved owner.

    The backend is already finished. This function never cancels a goal and cannot supply
    missing transport evidence. CORE alone clears its candidate and conditionally changes mode.
    """
    with self._lock:
        if admission is not None and admission() is not True:
            return False
        body = native_readback(self)
        operation, owner, proof = body.get('operation'), body['owner'], body.get('quiescence')
        if (self._nav_state is not NavigationState.ARRIVED or self._admitting is not None
                or self._moving_session is not None or self.mapping_active or self._lease is not None
                or self._active_correlation_id is not None
                or operation is None or operation['phase'] != 'TERMINAL' or operation['result'] != 'SUCCEEDED'
                or operation['kind'] not in ('navigate', 'home')
                or operation['boot_id'] != expected_boot_id or owner['boot_id'] != expected_boot_id
                or expected_run_id is not None and operation['run_id'] != str(expected_run_id)
                or expected_owner_generation is not None and owner['owner_generation'] != expected_owner_generation
                or expected_correlation_id is not None and operation['correlation_id'] != expected_correlation_id
                or owner['owner_run_id'] is not None or owner != self.native.owner()
                or proof is None or proof['quiescent'] is not True
                or proof['boot_id'] != expected_boot_id or proof['requested_run_id'] != operation['run_id']
                or proof['owner_generation'] != owner['owner_generation']
                or type(proof['transport_generation']) is not int or proof['transport_generation'] < 0):
            return False
        return handover() is True
