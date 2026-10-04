"""Import a pinned OMX-F or OMX-L model into Isaac Sim 5.1/6.x and inspect its USD."""

import argparse
from pathlib import Path
import xml.etree.ElementTree as ET

from model_checks import check_urdf, check_vendor_manifest, EXPECTED_JOINTS
from prepare_urdf import validate_output_path
from importer_compat import import_model, reference_model


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, choices=("omx_f", "omx_l"))
    parser.add_argument("--urdf", required=True, type=Path, help="Prepared URDF with local file mesh URIs")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--frames", type=int, default=120, help="Render frames after import; 0 runs until closed")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.frames < 0:
        raise SystemExit("--frames must be zero or positive")
    try:
        check_vendor_manifest()
        check_urdf(args.urdf, args.model, allow_package=False)
        output_dir = validate_output_path(args.output_dir / "model.usd").parent
    except (ValueError, OSError, ET.ParseError) as exc:
        raise SystemExit(f"OMX preflight failed: {exc}") from exc
    output_dir.mkdir(parents=True, exist_ok=True)

    from isaacsim import SimulationApp

    # Preserve a failed import's nonzero exit after normal extension cleanup.
    app = SimulationApp({"headless": args.headless, "fast_shutdown": False})
    try:
        import omni.kit.app
        import omni.kit.commands
        import omni.usd
        from pxr import Usd, UsdGeom, UsdPhysics

        manager = omni.kit.app.get_app().get_extension_manager()
        manager.set_extension_enabled_immediate("isaacsim.asset.importer.urdf", True)
        import isaacsim.asset.importer.urdf as urdf_api

        usd_path = import_model(urdf_api, omni.kit.commands.execute, args.urdf, output_dir, "Manipulator")
        reference_model(omni.usd.get_context(), usd_path, Usd, UsdGeom)
        app.update()
        stage = omni.usd.get_context().get_stage()
        if stage is None:
            raise RuntimeError("Isaac Sim did not open the OMX USD stage")
        articulations = [str(prim.GetPath()) for prim in stage.Traverse()
                         if prim.HasAPI(UsdPhysics.ArticulationRootAPI)]
        if len(articulations) != 1:
            raise RuntimeError(f"Expected one OMX articulation, found {articulations}")
        joints = {prim.GetName() for prim in stage.Traverse() if prim.IsA(UsdPhysics.Joint)}
        missing = EXPECTED_JOINTS[args.model] - joints
        if missing:
            raise RuntimeError(f"Imported OMX joints missing: {sorted(missing)}")
        print(f"OMX USD: {usd_path}; articulation: {articulations[0]}; joints: {sorted(joints)}")
        frame = 0
        while app.is_running() and (args.frames == 0 or frame < args.frames):
            app.update()
            frame += 1
    finally:
        app.close()


if __name__ == "__main__":
    main()
