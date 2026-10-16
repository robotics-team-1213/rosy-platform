"""The 'wait' value of the tri-state phase gate (D-780 §3): allow ``True`` / wait / deny.

A gate answers ``PHASE_WAIT`` when a named barrier holds the next phase back; the runner then
submits nothing and returns. ``PHASE_WAIT`` refuses truth testing, so ``gate and other_gate``
fails loudly instead of reading as allow. The barrier journal and supervisor that produce it
live with the owner composition (``rosy_agent.barrier_supervisor``).
"""


class _PhaseWait:
    """Singleton 'wait' decision of a phase gate; never truthy, never falsy."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self) -> bool:
        raise TypeError("PHASE_WAIT is neither allow nor deny; compare with `is`")

    def __repr__(self) -> str:
        return "PHASE_WAIT"


PHASE_WAIT = _PhaseWait()

__all__ = ["PHASE_WAIT"]
