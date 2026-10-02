import math
from pathlib import Path

import pytest

from rosy_cell.cell import load_cell
from rosy_cell.compiler import CompileError, carry_z, compile_job
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
    # the last pallet filled (B) is emptied first
    assert (first.kind, first.item, first.pallet, first.layer) == ("pick", "box", "B", 1)
    # B's top layer comes off nearest-first. Robot at (-0.2, 0.15) in B's frame; mirrored layer 1 nearest is
    # (0.015,0.075): 0.215^2 + 0.075^2 = 0.05185 -> base (0.2+0.015, -0.15+0.075, 0.042)
    assert (first.target.x, first.target.y, first.target.z) == pytest.approx((0.215, -0.075, 0.042))
    assert job.steps[1].target.y == pytest.approx(0.2)
    assert (job.steps[14].item, job.steps[14].kind) == ("slip_sheet", "pick")
    assert [(s.kind, s.pallet) for s in job.steps if s.kind == "pallet_done"] == [
        ("pallet_done", "B"),
        ("pallet_done", "A"),
    ]
    assert job.steps[30].pallet == "B" and job.steps[31].pallet == "A"


def test_depalletize_transfers_are_palletize_transfers_reversed():
    pal = compile_job(*_inputs(), **TOL).steps
    dep = compile_job(*_inputs(recipe_edit=("mode: palletize", "mode: depalletize")), **TOL).steps

    def moves(steps):
        pairs = [s for s in steps if s.kind != "pallet_done"]
        return [(a.item, a.pallet, a.layer, a.target, b.target) for a, b in zip(pairs[::2], pairs[1::2])]

    swapped = [(item, pallet, layer, dst, src) for item, pallet, layer, src, dst in moves(pal)]
    assert moves(dep) == swapped[::-1]


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


def test_compile_refuses_a_robot_base_inside_the_pallet_footprint():
    # pallet_a taught with origin (-0.05,-0.05,0), identity axes: from_base(0,0,0) = (0.05, 0.05),
    # which lies inside the 0.11 x 0.10 pallet, so far-first order is meaningless there.
    recipe, cell = _inputs(
        cell_edit=(
            "pallet_a: {origin: [0.2, 0, 0], x_point: [0.3, 0, 0], plane_point: [0.2, 0.1, 0]}",
            "pallet_a: {origin: [-0.05, -0.05, 0], x_point: [0.05, -0.05, 0], plane_point: [-0.05, 0.05, 0]}",
        )
    )
    with pytest.raises(CompileError, match="pallet A: robot base lies inside the pallet footprint"):
        compile_job(recipe, cell, **TOL)


# carry_z hand calculation (fixtures): every frame is flat at z = 0. Stack per pallet: layer 0 top 0.02,
# slip sheet 0.002, layer 1 top 0.02 + 0.002 + 0.02 = 0.042. Stations: infeed 0.02, sheets 0.002.
# Highest surface = 0.042 (pallet stack top); + box height 0.02 + approach_clearance_m 0.05 = 0.112.
# The home pose z (0.15) is not an obstacle and must not enter the value.
def test_carry_z_reproduces_the_hand_calculation():
    recipe, cell = _inputs()
    assert carry_z(recipe, cell, **TOL) == pytest.approx(0.112)


def test_carry_z_rises_with_a_tilted_pallet_frame():
    flat = carry_z(*_inputs(), **TOL)
    # plane_point 5 mm above the plane tilts pallet_a by atan(0.005 / 0.1) ~ 2.9 deg (within max_tilt_deg 5);
    # its far-y corners (y = 0.10 m) lift the stack top by ~0.005 m
    tilted = carry_z(*_inputs(cell_edit=("plane_point: [0.2, 0.1, 0]", "plane_point: [0.2, 0.1, 0.005]")), **TOL)
    assert tilted > flat + 0.004


def test_carry_z_covers_a_station_above_every_stack():
    recipe, cell = _inputs(cell_edit=("sheets: {frame: base, x: -0.1, y: 0.2, z: 0.002", "sheets: {frame: base, x: -0.1, y: 0.2, z: 0.3"))
    assert carry_z(recipe, cell, **TOL) == pytest.approx(0.3 + 0.02 + 0.05)


def test_job_carries_carry_z_and_no_step_approaches_above_it():
    recipe, cell = _inputs()
    job = compile_job(recipe, cell, **TOL)
    assert job.carry_z == carry_z(recipe, cell, **TOL)
    approaches = [s.approach_z for s in job.steps if s.approach_z is not None]
    assert approaches and all(z <= job.carry_z for z in approaches)


