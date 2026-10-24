"""The first transfer profile covers the actual pinned OMX body, including visuals."""
from dataclasses import FrozenInstanceError
from hashlib import sha256
from importlib import import_module
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import pytest

WORLD = Path(__file__).resolve().parents[1]
ASSETS = WORLD.parents[1] / "learning/envs/isaac/assets/open_manipulator_description"
PREFIX = "package://open_manipulator_description/"
sys.path.insert(0, str(WORLD / "src"))


def api():
    try:
        return import_module("rosy.world.state.projections.omx_geometry")
    except ModuleNotFoundError:
        pytest.fail("verified full OMX geometry descriptor is missing")


@pytest.fixture(scope="module")
def bundle():
    urdf = (ASSETS / "urdf/omx_f/omx_f.urdf").read_bytes().replace(b"\r\n", b"\n")
    root = ET.fromstring(urdf)
    meshes = {node.attrib["filename"]: (ASSETS / node.attrib["filename"].removeprefix(PREFIX)).read_bytes()
              for node in root.findall(".//mesh")}
    return urdf, meshes


def test_actual_bundle_includes_every_visual_and_collision_link(bundle):
    urdf, meshes = bundle
    geometry = api().load_omx_geometry(urdf, meshes)
    expected = frozenset(node.attrib["name"] for node in ET.fromstring(urdf).findall("link")
                         if node.findall("./visual/geometry") or node.findall("./collision/geometry"))
    assert len(meshes) == 8
    assert geometry.required_links == expected == frozenset({"end_effector_link", *(f"link{i}" for i in range(8))})
    assert geometry.model_digest == "c99e3b4ba229be84f40f9af44155a8ae9d1a4b250301cbe57d5f179d4dfaec51"
    assert geometry.model_digest != sha256(urdf).hexdigest()
    assert api().load_omx_geometry(urdf.replace(b"\n", b"\r\n"), meshes) == geometry
    with pytest.raises(FrozenInstanceError):
        geometry.model_digest = "a" * 64
    meshes_copy = dict(meshes)
    same = api().load_omx_geometry(urdf, meshes_copy)
    meshes_copy.clear()
    assert same == geometry


@pytest.mark.parametrize("change", ["urdf", "mesh", "missing", "extra", "empty", "text", "not_mapping"])
def test_unpinned_incomplete_or_substituted_assets_are_rejected(bundle, change):
    urdf, original = bundle
    meshes = dict(original)
    first = next(iter(meshes))
    if change == "urdf":
        urdf = urdf.replace(b'0.01 0.01 0.01', b'0.02 0.01 0.01')
    elif change == "mesh":
        meshes[first] += b"changed"
    elif change == "missing":
        del meshes[first]
    elif change == "extra":
        meshes["package://unreviewed/body.stl"] = b"body"
    elif change == "empty":
        meshes[first] = b""
    elif change == "text":
        urdf = urdf.decode()
    else:
        meshes = list(meshes)
    with pytest.raises(ValueError):
        api().load_omx_geometry(urdf, meshes)


@pytest.mark.parametrize("change", ["partial_links", "unknown_model"])
def test_direct_descriptor_cannot_shrink_coverage_or_select_an_unreviewed_model(bundle, change):
    geometry = api().load_omx_geometry(*bundle)
    digest = geometry.model_digest if change == "partial_links" else "a" * 64
    links = frozenset({"link1"}) if change == "partial_links" else geometry.required_links
    with pytest.raises(ValueError):
        api().ArmGeometry(digest, links)
