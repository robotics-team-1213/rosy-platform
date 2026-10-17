"""Private measured-pack ingress, not an ordinary BatteryState adapter.

decode returns (EnergyReading, original_source_now_ns). It runs outside CORE's
writer boundary. Actual vendor hardware/calibration must be accepted separately.
"""
from threading import RLock


class PackEnergyIngress:
    def __init__(self, fence, context):
        self._fence, self._context = fence, context
        self._lock = RLock()

    def receive(self, provider, decode):
        fence, context = self._fence, self._context
        ledger, modes = fence._ledger, fence._command._modes
        with self._lock:
            token = object()
            with modes._lock, ledger._lock:
                parent = ledger._current
                if (fence._native_energy is not context or fence._energy_owner is not context
                        or context.clock is not ledger._clock
                        or not context.begin(token)):
                    return False
            sample = read = None
            try:
                read = context.source.begin(provider)
                if read is not None:
                    reading, source_now = decode()
                    sample = context.source.complete(read, provider, reading, source_now_ns=source_now)
            except Exception:
                sample = None
            finally:
                if sample is None:
                    context.source.abort(read)
                # No source lock is held when entering the existing boundary.
                with modes._lock, ledger._lock:
                    if (fence._native_energy is context and fence._energy_owner is context
                            and context.clock is ledger._clock):
                        accepted = context.finish(token, sample, now=ledger._now(),
                                                  parent=parent, fence=fence)
                    else:
                        fence.request_stop(parent)  # Never redirects to a replacement parent/source.
                        accepted = False
            return accepted
