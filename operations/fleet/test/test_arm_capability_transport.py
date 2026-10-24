"""Strict capability reads and canonical journal receipts never authorize replay."""
import json
from pathlib import Path

import pytest

from fleet.server.local_action_transport import LocalActionUnavailable, UnixLocalActionTransport
from test_arm_action_transport import grant
from test_cell_action_transport import _response


def facts():
    root = Path(__file__).resolve().parents[3]
    return json.loads((root / "contracts/foundation/test/fixtures/arm_transfer_capability_v1.json").read_text())


@pytest.mark.parametrize("fault", [None, "instance", "workcell", "mode", "version", "extra"])
def test_capability_read_is_single_exchange_and_validates_scope_and_closed_contract(tmp_path, fault):
    client, sent = UnixLocalActionTransport(tmp_path), []
    capability = facts()
    if fault in {"instance", "workcell"}:
        capability[f"{fault}_id"] = "other"
    elif fault == "mode":
        capability["control_mode"] = "manual"
    elif fault == "extra":
        capability["approved"] = True

    def exchange(instance, request):
        sent.append((instance, request))
        return {"version": 1 if fault == "version" else 2, "status": 200, "capability": capability}

    client._exchange = exchange
    read = getattr(client, "transfer_capability", None)
    assert read is not None, "Fleet capability read is missing"
    if fault:
        with pytest.raises(LocalActionUnavailable):
            read("arm-1", workcell_id="workcell-1")
    else:
        assert read("arm-1", workcell_id="workcell-1").model_dump() == facts()
    assert sent == [("arm-1", {"version": 2, "operation": "GetTransferCapability"})]


@pytest.mark.parametrize("journal", [None, "other-journal"])
def test_arm_receipt_requires_the_grants_canonical_journal(tmp_path, journal):
    body = grant().model_copy(update={"owner_journal_id": "journal-1", "owner_session_id": "session-1"})
    response = _response(body, phases=[])
    response["receipt"]["journal_id"] = journal
    client = UnixLocalActionTransport(tmp_path)
    client._exchange = lambda *_: response
    with pytest.raises(LocalActionUnavailable):
        client.get(body)


def test_arm_404_is_not_returned_as_verified_absence(tmp_path):
    body = grant().model_copy(update={"owner_journal_id": "journal-1", "owner_session_id": "session-1"})
    client = UnixLocalActionTransport(tmp_path)
    client._exchange = lambda *_: {"version": 2, "status": 404, "journal_id": "journal-1",
                                   "error": {"code": "ACTION_NOT_FOUND"}}
    with pytest.raises(LocalActionUnavailable):
        client.get(body)
