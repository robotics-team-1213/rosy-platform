"""Prepare ROSY's xacro model for Isaac Sim URDF import."""

import argparse
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET


REPOSITORY = Path(__file__).resolve().parents[3]
# The old sibling src/sim/description (D-427 wave 4c moves it to middleware).
DESCRIPTION = REPOSITORY / "src" / "sim" / "description"


def validate_output_path(path: Path) -> Path:
    output = path.resolve()
    if output.is_relative_to(REPOSITORY):
        raise ValueError("Generated artifacts must be written outside the source checkout")
    if os.name == "nt" and not output.is_relative_to(Path("X:/DevTemp").resolve()):
        raise ValueError("On Windows, generated artifacts must be under X:\\DevTemp")
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
    output = validate_output_path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(urdf, encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="URDF output path outside the source tree")
    parser.add_argument("--xacro", default="xacro", help="xacro executable from a ROS 2 Jazzy overlay")
    args = parser.parse_args()
    print(prepare(args.output, args.xacro))


if __name__ == "__main__":
    main()
