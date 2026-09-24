"""The two reconcile latches differ, and the difference is the point.

Both live at 5 Hz in `ros_bridge.py`, where no host test reaches them. LED
latches even when its service is missing; LiDAR does not, because it is a
navigation input and a late driver must still be reached. Getting that backwards
is silent: the robot simply never spins its lidar, or repaints the same colour
five times a second forever.
"""

from __future__ import annotations

from types import SimpleNamespace

from core.bridge.reconcile import led, reconcile


def test_no_action_when_nothing_changed():
    calls = []
    acted, applied = reconcile("red", "red", lambda: calls.append(1) or True,
                               latch_on_skip=True)

    assert acted is False
    assert applied == "red"
    assert calls == []


def test_acts_and_latches_when_the_desire_changes():
    acted, applied = reconcile("green", "red", lambda: True, latch_on_skip=False)

    assert acted is True
    assert applied == "green"


def test_led_latches_even_though_the_service_was_missing():
    """Decoration: skipping is fine, repainting at 5 Hz is not."""
    acted, applied = reconcile("green", "red", lambda: False, latch_on_skip=True)

    assert acted is False
    assert applied == "green", "a skipped LED call must not be retried"


def test_lidar_does_not_latch_when_the_service_was_missing():
    """Navigation input: a driver that comes up late must still be reached."""
    acted, applied = reconcile(True, False, lambda: False, latch_on_skip=False)

    assert acted is False
    assert applied is False, "an unsent lidar command must be retried next tick"


def test_lidar_retries_until_the_service_appears_then_stops():
    ready = iter([False, False, True])
    applied = False
    attempts = 0

    for _ in range(4):
        def send():
            nonlocal attempts
            attempts += 1
            return next(ready, True)

        _acted, applied = reconcile(True, applied, send, latch_on_skip=False)

    assert applied is True
    assert attempts == 3, "stops attempting once the command has landed"


def test_false_is_a_value_not_an_absence():
    """`spinning=False` must be latchable — a stop command is a command."""
    acted, applied = reconcile(False, True, lambda: True, latch_on_skip=False)

    assert acted is True
    assert applied is False


# --- the LED composition `reconcile.led` replaced inline ---------------------

def test_the_led_latches_after_a_skipped_service_call():
    """The asymmetry, end to end: a missing service is not retried at 5 Hz."""
    seen = []

    applied = led(None, "clear", info_visible=True, gauge_percent=90.0,
                  now=0.0, act=lambda command: seen.append(command) or False)

    assert applied.command == "fill"
    assert (applied.r, applied.g, applied.b) == (0, 60, 0)
    assert seen == [applied], "act receives the very command that is latched"


def test_the_same_led_command_is_not_sent_twice():
    seen = []

    applied = led(None, "clear", info_visible=True, gauge_percent=90.0,
                  now=0.0, act=lambda command: seen.append(command) or True)
    led(None, applied, info_visible=True, gauge_percent=90.0,
        now=0.5, act=lambda command: seen.append(command) or True)

    assert len(seen) == 1, "the tick is 5 Hz; the colour has not changed"


def test_a_live_alert_outbids_the_gauge():
    """§"표시 권한": a live alert outranks the info-window gauge, blink phase or not."""
    alert = SimpleNamespace(lit_at=lambda now: True, r=60, g=0, b=0)

    applied = led(alert, "clear", info_visible=True, gauge_percent=90.0,
                  now=0.0, act=lambda command: True)

    assert applied.command == "fill"
    assert (applied.r, applied.g, applied.b) == (60, 0, 0)
