"""Minimal rclpy / message / DYNAMIXEL SDK stand-ins for host behaviour tests.

Only what bringup's nodes touch. Installed into ``sys.modules`` by the
``ros_stubs`` fixture (conftest.py) and removed again after each test, so the
real packages are never needed and never shadowed outside the test.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace


class Msg:
    """Any ROS message: keyword fields, nested fields appear on first access."""

    def __init__(self, **fields):
        self.__dict__.update(fields)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        value = Msg()
        setattr(self, name, value)
        return value


def _msg_type(name):
    return type(name, (Msg,), {})


class Time:
    def __init__(self, nanoseconds):
        self.nanoseconds = nanoseconds

    def __sub__(self, other):
        return Time(self.nanoseconds - other.nanoseconds)

    def to_msg(self):
        return Msg(nanosec=self.nanoseconds)


class Clock:
    def __init__(self):
        self._ns = 0

    def now(self):
        self._ns += 33_000_000
        return Time(self._ns)


class Logger:
    def __init__(self, sink):
        self._sink = sink

    def _log(self, level, text, **_kwargs):
        self._sink.append((level, text))

    def info(self, text, **kwargs):
        self._log("info", text, **kwargs)

    def warn(self, text, **kwargs):
        self._log("warn", text, **kwargs)

    warning = warn

    def error(self, text, **kwargs):
        self._log("error", text, **kwargs)


class Publisher:
    def __init__(self, topic):
        self.topic = topic
        self.messages = []

    def publish(self, message):
        self.messages.append(message)


class World:
    """Everything the stubbed ROS graph saw during one test."""

    def __init__(self):
        self.parameters = {}
        self.publishers = {}
        self.subscriptions = []
        self.timers = []
        self.logs = []
        self.descriptors = {}
        self.sdk_events = []


def install(monkeypatch, world: World) -> None:
    def module(name, **attributes):
        mod = ModuleType(name)
        mod.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, mod)
        return mod

    class Node:
        def __init__(self, name):
            self.node_name = name
            self._clock = Clock()

        def declare_parameter(self, name, value=None, descriptor=None):
            world.descriptors[name] = descriptor
            world.parameters.setdefault(name, value)

        def get_parameter(self, name):
            return SimpleNamespace(value=world.parameters[name])

        def create_publisher(self, _type, topic, _qos):
            publisher = Publisher(topic)
            world.publishers[topic] = publisher
            return publisher

        def create_subscription(self, _type, topic, callback, _qos):
            world.subscriptions.append((topic, callback))
            return SimpleNamespace(topic=topic)

        def create_timer(self, period, callback):
            world.timers.append((period, callback))
            return SimpleNamespace(period=period)

        def get_logger(self):
            return Logger(world.logs)

        def get_clock(self):
            return self._clock

        def destroy_node(self):
            pass

    rclpy = module("rclpy", init=lambda **_k: None, shutdown=lambda: None,
                   spin=lambda _node: None, ok=lambda: True)
    rclpy.node = module("rclpy.node", Node=Node)
    rclpy.qos = module("rclpy.qos", QoSProfile=lambda **k: SimpleNamespace(**k),
                       DurabilityPolicy=SimpleNamespace(TRANSIENT_LOCAL="transient_local"),
                       ReliabilityPolicy=SimpleNamespace(RELIABLE="reliable"))
    module("rcl_interfaces")
    module("rcl_interfaces.msg", ParameterDescriptor=lambda **k: SimpleNamespace(**k))
    for package, names in (("geometry_msgs", ("Twist", "TransformStamped")),
                           ("nav_msgs", ("Odometry",)),
                           ("sensor_msgs", ("JointState",)),
                           ("std_msgs", ("Bool", "Float32", "UInt16MultiArray"))):
        module(package)
        module(f"{package}.msg", **{name: _msg_type(name) for name in names})
    module("tf2_ros", TransformBroadcaster=lambda _node: SimpleNamespace(sendTransform=lambda _t: None))
    module("tf_transformations", quaternion_from_euler=lambda *_a: (0.0, 0.0, 0.0, 1.0))
    install_sdk(monkeypatch, world, module)


def install_sdk(monkeypatch, world: World, module) -> None:
    events = world.sdk_events

    class Port:
        def __init__(self, device):
            self.device = device

        def openPort(self):
            events.append(("open",))
            return True

        def setBaudRate(self, baudrate):
            events.append(("baud", baudrate))
            return True

        def closePort(self):
            events.append(("close",))

    class Packet:
        def __init__(self, _protocol):
            pass

        def reboot(self, _port, motor_id):
            events.append(("reboot", motor_id))
            return 0, 0

        def write1ByteTxRx(self, _port, motor_id, address, value):
            events.append(("write1", motor_id, address, value))
            return 0, 0

        def write4ByteTxRx(self, _port, motor_id, address, value):
            events.append(("write4", motor_id, address, value))
            return 0, 0

        def read4ByteTxRx(self, _port, motor_id, address):
            events.append(("read4", motor_id, address))
            return 0, 0, 0

    class SyncWrite:
        def __init__(self, *_args):
            self.params = []

        def clearParam(self):
            self.params = []

        def addParam(self, motor_id, param):
            self.params.append((motor_id, bytes(param)))
            return True

        def txPacket(self):
            events.append(("goal", tuple(self.params)))
            return 0

    class BulkRead:
        def __init__(self, *_args):
            pass

        def clearParam(self):
            pass

        def addParam(self, *_args):
            return True

        def txRxPacket(self):
            events.append(("feedback",))
            return 0

        def isAvailable(self, *_args):
            return True

        def getData(self, motor_id, address, _length):
            return 0 if address == 128 else 1000 * motor_id

    module("dynamixel_sdk", COMM_SUCCESS=0, PortHandler=Port, PacketHandler=Packet,
           GroupSyncWrite=SyncWrite, GroupBulkRead=BulkRead,
           DXL_LOBYTE=lambda v: v & 0xFF, DXL_HIBYTE=lambda v: (v >> 8) & 0xFF,
           DXL_LOWORD=lambda v: v & 0xFFFF, DXL_HIWORD=lambda v: (v >> 16) & 0xFFFF)
