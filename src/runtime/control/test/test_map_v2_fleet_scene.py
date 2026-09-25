"""MAP v2 fleet — 260919 STL becomes a Gazebo road scene without reshaping it."""

import importlib.util
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "map" / "map_v2_fleet"
SOURCE = BUNDLE / "260919 MAP FILE.STL"
WORLD = BUNDLE / "worlds" / "map_v2_fleet.world"
MESH = BUNDLE / "meshes" / "road_lines.stl"
MAP_YAML = BUNDLE / "maps" / "map_v2_fleet.yaml"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, BUNDLE / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def scene():
    return _load("stl_scene").load_scene(SOURCE)


def test_source_is_the_reviewed_binary_stl(scene):
    assert scene.triangle_count == 1768
    assert len(scene.source_sha256) == 64


def test_footprint_is_centred_in_metres(scene):
    assert scene.size_x == pytest.approx(2.810, abs=1e-4)
    assert scene.size_y == pytest.approx(1.260, abs=1e-4)
    xs = [v[0] for t in scene.lines for v in t]
    ys = [v[1] for t in scene.lines for v in t]
    assert min(xs) >= -1.4051 and max(xs) <= 1.4051
    assert min(ys) >= -0.6301 and max(ys) <= 0.6301


def test_perimeter_ring_becomes_four_wall_boxes(scene):
    walls = scene.walls
    assert len(walls) == 4
    for wall in walls:
        assert min(wall.size_x, wall.size_y) == pytest.approx(0.005, abs=1e-6)
        assert wall.height == pytest.approx(0.155, abs=1e-6)
    long_walls = sorted(max(w.size_x, w.size_y) for w in walls)
    assert long_walls[-1] == pytest.approx(2.810, abs=1e-4)

    long = [w for w in walls if w.size_x > w.size_y]
    short = [w for w in walls if w.size_x < w.size_y]
    assert len(long) == 2 and len(short) == 2
    for wall in long:
        assert wall.cx == pytest.approx(0.0, abs=1e-6)
        assert abs(wall.cy) == pytest.approx(0.6275, abs=1e-6)
    for wall in short:
        assert wall.cy == pytest.approx(0.0, abs=1e-6)
        assert abs(wall.cx) == pytest.approx(1.4025, abs=1e-6)


def test_floor_paint_is_flat_and_below_one_millimetre(scene):
    assert len(scene.lines) == 1768 - scene.wall_triangle_count
    assert max(v[2] for t in scene.lines for v in t) <= 0.001


def test_rotation_is_proper_not_mirrored():
    mod = _load("stl_scene")
    # STL Y-up: +z (toward viewer) must map to ROS -y; +y (up) to ROS +z.
    assert mod.stl_to_ros((0.0, 0.0, 1000.0), (0.0, 0.0)) == pytest.approx((0.0, -1.0, 0.0))
    assert mod.stl_to_ros((0.0, 1000.0, 0.0), (0.0, 0.0)) == pytest.approx((0.0, 0.0, 1.0))


def test_ring_walls_rejects_a_ring_not_sitting_on_the_floor():
    mod = _load("stl_scene")
    # A synthetic 4-corner-x/4-corner-z rectangular ring, same shape the real
    # wall ring has, but lifted 10 mm off the floor (min height != 0).
    xs = (0.0, 5.0, 995.0, 1000.0)
    zs = (0.0, 5.0, 495.0, 500.0)
    ys = (10.0, 160.0)
    tall = []
    for x0, x1 in ((xs[0], xs[1]), (xs[2], xs[3])):
        for z0, z1 in ((zs[0], zs[1]), (zs[2], zs[3])):
            for y in ys:
                tall.append(((x0, y, z0), (x1, y, z0), (x1, y, z1)))
    with pytest.raises(ValueError, match="floor"):
        mod._ring_walls(tall)


def test_rejects_truncated_stl(tmp_path):
    bad = tmp_path / "bad.stl"
    bad.write_bytes(b"\0" * 80 + struct.pack("<I", 5))
    with pytest.raises(ValueError, match="binary STL"):
        _load("stl_scene").load_scene(bad)


