"""Approved Cell Jobs submit once and reconcile their persisted transfer attempt."""

from datetime import datetime, timedelta, timezone

import json
import asyncio

import pytest

from fleet.server.cell_job_dispatcher import CellJobDispatcher
from fleet.server.cell_job_store import CellJobStore
from fleet.server.mission_store import MissionConflict
from test_cell_job_store import _create, _goal, _stores


class Transport:
    def __init__(self, store, tasks, *, lose_submit=False):
        self.store, self.tasks = store, tasks
        self.lose_submit = lose_submit
        self.submissions, self.lookups, self.cancellations = [], [], []
        self.receipt = None

    def set_receipt(self, grant, state, event_id):
        phases = []
        if state == "SUCCEEDED":
            phases = [{"phase_id": phase, "ordinal": ordinal, "state": "SUCCEEDED",
                       "journal_event_id": ordinal + 1,
                       "observed_at": datetime.now(timezone.utc).isoformat()}
                      for ordinal, phase in enumerate(("approach", "grasp", "transfer", "release"))]
        self.receipt = {
            **{field: getattr(grant, field) for field in (
                "mission_id", "step_id", "action_id", "attempt_id", "request_digest",
                "workcell_id", "instance_id", "authority_epoch", "dispatch_generation",
            )},
            "state": state, "journal_event_id": event_id,
            "observed_at": datetime.now(timezone.utc).isoformat(), "driver_goal_id": "local-goal",
            "reason": None, "phase_summaries": phases,
        }

    def submit(self, grant):
        saved = self.store.get(grant.mission_id)
        step = saved["steps"][saved["current_step_index"]]
        assert step["grant"] == grant.model_dump(mode="json")
        assert step["status"] == "RUNNING"
        assert self.tasks.resource_claims(resource_kind="workcell", resource_id=grant.workcell_id)[0][
            "phase"] == "DISPATCHING"
        self.submissions.append(grant)
        self.set_receipt(grant, "ACCEPTED", 1)
        if self.lose_submit:
            raise TimeoutError("lost submit receipt")
        return self.receipt

    def get(self, grant):
        self.lookups.append(grant)
        return self.receipt

    def cancel(self, grant, *, reason):
        self.cancellations.append((grant, reason))
        self.set_receipt(grant, "CANCEL_REQUESTED", 2)
        return self.receipt


def _ready(tmp_path, *, lose_submit=False):
    path, tasks, _, enabled = _stores(tmp_path)
    store = CellJobStore(path)
    _create(store)
    store.admit("cell-mission-1", actor_id="operator-1", expected_generation=enabled["generation"])
    transport = Transport(store, tasks, lose_submit=lose_submit)
    dispatcher = CellJobDispatcher(store, tasks, transport, {"omx_01": "omx_01_control"},
                                   config_revisions={"omx_01": "cell-config-v1"})
    return path, store, tasks, transport, dispatcher


def test_cell_dispatcher_waits_for_independent_goal_before_next_step(tmp_path):
    _, store, tasks, transport, dispatcher = _ready(tmp_path)
    assert dispatcher.dispatch_next()["state"] == "ACCEPTED"
    first = transport.submissions[0]
    assert first.action_kind == "CELL_TRANSFER" and first.cell_transfer.step_index == 0
    transport.set_receipt(first, "SUCCEEDED", 8)
    assert dispatcher.dispatch_next()["state"] == "ACTION_SUCCEEDED"
    assert dispatcher.dispatch_next() is None
    assert len(transport.submissions) == 1
    store.confirm_step_goal("cell-mission-1", step_index=0, action_id=first.action_id,
                            attempt_id=first.attempt_id, evidence=_goal(first.action_id, first.attempt_id, "goal-0"))
    assert dispatcher.dispatch_next()["state"] == "ACCEPTED"
    second = transport.submissions[1]
    assert second.cell_transfer.step_index == 1 and second.attempt_id != first.attempt_id
    transport.set_receipt(second, "SUCCEEDED", 9)
    dispatcher.dispatch_next()
    assert tasks.resource_claims(resource_kind="pallet", resource_id="pallet-1")
    store.confirm_step_goal("cell-mission-1", step_index=1, action_id=second.action_id,
                            attempt_id=second.attempt_id, evidence=_goal(second.action_id, second.attempt_id, "goal-1"))
    assert tasks.resource_claims(resource_kind="pallet", resource_id="pallet-1") == []


