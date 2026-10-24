"""recipe/3 compiles through the mixed planner into a multi-arm Cell Job (D-781 §5, D-779 stages 2-4)."""

import copy
import hashlib
import json
from pathlib import Path
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
for relative in ("contracts/skill/src", "operations/site_execution/src", "middleware/skills/api/src",
                 "operations/processes/palletizing/src"):
    path = str(ROOT / relative)
    if path not in sys.path:
        sys.path.insert(0, path)

from fleet.server.cell_compiler import PalletizingCellJobCompiler  # noqa: E402
from fleet.server.cell_goal_evidence import make_cell_job_resolver  # noqa: E402
from fleet.server.cell_job_store import CellJobStore  # noqa: E402
from fleet.server.cell_mixed_submission import compile_mixed_submission, is_mixed  # noqa: E402
from rosy.processes.palletizing.submission import compile_cell_submission  # noqa: E402
from rosy.processes.palletizing.cell import load_cell  # noqa: E402
from rosy.processes.palletizing.compiler import compile_job, job_document  # noqa: E402
from rosy.processes.palletizing.mixed_planner import PLANNER_VERSION  # noqa: E402
from rosy.processes.palletizing.recipe import load_recipe  # noqa: E402

from core_common.protocol.schemas import CellTransferPayload  # noqa: E402
from fleet.server.step_action_kinds import step_action_kind  # noqa: E402
from rosy.execution.site.item_pose import centre_above_tcp_m, step_goal_predicate  # noqa: E402

from test_cell_goal_evidence_service import _tolerance  # noqa: E402
from test_cell_job_store import _stores  # noqa: E402

MIXED = ROOT / "operations/processes/palletizing/test/fixtures/mixed_two_arm"
# Immutable inputs from the original recipe/1 golden at 26a148117.
SINGLE = ROOT / "test/fixtures/recipe1_pre_g2"
TOL_M = 0.001
CELL = "bench_01"


def _yaml(folder, name):
    return yaml.safe_load((folder / name).read_text(encoding="utf-8"))


def mixed_candidate(adapter):
    recipe, cell = _yaml(MIXED, "recipe.yaml"), _yaml(MIXED, "cell.yaml")
    compiled = adapter.compile_mixed(recipe, cell)
    return {"kind": "cell_job", "recipe": recipe, "cell": cell, "recipe_sha256": compiled.recipe_digest,
            "cell_sha256": compiled.cell_digest, "job": copy.deepcopy(compiled.job)}


@pytest.fixture(scope="module")
def adapter():
    return PalletizingCellJobCompiler(tol_m=TOL_M)


