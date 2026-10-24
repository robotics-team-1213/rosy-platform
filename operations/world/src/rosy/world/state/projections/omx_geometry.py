"""Verified geometry coverage for the first, pinned OMX transfer profile.

Installation supplies asset bytes; this module opens no files or network paths.
The fingerprint includes mesh contents, URDF origins/scales and visual geometry.
Coverage identifies required observations; it cannot verify measured bounds,
perform FK, authenticate a producer or grant clearance.
"""
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
import json
import xml.etree.ElementTree as ET


# Same normalized vendor 5.1.2 URDF as omx_f_kinematics.yaml, with all eight meshes.
_URDF_DIGEST = "d06720f50c71b380daa91f6cf52ae089725bc588617e5f42ed2433b6e665b809"
_MODEL_DIGEST = "c99e3b4ba229be84f40f9af44155a8ae9d1a4b250301cbe57d5f179d4dfaec51"


@dataclass(frozen=True)
class ArmGeometry:
    model_digest: str
    required_links: frozenset[str]


def load_omx_geometry(urdf: bytes, meshes: Mapping[str, bytes]) -> ArmGeometry:
    """Reject changed/incomplete assets instead of inferring coverage from joints.

    Only this reviewed model is supported. A different model needs a new reviewed
    profile; callers cannot choose a smaller link set or a replacement digest.
    """
    if not isinstance(urdf, bytes) or not isinstance(meshes, Mapping):
        raise ValueError("OMX geometry requires URDF and mesh bytes")
    normalized = urdf.replace(b"\r\n", b"\n")
    if sha256(normalized).hexdigest() != _URDF_DIGEST:
        raise ValueError("OMX URDF does not match the installed geometry profile")
    # Parse only after matching the exact pin; arbitrary XML is never interpreted.
    root = ET.fromstring(normalized)
    references = {node.attrib["filename"] for node in root.findall(".//mesh")}
    assets = dict(meshes)
    if set(assets) != references or any(not isinstance(value, bytes) or not value for value in assets.values()):
        raise ValueError("OMX geometry requires exactly the referenced mesh assets")
    document = {"format": "rosy.omx-geometry/1", "urdf": _URDF_DIGEST,
                "meshes": {name: sha256(value).hexdigest() for name, value in assets.items()}}
    digest = sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if digest != _MODEL_DIGEST:
        raise ValueError("OMX mesh contents do not match the installed geometry profile")
    links = frozenset(node.attrib["name"] for node in root.findall("link")
                      if node.findall("./visual/geometry") or node.findall("./collision/geometry"))
    return ArmGeometry(digest, links)
