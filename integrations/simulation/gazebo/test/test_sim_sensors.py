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


def test_floor_under_each_ray_reads_as_floor_and_a_missing_floor_as_cliff():
    ir = _ir()
    assert ir.ir_raw([0.013, 0.013, 0.013]) == [ir.FLOOR_RAW] * 3
    assert ir.ir_raw([0.013, math.inf, None]) == [ir.FLOOR_RAW, ir.CLIFF_RAW, ir.CLIFF_RAW]
    assert ir.ir_raw([ir.FLOOR_MAX_M + 1e-3, 0.013, math.nan]) == [ir.CLIFF_RAW, ir.FLOOR_RAW, ir.CLIFF_RAW]
    # The safety worker's cliff_mode low thresholds (cliff < 800, clear >= 1500), 12-bit ADC.
    assert ir.FLOOR_RAW >= 1500 and ir.CLIFF_RAW < 800 and ir.FLOOR_RAW < 4000


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
