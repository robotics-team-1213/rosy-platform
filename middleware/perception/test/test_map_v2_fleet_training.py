"""Curved training map keeps the measured map and ambiguous white wall/paint."""

import math
import xml.etree.ElementTree as ET

import numpy as np
import pytest
import yaml

from test_map_v2_fleet_scene import BUNDLE, SOURCE, _load


def test_training_assets_are_generated_deterministically_without_replacing_the_baseline(tmp_path):
    build = _load("build_world")
    build.build(SOURCE, tmp_path)
    paths = ("worlds/map_v2_fleet_real.world", "meshes/road_lines.stl", "lane_graph.yaml")
    first = {}
    for path in paths:
        generated = tmp_path / "training-curved" / path
        assert generated.is_file(), f"missing training asset: {path}"
        first[path] = generated.read_bytes()
        assert first[path] == (BUNDLE / "training-curved" / path).read_bytes()
    build.build(SOURCE, tmp_path)
    for path, data in first.items():
        assert (tmp_path / "training-curved" / path).read_bytes() == data
    for path in paths[:2]:
        assert (tmp_path / path).read_bytes() == (BUNDLE / path).read_bytes()


def test_training_walls_are_white_grounded_and_taller_than_pinky():
    path = BUNDLE / "training-curved/worlds/map_v2_fleet_real.world"
    assert path.is_file(), "curved training world has not been generated"
    world = ET.parse(path).getroot().find("world")
    walls = world.findall("./model[@name='track_v2_fleet']/link/collision")
    assert len(walls) == 4
    geometry = yaml.safe_load((BUNDLE.parents[2] / "apps/device/pinky/profile/config/geometry.yaml").read_text())
    for wall in walls:
        size = [float(v) for v in wall.find("./geometry/box/size").text.split()]
        z = float(wall.find("pose").text.split()[2])
        assert size[2] == pytest.approx(0.30)
        assert size[2] > geometry["lidar"]["height_m"]
        assert z - size[2] / 2 == pytest.approx(0.0)
        visual = world.find(f"./model[@name='track_v2_fleet']/link/visual[@name='{wall.attrib['name'].replace('_col', '_vis')}']")
        assert visual.find("./geometry/box/size").text == wall.find("./geometry/box/size").text
        assert visual.find("./material/diffuse").text == "1 1 1 1"
    paint = world.find("./model[@name='road_lines']/link/visual")
    assert paint.find("./material/diffuse").text == "1 1 1 1"
    assert paint.find(".//uri").text.endswith("/training-curved/meshes/road_lines.stl")
    assert world.find("./model[@name='wall_tape']") is None


def test_s_bend_is_stronger_but_crosswalks_junctions_and_lane_clearance_remain():
    build = _load("build_world")
    path = BUNDLE / "training-curved/lane_graph.yaml"
    assert path.is_file(), "curved training graph has not been generated"
    original = yaml.safe_load((BUNDLE / "lane_graph.yaml").read_text())
    curved = yaml.safe_load(path.read_text())
    for key in ("nodes", "roundabout", "crosswalks", "parking"):
        assert curved[key] == original[key]
    for name in original["segments"]:
        if name != "east":
            assert curved["segments"][name] == original["segments"][name]
    before = np.array(original["segments"]["east"]["points"])
    after = np.array(curved["segments"]["east"]["points"])
    bend = (before[:, 0] > 0.4) & (before[:, 0] < 1.1) & (np.abs(before[:, 1]) < 0.15)
    assert np.ptp(after[bend, 1]) > 1.3 * np.ptp(before[bend, 1])
    assert np.array_equal(before[[0, -1]], after[[0, -1]])
    length = sum(math.dist(a, b) for a, b in zip(after[:-1], after[1:]))
    assert curved["segments"]["east"]["length_m"] == pytest.approx(length, abs=1e-4)
    scene = build.training_scene(_load("stl_scene").load_scene(SOURCE))
    field = _load("lane_graph").LineField(scene)
    assert min(field.at(x, y) for x, y in after[bend]) >= 0.055
    # No artificial dark moat between existing outer paint and the wall.
    baseline = _load("stl_scene").load_scene(SOURCE)
    outer = [t for t in baseline.lines if all(abs(v[0]) > 1.35 or abs(v[1]) > 0.58 for v in t)]
    assert outer and all(t in scene.lines for t in outer)
