import math
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


# Fixture split layer (box 0.05 x 0.03, pallet 0.11 x 0.10, gap 0): ny0=floor(0.10/0.03)=3,
# ny1=floor(0.10/0.05)=2; k=1 column at 0 deg + m=floor(0.06/0.03)=2 columns at 90 deg = 7, x0=0.
# Layer 0 centres: yaw 0 at x=0.025, y=0.02/0.05/0.08; yaw 90 at x=0.065/0.095, y=0.025/0.075.
# Layer 1 is mirrored (x -> 0.11 - x): yaw 0 at x=0.085; yaw 90 at x=0.045/0.015.


def test_palletize_job_shape_and_first_place():
    recipe, cell = _inputs()
    job = compile_job(recipe, cell, **TOL)
    assert job.recipe_hash == recipe.content_hash and job.cell_hash == cell.content_hash
    # per pallet: 7 boxes x (pick, place) + 1 sheet x (pick, place) + 7 x 2 + pallet_done = 31
    assert len(job.steps) == 62
    first_pick, first_place = job.steps[0], job.steps[1]
    assert (first_pick.kind, first_pick.item, first_pick.target.y) == ("pick", "box", pytest.approx(0.2))
    assert first_place.kind == "place" and first_place.pallet == "A" and first_place.layer == 0
    # pallet A origin (0.2,0,0), identity -> robot at (-0.2,0) in the pallet frame.
    # farthest layer-0 box: (0.095,0.075): (0.295^2 + 0.075^2) = 0.09265, the largest of the seven.
    # base pose = (0.2+0.095, 0.075, z_top 0.02), yaw pi/2
    assert (first_place.target.x, first_place.target.y, first_place.target.z) == pytest.approx((0.295, 0.075, 0.02))
    assert first_place.target.yaw == pytest.approx(math.pi / 2)
    assert first_place.approach_z == pytest.approx(0.07)  # 0.02 + clearance 0.05
    # last layer-0 place is the nearest box (0.025,0.02): 0.225^2 + 0.02^2 = 0.051025 -> base (0.225, 0.02)
    assert (job.steps[13].target.x, job.steps[13].target.y) == pytest.approx((0.225, 0.02))
    sheet_place = job.steps[15]
    # sheet at pallet centre (0.055,0.05) -> base (0.255,0.05); z = 0.02 box + 0.002 sheet
    assert (sheet_place.item, sheet_place.target.z) == ("slip_sheet", pytest.approx(0.022))
    assert (sheet_place.target.x, sheet_place.target.y) == pytest.approx((0.255, 0.05))
    # layer 1 farthest: (0.085,0.08): 0.285^2 + 0.08^2 = 0.087625 -> base (0.285, 0.08, 0.042)
    assert (job.steps[17].target.x, job.steps[17].target.y, job.steps[17].target.z) == pytest.approx(
        (0.285, 0.08, 0.042)
    )
    assert job.steps[30].kind == "pallet_done" and job.steps[30].pallet == "A"
    # pallet B origin (0.2,-0.15,0) -> robot at (-0.2, 0.15) in its frame; (x+0.2)^2 + (y-0.15)^2:
    # (0.095,0.025): 0.087025+0.015625=0.10265 beats (0.095,0.075): 0.087025+0.005625=0.09265
    # base = (0.2+0.095, -0.15+0.025) = (0.295, -0.125)
    assert job.steps[32].pallet == "B"
    assert (job.steps[32].target.x, job.steps[32].target.y) == pytest.approx((0.295, -0.125))


def test_each_layer_is_placed_from_far_to_near_the_robot():
    recipe, cell = _inputs()
    job = compile_job(recipe, cell, **TOL)
    for pallet in ("A", "B"):
        for layer in (0, 1):
            places = [
                s.target
                for s in job.steps
                if s.kind == "place" and s.item == "box" and s.pallet == pallet and s.layer == layer
            ]
            assert len(places) == 7
            dist = [math.hypot(p.x, p.y) for p in places]  # robot base is the origin
            assert all(a >= b - 1e-12 for a, b in zip(dist, dist[1:])), (pallet, layer, dist)


def test_depalletize_is_the_reverse_of_palletize():
    recipe, cell = _inputs(recipe_edit=("mode: palletize", "mode: depalletize"))
    job = compile_job(recipe, cell, **TOL)
    assert len(job.steps) == 62
    first = job.steps[0]
    assert (first.kind, first.item, first.layer) == ("pick", "box", 1)
    # top layer comes off nearest-first: A layer 1 nearest (0.015,0.025): 0.215^2 + 0.025^2 = 0.04685
    assert (first.target.x, first.target.y, first.target.z) == pytest.approx((0.215, 0.025, 0.042))
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
