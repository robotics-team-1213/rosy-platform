"""Checks that can run before launching the Isaac Sim GPU application."""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname
import xml.etree.ElementTree as ET


ASSETS = Path(__file__).resolve().parent / "assets" / "open_manipulator_description"
PACKAGE_URI = "package://open_manipulator_description/"
EXPECTED_JOINTS = {
    "pinky": {"l_wheel_joint", "r_wheel_joint"},
    "omx_f": {"joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1", "gripper_joint_2"},
    "omx_l": {"joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1"},
}


def check_vendor_manifest(assets: Path = ASSETS) -> int:
    manifest = json.loads((assets / "manifest.json").read_text(encoding="utf-8"))
    files = manifest["files"]
    if not files or manifest["license"] != "Apache-2.0":
        raise ValueError("OMX manifest is incomplete")
    paths = set()
    for entry in files:
        path = (assets / entry["path"]).resolve()
        if not path.is_relative_to(assets.resolve()) or path in paths or not path.is_file():
            raise ValueError(f"Invalid OMX manifest path: {entry['path']}")
        paths.add(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            raise ValueError(f"OMX asset hash mismatch: {entry['path']}")
    return len(files)


def _mesh_path(uri: str, assets: Path) -> Path:
    if uri.startswith(PACKAGE_URI):
        path = (assets / uri[len(PACKAGE_URI):]).resolve()
        if not path.is_relative_to(assets.resolve()):
            raise ValueError(f"Mesh escapes OMX assets: {uri}")
        return path
    parsed = urlparse(uri)
    if parsed.scheme == "file" and not parsed.netloc:
        return Path(url2pathname(unquote(parsed.path)))
    raise ValueError(f"Unsupported mesh URI: {uri}")


def check_urdf(path: Path, model: str, assets: Path = ASSETS, *, allow_package: bool = True) -> dict:
    if model not in EXPECTED_JOINTS:
        raise ValueError(f"Unknown model: {model}")
    root = ET.parse(path).getroot()
    if root.tag != "robot" or root.find(".//gazebo") is not None or root.find(".//ros2_control") is not None:
        raise ValueError("Isaac model must be a robot without simulator or hardware plugins")
    joints = {joint.get("name") for joint in root.iter("joint")}
    missing = EXPECTED_JOINTS[model] - joints
    if missing:
        raise ValueError(f"Missing {model} joints: {sorted(missing)}")
    meshes = list(root.iter("mesh"))
    if not meshes:
        raise ValueError(f"No meshes in {model} model")
    for mesh in meshes:
        uri = mesh.get("filename", "")
        if not allow_package and uri.startswith("package://"):
            raise ValueError(f"Unresolved {model} mesh URI: {uri}")
        resolved = _mesh_path(uri, assets)
        if not resolved.is_file():
            raise ValueError(f"Missing {model} mesh: {uri}")
    return {"model": model, "joints": len(joints), "meshes": len(meshes)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pinky-urdf", type=Path, help="Prepared Pinky URDF, after xacro rendering")
    args = parser.parse_args()
    try:
        count = check_vendor_manifest()
        print(f"OMX manifest: {count} files verified")
        for model in ("omx_f", "omx_l"):
            source = ASSETS / "urdf" / model / f"{model}.urdf"
            print(check_urdf(source, model))
        if args.pinky_urdf:
            print(check_urdf(args.pinky_urdf, "pinky", allow_package=False))
    except (ValueError, OSError, ET.ParseError) as exc:
        raise SystemExit(f"Model preflight failed: {exc}") from exc


if __name__ == "__main__":
    main()
