"""Tests for named-operator reconciliation of UNKNOWN navigation tasks (D-1071)."""

from __future__ import annotations

from hashlib import sha256
import sqlite3
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from fakes import FakeRobot, run
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.task_reconcile_routes import quiescence_proof_ok
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint

USERS = {
    sha256(b"alice-token").hexdigest(): {"principal_id": "alice", "role": "operator"},
    sha256(b"bob-token").hexdigest(): {"principal_id": "bob", "role": "viewer"},
}
ALICE = {"Authorization": "Bearer alice-token"}
BOB = {"Authorization": "Bearer bob-token"}
SHARED = {"Authorization": "Bearer shared-token"}
ENDPOINT = RobotEndpoint("rosy_01", "http://robot.local", "rest-token")


class _Robot(FakeRobot):
    def __init__(self, robot_id: str, *, state: dict | None = None, nav_state=None) -> None:
        super().__init__(robot_id, state=state)
        self.nav_state = nav_state if nav_state is not None else _valid_nav_state()
        self.cancel_error: BaseException | None = None
        self.get_error: BaseException | None = None

    async def navigation_cancel(self) -> dict:
        self._record("navigation_cancel")
        if self.cancel_error is not None:
            raise self.cancel_error
        return {"canceled": True}

    async def _get(self, path: str) -> dict:
        self._record("get", path)
        if self.get_error is not None:
            raise self.get_error
        return self.nav_state(path) if callable(self.nav_state) else dict(self.nav_state)


def _valid_nav_state(*, boot_id: str = "boot-1") -> dict:
    return {
        "lookup": "FOUND",
        "navigation": "IDLE",
        "owner": {"boot_id": boot_id, "owner_generation": 3, "owner_run_id": None},
        "quiescence": {
            "boot_id": boot_id,
            "requested_run_id": "run-prev",
            "owner_run_id": None,
            "owner_generation": 3,
            "transport_generation": 5,
            "observed_at": "2026-11-22T03:10:00Z",
            "admitting": False,
            "pending_submission": False,
            "actuating_callback": False,
            "lease_active": False,
            "quiescent": True,
        },
        "operation": {
            "run_id": "run-prev",
            "boot_id": boot_id,
            "kind": "navigate",
            "correlation_id": "prev",
            "phase": "TERMINAL",
            "result": "CANCELED",
            "reason": None,
        },
    }


def _readback(operation: dict, *, result: str = "SUCCEEDED", quiescent: bool = True) -> dict:
    return {
        "lookup": "FOUND",
        "operation": operation | {"phase": "TERMINAL", "result": result},
        "owner": {"boot_id": operation["boot_id"], "owner_generation": 7, "owner_run_id": None},
        "quiescence": {
            "boot_id": operation["boot_id"],
            "requested_run_id": operation["run_id"],
            "owner_run_id": None,
            "owner_generation": 7,
            "transport_generation": 11,
            "observed_at": "2026-11-22T03:10:00Z",
            "admitting": False,
            "pending_submission": False,
            "actuating_callback": False,
            "lease_active": False,
            "quiescent": quiescent,
        },
    }


def _claim_counts(store: FleetTaskStore, robot_id: str = "rosy_01") -> tuple[int, int]:
    with sqlite3.connect(store.path) as conn:
        claims = conn.execute(
            "SELECT COUNT(*) FROM fleet_action_claims WHERE resource_key = ?",
            (f"robot:{robot_id}",),
        ).fetchone()[0]
        reservations = conn.execute(
            "SELECT COUNT(*) FROM fleet_robot_reservations WHERE robot_id = ?",
            (robot_id,),
        ).fetchone()[0]
    return int(claims), int(reservations)


def _setup_app(tmp_path, *, robot=None, console_token=None, users=USERS):
    robot = robot or _Robot("rosy_01")
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    service = FleetTaskService(store, robot_ids={"rosy_01"})
    console = FleetConsole([ENDPOINT], [robot])
    app = create_app(
        console,
        site_users=users,
        console_token=console_token,
        task_service=service,
        start_task_dispatcher=False,
    )
    return app, service, store, robot, TestClient(app)


