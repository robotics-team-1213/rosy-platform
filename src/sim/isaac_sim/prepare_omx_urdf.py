"""Resolve the pinned ROBOTIS OMX model meshes for Isaac Sim's URDF importer."""

import argparse
from pathlib import Path
import xml.etree.ElementTree as ET

from prepare_urdf import validate_output_path
from model_checks import check_urdf, check_vendor_manifest


ASSETS = Path(__file__).resolve().parent / "assets" / "open_manipulator_description"
PACKAGE_URI = "package://open_manipulator_description/"


def prepare(model: str, output: Path) -> Path:
    if model not in {"omx_f", "omx_l"}:
        raise ValueError("model must be omx_f or omx_l")
    source = ASSETS / "urdf" / model / f"{model}.urdf"
    check_vendor_manifest()
    check_urdf(source, model)
    root = ET.parse(source).getroot()
    for mesh in root.iter("mesh"):
        uri = mesh.get("filename", "")
        if not uri.startswith(PACKAGE_URI):
            raise ValueError(f"Unexpected OMX mesh URI: {uri}")
        target = (ASSETS / uri[len(PACKAGE_URI):]).resolve()
        if not target.is_relative_to(ASSETS) or not target.is_file():
            raise ValueError(f"Missing or escaping OMX mesh: {uri}")
        mesh.set("filename", target.as_uri())
    output = validate_output_path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)
    check_urdf(output, model, allow_package=False)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, choices=("omx_f", "omx_l"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(prepare(args.model, args.output))


if __name__ == "__main__":
    main()
