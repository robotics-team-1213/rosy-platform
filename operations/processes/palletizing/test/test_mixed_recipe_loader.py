"""recipe/3 loader (D-781 §1): accepted fields, refusals, gripper range, content hash."""

from __future__ import annotations

import pytest
import yaml

from rosy.processes.palletizing import SCHEMA_RECIPE, SCHEMA_RECIPE_MANUAL, SCHEMA_RECIPE_MIXED
from rosy.processes.palletizing.mixed_recipe import GripRange, load_mixed_recipe
from rosy.processes.palletizing.recipe import RecipeError, content_hash, load_recipe

BASE = {
    "schema": "rosy_cell.recipe/3",
    "name": "omx-mixed-foam",
    "mode": "palletize",
    "items": [
        {"sku": "foam_40x30x30", "length": 0.040, "width": 0.030, "height": 0.030, "mass_kg": 0.020,
         "grasp_depth": 0.015, "quantity": 4, "orientation": "yaw_only", "max_load_on_top_kg": 0.10},
        {"sku": "foam_30x20x20", "length": 0.030, "width": 0.020, "height": 0.020, "mass_kg": 0.010,
         "quantity": 2, "orientation": "upright_fixed", "max_load_on_top_kg": 0.05},
    ],
    "pallets": [{"id": "A", "frame": "pallet_a", "length": 0.20, "width": 0.15, "max_stack_height": 0.07,
                 "max_load_kg": 0.5}],
    "pick_stations": ["infeed_left", "infeed_right"],
    "gap": 0.008,
    "stability": {"rule": "support_ratio_v1", "max_height_to_base_ratio": 1.5},
    "planner": {"candidates": "extreme_points", "yaw_deg": [0, 90], "allow_push": False},
}


def doc(**changes: object) -> dict:
    data = yaml.safe_load(yaml.safe_dump(BASE))
    for key, value in changes.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    return data


def item(**changes: object) -> dict:
    out = dict(BASE["items"][0])
    out.update(changes)
    return out


def load(data: dict, **kw: object):
    return load_mixed_recipe(yaml.safe_dump(data), **kw)


def problems(data: dict, **kw: object) -> str:
    with pytest.raises(RecipeError) as err:
        load(data, **kw)
    return "; ".join(err.value.problems)


def test_schema_constant_is_new_and_distinct():
    assert SCHEMA_RECIPE_MIXED == "rosy_cell.recipe/3"
    assert SCHEMA_RECIPE_MIXED not in {SCHEMA_RECIPE, SCHEMA_RECIPE_MANUAL}


def test_valid_recipe_loads_with_canonical_hash():
    data = doc()
    recipe = load(data)
    assert recipe.name == "omx-mixed-foam"
    assert [i.sku for i in recipe.items] == ["foam_40x30x30", "foam_30x20x20"]
    assert recipe.items[1].grasp_depth == 0.0
    assert recipe.pick_stations == ("infeed_left", "infeed_right")
    assert recipe.planner.yaw_deg == (0, 90) and recipe.planner.allow_push is False
    assert recipe.stability.rule == "support_ratio_v1"
    assert recipe.content_hash == content_hash(data)
    assert load(doc()).content_hash == recipe.content_hash


def test_orientation_controls_allowed_yaws():
    recipe = load(doc())
    assert recipe.items[0].yaws_deg((0, 90)) == (0, 90)
    assert recipe.items[1].yaws_deg((0, 90)) == (0,)


@pytest.mark.parametrize("key, value, needle", [
    ("layers", [{"pattern": "grid"}], "layers is not accepted"),
    ("slip_sheet", {"thickness": 0.002, "station": "sheets"}, "slip_sheet is not accepted"),
    ("box", {"length": 0.04}, "box is not accepted"),
    ("pick_station", "infeed", "pick_station is not accepted"),
    ("extra", 1, "recipe.extra is not a known field"),
])
def test_refused_and_unknown_top_level_keys(key, value, needle):
    assert needle in problems(doc(**{key: value}))


def test_depalletize_is_refused():
    assert "depalletize is not accepted" in problems(doc(mode="depalletize"))
    assert "mode must be palletize" in problems(doc(mode="sort"))


