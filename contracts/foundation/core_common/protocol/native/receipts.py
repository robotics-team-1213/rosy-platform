"""Small, ROS-free bookkeeping for a native owner's accepted operations.

Callers hold their existing owner lock while mutating or reading this ledger.
"""

from collections import deque
from datetime import datetime, timezone
from uuid import UUID, uuid4

from core_common.protocol.native.operation import NativeOperation


BOOT_ID = uuid4()


class NativeReceipts:
    def __init__(self) -> None:
        self.current: NativeOperation | None = None
        self.terminal: deque[NativeOperation] = deque(maxlen=32)
        self.generation = 0

    def expect(self, boot_id: UUID | None, generation: int | None) -> None:
        if (boot_id is None) != (generation is None):
            raise ValueError("VALIDATION_ERROR")
        if boot_id is not None and (boot_id != BOOT_ID or generation != self.generation):
            raise ValueError("OWNER_GENERATION_CHANGED")

    def admit(self, kind: str, correlation_id: str | None = None) -> NativeOperation:
        if self.current is not None and self.current.phase != "TERMINAL":
            raise ValueError("native owner still has an unresolved run")
        operation = NativeOperation(run_id=uuid4(), boot_id=BOOT_ID, kind=kind,
                                    correlation_id=correlation_id, phase="SUBMITTED")
        self.current = operation
        self.generation += 1
        return operation

    def update(self, run_id: UUID, *, phase: str, result: str | None = None,
               reason: str | None = None) -> NativeOperation | None:
        current = self.current
        if current is None or current.run_id != run_id or current.phase == "TERMINAL":
            return None
        updated = NativeOperation.model_validate({**current.model_dump(),
                                                  "phase": phase, "result": result, "reason": reason})
        self.current = updated
        self.generation += 1
        if phase == "TERMINAL":
            self.terminal.append(updated)
        return updated

    def lookup(self, run_id: UUID | None = None) -> NativeOperation | None:
        if run_id is None:
            return self.current or (self.terminal[-1] if self.terminal else None)
        if self.current is not None and self.current.run_id == run_id:
            return self.current
        return next((op for op in reversed(self.terminal) if op.run_id == run_id), None)

    def owner(self) -> dict:
        return {"boot_id": str(BOOT_ID), "owner_generation": self.generation,
                "owner_run_id": str(self.current.run_id) if self.current and self.current.phase != "TERMINAL" else None}

    def capture(self, lock, run_id: UUID | None = None) -> NativeOperation | None:
        """Copy only the locked ledger; optional safety evidence must never wait."""
        if not lock.acquire(blocking=False):
            raise BlockingIOError("native owner is busy")
        try:
            operation = self.lookup(run_id)
            return operation if (run_id is not None or operation is not None
                                 and operation.phase != "TERMINAL") else None
        finally:
            lock.release()

    def readback(self, run_id: UUID | None = None, *, admitting: bool = False,
                 pending_submission: bool = False, actuating_callback: bool = False,
                 lease_active: bool = False,
                 transport_generation: int | None = None) -> dict:
        operation = self.lookup(run_id)
        proof = None
        if operation is not None and transport_generation is not None:
            owner = self.owner()
            proof = {
                "boot_id": str(BOOT_ID), "owner_run_id": owner["owner_run_id"],
                "requested_run_id": str(operation.run_id),
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "owner_generation": self.generation,
                "transport_generation": transport_generation,
                "admitting": admitting, "pending_submission": pending_submission,
                "actuating_callback": actuating_callback, "lease_active": lease_active,
                "quiescent": operation.phase == "TERMINAL" and owner["owner_run_id"] is None
                and not (admitting or pending_submission or actuating_callback or lease_active),
            }
        return {"owner": self.owner(),
                "operation": operation.model_dump(mode="json") if operation else None,
                "lookup": "FOUND" if operation else "UNKNOWN", "quiescence": proof}
