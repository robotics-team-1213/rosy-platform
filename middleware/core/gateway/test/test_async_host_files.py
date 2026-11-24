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


def test_face_inputs_offload_retries_after_error_without_clobbering_newer_write():
    from types import SimpleNamespace
    from core.bridge.expression_policy import Expression
    from core.bridge.ros_bridge_helpers import RosBridgeHelpersMixin
    from core_common.protocol.schemas import HealthState

    writer = AsyncHostFileWriter()
    first_started = threading.Event()
    release_first = threading.Event()
    calls = []
    warnings = []

    def fake_write(_svc, content):
        calls.append(content["face"])
        if content["face"] == "hello":
            first_started.set()
            release_first.wait(timeout=1.0)
            raise OSError("disk hiccup")

    class HelperHost(RosBridgeHelpersMixin):
        pass

    helper = HelperHost()
    helper._file_writer = writer
    helper._node = SimpleNamespace(get_logger=lambda: SimpleNamespace(warning=warnings.append))
    helper.diagnostics = SimpleNamespace(summary_health=lambda: HealthState.OK)
    helper._face_inputs_last = None
    helper._face_inputs_at = None
    helper._face_inputs_failed = False
    helper._face_inputs_lock = threading.Lock()
    helper._face_inputs_gen = 0
    helper._expression_intent = Expression(None)
    helper._face_desired = "hello"
    helper._svc = SimpleNamespace(
        state=SimpleNamespace(snapshot=lambda: SimpleNamespace(
            mode=SimpleNamespace(value="IDLE"),
            battery=SimpleNamespace(percent=90.0),
            robot_id="rosy_45",
            navigation=SimpleNamespace(value="IDLE"),
            safety=SimpleNamespace(estop=False),
            charge=SimpleNamespace(charging=False),
        )),
        power=SimpleNamespace(info_hold_s=5.0),
        vision=SimpleNamespace(status=lambda now: SimpleNamespace(
            camera_ok=True, usable=True, reason=None, exposure=None, gain=None,
            fps=8.0, fresh=True, stale_after_s=2.0, updated_at=now)),
        person_request=SimpleNamespace(view=lambda: None),
        host_files=SimpleNamespace(write_face_inputs=fake_write),
    )
    status = SimpleNamespace(mode=SimpleNamespace(value="NORMAL"), info_visible=False)

    # First submission blocks in writer, then raises after a second newer submission bumps gen.
    helper._maybe_write_face_inputs(status, now=1.0)
    assert first_started.wait(timeout=0.5)
    helper._face_desired = "happy"
    helper._maybe_write_face_inputs(status, now=2.1)
    release_first.set()

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and "happy" not in calls:
        time.sleep(0.005)
    writer.close()
    assert calls == ["hello", "happy"]
    # Older failure must not wipe _face_inputs_last set by the newer "happy" submission.
    assert helper._face_inputs_last is not None
    assert len(warnings) == 1
