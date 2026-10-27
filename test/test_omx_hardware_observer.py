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


def native_channel(monkeypatch, module, publish):
    import json
    class Channel:
        def __init__(self, key): self.key = key
        def write(self, kind, payload, **kwargs):
            assert kind == 'joints' and kwargs['captured_at'] > 0
            values = json.loads(payload)
            publish(self.key, SimpleNamespace(name=list(values), position=list(values.values())))
    monkeypatch.setattr(module, 'SnapshotChannel', Channel)
    monkeypatch.setitem(sys.modules, 'rclpy', None)
    monkeypatch.setitem(sys.modules, 'sensor_msgs', None)


def rows():
    return [dict(id=i, model_number=1060 if i < 14 else 1200, position_raw=2048,
                 torque_enabled=0, hardware_error=0) for i in range(11, 17)]


def test_existing_owner_publishes_fault32_before_stopping_without_joint_state(monkeypatch, tmp_path):
    import json
    monkeypatch.setenv('RMW_IMPLEMENTATION', 'rmw_fastrtps_cpp')
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'deploy/robot/omx'))
    module, published, events = observer(), [], []
    data = [{**row, 'hardware_error': 32 if row['id'] == 12 else 0,
             'goal_position_raw': 2048, 'present_pwm_raw': 0, 'pwm_limit_raw': 20,
             'temperature': 43, 'temperature_limit': 70, 'voltage_raw': 116,
             'min_voltage_raw': 60, 'max_voltage_raw': 140} for row in rows()]
    @contextmanager
    def port(device):
        events.append('open')
        try:
            yield object()
        finally:
            events.append('close')
    def read(port, *, allow_fault):
        assert allow_fault is True
        events.append('read')
        return data
    node = SimpleNamespace(create_publisher=lambda *args: SimpleNamespace(publish=published.append),
        get_clock=lambda: SimpleNamespace(now=lambda: SimpleNamespace(to_msg=lambda: 0)), destroy_node=lambda: None)
    monkeypatch.setitem(sys.modules, 'register_probe', SimpleNamespace(open_readonly_port=port, read_motors=read))
    monkeypatch.setitem(sys.modules, 'rclpy', SimpleNamespace(init=lambda **kwargs: None,
        create_node=lambda *args: node, ok=lambda: True, shutdown=lambda: None))
    monkeypatch.setitem(sys.modules, 'sensor_msgs.msg', SimpleNamespace(
        JointState=lambda: SimpleNamespace(header=SimpleNamespace())))
    state = tmp_path / 'health.json'
    native_channel(monkeypatch, module, lambda key, message: published.append(message))
    result = module.main(['--device', '/test/follower', '--domain-id', '13', '--persistent',
                         '--health-file', str(state), '--health-owner', 'arm_a'])
    assert result == 2 and published == [] and events == ['open', 'read', 'close']
    snapshot = json.loads(state.read_text())
    assert snapshot['status'] == 'fault' and snapshot['motors'][1]['hardware_error'] == 32
    assert all(m['torque_enabled'] is False for m in snapshot['motors'])


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
            raise KeyboardInterrupt()

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
    native_channel(monkeypatch, module, lambda key, message: samples.append(message))
    result = module.main(["--device", "/test/follower", "--domain-id", "13", "--persistent"])
    assert result == (0 if ending == "stop" else 2)
    assert len(samples) == (2 if ending == "stop" else 1)
    assert events.count("read") == 2 and events.count("open") == events.count("close") == 1
    assert 'destroy' not in events


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
    native_channel(monkeypatch, module, lambda key, message: (topics.append(key), messages.append(message)))
    assert module.main(["--device", f"/test/{arm}", "--domain-id", "13", "--duration", "1", "--joint-topic", topic]) == 0
    assert topics == [topic]
    assert nodes == []
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
    native_channel(monkeypatch, module, lambda key, message: events.append('publish'))
    assert module.main(["--device", "/test", "--domain-id", "13", "--duration", "1"]) == 2
    assert events == ["open", "close"]
    import json
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["exit_code"] == 2


@pytest.mark.parametrize("setting", ["CYCLONEDDS_URI", "FASTDDS_DEFAULT_PROFILES_FILE",
                                     "FASTRTPS_DEFAULT_PROFILES_FILE", "ROS_DISCOVERY_SERVER"])
def test_discovery_settings_cannot_enable_ros_in_native_observer(monkeypatch, setting):
    monkeypatch.setenv(setting, "external-profile")
    module = observer()
    @contextmanager
    def port(device):
        yield object()
    data = rows()
    data[0]['hardware_error'] = 4
    monkeypatch.setitem(sys.modules, 'register_probe', SimpleNamespace(
        open_readonly_port=port, read_motors=lambda p: data))
    native_channel(monkeypatch, module, lambda *args: pytest.fail('fault produced positions'))
    assert module.main(['--device', '/test', '--duration', '1']) == 2


def test_observer_unit_restarts_only_into_an_idle_cell():
    import configparser
    from pathlib import Path
    unit = configparser.ConfigParser(interpolation=None, strict=False)
    unit.read(Path(__file__).resolve().parents[1] / 'deploy/robot/omx/rosy-omx-observer@.service')
    service = unit['Service']
    assert service['Restart'] == 'on-failure' and int(service['RestartSec']) >= 10
    assert unit['Unit']['StartLimitIntervalSec'] == '0'
    guard = service['ExecStartPre']
    assert 'flock -n 9' in guard and '%h/rosy-omx/session.lock' in guard  # the lock joint_tune.session_lock takes
    assert 'fuser "$ROSY_OBSERVER_DEVICE"' in guard and 'exit 1' in guard


def test_observer_unit_writes_its_instances_health_file_into_a_folder_it_creates():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / 'deploy/robot/omx/rosy-omx-observer@.service').read_text()
    # D-871: no sha-named drop-in; the auto-updater reads this file as the torque-OFF evidence
    assert 'ExecStartPre=/bin/mkdir -p -m 0700 %h/.local/state/rosy/motor-health\n' in text
    assert '--health-file "%h/.local/state/rosy/motor-health/%i.json" --health-owner %i' in text
