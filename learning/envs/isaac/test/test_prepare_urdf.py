import importlib.util
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest


MODULE = Path(__file__).parents[1] / "prepare_urdf.py"
spec = importlib.util.spec_from_file_location("prepare_urdf", MODULE)
prepare_urdf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare_urdf)


def test_mesh_uris_resolve_to_existing_description_assets():
    description = prepare_urdf.DESCRIPTION
    xml = '<robot><link name="body"><visual><geometry><mesh filename="package://description/meshes/visual/base_link.dae"/></geometry></visual></link></robot>'
    root = ET.fromstring(prepare_urdf.resolve_meshes(xml, description))
    uri = root.find(".//mesh").attrib["filename"]
    assert uri == (description / "meshes/visual/base_link.dae").resolve().as_uri()


def test_missing_or_escape_mesh_fails_before_import():
    description = prepare_urdf.DESCRIPTION
    for filename in ("package://description/../private/secret.dae", "package://description/meshes/missing.dae"):
        xml = f'<robot><mesh filename="{filename}"/></robot>'
        with pytest.raises(ValueError):
            prepare_urdf.resolve_meshes(xml, description)


def test_unknown_package_uri_fails_before_import():
    description = prepare_urdf.DESCRIPTION
    with pytest.raises(ValueError, match="package"):
        prepare_urdf.resolve_meshes('<robot><mesh filename="package://other/mesh.dae"/></robot>', description)


def test_generated_urdf_cannot_be_written_into_checkout():
    candidate = Path(__file__).parents[1] / "generated.urdf"
    with pytest.raises(ValueError, match="outside"):
        prepare_urdf.validate_output_path(candidate)


def reference_body():
    return ET.fromstring('''<robot name="pinky">
      <link name="base_footprint"/>
      <link name="base_link">
        <inertial><origin xyz="-.025 0 .025" rpy="0 0 0"/>
          <mass value=".8"/><inertia ixx=".001" iyy=".002" izz=".003" ixy="0" ixz="0" iyz="0"/></inertial>
        <collision><origin xyz=".01 -.02 .03"/><geometry><box size=".1 .08 .1"/></geometry></collision>
        <visual><geometry><mesh filename="original.dae"/></geometry></visual>
      </link>
      <link name="wheel"><inertial><mass value=".2"/></inertial></link>
      <joint name="base_link_fixed_joint" type="fixed">
        <parent link="base_footprint"/><child link="base_link"/><origin xyz="0 0 .028" rpy="0 0 0"/>
      </joint>
      <joint name="wheel_joint" type="continuous">
        <parent link="base_link"/><child link="wheel"/><origin xyz=".01 .05 -.01" rpy="0 1.57 0"/>
      </joint>
    </robot>''')


def test_mass_reference_conversion_preserves_physical_mass_com_and_link_poses():
    root = reference_body()
    inertia = ET.tostring(root.find("./link[@name='base_link']/inertial/inertia"))
    prepare_urdf.promote_base_mass(root)
    foot = root.find("./link[@name='base_footprint']")
    assert sum(float(m.get('value')) for m in root.findall('./link/inertial/mass')) == pytest.approx(1.)
    assert float(foot.find('inertial/mass').get('value')) == pytest.approx(.8)
    assert ET.tostring(foot.find('inertial/inertia')) == inertia
    assert list(map(float, foot.find('inertial/origin').get('xyz').split())) == pytest.approx((-.025, 0., .053))
    assert list(map(float, foot.find('collision/origin').get('xyz').split())) == pytest.approx((.01, -.02, .058))
    assert list(map(float, foot.find('visual/origin').get('xyz').split())) == pytest.approx((0., 0., .028))
    assert foot.find('visual/geometry/mesh').get('filename') == 'original.dae'
    assert len(root.find("./link[@name='base_link']")) == 0
    wheel = root.find("./joint[@name='wheel_joint']")
    assert wheel.find('parent').get('link') == 'base_footprint'
    assert list(map(float, wheel.find('origin').get('xyz').split())) == pytest.approx((.01, .05, .018))
    assert wheel.find('origin').get('rpy') == '0 1.57 0'
    assert root.find("./joint[@name='base_link_fixed_joint']/origin").get('xyz') == '0 0 .028'


@pytest.mark.parametrize('xyz,rpy', [('0 0 nan', '0 0 0'), ('0 0 .028', '0 .1 0'), ('0 .028', '0 0 0')])
def test_invalid_reference_transform_is_rejected_before_any_asset_mutation(xyz, rpy):
    root = reference_body()
    root.find("./joint[@name='base_link_fixed_joint']/origin").attrib.update(xyz=xyz, rpy=rpy)
    before = ET.tostring(root)
    with pytest.raises(ValueError):
        prepare_urdf.promote_base_mass(root)
    assert ET.tostring(root) == before


def test_prepared_asset_uses_the_physical_footprint_root(monkeypatch, tmp_path):
    from types import SimpleNamespace
    monkeypatch.setattr(prepare_urdf.subprocess, 'run', lambda *a, **k:
                        SimpleNamespace(stdout=ET.tostring(reference_body(), encoding='unicode')))
    path = prepare_urdf.prepare(tmp_path / 'pinky.urdf')
    root = ET.parse(path).getroot()
    assert root.find("./link[@name='base_footprint']/inertial/mass").get('value') == '.8'
    assert len(root.find("./link[@name='base_link']")) == 0


@pytest.mark.skipif(not shutil.which("xacro"), reason="requires a sourced ROS 2 xacro overlay")
def test_isaac_render_keeps_sim_collision_and_drops_gazebo_plugins():
    source = prepare_urdf.DESCRIPTION / "urdf/robot.urdf.xacro"
    rendered = subprocess.run(
        ["xacro", str(source), "is_sim:=true", "sim_backend:=isaac", "namespace:="],
        check=True, capture_output=True, text=True,
    ).stdout
    root = ET.fromstring(rendered)
    assert not list(root.iter("gazebo"))
    assert root.find("./link[@name='base_link']/collision/geometry/box") is not None
    assert {joint.get("name") for joint in root.iter("joint")} >= {"l_wheel_joint", "r_wheel_joint"}
