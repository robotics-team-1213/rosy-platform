"""The actual bodyless safety route captures native owners before its listeners run."""

from uuid import UUID, uuid4
from types import SimpleNamespace

import pytest

from core_features.command.arbitration import Mode
from core_features.navigation.manager import NavGoalSpec
from core.bridge.goal_tracker import GoalTracker
from test_docking_mode_ownership import docking_robot, OPERATOR


VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}


@pytest.mark.parametrize("kind", ["teleop", "follow", "dock", "undock"])
def test_safety_stop_returns_actual_native_owner(core_client, kind):
    if kind in {"dock", "undock"}:
        client, services = docking_robot(core_client)
        if kind == "undock":
            services.docking._mark_docked()
            assert client.post("/api/v1/docking/undock", headers=OPERATOR).status_code == 200
        owner = services.docking
    else:
        client, services = core_client()
        if kind == "teleop":
            services.modes.transition(Mode.MANUAL)
            assert services.command.teleop(0.1, 0)[0]
            owner = services.command
        else:
            response = client.post("/api/v1/swarm/follow", headers=OPERATOR,
                                   json={"target_robot_id": "rosy_02", "distance": 0.5})
            assert response.status_code == 200, response.text
            owner = services.swarm
    original = owner.native_readback()["operation"]
    response = client.post("/api/v1/safety/stop", headers=VIEWER)
    assert response.status_code == 200, response.text
    assert response.json()["estop"] is True
    assert services.safety.estop and services.modes.mode is Mode.EMERGENCY
    operations = response.json()["operations"]
    assert len(operations) == 1
    stopped = operations[0]
    assert (stopped["run_id"], stopped["boot_id"], stopped["kind"]) == (
        original["run_id"], original["boot_id"], kind)
    assert (stopped["result"], stopped["reason"]) == ("CANCELED", "SAFETY_STOP")
    assert owner.native_readback(UUID(stopped["run_id"]))["operation"] == stopped
    # Repeating stop must not borrow an old, already terminal owner.
    assert client.post("/api/v1/safety/stop", headers=VIEWER).json()["operations"] == []


def test_safety_stop_empty_owner_is_only_ack(core_client):
    client, services = core_client()
    response = client.post("/api/v1/safety/stop", headers=VIEWER)
    assert response.json() == {"estop": True, "operations": []}
    assert services.safety.estop


@pytest.mark.parametrize("owner_name", ["nav", "docking", "swarm", "command"])
def test_missing_native_owner_still_runs_real_safety_latch(core_client, monkeypatch, owner_name):
    client, services = core_client()
    services.modes.transition(Mode.MANUAL)
    command = services.command
    assert command.teleop(0.1, 0)[0]
    monkeypatch.delattr(services, owner_name)
    response = client.post("/api/v1/safety/stop", headers=VIEWER)
    assert response.status_code == 200
    assert response.json() == {"estop": True, "operations": []}
    assert services.safety.estop and services.modes.mode is Mode.EMERGENCY
    assert command.native.current.result == "CANCELED"


@pytest.mark.parametrize("missing", ["pruned", "reboot", "later_owner"])
def test_safety_stop_never_substitutes_unknown_or_later_identity(core_client, monkeypatch, missing):
    client, services = core_client()
    services.modes.transition(Mode.MANUAL)
    services.command.teleop(0.1, 0)
    captured = services.command.native_readback()["operation"]
    capture = services.command.capture_native_operation

    def changed_readback(run_id=None):
        operation = capture(run_id)
        if run_id is not None:
            if missing == "pruned":
                return None
            else:
                field = "boot_id" if missing == "reboot" else "run_id"
                operation = operation.model_copy(update={field: uuid4()})
        return operation

    monkeypatch.setattr(services.command, "capture_native_operation", changed_readback)
    response = client.post("/api/v1/safety/stop", headers=VIEWER)
    assert response.json()["operations"] == [captured]
    assert services.safety.estop


def test_failed_owner_capture_cannot_block_safety_latch(core_client, monkeypatch):
    client, services = core_client()
    services.modes.transition(Mode.MANUAL)
    assert services.command.teleop(0.1, 0)[0]

    def unavailable(run_id=None):
        raise RuntimeError("owner readback unavailable")

    monkeypatch.setattr(services.nav, "capture_native_operation", unavailable)
    response = client.post("/api/v1/safety/stop", headers=VIEWER)
    assert response.status_code == 200
    assert response.json() == {"estop": True, "operations": []}
    assert services.safety.estop and services.modes.mode is Mode.EMERGENCY


@pytest.mark.parametrize("kind", ["navigate", "home"])
def test_safety_stop_keeps_multiple_owners_and_pending_transport(core_client, kind):
    client, services = core_client()
    tracker = GoalTracker()
    generation = tracker.opening()
    tracker.accepted(generation, object())
    services.nav.executor = SimpleNamespace(send_goal=lambda *args, **kw: None,
        cancel_goal=tracker.cancel_all, native_transport_snapshot=tracker.transport_snapshot)
    # Both real owner ledgers remain distinct even when their work overlaps.
    services.modes.transition(Mode.MANUAL)
    assert services.command.teleop(0.1, 0)[0]
    services.nav.goal(NavGoalSpec(1, 2, 0), kind=kind)
    expected = {services.command.native.current.run_id, services.nav.native.current.run_id}
    response = client.post("/api/v1/safety/stop", headers=VIEWER)
    operations = response.json()["operations"]
    assert {UUID(op["run_id"]) for op in operations} == expected
    assert {op["kind"] for op in operations} == {"teleop", kind}
    nav_id = services.nav.native.current.run_id
    pending = services.nav.native_readback(nav_id)
    assert pending["operation"]["result"] == "CANCELED"
    assert pending["quiescence"]["pending_submission"]
    assert not pending["quiescence"]["quiescent"]
    tracker.finished(generation)
    assert services.nav.native_readback(nav_id)["quiescence"]["quiescent"]


def test_safety_stop_preserves_first_terminal_racing_with_latch(core_client, monkeypatch):
    client, services = core_client()
    services.nav.executor = SimpleNamespace(send_goal=lambda *args, **kw: None, cancel_goal=lambda: None)
    services.nav.goal(NavGoalSpec(1, 2, 0))
    run_id = services.nav.native.current.run_id
    trigger = services.safety.trigger_estop

    def complete_then_latch(source):
        services.nav.on_result(True, native_run_id=run_id)
        return trigger(source)

    monkeypatch.setattr(services.safety, "trigger_estop", complete_then_latch)
    response = client.post("/api/v1/safety/stop", headers=VIEWER)
    operation, = response.json()["operations"]
    assert operation["run_id"] == str(run_id)
    assert operation["result"] == "SUCCEEDED"
    assert services.safety.estop


def test_safety_stop_failed_post_readback_retains_pending_identity(core_client, monkeypatch):
    client, services = core_client()
    services.modes.transition(Mode.MANUAL)
    services.command.teleop(0.1, 0)
    capture = services.command.capture_native_operation
    captured = capture().model_dump(mode="json")

    def failed_readback(run_id=None):
        if run_id is not None:
            raise RuntimeError("readback unavailable")
        return capture()

    monkeypatch.setattr(services.command, "capture_native_operation", failed_readback)
    assert client.post("/api/v1/safety/stop", headers=VIEWER).json()["operations"] == [captured]