def test_lost_receipt_reopens_same_attempt_without_resubmit_or_hold_release(tmp_path):
    path, store, tasks, transport, dispatcher = _ready(tmp_path, lose_submit=True)
    assert dispatcher.dispatch_next()["state"] == "HOLD"
    original = transport.submissions[0]
    reopened = CellJobStore(path)
    recovered = CellJobDispatcher(reopened, tasks, transport, {"omx_01": "omx_01_control"},
                                  config_revisions={"omx_01": "cell-config-v1"})
    transport.set_receipt(original, "SUCCEEDED", 8)
    assert recovered.dispatch_next()["state"] == "HOLD"
    assert len(transport.submissions) == 1 and transport.lookups[-1] == original
    assert reopened.get("cell-mission-1")["steps"][1]["status"] == "WAITING"
    assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01")
    count = len(reopened.get("cell-mission-1")["events"])
    recovered.dispatch_next()
    assert len(reopened.get("cell-mission-1")["events"]) == count


@pytest.mark.parametrize("mutation", ["attempt", "missing_phases", "unfinished_phases"])
def test_cell_readback_conflict_retains_claims_and_blocks_next_step(tmp_path, mutation):
    _, store, tasks, transport, dispatcher = _ready(tmp_path)
    dispatcher.dispatch_next()
    transport.set_receipt(transport.submissions[0], "SUCCEEDED", 8)
    if mutation == "attempt":
        transport.receipt["attempt_id"] = "different-attempt"
    elif mutation == "missing_phases":
        transport.receipt["phase_summaries"] = None
    else:
        transport.receipt["phase_summaries"][3]["state"] = "RUNNING"
    assert dispatcher.dispatch_next()["state"] == "HOLD"
    assert store.get("cell-mission-1")["steps"][1]["status"] == "WAITING"
    assert tasks.resource_claims(resource_kind="pallet", resource_id="pallet-1")


def test_cell_cancel_acknowledgement_is_not_completion(tmp_path):
    _, store, tasks, transport, dispatcher = _ready(tmp_path)
    dispatcher.dispatch_next()
    assert dispatcher.cancel_current("cell-mission-1", reason="SITE_STOP")["state"] == "CANCEL_REQUESTED"
    grant, reason = transport.cancellations[0]
    assert grant == transport.submissions[0] and reason == "SITE_STOP"
    assert store.get("cell-mission-1")["status"] == "RUNNING"
    assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01")


def test_changed_receipt_at_same_watermark_is_rejected(tmp_path):
    _, store, _, transport, dispatcher = _ready(tmp_path)
    dispatcher.dispatch_next()
    original = transport.submissions[0]
    transport.receipt["state"] = "RUNNING"
    with pytest.raises(MissionConflict, match="different evidence"):
        store.record_action_receipt(original.mission_id, step_index=0, receipt=transport.receipt)


def test_expired_grant_can_be_read_without_releasing_occupancy_or_submitting_again(tmp_path):
    _, store, tasks, transport, dispatcher = _ready(tmp_path)
    dispatcher.dispatch_next()
    original = transport.submissions[0]
    recovered = CellJobDispatcher(store, tasks, transport, {"omx_01": "omx_01_control"},
                                  config_revisions={"omx_01": "cell-config-v1"},
                                  now=lambda: original.expires_at + timedelta(seconds=1))
    assert recovered.dispatch_next()["state"] == "ACCEPTED"
    assert len(transport.submissions) == 1 and transport.lookups[-1] == original
    assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01")


def test_stop_after_persisting_attempt_prevents_local_send(tmp_path, monkeypatch):
    _, store, tasks, transport, dispatcher = _ready(tmp_path)
    start = store.start_step

    def stop_after_start(*args, **kwargs):
        row = start(*args, **kwargs)
        tasks.trip_stop_latch(actor_id="operator-1")
        return row

    monkeypatch.setattr(store, "start_step", stop_after_start)
    assert dispatcher.dispatch_next()["state"] == "HOLD"
    assert transport.submissions == []
    assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01")


def test_invalid_persisted_grant_records_hold_without_lookup(tmp_path):
    _, store, _, transport, dispatcher = _ready(tmp_path)
    dispatcher.dispatch_next()
    grant = transport.submissions[0].model_dump(mode="json")
    grant["request_digest"] = "f" * 64
    with store._connect() as connection:
        connection.execute("UPDATE fleet_cell_steps SET grant_json=? WHERE step_index=0", (json.dumps(grant),))
        connection.commit()
    assert dispatcher.dispatch_next()["state"] == "HOLD"
    assert store.get("cell-mission-1")["status"] == "HOLD"
    assert transport.lookups == []


