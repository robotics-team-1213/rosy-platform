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
        _node(world, monkeypatch)
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
