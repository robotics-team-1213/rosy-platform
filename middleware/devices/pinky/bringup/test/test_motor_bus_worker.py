"""Tests for dedicated UART worker decoupling in bringup (Phase 1)."""

from __future__ import annotations

import threading
import time

from bringup.motor_bus_worker import MotorBusWorker


class _FakeDriver:
    DXL_IDS = [1, 2]
    MAX_RPM = 100.0

    def __init__(self, *, feedback_delay_s: float = 0.0):
        self.feedback_delay_s = feedback_delay_s
        self.commands = []
        self.stop_failures = 0
        self.feedback_value = (12.0, -12.0, 100, 200)
        self.feedback_calls = 0
        self.health_calls = []

    def set_double_rpm(self, rpm_l, rpm_r):
        self.commands.append((float(rpm_l), float(rpm_r)))
        if rpm_l == 0.0 and rpm_r == 0.0 and self.stop_failures > 0:
            self.stop_failures -= 1
            return False
        return True

    def get_feedback(self):
        self.feedback_calls += 1
        if self.feedback_delay_s:
            time.sleep(self.feedback_delay_s)
        return self.feedback_value

    def read_health_one(self, dxl_id):
        self.health_calls.append(dxl_id)
        return {
            "id": dxl_id,
            "temperature_c": 40,
            "temperature_limit_c": 70,
            "input_voltage_v": 12.1,
            "hardware_error": 0,
        }


def test_slow_uart_feedback_does_not_block_cmd_or_read_feedback():
    driver = _FakeDriver(feedback_delay_s=0.15)
    worker = MotorBusWorker(driver, drive_enabled=True, feedback_period_s=0.02, feedback_stale_s=0.5)
    worker.start()
    try:
        time.sleep(0.03)
        t0 = time.monotonic()
        assert worker.set_double_rpm(20.0, -20.0) is True
        fb = worker.read_feedback()
        elapsed = time.monotonic() - t0
        assert elapsed < 0.05
        assert isinstance(fb, tuple) and len(fb) == 4
    finally:
        worker.stop()


def test_burst_commands_coalesce_to_latest_and_retry_failed_stop():
    driver = _FakeDriver()
    driver.stop_failures = 1
    gate = threading.Event()
    orig_get_fb = driver.get_feedback

    def gated_fb():
        gate.wait(timeout=0.02)
        return orig_get_fb()

    driver.get_feedback = gated_fb
    worker = MotorBusWorker(driver, drive_enabled=True, feedback_period_s=0.01, health_step_period_s=0.02)
    worker.start()
    try:
        assert worker.set_double_rpm(10.0, 10.0) is True
        assert worker.set_double_rpm(25.0, 25.0) is True
        assert worker.set_double_rpm(0.0, 0.0) is True
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            if driver.commands.count((0.0, 0.0)) >= 2:
                break
            time.sleep(0.005)
        assert driver.commands.count((0.0, 0.0)) >= 2
    finally:
        gate.set()
        worker.stop()


def test_stale_or_failed_feedback_reports_none_so_lease_clears():
    now = [10.0]
    driver = _FakeDriver()
    worker = MotorBusWorker(
        driver,
        drive_enabled=True,
        feedback_period_s=0.01,
        feedback_stale_s=0.05,
        clock=lambda: now[0],
    )
    worker.start()
    try:
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline and worker.read_feedback()[0] is None:
            time.sleep(0.005)
        assert worker.read_feedback() == (12.0, -12.0, 100, 200)

        now[0] = 20.0
        assert worker.read_feedback() == (None, None, None, None)

        driver.feedback_value = (None, None, None, None)
        now[0] = 20.01
        time.sleep(0.02)
        assert worker.read_feedback() == (None, None, None, None)
    finally:
        worker.stop()


def test_no_motion_mode_refuses_writes_and_collects_health():
    driver = _FakeDriver()
    worker = MotorBusWorker(driver, drive_enabled=False, feedback_period_s=0.01, health_step_period_s=0.01)
    worker.start()
    try:
        assert worker.set_double_rpm(10.0, 10.0) is False
        assert worker.set_double_rpm(0.0, 0.0) is False
        deadline = time.monotonic() + 0.5
        snap = None
        while time.monotonic() < deadline and snap is None:
            snap = worker.consume_health()
            time.sleep(0.005)
        assert snap is not None and [row["id"] for row in snap] == [1, 2]
        assert worker.consume_health() is None
        assert driver.commands == []
    finally:
        worker.stop()
        assert worker._thread is None
