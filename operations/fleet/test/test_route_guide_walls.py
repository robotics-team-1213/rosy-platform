"""D-573 rev 8: Fleet names the map walls beside a robot's lane in its route prior."""

import json
import math
from pathlib import Path

import pytest

from fleet.site_map import SiteMap, SiteWall
from fleet.traffic.route_guide import wall_sides

V5 = Path(__file__).resolve().parents[3] / "deploy/site/site-maps/map_v2_fleet-v5.json"
WALLS = SiteMap.model_validate(json.loads(V5.read_text(encoding="utf-8"))).walls


def test_the_west_lane_has_the_outer_wall_on_its_right_going_south_and_on_its_left_going_north():
    assert wall_sides(WALLS, -1.2825, 0.0, -math.pi / 2, 0.0925) == (None, pytest.approx(-0.1175), pytest.approx(0.625))
    assert wall_sides(WALLS, -1.2825, 0.0, math.pi / 2, 0.0925) == (pytest.approx(0.1175), None, pytest.approx(0.625))


def test_no_wall_far_away_across_the_road_ahead_or_reaching_into_the_lane():
    assert wall_sides(WALLS, 0.0, 0.0, 0.0, 0.0925) == (None, None, None)
    assert wall_sides(WALLS, -1.0, 0.0, math.pi, 0.0925) == (None, None, None)        # wall_w across the way
    assert wall_sides(WALLS, -1.35, 0.0, -math.pi / 2, 0.0925) == (None, None, None)   # 5 cm: inside the lane
    opening = [SiteWall(id="o", face=((0.3, -0.12), (1.0, -0.12)))]                     # starts ahead: an opening first
    assert wall_sides(opening, 0.0, 0.0, 0.0, 0.0925) == (None, None, None)


def test_a_turned_wall_reads_at_its_outermost_point_ahead():
    turned = [SiteWall(id="t", face=((0.0, -0.08), (0.8, -0.18)))]
    assert wall_sides(turned, 0.0, 0.0, 0.0, 0.0925) == (None, None, None)         # its near end is in the lane
    turned = [SiteWall(id="t", face=((0.0, -0.12), (0.8, -0.16)))]
    assert wall_sides(turned, 0.0, 0.0, 0.0, 0.0925)[1:] == (pytest.approx(-0.16), pytest.approx(0.8))
    short = [SiteWall(id="s", face=((-0.2, -0.12), (0.3, -0.12)))]                  # ends 0.3 m ahead
    assert wall_sides(short, 0.0, 0.0, 0.0, 0.0925)[1:] == (pytest.approx(-0.12), pytest.approx(0.3))


def test_walls_need_finite_points_unique_ids_and_a_length():
    with pytest.raises(ValueError):
        SiteWall(id="w", face=((0.0, 0.0), (0.01, 0.0)))
    with pytest.raises(ValueError):
        SiteWall(id="w", face=((0.0, float("nan")), (1.0, 0.0)))
    body = json.loads(V5.read_text(encoding="utf-8"))
    with pytest.raises(ValueError):
        SiteMap.model_validate({**body, "walls": body["walls"] + body["walls"][:1]})
