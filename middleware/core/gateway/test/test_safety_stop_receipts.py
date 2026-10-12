"""The actual bodyless safety route captures native owners before its listeners run."""

from uuid import UUID, uuid4

import pytest

from core_features.command.arbitration import Mode
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


@pytest.mark.parametrize("missing", ["pruned", "reboot", "later_owner"])
def test_safety_stop_never_substitutes_unknown_or_later_identity(core_client, monkeypatch, missing):
    client, services = core_client()
    services.modes.transition(Mode.MANUAL)
    services.command.teleop(0.1, 0)
    captured = services.command.native_readback()["operation"]
    readback = services.command.native_readback

    def changed_readback(run_id=None):
        view = readback(run_id)
        if run_id is not None:
            if missing == "pruned":
                view.update(operation=None, lookup="UNKNOWN", quiescence=None)
            else:
                field = "boot_id" if missing == "reboot" else "run_id"
                view["operation"][field] = str(uuid4())
        return view

    monkeypatch.setattr(services.command, "native_readback", changed_readback)
    response = client.post("/api/v1/safety/stop", headers=VIEWER)
    assert response.json()["operations"] == [captured]
    assert services.safety.estop


def test_failed_owner_capture_cannot_block_safety_latch(core_client, monkeypatch):
    client, services = core_client()

    def unavailable(run_id=None):
        raise RuntimeError("owner readback unavailable")

    monkeypatch.setattr(services.nav, "native_readback", unavailable)
    response = client.post("/api/v1/safety/stop", headers=VIEWER)
    assert response.status_code == 200
    assert response.json() == {"estop": True, "operations": []}
    assert services.safety.estop and services.modes.mode is Mode.EMERGENCY
