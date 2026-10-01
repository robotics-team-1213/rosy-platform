from pathlib import Path

import pytest

from rosy_cell.recipe import RecipeError, load_recipe

FIXTURE = Path(__file__).parent / "fixtures" / "recipe_two_layer.yaml"


def test_fixture_loads_with_a_stable_hash():
    text = FIXTURE.read_text(encoding="utf-8")
    recipe = load_recipe(text)
    assert recipe.mode == "palletize"
    assert [slot.id for slot in recipe.pallets] == ["A", "B"]
    assert recipe.layers[1].mirrored and recipe.layers[1].slip_sheet_below
    assert recipe.slip_sheet_station == "sheets"
    assert len(recipe.content_hash) == 64
    reordered = text.replace("mode: palletize\n", "") + "mode: palletize\n"
    assert load_recipe(reordered).content_hash == recipe.content_hash


@pytest.mark.parametrize(
    "old, new, problem",
    [
        ("rosy_cell.recipe/1", "rosy_cell.recipe/0", "schema"),
        ("mode: palletize", "mode: stack", "mode"),
        ("{pattern: split}", "{pattern: pinwheel}", "pattern"),
        ("id: B", "id: A", "duplicate pallet id"),
        ("slip_sheet: {thickness: 0.002, station: sheets}\n", "", "slip_sheet"),
        ("length: 0.05", "length: -0.05", "box"),
        # non-finite and wrong-typed numbers
        ("length: 0.05", "length: .nan", "box.length"),
        ("length: 0.05", "length: .inf", "box.length"),
        ("length: 0.05", "length: yes", "box.length"),
        ("length: 0.05", "length: '0.05'", "box.length"),
        ("length: 0.11", "length: .nan", "pallets[0].length"),
        ("max_load_kg: 1.0", "max_load_kg: [1]", "pallets[0].max_load_kg"),
        ("gap: 0.0", "gap: .nan", "gap"),
        ("gap: 0.0", "gap: -0.01", "gap"),
        ("gap: 0.0", "gap: 'none'", "gap"),
        # slip sheet thickness
        ("thickness: 0.002", "thickness: -0.03", "slip_sheet.thickness"),
        ("thickness: 0.002", "thickness: 0", "slip_sheet.thickness"),
        ("thickness: 0.002", "thickness: .inf", "slip_sheet.thickness"),
        ("slip_sheet: {thickness: 0.002, station: sheets}", "slip_sheet: [0.002]", "slip_sheet"),
        # booleans must be real booleans
        ("mirrored: true", "mirrored: 'false'", "layers[1].mirrored"),
        ("slip_sheet_below: true", "slip_sheet_below: 1", "layers[1].slip_sheet_below"),
        # malformed containers, keys and ids
        ("{pattern: split}", "{pattern: [split]}", "layers[0].pattern"),
        ("layers:\n", "layers: 3\nold_layers:\n", "layers"),
        ("{pattern: split}", "split", "layers[0]"),
        ("box: {length: 0.05, width: 0.03, height: 0.02, mass_kg: 0.01}", "box: [0.05, 0.03]", "box"),
        ("id: A", "id: 7", "pallets[0].id"),
        ("frame: pallet_a", "frame: [pallet_a]", "pallets[0].frame"),
        ("pick_station: infeed", "pick_station: 3", "pick_station"),
        ("name: foam-blocks-two-layer", "name: 12", "name"),
        ("mode: palletize", "mode: [palletize]", "mode"),
        ("pallets:\n", "pallets: {A: 1}\nold_pallets:\n", "pallets"),
        ("height: 0.02", "height: 0.02, colour: red", "box.colour"),
        ("gap: 0.0", "gap: 0.0\napproach: '+x'", "approach"),
        ("gap: 0.0", "gap: 0.0\nmade_on: 2026-10-01", "made_on"),
        ("gap: 0.0", "gap: 0.0\n1: one", "1"),
        ("gap: 0.0\n", "", "gap"),
    ],
)
def test_bad_recipes_name_the_problem(old, new, problem):
    text = FIXTURE.read_text(encoding="utf-8").replace(old, new, 1)
    with pytest.raises(RecipeError) as err:
        load_recipe(text)
    assert any(problem in p for p in err.value.problems), err.value.problems


@pytest.mark.parametrize("text", ["", "- a list", "a: [unclosed", "just text"])
def test_non_mapping_or_unparsable_text_is_a_recipe_error(text):
    with pytest.raises(RecipeError):
        load_recipe(text)


def test_all_field_problems_are_reported_together():
    text = FIXTURE.read_text(encoding="utf-8").replace("length: 0.05", "length: yes", 1)
    text = text.replace("gap: 0.0", "gap: -1", 1).replace("mirrored: true", "mirrored: 'no'", 1)
    with pytest.raises(RecipeError) as err:
        load_recipe(text)
    joined = " | ".join(err.value.problems)
    assert "box.length" in joined and "gap" in joined and "layers[1].mirrored" in joined, joined


def test_hash_is_over_parsed_values_so_int_and_float_differ():
    # documented false reject (safe direction): `gap: 0` and `gap: 0.0` parse to int and float
    text = FIXTURE.read_text(encoding="utf-8")
    assert load_recipe(text).content_hash != load_recipe(text.replace("gap: 0.0", "gap: 0", 1)).content_hash
