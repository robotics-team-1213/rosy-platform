from fleet.server.task_store import FleetTaskStore, IdempotencyConflict, InvalidTaskTransition


def test_task_history_is_append_only_and_survives_reopen(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    store = FleetTaskStore(path)
    created = store.create_task(
        task_id="task-1", robot_id="rosy_01", task_type="navigate",
        source="operator", actor_id="site-console", request_key="click-1",
        request={"goal": {"x": 1.0, "y": 2.0, "yaw": 0.0}}, evidence=None,
    )
    assert created["created"] is True
    store.transition("task-1", "ACCEPTED", actor_id="site-console",
                     source="operator", receipt={"accepted": True})
    store.transition("task-1", "UNKNOWN", actor_id="site-console",
                     source="operator", reason="COMMAND_RESULT_UNKNOWN")

    restarted = FleetTaskStore(path)
    task = restarted.get_task("task-1")

    assert task["status"] == "UNKNOWN"
    assert [row["status"] for row in restarted.history("task-1")] == [
        "REQUESTED", "ACCEPTED", "UNKNOWN",
    ]
    assert task["receipt"] == {"accepted": True}


def test_idempotency_key_reuses_same_task_and_rejects_changed_intent(tmp_path):
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    args = dict(task_id="task-1", robot_id="rosy_01", task_type="navigate",
                source="operator", actor_id="site-console", request_key="click-1",
                request={"goal": {"x": 1.0, "y": 2.0, "yaw": 0.0}}, evidence=None)
    first = store.create_task(**args)

    duplicate = store.create_task(**{**args, "task_id": "task-2"})
    assert duplicate["created"] is False
    assert duplicate["task"]["task_id"] == first["task"]["task_id"]

    try:
        store.create_task(**{**args, "task_id": "task-3",
                             "request": {"goal": {"x": 9.0, "y": 2.0, "yaw": 0.0}}})
    except IdempotencyConflict:
        pass
    else:
        raise AssertionError("an idempotency key must not be reused for a different goal")


def test_illegal_task_transition_is_rejected(tmp_path):
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    store.create_task(task_id="task-1", robot_id="rosy_01", task_type="navigate",
                      source="operator", actor_id="site-console", request_key="click-1",
                      request={"goal": {"x": 1.0, "y": 2.0, "yaw": 0.0}}, evidence=None)
    try:
        store.transition("task-1", "COMPLETED", actor_id="site-console", source="operator")
    except InvalidTaskTransition:
        pass
    else:
        raise AssertionError("REQUESTED cannot skip acceptance or execution")


def test_task_store_refuses_credentials_and_oversized_evidence(tmp_path):
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    args = dict(task_id="task-safe", robot_id="rosy_01", task_type="navigate",
                source="operator", actor_id="site-console", request_key="safe-1",
                request={"goal": {"x": 1.0, "y": 2.0, "yaw": 0.0}})

    try:
        store.create_task(**args, evidence={"source": ({"access_token": "never-store"},)})
    except ValueError as exc:
        assert "credential fields" in str(exc)
    else:
        raise AssertionError("task evidence must not persist credentials")

    try:
        store.create_task(**args, evidence={"note": "x" * (64 * 1024)})
    except ValueError as exc:
        assert "64 KiB" in str(exc)
    else:
        raise AssertionError("task evidence size must remain bounded")
