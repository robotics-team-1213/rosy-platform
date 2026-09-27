"""Exercise the real face callback and timer without ROS or an LCD device."""

import importlib.util
import json
import sys
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from PIL import Image


FACE = Path(__file__).resolve().parents[1] / "emotion"


class FakeLCD:
    w, h = 240, 320

    def __init__(self):
        self.events = []

    def img_show(self, image):
        self.events.append(("img_show", image))

    def set_backlight(self, value):
        self.events.append(("set_backlight", value))

    def sleep(self):
        self.events.append(("sleep",))

    def wake(self):
        self.events.append(("wake",))


@pytest.fixture
def face(monkeypatch):
    """Load the actual node methods with only its ROS and hardware imports stubbed."""
    rclpy = ModuleType("rclpy")
    rclpy.node = ModuleType("rclpy.node")
    rclpy.node.Node = object
    rclpy.qos = ModuleType("rclpy.qos")
    rclpy.qos.QoSProfile = lambda **_kw: object()
    rclpy.qos.DurabilityPolicy = SimpleNamespace(TRANSIENT_LOCAL="latched")
    rclpy.qos.ReliabilityPolicy = SimpleNamespace(RELIABLE="reliable")
    ament = ModuleType("ament_index_python")
    ament.packages = ModuleType("ament_index_python.packages")
    ament.packages.get_package_share_directory = lambda _name: str(FACE.parent)
    std_msgs = ModuleType("std_msgs")
    std_msgs.msg = ModuleType("std_msgs.msg")
    std_msgs.msg.String = object
    interfaces = ModuleType("interfaces")
    interfaces.srv = ModuleType("interfaces.srv")
    interfaces.srv.Emotion = object
    lcd_module = ModuleType("emotion.rosy_lcd")
    lcd_module.LCD = FakeLCD
    for module in (rclpy, rclpy.node, rclpy.qos, ament, ament.packages,
                   std_msgs, std_msgs.msg, interfaces, interfaces.srv, lcd_module):
        monkeypatch.setitem(sys.modules, module.__name__, module)

    name = "emotion._runtime_under_test"
    spec = importlib.util.spec_from_file_location(name, FACE / "emotion_server.py")
    runtime = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, runtime)
    spec.loader.exec_module(runtime)
    clock = [100.0]
    monkeypatch.setattr(runtime, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    node = runtime.RosyEmotion.__new__(runtime.RosyEmotion)
    node.lcd = FakeLCD()
    with Image.open(FACE / "happy.gif") as gif:
        node.gif_frames = [gif.convert("RGB")]
    node.gif_lock = threading.Lock()
    node.current_frame_index = 0
    node.play_frame_skip = 1
    node.power_mode = "active"
    node.display_sleeping = False
    node.info_image = None
    node.info_until = 0.0
    node._shown_info = None
    node._backlight_for = lambda mode: {"active": 100, "idle": 30, "standby": 0}[mode]
    node.get_logger = lambda: SimpleNamespace(warn=lambda _msg: None, error=lambda _msg: None)
    return node, clock


def _send(node, **overrides):
    payload = {"robot_id": "rosy_demo", "battery_percent": 73.4,
               "battery_voltage": 12.1, "mode": "IDLE", "navigation": "IDLE",
               "health": "OK", "hold_s": 2.0}
    payload.update(overrides)
    node.display_info_callback(SimpleNamespace(data=json.dumps(payload)))


def test_live_node_renders_at_lcd_resolution_then_returns_to_intent(face):
    node, clock = face
    assert node.gif_frames[0].size == (1000, 750)  # actual shipped asset

    _send(node)
    assert node.info_image.size == (320, 240)
    assert node.info_until == 102.0

    node.timer_callback()
    assert node.lcd.events[-1] == ("img_show", node.info_image)
    clock[0] = 101.9
    node.timer_callback()
    assert len([event for event in node.lcd.events if event[0] == "img_show"]) == 1

    clock[0] = 102.0
    node.timer_callback()
    assert node.info_image is None
    assert node.lcd.events[-1] == ("img_show", node.gif_frames[0])


def test_last_republished_card_expires_and_standby_restores_backlight(face):
    node, clock = face
    node.power_mode = "standby"
    node.display_sleeping = True
    _send(node, hold_s="bad")  # malformed duration uses the finite 15 s default
    assert node.info_until == 115.0
    assert ("wake",) in node.lcd.events

    clock[0] = 101.0
    _send(node, hold_s=2.0)  # CORE's latest publication resets the expiry
    assert node.info_until == 103.0
    node.timer_callback()
    clock[0] = 103.0
    node.timer_callback()
    assert node.info_image is None
    assert node.display_sleeping is True
    assert ("set_backlight", 0) in node.lcd.events
    assert node.lcd.events[-1] == ("sleep",)
