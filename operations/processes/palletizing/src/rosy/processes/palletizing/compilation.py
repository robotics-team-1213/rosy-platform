"""Build the complete single-cell process result for application and Fleet adapters."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
import json

from . import compiler
from .cell import load_cell
from .plan_bundle import compile_plan_bundle
from .recipe import load_recipe
from .submission import CellJobCompilation


def item_geometry(recipe: Mapping) -> dict[str, dict[str, float]]:
    parsed = load_recipe(json.dumps(dict(recipe), allow_nan=False))
    geometry = {"box": {"grasp_depth_m": parsed.box.grasp_depth, "height_m": parsed.box.height}}
    if parsed.slip_sheet_thickness is not None:
        geometry["slip_sheet"] = {"grasp_depth_m": 0.0, "height_m": parsed.slip_sheet_thickness}
    return geometry


def compile_cell_job(recipe: Mapping, cell: Mapping, *, process_artifact_digest: str,
                     tol_m: float) -> CellJobCompilation:
    if not isinstance(recipe, Mapping) or not isinstance(cell, Mapping):
        raise ValueError("recipe and cell must be document mappings")
    parsed_recipe = load_recipe(json.dumps(dict(recipe), allow_nan=False))
    parsed_cell = load_cell(json.dumps(dict(cell), allow_nan=False))
    job = compiler.compile_job(parsed_recipe, parsed_cell, tol_m=tol_m)
    if compiler.carry_z(parsed_recipe, parsed_cell, tol_m=tol_m) != job.carry_z:
        raise ValueError("Job carry_z differs from the palletizing carry_z")
    plan = compile_plan_bundle(job, parsed_recipe, parsed_cell,
                               process_artifact_digest=process_artifact_digest, tol_m=tol_m)
    return CellJobCompilation(
        job=compiler.job_document(job), plan_bundle=plan.bundle,
        ledger_markers=tuple(asdict(marker) for marker in plan.ledger_markers),
        operator_checkpoints=tuple(checkpoint.as_dict() for checkpoint in plan.operator_checkpoints),
    )
