"""The OMX owner's ``CellDocumentValidator`` over injected process rules (D-404 §6, D-413 §1).

The device side owns no process rules. The composition passes rules shaped like
``rosy.processes.palletizing.acceptance.CellDocumentRules``; this wrapper only turns their plain
results into the acceptance store's validated types.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from omx_adapter.cell_acceptance import ValidatedCell, ValidatedRecipe


class CellDocumentRules(Protocol):
    def cell(self, cell: Mapping) -> tuple[str, str]: ...
    def recipe(self, recipe: Mapping, cell: Mapping) -> tuple[str, Mapping[str, Mapping[str, Any]]]: ...


class ProcessCellDocumentValidator:
    """``CellDocumentValidator`` over canonical JSON documents; errors are ``ValueError``."""

    def __init__(self, rules: CellDocumentRules) -> None:
        self.rules = rules

    def validate_cell(self, cell: Mapping) -> ValidatedCell:
        sha256, kinematics_revision = self.rules.cell(cell)
        return ValidatedCell(sha256=sha256, kinematics_revision=kinematics_revision)

    def validate_recipe(self, recipe: Mapping, cell: Mapping) -> ValidatedRecipe:
        sha256, items = self.rules.recipe(recipe, cell)
        return ValidatedRecipe(sha256=sha256, items=items)


__all__ = ["CellDocumentRules", "ProcessCellDocumentValidator"]
