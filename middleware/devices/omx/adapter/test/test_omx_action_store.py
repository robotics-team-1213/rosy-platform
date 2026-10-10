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


def test_holding_action_marks_active_phase_unknown_and_blocks_continuation(tmp_path):
    store = ActionStore(tmp_path / "actions.sqlite3")
    action = create(store)["action"]
    attempt = store.begin_submission(action["action_id"], expected_generation=8)
    store.begin_phase(
        action["action_id"], attempt["attempt_id"], phase_id="approach",
        ordinal=0, command_digest="a" * 64,
    )
    store.record_first_phase_submission(
        action["action_id"], attempt["attempt_id"], phase_id="approach",
        accepted=True, driver_goal_id="ros-goal-approach",
    )

    held = store.hold_action(
        action["action_id"], attempt["attempt_id"], reason="STOP_GENERATION_FENCED",
    )

    phase = store.action_phases(action["action_id"])[0]
    assert held["state"] == "HOLD"
    assert phase["state"] == "UNKNOWN"
    assert phase["driver_goal_id"] == "ros-goal-approach"
    assert phase["reason"] == "STOP_GENERATION_FENCED"
    with pytest.raises(InvalidActionTransition):
        store.begin_phase(
            action["action_id"], attempt["attempt_id"], phase_id="grasp",
            ordinal=1, command_digest="b" * 64,
        )


def test_prepared_but_never_submitted_intent_is_not_called_unknown(tmp_path):
    path = tmp_path / "actions.sqlite3"
    action = create(ActionStore(path))["action"]

    assert ActionStore(path).recover_after_restart() == []
    assert ActionStore(path).get_action(action["action_id"])["state"] == "PREPARED"


def start_running(store):
    action = create(store)["action"]
    attempt = store.begin_submission(action["action_id"], expected_generation=8)
    accepted = store.record_submission(
        action["action_id"], attempt["attempt_id"], accepted=True,
        driver_goal_id="legacy-action-goal",
    )
    store.mark_running(
        action["action_id"], attempt["attempt_id"],
        driver_goal_id="legacy-action-goal",
    )
    return accepted["action_id"], attempt["attempt_id"]


def test_action_attempt_persists_multiple_ordered_ros_goal_phases(tmp_path):
    store = ActionStore(tmp_path / "actions.sqlite3")
    action_id, attempt_id = start_running(store)

    store.begin_phase(
        action_id, attempt_id, phase_id="approach", ordinal=0,
        command_digest="a" * 64,
    )
    store.record_phase_submission(
        action_id, attempt_id, phase_id="approach", accepted=True,
        driver_goal_id="ros-goal-approach",
    )
    store.record_phase_terminal(
        action_id, attempt_id, phase_id="approach",
        driver_goal_id="ros-goal-approach", outcome="SUCCEEDED",
        result_source="ros-action-result",
        result_observed_at="2026-09-30T10:00:00Z", result={"status": 4},
    )
    with pytest.raises(InvalidActionTransition):
        store.begin_phase(
            action_id, attempt_id, phase_id="approach", ordinal=1,
            command_digest="b" * 64,
        )
    store.begin_phase(
        action_id, attempt_id, phase_id="grasp", ordinal=1,
        command_digest="b" * 64,
    )
    store.record_phase_submission(
        action_id, attempt_id, phase_id="grasp", accepted=True,
        driver_goal_id="ros-goal-grasp",
    )

    phases = store.action_phases(action_id)
    assert [(phase["phase_id"], phase["ordinal"], phase["state"],
             phase["driver_goal_id"]) for phase in phases] == [
        ("approach", 0, "SUCCEEDED", "ros-goal-approach"),
        ("grasp", 1, "ACCEPTED", "ros-goal-grasp"),
    ]


