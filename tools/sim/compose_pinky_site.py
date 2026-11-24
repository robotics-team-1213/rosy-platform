"""Compose an imported ROSY Pinky asset with the versioned Isaac site and R08 cell."""

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
import shutil


SITE_STAGE = "world_261026_ab_candidate.usda"
PINKY_LAYERS = (
    "model.usd", "configuration/model_base.usd", "configuration/model_robot.usd",
    "configuration/model_physics.usd", "configuration/model_sensor.usd",
)


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, required=True, help="build_isaac_site_scene.py output")
    parser.add_argument("--site-map", type=Path, required=True)
    parser.add_argument("--pinky", type=Path, required=True, help="imported model.usd and configuration directory")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics

    site = json.loads((args.site / "manifest.json").read_bytes())
    map_doc = json.loads(args.site_map.read_bytes())
    site_layers = (SITE_STAGE, "r08-ab-candidate.usdc")
    if (site.get("parking_map_sha256") != digest(args.site_map)
            or site.get("parking_map_version") != map_doc["version"]
            or map_doc["map"].get("map_id") != "world_261026"
            or any(site["outputs"][name] != digest(args.site / name) for name in site_layers)):
        raise ValueError("site map and authored layers must match the scene manifest")
    c2 = next(place for place in map_doc["map"]["places"] if place["id"] == "C2")
    if not all(type(c2[name]) in (int, float) and math.isfinite(c2[name]) for name in ("x", "y", "yaw")):
        raise ValueError("C2 needs a measured map position and heading")

    robot = Usd.Stage.Open(str(args.pinky / PINKY_LAYERS[0]))
    if (not robot or robot.GetDefaultPrim().GetName() != "rosy"
            or UsdGeom.GetStageUpAxis(robot) != UsdGeom.Tokens.z
            or UsdGeom.GetStageMetersPerUnit(robot) != 1
            or not all((args.pinky / name).is_file() for name in PINKY_LAYERS)):
        raise ValueError("expected a portable, metre-scale native Pinky asset")

    root = args.out.resolve()
    root.mkdir(parents=True, exist_ok=False)
    for directory, source, layers in (("site", args.site, site_layers), ("pinky", args.pinky, PINKY_LAYERS)):
        for name in layers:
            dest = root / directory / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, dest)
    shutil.copyfile(args.site_map, root / "site-map.json")
    stage_path = root / "world_261026_pinky_ab.usda"
    stage = Usd.Stage.CreateNew(str(stage_path))
    stage.GetRootLayer().subLayerPaths = [f"./site/{SITE_STAGE}"]
    floor = stage.GetPrimAtPath("/World/Site")
    if not floor.IsValid():
        raise ValueError("expected shared site coordinates")
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1)
    stage.SetDefaultPrim(stage.GetPrimAtPath("/World"))

    # Gazebo uses the same initial chassis height before the robot settles on the floor.
    spawn = Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(0, 0, 1), math.degrees(c2["yaw"])))
    spawn.SetTranslateOnly(Gf.Vec3d(c2["x"], c2["y"], .10))
    site_to_world = UsdGeom.Xformable(floor).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    mount = UsdGeom.Xform.Define(stage, Sdf.Path("/World/Pinky"))
    mount.AddTransformOp().Set(spawn * site_to_world)
    imported = stage.DefinePrim("/World/Pinky/Robot", "Xform")
    imported.GetReferences().AddReference("./pinky/model.usd")
    physics = imported.GetVariantSets().GetVariantSet("Physics")
    choice = next((name for name in physics.GetVariantNames() if name.lower() == "physx"), None)
    if not choice or not physics.SetVariantSelection(choice):
        raise ValueError("Pinky asset is missing its PhysX variant")

    site_paths = [str(p.GetPath()) for p in stage.Traverse() if p.IsA(UsdPhysics.Scene)]
    wheel_names = {p.GetName() for p in Usd.PrimRange(imported) if p.IsA(UsdPhysics.RevoluteJoint)}
    roots = [str(p.GetPath()) for p in stage.Traverse() if p.HasAPI(UsdPhysics.ArticulationRootAPI)]
    if len(site_paths) != 1 or len(roots) != 3 or not {"l_wheel_joint", "r_wheel_joint"} <= wheel_names:
        raise ValueError(f"expected one physics scene, A/B and Pinky articulations: {roots}")
    stage.GetRootLayer().Save()
    manifest = {
        "scope": "C2 spawn composition, not an integrated motion or handoff trial",
        "site_map_version": map_doc["version"], "spawn_place": "C2", "spawn_site_xy_yaw": [c2[k] for k in ("x", "y", "yaw")],
        "articulation_roots": roots, "physics_scenes": site_paths,
        "sha256": {file.relative_to(root).as_posix(): digest(file) for file in sorted(root.rglob("*")) if file.is_file()},
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(stage_path)


if __name__ == "__main__":
    main()
