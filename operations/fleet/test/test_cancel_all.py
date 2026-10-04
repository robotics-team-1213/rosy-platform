"""D-421 전체 주행 취소 — 래치 없는 사이트 fanout. 네트워크 없이 가짜 로봇으로 돈다."""

from __future__ import annotations

import asyncio
import sqlite3
from hashlib import sha256

from fastapi.testclient import TestClient

from fakes import FakeClock, FakeRobot, run, settle
from fleet.server.app import create_app
from fleet.server.cancel_all import (
    CANCEL_ALL_REASON,
    DISPATCH_OVERLAP_REASON,
    DriveCancelFence,
    cancel_all_driving,
)
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import RobotApiError

DRIVING_CALLS = [("swarm_cancel",), ("navigation_cancel",), ("line_follow_mode", "OFF")]
LATCHING = {"estop", "safety_release", "mode"}


def _console(*robots: FakeRobot) -> FleetConsole:
    endpoints = [RobotEndpoint(robot_id=r.robot_id, base_url=f"http://127.0.0.1:808{i}",
                               token="t") for i, r in enumerate(robots)]
    return FleetConsole(endpoints, list(robots), clock=FakeClock())


def _gone(*_args, **_kwargs):
    async def fail(*_a, **_k):
        raise ConnectionError("gone")
    return fail


def _service(tmp_path, *robot_ids: str) -> FleetTaskService:
    service = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"),
                               robot_ids=set(robot_ids))
    service.store.rearm_dispatch(expected_generation=1, actor_id="test-operator")
    return service


# --- fanout -------------------------------------------------------------------------


def test_every_robot_gets_swarm_navigation_and_line_follow_cancel_and_nothing_latching():
    robots = [FakeRobot("rosy_01"), FakeRobot("rosy_02")]
    result = run(cancel_all_driving(_console(*robots), None, DriveCancelFence(),
                                    actor_id="op"))

    assert result["cancelled"] == 2 and result["total"] == 2
    assert result["evidence"] == "CORE_REPLY_ONLY"
    for robot, row in zip(robots, result["robots"]):
        assert robot.calls == DRIVING_CALLS
        assert row["result"] == "cancelled"
        assert all(step["ok"] for step in row["steps"].values())
        assert not LATCHING & {call[0] for call in robot.calls}
    assert result["tasks"] == {"canceled": [], "error": None}


def test_an_unreachable_robot_does_not_stop_the_others():
    """닿지 않는 한 대 때문에 멈출 수 있었던 나머지가 계속 달리면 안 된다."""
    good, bad = FakeRobot("rosy_01"), FakeRobot("rosy_02")
    bad.swarm_cancel = _gone()
    bad.navigation_cancel = _gone()
    bad.line_follow_mode = _gone()
    result = run(cancel_all_driving(_console(good, bad), None, DriveCancelFence(),
                                    actor_id="op"))

    assert result["cancelled"] == 1
    assert good.calls == DRIVING_CALLS
    row = result["robots"][1]
    assert row["result"] == "unreachable"
    assert row["steps"]["navigation"]["error"]["reachable"] is False


def test_a_refusal_is_failed_and_the_later_steps_still_run():
    robot = FakeRobot("rosy_01")

    async def refuse():
        robot._record("navigation_cancel")
        raise RobotApiError("rosy_01", 409, "MODE_CONFLICT", "no")

    robot.navigation_cancel = refuse
    row = run(cancel_all_driving(_console(robot), None, DriveCancelFence(),
                                 actor_id="op"))["robots"][0]

    assert row["result"] == "failed"
    assert row["steps"]["navigation"]["error"]["code"] == "MODE_CONFLICT"
    assert row["steps"]["navigation"]["error"]["reachable"] is True
    assert ("line_follow_mode", "OFF") in robot.calls


def test_a_robot_reached_only_partly_is_failed_not_unreachable():
    robot = FakeRobot("rosy_01")
    robot.navigation_cancel = _gone()
    row = run(cancel_all_driving(_console(robot), None, DriveCancelFence(),
                                 actor_id="op"))["robots"][0]

    assert row["result"] == "failed"


