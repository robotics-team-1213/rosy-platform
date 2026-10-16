"""Hand-computed recipe/3 cases: the expected numbers are worked out on paper from D-781 §1, §3, §4.

These catch a misread rule (for example "at least 60 %" instead of "more than 60 %"), which the
independent checker in test_mixed_planner.py would share with the planner.
"""

from __future__ import annotations

import pytest
import yaml

from rosy.processes.palletizing.mixed_cell import Finger, annulus_reach, workcell_from_dict
from rosy.processes.palletizing.mixed_planner import plan_mixed
from rosy.processes.palletizing.mixed_recipe import load_mixed_recipe
from rosy.processes.palletizing.mixed_rules import (
    Placed,
    in_approach,
    loads_on_top,
    support_ok,
    support_ratio_and_corners,
)
from rosy.processes.palletizing.recipe import RecipeError


def box(i, x, y, z, lx, ly, h=0.03, mass=0.02, yaw=0, top_kg=0.1, depth=0.015):
    return Placed(i, "s", "A", x, y, z, lx, ly, h, yaw, mass, top_kg, depth)


# ---- support_ratio_v1 ------------------------------------------------------------------------

def test_three_corners_and_81_percent_pass():
    # B 40x40 mm on A1 (40x30 at the origin) and A2 (20x20 at y 35 mm).
    # Contact: 40*30 + 20*5 = 1300 mm^2 of 1600 = 81.25 %; corners (0,0) (40,0) on A1, (0,40) on A2.
    a1, a2 = box(0, 0, 0, 0, 0.04, 0.03), box(1, 0, 0.035, 0, 0.02, 0.02)
    b = box(2, 0, 0, 0.03, 0.04, 0.04)
    ratio, corners = support_ratio_and_corners(b, [a1, a2])
    assert ratio == pytest.approx(0.8125) and corners == 3
    assert support_ok(ratio, corners)
    # Without A2: 75 % and two corners -> fails every clause.
    ratio, corners = support_ratio_and_corners(b, [a1])
    assert ratio == pytest.approx(0.75) and corners == 2
    assert not support_ok(ratio, corners)


def test_sixty_percent_needs_more_than_sixty():
    # B 40x40 mm over two 40x12 mm strips at y 0 and y 28 mm: 2*480 = 960 of 1600 = exactly 60 %, 4 corners.
    b = box(2, 0, 0, 0.03, 0.04, 0.04)
    exact = [box(0, 0, 0, 0, 0.04, 0.012), box(1, 0, 0.028, 0, 0.04, 0.012)]
    ratio, corners = support_ratio_and_corners(b, exact)
    assert ratio == pytest.approx(0.60) and corners == 4
    assert not support_ok(ratio, corners)
    # 15 mm strips: 1200 of 1600 = 75 % with 4 corners passes the first clause.
    wider = [box(0, 0, 0, 0, 0.04, 0.015), box(1, 0, 0.025, 0, 0.04, 0.015)]
    assert support_ok(*support_ratio_and_corners(b, wider))


def test_ninety_six_percent_passes_with_two_corners():
    # B 40x30 shifted 1.5 mm over A 40x30: contact 38.5*30 = 96.25 %, corners at x 1.5 only -> 2.
    a, b = box(0, 0, 0, 0, 0.04, 0.03), box(1, 0.0015, 0, 0.03, 0.04, 0.03)
    ratio, corners = support_ratio_and_corners(b, [a])
    assert ratio == pytest.approx(0.9625) and corners == 2
    assert support_ok(ratio, corners)


# ---- load on top -----------------------------------------------------------------------------

def test_load_splits_by_contact_area_and_passes_down():
    # B (20 g) bridges A1 and A2 with equal contact; C (10 g) sits on B only.
    a1, a2 = box(0, 0, 0, 0, 0.02, 0.03), box(1, 0.028, 0, 0, 0.02, 0.03)
    b = box(2, 0.004, 0, 0.03, 0.04, 0.03, mass=0.02)
    c = box(3, 0.01, 0, 0.06, 0.02, 0.02, h=0.02, mass=0.01)
    carried = loads_on_top([a1, a2, b, c])
    assert carried[3] == pytest.approx(0.0)
    assert carried[2] == pytest.approx(0.01)
    assert carried[0] == pytest.approx(0.015) and carried[1] == pytest.approx(0.015)


