"""C4b G2a: the owner's accepted cell/recipe store backs the cell-hash and item-geometry checks."""

from __future__ import annotations

import hashlib
import json

import pytest

from core_common.protocol.schemas import FleetActionGrant, FleetCellTransferGrant
from omx_adapter.action_api import ActionApi
from omx_adapter.cell_acceptance import (
    CellAcceptanceRefused, CellAcceptanceStore, ValidatedCell, ValidatedRecipe, canonical_sha256,
)

from test_omx_action_api import FakePhaseExecution, _cell_transfer_grant, _grant, _runner

KINEMATICS = "k" * 64
CELL = {"schema": "rosy_cell.cell/2", "kinematics_revision": KINEMATICS, "home": {"x": 0.1}}
RECIPE = {"schema": "rosy_cell.recipe/1", "name": "demo", "box": {"width": 0.03}}
BOX = {"grasp_width_m": 0.03, "grasp_depth_m": 0.015, "height_m": 0.03}


def _sha(document):
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Validator:
    """Stands in for the composition's palletizing validator; records what it was shown."""

    def __init__(self, *, cell_hash=None, recipe_hash=None, items=None, fail=False):
        self.cell_hash, self.recipe_hash = cell_hash, recipe_hash
        self.items = {"box": BOX} if items is None else items
        self.fail = fail
        self.calls = []

    def validate_cell(self, cell):
        self.calls.append(("cell", cell))
        if self.fail:
            raise ValueError("cell is invalid")
        return ValidatedCell(sha256=self.cell_hash or _sha(cell),
                             kinematics_revision=cell["kinematics_revision"])

    def validate_recipe(self, recipe, cell):
        self.calls.append(("recipe", recipe, cell))
        if self.fail:
            raise ValueError("recipe does not compile against the cell")
        return ValidatedRecipe(sha256=self.recipe_hash or _sha(recipe), items=self.items)


def _store(tmp_path, validator=None, unresolved=()):
    tmp_path.mkdir(parents=True, exist_ok=True)
    return CellAcceptanceStore(
        tmp_path / "actions.sqlite3", workcell_id="omx-1", instance_id="omx-1-control",
        kinematics_revision=KINEMATICS, config_revision="cfg-1",
        validator=validator or Validator(), unresolved_actions=lambda: list(unresolved),
    )


def _accepted(tmp_path, **kwargs):
    store = _store(tmp_path, **kwargs)
    store.accept_cell(CELL, actor_id="operator-1")
    store.accept_recipe(RECIPE, actor_id="operator-1")
    return store


def _cell_grant(cell=CELL, recipe=RECIPE, **transfer):
    payload = {**_cell_transfer_grant()["cell_transfer"], "cell_sha256": _sha(cell),
               "recipe_sha256": _sha(recipe), **transfer}
    return FleetCellTransferGrant.model_validate(_cell_transfer_grant(cell_transfer=payload))


def test_canonical_hash_is_the_palletizing_content_hash_form():
    assert canonical_sha256(CELL) == _sha(CELL)


def test_accepting_stores_text_and_hashes_and_survives_restart(tmp_path):
    store = _accepted(tmp_path)
    reopened = _store(tmp_path)
    current = reopened.current()
    assert current["cell_sha256"] == _sha(CELL)
    assert current["cell"] == CELL
    assert current["recipes"] == {_sha(RECIPE): RECIPE}
    assert reopened.accepted_cell_sha256() == _sha(CELL) == store.accepted_cell_sha256()
    assert reopened.accepted_item_geometry(_sha(RECIPE), "box") == BOX


def test_validator_runs_on_every_acceptance_and_recipe_is_checked_against_the_cell(tmp_path):
    validator = Validator()
    _accepted(tmp_path, validator=validator)
    assert validator.calls == [("cell", CELL), ("recipe", RECIPE, CELL)]


def test_store_recomputes_the_hash_and_refuses_a_validator_disagreement(tmp_path):
    store = _store(tmp_path, validator=Validator(cell_hash="0" * 64))
    with pytest.raises(CellAcceptanceRefused, match="hash"):
        store.accept_cell(CELL, actor_id="operator-1")
    assert store.accepted_cell_sha256() is None


