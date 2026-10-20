"""Test-only probes preserve the real readback and nonblocking lock results."""
import json
import sys
import threading
import traceback


def install_readback_probe(owner, motion, clock, monkeypatch):
    local, reports = threading.local(), []
    original_lock = motion._lock
    original_snapshot, original_ack, original_readback = motion.snapshot, owner.ack, owner.readback
    original_clear, clears = motion.clear, []

    def clear():
        clears.append(dict(at=clock(), callers=traceback.format_stack(limit=8)))
        del clears[:-4]
        return original_clear()

    def record(**values):
        steps = getattr(local, 'steps', None)
        if steps is not None:
            steps.append(values)

    class ObservedLock:
        def acquire(self, *args, **kwargs):
            result = original_lock.acquire(*args, **kwargs)
            record(motion_lock_acquired=result)
            if result and getattr(local, 'steps', None) is not None:
                sample = motion._latest
                record(motion_sample=None if sample is None else dict(sample[0], local_at=sample[1]),
                       local_now=motion.clock(), source_now=motion.source_clock(), max_age_s=motion.max_age_s)
            return result
        def release(self):
            return original_lock.release()
        def __enter__(self):
            self.acquire()
            return self
        def __exit__(self, *args):
            self.release()
        def locked(self):
            return original_lock.locked()

    def snapshot():
        result = original_snapshot()
        record(motion=None if result is None else {k: result[k] for k in ('captured_at', 'valid_until', 'odom_epoch')})
        return result

    def ack():
        try:
            result = original_ack()
            record(ack='accepted', captured_at=result.captured_at, valid_until=result.valid_until)
            return result
        except ValueError as exc:
            record(ack_error=str(exc))
            raise

    def readback():
        steps, began = [], clock()
        local.steps = steps
        try:
            result = original_readback()
            if owner.session is not None and not result.binding_valid:
                report = dict(began=began, finished=clock(), state=result.state,
                    reason=result.reason, captured_at=result.captured_at, valid_until=result.valid_until,
                    steps=steps, clears=list(clears))
                reports.append(report)
                print('STATION_READBACK_DIAGNOSTIC '+json.dumps(report), flush=True)
            return result
        finally:
            local.steps = None

    monkeypatch.setattr(motion, '_lock', ObservedLock())
    monkeypatch.setattr(motion, 'snapshot', snapshot)
    monkeypatch.setattr(motion, 'clear', clear)
    monkeypatch.setattr(owner, 'ack', ack)
    monkeypatch.setattr(owner, 'readback', readback)
    return reports


def install_hold_probe(motion, clock):
    """Observe the caught cause at HOLD entry without changing the real stop."""
    original = motion.stop_hold

    async def stop_hold(current, reason, **kwargs):
        error = sys.exception()
        if error is not None and reason in (
                'CHARGE_MOTION_READBACK_UNAVAILABLE', 'CHARGE_DEPARTURE_UNVERIFIED'):
            report = dict(session_id=current.session_id, reason=reason, clock=clock(),
                exception_type=type(error).__name__, exception=str(error),
                traceback=traceback.format_exception(error))
            for frame, _ in traceback.walk_tb(error.__traceback__):
                view = frame.f_locals.get('view') if frame.f_code.co_name == 'read_return' else None
                if isinstance(view, dict):
                    report['return_trip'] = {key: view.get(key) for key in ('state', 'reason', 'detail')}
            print('STATION_HOLD_DIAGNOSTIC '+json.dumps(report), flush=True)
        return await original(current, reason, **kwargs)

    motion.stop_hold = stop_hold