# ---- finger clearance / approach --------------------------------------------------------------

def test_finger_strip_relation():
    # A 40x30x30 mm at the origin, yaw 0: fingers beside y=0 and y=30 mm, 14 mm out
    # (4 margin + 10 thick), x 20 +- 21 mm, from z 12 mm (30 - 15 grasp - 3 overhang) up.
    finger = Finger()
    a = box(0, 0, 0, 0, 0.04, 0.03)
    assert in_approach(a, box(1, 0, 0.035, 0, 0.04, 0.03), finger)       # 5 mm away: in the strip
    assert not in_approach(a, box(1, 0, 0.045, 0, 0.04, 0.03), finger)   # 15 mm away: clear
    assert not in_approach(a, box(1, 0.065, 0.035, 0, 0.04, 0.03), finger)  # beside the strip in x
    assert not in_approach(a, box(1, 0, 0.035, 0, 0.04, 0.03, h=0.01), finger)  # below z 12 mm
    yawed = box(0, 0, 0, 0, 0.03, 0.04, yaw=90)  # width along x: fingers beside x
    assert in_approach(yawed, box(1, 0.035, 0, 0, 0.03, 0.04), finger)
    assert not in_approach(yawed, box(1, 0, 0.045, 0, 0.03, 0.04), finger)


# ---- whole plan: two identical items on a pallet that fits exactly one footprint -------------

def _tower_text(yaws=(0,), orientation="yaw_only"):
    return yaml.safe_dump({
        "schema": "rosy_cell.recipe/3", "name": "tower", "mode": "palletize",
        "items": [{"sku": "foam", "length": 0.04, "width": 0.03, "height": 0.03, "mass_kg": 0.02,
                   "grasp_depth": 0.015, "quantity": 2, "orientation": orientation, "max_load_on_top_kg": 0.1}],
        "pallets": [{"id": "A", "frame": "pallet_a", "length": 0.04, "width": 0.03, "max_stack_height": 0.07,
                     "max_load_kg": 0.5}],
        "pick_stations": ["infeed"], "gap": 0.008,
        "stability": {"rule": "support_ratio_v1", "max_height_to_base_ratio": 1.5},
        "planner": {"candidates": "extreme_points", "yaw_deg": list(yaws), "allow_push": False},
    })


def test_tower_plan_numbers():
    cell = workcell_from_dict({"arms": [{"role": "solo", "base_in_cell": {"x": 0.0, "y": 0.0}}],
                               "pallet_origins": {"A": [0.10, 0.0, 0.0]}, "stations": {"infeed": [0.0, 0.15, 0.0]}})
    plan = plan_mixed(load_mixed_recipe(_tower_text()), cell, annulus_reach(cell, 0.05, 0.30))
    s0, s1 = plan.steps
    # Centre (0.12, 0.015); TCP 15 mm under the top: z 0.015 then 0.045.
    assert (s0.pose_cell.x, s0.pose_cell.y) == pytest.approx((0.12, 0.015))
    assert s0.pose_cell.z == pytest.approx(0.015) and s1.pose_cell.z == pytest.approx(0.045)
    assert s0.depends_on == () and s1.depends_on == (0,)
    # carry_z = highest surface that may stand + hang (30 - 15 mm) + clearance 20 mm.
    # Step 0 runs before step 1 (its only descendant): surfaces 0 -> 0.035.
    # Step 1: step 0 stands, top 0.03 -> 0.065.
    assert s0.carry_z == pytest.approx(0.035) and s1.carry_z == pytest.approx(0.065)
    assert s0.pick_cell.z == pytest.approx(0.015)
    assert dict(plan.feed_order) == {"infeed": ((0, "foam"), (1, "foam"))}


def test_upright_fixed_needs_yaw_zero():
    with pytest.raises(RecipeError, match="upright_fixed"):
        load_mixed_recipe(_tower_text(yaws=(90,), orientation="upright_fixed"))
    recipe = load_mixed_recipe(_tower_text(yaws=(0, 90), orientation="upright_fixed"))
    assert recipe.items[0].yaws_deg(recipe.planner.yaw_deg) == (0,)