def test_invalid_document_or_other_kinematics_is_refused(tmp_path):
    with pytest.raises(CellAcceptanceRefused, match="invalid"):
        _store(tmp_path / "a", validator=Validator(fail=True)).accept_cell(CELL, actor_id="op")
    other = {**CELL, "kinematics_revision": "q" * 64}
    store = _store(tmp_path)
    with pytest.raises(CellAcceptanceRefused, match="kinematics"):
        store.accept_cell(other, actor_id="op")
    assert store.accepted_cell_sha256() is None


def test_recipe_needs_an_accepted_cell_and_complete_positive_geometry(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(CellAcceptanceRefused, match="cell"):
        store.accept_recipe(RECIPE, actor_id="op")
    store.accept_cell(CELL, actor_id="op")
    bad = _store(tmp_path, validator=Validator(items={"box": {**BOX, "grasp_width_m": -0.03}}))
    with pytest.raises(CellAcceptanceRefused, match="geometry"):
        bad.accept_recipe(RECIPE, actor_id="op")


def test_replacement_is_refused_while_an_action_is_unresolved(tmp_path):
    _accepted(tmp_path)
    busy = _store(tmp_path, unresolved=[{"action_id": "a-1"}])
    replacement = {**CELL, "home": {"x": 0.2}}
    with pytest.raises(CellAcceptanceRefused, match="unresolved"):
        busy.accept_cell(replacement, actor_id="op")
    assert busy.accepted_cell_sha256() == _sha(CELL)


def test_unknown_hashes_and_items_have_no_geometry(tmp_path):
    store = _accepted(tmp_path)
    assert store.accepted_item_geometry("f" * 64, "box") is None
    assert store.accepted_item_geometry(_sha(RECIPE), "slip_sheet") is None


def test_capability_requires_the_accepted_cell_recipe_item_and_config(tmp_path):
    store = _accepted(tmp_path)
    assert store.capability_current(_cell_grant()) is True
    assert store.capability_current(_cell_grant(cell={**CELL, "x": 1})) is False
    assert store.capability_current(_cell_grant(recipe={**RECIPE, "x": 1})) is False
    assert store.capability_current(_cell_grant(item="slip_sheet")) is False
    other_config = _cell_grant().model_copy(update={"config_revision": "cfg-2"})
    assert store.capability_current(other_config) is False
    assert store.capability_current(FleetActionGrant.model_validate(_grant())) is False


def test_cell_replacement_makes_the_old_hash_and_its_recipes_stale(tmp_path):
    store = _accepted(tmp_path)
    old = _cell_grant()
    replacement = {**CELL, "home": {"x": 0.2}}
    store.accept_cell(replacement, actor_id="op")

    assert store.capability_current(old) is False
    assert store.accepted_item_geometry(_sha(RECIPE), "box") is None
    # The recipe must be accepted again against the new cell before the new hash is admitted.
    assert store.capability_current(_cell_grant(cell=replacement)) is False
    store.accept_recipe(RECIPE, actor_id="op")
    assert store.capability_current(_cell_grant(cell=replacement)) is True


def test_owner_rejects_an_unknown_or_stale_cell_hash_before_journaling(tmp_path):
    store = _accepted(tmp_path / "acceptance")
    journal, driver, runner = _runner(
        tmp_path,
        phase_runner_factories={"CELL_TRANSFER": lambda grant, recorder: FakePhaseExecution(recorder)},
        capability_current=store.capability_current,
    )
    api = ActionApi(runner)

    def submit(grant):
        return api.dispatch({"version": 2, "operation": "SubmitAction",
                             "grant": grant.model_dump(mode="json")}, peer_uid=1001)

    unknown = submit(_cell_grant(cell={**CELL, "forged": True}))
    assert (unknown["status"], unknown["error"]["code"]) == (403, "GRANT_REJECTED")
    assert journal.get_action("cell-action-1") is None

    current = _cell_grant()
    store.accept_cell({**CELL, "home": {"x": 0.2}}, actor_id="op")
    stale = submit(current)
    assert (stale["status"], stale["error"]["code"]) == (403, "GRANT_REJECTED")
    assert journal.get_action("cell-action-1") is None and driver.submissions == []


def test_a_validator_is_required(tmp_path):
    with pytest.raises(ValueError, match="validator"):
        CellAcceptanceStore(tmp_path / "a.sqlite3", workcell_id="omx-1", instance_id="omx-1-control",
                            kinematics_revision=KINEMATICS, config_revision="cfg-1",
                            validator=None, unresolved_actions=list)
