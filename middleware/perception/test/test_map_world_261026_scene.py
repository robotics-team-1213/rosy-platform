"""map_world_261026 — graph v7 bays become pink paint and collision guides."""

import importlib.util
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "map" / "map_world_261026"
WORLD = BUNDLE / "worlds" / "map_world_261026.world"
LOOP = BUNDLE / "meshes" / "road_lines_loop.stl"
FULL = BUNDLE / "meshes" / "road_lines.stl"


def _builder():
    spec = importlib.util.spec_from_file_location(
        "build_world", BUNDLE / "scripts" / "build_world.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _triangles(path):
    data = path.read_bytes()
    count = struct.unpack_from("<I", data, 80)[0]
    out = []
    for i in range(count):
        v = struct.unpack_from("<12f", data, 84 + 50 * i)
        out.append((v[3:6], v[6:9], v[9:12]))
    return out


def test_regeneration_is_byte_deterministic(tmp_path):
    _builder().build(tmp_path)
    assert (tmp_path / "worlds" / "map_world_261026.world").read_bytes() == WORLD.read_bytes()
    assert (tmp_path / "meshes" / "road_lines_loop.stl").read_bytes() == LOOP.read_bytes()


def test_loop_mesh_is_the_parking_excluded_subset():
    # The 2026-10-31 ceiling finding: loop paint matches the floor, the CAD
    # parking paint does not. The loop mesh keeps y <= 0.20 only.
    full, loop = _triangles(FULL), _triangles(LOOP)
    assert 0 < len(loop) < len(full)
    assert all(max(v[1] for v in t) <= 0.20 for t in loop)


def test_pink_guide_is_visual_only_and_complete():
    root = ET.parse(WORLD).getroot()
    pink = root.find(".//model[@name='pink_guide']")
    assert len(pink.findall(".//visual")) == 11   # 8 guide segments + 3 bay lanes
    assert pink.find(".//collision") is None


def test_each_bay_has_rails_and_a_stop_bar_with_collision():
    root = ET.parse(WORLD).getroot()
    models = root.findall(".//model")
    names = [m.attrib["name"] for m in models]
    assert len(names) == len(set(names)), f"Duplicate SDF model names break gz-sim: {names}"
    bays = [m for m in models if m.attrib["name"].startswith("bay_guide_")]
    assert len(bays) == 3
    for bay in bays:
        assert len(bay.findall(".//collision")) == 3
    # v7 bay x positions -0.414 / -0.19 / 0.032 (each model's pose child).
    poses = sorted(float(b.find("pose").text.split()[0]) for b in bays)
    assert poses == [-0.414, -0.19, 0.032]


def test_loop_paint_and_walls():
    root = ET.parse(WORLD).getroot()
    loop = root.find(".//model[@name='road_lines_loop']")
    assert loop.find(".//collision") is None
    assert "road_lines_loop.stl" in ET.tostring(loop, encoding="unicode")
    track = root.find(".//model[@name='track_261026']")
    assert len(track.findall(".//collision")) == 4
