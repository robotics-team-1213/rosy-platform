"""D-941 3: speed table v(s) - lane cap, measured curve cap, stripes, braking ahead."""
import math

from fleet.site_map import SiteMap
from fleet.speed_table import DECEL_MPS2, STRIPE_MPS, CurveCap, speed_table

R = 0.115
ARC = [[1.0 + R * math.sin(a), -R * math.cos(a)] for a in (math.pi * k / 12 for k in range(13))]


def site():
    return SiteMap.model_validate({
        "schema": "rosy.site_map/1", "map_id": "speed_test",
        "places": [{"id": "A", "name": "A", "x": 0.0, "y": -R},
                   {"id": "S5", "name": "U턴 전", "x": 1.0, "y": -R, "kind": "stop"},
                   {"id": "B", "name": "B", "x": 1.0, "y": R}],
        "edges": [{"id": "lower", "from": "A", "to": "S5", "polyline": [[0.0, -R], [1.0, -R]],
                   "direction": "one_way", "width_m": 0.1, "speed_cap_mps": 0.15},
                  {"id": "uturn", "from": "S5", "to": "B", "polyline": ARC,
                   "direction": "one_way", "width_m": 0.1, "speed_cap_mps": 0.15}]})


def at(table, s):
    """The limit in force at distance s (rows are change points)."""
    return [v for s0, v in table["rows"] if s0 <= s + 1e-9][-1]


def test_lane_cap_stripe_and_curve_cap_with_braking_before_them():
    table = speed_table(site(), [("lower", True, 0.0, 1.0), ("uturn", True, 0.0, math.pi * R)],
                        curve_caps=[CurveCap(0.2, 0.08)], start_mps=0.15)
    assert table["curve_caps_measured"] is True
    assert table["stripes"] == [{"place": "S5", "s_m": 1.0}]
    assert at(table, 0.3) == 0.15
    assert at(table, 1.0) <= STRIPE_MPS                       # on the stripe
    assert at(table, 1.2) <= 0.08 + 1e-6                      # in the U-turn
    # braking: just before the stripe the limit already falls on sqrt(v^2 + 2 a d)
    s0 = 1.0 - 0.06 - 0.02
    assert at(table, s0) <= math.sqrt(STRIPE_MPS ** 2 + 2 * DECEL_MPS2 * 0.02) + 0.003
    assert table["rows"][-1][1] == 0.0 and abs(table["length_m"] - (1.0 + math.pi * R)) < 0.01


def test_without_a_measured_curve_cap_the_lane_cap_holds_and_it_says_so():
    table = speed_table(site(), [("uturn", True, 0.0, math.pi * R)], start_mps=0.15)
    assert table["curve_caps_measured"] is False
    assert at(table, 0.15) == 0.15


def test_a_start_from_rest_accelerates_and_a_route_off_the_stripe_has_none():
    table = speed_table(site(), [("lower", True, 0.0, 0.8)])
    assert table["rows"][0] == [0.0, 0.0] and table["stripes"] == []
    assert at(table, 0.02) < 0.15 and at(table, 0.4) == 0.15


def test_a_closed_loop_does_not_stop_at_its_seam_and_slows_on_both_sides_of_a_stripe_there():
    from fleet.lane_progress import main_loop
    square = SiteMap.model_validate({
        "schema": "rosy.site_map/1", "map_id": "loop_speed",
        "places": [{"id": "A", "name": "A", "x": 0.0, "y": 0.0, "kind": "stop"},
                   {"id": "B", "name": "B", "x": 1.0, "y": 0.0}, {"id": "C", "name": "C", "x": 1.0, "y": 1.0},
                   {"id": "D", "name": "D", "x": 0.0, "y": 1.0}],
        "edges": [{"id": a + b, "from": a, "to": b, "polyline": [p, q], "direction": "one_way",
                   "width_m": 0.1, "speed_cap_mps": 0.15}
                  for a, b, p, q in (("A", "B", [0, 0], [1, 0]), ("B", "C", [1, 0], [1, 1]),
                                     ("C", "D", [1, 1], [0, 1]), ("D", "A", [0, 1], [0, 0]))]})
    table = speed_table(square, [(e, True, 0.0, math.inf) for e in main_loop(square)], closed=True)
    assert table["stripes"] == [{"place": "A", "s_m": 0.0}]
    assert at(table, 0.0) <= STRIPE_MPS and at(table, 2.0) == 0.15
    assert at(table, 3.96) <= STRIPE_MPS                      # the stripe's far side, just before the seam
    assert at(table, 3.85) == 0.15 and at(table, 3.925) < 0.15  # braking ahead of it wraps too (~0.033 m)
    assert table["rows"][-1][1] > 0.0                         # a loop never ends at 0
