"""C4b G5: the production CellJobCompiler recompiles with the palletizing process (D-403 §3)."""

import ast
from pathlib import Path
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[4]
for relative in ("contracts/skill/src", "modules/execution/src", "modules/skills/api/src", "operations/processes/palletizing/src"):
    path = str(ROOT / relative)
    if path not in sys.path:
        sys.path.insert(0, path)

from fleet.server.cell_compiler import PalletizingCellJobCompiler  # noqa: E402
from rosy.execution.site.cell_submission import CellJobCompilation, compile_cell_submission  # noqa: E402
from rosy.processes.palletizing import compiler as process_compiler  # noqa: E402
from rosy.processes.palletizing.cell import load_cell  # noqa: E402
from rosy.processes.palletizing.compiler import compile_job, job_document  # noqa: E402
from rosy.processes.palletizing.recipe import load_recipe  # noqa: E402

EXAMPLES = ROOT / "src/site/cell/examples/omx_sim"
TOL_M = 0.001


def _documents():
    return (yaml.safe_load((EXAMPLES / "recipe.yaml").read_text(encoding="utf-8")),
            yaml.safe_load((EXAMPLES / "cell.yaml").read_text(encoding="utf-8")))


def _candidate(recipe_doc, cell_doc):
    import json
    recipe = load_recipe(json.dumps(recipe_doc))
    cell = load_cell(json.dumps(cell_doc))
    return {"kind": "cell_job", "recipe": recipe_doc, "cell": cell_doc,
            "recipe_sha256": recipe.content_hash, "cell_sha256": cell.content_hash,
            "job": job_document(compile_job(recipe, cell, tol_m=TOL_M))}


def test_adapter_returns_the_palletizing_job_bundle_and_ledger():
    recipe_doc, cell_doc = _documents()
    compiled = PalletizingCellJobCompiler(tol_m=TOL_M).compile(recipe_doc, cell_doc)

    candidate = _candidate(recipe_doc, cell_doc)
    assert isinstance(compiled, CellJobCompilation)
    assert compiled.job == candidate["job"]
    assert compiled.plan_bundle.recipe_digest == candidate["recipe_sha256"]
    assert compiled.plan_bundle.cell_digest == candidate["cell_sha256"]
    assert len(compiled.plan_bundle.steps) == 18  # 2 pallets x 2 layers x 4 boxes + 2 sheets
    assert [marker["pallet_id"] for marker in compiled.ledger_markers] == ["A", "B"]
    carry = compiled.plan_bundle.steps[0].invocation.inputs["carry_z_base_m"]
    assert carry == compiled.job["carry_z"]


def test_recompiled_candidate_passes_and_a_tampered_job_is_a_mismatch():
    recipe_doc, cell_doc = _documents()
    adapter = PalletizingCellJobCompiler(tol_m=TOL_M)
    candidate = _candidate(recipe_doc, cell_doc)

    submission = compile_cell_submission(candidate, compiler=adapter,
                                         workcell_id="omx_sim", instance_id="omx_sim_01")
    assert submission.resources == (("workcell", "omx_sim"), ("pallet", "A"), ("pallet", "B"))
    assert len(submission.as_store_document()["steps"]) == 18

    candidate["job"]["steps"][1]["target"]["x"] += 0.001
    with pytest.raises(ValueError, match="differs from the recompiled Job"):
        compile_cell_submission(candidate, compiler=adapter,
                                workcell_id="omx_sim", instance_id="omx_sim_01")


def test_carry_z_comes_from_the_process_function_not_a_copy(monkeypatch):
    recipe_doc, cell_doc = _documents()
    monkeypatch.setattr(process_compiler, "carry_z", lambda recipe, cell, *, tol_m: 9.75)
    with pytest.raises(ValueError, match="carry_z"):
        PalletizingCellJobCompiler(tol_m=TOL_M).compile(recipe_doc, cell_doc)


def test_artifact_digest_names_the_process_source():
    adapter = PalletizingCellJobCompiler(tol_m=TOL_M)
    recipe_doc, cell_doc = _documents()
    assert adapter.compile(recipe_doc, cell_doc).plan_bundle.process_artifact_digest == (
        adapter.process_artifact_digest)
    assert len(adapter.process_artifact_digest) == 64


@pytest.mark.parametrize("tol_m", [0, -1.0, float("nan"), True, "0.001"])
def test_tolerance_has_no_default_and_must_be_positive(tol_m):
    with pytest.raises(ValueError):
        PalletizingCellJobCompiler(tol_m=tol_m)


def test_invalid_documents_raise_value_errors():
    recipe_doc, cell_doc = _documents()
    with pytest.raises(ValueError):
        PalletizingCellJobCompiler(tol_m=TOL_M).compile({**recipe_doc, "box": "x"}, cell_doc)


def test_only_cell_compiler_imports_the_palletizing_process_in_fleet():
    fleet = ROOT / "src/site/fleet/fleet"
    importers = []
    for path in fleet.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            if any(name.startswith("rosy.processes") for name in names):
                importers.append(path.relative_to(fleet).as_posix())
    assert sorted(set(importers)) == ["server/cell_compiler.py"]


def test_item_geometry_comes_from_the_validated_recipe():
    # C4b 1c P3: grasp depth is read from the palletizing Recipe (its one explicit default), not
    # re-defaulted by Fleet.
    recipe_doc, _ = _documents()
    adapter = PalletizingCellJobCompiler(tol_m=TOL_M)
    assert adapter.item_geometry(recipe_doc) == {
        "box": {"grasp_depth_m": 0.015, "height_m": 0.03},
        "slip_sheet": {"grasp_depth_m": 0.0, "height_m": 0.002},
    }
    no_depth = {**recipe_doc, "box": {key: value for key, value in recipe_doc["box"].items()
                                      if key != "grasp_depth"}}
    assert adapter.item_geometry(no_depth)["box"]["grasp_depth_m"] == load_recipe(
        __import__("json").dumps(no_depth)).box.grasp_depth
    with pytest.raises(ValueError):
        adapter.item_geometry({**recipe_doc, "box": "x"})


def test_goal_predicates_need_explicit_geometry():
    from fleet.server.cell_goal_evidence import attach_goal_predicates
    with pytest.raises(KeyError):
        attach_goal_predicates({"steps": [{"inputs": {"item": "box"}}]}, {"box": {"height_m": 0.03}}, None)
