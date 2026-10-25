import json
import sqlite3

import pytest

from core_common.protocol.integrated_control import (
    ControlDispatchFence, ControlStopIngress, ControlStopReconcile,
    ControlStopSnapshot, ControlStopUnitResult,
)
from fleet.server.control_stop_store import ControlStopStore, StopAssignment, has_local_uncertainty
from fleet.server.task_store import FleetTaskStore


@pytest.fixture
def journal(tmp_path, monkeypatch):
    tasks = FleetTaskStore(tmp_path / "tasks.sqlite3")
    calls = []

    def latch(connection, **kwargs):
        # This fake isolates journal atomicity; root integration tests exercise actual Task cleanup.
        assert kwargs == dict(enabled=False, actor_id="private-operator", reason="CONTROL_UNIT_STOP",
                              release_pre_dispatch=True)
        calls.append(True)
        connection.execute("UPDATE fleet_dispatch_control SET generation=generation+1,dispatch_enabled=0")

    monkeypatch.setattr(tasks, "_advance_dispatch_control_in", latch, raising=False)
    with tasks._connect() as connection:
        connection.execute("UPDATE fleet_dispatch_control SET authority_epoch=3,generation=7")
    return ControlStopStore(tasks, unit_id="R", config_revision="v1"), calls


def request(identity="stop-1", *, generation=7, expected=None, target="R"):
    return ControlStopIngress(origin_id="R", stop_id=identity, target_unit=target, config_revision="v1",
                              expected_controls=expected or {"R": {"authority_epoch": 3, "generation": generation}})


def claim(store, ingress=None, *, scope=("R",), assignments=None):
    return store.claim(ingress or request(), scope=scope, assignments=assignments or {}, actor_id="private-operator")


def result(unit="R", *, state="ACKNOWLEDGED", generation=8):
    return ControlStopUnitResult(unit_id=unit, state=state,
                                 dispatch=ControlDispatchFence(authority_epoch=3, generation=generation),
                                 acknowledged_robots=1, unknown_robots=0, omx_state="LOCAL_LATCHED",
                                 physical_stop="UNVERIFIED")


def finish_local(store, claimed, *, state="ACKNOWLEDGED"):
    local = next(item for item in claimed.snapshot.results if item.unit_id == "R")
    return store.finish("R", claimed.snapshot.stop_id, "R", claimed.tickets[0].ticket,
                        result(state=state, generation=local.dispatch.generation))


def local_guard(store):
    with store.tasks._connect() as connection:
        return has_local_uncertainty(connection, "R")


def child_plan(ingress):
    child = ingress.model_copy(update={"target_unit": "A", "expected_controls": {
        "A": ingress.expected_controls["A"]}})
    return {"A": StopAssignment(child, ("A",))}


def child_snapshot(*, state="UNKNOWN", revision=1, **updates):
    values = dict(unit_id="A", origin_id="R", stop_id="stop-1", target_unit="A", config_revision="v1",
                  results=[result("A", state=state)], revision=revision)
    values.update(updates)
    return ControlStopSnapshot(**values)


def test_first_claim_latches_once_and_duplicate_after_rearm_never_gets_ticket(journal):
    store, calls = journal
    first = claim(store)
    assert len(first.tickets) == len(calls) == 1
    assert first.snapshot.results[0].dispatch.generation == 8 and local_guard(store)
    assert finish_local(store, first)
    with store.tasks._connect() as connection:
        connection.execute("UPDATE fleet_dispatch_control SET generation=99,dispatch_enabled=1")
    duplicate = claim(store)
    assert duplicate.tickets == () and duplicate.snapshot.results[0].state == "ACKNOWLEDGED"
    assert len(calls) == 1 and not local_guard(store)
    with pytest.raises(ValueError, match="IDENTITY_CONFLICT"):
        claim(store, request(generation=99))
    assert store.tasks.dispatch_control()["generation"] == 99


def test_journal_and_latch_rollback_together_on_helper_failure(journal, monkeypatch):
    store, _ = journal

    def failed(connection, **kwargs):
        connection.execute("UPDATE fleet_dispatch_control SET generation=generation+1")
        raise sqlite3.OperationalError("synthetic latch failure")

    monkeypatch.setattr(store.tasks, "_advance_dispatch_control_in", failed)
    with pytest.raises(sqlite3.OperationalError):
        claim(store)
    assert store.tasks.dispatch_control()["generation"] == 7
    assert store.history().stops == []
    with pytest.raises(KeyError):
        store.snapshot("R", "stop-1")


def test_stale_local_fence_does_not_block_independent_child_ticket(journal):
    store, calls = journal
    ingress = request(expected={"R": {"authority_epoch": 3, "generation": 6},
                                "A": {"authority_epoch": 2, "generation": 4}})
    first = claim(store, ingress, scope=("R", "A"), assignments=child_plan(ingress))
    assert calls == [] and [ticket.delivery_unit for ticket in first.tickets] == ["A"]
    assert {row.unit_id: row.state for row in first.snapshot.results} == {"A": "PENDING", "R": "STALE_FENCE"}
    assert not local_guard(store)
    assert store.assigned("R", "stop-1")["assignments"]["A"]["request"]["target_unit"] == "A"


