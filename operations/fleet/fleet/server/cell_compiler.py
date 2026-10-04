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

from rosy.execution.site.cell_submission import CellJobCompilation
from rosy.processes import palletizing
from rosy.processes.palletizing import compiler as process_compiler
from rosy.processes.palletizing.cell import load_cell
from rosy.processes.palletizing.plan_bundle import compile_plan_bundle
from rosy.processes.palletizing.recipe import load_recipe


def _process_source_digest() -> str:
    """sha256 over the installed palletizing sources: the process artifact the Job came from."""
    hasher = hashlib.sha256()
    for path in sorted(Path(palletizing.__file__).parent.glob("*.py")):
        hasher.update(path.name.encode("utf-8") + b"\0" + path.read_bytes().replace(b"\r\n", b"\n"))
    return hasher.hexdigest()


class PalletizingCellJobCompiler:
    """``compile(recipe, cell)`` for ``compile_cell_submission``; documents are canonical JSON."""

    def __init__(self, *, tol_m: float) -> None:
        if (isinstance(tol_m, bool) or not isinstance(tol_m, (int, float))
                or not math.isfinite(tol_m) or tol_m <= 0):
            raise ValueError("stack tolerance tol_m must be a positive finite number")
        self.tol_m = float(tol_m)
        self.process_artifact_digest = _process_source_digest()

    def item_geometry(self, recipe: Mapping) -> dict[str, dict[str, float]]:
        """Grasp depth and height per item, read from the validated Recipe (1c P3): the box depth
        default lives only in the palletizing Box; a slip sheet is taken at its top face."""
        parsed = load_recipe(json.dumps(recipe, allow_nan=False))
        geometry = {"box": {"grasp_depth_m": parsed.box.grasp_depth, "height_m": parsed.box.height}}
        if parsed.slip_sheet_thickness is not None:
            geometry["slip_sheet"] = {"grasp_depth_m": 0.0, "height_m": parsed.slip_sheet_thickness}
        return geometry

    def compile(self, recipe: Mapping, cell: Mapping) -> CellJobCompilation:
        # JSON is YAML, and both hashes are taken over the parsed value, so they are unchanged.
        parsed_recipe = load_recipe(json.dumps(recipe, allow_nan=False))
        parsed_cell = load_cell(json.dumps(cell, allow_nan=False))
        job = process_compiler.compile_job(parsed_recipe, parsed_cell, tol_m=self.tol_m)
        if process_compiler.carry_z(parsed_recipe, parsed_cell, tol_m=self.tol_m) != job.carry_z:
            raise ValueError("Job carry_z differs from the palletizing carry_z")
        plan = compile_plan_bundle(job, parsed_recipe, parsed_cell,
                                   process_artifact_digest=self.process_artifact_digest,
                                   tol_m=self.tol_m)
        return CellJobCompilation(
            job=process_compiler.job_document(job), plan_bundle=plan.bundle,
            ledger_markers=tuple({"after_step_ordinal": marker.after_step_ordinal,
                                  "pallet_id": marker.pallet_id} for marker in plan.ledger_markers),
            operator_checkpoints=tuple(checkpoint.as_dict() for checkpoint in plan.operator_checkpoints),
        )


__all__ = ["PalletizingCellJobCompiler"]
