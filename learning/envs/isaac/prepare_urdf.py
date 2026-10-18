"""Prepare ROSY's xacro model for Isaac Sim URDF import."""

import argparse
import math
import os
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET


REPOSITORY = Path(__file__).resolve().parents[3]
# The old sibling middleware/devices/pinky/description (D-427 wave 4c moves it to middleware).
DESCRIPTION = REPOSITORY / "middleware" / "devices" / "pinky" / "description"


def validate_output_path(path: Path) -> Path:
    output = path.resolve()
    if output.is_relative_to(REPOSITORY):
        raise ValueError("Generated artifacts must be written outside the source checkout")
    if os.name == "nt" and not output.is_relative_to(Path(os.environ.get("ROSY_SCRATCH") or tempfile.gettempdir()).resolve()):
        raise ValueError("On Windows, generated artifacts must be under ROSY_SCRATCH or the system temp directory")
    return output


def resolve_meshes(urdf: str, description: Path) -> str:
    """Resolve checked description meshes without relying on Isaac's ROS paths."""
    root = ET.fromstring(urdf)
    base = description.resolve()
    prefix = "package://description/"
    for mesh in root.iter("mesh"):
        filename = mesh.get("filename", "")
        if filename.startswith("package://") and not filename.startswith(prefix):
            raise ValueError(f"Unknown package mesh: {filename}")
        if not filename.startswith(prefix):
            continue
        target = (base / filename[len(prefix):]).resolve()
        if not target.is_relative_to(base) or not target.is_file():
            raise ValueError(f"Missing or escaping mesh: {filename}")
        mesh.set("filename", target.as_uri())
    return ET.tostring(root, encoding="unicode")


def promote_base_mass(root):
    """Keep Pinky's footprint frame physical instead of importing a massless root actor."""
    foot = root.find("./link[@name='base_footprint']")
    body = root.find("./link[@name='base_link']")
    joint = root.find("./joint[@name='base_link_fixed_joint']")
    if (foot is None or body is None or joint is None or len(foot) or joint.get('type') != 'fixed'
            or joint.find('parent').get('link') != 'base_footprint'
            or joint.find('child').get('link') != 'base_link' or joint.find('origin') is None
            or body.find('inertial/mass') is None):
        raise ValueError('Empty footprint and physical fixed base link required')
    origin = joint.find('origin')
    offset = tuple(map(float, origin.get('xyz', '0 0 0').split()))
    rotation = tuple(map(float, origin.get('rpy', '0 0 0').split()))
    mass = float(body.find('inertial/mass').get('value'))
    if (len(offset) != 3 or rotation != (0., 0., 0.) or not all(map(math.isfinite, (*offset, mass)))
            or mass <= 0):
        raise ValueError('Finite translation-only base reference and positive mass required')
    parts = [item for item in body if item.tag in ('visual', 'collision', 'inertial')]
    children = [j for j in root.findall('joint') if j.find('parent').get('link') == 'base_link']
    shifted = []
    for item in [*parts, *children]:
        current = item.find('origin')
        xyz = tuple(map(float, current.get('xyz', '0 0 0').split())) if current is not None else (0., 0., 0.)
        if len(xyz) != 3 or not all(map(math.isfinite, xyz)):
            raise ValueError('Finite body and joint origins required')
        shifted.append((item, tuple(a + b for a, b in zip(xyz, offset))))
    for item, xyz in shifted:
        current = item.find('origin')
        if current is None:
            current = ET.SubElement(item, 'origin')
        current.set('xyz', ' '.join(map(str, xyz)))
    for item in parts:
        body.remove(item)
        foot.append(item)
    for child in children:
        child.find('parent').set('link', 'base_footprint')


def prepare(output: Path, xacro_executable: str = "xacro") -> Path:
    source = DESCRIPTION / "urdf" / "robot.urdf.xacro"
    result = subprocess.run(
        [xacro_executable, str(source), "is_sim:=true", "sim_backend:=isaac", "namespace:="],
        check=True, capture_output=True, text=True,
    )
    urdf = resolve_meshes(result.stdout, DESCRIPTION)
    root = ET.fromstring(urdf)
    if root.tag != "robot" or any(element.tag == "gazebo" for element in root.iter()):
        raise ValueError("Isaac URDF must contain a robot without Gazebo plugins")
    promote_base_mass(root)
    output = validate_output_path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(ET.tostring(root, encoding="unicode"), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="URDF output path outside the source tree")
    parser.add_argument("--xacro", default="xacro", help="xacro executable from a ROS 2 Jazzy overlay")
    args = parser.parse_args()
    print(prepare(args.output, args.xacro))


if __name__ == "__main__":
    main()