def test_receipt_replay_is_idempotent_after_goal_advances_the_job(tmp_path):
    _, store, _, transport, dispatcher = _ready(tmp_path)
    dispatcher.dispatch_next()
    grant = transport.submissions[0]
    transport.set_receipt(grant, "SUCCEEDED", 8)
    dispatcher.dispatch_next()
    store.confirm_step_goal(grant.mission_id, step_index=0, action_id=grant.action_id,
                            attempt_id=grant.attempt_id, evidence=_goal(grant.action_id, grant.attempt_id, "goal-0"))
    previous = store.get(grant.mission_id)
    repeated = store.record_action_receipt(grant.mission_id, step_index=0, receipt=transport.receipt)
    assert repeated == previous


@pytest.mark.parametrize("legacy_fails", [False, True])
def test_one_worker_visits_cell_dispatcher_even_when_legacy_dispatch_fails(monkeypatch, legacy_fails):
    from fleet.server.app import _mission_dispatch_loop

    sequence = []

    class Dispatcher:
        def __init__(self, name):
            self.name = name

        def dispatch_next(self):
            sequence.append(self.name)
            if self.name == "legacy" and legacy_fails:
                raise RuntimeError("legacy readback unavailable")

    async def end_cycle(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", end_cycle)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_mission_dispatch_loop(Dispatcher("legacy"), Dispatcher("cell")))
    assert sequence == ["legacy", "cell"]


@pytest.mark.parametrize("state", ["ACCEPTED", "SUCCEEDED"])
def test_stop_during_readback_holds_even_duplicate_receipt(tmp_path, monkeypatch, state):
    _, store, tasks, transport, dispatcher = _ready(tmp_path)
    dispatcher.dispatch_next()
    grant = transport.submissions[0]
    if state == "SUCCEEDED":
        transport.set_receipt(grant, state, 8)
    original_get = transport.get

    def stopped_get(grant):
        tasks.trip_stop_latch(actor_id="operator-1")
        return original_get(grant)

    monkeypatch.setattr(transport, "get", stopped_get)
    assert dispatcher.dispatch_next()["state"] == "HOLD"
    assert store.get(grant.mission_id)["steps"][1]["status"] == "WAITING"
    assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01")
    assert len(transport.submissions) == 1


@pytest.mark.parametrize("conflict", ["regression", "changed_event", "skipped_phase"])
def test_phase_history_conflicts_hold_attempt_and_occupancy(tmp_path, conflict):
    _, store, tasks, transport, dispatcher = _ready(tmp_path)
    dispatcher.dispatch_next()
    grant = transport.submissions[0]
    transport.set_receipt(grant, "RUNNING", 4)
    phase = {"phase_id": "approach", "ordinal": 0, "state": "SUCCEEDED",
             "journal_event_id": 3, "observed_at": datetime.now(timezone.utc).isoformat()}
    transport.receipt["phase_summaries"] = [phase.copy()]
    assert dispatcher.dispatch_next()["state"] == "RUNNING"
    transport.receipt["journal_event_id"] = 6
    if conflict == "regression":
        phase.update(state="RUNNING", journal_event_id=5)
    elif conflict == "changed_event":
        phase.update(state="RUNNING")
    else:
        phase.update(phase_id="transfer", ordinal=2, journal_event_id=5)
    transport.receipt["phase_summaries"] = [phase]
    assert dispatcher.dispatch_next()["state"] == "HOLD"
    assert store.get(grant.mission_id)["steps"][1]["status"] == "WAITING"
    assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01")
    assert len(transport.submissions) == 1


def test_older_phase_success_cannot_override_latest_durable_failure(tmp_path):
    _, store, tasks, transport, dispatcher = _ready(tmp_path)
    dispatcher.dispatch_next()
    grant = transport.submissions[0]
    transport.set_receipt(grant, "SUCCEEDED", 8)
    transport.receipt["state"] = "RUNNING"
    transport.receipt["phase_summaries"][3].update(state="FAILED", journal_event_id=7)
    assert dispatcher.dispatch_next()["state"] == "RUNNING"
    transport.receipt["state"] = "SUCCEEDED"
    transport.receipt["journal_event_id"] = 9
    transport.receipt["phase_summaries"][3].update(state="SUCCEEDED", journal_event_id=6)
    assert dispatcher.dispatch_next()["state"] == "HOLD"
    assert store.get(grant.mission_id)["steps"][1]["status"] == "WAITING"
    assert tasks.resource_claims(resource_kind="workcell", resource_id="omx_01")
