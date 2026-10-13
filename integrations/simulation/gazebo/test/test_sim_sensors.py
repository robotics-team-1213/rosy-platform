"""Gazebo IMU + IR floor sensors: opt-in per launch, device-shaped topics, never in device config."""

import importlib.util
import math
import re
import struct
import sys
from types import SimpleNamespace
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
DESCRIPTION = REPO / "middleware" / "devices" / "pinky" / "description" / "urdf"
SAFETY_ADAPTER = REPO / "middleware" / "drive" / "safety" / "adapter"


def _ir():
    spec = importlib.util.spec_from_file_location("sim_ir_floor", ROOT / "scripts" / "sim_ir_floor.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _declared(name, path):
    text = (SAFETY_ADAPTER / path).read_text(encoding="utf-8")
    return int(re.search(rf"declare_parameter\('{name}', (\d+)\)", text).group(1))


def test_floor_under_each_ray_reads_as_floor_and_a_missing_floor_as_cliff():
    ir = _ir()
    assert ir.ir_raw([0.013, 0.013, 0.013]) == [ir.FLOOR_RAW] * 3
    assert ir.ir_raw([0.013, math.inf, 0.2]) == [ir.FLOOR_RAW, ir.CLIFF_RAW, ir.CLIFF_RAW]
    assert ir.ir_raw([ir.FLOOR_MAX_M + 1e-3, 0.013, math.nan]) == [ir.CLIFF_RAW, ir.FLOOR_RAW, ir.CLIFF_RAW]


def test_no_frame_until_every_channel_has_a_reading():
    ir = _ir()
    assert ir.ir_raw([None, 0.013, 0.013]) is None
    assert ir.ir_raw([0.013, 0.013, None]) is None


def test_ir_node_never_refreshes_floor_from_a_stale_channel(monkeypatch):
    callbacks, published, timers = {}, [], []
    now = [1_000_000_000]
    node = SimpleNamespace(
        create_publisher=lambda *_: SimpleNamespace(publish=lambda msg: published.append(msg.data)),
        create_subscription=lambda _type, topic, callback, _qos: callbacks.setdefault(topic, callback),
        create_timer=lambda _period, callback: timers.append(callback),
        get_clock=lambda: SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=now[0])),
        destroy_node=lambda: None)

    def send(name, stamp, distance=.013):
        callbacks['ir_sim/' + name](SimpleNamespace(ranges=[distance],
            header=SimpleNamespace(stamp=SimpleNamespace(sec=stamp, nanosec=0))))

    def spin(_node):
        send('left', 1); send('right', 1)
        timers[0]()
        assert published == []
        send('mid', 1)
        timers[0]()
        assert published == [[2000] * 3]
        now[0] = 2_000_000_000
        send('mid', 2); send('right', 2); timers[0]()
        assert published == [[2000] * 3]  # Left never reported this frame.
        send('left', 2, math.inf)
        timers[0]()
        assert published == [[2000] * 3, [100, 2000, 2000]]
        send('left', 2); send('mid', 2); send('right', 2)
        timers[0]()
        send('left', 1); send('mid', 1); send('right', 1)
        timers[0]()
        assert len(published) == 2  # Repeated or replayed timestamps cannot refresh evidence.
        now[0] = 4_000_000_000
        for name in ('left', 'mid', 'right'):
            send(name, 3)
        timers[0]()
        assert len(published) == 2  # A complete but queued old frame is still stale.
        for name in ('left', 'mid', 'right'):
            send(name, 5)
        timers[0]()
        assert len(published) == 2  # /clock has not reached the physics frame yet.
        now[0] = 5_000_000_000
        timers[0]()
        assert published[-1] == [2000] * 3 and len(published) == 3
        now[0] = 6_000_000_000
        send('mid', 6); send('right', 6)
        callbacks['ir_sim/left'](SimpleNamespace(ranges=[.013],
            header=SimpleNamespace(stamp=SimpleNamespace(sec=5, nanosec=1_000_000_000))))
        timers[0]()
        assert len(published) == 3  # Noncanonical time must not alias the next valid frame.

    monkeypatch.setitem(sys.modules, 'rclpy', SimpleNamespace(init=lambda: None,
        create_node=lambda _: node, spin=spin, ok=lambda: True, shutdown=lambda: None))
    monkeypatch.setitem(sys.modules, 'rclpy.qos', SimpleNamespace(qos_profile_sensor_data=object()))
    monkeypatch.setitem(sys.modules, 'sensor_msgs.msg', SimpleNamespace(LaserScan=object))
    monkeypatch.setitem(sys.modules, 'std_msgs.msg', SimpleNamespace(UInt16MultiArray=SimpleNamespace))
    _ir().main()


def test_values_are_valid_ir_on_the_worker_thresholds():
    ir = _ir()
    hazard = (SAFETY_ADAPTER / "hazard.py").read_text(encoding="utf-8")
    assert "all(0 < v < 4000 for v in self.ir_raw)" in hazard  # on_ir validity window
    cliff_max = _declared("cliff_raw_max", "node.py")
    clear = _declared("cliff_clear_raw", "node.py")
    assert 0 < ir.CLIFF_RAW < cliff_max          # a valid reading that trips cliff_mode low
    assert clear <= ir.FLOOR_RAW < 4000           # a valid reading that clears it


