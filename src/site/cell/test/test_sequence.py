import math

import pytest

from rosy_cell.geometry import Frame
from rosy_cell.sequence import place_order
from rosy_cell.stack import PlacedBox

RULES = {"min_span_m": 0.02, "min_angle_deg": 10.0}
LAYER = (
    PlacedBox(0, 0.095, 0.075, 0.02, 0.0),
    PlacedBox(0, 0.025, 0.050, 0.02, 0.0),
    PlacedBox(0, 0.025, 0.020, 0.02, 0.0),
    PlacedBox(0, 0.065, 0.025, 0.02, 0.0),
)


def _xy(boxes):
    return [(b.x, b.y) for b in boxes]


def test_from_base_inverts_to_base():
    f = Frame.from_three_points((1, 2, 0), (1, 3, 0), (0, 2, 0), **RULES)
    p = (0.5, 0.25, 0.1)
    assert f.from_base(f.to_base(p)) == pytest.approx(p)
    # robot base (0,0,0): p - origin = (-1,-2,0); x_axis=(0,1,0) -> -2, y_axis=(-1,0,0) -> 1
    assert f.from_base((0.0, 0.0, 0.0)) == pytest.approx((-2.0, 1.0, 0.0))


def test_pallet_in_front_of_the_robot_places_high_x_first():
    # pallet origin (0.2,0,0), identity axes -> robot at (-0.2, 0) in the pallet frame.
    # squared distances (x+0.2)^2 + y^2:
    #   (0.095,0.075): 0.087025+0.005625=0.09265   (0.065,0.025): 0.070225+0.000625=0.07085
    #   (0.025,0.050): 0.050625+0.0025  =0.053125  (0.025,0.020): 0.050625+0.0004  =0.051025
    f = Frame.from_three_points((0.2, 0, 0), (0.3, 0, 0), (0.2, 0.1, 0), **RULES)
    assert _xy(place_order(LAYER, f)) == [(0.095, 0.075), (0.065, 0.025), (0.025, 0.050), (0.025, 0.020)]


def test_pallet_beside_the_robot_places_far_y_first():
    # pallet origin (0,0.2,0), identity axes -> robot at (0, -0.2) in the pallet frame.
    # squared distances x^2 + (y+0.2)^2:
    #   (0.095,0.075): 0.009025+0.075625=0.08465   (0.065,0.025): 0.004225+0.050625=0.05485
    #   (0.025,0.050): 0.000625+0.0625  =0.063125  (0.025,0.020): 0.000625+0.0484  =0.049025
    f = Frame.from_three_points((0, 0.2, 0), (0.1, 0.2, 0), (0, 0.3, 0), **RULES)
    assert _xy(place_order(LAYER, f)) == [(0.095, 0.075), (0.025, 0.050), (0.065, 0.025), (0.025, 0.020)]


def test_robot_behind_a_turned_pallet():
    # origin (0.3,0,0), x_axis=(-1,0,0), y_axis=(0,-1,0): from_base(0)=R^T(-0.3,0,0)=(0.3, 0, 0).
    # squared distances (x-0.3)^2 + y^2:
    #   (0.025,0.020): 0.075625+0.0004=0.076025  (0.025,0.050): 0.075625+0.0025=0.078125
    #   (0.065,0.025): 0.055225+0.000625=0.05585 (0.095,0.075): 0.042025+0.005625=0.04765
    f = Frame.from_three_points((0.3, 0, 0), (0.2, 0, 0), (0.3, -0.1, 0), **RULES)
    assert _xy(place_order(LAYER, f)) == [(0.025, 0.050), (0.025, 0.020), (0.065, 0.025), (0.095, 0.075)]


def test_equal_distance_ties_break_on_x_then_y():
    # robot at (0.05, -1) in the pallet frame (origin (-0.05,1,0)); (0.0,0) and (0.1,0) are equidistant
    f = Frame.from_three_points((-0.05, 1, 0), (0.05, 1, 0), (-0.05, 1.1, 0), **RULES)
    tie = (PlacedBox(0, 0.1, 0.0, 0.02, 0.0), PlacedBox(0, 0.0, 0.0, 0.02, 0.0))
    assert math.isclose(math.dist((0.1, 0.0), (0.05, -1.0)), math.dist((0.0, 0.0), (0.05, -1.0)))
    assert _xy(place_order(tie, f)) == [(0.0, 0.0), (0.1, 0.0)]
