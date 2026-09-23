"""Structural harness: what `RosBridge.__init__` registers on the node.

**Read this before extending it.** The plan that produced this file rejected a
stubbed-rclpy harness as a *strategy*, for four reasons that have not gone away:
tests against a stub assert stub semantics; QoS, `MultiThreadedExecutor`
re-entrancy, timer scheduling and action futures are exactly what makes the
bridge risky and exactly what a stub erases; it forks an unvalidated rclpy
surface in-tree; and its maintenance cost grows with every message type.

It survived as **one concession**: a stub is the only credible way to make the
3b adapter reshape gradable without a robot, because it can assert that
`__init__` still registers the same timers at the same periods. Structural, not
semantic. That is the whole mandate.

So:

- **Do not** add a test here that calls a callback, drives a tick, or asserts on
  a message value. Those belong in the ROS-free siblings (`translate.py`,
  `display.py`, `reconcile.py`, `odometry.py`, `save_map.py`,
  `battery_policy.py`, `goal_tracker.py`), where no stub is involved.
- **Do not** move the stub into `conftest.py`. It lives in this file so its
  blast radius is this file: nothing else can start depending on stub
  semantics by accident.
- The periods below are the contract. `1/50` is D-2, the sole `cmd_vel`
  publisher, and a reshape that changes it is the failure this exists to catch.
- Every literal here is read off `ros_bridge.py`, never pasted from this
  harness's own output. A baseline derived from the thing it checks ratifies
  whatever that thing currently does — which is how an undeclared costmap
  change once got pinned without anyone reviewing it.

What it still cannot see, so that nobody mistakes green for verified: whether a
callback *does* the right thing, whether QoS means what the profile says on a
real DDS, and anything about executor re-entrancy or action futures. It proves
the wiring diagram, not the wiring.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest
import yaml

CONFIG_DIR = Path(__file__).parent.parent / "config"

#: The ROS modules `ros_bridge` imports. Each is replaced by a module whose every
#: attribute is a distinct dummy class — enough for `create_publisher(Twist, ...)`
#: to resolve `Twist`, because `__init__` only ever passes these as type
#: arguments and never constructs one.
_ROS_MODULES = [
    "rclpy", "rclpy.action", "rclpy.node", "rclpy.qos",
    "geometry_msgs", "geometry_msgs.msg",
    "nav_msgs", "nav_msgs.msg",
    "nav2_msgs", "nav2_msgs.action", "nav2_msgs.msg",
    "lifecycle_msgs", "lifecycle_msgs.msg",
    "sensor_msgs", "sensor_msgs.msg",
    "std_msgs", "std_msgs.msg",
    "std_srvs", "std_srvs.srv",
    "interfaces", "interfaces.srv",
    "tf2_ros",
    # Stubbed so the optional-import branch at `ros_bridge.py` is *taken*, and the
    # fourth service client is part of the contract rather than an accident of
    # what happens to be installed on the machine running the suite.
    "slam_toolbox", "slam_toolbox.srv",
]


class _Permissive(type):
    """Metaclass so `ReliabilityPolicy.RELIABLE` and friends resolve to something."""

    def __getattr__(cls, name: str) -> Any:
        created = _Permissive(name, (), {})
        setattr(cls, name, created)
        return created


class _Anything(types.ModuleType):
    """A module that answers any attribute with a fresh permissive dummy class."""

    def __getattr__(self, name: str) -> Any:
        def initialize(instance, *args, **kwargs):
            for key, value in kwargs.items():
                setattr(instance, key, value)

        created = _Permissive(name, (), {"__init__": initialize})
        setattr(self, name, created)
        return created


def _qos_kind(qos) -> object:
    """`10` for a plain depth, `"SENSOR"` for sensor-data, `"LATCHED"` for latch.

    Three endpoints are latched (`TRANSIENT_LOCAL`, depth 1) and the latch is
    load-bearing: PWR-003 needs a late-joining node to receive the current
    power mode immediately. Losing it is invisible on the host and presents on
    a robot as "a node that started late never learned the mode".

    Scan/imu/range must not look latched (D-119). The stub `qos_profile_sensor_data`
    is a dummy type whose name is the import name.
    """
    if isinstance(qos, int):
        return qos
    name = getattr(qos, "__name__", None) or type(qos).__name__
    if name == "qos_profile_sensor_data":
        return "SENSOR"
    reliability = getattr(qos, "reliability", None)
    if (getattr(qos, "depth", None) == 1
            and getattr(reliability, "__name__", "") == "BEST_EFFORT"):
        return "PREVIEW"
    return "LATCHED"


class RecordingNode:
    """Records what the bridge registers. Executes nothing."""

    def __init__(self) -> None:
        self.timers: list[float] = []
        self.subscriptions: list[tuple[str, str]] = []
        self.publishers: list[tuple[str, object]] = []
        self.clients: list[str] = []

    def create_timer(self, period_s, _callback):
        self.timers.append(period_s)
        return object()

    def create_subscription(self, _type, topic, callback, qos):
        # The callback is the point: the reshape's core operation is rewiring
        # topic -> handler across module boundaries, and a topic-only baseline
        # cannot see `scan` pointed at `_on_imu`.
        self.subscriptions.append((topic, callback.__name__, _qos_kind(qos)))
        return object()

    def create_publisher(self, _type, topic, qos):
        self.publishers.append((topic, _qos_kind(qos)))
        return object()

    def create_client(self, _type, name):
        self.clients.append(name)
        return types.SimpleNamespace(service_is_ready=lambda: False)

    def get_logger(self):
        return types.SimpleNamespace(
            info=lambda *a, **k: None, warn=lambda *a, **k: None,
            warning=lambda *a, **k: None, error=lambda *a, **k: None,
            debug=lambda *a, **k: None)

    def get_parameter(self, name):
        # rclpy declares `use_sim_time` on every node; the bridge reads it once.
        assert name == "use_sim_time"
        return types.SimpleNamespace(value=False)

    def get_clock(self):
        # nanoseconds: D-137 T4 — 브리지가 자문 피드에 노드 시계를 바인딩한다.
        return types.SimpleNamespace(
            now=lambda: types.SimpleNamespace(nanoseconds=0.0,
                                              to_msg=lambda: None))


@pytest.fixture
def registered(tmp_path, monkeypatch):
    """Build a `RosBridge` against stubbed ROS. Returns node, bridge and services."""
    import core.bridge as bridge_pkg
    from core_common.profile import RobotProfile
    from core.services import CoreServices

    for name in _ROS_MODULES:
        monkeypatch.setitem(sys.modules, name, _Anything(name))

    # The stubs unwind on their own; the module *built against* them does not.
    # Both the `sys.modules` entry and the parent-package attribute have to go,
    # and they have to go on the way *out* — monkeypatch cannot record an undo
    # for a key that does not exist yet at setup time. Left in place, the
    # stub-bound module outlives the fixture and the next test to import it gets
    # a result that depends on file ordering.
    key = "core.bridge.ros_bridge"
    sys.modules.pop(key, None)

    def read(name):
        return yaml.safe_load((CONFIG_DIR / name).read_text(encoding="utf-8"))

    config = read("rosy_default.yaml")
    services = CoreServices.build(
        config, RobotProfile.load(CONFIG_DIR / "profile.pinky_pro.yaml"),
        read("capabilities.yaml"), tmp_path / "wp.json")

    from core.bridge.ros_bridge import RosBridge

    node = RecordingNode()
    bridge = RosBridge(node, services)
    yield types.SimpleNamespace(node=node, bridge=bridge, services=services)

    sys.modules.pop(key, None)
    if getattr(bridge_pkg, "ros_bridge", None) is not None:
        delattr(bridge_pkg, "ros_bridge")


#: Period in seconds, in registration order. `1/50` is D-2's sole `cmd_vel`
#: publisher; `1/10` is `state.rate_hz` from `rosy_default.yaml`.
EXPECTED_TIMERS = [
    1.0 / 50.0, 1.0 / 10.0, 1.0, 1.0 / 5.0, 1.0 / 5.0, 1.0 / 5.0,
    1.0 / 20.0,
]

#: `(topic, callback, qos)` — read off `ros_bridge.py:89-103`, not off this
#: harness's own output. Topic alone would not see `scan` rewired to `_on_imu`,
#: and QoS alone would not see the `map` latch dropped.
EXPECTED_SUBSCRIPTIONS = [
    ("odom", "_on_odom", 10),
    ("battery/voltage", "_on_battery", 10),
    ("nav_cmd_vel", "_on_nav_cmd_vel", 10),
    ("line/observation", "_on_line_observation", 10),
    ("detection_evidence", "_on_detection_evidence", 10),
    ("road/observation", "_on_road_observation", 10),
    ("camera/preview/compressed", "_on_camera_preview", "PREVIEW"),
    ("amcl/transition_event", "_on_amcl_transition", 10),
    ("map_server/transition_event", "_on_map_server_transition", 10),
    ("slam_toolbox/transition_event", "_on_slam_transition", 10),
    ("controller_server/transition_event", "_on_controller_transition", 10),
    ("local_costmap/local_costmap/transition_event", "_on_local_costmap_transition", 10),
    ("global_costmap/global_costmap/transition_event", "_on_global_costmap_transition", 10),
    ("motor/ready", "_on_motor_ready", "LATCHED"),
    ("robot/hitl_request", "_on_hitl_request", 10),
    ("robot/degraded_modules", "_on_degraded_modules", 10),
    ("scan", "_on_scan", "SENSOR"),
    ("imu_raw", "_on_imu", "SENSOR"),
    ("us_sensor/range", "_on_us_range", "SENSOR"),
    ("batt_state", "_on_batt_state", 10),
    ("map", "_on_map", "LATCHED"),
    ("plan", "_on_plan", 10),
    ("local_costmap/costmap_raw", "_on_local_costmap", 10),
    ("global_costmap/costmap_raw", "_on_global_costmap", 10),
]

#: `(topic, qos)` — `ros_bridge.py:81-107`.
EXPECTED_PUBLISHERS = [
    ("cmd_vel", 10),
    ("initialpose", 10),
    ("power/mode", "LATCHED"),
    ("display/info", 10),
    ("docking/collision_exemption", "LATCHED"),
]

#: Four, not three. The fourth is behind the optional `slam_toolbox` import and
#: the harness stubs that module so the branch is always taken — otherwise this
#: literal would pin whatever happened to be installed, and a reshape could drop
#: `_slam_client` entirely and stay green.
EXPECTED_CLIENTS = ["set_led", "start_motor", "stop_motor", "slam_toolbox/save_map"]


def test_the_bridge_registers_timers_at_the_expected_periods(registered):
    """The one thing this harness exists to hold across a reshape.

    Moving the timers must not change how many there are, how fast they run, or
    the order they are created in. A dropped timer is a subsystem that silently
    stops ticking.
    """
    assert registered.node.timers == EXPECTED_TIMERS


def test_the_cmd_vel_timer_is_first_and_fifty_hertz(registered):
    """D-2 called out on its own, because it is the one with a safety argument."""
    assert registered.node.timers[0] == pytest.approx(0.02)


def test_every_subscription_keeps_its_topic_callback_and_qos(registered):
    assert registered.node.subscriptions == EXPECTED_SUBSCRIPTIONS


def test_every_publisher_keeps_its_topic_and_qos(registered):
    """`cmd_vel` first and once: D-2 says there is exactly one publisher."""
    assert registered.node.publishers == EXPECTED_PUBLISHERS
    assert [topic for topic, _ in registered.node.publishers].count("cmd_vel") == 1


def test_the_three_latched_endpoints_stay_latched(registered):
    """PWR-003 needs a late-joining node to receive the current mode at once.
    A dropped latch is invisible on the host and intermittent on a robot."""
    latched = {topic for topic, qos in registered.node.publishers if qos == "LATCHED"}
    latched |= {t for t, _cb, qos in registered.node.subscriptions if qos == "LATCHED"}

    assert latched == {"map", "power/mode", "docking/collision_exemption", "motor/ready"}


def test_the_bridge_opens_the_same_service_clients(registered):
    assert registered.node.clients == EXPECTED_CLIENTS


def test_the_nav2_action_client_and_tf_listener_are_built(registered):
    """Neither goes through `node.create_*`, so the recording node cannot see
    them. They are where a navigation adapter would put them, so assert directly."""
    assert registered.bridge.nav_client is not None
    assert registered.bridge.tf_buffer is not None
    assert registered.bridge.tf_listener is not None


def test_both_executor_contracts_are_wired_to_the_bridge(registered):
    """C3 itself: one class answering two Protocols. A composition root has to
    reproduce these two assignments, and nothing else checks that it did."""
    assert registered.services.nav.executor is registered.bridge
    assert registered.services.docking.executor is registered.bridge


def test_lifecycle_transition_parser_accepts_active_id_and_label(registered):
    active_id = types.SimpleNamespace(goal_state=types.SimpleNamespace(id=3, label="inactive"))
    inactive = types.SimpleNamespace(goal_state=types.SimpleNamespace(id=2, label="active"))
    label_only = types.SimpleNamespace(goal_state=types.SimpleNamespace(id="bad", label="ACTIVE"))

    assert registered.bridge._lifecycle_active(active_id) is True
    assert registered.bridge._lifecycle_active(inactive) is False
    assert registered.bridge._lifecycle_active(label_only) is True
