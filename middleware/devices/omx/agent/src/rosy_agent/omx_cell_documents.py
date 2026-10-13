"""Palletizing validation for the OMX owner's accepted cell/recipe store (D-404 §6, C4b G2a).

The device adapter (``omx_adapter.cell_acceptance``) owns the journal and the hash checks but no
process rules (D-413 §1). This composition supplies the rules: the same palletizing loaders and
compiler Fleet uses, run inside the owner process, so a recipe is accepted only if it compiles
against the accepted cell.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping

from omx_adapter.cell_acceptance import ValidatedCell, ValidatedRecipe
from rosy.processes.palletizing.cell import load_cell
from rosy.processes.palletizing.compiler import compile_job
from rosy.processes.palletizing.recipe import load_recipe


class PalletizingCellDocumentValidator:
    """``CellDocumentValidator`` over canonical JSON documents; errors are ``ValueError``."""

    def __init__(self, *, tol_m: float) -> None:
        if (isinstance(tol_m, bool) or not isinstance(tol_m, (int, float))
                or not math.isfinite(tol_m) or tol_m <= 0):
            raise ValueError("stack tolerance tol_m must be a positive finite number")
        self.tol_m = float(tol_m)

    def validate_cell(self, cell: Mapping) -> ValidatedCell:
        parsed = load_cell(json.dumps(cell, allow_nan=False))
        return ValidatedCell(sha256=parsed.content_hash, kinematics_revision=parsed.kinematics_revision)

    def validate_recipe(self, recipe: Mapping, cell: Mapping) -> ValidatedRecipe:
        parsed = load_recipe(json.dumps(recipe, allow_nan=False))
        compile_job(parsed, load_cell(json.dumps(cell, allow_nan=False)), tol_m=self.tol_m)
        box = parsed.box
        # Only the box has a grasp; a slip sheet stays without geometry, so its transfer is refused.
        return ValidatedRecipe(sha256=parsed.content_hash, items={"box": {
            "grasp_width_m": box.width, "grasp_depth_m": box.grasp_depth, "height_m": box.height}})


__all__ = ["PalletizingCellDocumentValidator"]
