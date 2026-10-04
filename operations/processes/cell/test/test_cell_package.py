from rosy_cell import SCHEMA_CELL, SCHEMA_RECIPE


def test_schema_ids_are_versioned():
    assert SCHEMA_RECIPE == "rosy_cell.recipe/1"
    assert SCHEMA_CELL == "rosy_cell.cell/2"
