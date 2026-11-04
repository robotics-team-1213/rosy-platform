"""Palletizing rules a cell owner runs before accepting a cell/recipe (D-404 §6, C4b G2a).

The OMX owner's acceptance store (``omx_adapter.cell_acceptance``) owns the journal and the hash
checks but no process rules (D-413 §1). The composition injects these rules: the same loaders and
compiler Fleet uses, so a recipe is accepted only if it compiles against the accepted cell. Results
are plain values; the owner wraps them in its own validated types.

A recipe/3 (D-781) is validated against a cell/3 document with the mixed compiler, and its
accepted geometry has one entry per sku under the grant's ``item_key`` (``box:<sku>``, D-781 §2).
The owner does not accept a cell/3 document yet (``cell`` is the cell/1 loader), so a recipe/3 is
refused until that acceptance is decided.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping

from core_common.protocol.cell_transfer import item_geometry_key

from . import SCHEMA_RECIPE_MIXED
from .cell import load_cell
from .compiler import compile_job
from .mixed_cell_doc import load_mixed_cell
from .mixed_recipe import load_mixed_recipe
from .mixed_submission import ITEM, compile_mixed_cell_job
from .recipe import load_recipe

Geometry = dict[str, dict[str, float]]


class CellDocumentRules:
    """Validate canonical JSON documents; errors are ``ValueError``."""

    def __init__(self, *, tol_m: float) -> None:
        if (isinstance(tol_m, bool) or not isinstance(tol_m, (int, float))
                or not math.isfinite(tol_m) or tol_m <= 0):
            raise ValueError("stack tolerance tol_m must be a positive finite number")
        self.tol_m = float(tol_m)

    def cell(self, cell: Mapping) -> tuple[str, str]:
        """(content sha256, kinematics revision) of an accepted cell document."""
        parsed = load_cell(json.dumps(cell, allow_nan=False))
        return parsed.content_hash, parsed.kinematics_revision

    def recipe(self, recipe: Mapping, cell: Mapping) -> tuple[str, Geometry]:
        """(content sha256, grasp geometry per item key) of a recipe that compiles against ``cell``."""
        if recipe.get("schema") == SCHEMA_RECIPE_MIXED:
            return self.mixed_recipe(recipe, cell)
        parsed = load_recipe(json.dumps(recipe, allow_nan=False))
        compile_job(parsed, load_cell(json.dumps(cell, allow_nan=False)), tol_m=self.tol_m)
        box = parsed.box
        # Only the box has a grasp; a slip sheet stays without geometry, so its transfer is refused.
        return parsed.content_hash, {"box": {
            "grasp_width_m": box.width, "grasp_depth_m": box.grasp_depth, "height_m": box.height}}

    @staticmethod
    def mixed_recipe(recipe: Mapping, cell: Mapping) -> tuple[str, Geometry]:
        """recipe/3 against a cell/3: it must compile; one geometry entry per sku (width = grasped)."""
        parsed = load_mixed_recipe(json.dumps(recipe, allow_nan=False))
        compile_mixed_cell_job(parsed, load_mixed_cell(json.dumps(cell, allow_nan=False)))
        return parsed.content_hash, {
            item_geometry_key(ITEM, item.sku): {"grasp_width_m": item.width, "grasp_depth_m": item.grasp_depth,
                                                "height_m": item.height} for item in parsed.items}


__all__ = ["CellDocumentRules"]
