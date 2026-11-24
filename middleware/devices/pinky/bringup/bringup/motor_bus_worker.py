"""Dedicated UART worker thread for Dynamixel bus I/O (zero ROS imports)."""

from __future__ import annotations

import math
import threading
import time
from typing import Any, Callable


class MotorBusWorker:
    """Serialize driver UART calls off the ROS callback executor."""

    def __init__(
        self,
        driver: Any,
        *,
        drive_enabled: bool,
        feedback_period_s: float = 1.0 / 30.0,
        health_step_period_s: float = 1.0,
        feedback_stale_s: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not feedback_period_s > 0:
            raise ValueError("feedback_period_s must be positive")
        if not health_step_period_s > 0:
            raise ValueError("health_step_period_s must be positive")
        stale = max(0.15, float(feedback_period_s) * 4.0) if feedback_stale_s is None else float(feedback_stale_s)
        if not stale > 0:
            raise ValueError("feedback_stale_s must be positive")
        self._driver = driver
        self._drive_enabled = bool(drive_enabled)
        self._feedback_period_s = float(feedback_period_s)
        self._health_step_period_s = float(health_step_period_s)
        self._feedback_stale_s = stale
        self._clock = clock

        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        self._cmd_seq = 0
        self._handled_seq = 0
        self._pending_cmd: tuple[float, float, int, bool] | None = None
        self._stop_pending = False
        self._last_cmd_ok = True
        self._last_stop_ok = True

        self._latest_feedback: tuple[float | None, float | None, int | None, int | None] = (None, None, None, None)
        self._last_feedback_ok_at: float | None = None
        self._health_rows: dict[int, dict[str, Any]] = {}
        self._health_idx = 0
        self._health_snapshot: list[dict[str, Any]] | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._wake.clear()
        self._thread = threading.Thread(target=self._run, name="bringup-uart-io", daemon=True)
        self._thread.start()

    def stop(self, timeout_s: float = 1.0) -> None:
        thread = self._thread
        self._stop_event.set()
        self._wake.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout_s)
        if thread is None or not thread.is_alive():
            self._thread = None

    def set_double_rpm(self, rpm_l: float, rpm_r: float) -> bool:
        try:
            velocities = [float(rpm_l), float(rpm_r)]
        except (TypeError, ValueError):
            return False
        max_rpm = float(self._driver.MAX_RPM)
        if any(not math.isfinite(v) or abs(v) > max_rpm for v in velocities):
            return False
        if not self._drive_enabled:
            return False
        is_stop = velocities[0] == 0.0 and velocities[1] == 0.0
        with self._lock:
            self._cmd_seq += 1
            self._pending_cmd = (velocities[0], velocities[1], self._cmd_seq, is_stop)
            if is_stop:
                self._stop_pending = True
                ok = self._last_stop_ok
            else:
                self._stop_pending = False
                ok = self._last_cmd_ok
        self._wake.set()
        return ok

    def read_feedback(self) -> tuple[float | None, float | None, int | None, int | None]:
        now = self._clock()
        with self._lock:
            fb = self._latest_feedback
            ok_at = self._last_feedback_ok_at
        if fb[0] is None or ok_at is None or (now - ok_at) > self._feedback_stale_s:
            return (None, None, None, None)
        return fb

    def consume_health(self) -> list[dict[str, Any]] | None:
        with self._lock:
            snap = self._health_snapshot
            self._health_snapshot = None
            return snap

    def _flush_pending_command(self) -> None:
        while not self._stop_event.is_set():
            with self._lock:
                cmd = self._pending_cmd
                should_write = (
                    cmd is not None and cmd[2] != self._handled_seq
                ) or (self._stop_pending and cmd is not None and cmd[3])
                if not should_write:
                    return
                rpm_l, rpm_r, seq, is_stop = cmd
            try:
                ok = bool(self._driver.set_double_rpm(rpm_l, rpm_r))
            except Exception:
                ok = False
            with self._lock:
                self._handled_seq = seq
                if is_stop:
                    self._last_stop_ok = ok
                    if ok and self._pending_cmd is not None and self._pending_cmd[2] == seq:
                        self._stop_pending = False
                else:
                    self._last_cmd_ok = ok
                # Loop again only if a newer command arrived during the write.
                if self._pending_cmd is not None and self._pending_cmd[2] != seq:
                    continue
                return

    def _poll_feedback(self) -> None:
        try:
            fb = self._driver.get_feedback()
        except Exception:
            fb = (None, None, None, None)
        now = self._clock()
        with self._lock:
            self._latest_feedback = fb
            if fb[0] is not None:
                self._last_feedback_ok_at = now

    def _poll_health_step(self) -> None:
        dxl_ids = list(self._driver.DXL_IDS)
        if not dxl_ids:
            return
        dxl_id = dxl_ids[self._health_idx]
        try:
            row = self._driver.read_health_one(dxl_id)
        except Exception:
            row = {
                "id": dxl_id,
                "temperature_c": None,
                "temperature_limit_c": None,
                "input_voltage_v": None,
                "hardware_error": None,
            }
        self._health_rows[dxl_id] = row
        self._health_idx = (self._health_idx + 1) % len(dxl_ids)
        if self._health_idx == 0:
            snapshot = [self._health_rows[i] for i in dxl_ids]
            with self._lock:
                self._health_snapshot = snapshot

    def _run(self) -> None:
        next_feedback = self._clock()
        next_health = self._clock() + self._health_step_period_s
        while not self._stop_event.is_set():
            self._flush_pending_command()
            if self._stop_event.is_set():
                break
            now = self._clock()
            if now >= next_feedback:
                self._poll_feedback()
                self._flush_pending_command()
                next_feedback = now + self._feedback_period_s
                if self._stop_event.is_set():
                    break
            now = self._clock()
            if now >= next_health:
                self._poll_health_step()
                self._flush_pending_command()
                next_health = now + self._health_step_period_s
                if self._stop_event.is_set():
                    break
            now = self._clock()
            wait_s = max(0.0, min(next_feedback - now, next_health - now))
            if self._wake.wait(timeout=wait_s):
                self._wake.clear()
