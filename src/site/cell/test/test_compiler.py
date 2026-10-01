from pathlib import Path

import pytest

from rosy_cell.cell import load_cell
from rosy_cell.compiler import CompileError, compile_job
from rosy_cell.recipe import load_recipe

FIX = Path(__file__).parent / "fixtures"
TOL = {"tol_m": 1e-6}


def _inputs(recipe_edit=("", ""), cell_edit=("", "")):
    recipe = (FIX / "recipe_two_layer.yaml").read_text(encoding="utf-8").replace(*recipe_edit, 1)
    cell = (FIX / "cell_demo.yaml").read_text(encoding="utf-8").replace(*cell_edit, 1)
    return load_recipe(recipe), load_cell(cell)


def test_palletize_job_shape_and_first_place():
    recipe, cell = _inputs()
    job = compile_job(recipe, cell, **TOL)
    assert job.recipe_hash == recipe.content_hash and job.cell_hash == cell.content_hash
    # per pallet: 7 boxes x (pick, place) + 1 sheet x (pick, place) + 7 x 2 + pallet_done = 31
    assert len(job.steps) == 62
    first_pick, first_place = job.steps[0], job.steps[1]
    assert (first_pick.kind, first_pick.item, first_pick.target.y) == ("pick", "box", pytest.approx(0.2))
    assert first_place.kind == "place" and first_place.pallet == "A" and first_place.layer == 0
    assert (first_place.target.x, first_place.target.y, first_place.target.z) == pytest.approx((0.225, 0.02, 0.02))
    assert first_place.approach_z == pytest.approx(0.07)
    sheet_place = job.steps[15]
    assert (sheet_place.item, sheet_place.target.z) == ("slip_sheet", pytest.approx(0.022))
    assert (sheet_place.target.x, sheet_place.target.y) == pytest.approx((0.255, 0.05))
    assert job.steps[30].kind == "pallet_done" and job.steps[30].pallet == "A"
    assert job.steps[32].target.y == pytest.approx(-0.15 + 0.02)


def test_depalletize_is_the_reverse_of_palletize():
    recipe, cell = _inputs(recipe_edit=("mode: palletize", "mode: depalletize"))
    job = compile_job(recipe, cell, **TOL)
    assert len(job.steps) == 62
    first = job.steps[0]
    assert (first.kind, first.item, first.layer) == ("pick", "box", 1)
    assert (first.target.x, first.target.y, first.target.z) == pytest.approx((0.285, 0.08, 0.042))
    assert job.steps[1].target.y == pytest.approx(0.2)
    assert (job.steps[14].item, job.steps[14].kind) == ("slip_sheet", "pick")


def test_compile_refuses_missing_frame_station_and_tall_stack():
    recipe, cell = _inputs(recipe_edit=("frame: pallet_b", "frame: pallet_c"))
    with pytest.raises(CompileError, match="pallet_c"):
        compile_job(recipe, cell, **TOL)
    recipe, cell = _inputs(recipe_edit=("pick_station: infeed", "pick_station: dock"))
    with pytest.raises(CompileError, match="dock"):
        compile_job(recipe, cell, **TOL)
    recipe, cell = _inputs(recipe_edit=("max_stack_height: 0.05", "max_stack_height: 0.03"))
    with pytest.raises(CompileError, match="pallet A: stack height"):
        compile_job(recipe, cell, **TOL)