def test_carry_z_refuses_unknown_frames_and_stations_like_compile_job():
    recipe, cell = _inputs(recipe_edit=("frame: pallet_b", "frame: pallet_c"))
    with pytest.raises(CompileError, match="pallet_c"):
        carry_z(recipe, cell, **TOL)
    recipe, cell = _inputs(recipe_edit=("pick_station: infeed", "pick_station: dock"))
    with pytest.raises(CompileError, match="dock"):
        carry_z(recipe, cell, **TOL)


# grasp_depth (C3b B1): the OMX-F TCP sits at the fingertips, so the TCP grasps a box
# grasp_depth below its top face. Box Step targets carry that TCP height; approach_z still
# clears the top face; the held box hangs (height - grasp_depth) below the TCP in carry.
DEPTH = ("height: 0.02, mass_kg: 0.01}", "height: 0.02, mass_kg: 0.01, grasp_depth: 0.008}")


def test_box_steps_target_the_tcp_grasp_depth_below_the_top_face():
    flat, deep = compile_job(*_inputs(), **TOL), compile_job(*_inputs(recipe_edit=DEPTH), **TOL)
    for a, b in zip(flat.steps, deep.steps):
        if a.kind == "pallet_done":
            continue
        drop = 0.008 if a.item == "box" else 0.0  # slip sheets are taken at their top face
        assert b.target.z == pytest.approx(a.target.z - drop)
        assert b.approach_z == pytest.approx(a.approach_z)  # clearance above the top face
        assert (b.target.x, b.target.y, b.target.yaw) == (a.target.x, a.target.y, a.target.yaw)


def test_carry_z_hangs_the_box_below_the_tcp_by_height_minus_depth():
    # highest surface 0.042 + (0.02 - 0.008) + clearance 0.05
    recipe, cell = _inputs(recipe_edit=DEPTH)
    assert carry_z(recipe, cell, **TOL) == pytest.approx(0.042 + 0.012 + 0.05)
    job = compile_job(recipe, cell, **TOL)
    assert all(s.approach_z <= job.carry_z for s in job.steps if s.approach_z is not None)


def test_carry_z_still_clears_a_slip_sheet_thicker_than_the_box_overhang():
    recipe, cell = _inputs(recipe_edit=("height: 0.02, mass_kg: 0.01}",
                                        "height: 0.02, mass_kg: 0.01, grasp_depth: 0.0195}"),
                           cell_edit=("fingertip_overhang_m: 0.0025", "fingertip_overhang_m: 0.0"))
    # box overhang 0.0005 < sheet 0.002 (tool without fingertip overhang): the sheet sets the hang
    assert carry_z(recipe, cell, **TOL) == pytest.approx(0.042 + 0.002 + 0.05)


# Review minor 4: the fingertips reach fingertip_overhang_m below the TCP (cell.yaml tool
# field, the same value as the OMX profile; test/test_cell_omx_sim_layout_contract.py pins it).


def test_cell_carries_the_tool_fingertip_overhang():
    _, cell = _inputs()
    assert cell.fingertip_overhang_m == pytest.approx(0.0025)


def test_carry_z_hangs_the_fingertips_when_they_reach_below_the_box():
    # box 0.02 - depth 0.008 = 0.012 overhang below TCP < fingertips 0.015 below TCP
    recipe, cell = _inputs(recipe_edit=DEPTH, cell_edit=(
        "fingertip_overhang_m: 0.0025", "fingertip_overhang_m: 0.012"))
    assert carry_z(recipe, cell, **TOL) == pytest.approx(0.042 + 0.012 + 0.05)
    recipe, cell = _inputs(recipe_edit=("height: 0.02, mass_kg: 0.01}",
                                        "height: 0.02, mass_kg: 0.01, grasp_depth: 0.006}"),
                           cell_edit=("fingertip_overhang_m: 0.0025", "fingertip_overhang_m: 0.014"))
    assert carry_z(recipe, cell, **TOL) == pytest.approx(0.042 + 0.014 + 0.05)


def test_grasp_depth_that_puts_the_fingertips_below_the_box_is_refused():
    recipe, cell = _inputs(recipe_edit=("height: 0.02, mass_kg: 0.01}",
                                        "height: 0.02, mass_kg: 0.01, grasp_depth: 0.018}"))
    with pytest.raises(CompileError, match="fingertip"):
        compile_job(recipe, cell, **TOL)
    with pytest.raises(CompileError, match="fingertip"):
        carry_z(recipe, cell, **TOL)
    recipe, cell = _inputs(recipe_edit=("height: 0.02, mass_kg: 0.01}",
                                        "height: 0.02, mass_kg: 0.01, grasp_depth: 0.0175}"))
    assert compile_job(recipe, cell, **TOL)  # exactly h - overhang is allowed
