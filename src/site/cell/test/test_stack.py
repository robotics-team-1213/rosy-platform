import pytest

from rosy_cell.load import Box, Pallet
from rosy_cell.stack import LayerSpec, build_stack, stack_issues

BOX = Box(length=0.05, width=0.03, height=0.02, mass_kg=0.01)
PALLET = Pallet(length=0.11, width=0.10, max_stack_height=0.05, max_load_kg=1.0)
LAYERS = [LayerSpec("split"), LayerSpec("split", mirrored=True, slip_sheet_below=True)]


def test_two_layers_with_a_slip_sheet():
    plan = build_stack(BOX, PALLET, LAYERS, gap=0.0, slip_sheet_thickness=0.002)
    assert [len(layer) for layer in plan.layers] == [7, 7]
    assert plan.layers[0][0].z_top == pytest.approx(0.02)
    assert plan.slip_sheets[0].below_layer == 1
    assert plan.slip_sheets[0].z == pytest.approx(0.022)
    assert plan.layers[1][0].z_top == pytest.approx(0.042)
    assert plan.height == pytest.approx(0.042)
    assert plan.mass_kg == pytest.approx(0.14)
    assert stack_issues(plan, BOX, PALLET, tol_m=1e-6) == []


def test_height_load_and_empty_layer_are_reported():
    low = Pallet(length=0.11, width=0.10, max_stack_height=0.04, max_load_kg=0.1)
    plan = build_stack(BOX, low, LAYERS, gap=0.0, slip_sheet_thickness=0.002)
    issues = stack_issues(plan, BOX, low, tol_m=1e-6)
    assert any(i.startswith("stack height") for i in issues)
    assert any(i.startswith("stack mass") for i in issues)
    tiny = Pallet(length=0.01, width=0.01, max_stack_height=0.05, max_load_kg=1.0)
    empty = build_stack(BOX, tiny, [LayerSpec("grid")], gap=0.0, slip_sheet_thickness=0.002)
    assert "layer 0 is empty" in stack_issues(empty, BOX, tiny, tol_m=1e-6)


def test_unknown_pattern_is_rejected():
    with pytest.raises(ValueError, match="unknown pattern"):
        build_stack(BOX, PALLET, [LayerSpec("pinwheel")], gap=0.0, slip_sheet_thickness=0.002)
