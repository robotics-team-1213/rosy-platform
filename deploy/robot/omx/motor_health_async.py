"""Coalescing snapshot writer and ordered FIFO JSONL writer for 5 Hz MotorHealth publishing."""
from __future__ import annotations

from collections import deque
import threading
import time

_FIELDS = (
    "joint", "id", "command_raw", "present_raw", "error_deg", "pwm", "pwm_limit", "pwm_utilization",
    "temperature_c", "temperature_limit_c", "voltage_v", "warnings", "hardware_error", "torque_enabled", "fault",
)


def snapshot_row(owner_id, session_id, status, stop_reasons, terminal_at, motions) -> dict:
    """Build an immutable ROSY motor-health.v1 snapshot dict copied safely from live motion state."""
    motors, stamps = [], []
    for state in motions.values():
        last = state["last"]
        if last is None:
            continue
        stamp = state["observed_at"]
        stamps.append(stamp)
        for motor in last["motors"]:
            motors.append({
                **{key: list(motor[key]) if isinstance(motor[key], (list, tuple)) else motor[key] for key in _FIELDS},
                "group": last["arm"],
                "min_voltage_v": motor["min_voltage_raw"] / 10,
                "max_voltage_v": motor["max_voltage_raw"] / 10,
                "observed_at": stamp,
            })
    row = dict(
        schema_version="rosy.motor-health.v1",
        owner_id=owner_id,
        session_id=session_id,
        status=status,
        observed_at=max(stamps) if stamps else terminal_at or time.time(),
        expected_motor_count=sum(len(state["limits"]) for state in motions.values()),
        motors=motors,
        stop_reasons=list(stop_reasons),
    )
    if terminal_at is not None:
        row["terminal_at"] = terminal_at
    return row


class AsyncSnapshotPublisher:
    """Single-thread coalescing atomic snapshot writer (non-blocking submit, flush on admit/fault/end)."""

    def __init__(self, writer):
        self._writer = writer
        self._cv = threading.Condition()
        self._pending = None
        self._closed = False
        self._in_flight = False
        self._last_error = None
        self._thread = threading.Thread(target=self._run, name="motor-health-publish", daemon=True)
        self._thread.start()

    def submit(self, path, row) -> None:
        with self._cv:
            if self._closed:
                return
            self._pending = (path, row)
            self._cv.notify_all()

    def pop_error(self):
        with self._cv:
            err = self._last_error
            self._last_error = None
            return err

    def flush(self, *, close: bool = False, timeout: float = 2.0) -> None:
        deadline = time.monotonic() + timeout
        with self._cv:
            if close:
                self._closed = True
            self._cv.notify_all()
            while (self._pending is not None or self._in_flight) and time.monotonic() < deadline:
                rem = deadline - time.monotonic()
                if rem <= 0:
                    break
                self._cv.wait(rem)
        if close and self._thread.is_alive():
            self._thread.join(0.5)

    def _run(self) -> None:
        while True:
            with self._cv:
                while self._pending is None and not self._closed:
                    self._cv.wait()
                if self._pending is None and self._closed:
                    return
                item = self._pending
                self._pending = None
                self._in_flight = True
            try:
                self._writer(*item)
            except Exception as exc:  # noqa: BLE001 - captured and surfaced via pop_error() on sample()
                with self._cv:
                    self._last_error = exc
            finally:
                with self._cv:
                    self._in_flight = False
                    self._cv.notify_all()


def _append_jsonl_line(path, line: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()


class AsyncJsonlWriter:
    """Single-thread FIFO JSONL writer (no coalescing; preserves every audit row in order)."""

    def __init__(self, writer=None):
        self._writer = _append_jsonl_line if writer is None else writer
        self._cv = threading.Condition()
        self._queue = deque()
        self._closed = False
        self._in_flight = False
        self._last_error = None
        self._thread = threading.Thread(target=self._run, name="motor-health-emit", daemon=True)
        self._thread.start()

    def submit(self, path, line: str) -> None:
        with self._cv:
            if self._closed:
                return
            self._queue.append((path, line))
            self._cv.notify_all()

    def pop_error(self):
        with self._cv:
            err = self._last_error
            self._last_error = None
            return err

    def flush(self, *, close: bool = False, timeout: float = 2.0) -> None:
        deadline = time.monotonic() + timeout
        with self._cv:
            if close:
                self._closed = True
            self._cv.notify_all()
            while (self._queue or self._in_flight) and time.monotonic() < deadline:
                rem = deadline - time.monotonic()
                if rem <= 0:
                    break
                self._cv.wait(rem)
        if close and self._thread.is_alive():
            self._thread.join(0.5)

    def _run(self) -> None:
        while True:
            with self._cv:
                while not self._queue and not self._closed:
                    self._cv.wait()
                if not self._queue and self._closed:
                    return
                item = self._queue.popleft()
                self._in_flight = True
            try:
                self._writer(*item)
            except Exception as exc:  # noqa: BLE001 - captured and surfaced via pop_error() on sample()
                with self._cv:
                    self._last_error = exc
            finally:
                with self._cv:
                    self._in_flight = False
                    self._cv.notify_all()


def public_reason(exc):
    if isinstance(exc, KeyboardInterrupt):
        return 'operator interruption'
    if not isinstance(exc, ValueError):
        return 'control failure'
    text = str(exc).lower()
    if 'temperature' in text and '>= configured limit' in text:
        return 'temperature limit'
    if 'voltage' in text and 'outside configured limits' in text:
        return 'voltage limit'
    for needle, reason in (('hardware error', 'hardware error'), ('following error', 'following error'),
                           ('overload risk', 'overload risk'), ('stale', 'stale telemetry'),
                           ('alignment deadline', 'alignment deadline')):
        if needle in text:
            return reason
    return 'control failure'
