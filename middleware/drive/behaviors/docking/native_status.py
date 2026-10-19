"""Native transport evidence captured while the docking manager holds its lock."""
from core_common.protocol.schemas import DockState


def owner_snapshot(native, lock, *, wait):
    if not lock.acquire(blocking=wait):
        return None
    try:
        return native.owner()
    finally:
        lock.release()


def readback(native, executor, state, run_id):
    snapshot = getattr(executor, 'native_transport_snapshot', None)
    before = snapshot() if callable(snapshot) else None
    after = snapshot() if callable(snapshot) else None
    stable = before is not None and before == after
    return native.readback(
        run_id, pending_submission=before[1] if before else True,
        actuating_callback=before[2] if before else True,
        lease_active=state in (DockState.DOCKING, DockState.UNDOCKING),
        transport_generation=before[0] if stable else None)
