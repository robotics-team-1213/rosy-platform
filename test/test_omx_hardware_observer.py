"""Physical feedback is fresh and complete, never synthetic or motion admission."""
import importlib.util
from pathlib import Path

import pytest
from contextlib import contextmanager
from types import SimpleNamespace
import sys


def observer():
    path = Path(__file__).resolve().parents[1] / "deploy/robot/omx/hardware_observer.py"
    spec = importlib.util.spec_from_file_location("hardware_observer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rows():
    return [dict(id=i, model_number=1060 if i < 14 else 1200, position_raw=2048,
                 torque_enabled=0, hardware_error=0) for i in range(11, 17)]


def test_nominal_radians_preserve_register_offset_without_applying_it_twice():
    data = rows()
    data[4].update(position_raw=3072, homing_offset_raw=1024)
    result = observer().positions(data, .02)
    assert result[:4] == pytest.approx([0] * 4)
    assert result[4] == pytest.approx(1.5707963267948966)


@pytest.mark.parametrize("duration", [.251, -1, float("nan"), float("inf")])
def test_stale_or_invalid_read_window_is_rejected(duration):
    with pytest.raises(ValueError):
        observer().positions(rows(), duration)


@pytest.mark.parametrize("change", ["missing", "duplicate", "wrong_model", "torque", "fault"])
def test_incomplete_or_unsafe_snapshot_never_becomes_joint_feedback(change):
    data = rows()
    if change == "missing":
        data.pop()
    elif change == "duplicate":
        data[-1]["id"] = 11
    elif change == "wrong_model":
        data[0]["model_number"] = 1200
    elif change == "torque":
        data[0]["torque_enabled"] = 1
    else:
        data[0]["hardware_error"] = 4
    with pytest.raises(ValueError):
        observer().positions(data, .02)


def test_motor_fault_closes_port_and_publishes_no_state(monkeypatch):
    module = observer()
    events = []
    @contextmanager
    def port(device):
        events.append("open")
        try:
            yield object()
        finally:
            events.append("close")
    broken = rows()
    broken[2]["hardware_error"] = 4
    node = SimpleNamespace(
        create_publisher=lambda *a: SimpleNamespace(publish=lambda m: events.append("publish")),
        get_clock=lambda: SimpleNamespace(now=lambda: SimpleNamespace(to_msg=lambda: 0)),
        destroy_node=lambda: events.append("destroy"))
    monkeypatch.setitem(sys.modules, "register_probe", SimpleNamespace(
        open_readonly_port=port, read_motors=lambda p: broken))
    monkeypatch.setitem(sys.modules, "rclpy", SimpleNamespace(
        init=lambda **k: None, create_node=lambda n: node, ok=lambda: True,
        shutdown=lambda: events.append("shutdown")))
    monkeypatch.setitem(sys.modules, "sensor_msgs.msg", SimpleNamespace(
        JointState=lambda: SimpleNamespace(header=SimpleNamespace())))
    monkeypatch.setenv("ROS_AUTOMATIC_DISCOVERY_RANGE", "LOCALHOST")
    assert module.main(["--device", "/test", "--domain-id", "13", "--duration", "1"]) == 2
    assert events == ["open", "close", "destroy", "shutdown"]
