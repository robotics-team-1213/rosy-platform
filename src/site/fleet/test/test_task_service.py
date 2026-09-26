from fakes import run
from fleet.hub.hub import HubError
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.transport import RobotApiError


def test_manual_navigation_is_durably_queued_before_any_robot_command(tmp_path):
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    service = FleetTaskService(store, robot_ids={"rosy_01"})
    dispatched = []

    task = run(service.submit_navigation(
        robot_id="rosy_01", x=1.25, y=-0.5, yaw=0.2,
        source="operator", actor_id="site-console", request_key="manual-1",
    ))

    assert task["task_id"]
    assert task["status"] == "QUEUED"
    assert task["source"] == "operator"
    assert task["actor_id"] == "site-console"
    assert task["request"]["goal"] == {"x": 1.25, "y": -0.5, "yaw": 0.2}
    assert task["receipt"] is None
    assert [row["status"] for row in store.history(task["task_id"])] == [
        "REQUESTED", "QUEUED",
    ]
    assert dispatched == []


def test_dispatcher_records_attempt_before_core_receipt_and_dispatches_once(tmp_path):
    service = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"),
                               robot_ids={"rosy_01"})
    queued = run(service.submit_navigation(
        robot_id="rosy_01", x=1.0, y=2.0, source="operator",
        actor_id="site-console", request_key="dispatch-1",
    ))
    attempts = []

    async def dispatch(task):
        attempts.append(task["attempt_id"])
        return {"accepted": True, "queued": False}

    accepted = run(service.dispatch_next({"rosy_01"}, dispatch=dispatch))
    empty = run(service.dispatch_next({"rosy_01"}, dispatch=dispatch))

    assert queued["status"] == "QUEUED"
    assert accepted["status"] == "ACCEPTED"
    assert accepted["attempt_id"] == attempts[0]
    assert accepted["attempt_seq"] == 1
    assert empty is None
    assert len(attempts) == 1


def test_policy_navigation_uses_same_validation_but_holds_before_dispatch(tmp_path):
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    service = FleetTaskService(store, robot_ids={"rosy_01"})
    dispatched = []

    async def dispatch():
        dispatched.append(True)
        return {"accepted": True}

    task = run(service.submit_navigation(
        robot_id="rosy_01", x=1.25, y=-0.5, yaw=0.2,
        source="policy", actor_id="policy:ceiling-north", request_key="e-7",
        evidence={"event_id": "e-7"},
    ))

    assert task["status"] == "HOLD"
    assert task["reason"] == "POLICY_NOT_ACCEPTED"
    assert task["evidence"] == {"event_id": "e-7"}
    assert [row["status"] for row in store.history(task["task_id"])] == [
        "REQUESTED", "HOLD",
    ]
    assert dispatched == []


def test_ambiguous_robot_timeout_records_unknown_and_never_retries(tmp_path):
    service = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"),
                               robot_ids={"rosy_01"})
    attempts = []

    async def dispatch():
        attempts.append(True)
        raise TimeoutError("response lost after request")

    run(service.submit_navigation(
        robot_id="rosy_01", x=1.0, y=2.0, yaw=0,
        source="operator", actor_id="site-console", request_key="timeout-1",
    ))
    task = run(service.dispatch_next({"rosy_01"}, dispatch=lambda _: dispatch()))

    assert task["status"] == "UNKNOWN"
    assert task["reason"] == "COMMAND_RESULT_UNKNOWN"
    assert [row["status"] for row in service.store.history(task["task_id"])] == [
        "REQUESTED", "QUEUED", "UNKNOWN",
    ]
    assert len(attempts) == 1


def test_definite_command_rejection_records_failed_without_storing_raw_error(tmp_path):
    service = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"),
                               robot_ids={"rosy_01"})

    async def dispatch():
        raise RobotApiError("rosy_01", 409, "FORMATION_ACTIVE", "private detail")

    task = run(service.submit_navigation(
        robot_id="rosy_01", x=1.0, y=2.0, yaw=0, source="operator",
        actor_id="site-console", request_key="rejected-1",
    ))
    task = run(service.dispatch_next({"rosy_01"}, dispatch=lambda _: dispatch()))

    assert task["status"] == "FAILED"
    assert task["reason"] == "COMMAND_REJECTED"
    assert "private detail" not in repr(task)


def test_local_hub_rejection_is_failed_without_claiming_unknown_dispatch(tmp_path):
    service = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"),
                               robot_ids={"rosy_01"})

    async def dispatch():
        raise HubError("FORMATION_ACTIVE", "formation is active")

    task = run(service.submit_navigation(
        robot_id="rosy_01", x=1.0, y=2.0, yaw=0, source="operator",
        actor_id="site-console", request_key="blocked-1",
    ))
    task = run(service.dispatch_next({"rosy_01"}, dispatch=lambda _: dispatch()))

    assert task["status"] == "FAILED"
    assert task["reason"] == "COMMAND_REJECTED"


def test_service_startup_recovers_interrupted_requested_task_as_unknown(tmp_path):
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    store.create_task(
        task_id="interrupted-task", robot_id="rosy_01", task_type="navigate",
        source="operator", actor_id="site-console", request_key="crash-1",
        request={"goal": {"x": 1.0, "y": 2.0, "yaw": 0.0}}, evidence=None,
    )

    FleetTaskService(store, robot_ids={"rosy_01"})
    task = store.get_task("interrupted-task")

    assert task["status"] == "UNKNOWN"
    assert task["reason"] == "PROCESS_RESTARTED_WITH_REQUESTED_TASK"
    assert [row["status"] for row in store.history("interrupted-task")] == [
        "REQUESTED", "UNKNOWN",
    ]


def test_policy_task_rejects_invalid_or_unknown_robot_before_policy_hold(tmp_path):
    service = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"),
                               robot_ids={"rosy_01"})

    try:
        run(service.submit_navigation(
            robot_id="rosy_99", x=1.0, y=2.0, yaw=0,
            source="policy", actor_id="policy:test", request_key="e-1",
            evidence={"event_id": "e-1"},
        ))
    except ValueError as exc:
        assert "UNKNOWN_ROBOT" in str(exc)
    else:
        raise AssertionError("the shared task validator must reject an unknown robot")


def test_same_idempotency_key_returns_existing_task_without_second_dispatch(tmp_path):
    service = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"),
                               robot_ids={"rosy_01"})
    attempts = []

    async def dispatch():
        attempts.append(True)
        return {"accepted": True}

    request = dict(robot_id="rosy_01", x=1.0, y=2.0, yaw=0,
                   source="operator", actor_id="site-console", request_key="ui-click-1")
    first = run(service.submit_navigation(**request))
    duplicate = run(service.submit_navigation(**request))

    assert duplicate["task_id"] == first["task_id"]
    assert first["status"] == duplicate["status"] == "QUEUED"
    assert len(attempts) == 0
