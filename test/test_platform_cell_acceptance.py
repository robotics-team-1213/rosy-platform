"""C4b G2a: the agent composition validates accepted cell/recipe text with the palletizing process."""

from pathlib import Path
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
for relative in ("contracts/skill/src", "apps/agent/src", "operations/processes/palletizing/src", "modules/execution/src",
                 "modules/skills/api/src", "src/products/omx/adapter"):
    path = str(ROOT / relative)
    if path not in sys.path:
        sys.path.insert(0, path)

from omx_adapter.cell_acceptance import CellAcceptanceRefused, CellAcceptanceStore  # noqa: E402
from rosy.processes.palletizing.cell import load_cell  # noqa: E402
from rosy.processes.palletizing.recipe import load_recipe  # noqa: E402
from rosy_agent.omx_cell_documents import PalletizingCellDocumentValidator  # noqa: E402

EXAMPLES = ROOT / "src/site/cell/examples/omx_sim"


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
