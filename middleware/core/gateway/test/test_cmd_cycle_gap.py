"""The 50 Hz cycle only counts late starts; reports belong to a slower timer."""
import ast
from pathlib import Path

import pytest

from core.bridge.cmd_vel import CycleGapWatch

BRIDGE = Path(__file__).resolve().parents[1] / "core/bridge/ros_bridge.py"


def _watch(times, cycle=lambda: None):
    clock = iter(times)
    return CycleGapWatch(cycle, clock=lambda: next(clock))


def _report(watch, warn):
    watch.reporting(lambda: None, warn)()


def test_gaps_under_the_limit_are_not_counted():
    warned = []
    watch = _watch([0.0, 0.02, 0.04, 0.139, 1.0])
    for _ in range(4):
        watch()
    _report(watch, warned.append)
    assert warned == []


def test_a_late_cycle_is_reported_with_its_worst_gap():
    warned = []
    watch = _watch([0.0, 0.02, 0.27, 0.42, 1.0])
    for _ in range(4):
        watch()
    _report(watch, warned.append)
    assert warned == ["cmd_vel cycle started late 2 time(s), worst gap 0.250 s"]


def test_the_cycle_itself_never_reports():
    """A blocking logger would hold the next send and stop, so the wrapper must not reach one."""
    ran = []
    watch = _watch([0.0, 9.0], cycle=lambda: ran.append(1))
    watch()
    watch()
    assert ran == [1, 1]
    call = next(n for n in ast.walk(ast.parse(Path(__import__("core.bridge.cmd_vel", fromlist=["x"]).__file__).read_text(encoding="utf-8")))
                if isinstance(n, ast.FunctionDef) and n.name == "__call__")
    names = {n.func.attr for n in ast.walk(call) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert names == {"_clock", "_cycle"}


def test_reports_are_limited_and_later_ones_keep_the_count():
    warned = []
    watch = _watch([0.0, 1.0, 1.1, 2.0, 2.1, 6.2, 6.3])
    watch()
    watch()
    _report(watch, warned.append)   # 1.1: first report
    watch()
    _report(watch, warned.append)   # 2.1: inside the interval, kept
    watch()
    _report(watch, warned.append)   # 6.3: due
    assert warned == ["cmd_vel cycle started late 1 time(s), worst gap 1.000 s",
                      "cmd_vel cycle started late 2 time(s), worst gap 4.200 s"]


def test_a_failing_report_waits_out_the_interval_and_keeps_the_tick():
    attempts, ticks = [], []

    def broken(message):
        attempts.append(message)
        raise RuntimeError("logger gone")
    watch = _watch([0.0, 1.0, 1.1, 2.0, 2.1, 7.0, 7.1])
    report = watch.reporting(lambda: ticks.append(1), broken)
    watch()
    watch()
    report()    # first attempt fails
    watch()
    report()    # late again, inside the interval: no second attempt
    watch()
    report()    # past the interval: one more
    assert len(attempts) == 2 and len(ticks) == 3


def test_a_failing_clock_still_runs_the_cycle():
    def broken():
        raise RuntimeError("clock")
    ran = []
    CycleGapWatch(lambda: ran.append(1), clock=broken)()
    assert ran == [1]


def test_a_cycle_or_tick_failure_is_not_hidden():
    def failing():
        raise ValueError("boom")
    watch = CycleGapWatch(failing, clock=lambda: 0.0)
    with pytest.raises(ValueError):
        watch()
    with pytest.raises(ValueError):
        watch.reporting(failing, print)()


def test_the_bridge_wires_the_watch_to_the_50_hz_timer_and_reports_from_the_1_hz_one():
    source = BRIDGE.read_text(encoding="utf-8")
    assert "create_timer(1.0 / 50.0, cmd_gap := CycleGapWatch(self._publish_cmd_vel))" in source
    assert "create_timer(1.0, cmd_gap.reporting(self._tick_diagnostics, node.get_logger().warning))" in source
