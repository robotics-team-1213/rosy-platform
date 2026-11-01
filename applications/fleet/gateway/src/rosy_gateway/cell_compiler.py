"""Bind process compilation to the injected Fleet submission port, without authority."""
from __future__ import annotations

from collections.abc import Mapping
import math
import re

from rosy.processes.palletizing import compilation
from rosy.processes.palletizing.submission import CellJobCompilation, compile_cell_submission


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

    def item_geometry(self, recipe: Mapping) -> dict[str, dict[str, float]]:
        """Supply recipe-owned height/depth for Fleet's persisted goal predicates."""
        return compilation.item_geometry(recipe)

    def compile(self, recipe: Mapping, cell: Mapping) -> CellJobCompilation:
        return compilation.compile_cell_job(recipe, cell,
            process_artifact_digest=self.process_artifact_digest, tol_m=self.tol_m)

    def compile_submission(self, candidate: Mapping, *, workcell_id: str, instance_id: str) -> dict:
        return compile_cell_submission(
            candidate, compiler=self, workcell_id=workcell_id, instance_id=instance_id).as_store_document()
