"""Palletizing process rules and compilation, without robot or ROS dependencies."""

SCHEMA_RECIPE = "rosy_cell.recipe/1"
SCHEMA_RECIPE_MANUAL = "rosy_cell.recipe/2"
SCHEMA_RECIPE_MIXED = "rosy_cell.recipe/3"  # D-781 mixed items, planned placement
SCHEMA_CELL = "rosy_cell.cell/2"

__all__ = ["SCHEMA_RECIPE", "SCHEMA_RECIPE_MANUAL", "SCHEMA_RECIPE_MIXED", "SCHEMA_CELL"]
