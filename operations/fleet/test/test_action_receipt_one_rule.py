"""Every Fleet path checks a device receipt against its grant with one rule (D-773 A2)."""

from datetime import datetime, timezone

import pytest

from core_common.protocol.schemas import DeviceActionReceipt
from fleet.server.action_receipts import RECEIPT_IDENTITY, receipt_matches_grant, verify_phase_receipt
from fleet.server.local_action_transport import LocalActionUnavailable, UnixLocalActionTransport
from fleet.server.step_dispatcher import StepJobDispatcher

from test_cell_action_transport import _grant, _response

PHASES = ("approach", "grasp", "transfer", "release")


def _phases(state="SUCCEEDED"):
    now = datetime.now(timezone.utc).isoformat()
    return [{"phase_id": name, "ordinal": index, "state": state, "journal_event_id": 1, "observed_at": now}
            for index, name in enumerate(PHASES)]


def _receipt(grant, *, state="SUCCEEDED", phases=None, **changes):
    document = _response(grant, phases=_phases() if phases is None else phases)["receipt"]
    return DeviceActionReceipt.model_validate({**document, "state": state, **changes})


def _changed(value):
    return value + 1 if isinstance(value, int) else value + "-other"


def test_identity_is_every_echoed_grant_field():
    grant = _grant()
    assert set(RECEIPT_IDENTITY) <= set(type(grant).model_fields) & set(DeviceActionReceipt.model_fields)


@pytest.mark.parametrize("field", RECEIPT_IDENTITY)
def test_every_path_refuses_a_receipt_that_differs_in_one_identity_field(tmp_path, field):
    grant = _grant()
    wrong = _receipt(grant, **{field: _changed(getattr(grant, field))})
    assert not receipt_matches_grant(grant, wrong)
    with pytest.raises(ValueError, match="does not match"):
        verify_phase_receipt(grant, wrong)
    with pytest.raises(ValueError, match="does not match"):
        StepJobDispatcher._verified(grant, wrong)
    client = UnixLocalActionTransport(tmp_path)
    client._exchange = lambda instance_id, request: {
        "version": 2, "status": 200, "receipt": wrong.model_dump(mode="json")}
    with pytest.raises(LocalActionUnavailable, match="does not match"):
        client.get(grant)


def test_named_phases_and_ordinals_accept_the_same_full_success():
    grant = _grant()
    receipt = _receipt(grant)
    assert verify_phase_receipt(grant, receipt) == receipt
    assert verify_phase_receipt(grant, {"receipt": receipt}, phase_ids=PHASES) == receipt
    assert StepJobDispatcher._verified(grant, receipt) == receipt


@pytest.mark.parametrize("phase_ids", [None, PHASES])
def test_a_success_with_a_missing_or_failed_phase_is_refused(phase_ids):
    grant = _grant()
    short = _receipt(grant, phases=_phases()[:3])
    failed = _receipt(grant, phases=[*_phases()[:3], {**_phases("FAILED")[3]}])
    for receipt in (short, failed):
        with pytest.raises(ValueError, match="every phase to succeed"):
            verify_phase_receipt(grant, receipt, phase_ids=phase_ids)


def test_a_receipt_without_phase_summaries_is_refused():
    grant = _grant()
    with pytest.raises(ValueError, match="missing phase summaries"):
        verify_phase_receipt(grant, _receipt(grant, state="RUNNING", phase_summaries=None))