def test_wrong_schema_is_refused_and_recipe1_loader_refuses_recipe3():
    assert "schema must be rosy_cell.recipe/3" in problems(doc(schema="rosy_cell.recipe/1"))
    with pytest.raises(RecipeError):
        load_recipe(yaml.safe_dump(doc()))


@pytest.mark.parametrize("width", [0.005, 0.0099, 0.0501, 0.08])
def test_grasped_width_outside_default_gripper_range(width):
    data = doc(items=[item(width=width, length=0.09, height=0.005, grasp_depth=0.0)])
    assert "outside the gripper range" in problems(data)


def test_gripper_range_is_injected():
    data = doc(items=[item(width=0.06, length=0.08)])
    assert "outside the gripper range" in problems(data)
    assert load(data, grip_range=GripRange(0.010, 0.070)).items[0].width == 0.06
    assert "outside the gripper range" in problems(doc(), grip_range=GripRange(0.035, 0.070))


@pytest.mark.parametrize("changes, needle", [
    ({"length": -0.04}, "sizes must be positive"),
    ({"height": 0.0}, "sizes must be positive"),
    ({"mass_kg": "heavy"}, "mass_kg must be a number"),
    ({"grasp_depth": 0.03}, "grasp_depth must be in [0, height)"),
    ({"quantity": 0}, "quantity must be a positive integer"),
    ({"quantity": True}, "quantity must be a positive integer"),
    ({"quantity": 1.5}, "quantity must be a positive integer"),
    ({"orientation": "any"}, "orientation must be one of"),
    ({"max_load_on_top_kg": -1}, "max_load_on_top_kg must be non-negative"),
    ({"colour": "red"}, "items[0].colour is not a known field"),
    ({"height": 0.05}, "exceeds max_height_to_base_ratio"),
])
def test_bad_item_fields(changes, needle):
    assert needle in problems(doc(items=[item(**changes)]))


def test_missing_item_field_and_duplicates():
    bad = item()
    del bad["max_load_on_top_kg"]
    assert "items[0].max_load_on_top_kg is missing" in problems(doc(items=[bad]))
    assert "duplicate sku 'foam_40x30x30'" in problems(doc(items=[item(), item()]))
    assert "at least one item is required" in problems(doc(items=[]))
    assert "duplicate stations" in problems(doc(pick_stations=["a", "a"]))
    assert "needs at least one station" in problems(doc(pick_stations=[]))


@pytest.mark.parametrize("planner, needle", [
    ({"candidates": "extreme_points", "yaw_deg": [0, 90], "allow_push": True}, "allow_push must be false"),
    ({"candidates": "extreme_points", "yaw_deg": [45], "allow_push": False}, "yaw_deg must be"),
    ({"candidates": "extreme_points", "yaw_deg": [], "allow_push": False}, "yaw_deg must be"),
    ({"candidates": "extreme_points", "yaw_deg": [0, 0], "allow_push": False}, "yaw_deg must be"),
    ({"candidates": "pct", "yaw_deg": [0], "allow_push": False}, "candidates must be one of"),
    ({"candidates": "extreme_points", "yaw_deg": [0], "allow_push": False, "seed": 1}, "planner.seed"),
])
def test_bad_planner(planner, needle):
    assert needle in problems(doc(planner=planner))


@pytest.mark.parametrize("stability, needle", [
    ({"rule": "support_ratio_v2", "max_height_to_base_ratio": 1.5}, "stability.rule must be one of"),
    ({"rule": "support_ratio_v1", "max_height_to_base_ratio": 0}, "must be positive"),
    ({"rule": "support_ratio_v1"}, "stability.max_height_to_base_ratio is missing"),
])
def test_bad_stability(stability, needle):
    assert needle in problems(doc(stability=stability))


def test_pallets_reuse_recipe1_rules():
    pallets = BASE["pallets"] * 2
    assert "duplicate pallet id 'A'" in problems(doc(pallets=pallets))
    assert "at least one pallet is required" in problems(doc(pallets=[]))


def test_every_problem_is_reported_at_once():
    found = problems(doc(layers=[], mode="depalletize", gap=-1))
    assert "layers is not accepted" in found and "depalletize" in found and "gap must be non-negative" in found


def test_not_a_mapping():
    assert "must be a mapping" in "; ".join(pytest.raises(RecipeError, load_mixed_recipe, "- a").value.problems)
