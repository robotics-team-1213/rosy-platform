"""MAP v2 fleet floor reference squares (D-395 rev. 1): data, 180 deg asymmetry, sim world."""

import math
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

BUNDLE = Path(__file__).resolve().parents[1] / "map" / "map_v2_fleet"
RULES = BUNDLE / "lane_rules.yaml"
WORLDS = (BUNDLE / "worlds" / "map_v2_fleet.world", BUNDLE / "worlds" / "map_v2_fleet_real.world")
#: Half the track's 2.76 m inner width / 1.2 m height bounds every square.
INNER_HALF = (1.38, 0.60)


@pytest.fixture(scope="module")
def squares():
    return yaml.safe_load(RULES.read_text(encoding="utf-8"))["reference_squares"]


def test_two_squares_with_the_documented_fields(squares):
    assert [s["id"] for s in squares] == ["A", "B"]
    for s in squares:
        assert s["outline_colour"] == "red" and s["fill_colour"] == "blue"
        assert "image-derived" in s["source"] and "pending" in s["source"]
        assert s["uncertainty_m"] == pytest.approx(0.03)
        (w, h), (fw, fh) = s["size"], s["fill_size"]
        assert 0.05 < fw < w < 0.25 and 0.05 < fh < h < 0.25
        x, y = s["centre"]
        assert abs(x) + w / 2 < INNER_HALF[0] and abs(y) + h / 2 < INNER_HALF[1]


def test_layout_is_not_invariant_under_180_deg_rotation(squares):
    """The point of the squares: a mirrored AMCL hypothesis predicts no square
    where one is seen, so every rotated square must land >= 0.3 m from all squares."""
    centres = [tuple(s["centre"]) for s in squares]
    rotated = [(-x, -y) for x, y in centres]
    nearest = min(math.dist(r, c) for r in rotated for c in centres)
    assert nearest >= 0.3
    assert nearest == pytest.approx(0.40, abs=0.02)


def test_a_square_fixes_the_heading_axis_but_not_its_sign(squares):
    """A robot placed on a square faces along the road, either way (user, 2026-10-01).

    The rules carry only the axis; the start candidates are axis and axis + 180,
    and the scan fit picks one. Flipping the heading swaps the front and rear wall
    distances along the axis, so the scan tells them apart only when the square
    is off-centre along that axis."""
    for s in squares:
        assert s["heading_axis_deg"] in (0, 90)
        along = s["centre"][0] if s["heading_axis_deg"] == 0 else s["centre"][1]
        assert abs(along) > 0.3   # front/rear walls differ by 2*|along| > 0.6 m


@pytest.mark.parametrize("world_path", WORLDS, ids=lambda p: p.name)
def test_world_has_flat_visual_only_patches_matching_the_rules(world_path, squares):
    world = ET.parse(world_path).getroot().find("world")
    for s in squares:
        model = world.find(f"./model[@name='reference_square_{s['id']}']")
        assert model is not None and model.find("static").text == "true"
        assert model.find(".//collision") is None
        x, y, z = (float(v) for v in model.find("pose").text.split()[:3])
        assert (x, y) == pytest.approx(tuple(s["centre"]), abs=5e-4) and z == 0.0
        outline, fill = model.findall(".//visual")
        for visual, size in ((outline, s["size"]), (fill, s["fill_size"])):
            got = [float(v) for v in visual.find("./geometry/plane/size").text.split()]
            assert got == pytest.approx(size, abs=5e-4)
        z_out, z_fill = (float(v.find("pose").text.split()[2]) for v in (outline, fill))
        assert 0.001 < z_out < z_fill < 0.01   # above the paint mesh (0.001), still flat
