import sqlite3

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


def test_readback_reports_server_order_for_queued_tasks_only(tmp_path):
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    for task_id in ("background", "operator"):
        store.create_task(
            task_id=task_id, robot_id="rosy_01", task_type="navigate",
            source="operator", actor_id="site-console", request_key=task_id,
            request={"goal": {"x": 1.0, "y": 2.0, "yaw": 0.0}}, evidence=None,
        )
    store.enqueue("background", priority_class=2)
    store.enqueue("operator", priority_class=0)

    assert store.get_task("operator")["queue_position"] == 1
    assert store.get_task("background")["queue_position"] == 2
    store.claim_next(worker_id="dispatcher", available_robot_ids={"rosy_01"})
    assert store.get_task("operator")["queue_position"] is None


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


def test_existing_database_is_migrated_without_losing_task_history(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE fleet_tasks (
                task_id TEXT PRIMARY KEY, robot_id TEXT NOT NULL, task_type TEXT NOT NULL,
                source TEXT NOT NULL, actor_id TEXT NOT NULL, request_key TEXT NOT NULL,
                status TEXT NOT NULL, reason TEXT, request_json TEXT NOT NULL,
                evidence_json TEXT, receipt_json TEXT, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, UNIQUE(source, actor_id, request_key)
            );
            CREATE TABLE fleet_task_history (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL REFERENCES fleet_tasks(task_id), status TEXT NOT NULL,
                source TEXT NOT NULL, actor_id TEXT NOT NULL, reason TEXT, created_at TEXT NOT NULL
            );
            INSERT INTO fleet_tasks VALUES (
                'legacy', 'rosy_01', 'navigate', 'operator', 'site-console', 'legacy-1',
                'REQUESTED', NULL, '{"goal":{"x":1,"y":2,"yaw":0}}', NULL, NULL,
                '2026-09-01T00:00:00+00:00', '2026-09-01T00:00:00+00:00'
            );
            INSERT INTO fleet_task_history(task_id, status, source, actor_id, created_at)
            VALUES ('legacy', 'REQUESTED', 'operator', 'site-console', '2026-09-01T00:00:00+00:00');
        """)

    migrated = FleetTaskStore(path)
    task = migrated.get_task("legacy")
    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(fleet_tasks)")}

    assert task["status"] == "REQUESTED"
    assert [row["status"] for row in migrated.history("legacy")] == ["REQUESTED"]
    assert {"priority_class", "queued_at", "expires_at", "lease_owner",
            "lease_until", "dispatch_phase", "attempt_id", "attempt_seq",
            "blocked_by", "waiting_on_json"} <= columns


def test_queue_claim_obeys_priority_and_reserves_each_robot_once(tmp_path):
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    for task_id, robot_id, priority in (
        ("background", "rosy_01", 2),
        ("operator", "rosy_02", 0),
        ("accepted-policy", "rosy_03", 1),
    ):
        store.create_task(
            task_id=task_id, robot_id=robot_id, task_type="navigate",
            source="operator", actor_id="site-console", request_key=task_id,
            request={"goal": {"x": 1, "y": 2, "yaw": 0}}, evidence=None,
        )
        store.enqueue(task_id, priority_class=priority)

    first = store.claim_next(worker_id="worker-a", available_robot_ids={
        "rosy_01", "rosy_02", "rosy_03",
    })
    second = store.claim_next(worker_id="worker-b", available_robot_ids={
        "rosy_01", "rosy_02", "rosy_03",
    })

    assert first["task_id"] == "operator"
    assert second["task_id"] == "accepted-policy"
    assert second["robot_id"] != first["robot_id"]
    assert store.get_task("operator")["status"] == "QUEUED"


def test_dispatch_attempt_is_stable_and_restart_never_requeues_ambiguous_send(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    store = FleetTaskStore(path)
    store.create_task(
        task_id="dispatching", robot_id="rosy_01", task_type="navigate",
        source="operator", actor_id="site-console", request_key="dispatch-1",
        request={"goal": {"x": 1, "y": 2, "yaw": 0}}, evidence=None,
    )
    store.enqueue("dispatching", priority_class=0)
    store.claim_next(worker_id="worker-a", available_robot_ids={"rosy_01"})
    attempt = store.mark_dispatching("dispatching", worker_id="worker-a")

    restarted = FleetTaskStore(path)
    restarted.recover_interrupted_work()

    task = restarted.get_task("dispatching")
    assert task["status"] == "UNKNOWN"
    assert task["attempt_id"] == attempt["attempt_id"]
    assert task["attempt_seq"] == 1
    assert restarted.claim_next(worker_id="worker-b", available_robot_ids={"rosy_01"}) is None


def test_expired_pre_dispatch_lease_can_be_claimed_safely_again(tmp_path):
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    store.create_task(
        task_id="ready", robot_id="rosy_01", task_type="navigate",
        source="operator", actor_id="site-console", request_key="ready-1",
        request={"goal": {"x": 1, "y": 2, "yaw": 0}}, evidence=None,
    )
    store.enqueue("ready", priority_class=0)
    store.claim_next(worker_id="worker-a", available_robot_ids={"rosy_01"})
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "UPDATE fleet_tasks SET lease_until='2000-01-01T00:00:00+00:00' WHERE task_id='ready'"
        )

    reclaimed = store.claim_next(worker_id="worker-b", available_robot_ids={"rosy_01"})

    assert reclaimed["task_id"] == "ready"
    assert reclaimed["lease_owner"] == "worker-b"
    assert reclaimed["dispatch_phase"] == "READY"


def test_confirmed_traffic_cancel_holds_task_until_release_then_allows_new_attempt(tmp_path):
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    store.create_task(
        task_id="traffic", robot_id="rosy_01", task_type="navigate",
        source="operator", actor_id="site-console", request_key="traffic-1",
        request={"goal": {"x": 1, "y": 2, "yaw": 0}}, evidence=None,
    )
    store.enqueue("traffic", priority_class=0)
    store.claim_next(worker_id="worker-a", available_robot_ids={"rosy_01"})
    attempt = store.mark_dispatching("traffic", worker_id="worker-a")
    waiting = store.wait_for_traffic(
        "traffic", worker_id="worker-a", reason="ROUTE_CONFLICT", blocked_by="rosy_02",
        waiting_on=["rosy_02"], dispatch_attempted=True, cancel_confirmed=True,
    )

    assert waiting["status"] == "QUEUED"
    assert waiting["dispatch_phase"] == "WAITING_TRAFFIC"
    assert waiting["attempt_id"] == attempt["attempt_id"]
    assert waiting["blocked_by"] == "rosy_02"
    assert store.claim_next(worker_id="worker-b", available_robot_ids={"rosy_01"}) is None

    released = store.release_traffic_wait("traffic")
    claimed = store.claim_next(worker_id="worker-b", available_robot_ids={"rosy_01"})

    assert released["dispatch_phase"] == "READY"
    assert released["blocked_by"] is None
    assert claimed["task_id"] == "traffic"
    assert [row["status"] for row in store.history("traffic")] == [
        "REQUESTED", "QUEUED", "QUEUED", "QUEUED",
    ]


def test_queued_task_can_be_cancelled_without_core_command_or_cancelling_dispatch(tmp_path):
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    store.create_task(
        task_id="cancel-me", robot_id="rosy_01", task_type="navigate",
        source="operator", actor_id="site-console", request_key="cancel-1",
        request={"goal": {"x": 1, "y": 2, "yaw": 0}}, evidence=None,
    )
    store.enqueue("cancel-me", priority_class=0)
    canceled = store.cancel_queued("cancel-me", actor_id="site-console")
    replay = store.cancel_queued("cancel-me", actor_id="site-console")

    assert canceled["status"] == "CANCELED"
    assert replay["status"] == "CANCELED"
    assert store.claim_next(worker_id="worker", available_robot_ids={"rosy_01"}) is None

    store.create_task(
        task_id="dispatching-cannot-cancel", robot_id="rosy_02", task_type="navigate",
        source="operator", actor_id="site-console", request_key="cancel-2",
        request={"goal": {"x": 1, "y": 2, "yaw": 0}}, evidence=None,
    )
    store.enqueue("dispatching-cannot-cancel", priority_class=0)
    store.claim_next(worker_id="worker", available_robot_ids={"rosy_02"})
    store.mark_dispatching("dispatching-cannot-cancel", worker_id="worker")
    try:
        store.cancel_queued("dispatching-cannot-cancel", actor_id="site-console")
    except InvalidTaskTransition:
        pass
    else:
        raise AssertionError("an in-flight command cannot be canceled as a queued task")


def test_expiry_releases_only_tasks_that_are_confirmed_pre_dispatch(tmp_path):
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    for task_id in ("expired", "dispatching"):
        store.create_task(
            task_id=task_id, robot_id=f"{task_id}-robot", task_type="navigate",
            source="operator", actor_id="site-console", request_key=task_id,
            request={"goal": {"x": 1, "y": 2, "yaw": 0}}, evidence=None,
        )
        store.enqueue(
            task_id, priority_class=0,
            expires_at=None if task_id == "dispatching" else "2000-01-01T00:00:00+00:00",
        )
    store.claim_next(worker_id="worker", available_robot_ids={"dispatching-robot"})
    store.mark_dispatching("dispatching", worker_id="worker")
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "UPDATE fleet_tasks SET expires_at='2000-01-01T00:00:00+00:00' "
            "WHERE task_id='dispatching'"
        )

    store.claim_next(worker_id="worker-2", available_robot_ids={"expired-robot"})

    assert store.get_task("expired")["status"] == "EXPIRED"
    assert store.get_task("dispatching")["status"] == "QUEUED"
    assert store.get_task("dispatching")["dispatch_phase"] == "DISPATCHING"
