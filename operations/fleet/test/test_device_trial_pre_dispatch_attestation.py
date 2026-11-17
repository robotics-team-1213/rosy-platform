"""D-977 5 (2026-11-17): in device_trial, PRE_DISPATCH needs a live single-use operator SOURCE_CLEAR; other profiles do not."""
from types import SimpleNamespace

import pytest

from fleet.server.mission_store import MissionConflict
from fleet.server.physical_transfer_attestations import OPERATOR_ATTESTED_PRODUCER_ID, PhysicalOperatorAttestations
from test_arm_transfer_job_api import PATH
from test_device_trial_arm_transfer import build
from test_physical_transfer_store import installation  # noqa: F401
from test_physical_transfer_observer_api import CONTEXT, OBSERVER, approved, measured, rig  # noqa: F401


@pytest.fixture
def gated(rig):  # the simulation rig with device_trial's attestation gate switched on
    attestations = PhysicalOperatorAttestations(rig.store)
    rig.app.state.arm_transfer_delegate.observation.attestations = attestations
    rig.attestations = attestations
    return rig


def clear(rig, mission, who="op-b"):
    job = rig.store.peek(mission)
    body = SimpleNamespace(kind="SOURCE_CLEAR", expected_request_digest=job["request_digest"],
                           expected_proposal_digest=job["proposal_digest"])
    return rig.attestations.record(mission, SimpleNamespace(principal_id=who), body)


def post(rig, mission, request):
    return rig.client.post(f"{PATH}/{mission}/observations", headers=OBSERVER, json=request)


def test_without_attestation_nothing_is_shown_or_dispatched(gated):
    mission = approved(gated)
    assert gated.client.get(CONTEXT, headers=OBSERVER).json() == {"context": None}
    clear(gated, mission)
    context = gated.client.get(CONTEXT, headers=OBSERVER).json()["context"]
    request = measured(gated, context, phase="PRE_DISPATCH")
    gated.attestations.store._clock_ns = lambda: gated.clock[0] + 60_000_000_000  # expired
    assert post(gated, mission, request).status_code == 409
    assert gated.port.submitted == []


def test_valid_attestation_dispatches_once_and_is_consumed(gated):
    mission = approved(gated)
    clear(gated, mission)
    context = gated.client.get(CONTEXT, headers=OBSERVER).json()["context"]
    request = measured(gated, context, phase="PRE_DISPATCH")
    assert post(gated, mission, request).status_code == 200
    assert len(gated.port.submitted) == 1
    assert not gated.attestations.source_clear_valid(mission)
    with pytest.raises(MissionConflict):
        gated.attestations.consume_source_clear(mission)
    assert post(gated, mission, request).status_code == 200  # replay is idempotent, never a second dispatch
    assert len(gated.port.submitted) == 1


def test_failed_dispatch_keeps_the_attestation_until_it_expires(gated):
    mission = approved(gated)
    clear(gated, mission)
    context = gated.client.get(CONTEXT, headers=OBSERVER).json()["context"]
    request = measured(gated, context, phase="PRE_DISPATCH")
    request["expected_request_digest"] = "0" * 64
    assert post(gated, mission, request).status_code == 409
    assert gated.attestations.source_clear_valid(mission)


def test_simulation_without_attestations_is_unchanged(rig):
    mission = approved(rig)
    context = rig.client.get(CONTEXT, headers=OBSERVER).json()["context"]
    assert post(rig, mission, measured(rig, context, phase="PRE_DISPATCH")).status_code == 200
    assert len(rig.port.submitted) == 1


def test_device_trial_observer_must_use_the_operator_attested_producer_id(tmp_path, installation, monkeypatch):
    monkeypatch.setattr("fleet.server.physical_transfer_attestations.OPERATOR_ATTESTED_PRODUCER_ID", "other-producer")
    with pytest.raises(ValueError, match="operator-attested producer id"):
        build(tmp_path, installation)
    assert OPERATOR_ATTESTED_PRODUCER_ID == "operator-attested-producer"