def test_fleet_forgets_the_goal_only_of_a_robot_whose_cancel_was_answered():
    """응답 없는 대의 목표를 지우면 화면은 '아무 데도 안 간다'지만 실제로는 아직 간다."""
    good, bad = FakeRobot("rosy_01"), FakeRobot("rosy_02")
    console = _console(good, bad)
    run(console.goal("rosy_01", 1.0, 0.0))
    run(console.goal("rosy_02", 2.0, 0.0))
    bad.navigation_cancel = _gone()

    run(cancel_all_driving(console, None, DriveCancelFence(), actor_id="op"))
    rows = run(console.snapshot())["robots"]

    assert rows[0]["goal"] is None
    assert rows[1]["goal"] == {"x": 2.0, "y": 0.0, "yaw": 0.0}


def test_an_open_formation_is_stopped_before_any_robot_call():
    """릴레이가 참조를 계속 밀면 취소한 팔로워가 다시 달린다 — 대형을 먼저 푼다."""
    log: list = []
    robot = FakeRobot("rosy_01", log=log)
    console = _console(robot)
    console.formation_status = lambda: {"active": True, "state": "RUNNING"}

    async def stop():
        log.append(("formation", "stop"))
        return {"active": False, "state": "STOPPED"}

    console.formation_stop = stop
    result = run(cancel_all_driving(console, None, DriveCancelFence(), actor_id="op"))

    assert log[0] == ("formation", "stop")
    assert result["formation"] == {"stopped": True, "state": "STOPPED"}


def test_no_formation_is_reported_as_not_stopped():
    result = run(cancel_all_driving(_console(FakeRobot("rosy_01")), None, DriveCancelFence(),
                                    actor_id="op"))
    assert result["formation"] == {"stopped": False, "state": "IDLE"}


def test_hub_scatters_swarm_cancel_through_robot_rest():
    robot = FakeRobot("rosy_01")
    console = _console(robot)
    assert run(console.hub.scatter_swarm_cancel("rosy_01")) == {"active": False}
    assert robot.calls == [("swarm_cancel",)]


# --- Fleet tasks ----------------------------------------------------------------------


def test_queued_tasks_are_canceled_with_the_cancel_all_reason_and_no_dispatch_latch(tmp_path):
    robot = FakeRobot("rosy_01")
    service = _service(tmp_path, "rosy_01")
    console = _console(robot)
    before = service.store.dispatch_control()
    task = run(service.submit_navigation(robot_id="rosy_01", x=1, y=2, source="operator",
                                         actor_id="op", request_key="k1"))

    result = run(cancel_all_driving(console, service, DriveCancelFence(), actor_id="op-7"))

    assert result["tasks"] == {"canceled": [task["task_id"]], "error": None}
    stored = service.store.get_task(task["task_id"])
    assert stored["status"] == "CANCELED" and stored["reason"] == CANCEL_ALL_REASON
    last = service.store.history(task["task_id"])[-1]
    assert last["actor_id"] == "op-7" and last["reason"] == CANCEL_ALL_REASON
    after = service.store.dispatch_control()
    assert after["dispatch_enabled"] is True
    assert after["generation"] == before["generation"]


def test_a_dispatched_task_is_not_rewritten_and_is_listed_as_awaiting_core(tmp_path):
    robot = FakeRobot("rosy_01")
    service = _service(tmp_path, "rosy_01")
    task = run(service.submit_navigation(robot_id="rosy_01", x=1, y=2, source="operator",
                                         actor_id="op", request_key="k1"))

    async def accepted(_task):
        return {"accepted": True}

    run(service.dispatch_next({"rosy_01"}, dispatch=accepted))
    result = run(cancel_all_driving(_console(robot), service, DriveCancelFence(),
                                    actor_id="op"))

    assert service.store.get_task(task["task_id"])["status"] == "ACCEPTED"
    assert result["tasks"]["canceled"] == []
    assert result["robots"][0]["tasks"]["awaiting_core_result"] == [task["task_id"]]


def test_a_task_store_failure_is_reported_and_the_fanout_continues(tmp_path):
    robot = FakeRobot("rosy_01")
    service = _service(tmp_path, "rosy_01")

    def broken(**_kwargs):
        raise OSError("disk unavailable")

    service.cancel_all_queued = broken
    result = run(cancel_all_driving(_console(robot), service, DriveCancelFence(),
                                    actor_id="op"))

    assert result["tasks"]["error"] == "TASK_STORE_UNAVAILABLE"
    assert robot.calls == DRIVING_CALLS


