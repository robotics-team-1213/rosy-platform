import pytest

from omx_adapter.action_store import ActionConflict, ActionStore, InvalidActionTransition


def create(store, payload=None, generation=8):
    return store.create_action(
        workcell_id="omx_01", instance_id="omx_01_control", principal_id="operator-1",
        request_key="pick-place-1", action_kind="PICK_PLACE",
        configuration_revision="cfg-v4", observation_id="obs-44", owner_generation=generation,
        payload=payload or {"source": "block-1", "destination": "tray-1"},
    )


def test_request_key_is_idempotent_and_payload_changes_conflict(tmp_path):
    store = ActionStore(tmp_path / "actions.sqlite3")
    first = create(store)
    duplicate = create(store, {"destination": "tray-1", "source": "block-1"})

    assert first["created"] is True
    assert duplicate["created"] is False
    assert first["action"]["action_id"] == duplicate["action"]["action_id"]
    assert duplicate["action"]["state"] == "PREPARED"
    stopped_duplicate = create(store, generation=9)
    assert stopped_duplicate["created"] is False
    assert stopped_duplicate["action"]["owner_generation"] == 8
    with pytest.raises(InvalidActionTransition):
        store.begin_submission(stopped_duplicate["action"]["action_id"], expected_generation=9)
    with pytest.raises(ActionConflict):
        create(store, {"source": "block-2", "destination": "tray-1"})


def test_omx_action_database_uses_durable_wal_on_new_connections(tmp_path):
    store = ActionStore(tmp_path / "actions.sqlite3")

    with store._connect() as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_intent_is_durable_before_submission_and_same_attempt_cannot_submit_twice(tmp_path):
    store = ActionStore(tmp_path / "actions.sqlite3")
    action = create(store)["action"]
    attempt = store.begin_submission(action["action_id"], expected_generation=8)

    assert attempt["state"] == "SUBMITTING"
    with pytest.raises(InvalidActionTransition):
        store.begin_submission(action["action_id"], expected_generation=8)
    assert [item["state"] for item in store.history(action["action_id"])] == [
        "PREPARED", "SUBMITTING",
    ]


def test_crash_after_driver_send_becomes_unknown_and_never_replays_same_key(tmp_path):
    path = tmp_path / "actions.sqlite3"
    store = ActionStore(path)
    action = create(store)["action"]
    attempt = store.begin_submission(action["action_id"], expected_generation=8)
    recovered = ActionStore(path)

    assert recovered.recover_after_restart() == [action["action_id"]]
    unknown = recovered.get_action(action["action_id"])
    duplicate = create(recovered)
    assert unknown["state"] == "UNKNOWN"
    assert duplicate["created"] is False
    assert duplicate["action"]["action_id"] == attempt["action_id"] == action["action_id"]
    with pytest.raises(InvalidActionTransition):
        recovered.begin_submission(action["action_id"], expected_generation=8)


def test_cancel_receipt_is_not_terminal_and_only_matching_attempt_can_finish(tmp_path):
    store = ActionStore(tmp_path / "actions.sqlite3")
    action = create(store)["action"]
    attempt = store.begin_submission(action["action_id"], expected_generation=8)
    store.record_submission(action["action_id"], attempt["attempt_id"], accepted=True,
                            driver_goal_id="goal-7")
    store.mark_running(action["action_id"], attempt["attempt_id"], driver_goal_id="goal-7")
    canceled = store.request_cancel(action["action_id"], attempt["attempt_id"])
    assert canceled["state"] == "CANCEL_REQUESTED"
    cancel_ack = store.record_cancel_ack(
        action["action_id"], attempt["attempt_id"], acknowledged=True)
    assert cancel_ack["state"] == "CANCEL_REQUESTED"
    assert cancel_ack["cancel_acknowledged"] is True

    with pytest.raises(InvalidActionTransition):
        store.record_terminal(action["action_id"], "old-attempt", driver_goal_id="goal-7",
                              outcome="SUCCEEDED", result_source="driver-result",
                              result_observed_at="2026-09-29T10:00:00Z",
                              result={"success": True})
    assert store.get_action(action["action_id"])["state"] == "CANCEL_REQUESTED"
    completed = store.record_terminal(
        action["action_id"], attempt["attempt_id"], driver_goal_id="goal-7",
        outcome="SUCCEEDED", result_source="driver-result",
        result_observed_at="2026-09-29T10:00:00Z",
        result={"success": True},
    )
    assert completed["state"] == "SUCCEEDED"
    assert store.get_action(action["action_id"])["state"] == "SUCCEEDED"


def test_acceptance_timeout_is_unknown_and_restart_keeps_unresolved_claim(tmp_path):
    path = tmp_path / "actions.sqlite3"
    store = ActionStore(path)
    action = create(store)["action"]
    attempt = store.begin_submission(action["action_id"], expected_generation=8)
    unknown = store.record_submission(action["action_id"], attempt["attempt_id"],
                                      accepted=None, driver_goal_id=None)

    assert unknown["state"] == "UNKNOWN"
    assert ActionStore(path).recover_after_restart() == []
    assert ActionStore(path).get_action(action["action_id"])["state"] == "UNKNOWN"


def test_fault_hold_stays_unresolved_until_matching_terminal_readback(tmp_path):
    store = ActionStore(tmp_path / "actions.sqlite3")
    action = create(store)["action"]
    attempt = store.begin_submission(action["action_id"], expected_generation=8)
    store.record_submission(action["action_id"], attempt["attempt_id"], accepted=True,
                            driver_goal_id="goal-7")

    held = store.hold_action(action["action_id"], attempt["attempt_id"], reason="grip_state_unknown")
    assert held["state"] == "HOLD"
    assert len(store.unresolved_actions(workcell_id="omx_01")) == 1
    with pytest.raises(InvalidActionTransition):
        store.begin_submission(action["action_id"], expected_generation=8)

    terminal = store.record_terminal(
        action["action_id"], attempt["attempt_id"], driver_goal_id="goal-7",
        outcome="FAILED", result_source="driver-result",
        result_observed_at="2026-09-29T10:00:00Z", result={"success": False},
    )
    assert terminal["state"] == "FAILED"
    assert store.unresolved_actions() == []


def test_prepared_but_never_submitted_intent_is_not_called_unknown(tmp_path):
    path = tmp_path / "actions.sqlite3"
    action = create(ActionStore(path))["action"]

    assert ActionStore(path).recover_after_restart() == []
    assert ActionStore(path).get_action(action["action_id"])["state"] == "PREPARED"