def test_builder_output_is_deterministic_and_checked_in(tmp_path):
    build = _load("build_world")
    build.build(SOURCE, tmp_path)
    assert (tmp_path / "worlds" / "map_v2_fleet.world").read_bytes() == WORLD.read_bytes()
    assert (tmp_path / "meshes" / "road_lines.stl").read_bytes() == MESH.read_bytes()


def test_world_has_four_lidar_height_wall_collisions_only():
    world = ET.parse(WORLD).getroot().find("world")
    boxes = [c for c in world.iter("collision") if c.find("./geometry/box") is not None]
    assert len(boxes) == 4
    assert not [c for c in world.iter("collision") if c.find("./geometry/mesh") is not None]


def test_lane_mesh_is_visual_only_above_the_ground_plane():
    world = ET.parse(WORLD).getroot().find("world")
    uris = [u.text for u in world.iter("uri")]
    assert "model://control/map/map_v2_fleet/meshes/road_lines.stl" in uris
    lines = world.find("./model[@name='road_lines']")
    assert lines.find("static").text == "true"
    assert float(lines.find("pose").text.split()[2]) == pytest.approx(0.001)


def test_world_records_the_source_hash(scene):
    assert scene.source_sha256 in WORLD.read_text(encoding="utf-8")


def test_white_lines_on_dark_floor_by_default():
    """The physical 260919 mat is white tape on a dark floor (lane.py polarity)."""
    text = WORLD.read_text(encoding="utf-8")
    assert "<diffuse>0.2 0.2 0.2 1</diffuse>" in text  # floor
    assert "<diffuse>1 1 1 1</diffuse>" in text        # lane paint


def _read_pgm(path: Path):
    data = path.read_bytes()
    assert data.startswith(b"P5")
    # world_to_map.py writes "P5\n# generated by world_to_map.py\n<w> <h>\n255\n" —
    # line 1 is the comment, so the width/height pair is line index 2, not 1.
    lines = data.split(b"\n", 4)
    width, height = (int(v) for v in lines[2].split())
    maxval_line = lines[3]
    assert maxval_line.strip() == b"255"
    header_len = len(b"\n".join(lines[:4])) + 1  # +1 for the newline after maxval
    payload = data[header_len:]
    assert len(payload) == width * height
    return width, height, payload


def test_occupancy_map_matches_the_wall_ring():
    meta = yaml.safe_load(MAP_YAML.read_text(encoding="utf-8"))
    assert meta["image"] == "map_v2_fleet.pgm"
    # 5 mm cells: every 5 mm wall covers >=1 cell centre, with the centre
    # falling mid-wall instead of tying on the wall's inner edge (the 1 cm
    # bug this size fixes). Chosen over thickening the walls or touching
    # world_to_map.py, per the plan's constraint that neither may change.
    assert meta["resolution"] == pytest.approx(0.005)
    x0, y0, _ = meta["origin"]
    resolution = meta["resolution"]
    width, height, payload = _read_pgm(BUNDLE / "maps" / meta["image"])
    # 2.81 x 1.26 m ring + 0.3 m margin on each side, 0.5 cm cells:
    # (2.81 + 0.6) / 0.005 = 682, (1.26 + 0.6) / 0.005 = 372.
    assert width == 682
    assert height == 372

    def pixel(x: float, y: float) -> int:
        col = int((x - x0) / resolution)
        grid_row = int((y - y0) / resolution)
        # write_map() emits grid rows from height-1 (max y) down to 0 (min y),
        # so the PGM's top-to-bottom row order is the reverse of grid_row.
        pgm_row = height - 1 - grid_row
        return payload[pgm_row * width + col]

    FREE, OCCUPIED, UNKNOWN = 254, 0, 205

    assert pixel(-1.26955, 0.24255) == FREE  # spawn seed

    for x, y in ((0.0, 0.6275), (0.0, -0.6275), (1.4025, 0.0), (-1.4025, 0.0)):
        assert pixel(x, y) == OCCUPIED, f"wall midpoint ({x}, {y}) is not occupied"

    for x, y in ((0.0, 0.75), (0.0, -0.75), (1.55, 0.0), (-1.55, 0.0)):
        assert pixel(x, y) == UNKNOWN, f"outside-ring cell ({x}, {y}) is not unknown"

    assert sum(1 for b in payload if b == UNKNOWN) > 0
