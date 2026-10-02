"""Bind process compilation to the injected Fleet submission port, without authority."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
import json
import math
import re

from rosy.execution.site.cell_submission import CellJobCompilation
from rosy.processes.palletizing.cell import load_cell
from rosy.processes.palletizing.compiler import compile_job
from rosy.processes.palletizing.plan_bundle import compile_plan_bundle
from rosy.processes.palletizing.recipe import load_recipe


class PalletizingCellCompiler:
    """The app supplies a pinned installed process artifact and compilation tolerance.

    This adapter neither accepts credentials nor creates Fleet grants. Loading and
    planning remain owned by the existing process; Fleet validates its output and
    separately requires named operator admission.
    """

    def __init__(self, *, process_artifact_digest: str, tol_m: float):
        if not isinstance(process_artifact_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", process_artifact_digest):
            raise ValueError("process_artifact_digest must be a pinned SHA-256")
        if isinstance(tol_m, bool) or not isinstance(tol_m, (int, float)) or not math.isfinite(tol_m) or tol_m <= 0:
            raise ValueError("tol_m must be finite and positive")
        self.process_artifact_digest = process_artifact_digest
        self.tol_m = tol_m

    def compile(self, recipe: Mapping, cell: Mapping) -> CellJobCompilation:
        if not isinstance(recipe, Mapping) or not isinstance(cell, Mapping):
            raise ValueError("recipe and cell must be document mappings")
        parsed_recipe = load_recipe(json.dumps(dict(recipe), allow_nan=False))
        parsed_cell = load_cell(json.dumps(dict(cell), allow_nan=False))
        job = compile_job(parsed_recipe, parsed_cell, tol_m=self.tol_m)
        plan = compile_plan_bundle(job, parsed_recipe, parsed_cell,
                                   process_artifact_digest=self.process_artifact_digest, tol_m=self.tol_m)
        return CellJobCompilation(
            job=json.loads(json.dumps(asdict(job), allow_nan=False)),
            plan_bundle=plan.bundle,
            ledger_markers=tuple(asdict(marker) for marker in plan.ledger_markers),
        )
