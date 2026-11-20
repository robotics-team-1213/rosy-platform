"""3D asset boundary (docs/reference/platform-folder-responsibilities.md): runtime meshes live only under declared asset roots with SOURCE.json provenance."""

from __future__ import annotations

import functools
import json
import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
MESH_SUFFIXES = {".stl", ".obj", ".dae", ".usd", ".usda", ".usdc", ".glb", ".gltf", ".ply", ".fbx"}
DESIGN_SUFFIXES = {".3mf", ".scad", ".step", ".stp", ".f3d", ".blend"}
BANNED_CAD_IMPORTS = {"manifold3d", "cadquery"}

# Mesh root -> provenance root (Pinky keeps SOURCE.json at the description package root).
ALLOWED_ROOTS = {
    "learning/envs/isaac/assets": "learning/envs/isaac/assets",
    "middleware/devices/pinky/description/meshes": "middleware/devices/pinky/description",
    "middleware/perception/map/map_v2_fleet": "middleware/perception/map/map_v2_fleet",
    "middleware/perception/map/map_world_261026": "middleware/perception/map/map_world_261026",
    "integrations/simulation/gazebo/models": "integrations/simulation/gazebo/models",
}


@functools.lru_cache(maxsize=1)
def _tracked() -> tuple[str, ...]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    return tuple(sorted(filter(None, out.decode("utf-8").split("\0"))))


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def _find_source_json(mesh_path: str, prov_root: str, tracked: set[str]) -> str | None:
    cur = PurePosixPath(mesh_path).parent
    while _under(cur.as_posix(), prov_root):
        candidate = f"{cur.as_posix()}/SOURCE.json"
        if candidate in tracked:
            return candidate
        if cur.as_posix() == prov_root:
            break
        cur = cur.parent
    return None


def test_3d_meshes_live_only_under_allowed_roots():
    assert [
        p for p in _tracked()
        if PurePosixPath(p).suffix.lower() in MESH_SUFFIXES and not any(_under(p, r) for r in ALLOWED_ROOTS)
    ] == []


def test_design_source_files_are_not_tracked():
    assert [p for p in _tracked() if PurePosixPath(p).suffix.lower() in DESIGN_SUFFIXES] == []


def test_every_tracked_mesh_has_valid_source_json():
    tracked = set(_tracked())
    source_files = {p for p in tracked if PurePosixPath(p).name == "SOURCE.json" and any(_under(p, r) for r in ALLOWED_ROOTS.values())}
    missing = []
    for path in sorted(tracked):
        if PurePosixPath(path).suffix.lower() not in MESH_SUFFIXES:
            continue
        prov_root = next((prov for mesh_root, prov in ALLOWED_ROOTS.items() if _under(path, mesh_root)), None)
        if prov_root is None:
            continue
        found = _find_source_json(path, prov_root, tracked)
        if found is None:
            missing.append(path)
        else:
            source_files.add(found)
    assert missing == []
    for src in sorted(source_files):
        data = json.loads((ROOT / src).read_text(encoding="utf-8"))
        assert isinstance(data, dict) and isinstance(data.get("source"), str) and data["source"].strip(), src


def test_no_python_file_imports_cad_generators():
    pattern = r"^\s*(import|from)\s+(" + "|".join(sorted(BANNED_CAD_IMPORTS)) + r")\b"
    out = subprocess.run(["git", "grep", "-nE", pattern, "--", "*.py"], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode in (0, 1), out.stderr  # 1 = no match
    assert out.stdout.splitlines() == []
