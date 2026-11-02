"""Resolve the pinned ROBOTIS OMX model meshes for Isaac Sim's URDF importer."""

import argparse
from pathlib import Path
import xml.etree.ElementTree as ET

from prepare_urdf import validate_output_path
from model_checks import check_urdf, check_vendor_manifest
import palletizing_gripper as palletizing


ASSETS = Path(__file__).resolve().parent / "assets" / "open_manipulator_description"
PACKAGE_URI = "package://open_manipulator_description/"
PALLETIZING_URI = "package://omx_f_palletizing_description/"


def prepare(model: str, output: Path, gripper: str | None = None) -> Path:
    if model not in {"omx_f", "omx_l"} or gripper not in (None, palletizing.GRIPPER) or gripper and model != "omx_f":
        raise ValueError("model must be omx_f or omx_l; the palletizing jaw fits omx_f only")
    source = palletizing.URDF if gripper else ASSETS / "urdf" / model / f"{model}.urdf"
    check_vendor_manifest()
    # Opt-in jaw v2.1: its own package holds only the two jaw meshes; the arm meshes are the vendor's, byte for byte.
    roots = {PACKAGE_URI: ASSETS} | ({PALLETIZING_URI: palletizing.ASSETS} if gripper else {})
    if gripper:
        check_vendor_manifest(palletizing.ASSETS)
    else:
        check_urdf(source, model)
    root = ET.parse(source).getroot()
    for mesh in root.iter("mesh"):
        uri = mesh.get("filename", "")
        prefix = next((p for p in roots if uri.startswith(p)), None)
        if prefix is None:
            raise ValueError(f"Unexpected OMX mesh URI: {uri}")
        target = (roots[prefix] / uri[len(prefix):]).resolve()
        if prefix == PALLETIZING_URI and not target.is_file():
            target = (ASSETS / uri[len(prefix):]).resolve()
        if not target.is_relative_to(ASSETS) and not target.is_relative_to(palletizing.ASSETS) or not target.is_file():
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
    parser.add_argument("--gripper", choices=(palletizing.GRIPPER,), help="Opt-in jaw instead of the stock OMX-F jaw")
    args = parser.parse_args()
    print(prepare(args.model, args.output, args.gripper))


if __name__ == "__main__":
    main()
