from fakes import run
import pytest
from fleet.hub.hub import HubError
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.transport import RobotApiError


def _service(database, robot_ids=("rosy_01",)):
    service = FleetTaskService(FleetTaskStore(database), robot_ids=set(robot_ids))
    state = service.store.dispatch_control()
    service.store.rearm_dispatch(expected_generation=state["generation"],
                                 actor_id="test-operator")
    return service


def test_manual_navigation_is_durably_queued_before_any_robot_command(tmp_path):
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    service = _service(store.path)
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


@pytest.mark.parametrize("error", [HubError("COMMAND_REJECTED", "bay admission changed"),
                                   RobotApiError("rosy_02", 409, "COMMAND_REJECTED", "bay refused")])
def test_bay_refusal_after_mover_send_keeps_task_unknown(tmp_path, monkeypatch, error):
    from fakes import FakeRobot
    from fleet.server.console import FleetConsole
    from fleet.swarm.robots import RobotEndpoint
    from fleet.server import console as console_module

    robot, other = FakeRobot("rosy_01"), FakeRobot("rosy_02")
    console = FleetConsole([RobotEndpoint(r.robot_id, "http://127.0.0.1", "t")
                            for r in (robot, other)], [robot, other])
    service = _service(tmp_path / "fleet.sqlite3")
    run(service.submit_navigation(robot_id="rosy_01", x=1.0, y=0.0, source="operator",
                                  actor_id="site-console", request_key="bay-refusal"))
    console._standing_in_the_way = lambda *_args: ["rosy_02"]
    console._pose_of = lambda _rid: (0.0, 0.0)
    monkeypatch.setattr(console_module.bays, "best_bay", lambda *_args, **_kw: (1.0, 1.0))

    async def refused(*_args):
        raise error

    console._send_to_bay = refused

    async def dispatch(attempt):
        return await console.goal("rosy_01", **attempt["request"]["goal"],
                                  task_id=attempt["task_id"], attempt_id=attempt["attempt_id"],
                                  attempt_seq=attempt["attempt_seq"])

    result = run(service.dispatch_next({"rosy_01"}, dispatch=dispatch))
    assert result["status"] == "UNKNOWN"
    assert result["reason"] == "COMMAND_RESULT_UNKNOWN"
    assert service.store.resource_claims(resource_kind="robot", resource_id="rosy_01")
    assert run(service.dispatch_next({"rosy_01"}, dispatch=dispatch)) is None
    assert len([call for call in robot.calls if call[0] == "navigation_goal"]) == 1


@pytest.mark.parametrize("stage", ["route_cancel", "trust_cancel", "observe", "lease_cancel"])
def test_post_acceptance_owner_errors_keep_task_unknown(tmp_path, stage):
    from fakes import FakeRobot
    from fleet.server.console import FleetConsole
    from fleet.swarm.robots import RobotEndpoint

    robot, other = FakeRobot("rosy_01"), FakeRobot("rosy_02")
    console = FleetConsole([RobotEndpoint(r.robot_id, "http://127.0.0.1", "t")
                            for r in (robot, other)], [robot, other])
    service = _service(tmp_path / "fleet.sqlite3")
    run(service.submit_navigation(robot_id="rosy_01", x=1.0, y=0.0, source="operator",
                                  actor_id="site-console", request_key=stage))

    async def failed_cancel():
        raise RobotApiError("rosy_01", 409, "COMMAND_REJECTED", "cancel not confirmed")

    robot.navigation_cancel = failed_cancel
    if stage == "route_cancel":
        robot._path = [(0.0, 0.0), (1.0, 0.0)]
        console._claims["rosy_02"] = list(robot._path)
    elif stage == "trust_cancel":
        console._untrusted_blocks = lambda *_args: True
    elif stage == "lease_cancel":
        original = robot.navigation_goal

        async def stopped_goal(*args, **kwargs):
            reply = await original(*args, **kwargs)
            try:
                await console.cancel("rosy_01")
            except RobotApiError:
                pass
            return reply

        robot.navigation_goal = stopped_goal
    else:
        async def failed_observe():
            raise HubError("UNKNOWN_ROBOT", "roster changed after send")

        console._observe = failed_observe

    async def dispatch(attempt):
        return await console.goal("rosy_01", **attempt["request"]["goal"],
                                  task_id=attempt["task_id"], attempt_id=attempt["attempt_id"])

    result = run(service.dispatch_next({"rosy_01"}, dispatch=dispatch))
    assert result["status"] == "UNKNOWN"
    assert service.store.resource_claims(resource_kind="robot", resource_id="rosy_01")
    assert run(service.dispatch_next({"rosy_01"}, dispatch=dispatch)) is None
    assert len([call for call in robot.calls if call[0] == "navigation_goal"]) == 1


