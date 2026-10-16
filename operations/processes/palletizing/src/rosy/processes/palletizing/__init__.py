"""Palletizing process rules and compilation, without robot or ROS dependencies."""

SCHEMA_RECIPE = "rosy_cell.recipe/1"
SCHEMA_RECIPE_MANUAL = "rosy_cell.recipe/2"
SCHEMA_RECIPE_MIXED = "rosy_cell.recipe/3"  # D-781 mixed items, planned placement
SCHEMA_CELL = "rosy_cell.cell/2"
SCHEMA_CELL_MIXED = "rosy_cell.cell/3"  # D-778 §1 multi-arm workcell, provisional G0 shape (mixed_cell_doc.py)

__all__ = ["SCHEMA_RECIPE", "SCHEMA_RECIPE_MANUAL", "SCHEMA_RECIPE_MIXED", "SCHEMA_CELL", "SCHEMA_CELL_MIXED"]