def test_first_phase_intent_is_allowed_while_parent_is_submitting(tmp_path):
    store = ActionStore(tmp_path / "actions.sqlite3")
    action = create(store)["action"]
    attempt = store.begin_submission(action["action_id"], expected_generation=8)

    phase = store.begin_phase(
        action["action_id"], attempt["attempt_id"], phase_id="approach",
        ordinal=0, command_digest="a" * 64,
    )

    assert phase["state"] == "SUBMITTING"
    with pytest.raises(InvalidActionTransition):
        store.begin_phase(
            action["action_id"], attempt["attempt_id"], phase_id="grasp",
            ordinal=1, command_digest="b" * 64,
        )


@pytest.mark.parametrize(("accepted", "goal_id", "expected"), [
    (True, "ros-goal-1", "ACCEPTED"),
    (False, None, "FAILED"),
    (None, None, "UNKNOWN"),
])
def test_first_phase_response_updates_parent_and_phase_together(
    tmp_path, accepted, goal_id, expected,
):
    store = ActionStore(tmp_path / "actions.sqlite3")
    action = create(store)["action"]
    attempt = store.begin_submission(action["action_id"], expected_generation=8)
    store.begin_phase(
        action["action_id"], attempt["attempt_id"], phase_id="approach",
        ordinal=0, command_digest="a" * 64,
    )

    recorded = store.record_first_phase_submission(
        action["action_id"], attempt["attempt_id"], phase_id="approach",
        accepted=accepted, driver_goal_id=goal_id,
    )

    assert recorded["action"]["state"] == expected
    assert recorded["phase"]["state"] == expected
    assert recorded["action"]["driver_goal_id"] == goal_id
    assert recorded["phase"]["driver_goal_id"] == goal_id


def test_first_phase_acceptance_event_failure_rolls_back_both_records(tmp_path, monkeypatch):
    store = ActionStore(tmp_path / "actions.sqlite3")
    action = create(store)["action"]
    attempt = store.begin_submission(action["action_id"], expected_generation=8)
    store.begin_phase(
        action["action_id"], attempt["attempt_id"], phase_id="approach",
        ordinal=0, command_digest="a" * 64,
    )
    append_event = store._append_event

    def fail_on_phase_acceptance(connection, **kwargs):
        if kwargs.get("event_type") == "ACTION_PHASE_ACCEPTANCE_RECORDED":
            raise RuntimeError("injected phase event write failure")
        return append_event(connection, **kwargs)

    monkeypatch.setattr(store, "_append_event", fail_on_phase_acceptance)
    with pytest.raises(RuntimeError, match="injected"):
        store.record_first_phase_submission(
            action["action_id"], attempt["attempt_id"], phase_id="approach",
            accepted=True, driver_goal_id="ros-goal-1",
        )

    assert store.get_action(action["action_id"])["state"] == "SUBMITTING"
    assert store.action_phases(action["action_id"])[0]["state"] == "SUBMITTING"


def test_restart_after_first_phase_intent_is_unknown_and_never_replayable(tmp_path):
    path = tmp_path / "actions.sqlite3"
    store = ActionStore(path)
    action = create(store)["action"]
    attempt = store.begin_submission(action["action_id"], expected_generation=8)
    store.begin_phase(
        action["action_id"], attempt["attempt_id"], phase_id="approach",
        ordinal=0, command_digest="a" * 64,
    )

    recovered = ActionStore(path)
    assert recovered.recover_after_restart() == [action["action_id"]]
    assert recovered.get_action(action["action_id"])["state"] == "UNKNOWN"
    phase = recovered.action_phases(action["action_id"])[0]
    assert phase["state"] == "UNKNOWN"
    assert phase["driver_goal_id"] is None
    with pytest.raises(InvalidActionTransition):
        recovered.record_first_phase_submission(
            action["action_id"], attempt["attempt_id"], phase_id="approach",
            accepted=True, driver_goal_id="late-goal",
        )
    with pytest.raises(InvalidActionTransition):
        recovered.begin_phase(
            action["action_id"], attempt["attempt_id"], phase_id="approach",
            ordinal=0, command_digest="a" * 64,
        )