def test_dispatcher_records_attempt_before_core_receipt_and_dispatches_once(tmp_path):
    service = _service(tmp_path / "fleet.sqlite3")
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


def test_correlated_core_events_project_only_the_current_attempt_result(tmp_path):
    service = _service(tmp_path / "fleet.sqlite3")
    queued = run(service.submit_navigation(
        robot_id="rosy_01", x=1.0, y=2.0, source="operator",
        actor_id="site-console", request_key="correlated-1",
    ))

    async def dispatch(_task):
        service.project_core_event({
            "robot_id": "rosy_01", "event_id": "result-started-1", "seq": 18,
            "type": "nav.started", "data": {"correlation_id": _task["attempt_id"]},
        })
        return {"accepted": False}

    accepted = run(service.dispatch_next({"rosy_01"}, dispatch=dispatch))
    event = {
        "robot_id": "rosy_01", "event_id": "result-started-1", "seq": 18,
        "type": "nav.started", "data": {"correlation_id": accepted["attempt_id"]},
    }
    running = service.project_core_event(event)
    duplicate = service.project_core_event(event)
    completed = service.project_core_event({
        **event, "event_id": "result-completed-1", "seq": 19,
        "type": "nav.completed",
    })
    stale = service.project_core_event({
        **event, "event_id": "result-started-old", "seq": 17,
    })
    wrong_robot = service.project_core_event({
        **event, "robot_id": "rosy_02", "event_id": "wrong-robot", "seq": 20,
    })

    assert accepted["status"] == "RUNNING"
    assert queued["task_id"] == accepted["task_id"]
    assert running["status"] == "RUNNING"
    assert duplicate["status"] == "RUNNING"
    assert completed["status"] == "COMPLETED"
    assert stale["status"] == "COMPLETED"
    assert wrong_robot is None
    assert [row["status"] for row in service.store.history(accepted["task_id"])] == [
        "REQUESTED", "QUEUED", "RUNNING", "COMPLETED",
    ]


def test_cancel_request_event_does_not_claim_a_final_action_result(tmp_path):
    service = _service(tmp_path / "fleet.sqlite3")
    run(service.submit_navigation(
        robot_id="rosy_01", x=1.0, y=2.0, source="operator",
        actor_id="site-console", request_key="cancel-not-final-1",
    ))

    async def dispatch(_task):
        return {"accepted": True}

    accepted = run(service.dispatch_next({"rosy_01"}, dispatch=dispatch))
    pending = service.project_core_event({
        "robot_id": "rosy_01", "event_id": "cancel-requested", "seq": 20,
        "type": "nav.canceled", "data": {"correlation_id": accepted["attempt_id"]},
    })
    assert pending["status"] == "UNKNOWN"
    assert pending["reason"] == "CORE_CANCEL_RESULT_PENDING"

    final = service.project_core_event({
        "robot_id": "rosy_01", "event_id": "cancel-result", "seq": 21,
        "type": "nav.failed", "data": {
            "correlation_id": accepted["attempt_id"], "error_code": "CANCELED",
        },
    })
    assert final["status"] == "FAILED"
    assert final["reason"] == "CORE_NAV_FAILED"


