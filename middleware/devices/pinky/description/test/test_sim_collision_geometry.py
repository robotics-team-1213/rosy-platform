"""Rendered collision geometry contracts for the Gazebo model."""

from __future__ import annotations

import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ROBOT_XACRO = ROOT / "urdf" / "robot.urdf.xacro"


def _render_robot(*, is_sim: bool, has_cargo_tray: bool = True) -> ET.Element:
    if shutil.which("xacro") is None:
        pytest.skip("xacro is not installed")
    result = subprocess.run(
        [
            "xacro",
            str(ROBOT_XACRO),
            f"is_sim:={'true' if is_sim else 'false'}",
            f"has_cargo_tray:={'true' if has_cargo_tray else 'false'}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return ET.fromstring(result.stdout)


def _collision_geometry_tags(robot: ET.Element) -> list[str]:
    return [
        geometry[0].tag
        for collision in robot.findall(".//collision")
        if (geometry := collision.find("geometry")) is not None and len(geometry)
    ]


def test_simulation_collisions_use_dart_supported_primitives():
    tags = _collision_geometry_tags(_render_robot(is_sim=True))

    assert tags
    assert "mesh" not in tags
    assert set(tags) <= {"box", "cylinder", "sphere"}


def test_physical_description_keeps_detailed_collision_meshes():
    tags = _collision_geometry_tags(_render_robot(is_sim=False))

    assert tags.count("mesh") == 8
    assert _collision_geometry_tags(_render_robot(is_sim=False, has_cargo_tray=False)).count("mesh") == 7


def test_cargo_tray_sim_pocket_colliders_clear_container_lidar_and_caster():
    robot = _render_robot(is_sim=True)
    tray_link = robot.find("./link[@name='cargo_tray_link']")
    assert tray_link is not None
    boxes = tray_link.findall("./collision/geometry/box")
    assert len(boxes) == 6

    pocket_joint = robot.find("./joint[@name='cargo_tray_pocket_fixed_joint']")
    assert pocket_joint is not None
    px, py, pz = map(float, pocket_joint.find("./origin").attrib["xyz"].split())
    # Canonical 1x3 container (0.030 x 0.090 x 0.0344 m) seated 0.5 mm over deck floor must fit inside pocket cleanly.
    c_min = (px - 0.015, py - 0.045, pz + 0.0005)
    c_max = (px + 0.015, py + 0.045, pz + 0.0005 + 0.0344)
    for col in tray_link.findall("./collision"):
        ox, oy, oz = map(float, col.find("./origin").attrib["xyz"].split())
        sx, sy, sz = map(float, col.find("./geometry/box").attrib["size"].split())
        b_min = (ox - sx / 2.0, oy - sy / 2.0, oz - sz / 2.0)
        b_max = (ox + sx / 2.0, oy + sy / 2.0, oz + sz / 2.0)
        overlap = all(min(c_max[i], b_max[i]) > max(c_min[i], b_min[i]) for i in range(3))
        assert not overlap, f"container intersects tray collider {col}"

    # Loaded cargo top (base_footprint z = 0.028 + c_max[2]) stays well under rplidar_link plane (z = 0.125 m).
    assert 0.028 + c_max[2] <= 0.125 - 0.035

    # Tray + cargo still keeps combined CoM forward of rear caster (x = -0.0695 m in base_link).
    mass = float(tray_link.find("./inertial/mass").attrib["value"])
    assert 0.030 <= mass <= 0.060
    tx = float(tray_link.find("./inertial/origin").attrib["xyz"].split()[0])
    combined_com_x = (1.54 * -0.015 + mass * tx + 0.030 * px) / (1.54 + mass + 0.030)
    assert combined_com_x > -0.050


def test_sim_drive_wheels_use_axial_cylinders_not_slipping_spheres():
    source = (ROOT / "urdf" / "rosy.urdf.xacro").read_text(encoding="utf-8")
    wheel_macro = source.split(
        '<xacro:macro name="insert_wheel"', 1
    )[1].split("</xacro:macro>", 1)[0]

    assert '<cylinder radius="0.028" length="0.016"/>' in wheel_macro
    assert 'rpy="${pi/2} 0 0"' in wheel_macro
    assert '<sphere radius="0.028"/>' not in wheel_macro


def test_sim_drive_wheels_allow_lateral_scrub_for_differential_turns():
    source = (ROOT / "urdf" / "rosy_gz.urdf.xacro").read_text(encoding="utf-8")
    left_wheel = source.split(
        '<gazebo reference="l_wheel">', 1
    )[1].split("</gazebo>", 1)[0]
    right_wheel = source.split(
        '<gazebo reference="r_wheel">', 1
    )[1].split("</gazebo>", 1)[0]

    for wheel in (left_wheel, right_wheel):
        assert "<fdir1>1 0 0</fdir1>" in wheel
        assert "<mu1>1.0</mu1>" in wheel
        assert "<mu2>0.05</mu2>" in wheel
        assert "<mu1>200</mu1>" not in wheel
        assert "<mu2>200</mu2>" not in wheel


def test_sim_slam_uses_model_pose_odom_and_keeps_wheel_odom_for_diagnostics():
    source = (ROOT / "urdf" / "rosy_gz.urdf.xacro").read_text(encoding="utf-8")
    diff_drive = source.split(
        'name="gz::sim::systems::DiffDrive"', 1
    )[1].split("</plugin>", 1)[0]
    truth_odom = source.split(
        'name="gz::sim::systems::OdometryPublisher"', 1
    )[1].split("</plugin>", 1)[0]

    assert "<odom_topic>${namespace}odom_wheel</odom_topic>" in diff_drive
    assert "<tf_topic>${namespace}tf_wheel</tf_topic>" in diff_drive
    assert "<odom_topic>${namespace}odom</odom_topic>" in truth_odom
    assert "<tf_topic>/tf</tf_topic>" in truth_odom
    assert "<odom_frame>${namespace}odom</odom_frame>" in truth_odom
    assert "<robot_base_frame>${namespace}base_footprint</robot_base_frame>" in truth_odom
    assert "<dimensions>2</dimensions>" in truth_odom


def test_sim_camera_render_profile_is_tunable_with_existing_defaults():
    robot = ROBOT_XACRO.read_text(encoding="utf-8")
    model = (ROOT / "urdf" / "rosy.urdf.xacro").read_text(encoding="utf-8")
    gazebo = (ROOT / "urdf" / "rosy_gz.urdf.xacro").read_text(
        encoding="utf-8")

    assert '<xacro:arg name="camera_width" default="1280"/>' in robot
    assert '<xacro:arg name="camera_height" default="720"/>' in robot
    assert '<xacro:arg name="camera_update_rate" default="10"/>' in robot
    assert "camera_width:=1280 camera_height:=720 camera_update_rate:=10" in model
    assert "<width>${camera_width}</width>" in gazebo
    assert "<height>${camera_height}</height>" in gazebo
    assert "<update_rate>${camera_update_rate}</update_rate>" in gazebo
