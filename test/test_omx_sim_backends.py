"""D-866 P2 shared simulator layer and MuJoCo adapter (tools/sim/omx_topic_backend.py, omx_mujoco_backend.py), ROS-free parts."""

import importlib.util
from pathlib import Path
import sys

import pytest

SIM = Path(__file__).resolve().parents[1] / "tools" / "sim"
URDF = """<robot name="omx_f"><link name="link5"><visual><geometry>
<mesh filename="package://open_manipulator_description/meshes/omx_f/follower_05_tip.stl"/></geometry></visual></link>
<gazebo><plugin filename="gz_ros2_control-system" name="x"/></gazebo>
<ros2_control is_async="true" name="OMXFSystem" type="system"><hardware>
<plugin>mock_components/GenericSystem</plugin><param name="mock_sensor_commands">false</param></hardware>
<joint name="joint1"><command_interface name="position"/></joint>
<gpio name="dxl11"><command_interface name="Goal Position"/></gpio></ros2_control></robot>"""


def _mod(name):
    sys.path.insert(0, str(SIM))
    spec = importlib.util.spec_from_file_location(name, SIM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_vendor_mock_hardware_becomes_the_topic_bridge():
    mod = _mod("omx_topic_backend")
    out = mod.with_topic_hardware(URDF)
    assert "mock_components/GenericSystem" not in out and "topic_based_ros2_control/TopicBasedSystem" in out
    assert mod.SIM_STATES in out and mod.SIM_COMMANDS in out and 'is_async="false"' in out
    assert "<gpio" not in out  # Dynamixel registers exist only on the real driver.
    assert '<joint name="joint1"><command_interface name="position"/>' in out  # Vendor joints untouched.
    with pytest.raises(ValueError):
        mod.with_topic_hardware(URDF.replace("<hardware>", "<hardware/><x>", 1))


def test_mujoco_urdf_drops_ros_blocks_and_resolves_meshes():
    mod = _mod("omx_mujoco_backend")
    out = mod.mjcf_urdf(URDF, "/share/meshes/omx_f")
    assert "<gazebo" not in out and "<ros2_control" not in out
    assert 'filename="follower_05_tip.stl"' in out and 'meshdir="/share/meshes/omx_f"' in out
    assert out.index("<mujoco>") < out.index("<link")


def test_adjacent_links_come_from_urdf_joints_without_the_world_anchor():
    mod = _mod("omx_mujoco_backend")
    urdf = ('<joint name="world_fixed" type="fixed"><parent link="world"/><child link="link0"/></joint>'
            '<joint name="joint1" type="revolute"><origin/><parent link="link0"/>\n<child link="link1"/></joint>'
            '<ros2_control><joint name="joint1"><command_interface name="position"/></joint></ros2_control>')
    assert mod.adjacent_links(urdf) == [("link0", "link1")]
