"""Optional receipt capture never waits ahead of the real safety latch."""

import threading

import pytest

from core_features.command.arbitration import Mode
from test_safety_stop_receipts import VIEWER


@pytest.mark.parametrize("owner_name,lock_name", [
    ("nav", "_lock"), ("docking", "_lock"), ("swarm", "_lock"), ("command", "_native_lock"),
])
def test_contended_owner_does_not_delay_latch(core_client, monkeypatch, owner_name, lock_name):
    client, services = core_client()
    services.modes.transition(Mode.MANUAL)
    services.command.teleop(0.1, 0)
    latched = threading.Event()
    emit = services.safety._emit

    def observe_latch(name, *args, **kwargs):
        if name == "safety.estop":
            assert services.safety.estop
            latched.set()
        return emit(name, *args, **kwargs)

    monkeypatch.setattr(services.safety, "_emit", observe_latch)
    responses = []
    worker = threading.Thread(target=lambda: responses.append(
        client.post("/api/v1/safety/stop", headers=VIEWER)))
    lock = getattr(getattr(services, owner_name), lock_name)
    with lock:
        worker.start()
        reached_latch = latched.wait(2)
    worker.join(5)
    assert reached_latch, "optional owner capture blocked the safety latch"
    assert not worker.is_alive()
    assert responses[0].status_code == 200
    assert responses[0].json() == {"estop": True, "operations": []}
    assert services.safety.estop and services.modes.mode is Mode.EMERGENCY
    assert services.command.native.current.result == "CANCELED"


def test_post_latch_capture_does_not_wait_for_owner(core_client, monkeypatch):
    client, services = core_client()
    services.modes.transition(Mode.MANUAL)
    services.command.teleop(0.1, 0)
    captured = services.command.native_readback()["operation"]
    held, release = threading.Event(), threading.Event()

    def hold_owner():
        with services.command._native_lock:
            held.set()
            release.wait(5)

    holder = threading.Thread(target=hold_owner)
    original = services.safety.trigger_estop

    def latch_then_contend(source):
        result = original(source)
        holder.start()
        assert held.wait(2)
        return result

    monkeypatch.setattr(services.safety, "trigger_estop", latch_then_contend)
    responses = []
    worker = threading.Thread(target=lambda: responses.append(
        client.post("/api/v1/safety/stop", headers=VIEWER)))
    worker.start()
    assert held.wait(2)
    worker.join(2)
    finished = not worker.is_alive()
    release.set()
    holder.join(3)
    worker.join(3)
    assert finished, "optional post-latch receipt capture waited on an owner"
    assert responses[0].json()["operations"] == [captured]
    assert services.safety.estop