def test_missing_local_and_child_fences_are_never_executable(journal):
    store, calls = journal
    ingress = request(expected={"A": {"authority_epoch": 2, "generation": 4}})
    first = claim(store, ingress, scope=("R", "A"), assignments=child_plan(ingress))
    assert calls == [] and [ticket.delivery_unit for ticket in first.tickets] == ["A"]
    assert next(row for row in first.snapshot.results if row.unit_id == "R").state == "NOT_REACHED"
    second = claim(store, request("no-child"), scope=("R", "A"),
                   assignments={"A": StopAssignment(None, ("A",))})
    assert [ticket.delivery_unit for ticket in second.tickets] == ["R"]
    assert next(row for row in second.snapshot.results if row.unit_id == "A").state == "NOT_REACHED"


def test_assignments_are_immutable_and_cannot_invent_fences(journal):
    store, _ = journal
    ingress = request(expected={"A": {"authority_epoch": 2, "generation": 4}})
    plans = child_plan(ingress)
    claim(store, ingress, scope=("A",), assignments=plans)
    changed = {"B": plans["A"]}
    with pytest.raises(ValueError, match="IDENTITY_CONFLICT"):
        claim(store, ingress, scope=("A",), assignments=changed)
    forged = plans["A"].request.model_copy(update={"expected_controls": {"A": ControlDispatchFence(
        authority_epoch=2, generation=999)}})
    with pytest.raises(ValueError, match="INVALID_ASSIGNMENT"):
        claim(store, request("forged", expected=ingress.expected_controls), scope=("A",),
              assignments={"A": StopAssignment(forged.model_copy(update={"stop_id": "forged"}), ("A",))})


def test_recovery_invalidates_tickets_and_never_replays_work(journal):
    store, calls = journal
    first = claim(store)
    reopened = ControlStopStore(store.tasks, unit_id="R", config_revision="v1")
    assert reopened.recover() == 1 and reopened.recover() == 0
    assert reopened.snapshot("R", "stop-1").results[0].state == "UNKNOWN"
    assert local_guard(reopened) and reopened.pending_count() == 1
    assert not finish_local(reopened, first)
    assert claim(reopened).tickets == () and len(calls) == 1


def test_finish_requires_matching_live_ticket_and_preserves_unknown_guard(journal):
    store, _ = journal
    first = claim(store)
    assert not store.finish("R", "stop-1", "R", "wrong", result())
    assert local_guard(store)
    assert finish_local(store, first, state="PARTIAL")
    assert local_guard(store) and store.pending_count() == 1
    assert not finish_local(store, first)


def test_finish_journal_failure_keeps_committed_guard_and_does_not_grant_new_ticket(journal, monkeypatch):
    store, calls = journal
    first = claim(store)

    def failed(*args):
        raise sqlite3.OperationalError("synthetic journal failure")

    monkeypatch.setattr(store, "_bump", failed)
    with pytest.raises(sqlite3.OperationalError):
        finish_local(store, first)
    assert local_guard(store) and store.snapshot("R", "stop-1").results[0].state == "SENDING"
    assert claim(store).tickets == () and len(calls) == 1


def test_rearm_guard_includes_local_uncertainty_from_an_old_configured_identity(journal):
    store, _ = journal
    claim(store)
    with store.tasks._connect() as connection:
        assert has_local_uncertainty(connection)
        assert not has_local_uncertainty(connection, "new-configured-unit")


def test_transport_failure_retains_uncertainty_without_inventing_peer_revision(journal):
    store, _ = journal
    ingress = request(expected={"A": {"authority_epoch": 2, "generation": 4}})
    first = claim(store, ingress, scope=("A",), assignments=child_plan(ingress))
    assert store.fail("R", "stop-1", "A", first.tickets[0].ticket)
    assert store.pending_count() == 1 and not local_guard(store)
    assert not store.fail("R", "stop-1", "A", first.tickets[0].ticket)
    assert store.observe_child("R", "stop-1", "A", child_snapshot(
        state="ACKNOWLEDGED", revision=1)).results[0].state == "ACKNOWLEDGED"
    assert store.pending_count() == 0


def test_mixed_terminal_child_outcomes_do_not_consume_uncertainty_capacity(journal):
    store, _ = journal
    ingress = request(expected={"A": {"authority_epoch": 2, "generation": 4}})
    assignment = StopAssignment(child_plan(ingress)["A"].request, ("A", "A1"))
    first = claim(store, ingress, scope=("A", "A1"), assignments={"A": assignment})
    snapshot = child_snapshot(results=[result("A"), result("A1", state="STALE_FENCE")])
    assert store.finish("R", "stop-1", "A", first.tickets[0].ticket, snapshot)
    assert store.pending_count() == 0 and not store.history().stops[0].incomplete


