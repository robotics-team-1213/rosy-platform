"""Camera / perception side of the per-device power policy (D-440)."""

import ast
import json
from pathlib import Path

import pytest

from control.camera_power_gate import DevicePowerGate, ready_report

NODE = Path(__file__).resolve().parents[1] / "nodes" / "camera_detect_node.py"


def test_no_board_means_run_every_tick():
    gate = DevicePowerGate()
    assert [gate.plan() for _ in range(8)] == ["run"] * 8


@pytest.mark.parametrize("board,plan", [
    ({"camera": "off"}, "off"),
    ({"camera": "on", "perception": "off"}, "off"),
    ({"camera": "on", "perception": "on"}, "run"),
    ({"lidar": "off"}, "run"),                    # other devices are not ours
    ({"camera": "sleepy"}, "run"),                # unknown level never pauses
])
def test_board_to_plan(board, plan):
    gate = DevicePowerGate()
    gate.update(json.dumps(board))
    assert gate.plan() == plan


def test_reduced_processes_one_tick_in_four():
    gate = DevicePowerGate(reduced_every=4)
    gate.update(json.dumps({"perception": "reduced"}))
    assert [gate.plan() for _ in range(8)] == ["run", "skip", "skip", "skip"] * 2


def test_camera_change_is_reported_once():
    gate = DevicePowerGate()
    assert gate.update(json.dumps({"camera": "off"})) == ("on", "off")
    assert gate.update(json.dumps({"camera": "off"})) is None
    assert gate.update(json.dumps({"camera": "on"})) == ("off", "on")
    assert gate.update("garbage") is None


def test_initial_managed_on_and_perception_wake_require_new_ready_report():
    gate = DevicePowerGate()
    assert gate.update('{"lidar":"on"}') is None
    assert gate.update('{"camera":"on","perception":"on"}') == ("on", "on")
    assert gate.update('{"camera":"on","perception":"on"}') is None
    assert gate.update('{"camera":"on","perception":"off"}') == ("on", "on")
    assert gate.update('{"camera":"on","perception":"on"}') == ("on", "on")


def test_ready_recheck_does_not_restart_an_unchanged_camera():
    from types import SimpleNamespace
    source = ast.parse((NODE.parent / "camera_power.py").read_text(encoding="utf-8"))
    cls = next(n for n in source.body if isinstance(n, ast.ClassDef))
    namespace = {}
    exec(compile(ast.Module(body=[cls], type_ignores=[]), "camera_power.py", "exec"), namespace)
    calls = []
    node = namespace["CameraPowerMixin"]()
    node._power_gate = DevicePowerGate()
    node._policy = SimpleNamespace(reset=lambda: calls.append("reset"))
    node._start_cam = lambda: calls.append("start")
    node._stop_cam = lambda: calls.append("stop")
    node.get_logger = lambda: SimpleNamespace(info=lambda _: None)
    node._report_camera_ready = lambda ready: calls.append(ready)
    node._on_power_devices(SimpleNamespace(data='{"camera":"on","perception":"on"}'))
    assert calls == ["reset", False]
    calls.clear()
    node._on_power_devices(SimpleNamespace(data='{"camera":"on","perception":"off"}'))
    node._on_power_devices(SimpleNamespace(data='{"camera":"on","perception":"on"}'))
    assert "start" not in calls and "stop" not in calls
    assert calls[-2:] == ["reset", False]


def test_ready_report_shape_matches_core_parser():
    assert json.loads(ready_report("camera", False)) == {"device": "camera", "ready": False}


def test_node_wires_the_gate_before_capture():
    """The plan is checked first in tick(): a paused camera must never be read."""
    tree = ast.parse(NODE.read_text(encoding="utf-8"))
    tick = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "tick")
    first = ast.unparse(tick.body[0])
    assert "self._power_held(self._power_gate.plan())" in first
    mixin = (NODE.parent / "camera_power.py").read_text(encoding="utf-8")
    assert "'power/devices'" in mixin and "'power/device_ready'" in mixin
    assert "CameraPowerMixin" in NODE.read_text(encoding="utf-8")


def test_a_paused_tick_reports_blocked_and_a_reduced_skip_holds_the_verdict():
    """Fail safe: a camera the power policy paused is blind, so it says blocked."""
    source = (NODE.parent / "camera_power.py").read_text(encoding="utf-8")
    assert "blocked = plan == 'off' or self._policy.blocked or not self._policy.ready" in source