def _create_unbound_unknown_task(client, service, store, robot):
    gen = store.dispatch_control()["generation"]
    assert client.post(
        "/api/fleet/dispatch/rearm", json={"expected_generation": gen}, headers=ALICE,
    ).status_code == 200
    created = client.post(
        "/api/fleet/robots/rosy_01/goal",
        json={"x": 1.0, "y": 2.0, "yaw": 0.0},
        headers=ALICE | {"Idempotency-Key": "reconcile-test-goal"},
    )
    assert created.status_code == 200
    task = created.json()["task"]

    async def timeout_dispatch(_attempt):
        raise TimeoutError("ambiguous goal send")

    dispatched = run(service.dispatch_next({"rosy_01"}, dispatch=timeout_dispatch))
    assert dispatched["status"] == "UNKNOWN"
    assert dispatched["reason"] == "COMMAND_RESULT_UNKNOWN"
    assert _claim_counts(store) == (1, 1)
    assert store.dispatch_control()["unresolved_actions"] == 1
    store.close_dispatch_for_startup()
    assert store.dispatch_control()["dispatch_enabled"] is False
    robot.calls.clear()
    return store.get_task(task["task_id"])


def test_reconcile_requires_named_operator_and_writes_api_audit(tmp_path):
    _, service, store, robot, client = _setup_app(tmp_path)
    task = _create_unbound_unknown_task(client, service, store, robot)
    # Set up via shared console token on a second client app shares store cleanly:
    shared_app = create_app(
        FleetConsole([ENDPOINT], [_Robot("rosy_01")]),
        console_token="shared-token",
        task_service=service,
        start_task_dispatcher=False,
    )
    shared_client = TestClient(shared_app)
    body = {"operator_confirmed": True, "expected_attempt_id": task["attempt_id"]}

    anon = client.post(f"/api/fleet/tasks/{task['task_id']}/reconcile", json=body)
    assert anon.status_code == 401

    viewer = client.post(f"/api/fleet/tasks/{task['task_id']}/reconcile", json=body, headers=BOB)
    assert viewer.status_code == 403
    assert viewer.json()["detail"]["code"] == "FORBIDDEN"

    shared = shared_client.post(
        f"/api/fleet/tasks/{task['task_id']}/reconcile", json=body, headers=SHARED,
    )
    assert shared.status_code == 403
    assert shared.json()["detail"]["code"] == "OPERATOR_IDENTITY_REQUIRED"

    ok = client.post(f"/api/fleet/tasks/{task['task_id']}/reconcile", json=body, headers=ALICE)
    assert ok.status_code == 200
    audit = store.api_audit(limit=5)
    assert any(
        row["principal_id"] == "alice"
        and row["method"] == "POST"
        and row["path"] == f"/api/fleet/tasks/{task['task_id']}/reconcile"
        and row["status_code"] == 200
        for row in audit
    )


