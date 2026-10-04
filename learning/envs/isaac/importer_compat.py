"""Capability-selected NVIDIA URDF import (5.1 commands or 6.x Python API).

Enable isaacsim.asset.importer.urdf before importing its module. Do not fall back
when a modern importer is present but broken: its failures are deployment holds.
"""

from pathlib import Path


def import_model(api, execute, urdf: Path, output_dir: Path, robot_type: str) -> str:
    if robot_type not in ("Wheeled", "Manipulator"):
        raise ValueError("Unsupported importer robot type")
    modern_names = ("URDFImporter", "URDFImporterConfig")
    present = [hasattr(api, name) for name in modern_names]
    if any(present):
        if not all(present) or not all(callable(getattr(api, name)) for name in modern_names):
            raise RuntimeError("Incomplete modern URDF importer API")
        options = dict(urdf_path=str(urdf.resolve()), usd_path=str(output_dir), robot_type=robot_type,
                       fix_base=False if robot_type == "Wheeled" else None,
                       merge_fixed_joints=False, collision_from_visuals=False)
        if robot_type == "Wheeled":
            options.update(joint_target_type={".*wheel_joint": "velocity"},
                           override_joint_stiffness={".*wheel_joint": 0.0})
        usd_path = api.URDFImporter(api.URDFImporterConfig(**options)).import_urdf()
    else:
        if not callable(execute):
            raise RuntimeError("Legacy URDF importer commands unavailable")
        success, config = execute("URDFCreateImportConfig")
        if not success or config is None:
            raise RuntimeError("Legacy URDF importer configuration failed")
        # These documented 5.1 properties are mandatory. Unknown SDK shapes fail.
        properties = dict(merge_fixed_joints=False, collision_from_visuals=False,
                          import_inertia_tensor=True, fix_base=robot_type == "Manipulator", make_default_prim=True)
        for name, value in properties.items():
            if not hasattr(config, name):
                raise RuntimeError(f"Legacy URDF configuration missing {name}")
            setattr(config, name, value)
        # OMX's pinned URDF has world_fixed; legacy fixed-base import explicitly
        # keeps the manipulator anchored. Pinky wheel drives are verified on USD.
        usd_path = str((output_dir / "model.usd").resolve())
        success, prim_path = execute("URDFParseAndImportFile", urdf_path=str(urdf.resolve()),
                                     import_config=config, dest_path=usd_path)
        if not success or not isinstance(prim_path, str) or not prim_path.startswith("/"):
            raise RuntimeError("Legacy URDF import failed")
    if not isinstance(usd_path, str) or not Path(usd_path).is_file():
        raise RuntimeError(f"URDF import produced no USD: {usd_path}")
    return usd_path


def reference_model(context, usd_path: str, usd_api, geom_api):
    """Compose the imported asset without closing Kit's live initialization stage.

    Replacing that stage immediately after URDF import crashes the installed 5.1
    graph/image executor. USD references are the documented standalone workflow.
    Only a fresh SimulationApp stage is supported; never overwrite an asset.
    """
    stage = context.get_stage()
    asset_stage = usd_api.Stage.Open(usd_path)
    if stage is None or asset_stage is None:
        raise RuntimeError("Imported USD or live SDK stage unavailable")
    if not asset_stage.GetDefaultPrim().IsValid():
        raise RuntimeError("Imported USD has no default prim")
    if stage.GetPrimAtPath("/World/Imported").IsValid():
        raise RuntimeError("SDK stage already contains the imported asset")
    geom_api.SetStageUpAxis(stage, geom_api.GetStageUpAxis(asset_stage))
    geom_api.SetStageMetersPerUnit(stage, geom_api.GetStageMetersPerUnit(asset_stage))
    references = stage.DefinePrim("/World/Imported", "Xform").GetReferences()
    if not references.AddReference(usd_path):
        raise RuntimeError("Imported USD reference could not be authored")
    return stage