def test_task_waits_on_traffic_queue_and_only_retries_after_release_callback(tmp_path):
    service = _service(tmp_path / "fleet.sqlite3", ("rosy_01", "rosy_02"))
    run(service.submit_navigation(
        robot_id="rosy_01", x=1.0, y=2.0, source="operator",
        actor_id="site-console", request_key="traffic-1",
    ))
    replies = iter((
        {"accepted": False, "queued": True, "dispatch_attempted": True,
         "cancel_confirmed": True, "blocked_by": "rosy_02", "waiting_on": ["rosy_02"]},
        {"accepted": True},
    ))
    dispatched = []

    async def dispatch(task):
        dispatched.append(task["attempt_id"])
        return next(replies)

    waiting = run(service.dispatch_next({"rosy_01"}, dispatch=dispatch))
    no_retry = run(service.dispatch_next({"rosy_01"}, dispatch=dispatch))
    service.traffic_queue_released(waiting["task_id"])
    accepted = run(service.dispatch_next({"rosy_01"}, dispatch=dispatch))

    assert waiting["status"] == "QUEUED"
    assert waiting["dispatch_phase"] == "WAITING_TRAFFIC"
    assert waiting["blocked_by"] == "rosy_02"
    assert waiting["waiting_on"] == ["rosy_02"]
    assert no_retry is None
    assert accepted["status"] == "ACCEPTED"
    assert accepted["attempt_seq"] == 2
    assert dispatched[0] != dispatched[1]


def test_traffic_queue_without_confirmed_cancel_becomes_unknown_and_is_not_retried(tmp_path):
    service = _service(tmp_path / "fleet.sqlite3")
    run(service.submit_navigation(
        robot_id="rosy_01", x=1.0, y=2.0, source="operator",
        actor_id="site-console", request_key="traffic-uncertain-1",
    ))
    calls = []

    async def dispatch(task):
        calls.append(task["attempt_id"])
        return {"accepted": False, "queued": True, "dispatch_attempted": True,
                "cancel_confirmed": False}

    first = run(service.dispatch_next({"rosy_01"}, dispatch=dispatch))
    second = run(service.dispatch_next({"rosy_01"}, dispatch=dispatch))

    assert first["status"] == "UNKNOWN"
    assert first["reason"] == "TRAFFIC_CANCEL_UNCONFIRMED"
    assert second is None
    assert len(calls) == 1


def test_policy_navigation_uses_same_validation_but_holds_before_dispatch(tmp_path):
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    service = _service(store.path)
    dispatched = []

    async def dispatch():
        dispatched.append(True)
        return {"accepted": True}

    task = run(service.submit_navigation(
        robot_id="rosy_01", x=1.25, y=-0.5, yaw=0.2,
        source="policy", actor_id="policy:ceiling-north", request_key="e-7",
        evidence={"evidence_id": "ev-7"},
    ))

    assert task["status"] == "HOLD"
    assert task["reason"] == "EVIDENCE_NOT_CONFIGURED"
    assert task["evidence"] == {"evidence_id": "ev-7"}
    assert [row["status"] for row in store.history(task["task_id"])] == [
        "REQUESTED", "HOLD",
    ]
    assert dispatched == []


def test_ambiguous_robot_timeout_records_unknown_and_never_retries(tmp_path):
    service = _service(tmp_path / "fleet.sqlite3")
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
    service = _service(tmp_path / "fleet.sqlite3")

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
    service = _service(tmp_path / "fleet.sqlite3")

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

    _service(store.path)
    task = store.get_task("interrupted-task")

    assert task["status"] == "UNKNOWN"
    assert task["reason"] == "PROCESS_RESTARTED_WITH_REQUESTED_TASK"
    assert [row["status"] for row in store.history("interrupted-task")] == [
        "REQUESTED", "UNKNOWN",
    ]


def test_policy_task_rejects_invalid_or_unknown_robot_before_policy_hold(tmp_path):
    service = _service(tmp_path / "fleet.sqlite3")

    try:
        run(service.submit_navigation(
            robot_id="rosy_99", x=1.0, y=2.0, yaw=0,
            source="policy", actor_id="policy:test", request_key="e-1",
            evidence={"evidence_id": "ev-1"},
        ))
    except ValueError as exc:
        assert "UNKNOWN_ROBOT" in str(exc)
    else:
        raise AssertionError("the shared task validator must reject an unknown robot")


def test_same_idempotency_key_returns_existing_task_without_second_dispatch(tmp_path):
    service = _service(tmp_path / "fleet.sqlite3")
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
