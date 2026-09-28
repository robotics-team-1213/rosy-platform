import importlib.util
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import pytest


MODULE = Path(__file__).parents[1] / "model_checks.py"
spec = importlib.util.spec_from_file_location("model_checks", MODULE)
checks = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = checks
spec.loader.exec_module(checks)


def test_pinned_omx_assets_are_complete_and_unchanged():
    assert checks.check_vendor_manifest() == 18
    assert checks.check_urdf(checks.ASSETS / "urdf/omx_f/omx_f.urdf", "omx_f")["meshes"] == 16
    assert checks.check_urdf(checks.ASSETS / "urdf/omx_l/omx_l.urdf", "omx_l")["meshes"] == 14


def test_omx_asset_hash_drift_is_rejected(monkeypatch):
    original = Path.read_bytes
    target = checks.ASSETS / "LICENSE"

    def tampered(path):
        return b"changed" if path == target else original(path)

    monkeypatch.setattr(Path, "read_bytes", tampered)
    with pytest.raises(ValueError, match="hash mismatch"):
        checks.check_vendor_manifest()


def test_mesh_lookup_rejects_escape_and_unknown_scheme():
    for uri in ("package://open_manipulator_description/../private.stl", "https://example.com/mesh.stl"):
        with pytest.raises(ValueError):
            checks._mesh_path(uri, checks.ASSETS)


def test_pinky_preflight_requires_resolved_mesh_and_excludes_gazebo(monkeypatch):
    mesh = (MODULE.parents[1] / "description/meshes/visual/base_link.dae").resolve().as_uri()
    root = ET.fromstring(
        f'<robot><mesh filename="{mesh}"/><joint name="l_wheel_joint"/>'
        '<joint name="r_wheel_joint"/></robot>'
    )
    monkeypatch.setattr(checks.ET, "parse", lambda _: ET.ElementTree(root))
    assert checks.check_urdf(Path("prepared.urdf"), "pinky", allow_package=False)["meshes"] == 1
    ET.SubElement(root, "gazebo")
    with pytest.raises(ValueError, match="without simulator"):
        checks.check_urdf(Path("prepared.urdf"), "pinky", allow_package=False)