def test_a_new_task_after_cancel_all_dispatches_normally(tmp_path):
    robot = FakeRobot("rosy_01")
    service = _service(tmp_path, "rosy_01")
    console, fence = _console(robot), DriveCancelFence()
    run(cancel_all_driving(console, service, fence, actor_id="op"))
    task = run(service.submit_navigation(robot_id="rosy_01", x=1, y=2, source="operator",
                                         actor_id="op", request_key="after"))

    run(service.dispatch_next({"rosy_01"}, dispatch=lambda t: fence.fenced_goal(console, t)))

    assert service.store.get_task(task["task_id"])["status"] == "ACCEPTED"


def test_a_dispatch_overlapping_cancel_all_is_canceled_again(tmp_path):
    """래치가 없으니, 막 집힌 작업이 취소 뒤에 출발하는 창을 울타리가 닫는다."""
    robot = FakeRobot("rosy_01")
    service = _service(tmp_path, "rosy_01")
    console, fence = _console(robot), DriveCancelFence()
    task = run(service.submit_navigation(robot_id="rosy_01", x=1, y=2, source="operator",
                                         actor_id="op", request_key="k1"))
    gate = asyncio.Event()
    original_goal = robot.navigation_goal

    async def slow_goal(*args, **kwargs):
        await gate.wait()
        return await original_goal(*args, **kwargs)

    robot.navigation_goal = slow_goal

    async def scenario():
        dispatch = asyncio.create_task(service.dispatch_next(
            {"rosy_01"}, dispatch=lambda t: fence.fenced_goal(console, t)))
        await settle()
        await cancel_all_driving(console, service, fence, actor_id="op")
        gate.set()
        return await dispatch

    run(scenario())

    stored = service.store.get_task(task["task_id"])
    assert stored["status"] == "UNKNOWN" and stored["reason"] == DISPATCH_OVERLAP_REASON
    names = [call[0] for call in robot.calls]
    assert names[names.index("navigation_goal"):].count("navigation_cancel") == 1


def test_fence_lets_a_dispatch_through_when_no_cancel_overlaps():
    robot = FakeRobot("rosy_01")
    console, fence = _console(robot), DriveCancelFence()
    task = {"robot_id": "rosy_01", "request": {"goal": {"x": 1.0, "y": 2.0, "yaw": 0.0}},
            "task_id": "t1", "attempt_id": "a1", "attempt_seq": 1}

    assert run(fence.fenced_goal(console, task)) == {"accepted": True}
    assert "navigation_cancel" not in [call[0] for call in robot.calls]


# --- HTTP surface ---------------------------------------------------------------------


def _app(tmp_path, *robots: FakeRobot, users=None):
    endpoints = [RobotEndpoint(r.robot_id, f"http://127.0.0.1:808{i}", "t")
                 for i, r in enumerate(robots)]
    service = _service(tmp_path, *(r.robot_id for r in robots))
    users = users or {sha256(b"operator-token").hexdigest(): {
        "principal_id": "operator-1", "role": "operator"}}
    client = TestClient(create_app(FleetConsole(endpoints, list(robots)),
                                   task_service=service, site_users=users,
                                   start_task_dispatcher=False))
    return client, service


OPERATOR = {"Authorization": "Bearer operator-token"}


def test_cancel_all_route_is_200_on_partial_failure_and_records_the_principal(tmp_path):
    good, bad = FakeRobot("rosy_01"), FakeRobot("rosy_02")
    bad.navigation_cancel = _gone()
    client, service = _app(tmp_path, good, bad)
    queued = client.post("/api/fleet/robots/rosy_01/goal", json={"x": 1, "y": 2},
                         headers={**OPERATOR, "Idempotency-Key": "q1"}).json()["task"]

    response = client.post("/api/fleet/cancel-all", headers=OPERATOR)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cancelled"] == 1 and body["total"] == 2
    assert [row["result"] for row in body["robots"]] == ["cancelled", "failed"]
    assert body["tasks"]["canceled"] == [queued["task_id"]]
    assert service.store.history(queued["task_id"])[-1]["actor_id"] == "operator-1"
    assert service.store.dispatch_control()["dispatch_enabled"] is True
    assert not any(call[0] == "estop" for call in good.calls + bad.calls)


