"""C4b G2a: the agent composition validates accepted cell/recipe text with the palletizing process."""

from pathlib import Path
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
for relative in ("contracts/skill/src", "middleware/devices/omx/agent/src", "operations/processes/palletizing/src", "operations/site_execution/src",
                 "middleware/skills/api/src", "middleware/devices/omx/adapter"):
    path = str(ROOT / relative)
    if path not in sys.path:
        sys.path.insert(0, path)

from core_common.protocol.cell_transfer import CellTransferPayload  # noqa: E402
from omx_adapter.cell_acceptance import (  # noqa: E402
    CellAcceptanceRefused, CellAcceptanceStore, ValidatedCell, canonical_sha256)
from rosy.processes.palletizing.cell import load_cell  # noqa: E402
from rosy.processes.palletizing.recipe import load_recipe  # noqa: E402
from rosy_agent.omx_cell_documents import PalletizingCellDocumentValidator  # noqa: E402

EXAMPLES = ROOT / "operations/processes/cell/examples/omx_sim"
MIXED = ROOT / "operations/processes/palletizing/test/fixtures/mixed_two_arm"


def _docs():
    return (yaml.safe_load((EXAMPLES / "recipe.yaml").read_text(encoding="utf-8")),
            yaml.safe_load((EXAMPLES / "cell.yaml").read_text(encoding="utf-8")))


def _store(tmp_path, kinematics):
    return CellAcceptanceStore(
        tmp_path / "owner.sqlite3", workcell_id="omx_sim", instance_id="omx_sim_01",
        kinematics_revision=kinematics, config_revision="cfg-1",
        validator=PalletizingCellDocumentValidator(tol_m=0.001), unresolved_actions=list)


def test_accepted_hashes_are_the_palletizing_content_hashes(tmp_path):
    recipe_doc, cell_doc = _docs()
    cell, recipe = load_cell((EXAMPLES / "cell.yaml").read_text(encoding="utf-8")), load_recipe(
        (EXAMPLES / "recipe.yaml").read_text(encoding="utf-8"))
    store = _store(tmp_path, cell.kinematics_revision)

    accepted_cell = store.accept_cell(cell_doc, actor_id="operator-1")
    accepted_recipe = store.accept_recipe(recipe_doc, actor_id="operator-1")

    assert accepted_cell["cell_sha256"] == cell.content_hash
    assert accepted_recipe["recipe_sha256"] == recipe.content_hash
    assert store.accepted_item_geometry(recipe.content_hash, "box") == {
        "grasp_width_m": 0.03, "grasp_depth_m": 0.015, "height_m": 0.03}
    # A slip sheet has no grasp the planner accepts; it gets no geometry.
    assert store.accepted_item_geometry(recipe.content_hash, "slip_sheet") is None


def test_palletizing_rejections_refuse_acceptance(tmp_path):
    recipe_doc, cell_doc = _docs()
    store = _store(tmp_path, cell_doc["kinematics_revision"])
    with pytest.raises(CellAcceptanceRefused, match="invalid"):
        store.accept_cell({**cell_doc, "schema": "rosy_cell.cell/1"}, actor_id="operator-1")
    store.accept_cell(cell_doc, actor_id="operator-1")
    unreachable = {**recipe_doc, "pick_station": "nowhere"}
    with pytest.raises(CellAcceptanceRefused, match="invalid for the accepted cell"):
        store.accept_recipe(unreachable, actor_id="operator-1")


# D-781 §2: a recipe/3 accepted geometry holds one entry per sku, keyed like the grant's item_key.
def _mixed_docs():
    return (yaml.safe_load((MIXED / "recipe.yaml").read_text(encoding="utf-8")),
            yaml.safe_load((MIXED / "cell.yaml").read_text(encoding="utf-8")))


SKUS = {"box:foam_40x30x30": {"grasp_width_m": 0.03, "grasp_depth_m": 0.015, "height_m": 0.03},
        "box:foam_30x20x20": {"grasp_width_m": 0.02, "grasp_depth_m": 0.01, "height_m": 0.02}}


def test_a_recipe3_validates_against_a_cell3_with_one_geometry_per_sku():
    recipe_doc, cell_doc = _mixed_docs()
    validated = PalletizingCellDocumentValidator(tol_m=0.001).validate_recipe(recipe_doc, cell_doc)
    assert validated.sha256 == canonical_sha256(recipe_doc)
    assert dict(validated.items) == SKUS


def test_a_recipe3_is_refused_against_a_single_arm_cell(tmp_path):
    recipe_doc, cell_doc = _docs()
    store = _store(tmp_path, cell_doc["kinematics_revision"])
    store.accept_cell(cell_doc, actor_id="operator-1")
    with pytest.raises(CellAcceptanceRefused, match="invalid for the accepted cell"):
        store.accept_recipe(_mixed_docs()[0], actor_id="operator-1")


class _Cell3Validator(PalletizingCellDocumentValidator):
    """Stand-in: this owner does not accept a cell/3 yet (open item); the recipe rules are real."""

    def validate_cell(self, cell):
        return ValidatedCell(sha256=canonical_sha256(cell), kinematics_revision="omx-test")


def test_capability_matches_a_grant_by_its_sku(tmp_path):
    from types import SimpleNamespace

    recipe_doc, cell_doc = _mixed_docs()
    store = CellAcceptanceStore(
        tmp_path / "owner.sqlite3", workcell_id="omx_01", instance_id="omx_01_control",
        kinematics_revision="omx-test", config_revision="cfg-1",
        validator=_Cell3Validator(tol_m=0.001), unresolved_actions=list)
    store.accept_cell(cell_doc, actor_id="operator-1")
    recipe = store.accept_recipe(recipe_doc, actor_id="operator-1")["recipe_sha256"]
    for key, geometry in SKUS.items():
        assert store.accepted_item_geometry(recipe, key) == geometry
    assert store.accepted_item_geometry(recipe, "box") is None  # a recipe/3 grant always names its sku

    def grant(**changes):
        transfer = CellTransferPayload.model_validate({
            "job_id": "job-1", "recipe_sha256": recipe, "cell_sha256": canonical_sha256(cell_doc),
            "step_index": 0, "item": "box", "pallet": "A", "layer": 0, "frame": "robot_base",
            "home": {"x": 0.12, "y": 0.0, "z": 0.12, "yaw": 0.0}, "pick": {"x": 0.1, "y": 0.1, "z": 0.0, "yaw": 0.0},
            "place": {"x": 0.15, "y": 0.0, "z": 0.0, "yaw": 0.0}, "pick_approach_z": 0.05,
            "place_approach_z": 0.05, "carry_z": 0.08, **changes})
        return SimpleNamespace(action_kind="CELL_TRANSFER", config_revision="cfg-1", cell_transfer=transfer)

    assert store.capability_current(grant(sku="foam_30x20x20")) is True
    assert store.capability_current(grant(sku="foam_99")) is False
    assert store.capability_current(grant()) is False
