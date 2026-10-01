import pytest

from rosy_cell.stack import PlacedBox
from rosy_cell.sequence import APPROACHES, place_order

LAYER = (
    PlacedBox(0, 0.095, 0.075, 0.02, 0.0),
    PlacedBox(0, 0.025, 0.050, 0.02, 0.0),
    PlacedBox(0, 0.025, 0.020, 0.02, 0.0),
    PlacedBox(0, 0.065, 0.025, 0.02, 0.0),
)


def test_far_side_first_for_each_approach():
    assert [(b.x, b.y) for b in place_order(LAYER, approach="+x")][:2] == [(0.025, 0.020), (0.025, 0.050)]
    assert place_order(LAYER, approach="-x")[0].x == 0.095
    assert place_order(LAYER, approach="+y")[0].y == 0.020
    assert place_order(LAYER, approach="-y")[0].y == 0.075


def test_unknown_approach_is_rejected():
    assert set(APPROACHES) == {"+x", "-x", "+y", "-y"}
    with pytest.raises(ValueError):
        place_order(LAYER, approach="up")
