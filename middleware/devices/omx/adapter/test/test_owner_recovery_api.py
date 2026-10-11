"""D-442 U3: delegated operator recovery clears only the owner HOLD latch."""

import pytest

from omx_adapter.action_store import ActionStore
from omx_adapter.action_api import ActionApi
from omx_adapter.local_stop import LocalStopController
from omx_adapter.owner_recovery_api import OwnerRecoveryApi
from test_omx_command_owner import make_state, owner_at


def prepared(tmp_path):
    owner, action = owner_at([100.0])
    owner.observe_joint_state(make_state())
    owner.preempt("manual_priority")
    owner.observe_joint_state(make_state(sequence=11))
    store = ActionStore(tmp_path / "owner.db")
    config = owner.config
    stop = LocalStopController(store.path, workcell_id=config.workcell_id, instance_id=config.instance_id)
    stop.rearm(authority_epoch=2, dispatch_generation=1, operator_confirmed=True,
               fleet_fence_current=lambda epoch, generation: (epoch, generation) == (2, 1))
    api = OwnerRecoveryApi(owner, stop, store, allowed_peer_uids={1001},
                           current_fence=lambda epoch, generation: (epoch, generation) == (2, 1))
    request = dict(version=1, operation="RecoverOwner", workcell_id=config.workcell_id,
                   instance_id=config.instance_id, authority_epoch=2, dispatch_generation=1,
                   operator_confirmed=True, observed_sequence=11, actor_id="named-operator")
    return api, owner, action, stop, store, request


def test_confirmed_recovery_clears_owner_hold_without_motion_or_rearming_stop(tmp_path):
    api, owner, action, stop, _, request = prepared(tmp_path)
    before = stop.snapshot(workcell_id=request["workcell_id"], instance_id=request["instance_id"])
    result = api.dispatch(request, peer_uid=1001)
    assert result["status"] == 200 and result["decision"]["accepted"] is True
    assert owner.state == "ready" and action.commands == []
    assert stop.snapshot(workcell_id=request["workcell_id"], instance_id=request["instance_id"]) == before


@pytest.mark.parametrize("patch", [
    {"version": True}, {"version": 2}, {"operator_confirmed": 1}, {"operator_confirmed": False},
    {"observed_sequence": True}, {"observed_sequence": "11"}, {"authority_epoch": True},
    {"dispatch_generation": -1}, {"actor_id": ""}, {"unexpected": True},
])
def test_recovery_rejects_coercion_missing_confirmation_and_extra_fields(tmp_path, patch):
    api, owner, action, _, _, request = prepared(tmp_path)
    assert api.dispatch({**request, **patch}, peer_uid=1001)["status"] == 400
    assert owner.state == "hold" and action.commands == []


def test_recovery_rejects_wrong_peer_and_device(tmp_path):
    api, owner, action, _, _, request = prepared(tmp_path)
    assert api.dispatch(request, peer_uid=1002)["status"] == 403
    assert api.dispatch({**request, "instance_id": "another"}, peer_uid=1001)["status"] == 404
    assert owner.state == "hold" and action.commands == []


def test_stale_fence_or_closed_local_stop_cannot_clear_owner_hold(tmp_path):
    api, owner, action, _, _, request = prepared(tmp_path)
    result = api.dispatch({**request, "dispatch_generation": 0}, peer_uid=1001)
    assert result["status"] == 409 and owner.state == "hold"
    assert action.commands == []


def test_stale_readback_cannot_clear_owner_hold(tmp_path):
    api, owner, action, _, _, request = prepared(tmp_path)
    result = api.dispatch({**request, "observed_sequence": 10}, peer_uid=1001)
    assert result["status"] == 409 and result["decision"]["reason"] == "fresh_readback_required"
    assert owner.state == "hold" and action.commands == []


def test_owner_state_readback_does_not_clear_hold(tmp_path):
    api, owner, action, _, _, request = prepared(tmp_path)
    read = {key: request[key] for key in ("version", "workcell_id", "instance_id")}
    result = api.dispatch({**read, "operation": "GetOwnerState"}, peer_uid=1001)
    assert result["status"] == 200 and result["owner"]["state"] == "hold"
    assert result["owner"]["observed_sequence"] == 11
    assert owner.state == "hold" and action.commands == []


def test_even_a_prepared_action_blocks_recovery(tmp_path):
    api, owner, action, _, store, request = prepared(tmp_path)
    store.create_action(workcell_id=owner.config.workcell_id, instance_id=owner.config.instance_id,
                        principal_id="fleet-peer", request_key="queued-1", action_kind="PICK_PLACE",
                        configuration_revision="cfg-1", observation_id="obs-1",
                        owner_generation=1, payload={})
    assert store.unresolved_actions() == []  # Legacy readback excludes PREPARED.
    result = api.dispatch(request, peer_uid=1001)
    assert result["status"] == 409 and owner.state == "hold" and action.commands == []