def test_reconcile_rejects_invalid_payloads_missing_task_wrong_status_and_attempt_mismatch(tmp_path):
    _, service, store, _, client = _setup_app(tmp_path)
    task = _create_unbound_unknown_task(client, service, store, _Robot("rosy_01"))
    path = f"/api/fleet/tasks/{task['task_id']}/reconcile"

    for bad_body in (
        {"operator_confirmed": False, "expected_attempt_id": task["attempt_id"]},
        {"operator_confirmed": 1, "expected_attempt_id": task["attempt_id"]},
        {"operator_confirmed": True, "expected_attempt_id": task["attempt_id"], "extra": 1},
    ):
        assert client.post(path, json=bad_body, headers=ALICE).status_code == 422

    missing = client.post(
        "/api/fleet/tasks/no-such-task/reconcile",
        json={"operator_confirmed": True, "expected_attempt_id": "a1"},
        headers=ALICE,
    )
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "TASK_NOT_FOUND"

    mismatch = client.post(
        path,
        json={"operator_confirmed": True, "expected_attempt_id": "wrong-attempt"},
        headers=ALICE,
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["code"] == "ATTEMPT_MISMATCH"

    queued_created = store.create_task(
        task_id="queued-task", robot_id="rosy_02", task_type="NAV_GOAL",
        source="operator", actor_id="alice", request_key="queued-key",
        request={"x": 0.0, "y": 0.0, "yaw": 0.0}, evidence=None,
    )
    queued_id = queued_created["task"]["task_id"]
    store.enqueue(queued_id, priority_class=0)
    non_unknown = client.post(
        f"/api/fleet/tasks/{queued_id}/reconcile",
        json={"operator_confirmed": True, "expected_attempt_id": "a1"},
        headers=ALICE,
    )
    assert non_unknown.status_code == 409
    assert non_unknown.json()["detail"]["code"] == "TASK_NOT_UNKNOWN"
    assert _claim_counts(store) == (1, 1)


def test_reconcile_unbound_unknown_happy_path_clears_claim_and_allows_rearm(tmp_path):
    _, service, store, robot, client = _setup_app(tmp_path)
    task = _create_unbound_unknown_task(client, service, store, robot)

    gen = store.dispatch_control()["generation"]
    blocked_rearm = client.post(
        "/api/fleet/dispatch/rearm", json={"expected_generation": gen}, headers=ALICE,
    )
    assert blocked_rearm.status_code == 409

    res = client.post(
        f"/api/fleet/tasks/{task['task_id']}/reconcile",
        json={"operator_confirmed": True, "expected_attempt_id": task["attempt_id"]},
        headers=ALICE,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["reconciled"] is True
    assert data["evidence"] == "CORE_QUIESCENCE_PROOF"
    assert data["task"]["status"] == "HOLD"
    assert data["task"]["reason"] == "OPERATOR_RECONCILED_QUIESCENT"
    assert robot.calls == [("navigation_cancel",), ("get", "/api/v1/navigation/state")]
    assert _claim_counts(store) == (0, 0)

    ctl = store.dispatch_control()
    assert ctl["unresolved_actions"] == 0
    assert ctl["rearm_available"] is True

    rearmed = client.post(
        "/api/fleet/dispatch/rearm", json={"expected_generation": ctl["generation"]}, headers=ALICE,
    )
    assert rearmed.status_code == 200
    assert rearmed.json()["dispatch_enabled"] is True

    history = store.history(task["task_id"])
    assert history[-1]["status"] == "HOLD"
    assert history[-1]["actor_id"] == "alice"
    assert history[-1]["reason"] == "OPERATOR_RECONCILED_QUIESCENT"


def test_reconcile_zero_run_boot_idle_core_happy_path_and_fail_closed_variants(tmp_path):
    zero_run_idle = {
        "navigation": "IDLE",
        "owner": {"boot_id": "boot-zero", "owner_generation": 0, "owner_run_id": None},
        "operation": None,
        "lookup": "UNKNOWN",
        "quiescence": None,
    }
    _, service, store, robot, client = _setup_app(tmp_path, robot=_Robot("rosy_01", nav_state=zero_run_idle))
    task = _create_unbound_unknown_task(client, service, store, robot)
    path = f"/api/fleet/tasks/{task['task_id']}/reconcile"
    body = {"operator_confirmed": True, "expected_attempt_id": task["attempt_id"]}

    for bad_state in (
        {
            "navigation": "IDLE",
            "owner": {"boot_id": "boot-zero", "owner_generation": 1, "owner_run_id": None},
            "operation": {"phase": "TERMINAL"},
            "lookup": "FOUND",
            "quiescence": None,
        },
        zero_run_idle | {"navigation": "NAVIGATING"},
        zero_run_idle | {"navigation": "ARRIVED"},
        zero_run_idle | {"lookup": "FOUND"},
        {"navigation": "IDLE"},
    ):
        robot.nav_state = bad_state
        refused = client.post(path, json=body, headers=ALICE)
        assert refused.status_code == 409, bad_state
        assert refused.json()["detail"]["code"] == "ROBOT_NOT_QUIESCENT"
        assert store.get_task(task["task_id"])["status"] == "UNKNOWN"
        assert _claim_counts(store) == (1, 1)

    robot.nav_state = zero_run_idle
    ok = client.post(path, json=body, headers=ALICE)
    assert ok.status_code == 200
    data = ok.json()
    assert data["reconciled"] is True
    assert data["evidence"] == "CORE_QUIESCENCE_PROOF"
    assert data["task"]["status"] == "HOLD"
    assert data["quiescence"]["no_native_run_in_boot"] is True
    assert _claim_counts(store) == (0, 0)
    ctl = store.dispatch_control()
    assert ctl["unresolved_actions"] == 0
    assert client.post(
        "/api/fleet/dispatch/rearm", json={"expected_generation": ctl["generation"]}, headers=ALICE,
    ).status_code == 200


def test_reconcile_fail_closed_when_robot_unreachable_or_state_unavailable(tmp_path):
    _, service, store, robot, client = _setup_app(tmp_path)
    task = _create_unbound_unknown_task(client, service, store, robot)
    body = {"operator_confirmed": True, "expected_attempt_id": task["attempt_id"]}
    path = f"/api/fleet/tasks/{task['task_id']}/reconcile"

    robot.cancel_error = OSError("network down")
    unreachable = client.post(path, json=body, headers=ALICE)
    assert unreachable.status_code == 503
    assert unreachable.json()["detail"]["code"] == "ROBOT_UNREACHABLE"
    assert store.get_task(task["task_id"])["status"] == "UNKNOWN"
    assert _claim_counts(store) == (1, 1)

    robot.cancel_error = None
    robot.get_error = TimeoutError("state timeout")
    unavailable = client.post(path, json=body, headers=ALICE)
    assert unavailable.status_code == 503
    assert unavailable.json()["detail"]["code"] == "CORE_QUIESCENCE_UNAVAILABLE"
    assert store.get_task(task["task_id"])["status"] == "UNKNOWN"
    assert _claim_counts(store) == (1, 1)


def _bad_nav_state(case: str) -> dict:
    state = _valid_nav_state()
    if case == "not_quiescent":
        state["quiescence"]["quiescent"] = False
    elif case == "owner_run_id":
        state["owner"]["owner_run_id"] = "run-99"
    elif case == "quiescence_owner_run_id":
        state["quiescence"]["owner_run_id"] = "run-99"
    elif case == "admitting":
        state["quiescence"]["admitting"] = True
    elif case == "pending_submission":
        state["quiescence"]["pending_submission"] = True
    elif case == "actuating_callback":
        state["quiescence"]["actuating_callback"] = True
    elif case == "lease_active":
        state["quiescence"]["lease_active"] = True
    elif case == "navigating":
        state["navigation"] = "NAVIGATING"
    elif case == "planning":
        state["navigation"] = "PLANNING"
    elif case == "blocked":
        state["navigation"] = "BLOCKED"
    elif case == "navigation_missing":
        state.pop("navigation", None)
    elif case == "lookup_unknown":
        state["lookup"] = "UNKNOWN"
    elif case == "requested_run_mismatch":
        state["quiescence"]["requested_run_id"] = "run-other"
    elif case == "op_boot_mismatch":
        state["operation"]["boot_id"] = "boot-other"
    elif case == "op_missing":
        state["operation"] = None
    elif case == "operation_running":
        state["operation"] = {"phase": "RUNNING"}
    elif case == "boot_mismatch":
        state["quiescence"]["boot_id"] = "boot-2"
    elif case == "owner_gen_mismatch":
        state["quiescence"]["owner_generation"] = 99
    return state


@pytest.mark.parametrize("case", [
    "not_quiescent", "owner_run_id", "quiescence_owner_run_id",
    "admitting", "pending_submission", "actuating_callback", "lease_active",
    "navigating", "planning", "blocked", "navigation_missing",
    "lookup_unknown", "requested_run_mismatch", "op_boot_mismatch", "op_missing",
    "operation_running", "boot_mismatch", "owner_gen_mismatch",
])
def test_reconcile_fail_closed_when_robot_not_quiescent(tmp_path, case):
    _, service, store, robot, client = _setup_app(tmp_path)
    task = _create_unbound_unknown_task(client, service, store, robot)
    robot.nav_state = _bad_nav_state(case)

    res = client.post(
        f"/api/fleet/tasks/{task['task_id']}/reconcile",
        json={"operator_confirmed": True, "expected_attempt_id": task["attempt_id"]},
        headers=ALICE,
    )
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "ROBOT_NOT_QUIESCENT"
    assert store.get_task(task["task_id"])["status"] == "UNKNOWN"
    assert _claim_counts(store) == (1, 1)


def test_quiescence_proof_window_bounds():
    valid = _valid_nav_state()
    assert quiescence_proof_ok(valid, 0.0) is True
    assert quiescence_proof_ok(valid, 2.0) is True
    assert quiescence_proof_ok(valid, 2.01) is False
    assert quiescence_proof_ok(valid, -0.01) is False


def test_reconcile_bound_native_unknown_delegates_to_native_readback(tmp_path):
    _, service, store, robot, client = _setup_app(tmp_path)
    gen = store.dispatch_control()["generation"]
    assert client.post(
        "/api/fleet/dispatch/rearm", json={"expected_generation": gen}, headers=ALICE,
    ).status_code == 200
    created = client.post(
        "/api/fleet/robots/rosy_01/goal",
        json={"x": 1.0, "y": 2.0, "yaw": 0.0},
        headers=ALICE | {"Idempotency-Key": "native-unknown-goal"},
    )
    task_id = created.json()["task"]["task_id"]
    op = {
        "run_id": str(uuid4()),
        "boot_id": str(uuid4()),
        "kind": "navigate",
        "correlation_id": None,
        "phase": "SUBMITTED",
        "result": None,
        "reason": None,
    }

    async def accept_native(attempt):
        op["correlation_id"] = attempt["attempt_id"]
        return {"accepted": True, "operation": dict(op)}

    assert run(service.dispatch_next({"rosy_01"}, dispatch=accept_native))["status"] == "ACCEPTED"
    unknown = store.transition(
        task_id, "UNKNOWN", actor_id="fleet-runtime", source="fleet", reason="NAV_STALL",
    )
    store.trip_stop_latch(actor_id="fleet-runtime", reason="UNKNOWN_STOP")

    robot.get_error = TimeoutError("offline")
    unavailable = client.post(
        f"/api/fleet/tasks/{task_id}/reconcile",
        json={"operator_confirmed": True, "expected_attempt_id": unknown["attempt_id"]},
        headers=ALICE,
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["detail"]["code"] == "CORE_QUIESCENCE_UNAVAILABLE"
    assert store.get_task(task_id)["reason"] == "NAV_STALL"
    assert _claim_counts(store) == (1, 1)
    robot.get_error = None

    robot.nav_state = _readback(op, result="SUCCEEDED", quiescent=False)
    refused = client.post(
        f"/api/fleet/tasks/{task_id}/reconcile",
        json={"operator_confirmed": True, "expected_attempt_id": unknown["attempt_id"]},
        headers=ALICE,
    )
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "ROBOT_NOT_QUIESCENT"
    assert _claim_counts(store) == (1, 1)

    robot.nav_state = _readback(op, result="SUCCEEDED", quiescent=True)
    ok = client.post(
        f"/api/fleet/tasks/{task_id}/reconcile",
        json={"operator_confirmed": True, "expected_attempt_id": unknown["attempt_id"]},
        headers=ALICE,
    )
    assert ok.status_code == 200
    data = ok.json()
    assert data["reconciled"] is True
    assert data["evidence"] == "NATIVE_READBACK"
    assert data["task"]["status"] == "COMPLETED"
    assert data["task"]["receipt"]["safe_released"] is True
    assert _claim_counts(store) == (0, 0)
    ctl = store.dispatch_control()
    assert ctl["unresolved_actions"] == 0
    rearmed = client.post(
        "/api/fleet/dispatch/rearm", json={"expected_generation": ctl["generation"]}, headers=ALICE,
    )
    assert rearmed.status_code == 200
