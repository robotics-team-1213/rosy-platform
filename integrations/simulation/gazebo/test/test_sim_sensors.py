"""Gazebo IMU + IR floor sensors: opt-in per launch, device-shaped topics, never in device config."""

import importlib.util
import math
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
DESCRIPTION = REPO / "middleware" / "apps" / "device" / "pinky" / "description" / "urdf"


def _ir():
    spec = importlib.util.spec_from_file_location("sim_ir_floor", ROOT / "scripts" / "sim_ir_floor.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _declared(name, path):
    text = (REPO / "middleware" / "perception" / "control" / path).read_text(encoding="utf-8")
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


def test_values_are_valid_ir_on_the_worker_thresholds():
    ir = _ir()
    hazard = (REPO / "middleware" / "perception" / "control" / "safety" / "hazard.py").read_text(encoding="utf-8")
    assert "all(0 < v < 4000 for v in self.ir_raw)" in hazard  # on_ir validity window
    cliff_max = _declared("cliff_raw_max", "safety/node.py")
    clear = _declared("cliff_clear_raw", "safety/node.py")
    assert 0 < ir.CLIFF_RAW < cliff_max          # a valid reading that trips cliff_mode low
    assert clear <= ir.FLOOR_RAW < 4000           # a valid reading that clears it


def test_channel_order_matches_the_device_adc_node():
    ir = _ir()
    control = REPO / "middleware" / "perception" / "control"
    assert "return [values[2], values[1], values[0]]" in (control / "ir_adc_node.py").read_text(encoding="utf-8")
    calib = (control / "sensing" / "perception" / "ir_calibration.py").read_text(encoding="utf-8")
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
    roots = [REPO / "contracts" / "foundation" / "config", REPO / "middleware" / "apps" / "device",
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
    assert abs((hi - lo + inc) - 2.0 * math.pi) < inc * 0.1
