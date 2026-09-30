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
    description = Path(__file__).parents[2] / "description"
    xml = '<robot><link name="body"><visual><geometry><mesh filename="package://description/meshes/visual/base_link.dae"/></geometry></visual></link></robot>'
    root = ET.fromstring(prepare_urdf.resolve_meshes(xml, description))
    uri = root.find(".//mesh").attrib["filename"]
    assert uri == (description / "meshes/visual/base_link.dae").resolve().as_uri()


def test_missing_or_escape_mesh_fails_before_import():
    description = Path(__file__).parents[2] / "description"
    for filename in ("package://description/../private/secret.dae", "package://description/meshes/missing.dae"):
        xml = f'<robot><mesh filename="{filename}"/></robot>'
        with pytest.raises(ValueError):
            prepare_urdf.resolve_meshes(xml, description)


def test_unknown_package_uri_fails_before_import():
    description = Path(__file__).parents[2] / "description"
    with pytest.raises(ValueError, match="package"):
        prepare_urdf.resolve_meshes('<robot><mesh filename="package://other/mesh.dae"/></robot>', description)


def test_generated_urdf_cannot_be_written_into_checkout():
    candidate = Path(__file__).parents[1] / "generated.urdf"
    with pytest.raises(ValueError, match="outside"):
        prepare_urdf.validate_output_path(candidate)


@pytest.mark.skipif(not shutil.which("xacro"), reason="requires a sourced ROS 2 xacro overlay")
def test_isaac_render_keeps_sim_collision_and_drops_gazebo_plugins():
    source = Path(__file__).parents[2] / "description/urdf/robot.urdf.xacro"
    rendered = subprocess.run(
        ["xacro", str(source), "is_sim:=true", "sim_backend:=isaac", "namespace:="],
        check=True, capture_output=True, text=True,
    ).stdout
    root = ET.fromstring(rendered)
    assert not list(root.iter("gazebo"))
    assert root.find("./link[@name='base_link']/collision/geometry/box") is not None
    assert {joint.get("name") for joint in root.iter("joint")} >= {"l_wheel_joint", "r_wheel_joint"}
