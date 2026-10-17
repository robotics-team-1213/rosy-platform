"""D-781 §2: the optional recipe/3 ``sku`` on the CELL_TRANSFER body and the owner geometry key."""

import pytest
from pydantic import ValidationError

from core_common.protocol.cell_transfer import item_geometry_key
from core_common.protocol.schemas import CellTransferPayload, FleetCellTransferGrant

from test_cell_transfer_pair_contract import _digest, _grant


def _with_transfer(**changes):
    raw = _grant()
    raw["cell_transfer"] = {**raw["cell_transfer"], **changes}
    return raw


def test_a_grant_without_sku_is_unchanged_and_keys_by_item():
    grant = FleetCellTransferGrant.model_validate(_grant())
    dumped = grant.model_dump(mode="json")
    assert "sku" not in dumped["cell_transfer"]
    assert grant.cell_transfer.sku is None and grant.cell_transfer.item_key == "box"


def test_a_sku_roundtrips_is_in_the_digest_and_keys_the_geometry():
    plain = FleetCellTransferGrant.model_validate(_grant()).model_dump(mode="json")
    grant = FleetCellTransferGrant.model_validate(_with_transfer(sku="foam_40x30x30"))
    dumped = grant.model_dump(mode="json")
    assert dumped["cell_transfer"]["sku"] == "foam_40x30x30"
    assert FleetCellTransferGrant.model_validate(dumped) == grant
    assert _digest(dumped) != _digest(plain)
    assert grant.cell_transfer.item_key == "box:foam_40x30x30" == item_geometry_key("box", "foam_40x30x30")
    assert item_geometry_key("slip_sheet") == "slip_sheet"


@pytest.mark.parametrize("changes", [
    {"sku": ""},
    {"sku": " foam"},
    {"sku": "foam 40"},
    {"sku": "x" * 97},
    {"sku": 7},
    {"item": "slip_sheet", "sku": "foam_40x30x30"},  # only a box step names a sku
])
def test_an_invalid_sku_is_refused(changes):
    with pytest.raises(ValidationError):
        CellTransferPayload.model_validate(_with_transfer(**changes)["cell_transfer"])
