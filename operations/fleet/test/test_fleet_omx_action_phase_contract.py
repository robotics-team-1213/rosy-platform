from datetime import datetime, timezone

import pytest

from core_common.protocol.schemas import DeviceActionPhaseReceipt
from fleet.server.mission_dispatcher import MissionDispatcher
from fleet.server.mission_progress import MissionProgressService
from fleet.server.mission_store import MissionConflict

from test_mission_dispatcher import Transport, _ready_mission, _receipt


def _phase(phase_id="approach", ordinal=0, event_id=3, state="RUNNING"):
    return {
        "phase_id": phase_id, "ordinal": ordinal, "state": state,
        "journal_event_id": event_id,
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }


def test_phase_receipt_is_small_allowlisted_and_timestamped():
    receipt = DeviceActionPhaseReceipt.model_validate(_phase())

    assert receipt.phase_id == "approach"
    assert receipt.ordinal == 0
    assert receipt.state == "RUNNING"
    assert receipt.journal_event_id == 3


@pytest.mark.parametrize("mutation", [
    {"phase_id": "move-anywhere"},
    {"ordinal": -1},
    {"state": "PHYSICAL_STOPPED"},
    {"journal_event_id": 0},
    {"trajectory": [1, 2, 3]},
    {"observed_at": "2026-10-01T00:00:00"},
])
def test_phase_receipt_rejects_unbounded_or_authority_shaped_fields(mutation):
    with pytest.raises(ValueError):
        DeviceActionPhaseReceipt.model_validate({**_phase(), **mutation})


def test_fleet_phase_projection_is_idempotent_attempt_fenced_and_read_only(tmp_path):
    task_store, service, mission, _ = _ready_mission(tmp_path)
    transport = Transport()
    dispatcher = MissionDispatcher(
        service, task_store, transport, {"omx-1": "omx-1-control"},
    )
    dispatcher.dispatch_next()
    grant = transport.submissions[0]
    observed = datetime.now(timezone.utc).isoformat()
    phase = {
        "phase_id": "approach", "ordinal": 0, "state": "RUNNING",
        "journal_event_id": 3, "observed_at": observed,
    }
    receipt = _receipt(grant, "RUNNING", 7)
    receipt["phase_summaries"] = [phase]

    dispatcher._apply_receipt(grant, dispatcher._verified_receipt(grant, receipt))
    dispatcher._apply_receipt(grant, dispatcher._verified_receipt(grant, receipt))
    history = service.history(mission["mission_id"])
    phase_events = [event for event in history if event["event_type"] == "ACTION_PHASE_SNAPSHOT"]
    progress = MissionProgressService(service.store).snapshot(mission["mission_id"])

    assert len(phase_events) == 1
    assert progress["progress"]["active_phase"] == "approach"
    assert progress["progress"]["phases"][0]["state"] == "RUNNING"
    assert service.get(mission["mission_id"])["status"] == "RUNNING"


def test_fleet_ignores_out_of_order_phase_snapshot_without_regression(tmp_path):
    task_store, service, mission, _ = _ready_mission(tmp_path)
    transport = Transport()
    dispatcher = MissionDispatcher(
        service, task_store, transport, {"omx-1": "omx-1-control"},
    )
    dispatcher.dispatch_next()
    grant = transport.submissions[0]
    observed = datetime.now(timezone.utc).isoformat()
    for state, event_id in (("RUNNING", 9), ("ACCEPTED", 8)):
        receipt = _receipt(grant, "RUNNING", event_id)
        receipt["phase_summaries"] = [{
            "phase_id": "approach", "ordinal": 0, "state": state,
            "journal_event_id": event_id, "observed_at": observed,
        }]
        dispatcher._apply_receipt(grant, dispatcher._verified_receipt(grant, receipt))

    progress = MissionProgressService(service.store).snapshot(mission["mission_id"])
    assert progress["progress"]["phases"][0]["state"] == "RUNNING"


def test_reused_phase_event_identity_with_changed_state_is_a_conflict(tmp_path):
    task_store, service, mission, _ = _ready_mission(tmp_path)
    transport = Transport()
    dispatcher = MissionDispatcher(
        service, task_store, transport, {"omx-1": "omx-1-control"},
    )
    dispatcher.dispatch_next()
    grant = transport.submissions[0]
    observed = datetime.now(timezone.utc).isoformat()
    base = {
        "phase_id": "approach", "ordinal": 0, "journal_event_id": 10,
        "observed_at": observed,
    }
    service.store.record_action_phase_summaries(
        mission["mission_id"], action_id=grant.action_id, attempt_id=grant.attempt_id,
        authority_epoch=grant.authority_epoch,
        dispatch_generation=grant.dispatch_generation,
        phases=[{**base, "state": "RUNNING"}],
    )

    with pytest.raises(MissionConflict, match="reused"):
        service.store.record_action_phase_summaries(
            mission["mission_id"], action_id=grant.action_id, attempt_id=grant.attempt_id,
            authority_epoch=grant.authority_epoch,
            dispatch_generation=grant.dispatch_generation,
            phases=[{**base, "state": "ACCEPTED"}],
        )


def test_newer_phase_event_cannot_regress_state(tmp_path):
    task_store, service, mission, _ = _ready_mission(tmp_path)
    transport = Transport()
    dispatcher = MissionDispatcher(
        service, task_store, transport, {"omx-1": "omx-1-control"},
    )
    dispatcher.dispatch_next()
    grant = transport.submissions[0]
    observed = datetime.now(timezone.utc).isoformat()
    common = {
        "phase_id": "approach", "ordinal": 0, "observed_at": observed,
    }
    service.store.record_action_phase_summaries(
        mission["mission_id"], action_id=grant.action_id, attempt_id=grant.attempt_id,
        authority_epoch=grant.authority_epoch,
        dispatch_generation=grant.dispatch_generation,
        phases=[{**common, "journal_event_id": 10, "state": "RUNNING"}],
    )

    with pytest.raises(MissionConflict, match="regresses"):
        service.store.record_action_phase_summaries(
            mission["mission_id"], action_id=grant.action_id, attempt_id=grant.attempt_id,
            authority_epoch=grant.authority_epoch,
            dispatch_generation=grant.dispatch_generation,
            phases=[{**common, "journal_event_id": 11, "state": "ACCEPTED"}],
        )


def test_fleet_rejects_stale_attempt_phase_receipts(tmp_path):
    task_store, service, mission, _ = _ready_mission(tmp_path)
    transport = Transport()
    dispatcher = MissionDispatcher(
        service, task_store, transport, {"omx-1": "omx-1-control"},
    )
    dispatcher.dispatch_next()
    grant = transport.submissions[0]

    with pytest.raises(MissionConflict, match="active Mission attempt"):
        service.store.record_action_phase_summaries(
            mission["mission_id"], action_id=grant.action_id, attempt_id="stale-attempt",
            authority_epoch=grant.authority_epoch,
            dispatch_generation=grant.dispatch_generation, phases=[],
        )
