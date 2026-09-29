"""map_v2_fleet real-profile launch (D-353 5): the Gazebo camera is the Pinky one."""

import ast
import math
from pathlib import Path

import yaml

from test_map_v2_fleet_launch import _urdf_camera_on_base_footprint

ROOT = Path(__file__).resolve().parents[3]
LAUNCH = ROOT / "sim" / "gz_sim" / "launch" / "map_v2_fleet_real.launch.py"
NOMINAL = ROOT / "runtime" / "sensing" / "config" / "camera_nominal_pinky_pro.yaml"
BUNDLE = ROOT / "runtime" / "sensing" / "map" / "map_v2_fleet"


def _constants():
    tree = ast.parse(LAUNCH.read_text(encoding="utf-8"))
    names = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and node.targets[0].id.startswith("REAL_"):
            names[node.targets[0].id] = eval(  # noqa: S307 - literal math only
                compile(ast.Expression(node.value), "launch", "eval"), {"math": math})
    return names


def test_camera_matches_the_nominal_pinky_profile():
    c = _constants()
    nominal = yaml.safe_load(NOMINAL.read_text(encoding="utf-8"))
    fx = nominal["width"] / 2.0 / math.tan(c["REAL_HFOV_RAD"] / 2.0)
    assert abs(fx - nominal["fx"]) < 0.1
    assert abs(math.radians(c["REAL_TILT_DEG"]) - nominal["pitch_rad"]) < 1e-3
    assert c["REAL_CAMERA_HEIGHT_M"] == nominal["height_m"]
    source = LAUNCH.read_text(encoding="utf-8")
    assert '"camera_width": "320"' in source
    assert '"camera_height": "240"' in source


def test_declared_ground_is_where_the_urdf_puts_the_sensor():
    c = _constants()
    x, z = _urdf_camera_on_base_footprint(
        math.radians(c["REAL_TILT_DEG"]), c["REAL_CAM_MOUNT_Z"])
    assert abs(z - c["REAL_CAMERA_HEIGHT_M"]) < 1e-4
    assert abs(x - c["REAL_CAMERA_X_OFFSET_M"]) < 1e-4


def test_launch_uses_the_real_world_and_only_core_commands_motion():
    source = LAUNCH.read_text(encoding="utf-8")
    assert '"map_v2_fleet_real.world"' in source
    assert (BUNDLE / "worlds" / "map_v2_fleet_real.world").is_file()
    assert (BUNDLE / "textures" / "carpet_grey.png").is_file()
    assert '"camera_ground_source": "GAZEBO"' in source
    assert 'DeclareLaunchArgument("camera_lane_mode", default_value="edge_left")' in source
    assert 'executable="core"' in source
    assert "cmd_vel" not in source


def test_default_camera_args_keep_the_lap_bench_camera():
    sim = (ROOT / "sim" / "gz_sim" / "launch" / "launch_sim.launch.xml").read_text(encoding="utf-8")
    assert '<arg name="camera_hfov" default="1.1519"/>' in sim
    assert '<arg name="cam_mount_z" default="0.0495"/>' in sim
