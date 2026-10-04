import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


def helper():
    path = Path(__file__).parents[1] / "importer_compat.py"
    assert path.is_file(), "Version-compatible importer is missing"
    spec = importlib.util.spec_from_file_location("importer_compat", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_modern_importer_preserves_wheel_configuration(tmp_path):
    options = {}
    destination = tmp_path / "modern.usd"
    destination.write_text("USD")

    class Config:
        def __init__(self, **kwargs):
            options.update(kwargs)

    api = SimpleNamespace(URDFImporterConfig=Config,
                          URDFImporter=lambda config: SimpleNamespace(import_urdf=lambda: str(destination)))
    assert helper().import_model(api, None, tmp_path / "robot.urdf", tmp_path, "Wheeled") == str(destination)
    assert options["fix_base"] is False
    assert options["joint_target_type"] == {".*wheel_joint": "velocity"}
    assert options["override_joint_stiffness"] == {".*wheel_joint": 0.0}


def test_legacy_import_writes_explicit_usd_and_checks_result(tmp_path):
    config = SimpleNamespace(merge_fixed_joints=True, fix_base=False, collision_from_visuals=True,
                             import_inertia_tensor=False, make_default_prim=False)
    calls = []

    def execute(command, **kwargs):
        calls.append((command, kwargs))
        if command == "URDFCreateImportConfig":
            return True, config
        Path(kwargs["dest_path"]).write_text("USD")
        return True, "/robot"

    result = helper().import_model(SimpleNamespace(), execute, tmp_path / "robot.urdf", tmp_path, "Manipulator")
    assert Path(result).is_file()
    assert config.fix_base is True
    assert config.merge_fixed_joints is False
    assert config.import_inertia_tensor is True
    assert config.collision_from_visuals is False
    assert config.make_default_prim is True
    assert calls[-1][0] == "URDFParseAndImportFile"


@pytest.mark.parametrize("api", [SimpleNamespace(URDFImporter=lambda: None),
                                 SimpleNamespace(URDFImporter=None, URDFImporterConfig=None)])
def test_partial_modern_api_never_falls_back(api, tmp_path):
    with pytest.raises(RuntimeError, match="Incomplete"):
        helper().import_model(api, lambda *a, **k: pytest.fail("fallback"), tmp_path / "r.urdf", tmp_path, "Wheeled")


def test_failed_legacy_config_and_missing_outputs_are_rejected(tmp_path):
    with pytest.raises(RuntimeError, match="configuration"):
        helper().import_model(SimpleNamespace(), lambda *a, **k: (False, None),
                              tmp_path / "r.urdf", tmp_path, "Wheeled")
    api = SimpleNamespace(URDFImporterConfig=lambda **kw: None,
                          URDFImporter=lambda _: SimpleNamespace(import_urdf=lambda: str(tmp_path / "absent.usd")))
    with pytest.raises(RuntimeError, match="no USD"):
        helper().import_model(api, None, tmp_path / "r.urdf", tmp_path, "Wheeled")


def test_imported_asset_is_referenced_without_replacing_live_stage():
    module = helper()
    assert hasattr(module, "reference_model"), "Safe stage-reference loader is missing"
    calls = []
    prim = SimpleNamespace(IsValid=lambda: True)
    asset = SimpleNamespace(GetDefaultPrim=lambda: prim)
    reference = SimpleNamespace(AddReference=lambda path: calls.append(("reference", path)) or True)
    stage = SimpleNamespace(GetPrimAtPath=lambda path: SimpleNamespace(IsValid=lambda: False),
                            DefinePrim=lambda path, kind: SimpleNamespace(GetReferences=lambda: reference))
    context = SimpleNamespace(get_stage=lambda: stage,
                              open_stage=lambda path: pytest.fail("Replacing live SDK stage risks graph invalidation"))
    usd = SimpleNamespace(Stage=SimpleNamespace(Open=lambda path: asset))
    geom = SimpleNamespace(GetStageUpAxis=lambda _: "Z", GetStageMetersPerUnit=lambda _: 1.0,
                           SetStageUpAxis=lambda *args: calls.append(("axis", args[1])),
                           SetStageMetersPerUnit=lambda *args: calls.append(("units", args[1])))
    assert module.reference_model(context, "robot.usd", usd, geom) is stage
    assert calls == [("axis", "Z"), ("units", 1.0), ("reference", "robot.usd")]


def test_reference_rejects_asset_with_no_default_prim():
    module = helper()
    assert hasattr(module, "reference_model"), "Safe stage-reference loader is missing"
    context = SimpleNamespace(get_stage=lambda: object())
    asset = SimpleNamespace(GetDefaultPrim=lambda: SimpleNamespace(IsValid=lambda: False))
    usd = SimpleNamespace(Stage=SimpleNamespace(Open=lambda path: asset))
    with pytest.raises(RuntimeError, match="default prim"):
        module.reference_model(context, "robot.usd", usd, None)