def test_cancel_all_route_is_operator_only(tmp_path):
    robot = FakeRobot("rosy_01")
    client, _ = _app(tmp_path, robot, users={
        sha256(b"viewer-token").hexdigest(): {"principal_id": "alice", "role": "viewer"},
        sha256(b"policy-token").hexdigest(): {"principal_id": "carol", "role": "policy-admin"},
        sha256(b"operator-token").hexdigest(): {"principal_id": "bob", "role": "operator"},
    })

    assert client.post("/api/fleet/cancel-all").status_code == 401
    assert client.post("/api/fleet/cancel-all",
                       headers={"Authorization": "Bearer viewer-token"}).status_code == 403
    assert client.post("/api/fleet/cancel-all",
                       headers={"Authorization": "Bearer policy-token"}).status_code == 403
    assert robot.calls == []
    assert client.post("/api/fleet/cancel-all", headers=OPERATOR).status_code == 200


def test_cancel_all_keeps_the_normal_audit_gate(tmp_path, monkeypatch):
    """D-330 의 감사 예외는 전용 비상 정지 하나다. 그때도 비상 정지는 살아 있다."""
    robot = FakeRobot("rosy_01")
    client, service = _app(tmp_path, robot)

    def fail_audit(**_kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(service.store, "begin_api_audit", fail_audit)

    response = client.post("/api/fleet/cancel-all", headers=OPERATOR)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "AUDIT_STORAGE_UNAVAILABLE"
    assert robot.calls == []


def test_cancel_all_is_safe_to_repeat(tmp_path):
    robot = FakeRobot("rosy_01")
    client, _ = _app(tmp_path, robot)
    client.post("/api/fleet/robots/rosy_01/goal", json={"x": 1, "y": 2},
                headers={**OPERATOR, "Idempotency-Key": "q1"})

    first = client.post("/api/fleet/cancel-all", headers=OPERATOR).json()
    second = client.post("/api/fleet/cancel-all", headers=OPERATOR).json()

    assert len(first["tasks"]["canceled"]) == 1
    assert second["tasks"]["canceled"] == []
    assert second["cancelled"] == 1
    assert robot.calls == DRIVING_CALLS * 2


def test_cancel_all_works_without_a_task_store():
    robot = FakeRobot("rosy_01")
    client = TestClient(create_app(FleetConsole(
        [RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "t")], [robot])))

    body = client.post("/api/fleet/cancel-all").json()
    assert body["cancelled"] == 1
    assert body["tasks"] == {"canceled": [], "error": None}
    assert body["robots"][0]["tasks"] == {"awaiting_core_result": []}


def test_cancel_all_contract_is_documented_and_wired_to_the_console():
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    reference = (root / "docs/reference/ROSY API & Protocol Reference.md").read_text(encoding="utf-8")
    srs = (root / "docs/spec/ROSY FLEET SRS.md").read_text(encoding="utf-8")
    web = root / "operations/fleet/fleet/server/web"
    console_js = (web / "console.js").read_text(encoding="utf-8")
    index = (web / "index.html").read_text(encoding="utf-8")

    assert "| POST | `/api/fleet/cancel-all` | `operator` bearer | D-421" in reference
    assert "`FLEET_CANCEL_ALL_DURING_DISPATCH`" in reference and "CORE_REPLY_ONLY" in reference
    assert "D-421" in srs and "전체 주행 취소" in srs and "전체 비상 정지" in srs
    assert '"/api/fleet/cancel-all"' in console_js and "물리 정지 미확인" in console_js
    assert 'id="cancel-all"' in index and "전체 비상 정지" in index


# --- review round 1: CORE-evidenced release, fence edges, held robots -----------------


def _dispatched(service, robot_id="rosy_01", key="k1"):
    """Submit and dispatch one task with an accepted CORE receipt; return its row."""
    task = run(service.submit_navigation(robot_id=robot_id, x=1, y=2, source="operator",
                                         actor_id="op", request_key=key))

    async def accepted(_task):
        return {"accepted": True}

    run(service.dispatch_next({robot_id}, dispatch=accepted))
    return service.store.get_task(task["task_id"])


def _nav_canceled(service, task, event_id="ev-1", seq=1, source="api:operator",
                  event_type="nav.canceled"):
    data = {"correlation_id": task["attempt_id"]}
    if source is not None:
        data["source"] = source
    return service.project_core_event({
        "robot_id": task["robot_id"], "event_id": event_id, "seq": seq,
        "type": event_type, "data": data})


