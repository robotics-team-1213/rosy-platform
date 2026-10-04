"""Manual sheet checkpoints retain canonical process authority without robot grants."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "operations/processes/palletizing/src"),
    str(ROOT / "operations/execution/src"),
    str(ROOT / "contracts/skill/src"),
    str(ROOT / "contracts/foundation"),
    str(ROOT / "operations/fleet"),
]

from fleet.server.cell_compiler import PalletizingCellJobCompiler  # noqa: E402
from rosy.execution.site.cell_submission import compile_cell_submission  # noqa: E402
from rosy.processes.palletizing.recipe import load_recipe, RecipeError  # noqa: E402


def documents(manual=True):
    folder = ROOT / "operations/processes/cell/examples/omx_sim"
    recipe = yaml.safe_load((folder / "recipe.yaml").read_text(encoding="utf-8"))
    cell = yaml.safe_load((folder / "cell.yaml").read_text(encoding="utf-8"))
    if manual:
        recipe["schema"] = "rosy_cell.recipe/2"
        recipe["slip_sheet"] = {"handling": "operator", "thickness": .002}
    return recipe, cell


def compile_documents(recipe, cell):
    compiler = PalletizingCellJobCompiler(tol_m=.001)
    return compiler, compiler.compile(recipe, cell)


def submission(recipe, cell, compiler, compiled):
    candidate = {"kind": "cell_job", "recipe": recipe, "cell": cell,
                 "recipe_sha256": compiled.plan_bundle.recipe_digest,
                 "cell_sha256": compiled.plan_bundle.cell_digest, "job": compiled.job}
    return compile_cell_submission(candidate, compiler=compiler, workcell_id="omx_cell_sim",
                                   instance_id="omx_cell_sim_01")


def test_recipe_one_job_bytes_hashes_and_empty_submission_keys_do_not_change():
    recipe, cell = documents(manual=False)
    compiler, compiled = compile_documents(recipe, cell)
    assert compiled.plan_bundle.recipe_digest == "8b620e598e4e3a90037e339383929fe6267fab0a6638053ef01b89679f9bfd0c"
    assert compiled.plan_bundle.cell_digest == "b994ee5214f590a10cac434085b8680f43a3c4ecf6e156a5625be793c9a986f3"
    encoded = json.dumps(compiled.job, sort_keys=True, separators=(",", ":")).encode()
    assert sha256(encoded).hexdigest() == "9fc1eb10f9252e5d304eee4d5e1bdec2094b9f13e62f638a4f0f779b62300aa4"
    assert len(compiled.plan_bundle.steps) == 18
    assert set(submission(recipe, cell, compiler, compiled).as_store_document()) == {
        "job_id", "workcell_id", "instance_id", "recipe_digest", "cell_digest",
        "process_artifact_digest", "job", "steps", "resources", "ledger_markers"}


def test_manual_sheet_job_has_two_bound_checkpoints_and_sixteen_box_skills():
    recipe, cell = documents()
    del cell["stations"]["sheets"]
    compiler, compiled = compile_documents(recipe, cell)
    assert len(compiled.plan_bundle.steps) == 16
    assert all(step.invocation.inputs["item"] == "box" for step in compiled.plan_bundle.steps)
    assert [(c["before_transfer_ordinal"], c["pallet_id"], c["layer_index"])
            for c in compiled.operator_checkpoints] == [(5, "A", 1), (13, "B", 1)]
    assert compiled.ledger_markers == ({"after_step_ordinal": 8, "pallet_id": "A"},
                                       {"after_step_ordinal": 16, "pallet_id": "B"})
    assert compiled.plan_bundle.steps[4].invocation.inputs["destination_pose_base"]["z_m"] == pytest.approx(.057)
    assert compiled.job["carry_z"] == pytest.approx(.117)
    checkpoints = [s for s in compiled.job["steps"] if s["kind"] == "operator_sheet"]
    assert len(checkpoints) == 2
    assert all(step["approach_z"] is None and step["thickness_m"] == .002 for step in checkpoints)
    persisted = submission(recipe, cell, compiler, compiled).as_store_document()
    assert persisted["operator_checkpoints"] == list(compiled.operator_checkpoints)
    assert len(persisted["steps"]) == 16


def test_unused_manual_sheet_station_does_not_raise_carry_height():
    recipe, cell = documents()
    cell["stations"]["sheets"]["z"] = 99.
    _, compiled = compile_documents(recipe, cell)
    assert compiled.job["carry_z"] == pytest.approx(.117)


def test_operator_sheet_thickness_changes_stack_but_not_held_item_hang():
    recipe, cell = documents()
    recipe["slip_sheet"]["thickness"] = .08
    for pallet in recipe["pallets"]:
        pallet["max_stack_height"] = .2
    _, compiled = compile_documents(recipe, cell)
    assert compiled.job["carry_z"] == pytest.approx(.195)


def test_first_layer_checkpoint_is_before_first_transfer():
    recipe, cell = documents()
    recipe["layers"][0]["slip_sheet_below"] = True
    _, compiled = compile_documents(recipe, cell)
    assert [row["before_transfer_ordinal"] for row in compiled.operator_checkpoints] == [1, 5, 9, 13]


@pytest.mark.parametrize("change", ["robot", "missing_handling", "station", "depalletize"])
def test_recipe_two_rejects_undefined_or_mixed_manual_semantics(change):
    recipe, _ = documents()
    if change == "robot":
        recipe["slip_sheet"]["handling"] = "robot"
    elif change == "missing_handling":
        recipe["slip_sheet"].pop("handling")
    elif change == "station":
        recipe["slip_sheet"]["station"] = "sheets"
    else:
        recipe["mode"] = "depalletize"
    with pytest.raises(RecipeError):
        load_recipe(json.dumps(recipe))


def test_checkpoint_ids_change_with_thickness_and_are_repeatable():
    recipe, cell = documents()
    _, first = compile_documents(recipe, cell)
    _, again = compile_documents(recipe, cell)
    assert first.operator_checkpoints == again.operator_checkpoints
    changed = deepcopy(recipe)
    changed["slip_sheet"]["thickness"] = .003
    _, second = compile_documents(changed, cell)
    assert {c["checkpoint_id"] for c in first.operator_checkpoints}.isdisjoint(
        {c["checkpoint_id"] for c in second.operator_checkpoints})


def test_submission_rejects_a_caller_stripped_checkpoint_job():
    recipe, cell = documents()
    compiler, compiled = compile_documents(recipe, cell)
    changed = deepcopy(dict(compiled.job))
    changed["steps"] = [step for step in changed["steps"] if step["kind"] != "operator_sheet"]
    with pytest.raises(ValueError, match="recompiled"):
        submission(recipe, cell, compiler, replace(compiled, job=changed))


def test_submission_rejects_trailing_checkpoint_and_wrong_metadata_binding():
    recipe, cell = documents()
    compiler, compiled = compile_documents(recipe, cell)
    for ordinal in (17, 6):
        changed = [dict(row) for row in compiled.operator_checkpoints]
        changed[0]["before_transfer_ordinal"] = ordinal
        wrapper = type("Compiler", (), {"compile": lambda self, *args:
                       replace(compiled, operator_checkpoints=tuple(changed))})()
        with pytest.raises(ValueError, match="checkpoint"):
            submission(recipe, cell, wrapper, compiled)


@pytest.mark.parametrize("field,value", [
    ("checkpoint_id", "a" * 64), ("pallet_id", "other"), ("layer_index", 9), ("thickness_m", .003)])
def test_submission_rejects_checkpoint_metadata_tampering(field, value):
    recipe, cell = documents()
    compiler, compiled = compile_documents(recipe, cell)
    changed = deepcopy(list(compiled.operator_checkpoints))
    changed[0][field] = value
    wrapper = type("Compiler", (), {"compile": lambda self, *args:
                   replace(compiled, operator_checkpoints=tuple(changed))})()
    with pytest.raises(ValueError, match="checkpoint"):
        submission(recipe, cell, wrapper, compiled)


def test_submission_rejects_missing_manual_metadata():
    recipe, cell = documents()
    compiler, compiled = compile_documents(recipe, cell)
    wrapper = type("Compiler", (), {"compile": lambda self, *args:
                   replace(compiled, operator_checkpoints=())})()
    with pytest.raises(ValueError, match="checkpoint"):
        submission(recipe, cell, wrapper, compiled)