def test_actual_action_dispatcher_routes_recovery_to_the_peer_guard(tmp_path):
    recovery, owner, action, _, _, request = prepared(tmp_path)
    api = ActionApi(object(), recovery_api=recovery)
    assert api.dispatch(request, peer_uid=1002)["status"] == 403
    assert api.dispatch(request, peer_uid=1001)["decision"]["accepted"] is True
    assert owner.state == "ready" and action.commands == []


def test_readback_cannot_change_during_the_journal_fence(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    api, owner, _, _, store, request = prepared(tmp_path)
    entered, release, feedback_started = Event(), Event(), Event()
    original = store.run_if_no_unresolved

    def fenced(**kwargs):
        clear = kwargs["operation"]
        def pause():
            entered.set()
            assert release.wait(2)
            return clear()
        return original(**{**kwargs, "operation": pause})

    store.run_if_no_unresolved = fenced
    def feedback():
        feedback_started.set()
        return owner.observe_joint_state(make_state(sequence=12))
    with ThreadPoolExecutor(max_workers=2) as pool:
        recovery = pool.submit(api.dispatch, request, peer_uid=1001)
        assert entered.wait(2)
        readback = pool.submit(feedback)
        assert feedback_started.wait(2)
        try:
            assert not readback.done()
        finally:
            release.set()
        assert recovery.result(timeout=2)["observed_sequence"] == 11
        assert readback.result(timeout=2) is True


def test_journal_commit_failure_after_clear_restores_original_owner_hold(tmp_path):
    import sqlite3

    api, owner, action, stop, store, request = prepared(tmp_path)
    before = owner.recovery_state()
    stop_before = stop.snapshot(workcell_id=request["workcell_id"], instance_id=request["instance_id"])
    connect = store._connect
    class FailCommit:
        def __init__(self):
            self.connection = connect()
        def execute(self, *args):
            return self.connection.execute(*args)
        def commit(self):
            assert owner.state == "ready"  # Failure is after the attempted clear.
            raise sqlite3.OperationalError("simulated journal commit failure")
        def close(self):
            self.connection.close()
    store._connect = FailCommit
    result = api.dispatch(request, peer_uid=1001)
    assert result["status"] == 503
    assert owner.recovery_state() == before
    assert stop.snapshot(workcell_id=request["workcell_id"], instance_id=request["instance_id"]) == stop_before
    assert action.commands == []


@pytest.mark.parametrize("contender", ["journal_claim", "local_stop"])
def test_recovery_serializes_with_journal_claim_and_local_stop(tmp_path, contender):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    from datetime import datetime, timezone
    from threading import Event
    from core_common.protocol.schemas import LocalStopRequest, StopRequestSource

    api, owner, action, stop, store, request = prepared(tmp_path)
    entered, release, attempted = Event(), Event(), Event()
    original = store.run_if_no_unresolved
    order = []

    def guarded(**kwargs):
        clear = kwargs["operation"]
        def pause():
            entered.set()
            assert release.wait(3)
            result = clear()
            order.append("recovery")
            return result
        return original(**{**kwargs, "operation": pause})

    store.run_if_no_unresolved = guarded
    def compete():
        attempted.set()
        if contender == "journal_claim":
            result = store.create_action(
                workcell_id=owner.config.workcell_id, instance_id=owner.config.instance_id,
                principal_id="fleet-peer", request_key="concurrent-1", action_kind="PICK_PLACE",
                configuration_revision="cfg-1", observation_id="obs-1", owner_generation=1, payload={})
        else:
            result = stop.trip(LocalStopRequest(
                workcell_id=owner.config.workcell_id, instance_id=owner.config.instance_id,
                authority_epoch=2, dispatch_generation=1, requested_at=datetime.now(timezone.utc),
                reason="operator_stop"), source=StopRequestSource.FLEET)
        order.append(contender)
        return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        recovery = pool.submit(api.dispatch, request, peer_uid=1001)
        assert entered.wait(3)
        competing = pool.submit(compete)
        assert attempted.wait(3)
        try:
            with pytest.raises(TimeoutError):
                competing.result(timeout=0.1)
        finally:
            release.set()
        assert recovery.result(timeout=3)["status"] == 200
        competing.result(timeout=3)
    assert order == ["recovery", contender] and action.commands == []
    if contender == "local_stop":
        assert not stop.is_open(authority_epoch=2, dispatch_generation=1)
