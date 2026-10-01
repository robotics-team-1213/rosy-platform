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
