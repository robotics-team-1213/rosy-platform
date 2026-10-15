"""D-24 amendment (2026-10-04): what may wake a sleeping robot, and what may not.

Three defects found on the live 9dfk STANDBY run are pinned here:

* (a) presence noise — invalid samples and hysteresis-band samples did not break
  the "consecutive" count, so two stray echoes minutes apart woke the robot;
* (b) the battery alert woke on every voltage sample below WARNING and pinned
  the robot ACTIVE (main already wakes only when the alert level changes; the
  cases here pin that rule);
* (c) "command" was implicit. It is now an explicit `on_command(source)`. The
  route table and the HTTP path that feed it are tested in the gateway
  (`test_power_command_routes.py`).
"""

from __future__ import annotations

import pytest

from core_common.protocol.schemas import PowerMode
from core_features.power.manager import PowerConfig, PowerManager, PresenceConfig

NAN = float("nan")
INF = float("inf")


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _standby_manager(clock: Clock) -> PowerManager:
    # Explicit dwell: main's defaults are 600 s / 1800 s; the cases only need "asleep".
    mgr = PowerManager(PowerConfig(idle_after_s=60.0, standby_after_s=300.0,
                                   presence=PresenceConfig()), clock=clock)
    clock.now += 400.0
    mgr.tick()
    assert mgr.mode == PowerMode.STANDBY
    return mgr


def _feed(mgr: PowerManager, clock: Clock, samples) -> None:
    """samples: (dt_before_s, range_m) pairs, fed through on_range."""
    for dt, range_m in samples:
        clock.now += dt
        mgr.on_range(range_m)


def _every(period_s: float, range_m: float, n: int):
    return [(period_s, range_m)] * n


# --- (a) presence -------------------------------------------------------------

NOISE_MUST_NOT_WAKE = {
    # The 9dfk case: one echo, then minutes of no-echo (inf), then another echo.
    "two echoes minutes apart, dropouts between": [
        (0.5, 0.20), *_every(0.5, INF, 240), (0.5, 0.20), *_every(0.5, INF, 10)],
    "two echoes minutes apart, nothing between": [(0.5, 0.20), (180.0, 0.20)],
    "echoes separated by hysteresis-band samples": [
        (0.5, 0.20), (0.5, 0.30), (0.5, 0.20), (0.5, 0.30), (0.5, 0.20), (0.5, 0.30)],
    "echoes separated by NaN": [(0.05, 0.20), (0.05, NAN)] * 10,
    "short burst at 20 Hz (0.15 s)": [*_every(0.05, 0.20, 4), *_every(0.05, 1.5, 5)],
    "echoes slower than max_gap_s": _every(1.5, 0.20, 10),
    "far and out-of-range only": [*_every(0.5, 1.2, 20), *_every(0.5, 5.0, 20)],
}

APPROACH_MUST_WAKE = {
    "20 Hz, 0.5 s in front": (_every(0.05, 0.20, 11), "proximity"),
    "5 Hz (IDLE rate), 0.6 s": (_every(0.2, 0.20, 4), "proximity"),
    "2 Hz (STANDBY rate), two samples": (_every(0.5, 0.20, 2), "proximity"),
    "walk-in from far then stays": ([*_every(0.5, 1.0, 3), *_every(0.5, 0.40, 2),
                                     *_every(0.5, 0.20, 2)], "proximity"),
    "hand on the sensor": (_every(0.1, 0.03, 6), "contact"),
}


@pytest.mark.parametrize("samples", NOISE_MUST_NOT_WAKE.values(), ids=NOISE_MUST_NOT_WAKE.keys())
def test_presence_noise_does_not_wake(samples):
    clock = Clock()
    mgr = _standby_manager(clock)
    _feed(mgr, clock, samples)
    assert mgr.last_wake_reason is None
    assert mgr.info_visible() is False


@pytest.mark.parametrize("case", APPROACH_MUST_WAKE.values(), ids=APPROACH_MUST_WAKE.keys())
def test_real_approach_wakes(case):
    samples, reason = case
    clock = Clock()
    mgr = _standby_manager(clock)
    _feed(mgr, clock, samples)
    assert mgr.mode == PowerMode.ACTIVE
    assert mgr.last_wake_reason == reason


def test_dropout_does_not_release_a_held_presence():
    clock = Clock()
    mgr = _standby_manager(clock)
    _feed(mgr, clock, _every(0.1, 0.20, 6))
    _feed(mgr, clock, _every(0.1, NAN, 10))
    assert mgr.presence.value == "near"


# --- (b) battery edge ---------------------------------------------------------

@pytest.mark.parametrize("levels,wakes", [
    (["ok", "ok", "ok"], 0),
    (["ok", "warning", "warning", "warning", "warning"], 1),
    (["warning"] * 50, 1),
    (["ok", "warning", "critical", "critical"], 2),
    (["warning", "ok", "warning"], 2),                # a new crossing wakes again
])
def test_battery_alert_is_edge_triggered(levels, wakes):
    clock = Clock()
    mgr = PowerManager(PowerConfig(), clock=clock)
    seen = []

    class Bus:
        def publish(self, type_, **_):
            if type_ == "power.wake":
                seen.append(type_)

    mgr._events = Bus()
    for level in levels:
        mgr.on_battery_alert(level)
    assert len(seen) == wakes


def test_sustained_warning_no_longer_pins_active():
    clock = Clock()
    mgr = PowerManager(PowerConfig(), clock=clock)
    mgr.on_battery_alert("warning")
    for _ in range(400):              # one voltage sample a second for 400 s
        clock.now += 1.0
        mgr.on_battery_alert("warning")
        mgr.tick()
    assert mgr.mode == PowerMode.STANDBY


# --- (c) command --------------------------------------------------------------

def test_on_command_wakes_without_info_window():
    clock = Clock()
    mgr = _standby_manager(clock)
    mgr.on_command("teleop")
    assert mgr.mode == PowerMode.ACTIVE
    assert mgr.last_wake_reason == "command"
    assert mgr.info_visible() is False
    assert mgr.status().idle_seconds == 0.0


def test_on_command_while_active_keeps_previous_wake_reason():
    clock = Clock()
    mgr = PowerManager(PowerConfig(), clock=clock)
    mgr.on_command("teleop")
    assert mgr.last_wake_reason is None