def test_recipe3_submission_is_accepted_into_the_ledger(tmp_path, adapter):
    candidate = mixed_candidate(adapter)
    assert is_mixed(candidate)
    submission = make_cell_job_resolver(adapter, None)(candidate, workcell_id=CELL, instance_id="omx_02_control")
    assert submission["arms"] == [{"instance_id": "omx_01_control", "role": "left", "workcell_id": "omx_01"},
                                  {"instance_id": "omx_02_control", "role": "right", "workcell_id": "omx_02"}]
    assert submission["resources"] == [["workcell", CELL], ["workcell", "omx_01"], ["workcell", "omx_02"],
                                       ["pallet", "A"]]
    assert submission["process_artifact_digest"] == adapter.process_artifact_digest
    assert submission["job"]["planner_version"] == PLANNER_VERSION
    identity = {"recipe_sha256": submission["recipe_digest"], "cell_sha256": submission["cell_digest"],
                "job": submission["job"]}
    assert submission["job_id"] == hashlib.sha256(json.dumps(
        identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()

    path, _, _, _ = _stores(tmp_path)
    job = CellJobStore(path).create(mission_id="mixed-1", proposal_principal_id="cell-service",
                                    request_key="rk-mixed-1", request_digest="d" * 64, submission=submission)
    assert job["status"] == "PROPOSED" and job["job_id"] == submission["job_id"]
    assert [(arm["arm_role"], arm["instance_id"], arm["owner_workcell"]) for arm in job["arms"]] == [
        ("left", "omx_01_control", "omx_01"), ("right", "omx_02_control", "omx_02")]
    placements = job["placements"]
    assert len(placements) == len(submission["steps"]) == 12
    for placement, step in zip(placements, submission["steps"]):
        wanted = step["placement"]
        assert placement["assigned"] == [wanted["arm"]] and placement["alternates"] == wanted["alternates"]
        assert placement["zone_id"] == wanted["zone"] and placement["depends_on"] == wanted["depends_on"]
        assert placement["payloads"] == wanted["actions"]
    assert any(p["alternates"] for p in placements) and {p["assigned"][0] for p in placements} == {"left", "right"}
    # the stored single-arm step shape carries the primary arm's inputs
    assert job["steps"][0]["step"]["inputs"] == submission["steps"][0]["placement"]["actions"][
        submission["steps"][0]["placement"]["arm"]]


def test_recipe3_steps_carry_their_sku_on_the_wire(adapter):
    """D-781 §2: every arm's inputs name the step's sku; the CELL_TRANSFER body carries it."""
    submission = compile_mixed_submission(mixed_candidate(adapter), compiler=adapter, workcell_id=CELL,
                                          instance_id="omx_01_control")
    plan = submission["job"]["plan"]["steps"]
    job = {"job_id": submission["job_id"], "recipe_digest": submission["recipe_digest"],
           "cell_digest": submission["cell_digest"]}
    assert {step["sku"] for step in plan} == {"foam_40x30x30", "foam_30x20x20"}
    for index, step in enumerate(submission["steps"]):
        for inputs in step["placement"]["actions"].values():
            payload = CellTransferPayload.model_validate(step_action_kind("CELL_TRANSFER").body(job, index, inputs))
            assert (payload.item, payload.sku) == ("box", plan[index]["sku"])
            assert payload.item_key == "box:" + plan[index]["sku"]


def test_the_resolver_fixes_one_predicate_per_arm_in_that_arms_frame(tmp_path, adapter):
    """D-781 §5: a predicate for the primary and every alternate arm, each from its own inputs."""
    tolerance = _tolerance()
    submission = make_cell_job_resolver(adapter, tolerance)(mixed_candidate(adapter), workcell_id=CELL,
                                                            instance_id="omx_01_control")
    geometry = adapter.item_geometry(_yaml(MIXED, "recipe.yaml"))
    assert geometry == {"foam_40x30x30": {"grasp_depth_m": 0.015, "height_m": 0.03},
                        "foam_30x20x20": {"grasp_depth_m": 0.01, "height_m": 0.02}}
    shared = 0
    for step in submission["steps"]:
        actions = step["placement"]["actions"]
        assert "goal_predicate" not in step and set(step["goal_predicates"]) == set(actions)
        for role, inputs in actions.items():
            offset = centre_above_tcp_m(**geometry[inputs["sku"]])
            assert step["goal_predicates"][role] == step_goal_predicate(inputs, tolerance, offset)
        if step["placement"]["alternates"]:
            shared += 1
            targets = [predicate["target"] for predicate in step["goal_predicates"].values()]
            assert targets[0] != targets[1]  # the same cell pose seen from two bases
    assert shared
    path, _, _, _ = _stores(tmp_path)
    job = CellJobStore(path).create(mission_id="mixed-1", proposal_principal_id="cell-service",
                                    request_key="rk-mixed-1", request_digest="d" * 64, submission=submission)
    assert [step["step"]["goal_predicates"] for step in job["steps"]] == [
        step["goal_predicates"] for step in submission["steps"]]


def test_same_documents_give_the_same_job_id(adapter):
    first = compile_mixed_submission(mixed_candidate(adapter), compiler=adapter, workcell_id=CELL,
                                     instance_id="omx_01_control")
    second = compile_mixed_submission(mixed_candidate(PalletizingCellJobCompiler(tol_m=TOL_M)), compiler=adapter,
                                      workcell_id=CELL, instance_id="omx_01_control")
    assert first == second


@pytest.mark.parametrize("change, message", [
    (lambda c: c["job"]["plan"]["steps"][0]["pose_cell"].update(x=0.5), "differs from the recompiled Job"),
    (lambda c: c["job"].update(planner_version="other/1"), "differs from the recompiled Job"),
    (lambda c: c.update(cell_sha256="0" * 64), "digest differs"),
    (lambda c: c.update(recipe_sha256="A" * 64), "lowercase SHA-256"),
    (lambda c: c.update(extra=1), "invalid envelope"),
    (lambda c: c["cell"]["arms"][0]["base_in_cell"].pop("calibration_revision"), "calibration_revision"),
])
def test_a_tampered_candidate_is_refused(adapter, change, message):
    candidate = mixed_candidate(adapter)
    change(candidate)
    with pytest.raises(ValueError, match=message):
        compile_mixed_submission(candidate, compiler=adapter, workcell_id=CELL, instance_id="omx_01_control")


def test_the_proposal_instance_must_be_one_of_the_cell_arms(adapter):
    with pytest.raises(ValueError, match="arm instances"):
        compile_mixed_submission(mixed_candidate(adapter), compiler=adapter, workcell_id=CELL,
                                 instance_id="omx_09_control")


def test_a_one_arm_cell_is_refused_before_the_ledger(adapter):
    candidate = mixed_candidate(adapter)
    cell = candidate["cell"]
    cell["arms"] = cell["arms"][:1]
    cell["zones"] = [zone for zone in cell["zones"] if zone["zone_id"] == "left_half"]
    cell["zones"][0].update(x_max=0.5)
    cell["reach"]["r_max_m"] = 0.40
    candidate["job"] = adapter.compile_mixed(candidate["recipe"], cell).job
    candidate["cell_sha256"] = adapter.compile_mixed(candidate["recipe"], cell).cell_digest
    with pytest.raises(ValueError, match="two or more arms"):
        compile_mixed_submission(candidate, compiler=adapter, workcell_id=CELL, instance_id="omx_01_control")


def test_recipe1_path_is_unchanged(adapter):
    recipe_doc, cell_doc = _yaml(SINGLE, "recipe.yaml"), _yaml(SINGLE, "cell.yaml")
    recipe, cell = load_recipe(json.dumps(recipe_doc)), load_cell(json.dumps(cell_doc))
    candidate = {"kind": "cell_job", "recipe": recipe_doc, "cell": cell_doc, "recipe_sha256": recipe.content_hash,
                 "cell_sha256": cell.content_hash, "job": job_document(compile_job(recipe, cell, tol_m=TOL_M))}
    assert not is_mixed(candidate)
    document = make_cell_job_resolver(adapter, None)(candidate, workcell_id="omx_sim", instance_id="omx_sim_01")
    assert document == compile_cell_submission(candidate, compiler=adapter, workcell_id="omx_sim",
                                               instance_id="omx_sim_01").as_store_document()
    # Pinned at 26a148117 (before recipe/3 compile existed). process_artifact_digest is left out: it
    # hashes the palletizing sources, so any source change moves it by design.
    document.pop("process_artifact_digest")
    assert document["job_id"] == "6f7a7870b04a91fc328e1d22df67b5ef" "ef2a0913986e10d0a5e329b565c0569d"
    assert hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest() == (
        "8491fe31d5004ef2d67c69b3606f8cbf" "2a50c37cac27382355efce55132c6179")