async def _accept_new(_task):
    return {"accepted": True}


def test_core_confirmed_cancel_releases_the_robot_for_new_work(tmp_path):
    """I1 probe: submit -> dispatch -> cancel-all -> nav.canceled -> a new task dispatches."""
    robot = FakeRobot("rosy_01")
    service = _service(tmp_path, "rosy_01")
    first = _dispatched(service)
    result = run(cancel_all_driving(_console(robot), service, DriveCancelFence(),
                                    actor_id="op-7"))
    assert result["robots"][0]["tasks"]["awaiting_core_result"] == [first["task_id"]]

    projected = _nav_canceled(service, first)
    assert projected["status"] == "HOLD" and projected["reason"] == CANCEL_ALL_REASON

    second = run(service.submit_navigation(robot_id="rosy_01", x=3, y=4, source="operator",
                                           actor_id="op", request_key="k2"))
    run(service.dispatch_next({"rosy_01"}, dispatch=_accept_new))
    assert service.store.get_task(second["task_id"])["status"] == "ACCEPTED"


def test_without_core_evidence_the_task_stays_and_the_robot_stays_claimed(tmp_path):
    robot = FakeRobot("rosy_01")
    service = _service(tmp_path, "rosy_01")
    first = _dispatched(service)
    run(cancel_all_driving(_console(robot), service, DriveCancelFence(), actor_id="op"))

    second = run(service.submit_navigation(robot_id="rosy_01", x=3, y=4, source="operator",
                                           actor_id="op", request_key="k2"))
    assert run(service.dispatch_next({"rosy_01"}, dispatch=_accept_new)) is None
    assert service.store.get_task(first["task_id"])["status"] == "ACCEPTED"
    assert service.store.get_task(second["task_id"])["status"] == "QUEUED"


def test_a_cancel_outside_any_cancel_all_window_stays_unknown(tmp_path):
    service = _service(tmp_path, "rosy_01")
    first = _dispatched(service)
    projected = _nav_canceled(service, first)
    assert projected["status"] == "UNKNOWN"
    assert projected["reason"] == "CORE_CANCEL_RESULT_PENDING"


def test_the_cancel_all_record_is_persisted_with_principal_robots_and_tasks(tmp_path):
    from fleet.server.cancel_all_store import record

    robot = FakeRobot("rosy_01")
    service = _service(tmp_path, "rosy_01")
    first = _dispatched(service)
    queued = run(service.submit_navigation(robot_id="rosy_01", x=3, y=4, source="operator",
                                           actor_id="op", request_key="k2"))
    result = run(cancel_all_driving(_console(robot), service, DriveCancelFence(),
                                    actor_id="op-7"))

    saved = record(service.store, result["cancel_all_id"])
    assert saved["principal_id"] == "op-7" and saved["robot_ids"] == ["rosy_01"]
    assert saved["opened_at"] <= saved["closed_at"]
    assert saved["canceled_task_ids"] == [queued["task_id"]]
    assert [row["task_id"] for row in saved["tagged_tasks"]] == [first["task_id"]]


def test_an_old_unknown_task_is_not_listed_as_awaiting_this_window(tmp_path):
    """I4: only ACCEPTED/RUNNING and UNKNOWN changed since the window opened."""
    import time

    robot = FakeRobot("rosy_01")
    service = _service(tmp_path, "rosy_01")
    task = run(service.submit_navigation(robot_id="rosy_01", x=1, y=2, source="operator",
                                         actor_id="op", request_key="old"))

    async def lost(_task):
        raise TimeoutError("reply lost")

    run(service.dispatch_next({"rosy_01"}, dispatch=lost))
    assert service.store.get_task(task["task_id"])["status"] == "UNKNOWN"
    time.sleep(0.02)
    result = run(cancel_all_driving(_console(robot), service, DriveCancelFence(),
                                    actor_id="op"))
    assert result["robots"][0]["tasks"]["awaiting_core_result"] == []


