"""Physical feedback is fresh and complete, never synthetic or motion admission."""
import importlib.util
from pathlib import Path

import pytest
from contextlib import contextmanager
from types import SimpleNamespace
import sys
import os


def observer():
    path = Path(__file__).resolve().parents[1] / "deploy/robot/omx/hardware_observer.py"
    spec = importlib.util.spec_from_file_location("hardware_observer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rows():
    return [dict(id=i, model_number=1060 if i < 14 else 1200, position_raw=2048,
                 torque_enabled=0, hardware_error=0) for i in range(11, 17)]


@pytest.mark.parametrize("ending", ["stop", "torque", "fault"])
def test_persistent_observation_stops_and_releases_bus_without_restarting(monkeypatch, ending):
    monkeypatch.setenv("RMW_IMPLEMENTATION", "rmw_fastrtps_cpp")
    module = observer()
    events, samples, running, clock = [], [], [True], [0.0]

    @contextmanager
    def port(device):
        events.append("open")
        try:
            yield object()
        finally:
            events.append("close")

    def read(_port):
        events.append("read")
        data = rows()
        if events.count("read") == 2 and ending != "stop":
            data[0]["torque_enabled" if ending == "torque" else "hardware_error"] = 1
        return data

    def sleep(_seconds):
        clock[0] += 301
        if ending == "stop" and len(samples) == 2:
            running[0] = False

    node = SimpleNamespace(
        create_publisher=lambda *args: SimpleNamespace(publish=samples.append),
        get_clock=lambda: SimpleNamespace(now=lambda: SimpleNamespace(to_msg=lambda: 0)),
        destroy_node=lambda: events.append("destroy"))
    monkeypatch.setitem(sys.modules, "register_probe", SimpleNamespace(open_readonly_port=port, read_motors=read))
    monkeypatch.setitem(sys.modules, "rclpy", SimpleNamespace(init=lambda **kwargs: None,
        create_node=lambda *args: node, ok=lambda: running[0], shutdown=lambda: events.append("shutdown")))
    monkeypatch.setitem(sys.modules, "sensor_msgs.msg", SimpleNamespace(
        JointState=lambda: SimpleNamespace(header=SimpleNamespace())))
    monkeypatch.setattr(module, "time", SimpleNamespace(
        monotonic=lambda: clock[0], time=lambda: 1700000000 + clock[0], sleep=sleep))
    result = module.main(["--device", "/test/follower", "--domain-id", "13", "--persistent"])
    assert result == (0 if ending == "stop" else 2)
    assert len(samples) == (2 if ending == "stop" else 1)
    assert events.count("read") == 2 and events.count("open") == events.count("close") == 1
    assert "destroy" in events


def test_persistent_mode_cannot_silently_extend_a_bounded_run():
    with pytest.raises(SystemExit) as error:
        observer().main(["--device", "/test/follower", "--domain-id", "13", "--duration", "1", "--persistent"])
    assert error.value.code == 2


@pytest.mark.parametrize("topic", ["/joint_states", "/omx/arm_a/joint_states",
                                    "/omx_commissioning/arm_a/command", "/omx_commissioning//joint_states"])
def test_dual_arm_observer_cannot_masquerade_as_control_feedback(topic):
    with pytest.raises(ValueError):
        observer().joint_topic(topic)


@pytest.mark.parametrize("arm", ["arm_a", "arm_b"])
def test_dual_arm_observer_routes_a_guarded_sample_to_its_own_topic(monkeypatch, capsys, arm):
    monkeypatch.setenv("RMW_IMPLEMENTATION", "rmw_fastrtps_cpp")
    module = observer()
    topics, nodes, messages = [], [], []
    clock = [0.0]
    @contextmanager
    def port(device):
        yield object()
    def publisher(kind, topic, depth):
        topics.append(topic)
        return SimpleNamespace(publish=lambda message: messages.append(message))
    node = SimpleNamespace(create_publisher=publisher,
        get_clock=lambda: SimpleNamespace(now=lambda: SimpleNamespace(to_msg=lambda: 0)),
        destroy_node=lambda: None)
    def create_node(name):
        nodes.append(name)
        return node
    monkeypatch.setitem(sys.modules, "register_probe", SimpleNamespace(open_readonly_port=port, read_motors=lambda p: rows()))
    monkeypatch.setitem(sys.modules, "rclpy", SimpleNamespace(init=lambda **kwargs: None,
        create_node=create_node, ok=lambda: True, shutdown=lambda: None))
    monkeypatch.setitem(sys.modules, "sensor_msgs.msg", SimpleNamespace(JointState=lambda: SimpleNamespace(header=SimpleNamespace())))
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(module.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + 1.5))
    topic = f"/omx_commissioning/{arm}/joint_states"
    assert module.main(["--device", f"/test/{arm}", "--domain-id", "13", "--duration", "1", "--joint-topic", topic]) == 0
    assert topics == [topic]
    assert arm in nodes[0]
    assert len(messages) == 1
    import json
    sample = next(json.loads(line) for line in capsys.readouterr().out.splitlines() if '"sample"' in line)
    assert sample["device"] == f"/test/{arm}"
    assert sample["joint_topic"] == topic
    assert sample["motion_admitted"] is False


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


@pytest.mark.parametrize("cleanup_failure", [None, "destroy", "shutdown"])
def test_motor_fault_closes_port_and_publishes_no_state(monkeypatch, capsys, cleanup_failure):
    monkeypatch.setenv('RMW_IMPLEMENTATION', 'rmw_fastrtps_cpp')  # Observer's declared middleware precondition.
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
    def cleanup(name):
        events.append(name)
        if cleanup_failure == name:
            raise RuntimeError("cleanup failed")
    node = SimpleNamespace(
        create_publisher=lambda *a: SimpleNamespace(publish=lambda m: events.append("publish")),
        get_clock=lambda: SimpleNamespace(now=lambda: SimpleNamespace(to_msg=lambda: 0)),
        destroy_node=lambda: cleanup("destroy"))
    monkeypatch.setitem(sys.modules, "register_probe", SimpleNamespace(
        open_readonly_port=port, read_motors=lambda p: broken))
    def init(**kwargs):
        assert os.environ.get("ROS_STATIC_PEERS", "") == ""
    monkeypatch.setitem(sys.modules, "rclpy", SimpleNamespace(
        init=init, create_node=lambda n: node, ok=lambda: True,
        shutdown=lambda: cleanup("shutdown")))
    monkeypatch.setitem(sys.modules, "sensor_msgs.msg", SimpleNamespace(
        JointState=lambda: SimpleNamespace(header=SimpleNamespace())))
    monkeypatch.setenv("ROS_AUTOMATIC_DISCOVERY_RANGE", "LOCALHOST")
    monkeypatch.setenv("ROS_STATIC_PEERS", "remote-peer")
    assert module.main(["--device", "/test", "--domain-id", "13", "--duration", "1"]) == 2
    assert events == ["open", "close", "destroy", "shutdown"]
    import json
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["exit_code"] == 2


@pytest.mark.parametrize("setting", ["CYCLONEDDS_URI", "FASTDDS_DEFAULT_PROFILES_FILE",
                                     "FASTRTPS_DEFAULT_PROFILES_FILE", "ROS_DISCOVERY_SERVER"])
def test_external_discovery_overrides_are_rejected_before_ros_or_serial_import(monkeypatch, setting):
    monkeypatch.setenv(setting, "external-profile")
    with pytest.raises(SystemExit) as error:
        observer().main(["--device", "/test", "--domain-id", "13", "--duration", "1"])
    assert error.value.code == 2
