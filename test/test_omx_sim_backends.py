"""D-866 P2 shared simulator layer and MuJoCo adapter (tools/sim/omx_topic_backend.py, omx_mujoco_backend.py), ROS-free parts."""

import importlib.util
from pathlib import Path
import re
import sys

import pytest

SIM = Path(__file__).resolve().parents[1] / "tools" / "sim"
ASSETS = Path(__file__).resolve().parents[1] / "learning/envs/isaac/assets"
V21_URDF = ASSETS / "omx_f_palletizing_description/urdf/omx_f_palletizing.urdf"
URDF = """<robot name="omx_f"><link name="link5"><visual><geometry>
<mesh filename="package://open_manipulator_description/meshes/omx_f/follower_05_tip.stl"/></geometry></visual></link>
<gazebo><plugin filename="gz_ros2_control-system" name="x"/></gazebo>
<ros2_control is_async="true" name="OMXFSystem" type="system"><hardware>
<plugin>mock_components/GenericSystem</plugin><param name="mock_sensor_commands">false</param></hardware>
<joint name="joint1"><command_interface name="position"/></joint>
<gpio name="dxl11"><command_interface name="Goal Position"/></gpio></ros2_control></robot>"""
V21 = """<robot name="omx_f_palletizing"><link name="link6"><visual><geometry>
<mesh filename="package://omx_f_palletizing_description/meshes/omx_f/palletizing_jaw6_servo_side_v2_1.stl"/>
</geometry></visual></link></robot>"""


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


def test_initial_staging_seeds_the_ros2_control_position_state():
    mod = _mod("omx_topic_backend")
    urdf = URDF.replace('<command_interface name="position"/></joint>',
                        '<command_interface name="position"/><state_interface name="position"/></joint>')
    out = mod.with_initial(urdf, {"joint1": "1.0"})
    assert '<state_interface name="position"><param name="initial_value">1.0</param></state_interface>' in out
    # The vendor URDF names a joint outside ros2_control too; staging must not run on into the next joint.
    elsewhere = urdf.replace("<ros2_control", '<joint name="gripper_joint_1"></joint><ros2_control', 1)
    with pytest.raises(ValueError):
        mod.with_initial(elsewhere, {"gripper_joint_1": "1.0"})


def test_palletizing_option_grafts_the_vendor_ros2_control_blocks():
    mod = _mod("omx_topic_backend")
    out = mod.with_vendor_control(V21, URDF)
    assert "<ros2_control" in out and "topic_based_ros2_control/TopicBasedSystem" in out  # the grafted vendor block
    assert "<gpio" not in out and 'is_async="false"' in out  # the topic swap applies to it as to the vendor URDF
    assert 'package://omx_f_palletizing_description/' in out  # the v2.1 geometry stays
    assert out.rstrip().endswith("</ros2_control></robot>")  # blocks land inside <robot>
    with pytest.raises(ValueError):
        mod.with_vendor_control(V21, URDF.split("<ros2_control")[0])  # a description without control blocks
    with pytest.raises(ValueError):
        mod.with_vendor_control(V21.replace("</robot>", ""), URDF)  # nothing to graft onto


def test_mujoco_urdf_drops_ros_blocks_and_resolves_meshes():
    mod = _mod("omx_mujoco_backend")
    out = mod.mjcf_urdf(URDF, "/share/meshes/omx_f")
    assert "<gazebo" not in out and "<ros2_control" not in out
    assert 'filename="follower_05_tip.stl"' in out and 'meshdir="/share/meshes/omx_f"' in out
    assert out.index("<mujoco>") < out.index("<link")


def test_palletizing_option_resolves_meshes_from_both_vendored_packages():
    mod = _mod("omx_mujoco_backend")
    out = mod.mjcf_urdf(V21_URDF.read_text(encoding="utf-8"), ASSETS, "palletizing-v2.1")
    assert 'strippath="false"' in out and f'meshdir="{ASSETS}"' in out and "package://" not in out
    meshes = re.findall(r'filename="([^"]+\.stl)"', out)
    assert any("palletizing_jaw6" in m for m in meshes) and any("follower_01" in m for m in meshes)  # both packages
    for mesh in meshes:
        assert (ASSETS / mesh).is_file(), mesh  # every URDF mesh resolves under the vendored assets tree
    # Vendor mode output stays the vendor's: bare names under the one share dir.
    vendor = mod.mjcf_urdf(URDF, "/share/meshes/omx_f")
    assert 'strippath="true"' in vendor and vendor.count('filename="follower_05_tip.stl"') == 1


def test_palletizing_finger_pads_are_the_isaac_pad_boxes():
    sys.path.insert(0, str(ASSETS.parent))
    import palletizing_gripper
    mod = _mod("omx_mujoco_backend")
    # The same vendored-jaw collider ship_release_scene.add_jaw puts on each finger, thin along the pad normal.
    assert mod.pad_box is palletizing_gripper.pad_box
    assert mod.pad_box(1)[1][0] == palletizing_gripper.PAD_THICKNESS_M


def test_adjacent_links_come_from_urdf_joints_without_the_world_anchor():
    mod = _mod("omx_mujoco_backend")
    urdf = ('<joint name="world_fixed" type="fixed"><parent link="world"/><child link="link0"/></joint>'
            '<joint name="joint1" type="revolute"><origin/><parent link="link0"/>\n<child link="link1"/></joint>'
            '<ros2_control><joint name="joint1"><command_interface name="position"/></joint></ros2_control>')
    assert mod.adjacent_links(urdf) == [("link0", "link1")]


def test_cell_world_reads_the_gazebo_work_scene_boxes():
    mod = _mod("omx_cell_world")
    boxes = {b["name"]: b for b in mod.boxes()}
    assert {"table", "pallet_a", "pallet_b", "sheet_stand", "slip_sheet_0", "infeed_block"} <= set(boxes)
    assert boxes["table"]["static"] and boxes["table"]["mass"] is None
    assert not boxes["infeed_block"]["static"] and boxes["infeed_block"]["mass"] == pytest.approx(0.02)
    assert mod.quaternion([0, 0, 0]) == pytest.approx([1, 0, 0, 0])
    assert mod.quaternion([0, 0, 3.141592653589793]) == pytest.approx([0, 0, 0, 1], abs=1e-9)


def test_cell_world_refuses_a_movable_box_without_mass(tmp_path):
    mod = _mod("omx_cell_world")
    world = tmp_path / "w.sdf"
    world.write_text('<sdf><world><model name="b"><pose>0 0 0 0 0 0</pose><link><collision><geometry><box>'
                     '<size>1 1 1</size></box></geometry></collision></link></model></world></sdf>')
    with pytest.raises(ValueError):
        mod.boxes(world)


def test_finger_pads_sit_on_the_calibrated_jaw_contact_point():
    """Both simulator backends grip through pads on this point; it must stay the teacher's calibrated value."""
    import yaml
    mod = _mod("omx_cell_world")
    profile = yaml.safe_load(mod.PROFILE.read_text(encoding="utf-8"))
    assert mod.jaw_contact_point() == tuple(profile["gripper"]["jaw"]["contact_point_m"])