def test_restart_appends_workflow_hold_and_preserves_possible_held_object(tmp_path):
    path = tmp_path / "actions.sqlite3"
    store = ActionStore(path)
    action = create(store)["action"]
    attempt = store.begin_submission(action["action_id"], expected_generation=8)
    store.record_workflow_state(
        action["action_id"], attempt["attempt_id"],
        workflow_state="VERIFY_HOLD", object_may_be_held=True,
        evidence_refs={"phase_result_id": "grasp-result"},
    )

    recovered = ActionStore(path)
    assert recovered.recover_after_restart() == [action["action_id"]]
    reopened = ActionStore(path)
    history = reopened.history(action["action_id"])
    workflow_events = [event for event in history
                       if event["event_type"] == "ACTION_WORKFLOW_STATE"]

    assert reopened.get_action(action["action_id"])["state"] == "UNKNOWN"
    assert workflow_events[-1]["detail"]["workflow_state"] == "HOLD"
    assert workflow_events[-1]["detail"]["object_may_be_held"] is True
    assert workflow_events[-1]["detail"]["evidence_refs"]["hold_reason"] == (
        "PROCESS_RESTARTED_WITH_UNRESOLVED_ACTION"
    )
    with pytest.raises(InvalidActionTransition):
        reopened.record_workflow_state(
            action["action_id"], attempt["attempt_id"],
            workflow_state="TRANSFER", object_may_be_held=True,
            evidence_refs={"phase_result_id": "late-result"},
        )


@pytest.mark.parametrize("accepted", [False, None])
def test_unaccepted_first_phase_cannot_claim_a_ros_goal_id(tmp_path, accepted):
    store = ActionStore(tmp_path / "actions.sqlite3")
    action = create(store)["action"]
    attempt = store.begin_submission(action["action_id"], expected_generation=8)
    store.begin_phase(
        action["action_id"], attempt["attempt_id"], phase_id="approach",
        ordinal=0, command_digest="a" * 64,
    )

    with pytest.raises(ValueError, match="cannot have a driver_goal_id"):
        store.record_first_phase_submission(
            action["action_id"], attempt["attempt_id"], phase_id="approach",
            accepted=accepted, driver_goal_id="unverified-goal",
        )


def test_phase_goal_identity_and_order_are_fenced(tmp_path):
    store = ActionStore(tmp_path / "actions.sqlite3")
    action_id, attempt_id = start_running(store)
    store.begin_phase(action_id, attempt_id, phase_id="approach", ordinal=0,
                      command_digest="a" * 64)
    store.record_phase_submission(action_id, attempt_id, phase_id="approach",
                                  accepted=True, driver_goal_id="ros-goal-1")

    with pytest.raises(InvalidActionTransition):
        store.begin_phase(action_id, attempt_id, phase_id="grasp", ordinal=1,
                          command_digest="b" * 64)
    with pytest.raises(InvalidActionTransition):
        store.record_phase_terminal(
            action_id, attempt_id, phase_id="approach", driver_goal_id="other-goal",
            outcome="SUCCEEDED", result_source="ros-action-result",
            result_observed_at="2026-09-30T10:00:00Z", result={"status": 4},
        )
    with pytest.raises(InvalidActionTransition):
        store.begin_phase(action_id, attempt_id, phase_id="approach", ordinal=1,
                          command_digest="b" * 64)


def test_restart_marks_inflight_phase_unknown_without_replaying_it(tmp_path):
    path = tmp_path / "actions.sqlite3"
    store = ActionStore(path)
    action_id, attempt_id = start_running(store)
    store.begin_phase(action_id, attempt_id, phase_id="approach", ordinal=0,
                      command_digest="a" * 64)
    store.record_phase_submission(action_id, attempt_id, phase_id="approach",
                                  accepted=True, driver_goal_id="ros-goal-1")
    store.request_phase_cancel(action_id, attempt_id, phase_id="approach")

    recovered = ActionStore(path)
    assert recovered.recover_after_restart() == [action_id]
    phase = recovered.action_phases(action_id)[0]
    assert phase["state"] == "UNKNOWN"
    assert phase["driver_goal_id"] == "ros-goal-1"
    late_ack = recovered.record_phase_cancel_ack(
        action_id, attempt_id, phase_id="approach", acknowledged=True,
    )
    assert late_ack["state"] == "UNKNOWN"
    assert late_ack["cancel_acknowledged"] is True
    with pytest.raises(InvalidActionTransition):
        recovered.begin_phase(action_id, attempt_id, phase_id="approach", ordinal=0,
                              command_digest="a" * 64)