def _overlap(tmp_path, goal_impl):
    """Run one dispatch whose console.goal is `goal_impl(gate)`, with a cancel-all in between."""
    robot, other = FakeRobot("rosy_01"), FakeRobot("rosy_02")
    service = _service(tmp_path, "rosy_01", "rosy_02")
    console, fence = _console(robot, other), DriveCancelFence()
    task = run(service.submit_navigation(robot_id="rosy_01", x=1, y=2, source="operator",
                                         actor_id="op", request_key="k1"))
    gate = asyncio.Event()
    console.goal = goal_impl(console, gate)

    async def scenario():
        dispatch = asyncio.create_task(service.dispatch_next(
            {"rosy_01"}, dispatch=lambda t: fence.fenced_goal(console, t)))
        await settle()
        await cancel_all_driving(console, service, fence, actor_id="op")
        gate.set()
        return await dispatch

    run(scenario())
    return service, console, robot, other, service.store.get_task(task["task_id"])


def test_an_overlapping_goal_that_raises_is_still_canceled_again(tmp_path):
    """I2: a failed reply may still have reached CORE."""
    def goal_impl(console, gate):
        async def goal(*_a, **_k):
            await gate.wait()
            raise ConnectionError("reply lost after send")
        return goal

    service, _, robot, _, task = _overlap(tmp_path, goal_impl)
    assert robot.calls.count(("navigation_cancel",)) == 2      # fanout + fence re-cancel
    assert task["status"] == "UNKNOWN" and task["reason"] == "COMMAND_RESULT_UNKNOWN"
    assert _origins(service, task) == ["fence"]                # _recancel tagged it
    assert _nav_canceled(service, task)["status"] == "HOLD"


def test_an_overlapping_dispatch_also_recalls_a_robot_sent_to_a_bay_for_it(tmp_path):
    """I3: _make_room may have sent a yielder to a bay after the fanout."""
    def goal_impl(console, gate):
        async def goal(robot_id, *_a, **_k):
            await gate.wait()
            console._yielding["rosy_02"] = {"bay": {"x": 0.0, "y": 0.0}, "for": robot_id}
            return {"accepted": True}
        return goal

    _, console, _, other, task = _overlap(tmp_path, goal_impl)
    assert other.calls.count(("navigation_cancel",)) == 2
    assert "rosy_02" not in console._yielding
    assert task["reason"] == DISPATCH_OVERLAP_REASON


def test_an_overlapping_explicit_core_reject_is_failed_without_a_recancel(tmp_path):
    """M1: CORE refused the goal; nothing to cancel."""
    def goal_impl(console, gate):
        async def goal(*_a, **_k):
            await gate.wait()
            return {"accepted": False}
        return goal

    _, _, robot, _, task = _overlap(tmp_path, goal_impl)
    assert robot.calls.count(("navigation_cancel",)) == 1
    assert task["status"] == "FAILED" and task["reason"] == "COMMAND_REJECTED"


def test_an_overlapping_dispatch_left_in_fleets_own_queue_is_withdrawn(tmp_path):
    """M1: the console queued it without reaching CORE -> CANCELED, robot released."""
    def goal_impl(console, gate):
        async def goal(*_a, **_k):
            await gate.wait()
            return {"accepted": False, "queued": True, "dispatch_attempted": False,
                    "cancel_confirmed": False, "reason": "YIELDED"}
        return goal

    service, _, robot, _, task = _overlap(tmp_path, goal_impl)
    assert robot.calls.count(("navigation_cancel",)) == 1
    assert task["status"] == "CANCELED" and task["reason"] == CANCEL_ALL_REASON
    nxt = run(service.submit_navigation(robot_id="rosy_01", x=3, y=4, source="operator",
                                        actor_id="op", request_key="k2"))
    run(service.dispatch_next({"rosy_01"}, dispatch=_accept_new))
    assert service.store.get_task(nxt["task_id"])["status"] == "ACCEPTED"


def test_cancel_keeps_the_claim_of_a_held_robot():
    """I5: a D-361 held robot stays a blocked obstacle for traffic."""
    robot = FakeRobot("rosy_01")
    console = _console(robot)
    run(console.snapshot())
    console.hold_robot("rosy_01", "ADDRESS_CHANGED")
    claim = console._claims["rosy_01"]

    run(console.cancel("rosy_01"))
    assert console._claims["rosy_01"] == claim


