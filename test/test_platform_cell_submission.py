"""Cell Job submissions cross the execution boundary without importing the process."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for relative in (
    "contracts/skill/src",
    "modules/execution/src",
    "modules/skills/api/src",
):
    path = str(ROOT / relative)
    if path not in sys.path:
        sys.path.insert(0, path)

from rosy.execution.api import PlanBundle, PlanStep
from rosy.execution.site.cell_submission import (
    CellJobCompilation,
    compile_cell_submission,
)
from rosy.skills.api import SkillInvocation


@dataclass
class Compiler:
    output: CellJobCompilation
    calls: list[tuple[dict, dict]]

    def compile(self, recipe: dict, cell: dict) -> CellJobCompilation:
        self.calls.append((recipe, cell))
        return self.output


def _inputs(pallet_id: str = "pallet-1") -> dict:
    return {
        "item": "box",
        "pallet_id": pallet_id,
        "layer_index": 0,
        "home_pose_base": {"x_m": 0.0, "y_m": 0.0, "z_m": 0.4, "yaw_rad": 0.0},
        "source_pose_base": {"x_m": 0.1, "y_m": 0.2, "z_m": 0.3, "yaw_rad": 0.0},
        "destination_pose_base": {"x_m": 0.4, "y_m": 0.5, "z_m": 0.3, "yaw_rad": 1.57},
        "source_approach_z_base_m": 0.5,
        "destination_approach_z_base_m": 0.5,
        "carry_z_base_m": 0.6,
    }


def _compilation(job: dict | None = None) -> CellJobCompilation:
    inputs = _inputs()
    canonical_job = job or {"steps": ["pick", "place", "pallet_done"]}
    bundle = PlanBundle(
        process_artifact_digest="a" * 64,
        recipe_digest="b" * 64,
        cell_digest="c" * 64,
        steps=(PlanStep(0, SkillInvocation("pallet.transfer", "1.0.0", inputs)),),
    )
    return CellJobCompilation(
        job=canonical_job,
        plan_bundle=bundle,
        ledger_markers=({"after_step_ordinal": 1, "pallet_id": "pallet-1"},),
    )


def _candidate(job: dict | None = None) -> dict:
    return {
        "kind": "cell_job",
        "recipe": {"schema": "rosy_cell.recipe/1"},
        "cell": {"schema": "rosy_cell.cell/2"},
        "recipe_sha256": "b" * 64,
        "cell_sha256": "c" * 64,
        "job": job or {"steps": ["pick", "place", "pallet_done"]},
    }


def test_cell_submission_recompiles_and_preserves_ordered_plan_and_ledger():
    compiler = Compiler(_compilation(), [])

    result = compile_cell_submission(
        _candidate(), compiler=compiler, workcell_id="cell-1", instance_id="omx-1",
    )

    assert compiler.calls == [(_candidate()["recipe"], _candidate()["cell"])]
    assert result.job == _candidate()["job"]
    assert result.plan_bundle.steps[0].ordinal == 0
    assert result.action_kinds == ("CELL_TRANSFER",)
    assert result.resources == (("workcell", "cell-1"), ("pallet", "pallet-1"))
    assert result.ledger_markers == ((1, "pallet-1"),)
    assert result.plan_bundle.steps[0].invocation.inputs["home_pose_base"]["z_m"] == 0.4
    assert result.as_store_document()["steps"][0]["inputs"]["pallet_id"] == "pallet-1"


def test_cell_submission_rejects_candidate_job_that_differs_from_recompilation():
    compiler = Compiler(_compilation(), [])

    with pytest.raises(ValueError, match="recompiled Job"):
        compile_cell_submission(
            _candidate({"steps": ["changed"]}), compiler=compiler,
            workcell_id="cell-1", instance_id="omx-1",
        )


def test_cell_submission_rejects_revision_and_non_transfer_skill_mismatch():
    wrong_revision = Compiler(
        CellJobCompilation(
            job=_candidate()["job"],
            plan_bundle=PlanBundle(
                process_artifact_digest="a" * 64, recipe_digest="d" * 64,
                cell_digest="c" * 64,
                steps=(PlanStep(0, SkillInvocation("pallet.transfer", "1.0.0", _inputs())),),
            ), ledger_markers=({"after_step_ordinal": 1, "pallet_id": "pallet-1"},),
        ), [],
    )
    with pytest.raises(ValueError, match="recipe digest"):
        compile_cell_submission(
            _candidate(), compiler=wrong_revision,
            workcell_id="cell-1", instance_id="omx-1",
        )

    other_skill = Compiler(
        CellJobCompilation(
            job=_candidate()["job"],
            plan_bundle=PlanBundle(
                process_artifact_digest="a" * 64, recipe_digest="b" * 64,
                cell_digest="c" * 64,
                steps=(PlanStep(0, SkillInvocation("robot.move", "1.0.0", {})),),
            ), ledger_markers=({"after_step_ordinal": 1, "pallet_id": "pallet-1"},),
        ), [],
    )
    with pytest.raises(ValueError, match="pallet.transfer"):
        compile_cell_submission(
            _candidate(), compiler=other_skill,
            workcell_id="cell-1", instance_id="omx-1",
        )


@pytest.mark.parametrize("candidate_update", [
    {"kind": "PICK_PLACE"},
    {"recipe_sha256": "invalid"},
    {"workcell_id": "attacker"},
])
def test_cell_submission_rejects_invalid_or_untrusted_envelopes(candidate_update):
    compiler = Compiler(_compilation(), [])
    candidate = {**_candidate(), **candidate_update}
    with pytest.raises(ValueError):
        compile_cell_submission(
            candidate, compiler=compiler, workcell_id="cell-1", instance_id="omx-1",
        )
