"""Tests for AsyncHostFileWriter non-blocking coalescing and shutdown."""

from __future__ import annotations

import threading
import time

from core.system.host_files import AsyncHostFileWriter


def test_async_host_file_writer_coalesces_latest_without_blocking():
    writer = AsyncHostFileWriter()
    started = threading.Event()
    release = threading.Event()
    seen = []

    def slow_first():
        started.set()
        release.wait(timeout=1.0)
        seen.append("first")

    t0 = time.monotonic()
    writer.submit("status_inputs", slow_first)
    assert started.wait(timeout=0.5)
    # Submitting newer values while the first write is blocked must return immediately and coalesce.
    writer.submit("status_inputs", lambda: seen.append("stale"))
    writer.submit("status_inputs", lambda: seen.append("latest"))
    writer.submit("face_inputs", lambda: seen.append("face"))
    elapsed = time.monotonic() - t0
    assert elapsed < 0.05

    release.set()
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and "face" not in seen:
        time.sleep(0.005)
    writer.close(timeout_s=1.0)
    assert "first" in seen
    assert "latest" in seen
    assert "face" in seen
    assert "stale" not in seen


def test_async_host_file_writer_reports_error_then_recovers():
    writer = AsyncHostFileWriter()
    events = []
    done = threading.Event()

    def boom():
        raise OSError("disk full")

    writer.submit("status_inputs", boom, on_error=lambda exc: (events.append(("err", str(exc))), done.set()))
    assert done.wait(timeout=1.0)
    ok_done = threading.Event()
    writer.submit("status_inputs", lambda: events.append(("write", "ok")),
                  on_ok=lambda: (events.append(("ok", "")), ok_done.set()))
    assert ok_done.wait(timeout=1.0)
    writer.close()
    assert events[0][0] == "err"
    assert ("ok", "") in events
