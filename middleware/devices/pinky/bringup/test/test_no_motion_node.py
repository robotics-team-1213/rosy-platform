"""The bringup node in no-motion mode, run against stubbed rclpy and SDK (D-192).

drive_enabled=False must mean: the real DynamixelDriver never writes torque
enable 1, the node never subscribes cmd_vel, motor/ready is only ever False,
and odometry / joint states still flow from the encoders.
"""

from __future__ import annotations

import importlib
import sys

import pytest

import ros_stubs

TORQUE_ENABLE = 64
LED_RED = 65


@pytest.fixture
def world(monkeypatch):
    stubbed = ros_stubs.World()
    ros_stubs.install(monkeypatch, stubbed)
    for name in ("bringup.bringup", "bringup.dynamixel_driver", "bringup.battery_publisher"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    yield stubbed
    for name in ("bringup.bringup", "bringup.dynamixel_driver", "bringup.battery_publisher"):
        sys.modules.pop(name, None)


def _node(world, monkeypatch, **parameters):
    world.parameters.update(parameters)
    module = importlib.import_module("bringup.bringup")
    driver = importlib.import_module("bringup.dynamixel_driver")
    monkeypatch.setattr(module.time, "sleep", lambda _s: None)
    monkeypatch.setattr(driver.time, "sleep", lambda _s: None)
    return module.Rosy()


def _ready(world):
    return [message.data for message in world.publishers["motor/ready"].messages]


def _torque_on(world):
    return [event for event in world.sdk_events
            if event[0] == "write1" and event[2] in (TORQUE_ENABLE, LED_RED) and event[3] == 1]


def test_no_motion_node_never_enables_torque_or_listens_to_cmd_vel(world, monkeypatch):
    node = _node(world, monkeypatch, drive_enabled=False)
    for _ in range(5):
        node.update_and_publish()

    assert node.is_initialized
    assert _torque_on(world) == []
    assert [topic for topic, _cb in world.subscriptions] == ["battery/voltage"]
    assert _ready(world) and set(_ready(world)) == {False}
    # Exactly one goal write: the zero the driver confirms before torque would come on.
    goals = [event for event in world.sdk_events if event[0] == "goal"]
    assert len(goals) == 1 and all(param == b"\0\0\0\0" for _id, param in goals[0][1])
    # Encoders still read back; odometry and joint states still publish.
    assert world.publishers["joint_states"].messages
    assert world.publishers["odom"].messages
    assert any("no-motion" in text for _level, text in world.logs)


def test_drive_mode_is_unchanged(world, monkeypatch):
    node = _node(world, monkeypatch)
    node.update_and_publish()

    assert len(_torque_on(world)) == 4  # torque and LED on both motors
    assert "cmd_vel" in [topic for topic, _cb in world.subscriptions]
    assert _ready(world)[0] is False and _ready(world)[-1] is True


def test_drive_enabled_is_read_only_and_strictly_boolean(world, monkeypatch):
    _node(world, monkeypatch, drive_enabled=False)
    assert world.descriptors["drive_enabled"].read_only is True

    sys.modules.pop("bringup.bringup", None)
    world.parameters.clear()
    with pytest.raises(ValueError, match="drive_enabled must be a boolean"):
        _node(world, monkeypatch, drive_enabled="false")


def test_stalled_motor_fails_start_after_one_reboot_retry(world, monkeypatch):
    # 8kcn: ID 1 latched overload, position fixed while current rose, yet start "succeeded".
    world.stall_on_goal.add(1)
    with pytest.raises(RuntimeError, match=r"ID 1: stalled"):
        _node(world, monkeypatch, motor_motion_check=True)
    assert sum(1 for event in world.sdk_events if event[0] == "reboot" and event[1] == 1) == 2
    assert not any("started successfully" in text for _level, text in world.logs)
    assert any(level == "error" and "motor start verification failed" in text for level, text in world.logs)


def test_latched_hardware_error_is_cleared_by_the_reboot_retry(world, monkeypatch):
    original = importlib.import_module("dynamixel_sdk").PacketHandler.reboot
    calls = {"n": 0}

    def reboot_then_relatch(self, port, motor_id):
        calls["n"] += 1
        result = original(self, port, motor_id)
        if calls["n"] <= 2 and motor_id == 1:
            world.hw_error[1] = 0x20  # first init: latches again right after; the retry reboot clears it
        return result

    monkeypatch.setattr(importlib.import_module("dynamixel_sdk").PacketHandler, "reboot", reboot_then_relatch)
    node = _node(world, monkeypatch)
    assert node.is_initialized
    assert world.hw_error[1] == 0


def test_persistent_hardware_error_is_reported_with_its_name(world, monkeypatch):
    original = importlib.import_module("dynamixel_sdk").PacketHandler.reboot

    def always_latched(self, port, motor_id):
        result = original(self, port, motor_id)
        world.hw_error[motor_id] = 0x20
        return result

    monkeypatch.setattr(importlib.import_module("dynamixel_sdk").PacketHandler, "reboot", always_latched)
    with pytest.raises(RuntimeError, match=r"hardware error 0x20 \(overload\)"):
        _node(world, monkeypatch)


def _goals(world):
    return [event for event in world.sdk_events if event[0] == "goal"]


def test_motion_probe_is_off_by_default_and_wheels_do_not_move(world, monkeypatch):
    node = _node(world, monkeypatch)
    assert node.is_initialized
    # Only the confirmed zero goals; nothing but zeros reached the wheels.
    assert all(param == b"\0\0\0\0" for goals in _goals(world) for _id, param in goals[1])


def test_stall_without_probe_is_not_detected_but_idle_current_is(world, monkeypatch):
    world.stall_on_goal.add(1)
    assert _node(world, monkeypatch).is_initialized  # needs the opt-in probe
    sys.modules.pop("bringup.bringup", None)
    world.parameters.clear()
    world.read2_value = 200  # 538 mA at zero velocity
    with pytest.raises(RuntimeError, match=r"ID 1: 538 mA at zero velocity"):
        _node(world, monkeypatch)


def test_motor_health_is_published_every_two_seconds_as_json(world, monkeypatch):
    import json
    _node(world, monkeypatch, drive_enabled=False)
    [callback] = [cb for period, cb in world.timers if period == 2.0]
    callback()
    [message] = world.publishers["motor/health"].messages
    motors = json.loads(message.data)["motors"]
    assert [m["id"] for m in motors] == [1, 2]
    assert set(motors[0]) == {"id", "temperature_c", "temperature_limit_c", "input_voltage_v", "hardware_error"}


@pytest.mark.parametrize("prefix,expected", [("", ["l_wheel_joint", "r_wheel_joint"]), ("rosy_01", ["rosy_01/l_wheel_joint", "rosy_01/r_wheel_joint"])])
def test_joint_states_match_urdf_wheel_joint_names(world, monkeypatch, prefix, expected):
    node = _node(world, monkeypatch, drive_enabled=False, frame_prefix=prefix)
    for _ in range(3):
        node.update_and_publish()
    assert world.publishers["joint_states"].messages[-1].name == expected


def test_motor_ready_clears_after_three_feedback_failures_and_recovers(world, monkeypatch):
    node = _node(world, monkeypatch, drive_enabled=True)
    assert _ready(world)[-1] is True
    feedback = [(None, None, None, None)]
    monkeypatch.setattr(node.driver, "get_feedback", lambda: feedback[0])
    odom_before = len(world.publishers["odom"].messages)
    for _ in range(2):
        node.update_and_publish()
    assert _ready(world)[-1] is True
    node.update_and_publish()
    assert _ready(world)[-1] is False
    assert len(world.publishers["odom"].messages) == odom_before

    feedback[0] = (0.0, 0.0, 1000, 2000)
    node.update_and_publish()
    assert _ready(world)[-1] is True
    assert len(world.publishers["odom"].messages) == odom_before + 1


def test_bringup_executor_kind_defaults_to_single_and_rejects_unknown(world):
    bringup_mod = importlib.import_module("bringup.bringup")
    assert bringup_mod._executor_kind({}) == "single"
    assert bringup_mod._executor_kind({"ROSY_EXECUTOR": "  "}) == "single"
    assert bringup_mod._executor_kind({"ROSY_EXECUTOR": "SINGLE"}) == "single"
    assert bringup_mod._executor_kind({"ROSY_EXECUTOR": " events "}) == "events"
    with pytest.raises(ValueError, match="ROSY_EXECUTOR must be one of 'events', 'single'"):
        bringup_mod._executor_kind({"ROSY_EXECUTOR": "multi"})


def test_bringup_spin_node_supports_single_and_events_executors(world):
    from types import SimpleNamespace
    bringup_mod = importlib.import_module("bringup.bringup")

    class ExternalShutdown(Exception):
        pass

    single_calls = []
    fake_rclpy = SimpleNamespace(
        __name__="rclpy",
        spin=lambda node: single_calls.append(node),
        executors=SimpleNamespace(ExternalShutdownException=ExternalShutdown),
    )
    bringup_mod._spin_node("node", rclpy_mod=fake_rclpy, environ={"ROSY_EXECUTOR": "single"})
    assert single_calls == ["node"]

    events_log = []

    class FakeEventsExecutor:
        def __init__(self, *, raise_exc=None):
            self._raise_exc = raise_exc

        def add_node(self, node):
            events_log.append(("add", node))

        def spin(self):
            events_log.append(("spin",))
            if self._raise_exc is not None:
                raise self._raise_exc

        def remove_node(self, node):
            events_log.append(("remove", node))

        def shutdown(self, timeout_sec=0):
            events_log.append(("shutdown", timeout_sec))

    bringup_mod._spin_node(
        "node",
        rclpy_mod=fake_rclpy,
        environ={"ROSY_EXECUTOR": "events"},
        import_module=lambda name: SimpleNamespace(EventsExecutor=lambda: FakeEventsExecutor()),
    )
    assert events_log == [("add", "node"), ("spin",), ("remove", "node"), ("shutdown", 0)]

    events_log.clear()
    bringup_mod._spin_node(
        "node",
        rclpy_mod=fake_rclpy,
        environ={"ROSY_EXECUTOR": "events"},
        import_module=lambda name: SimpleNamespace(
            EventsExecutor=lambda: FakeEventsExecutor(raise_exc=ExternalShutdown())),
    )
    assert events_log == [("add", "node"), ("spin",), ("remove", "node"), ("shutdown", 0)]

    events_log.clear()
    with pytest.raises(KeyboardInterrupt):
        bringup_mod._spin_node(
            "node",
            rclpy_mod=fake_rclpy,
            environ={"ROSY_EXECUTOR": "events"},
            import_module=lambda name: SimpleNamespace(
                EventsExecutor=lambda: FakeEventsExecutor(raise_exc=KeyboardInterrupt())),
        )
    assert events_log == [("add", "node"), ("spin",), ("remove", "node"), ("shutdown", 0)]
