import math

import pytest

from rosy_cell.load import Box, Pallet
from rosy_cell.pattern import best_grid, footprint, grid

BOX = Box(length=0.04, width=0.03, height=0.02, mass_kg=0.01)
PALLET = Pallet(length=0.12, width=0.09, max_stack_height=0.10, max_load_kg=1.0)


def test_box_and_pallet_reject_non_positive_sizes():
    with pytest.raises(ValueError):
        Box(length=0.0, width=0.03, height=0.02, mass_kg=0.01)
    with pytest.raises(ValueError):
        Pallet(length=0.12, width=0.09, max_stack_height=-1.0, max_load_kg=1.0)


def test_footprint_swaps_sides_at_ninety_degrees():
    assert footprint(BOX, 0.0) == (0.04, 0.03)
    assert footprint(BOX, math.pi / 2) == (0.03, 0.04)


def test_exact_fit_grid_counts_and_centres():
    layer = grid(BOX, PALLET, gap=0.0, yaw=0.0)
    assert len(layer) == 9
    assert (layer[0].x, layer[0].y) == pytest.approx((0.02, 0.015))
    assert len(grid(BOX, PALLET, gap=0.0, yaw=math.pi / 2)) == 8


def test_gap_reduces_count_and_block_is_centred():
    layer = grid(BOX, PALLET, gap=0.01, yaw=0.0)
    assert len(layer) == 4
    assert (layer[0].x, layer[0].y) == pytest.approx((0.035, 0.025))


def test_best_grid_picks_the_orientation_with_more_boxes():
    layer = best_grid(BOX, PALLET, gap=0.0)
    assert len(layer) == 9
    assert all(p.yaw == 0.0 for p in layer)