@pytest.mark.parametrize("updates", [
    {"origin_id": "B"}, {"stop_id": "different"}, {"unit_id": "B"}, {"target_unit": "R"},
    {"config_revision": "v2"}, {"results": [result("B")]},
])
def test_child_readback_rejects_provenance_and_scope_spoofing(journal, updates):
    store, _ = journal
    ingress = request(expected={"A": {"authority_epoch": 2, "generation": 4}})
    claim(store, ingress, scope=("A",), assignments=child_plan(ingress))
    store.recover()
    with pytest.raises(ValueError, match="CHILD_RESULT_MISMATCH"):
        store.observe_child("R", "stop-1", "A", child_snapshot(**updates))
    assert store.snapshot("R", "stop-1").results[0].state == "UNKNOWN"


def test_child_get_readback_is_monotonic_and_cannot_clear_local_guard(journal):
    store, calls = journal
    ingress = request(expected={"R": {"authority_epoch": 3, "generation": 7},
                                "A": {"authority_epoch": 2, "generation": 4}})
    first = claim(store, ingress, scope=("R", "A"), assignments=child_plan(ingress))
    store.recover()
    view = store.observe_child("R", "stop-1", "A", child_snapshot(revision=2))
    assert store.observe_child("R", "stop-1", "A", child_snapshot(revision=2)).revision == view.revision
    with pytest.raises(ValueError, match="REVISION_CONFLICT"):
        store.observe_child("R", "stop-1", "A", child_snapshot(revision=1))
    with pytest.raises(ValueError, match="REVISION_CONFLICT"):
        store.observe_child("R", "stop-1", "A", child_snapshot(revision=2, state="ACKNOWLEDGED"))
    view = store.observe_child("R", "stop-1", "A", child_snapshot(
        revision=3, state="SUPERSEDED_BY_OPERATOR_RECOMMISSIONING"))
    assert local_guard(store) and len(calls) == 1 and claim(
        store, ingress, scope=("R", "A"), assignments=child_plan(ingress)).tickets == ()
    assert next(row for row in view.results if row.unit_id == "R").state == "UNKNOWN"
    assert not finish_local(store, first)


def confirmation(generation=8, *, units=None):
    return ControlStopReconcile(expected_generation=generation, receiver_channels_terminated=True,
                                receivers_recommissioned=True, evidence="private-recommissioning-evidence",
                                affected_units=units or ["R"])


def test_named_local_reconciliation_requires_no_live_work_and_current_generation(journal):
    store, _ = journal
    first = claim(store)
    with pytest.raises(ValueError, match="RECONCILIATION_REFUSED"):
        store.reconcile("R", "stop-1", confirmation(), actor_id="named", live_work=lambda *args: False)
    store.recover()
    with pytest.raises(ValueError, match="RECONCILIATION_REFUSED"):
        store.reconcile("R", "stop-1", confirmation(), actor_id="named", live_work=lambda *args: True)
    with pytest.raises(ValueError, match="FENCE_CHANGED"):
        store.reconcile("R", "stop-1", confirmation(7), actor_id="named", live_work=lambda *args: False)
    with pytest.raises(ValueError, match="LOCAL_RECONCILIATION_ONLY"):
        store.reconcile("R", "stop-1", confirmation(units=["A"]), actor_id="named", live_work=lambda *args: False)
    view = store.reconcile("R", "stop-1", confirmation(), actor_id="private-named", live_work=lambda *args: False)
    assert view.results[0].state == "SUPERSEDED_BY_OPERATOR_RECOMMISSIONING"
    assert not local_guard(store) and store.pending_count() == 0
    assert store.tasks.dispatch_control()["generation"] == 8
    assert not store.tasks.dispatch_control()["dispatch_enabled"]
    with store.tasks._connect() as connection:
        row = connection.execute("SELECT original_json,reconcile_json,reconciled_by FROM "
                                 "fleet_control_stop_deliveries").fetchone()
        assert json.loads(row["original_json"])[0]["state"] == "UNKNOWN"
        assert "private-recommissioning-evidence" in row["reconcile_json"]
    assert "private" not in view.model_dump_json() and "private" not in store.history().model_dump_json()
    assert not finish_local(store, first)


def test_unresolved_capacity_does_not_delete_dedup_records(journal):
    store, _ = journal
    claims = [claim(store, request(f"stop-{index}", generation=7 + index)) for index in range(64)]
    assert store.pending_count() == 64
    with pytest.raises(ValueError, match="UNRESOLVED_CAPACITY"):
        claim(store, request("overflow", generation=71))
    assert claim(store, request("stop-0")).tickets == ()
    assert finish_local(store, claims[0])
    assert claim(store, request("new", generation=71)).tickets
    assert store.snapshot("R", "stop-0").results[0].state == "ACKNOWLEDGED"


def test_history_keeps_unresolved_before_newer_terminal_records(journal):
    store, _ = journal
    claim(store, request("old-active"))
    for index in range(105):
        claimed = claim(store, request(f"done-{index}", generation=8 + index))
        assert finish_local(store, claimed)
    history = store.history()
    assert len(history.stops) == 100 and history.stops[0].stop_id == "old-active"
    assert history.stops[0].incomplete and history.stops[0].local_reconciliation_required
    assert "private" not in history.model_dump_json()
    assert store.pending_count() == 1
