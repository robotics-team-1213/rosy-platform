"""MAP v2 fleet — the stage-3 parking marker in the generated world.

A low inclined ("wedge") ArUco tag: DICT_4X4_50 id 7, 50 mm, with a white
one-cell quiet zone, on a face inclined 25 deg from the floor whose bottom
edge lies at x=-0.78, y=0 and faces -x toward the parking bay
(docs/plans/2026-09-23-lane-network-parking-design.md). The offline renders
(dock_scene) must describe the same marker the world builder places.
"""

import importlib.util
import math
import xml.etree.ElementTree as ET
from pathlib import Path

import cv2
import numpy as np
import pytest

import dock_scene

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "map" / "map_v2_fleet"
SOURCE = BUNDLE / "260919 MAP FILE.STL"
WORLD = BUNDLE / "worlds" / "map_v2_fleet.world"
TEXTURE = BUNDLE / "textures" / "dock_tag_7.png"
URI = "model://control/map/map_v2_fleet/textures/dock_tag_7.png"


def _build_world():
    spec = importlib.util.spec_from_file_location(
        "build_world_for_marker", BUNDLE / "scripts" / "build_world.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _marker():
    world = ET.parse(WORLD).getroot().find("world")
    return world.find("./model[@name='dock_tag_7']")


def test_the_world_places_one_static_visual_only_marker():
    model = _marker()
    assert model is not None
    assert model.find("static").text == "true"
    assert model.find(".//collision") is None     # like the paint: never an obstacle
    visual = model.find(".//visual")
    assert visual.find("./geometry/plane/normal").text.split() == ["0", "0", "1"]
    assert visual.find(".//albedo_map").text == URI


def test_the_face_is_inclined_25_deg_with_its_bottom_edge_at_the_bay():
    visual = _marker().find(".//visual")
    x, y, z, roll, pitch, yaw = (float(v) for v in visual.find("pose").text.split())
    sx, sy = (float(v) for v in visual.find("./geometry/plane/size").text.split())
    assert sx == pytest.approx(sy) == pytest.approx(dock_scene.FACE_M, abs=1e-5)
    assert (roll, yaw) == (0.0, 0.0)
    assert pitch == pytest.approx(-math.radians(25.0), abs=1e-5)
    # R_y(pitch) takes the plane's +z normal to (-sin 25, 0, cos 25): facing -x, up.
    normal = (math.sin(pitch), 0.0, math.cos(pitch))
    assert normal[0] < 0.0 and normal[2] > 0.0
    half = sx / 2.0
    bottom_x = x - half * math.cos(-pitch)
    bottom_z = z - half * math.sin(-pitch)
    top_z = z + half * math.sin(-pitch)
    assert bottom_x == pytest.approx(-0.78, abs=1e-4)
    assert y == 0.0
    assert bottom_z == pytest.approx(0.0, abs=0.001)
    assert 0.021 <= top_z <= 0.029                  # the user's 21-29 mm


def test_the_offline_scene_is_the_world_marker():
    build = _build_world()
    assert build.DOCK_TAG_ID == dock_scene.TAG_ID
    assert build.DOCK_TAG_SIZE_M == dock_scene.TAG_SIZE_M
    assert build.DOCK_TAG_TILT_RAD == pytest.approx(dock_scene.FACE_TILT_RAD)
    assert build.DOCK_TAG_BOTTOM_X == dock_scene.BOTTOM_X
    assert build.DOCK_TAG_FACE_M == pytest.approx(dock_scene.FACE_M)


def test_the_texture_decodes_to_id_7_with_a_white_quiet_zone():
    image = cv2.imread(str(TEXTURE), cv2.IMREAD_GRAYSCALE)
    assert image is not None and image.shape[0] == image.shape[1]
    cell = image.shape[0] // 8
    border = np.concatenate([image[:cell].ravel(), image[-cell:].ravel(),
                             image[:, :cell].ravel(), image[:, -cell:].ravel()])
    assert border.min() == 255                     # quiet zone
    assert image[cell:2 * cell, cell:-cell].max() == 0   # the marker's black border
    detector = cv2.aruco.ArucoDetector(
        cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50),
        cv2.aruco.DetectorParameters())
    _, ids, _ = detector.detectMarkers(cv2.copyMakeBorder(
        image, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=255))
    assert ids is not None and ids.flatten().tolist() == [7]
    assert np.array_equal(image, dock_scene.tag_texture())


def test_the_builder_regenerates_the_same_texture(tmp_path):
    _build_world().build(SOURCE, tmp_path)
    rebuilt = cv2.imread(str(tmp_path / "textures" / "dock_tag_7.png"), cv2.IMREAD_GRAYSCALE)
    assert np.array_equal(rebuilt, cv2.imread(str(TEXTURE), cv2.IMREAD_GRAYSCALE))


def test_the_tag_white_stays_under_the_paint_threshold():
    """The face's diffuse keeps the tag's white out of the paint pipeline
    (bright threshold 180); lane paint is 1.0 and the floor 0.2."""
    material = _marker().find(".//visual/material")
    diffuse = [float(v) for v in material.find("diffuse").text.split()]
    assert diffuse[:3] == [0.6, 0.6, 0.6]
