"""Production CellJobCompiler port adapter: Fleet recompiles a Cell Job with the palletizing process.

This is the only Fleet module that imports ``rosy.processes.palletizing`` (D-413: the execution
port stays process-free; the composition injects this adapter into ``create_app``). Fleet never
re-derives carry_z: it calls the process function and refuses a Job that disagrees (D-403 §2).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path

from rosy.processes import palletizing
from rosy.processes.palletizing import compilation
from rosy.processes.palletizing.mixed_cell_doc import load_mixed_cell
from rosy.processes.palletizing.mixed_recipe import load_mixed_recipe
from rosy.processes.palletizing.mixed_submission import compile_mixed_cell_job
from rosy.processes.palletizing.submission import CellJobCompilation, compile_cell_submission

from .cell_mixed_submission import MIXED_RECIPE_SCHEMA, MixedCellCompilation


def _process_source_digest() -> str:
    """sha256 over the installed palletizing sources: the process artifact the Job came from."""
    hasher = hashlib.sha256()
    for path in sorted(Path(palletizing.__file__).parent.glob("*.py")):
        hasher.update(path.name.encode("utf-8") + b"\0" + path.read_bytes().replace(b"\r\n", b"\n"))
    return hasher.hexdigest()


class PalletizingCellJobCompiler:
    """``compile(recipe, cell)`` for ``compile_cell_submission`` and ``compile_mixed(recipe, cell)`` for a
    recipe/3 multi-arm submission (cell_mixed_submission); documents are canonical JSON."""

    def __init__(self, *, tol_m: float) -> None:
        if (isinstance(tol_m, bool) or not isinstance(tol_m, (int, float))
                or not math.isfinite(tol_m) or tol_m <= 0):
            raise ValueError("stack tolerance tol_m must be a positive finite number")
        self.tol_m = float(tol_m)
        self.process_artifact_digest = _process_source_digest()

    def item_geometry(self, recipe: Mapping) -> dict[str, dict[str, float]]:
        """Grasp depth and height per item, read from the validated Recipe (1c P3): the box depth
        default lives only in the palletizing Box; a slip sheet is taken at its top face. A
        recipe/3 is keyed by sku (its steps' inputs name the sku, D-781 §2)."""
        if recipe.get("schema") == MIXED_RECIPE_SCHEMA:
            mixed = load_mixed_recipe(json.dumps(recipe, allow_nan=False))
            return {item.sku: {"grasp_depth_m": item.grasp_depth, "height_m": item.height} for item in mixed.items}
        return compilation.item_geometry(recipe)

    def compile(self, recipe: Mapping, cell: Mapping) -> CellJobCompilation:
        return compilation.compile_cell_job(recipe, cell,
            process_artifact_digest=self.process_artifact_digest, tol_m=self.tol_m)

    def compile_submission(self, candidate: Mapping, *, workcell_id: str, instance_id: str) -> dict:
        return compile_cell_submission(
            candidate, compiler=self, workcell_id=workcell_id, instance_id=instance_id).as_store_document()

    def compile_mixed(self, recipe: Mapping, cell: Mapping) -> MixedCellCompilation:
        """recipe/3 + cell/3 -> the mixed plan compiled for every arm (D-781 §5). The planner and
        submission versions are in the Job; the process sources are in process_artifact_digest."""
        compiled = compile_mixed_cell_job(load_mixed_recipe(json.dumps(recipe, allow_nan=False)),
                                          load_mixed_cell(json.dumps(cell, allow_nan=False)))
        return MixedCellCompilation(
            job=compiled.job, arms=compiled.arms, steps=compiled.steps, ledger_markers=compiled.ledger_markers,
            pallet_ids=compiled.pallet_ids, recipe_digest=compiled.recipe_digest, cell_digest=compiled.cell_digest,
            process_artifact_digest=self.process_artifact_digest)


__all__ = ["PalletizingCellJobCompiler"]
