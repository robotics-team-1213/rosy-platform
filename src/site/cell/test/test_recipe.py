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
        ('approach: "+x"', 'approach: "up"', "approach"),
        ("{pattern: split}", "{pattern: pinwheel}", "pattern"),
        ("id: B", "id: A", "duplicate pallet id"),
        ("slip_sheet: {thickness: 0.002, station: sheets}\n", "", "slip_sheet"),
        ("length: 0.05", "length: -0.05", "invalid recipe field"),
    ],
)
def test_bad_recipes_name_the_problem(old, new, problem):
    text = FIXTURE.read_text(encoding="utf-8").replace(old, new, 1)
    with pytest.raises(RecipeError) as err:
        load_recipe(text)
    assert any(problem in p for p in err.value.problems), err.value.problems