def test_a_local_address_gate_refusal_is_reported_as_not_sent():
    """M2: the pinned-address gate refused locally; CORE never saw line-follow OFF."""
    robot = FakeRobot("rosy_01")

    async def gated(_mode):
        raise RobotApiError("rosy_01", 409, "ADDRESS_UNVERIFIED", "stop requests only")

    robot.line_follow_mode = gated
    row = run(cancel_all_driving(_console(robot), None, DriveCancelFence(),
                                 actor_id="op"))["robots"][0]
    error = row["steps"]["line_follow"]["error"]
    assert error == {"reachable": False, "sent": False, "code": "ADDRESS_UNVERIFIED",
                     "message": error["message"]}
    assert row["result"] == "failed"


# --- review round 2: event-before-tag race, attempt/source/grace matching -------------


def _origins(service, task):
    with sqlite3.connect(service.store.path) as connection:
        return [row[0] for row in connection.execute(
            "SELECT origin FROM fleet_cancel_all_tasks WHERE task_id=? AND attempt_id=?",
            (task["task_id"], task["attempt_id"]))]


def test_a_dispatch_started_mid_window_is_tagged_before_its_goal_call(tmp_path, caplog):
    """HIGH: CORE's nav.canceled for the window's own cancel can beat the goal reply."""
    robot = FakeRobot("rosy_01")
    service = _service(tmp_path, "rosy_01")
    console, fence = _console(robot), DriveCancelFence()
    gate_nav, gate_goal = asyncio.Event(), asyncio.Event()
    original_cancel = robot.navigation_cancel

    async def slow_cancel():
        await gate_nav.wait()
        return await original_cancel()

    async def goal(*_a, **_k):
        await gate_goal.wait()
        return {"accepted": True}

    robot.navigation_cancel = slow_cancel
    console.goal = goal

    async def scenario():
        window = asyncio.create_task(cancel_all_driving(console, service, fence, actor_id="op"))
        await settle()
        task = await service.submit_navigation(robot_id="rosy_01", x=1, y=2, source="operator",
                                               actor_id="op", request_key="mid")
        dispatch = asyncio.create_task(service.dispatch_next(
            {"rosy_01"}, dispatch=lambda t: fence.fenced_goal(console, t)))
        await settle()
        assert _nav_canceled(service, service.store.get_task(task["task_id"]))["status"] == "HOLD"
        gate_nav.set()
        await window
        gate_goal.set()
        await dispatch
        return task

    task = run(scenario())
    stored = service.store.get_task(task["task_id"])
    assert stored["status"] == "HOLD" and stored["reason"] == CANCEL_ALL_REASON
    assert "after HOLD(FLEET_CANCEL_ALL) ignored" in caplog.text
    assert run(service.submit_navigation(robot_id="rosy_01", x=3, y=4, source="operator",
                                         actor_id="op", request_key="next"))
    assert run(service.dispatch_next({"rosy_01"}, dispatch=_accept_new))["status"] == "ACCEPTED"


def test_tagging_after_the_event_settles_the_already_canceled_attempt(tmp_path):
    """HIGH (b): the event projected UNKNOWN before the tag; tagging applies the HOLD."""
    from fleet.server.cancel_all_store import open_record, tag_task

    service = _service(tmp_path, "rosy_01")
    first = _dispatched(service)
    opened = open_record(service.store, principal_id="op", robot_ids=[])
    assert _nav_canceled(service, first)["status"] == "UNKNOWN"

    tag_task(service.store, opened["cancel_all_id"], first["task_id"])
    assert service.store.get_task(first["task_id"])["status"] == "HOLD"
    assert run(service.submit_navigation(robot_id="rosy_01", x=3, y=4, source="operator",
                                         actor_id="op", request_key="next"))
    assert run(service.dispatch_next({"rosy_01"}, dispatch=_accept_new))["status"] == "ACCEPTED"


def test_a_later_cancel_of_an_unanswered_robot_is_not_this_windows(tmp_path):
    """MEDIUM: the window's cancel never reached the robot; a later cancel is someone else's."""
    robot = FakeRobot("rosy_01")
    robot.navigation_cancel = _gone()
    service = _service(tmp_path, "rosy_01")
    first = _dispatched(service)
    run(cancel_all_driving(_console(robot), service, DriveCancelFence(), actor_id="op"))

    projected = _nav_canceled(service, first, event_id="ev-later")
    assert projected["status"] == "UNKNOWN"
    assert projected["reason"] == "CORE_CANCEL_RESULT_PENDING"


