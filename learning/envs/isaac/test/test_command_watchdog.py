import importlib.util
from pathlib import Path

import pytest
from types import SimpleNamespace
import sys


def helper():
    path = Path(__file__).parents[1] / "command_watchdog.py"
    assert path.is_file(), "Simulator command freshness watchdog is missing"
    spec = importlib.util.spec_from_file_location("command_watchdog", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def armed():
    guard = helper().CommandWatchdog(0.5)
    guard.graph_tick(10, 1.0)
    guard.receive(10)
    return guard


def test_startup_has_no_wheel_command_without_twist():
    guard = helper().CommandWatchdog(0.5)
    guard.graph_tick(10, 1.0)
    assert guard.filter((4, 4), 10) == (0.0, 0.0)


def test_tick_does_not_refresh_a_latched_twist():
    guard = armed()
    assert guard.filter((4, 4), 10.1) == (4, 4)
    guard.graph_tick(10.5, 1.5)
    assert guard.filter((4, 4), 10.5) == (0.0, 0.0)
    guard.graph_tick(10.6, 1.6)
    assert guard.filter((4, 4), 10.6) == (0.0, 0.0)


def test_missing_graph_callbacks_expires_even_with_new_twist():
    guard = armed()
    guard.receive(10.45)
    assert guard.filter((4, 4), 10.5) == (0.0, 0.0)
    guard.graph_tick(10.51, 1.51)
    assert guard.filter((4, 4), 10.51) == (0.0, 0.0)
    guard.receive(10.52)
    assert guard.filter((4, 4), 10.52) == (4, 4)


def test_pause_and_simulation_reset_require_new_command():
    guard = armed()
    assert guard.filter((4, 4), 10.1, playing=False) == (0.0, 0.0)
    guard.graph_tick(10.2, 1.2)
    assert guard.filter((4, 4), 10.2) == (0.0, 0.0)
    guard.receive(10.3)
    assert guard.filter((4, 4), 10.3) == (4, 4)
    guard.graph_tick(10.4, 0.0)
    assert guard.filter((4, 4), 10.4) == (0.0, 0.0)


@pytest.mark.parametrize("values", [(float("nan"), 1), (1, float("inf")), (1,), (1, 2, 3), None, ("bad", 1)])
def test_invalid_wheel_output_revokes_command(values):
    guard = armed()
    assert guard.filter(values, 10.1) == (0.0, 0.0)
    assert guard.filter((4, 4), 10.2) == (0.0, 0.0)


def test_clock_reversal_and_invalid_timeout_fail_closed():
    guard = armed()
    assert guard.filter((4, 4), 9.9) == (0.0, 0.0)
    for timeout in (0, -1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            helper().CommandWatchdog(timeout)


def test_actual_graph_receipt_and_gate_callbacks_do_not_refresh_old_twist(monkeypatch):
    module = helper()
    module.ACTIVE_WATCHDOG = module.CommandWatchdog(0.5)
    monkeypatch.setitem(sys.modules, "command_watchdog", module)
    timeline = SimpleNamespace(get_current_time=lambda: 1.0, is_playing=lambda: True)
    timeline_module = SimpleNamespace(get_timeline_interface=lambda: timeline)
    monkeypatch.setitem(sys.modules, "omni", SimpleNamespace(timeline=timeline_module))
    monkeypatch.setitem(sys.modules, "omni.timeline", timeline_module)
    now = [10.0]
    monkeypatch.setattr("time.monotonic", lambda: now[0])
    receipt, gate = {}, {"og": SimpleNamespace(ExecutionAttributeState=SimpleNamespace(ENABLED=1))}
    exec(module.RECEIPT_SCRIPT, receipt)
    exec(module.GATE_SCRIPT, gate)
    db = SimpleNamespace(inputs=SimpleNamespace(wheelVelocity=(3.0, 3.0)), outputs=SimpleNamespace())
    receipt["compute"](db)
    gate["compute"](db)
    assert db.outputs.velocityCommand == (3, 3)
    now[0] = 10.5
    gate["compute"](db)
    assert db.outputs.velocityCommand == (0, 0)
    now[0] = 10.6
    receipt["compute"](db)  # Same vector, genuinely new ROS message.
    gate["compute"](db)
    assert db.outputs.velocityCommand == (3, 3)


def runtime():
    path = Path(__file__).parents[1] / "drive_runtime.py"
    assert path.is_file(), "Runtime watchdog integration is missing"
    spec = importlib.util.spec_from_file_location("drive_runtime", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_watchdog_emergency_zero_reaches_graph_and_both_usd_drives():
    observed = []
    controller = SimpleNamespace(attribute=lambda path: path, set=lambda path, value: observed.append((path, value)))
    drives = [SimpleNamespace(GetTargetVelocityAttr=lambda n=n:
                              SimpleNamespace(Set=lambda value: observed.append((n, value)))) for n in range(2)]
    runtime().force_zero_wheels(controller, drives)
    assert ("/World/ROSYDrive/Gate.outputs:velocityCommand", [0.0, 0.0]) in observed
    assert (0, 0.0) in observed and (1, 0.0) in observed


def test_runner_has_no_ungated_articulation_command():
    source = (Path(__file__).parents[1] / "run_rosy.py").read_text(encoding="utf-8")
    assert '"/World/ROSYDrive/Gate.outputs:velocityCommand"' in source
    assert '"/World/ROSYDrive/Articulation.inputs:velocityCommand"' in source
    assert '"Diff.outputs:velocityCommand", "Articulation.inputs:velocityCommand"' not in source
    assert '"Twist.outputs:execOut", "Receipt.inputs:execIn"' in source
    assert "force_zero_wheels(og.Controller, wheel_drives)" in source