def test_phase_cancel_ack_is_not_terminal_and_requires_matching_goal_result(tmp_path):
    store = ActionStore(tmp_path / "actions.sqlite3")
    action_id, attempt_id = start_running(store)
    store.begin_phase(action_id, attempt_id, phase_id="transfer", ordinal=0,
                      command_digest="c" * 64)
    store.record_phase_submission(action_id, attempt_id, phase_id="transfer",
                                  accepted=True, driver_goal_id="ros-goal-transfer")
    store.mark_phase_running(action_id, attempt_id, phase_id="transfer",
                             driver_goal_id="ros-goal-transfer")
    store.request_phase_cancel(action_id, attempt_id, phase_id="transfer")
    acknowledged = store.record_phase_cancel_ack(
        action_id, attempt_id, phase_id="transfer", acknowledged=True,
    )

    assert acknowledged["state"] == "CANCEL_REQUESTED"
    assert acknowledged["cancel_acknowledged"] is True
    with pytest.raises(InvalidActionTransition):
        store.record_phase_terminal(
            action_id, attempt_id, phase_id="transfer", driver_goal_id="another-goal",
            outcome="CANCELED", result_source="ros-action-result",
            result_observed_at="2026-09-30T10:00:00Z", result={"status": 5},
        )
    canceled = store.record_phase_terminal(
        action_id, attempt_id, phase_id="transfer", driver_goal_id="ros-goal-transfer",
        outcome="CANCELED", result_source="ros-action-result",
        result_observed_at="2026-09-30T10:00:01Z", result={"status": 5},
    )
    assert canceled["state"] == "CANCELED"


def test_action_schema_v1_database_upgrades_additively_to_phase_ledger_v2(tmp_path):
    path = tmp_path / "actions.sqlite3"
    store = ActionStore(path)
    action = create(store)["action"]
    with store._connect() as connection:
        connection.execute("DROP TABLE omx_action_phases")
        connection.execute("PRAGMA user_version=1")

    upgraded = ActionStore(path)
    with upgraded._connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'",
        )}
    assert "omx_actions" in tables
    assert "omx_action_events" in tables
    assert "omx_action_phases" in tables
    assert upgraded.get_action(action["action_id"])["state"] == "PREPARED"


def test_phase_receipt_state_and_event_share_one_snapshot_during_a_writer_update(tmp_path, monkeypatch):
    store = ActionStore(tmp_path / "actions.sqlite3")
    writer = ActionStore(store.path)
    action_id, attempt_id = start_running(store)
    store.begin_phase(action_id, attempt_id, phase_id="approach", ordinal=0, command_digest="a" * 64)
    store.record_phase_submission(action_id, attempt_id, phase_id="approach",
                                  accepted=True, driver_goal_id="ros-goal-1")
    before = store.action_phase_receipts(action_id, attempt_id)[0]
    original_connect = store._connect
    changed = []

    class Cursor:
        def __init__(self, cursor):
            self.cursor = cursor

        def fetchall(self):
            rows = self.cursor.fetchall()
            if not changed:
                changed.append(True)
                writer.mark_phase_running(action_id, attempt_id, phase_id="approach",
                                          driver_goal_id="ros-goal-1")
            return rows

    class Connection:
        def __init__(self):
            self.connection = original_connect()

        def execute(self, query, *args):
            cursor = self.connection.execute(query, *args)
            return Cursor(cursor) if "SELECT * FROM omx_action_phases" in query else cursor

        def close(self):
            self.connection.close()

    monkeypatch.setattr(store, "_connect", Connection)
    observed = store.action_phase_receipts(action_id, attempt_id)[0]
    assert changed == [True]
    assert observed == before
    assert writer.action_phase_receipts(action_id, attempt_id)[0]["state"] == "RUNNING"
