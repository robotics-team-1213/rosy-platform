import math

import pytest

from rosy_cell.load import Box, Pallet
from rosy_cell.pattern import PATTERNS, Placement, best_grid, layer_issues, mirrored, split_block

BOX = Box(length=0.05, width=0.03, height=0.02, mass_kg=0.01)
PALLET = Pallet(length=0.11, width=0.10, max_stack_height=0.10, max_load_kg=1.0)
TOL = {"tol_m": 1e-6}


def test_split_beats_both_pure_grids():
    assert len(best_grid(BOX, PALLET, gap=0.0)) == 6
    layer = split_block(BOX, PALLET, gap=0.0)
    assert len(layer) == 7
    assert sum(1 for p in layer if p.yaw == 0.0) == 3
    assert sum(1 for p in layer if p.yaw == pytest.approx(math.pi / 2)) == 4
    assert layer_issues(layer, BOX, PALLET, **TOL) == []


def test_mirror_reflects_x_and_keeps_the_layer_valid():
    layer = split_block(BOX, PALLET, gap=0.0)
    flipped = mirrored(layer, PALLET)
    assert [round(p.x, 6) for p in flipped] == [round(0.11 - p.x, 6) for p in layer]
    assert layer_issues(flipped, BOX, PALLET, **TOL) == []


def test_overlap_and_overhang_are_reported():
    bad = [Placement(0.025, 0.015, 0.0), Placement(0.03, 0.015, 0.0), Placement(0.10, 0.015, 0.0)]
    issues = layer_issues(bad, BOX, PALLET, **TOL)
    assert "boxes 0 and 1 overlap" in issues
    assert "box 2 overhangs the pallet" in issues


def test_pattern_registry_names():
    assert set(PATTERNS) == {"grid", "split"}


def test_split_centres_without_empty_ninety_degree_columns():
    # pallet 0.13 x 0.04 is too narrow for the 90-degree footprint (0.03 x 0.05): ny1 = floor(0.04/0.05) = 0.
    # ny0 = floor(0.04/0.03) = 1, k = floor(0.13/0.05) = 2 columns -> extent 0.10, x0 = (0.13 - 0.10)/2 = 0.015.
    # centres x = 0.015 + 0.025 = 0.04 and 0.09; y = (0.04 - 0.03)/2 + 0.015 = 0.02.
    narrow = Pallet(length=0.13, width=0.04, max_stack_height=0.10, max_load_kg=1.0)
    layer = split_block(BOX, narrow, gap=0.0)
    assert [(p.x, p.y, p.yaw) for p in layer] == [
        pytest.approx((0.04, 0.02, 0.0)),
        pytest.approx((0.09, 0.02, 0.0)),
    ]
    assert layer_issues(layer, BOX, narrow, **TOL) == []


def test_split_centres_without_empty_zero_degree_columns():
    # box 0.03 long x 0.05 wide: the 0-degree footprint is 0.03 x 0.05 and does not fit width 0.04 (ny0 = 0).
    # 90-degree footprint is 0.05 x 0.03: ny1 = 1, m = floor(0.13/0.05) = 2, k must be 0 -> x0 = 0.015.
    wide = Box(length=0.03, width=0.05, height=0.02, mass_kg=0.01)
    narrow = Pallet(length=0.13, width=0.04, max_stack_height=0.10, max_load_kg=1.0)
    layer = split_block(wide, narrow, gap=0.0)
    assert [(p.x, p.y) for p in layer] == [pytest.approx((0.04, 0.02)), pytest.approx((0.09, 0.02))]