def test_channel_order_matches_the_device_adc_node():
    ir = _ir()
    control = REPO / "middleware" / "perception" / "control"
    assert "return [values[2], values[1], values[0]]" in (control / "ir_adc_node.py").read_text(encoding="utf-8")
    calib = (REPO / 'middleware' / 'perception' / 'front_camera' / "perception" / "ir_calibration.py").read_text(encoding="utf-8")
    assert 'CHANNELS = ("left", "centre", "right")' in calib
    assert ir.CHANNELS == ("left", "mid", "right")


def test_ir_rays_hang_from_the_urdf_ir_links():
    gz = (DESCRIPTION / "rosy_gz.urdf.xacro").read_text(encoding="utf-8")
    urdf = (DESCRIPTION / "rosy.urdf.xacro").read_text(encoding="utf-8")
    calls = re.findall(r'<xacro:ir_floor_ray link="(\w+)" name="(\w+)"', gz)
    assert calls == [("ir_l_link", "left"), ("ir_mid_link", "mid"), ("ir_r_link", "right")]
    for link, _ in calls:
        assert f'<link name="{link}"/>' in urdf
    # Pointing straight down from the link origin.
    assert "<pose>0 0 0 0 1.5708 0</pose>" in gz


def test_launch_bridges_extra_sensors_only_on_request():
    sim = (ROOT / "launch" / "launch_sim.launch.xml").read_text(encoding="utf-8")
    assert '<arg name="sim_sensors" default="false"/>' in sim
    assert sim.count('if="$(var sim_sensors)"') == 2
    real = (ROOT / "launch" / "map_v2_fleet_real.launch.py").read_text(encoding="utf-8")
    assert 'DeclareLaunchArgument("sim_sensors", default_value="false")' in real
    bridge = yaml.safe_load((ROOT / "params" / "rosy_bridge_sim_sensors.yaml").read_text(encoding="utf-8"))
    assert {(e["ros_topic_name"], e["ros_type_name"]) for e in bridge} == {
        ("imu_raw", "sensor_msgs/msg/Imu"),
        ("ir_sim/left", "sensor_msgs/msg/LaserScan"),
        ("ir_sim/mid", "sensor_msgs/msg/LaserScan"),
        ("ir_sim/right", "sensor_msgs/msg/LaserScan")}
    assert all(e["direction"] == "GZ_TO_ROS" for e in bridge)
    assert "sim_ir_floor.py" in (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")


def test_sim_overlay_fragment_enforces_with_all_three_sensors():
    raw = yaml.safe_load((ROOT / "config" / "sim_sensors_core.yaml").read_text(encoding="utf-8"))
    assert raw == {"control": {"sensor_adapter": {
        "mode": "enforce", "required": ["lidar", "imu", "ir"], "simulation_sensors": True}}}


def test_no_device_config_carries_the_simulation_flag():
    roots = [REPO / "contracts" / "foundation" / "config", REPO / "middleware" / "devices",
             REPO / "deploy"]
    hits = [p for root in roots for p in root.rglob("*.yaml")
            if "simulation_sensors" in p.read_text(encoding="utf-8", errors="ignore")]
    assert hits == []


def test_gazebo_lidar_covers_one_turn_without_a_repeated_beam():
    # D-468 return_scan_view needs (angle_max - angle_min + increment) == 2 pi, like the C1.
    gz = (DESCRIPTION / "rosy_gz.urdf.xacro").read_text(encoding="utf-8")
    block = gz[gz.index("<sensor name='gpu_lidar'"):]
    samples = int(re.search(r"<samples>(\d+)</samples>", block).group(1))
    expr = {k: re.search(rf"<{k}>\$\{{(.+?)\}}</{k}>", block).group(1) for k in ("min_angle", "max_angle")}
    lo, hi = (eval(expr[k], {"pi": math.pi}) for k in ("min_angle", "max_angle"))  # noqa: S307
    inc = (hi - lo) / (samples - 1)
    assert samples == 640
    assert abs(inc - 2.0 * math.pi / samples) < 1e-12
    assert abs((hi - lo + inc) - 2.0 * math.pi) < 1e-12
    # Ogre2's float32 cubemap lookup wraps at the face edge.
    angle = lo
    for _ in range(samples):
        axes = abs(math.sin(angle)), abs(math.cos(angle))
        uv = 0.5 * (1.0 + min(axes) / max(axes))
        assert struct.unpack('f', struct.pack('f', uv))[0] < 1.0
        angle += inc


def test_gazebo_lidar_noise_stays_within_the_measured_c1():
    # A static real C1 reads at most 3.4 mm per-beam sigma inside 0.5 m
    # (docs/validation/crosswalk-core-gate-sim-2026-10-10/result.md). The safety gate takes
    # the nearest of 640 beams, so a larger sigma pulls every wall about 3 sigma closer.
    gz = (DESCRIPTION / "rosy_gz.urdf.xacro").read_text(encoding="utf-8")
    start = gz.index("<sensor name='gpu_lidar'")
    block = gz[start:gz.index("</sensor>", start)]
    stddev = float(re.search(r"<stddev>([\d.]+)</stddev>", block).group(1))
    resolution = float(re.search(r"<range>.*?<resolution>([\d.]+)</resolution>", block, re.S).group(1))
    assert 0.0 < stddev <= 0.0035
    assert resolution <= 0.001