def test_a_new_attempt_of_a_tagged_task_is_not_misattributed(tmp_path):
    robot = FakeRobot("rosy_01")
    service = _service(tmp_path, "rosy_01")
    first = _dispatched(service)
    run(cancel_all_driving(_console(robot), service, DriveCancelFence(), actor_id="op"))
    with sqlite3.connect(service.store.path) as connection:
        connection.execute("UPDATE fleet_tasks SET attempt_id='attempt-2' WHERE task_id=?",
                           (first["task_id"],))

    projected = _nav_canceled(service, {**first, "attempt_id": "attempt-2"})
    assert projected["status"] == "UNKNOWN"


def test_a_non_api_cancel_source_is_not_attributed_to_the_window(tmp_path):
    robot = FakeRobot("rosy_01")
    service = _service(tmp_path, "rosy_01")
    first = _dispatched(service)
    run(cancel_all_driving(_console(robot), service, DriveCancelFence(), actor_id="op"))
    assert _nav_canceled(service, first, source="line_stuck")["status"] == "UNKNOWN"


def test_a_cancel_after_the_grace_is_not_attributed(tmp_path, monkeypatch):
    from fleet.server import cancel_all_store

    robot = FakeRobot("rosy_01")
    service = _service(tmp_path, "rosy_01")
    first = _dispatched(service)
    run(cancel_all_driving(_console(robot), service, DriveCancelFence(), actor_id="op"))
    monkeypatch.setattr(cancel_all_store, "HOLD_GRACE_S", -1.0)
    assert _nav_canceled(service, first)["status"] == "UNKNOWN"


def test_a_late_correlated_event_after_hold_is_logged_not_applied(tmp_path, caplog):
    robot = FakeRobot("rosy_01")
    service = _service(tmp_path, "rosy_01")
    first = _dispatched(service)
    run(cancel_all_driving(_console(robot), service, DriveCancelFence(), actor_id="op"))
    assert _nav_canceled(service, first)["status"] == "HOLD"

    late = _nav_canceled(service, first, event_id="ev-2", seq=2, event_type="nav.completed")
    assert late["status"] == "HOLD"
    assert "after HOLD(FLEET_CANCEL_ALL) recorded, not applied" in caplog.text


def test_an_existing_journal_without_the_new_tables_gets_them(tmp_path):
    path = tmp_path / "fleet.sqlite3"
    FleetTaskStore(path)
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE fleet_cancel_all_tasks")
        connection.execute("DROP TABLE fleet_cancel_all")
    service = FleetTaskService(FleetTaskStore(path), robot_ids={"rosy_01"})
    result = run(cancel_all_driving(_console(FakeRobot("rosy_01")), service,
                                    DriveCancelFence(), actor_id="op"))
    assert result["cancel_all_id"] and result["record_error"] is None


def test_without_a_record_the_response_says_so_and_falls_back(tmp_path, monkeypatch):
    from fleet.server import cancel_all_store

    def broken(*_a, **_k):
        raise sqlite3.OperationalError("locked")

    robot = FakeRobot("rosy_01")
    service = _service(tmp_path, "rosy_01")
    first = _dispatched(service)
    monkeypatch.setattr(cancel_all_store, "open_record", broken)
    result = run(cancel_all_driving(_console(robot), service, DriveCancelFence(), actor_id="op"))

    assert result["cancel_all_id"] is None
    assert result["record_error"] == "CANCEL_ALL_RECORD_UNAVAILABLE"
    assert result["robots"][0]["tasks"]["awaiting_core_result"] == [first["task_id"]]
    assert robot.calls == DRIVING_CALLS


def test_old_closed_records_are_pruned_when_a_window_opens(tmp_path):
    from fleet.server.cancel_all_store import record

    robot = FakeRobot("rosy_01")
    service = _service(tmp_path, "rosy_01")
    _dispatched(service)
    old = run(cancel_all_driving(_console(robot), service, DriveCancelFence(), actor_id="op"))
    with sqlite3.connect(service.store.path) as connection:
        connection.execute("UPDATE fleet_cancel_all SET closed_at='2000-01-01T00:00:00.000+00:00'")
    new = run(cancel_all_driving(_console(robot), service, DriveCancelFence(), actor_id="op"))

    assert record(service.store, old["cancel_all_id"]) is None
    assert record(service.store, new["cancel_all_id"]) is not None
