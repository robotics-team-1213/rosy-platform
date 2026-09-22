"""MAP v2 fleet — 260919 STL becomes a Gazebo road scene without reshaping it."""

import importlib.util
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "map" / "map_v2_fleet"
SOURCE = BUNDLE / "260919 MAP FILE.STL"


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


def test_floor_paint_is_flat_and_below_one_millimetre(scene):
    assert len(scene.lines) == 1768 - scene.wall_triangle_count
    assert max(v[2] for t in scene.lines for v in t) <= 0.001


def test_rotation_is_proper_not_mirrored():
    mod = _load("stl_scene")
    # STL Y-up: +z (toward viewer) must map to ROS -y; +y (up) to ROS +z.
    assert mod.stl_to_ros((0.0, 0.0, 1000.0), (0.0, 0.0)) == pytest.approx((0.0, -1.0, 0.0))
    assert mod.stl_to_ros((0.0, 1000.0, 0.0), (0.0, 0.0)) == pytest.approx((0.0, 0.0, 1.0))


def test_rejects_truncated_stl(tmp_path):
    bad = tmp_path / "bad.stl"
    bad.write_bytes(b"\0" * 80 + struct.pack("<I", 5))
    with pytest.raises(ValueError, match="binary STL"):
        _load("stl_scene").load_scene(bad)
