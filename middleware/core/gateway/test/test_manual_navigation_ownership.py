"""D-442 U1: autonomous requests must not take a live manual session."""

import pytest
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from core_features.command.arbitration import Mode
from core_features.command.manager import Twist


OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}


@pytest.mark.parametrize("path,body", [
    ("/api/v1/navigation/goal", {"x": 1.0, "y": 0.5}),
    ("/api/v1/navigation/goal", {"x": 1.0, "y": 0.5,
                                "correlation_id": "fleet-manual-conflict"}),
    ("/api/v1/mode", {"mode": "NAVIGATION"}),
    ("/api/v1/swarm/follow", {"target_robot_id": "rosy_02", "distance": 0.5}),
])
def test_autonomy_refuses_live_manual_without_taking_output(core_client, path, body):
    client, svc = core_client()
    sent = []

    class Executor:
        def send_goal(self, spec, **kwargs):
            sent.append(spec)

        def cancel_goal(self):
            pass

    svc.nav.executor = Executor()
    assert svc.modes.transition(Mode.MANUAL)[0]
    assert svc.command.teleop(0.1, 0.0)[0]
    assert svc.command.manual_active
    response = client.post(path, json=body, headers=OPERATOR)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MODE_CONFLICT"
    assert svc.modes.mode is Mode.MANUAL
    assert svc.command.manual_active
    assert svc.command.select_output() == Twist(0.1, 0.0)
    assert sent == []
    assert not svc.swarm.active


@pytest.mark.parametrize("release", ["clear", "expire"])
def test_mode_machine_refuses_navigation_until_manual_session_ends(core_client, monkeypatch, release):
    _, svc = core_client()
    assert svc.modes.transition(Mode.MANUAL)[0]
    assert svc.command.teleop(0.1, 0.0)[0]
    assert not svc.modes.can_transition(Mode.NAVIGATION)
    assert not svc.modes.transition(Mode.NAVIGATION)[0]
    if release == "clear":
        svc.command.clear_manual()
    else:
        expired_at = svc.command.watchdog._last_refresh + 1.0
        monkeypatch.setattr("core_features.safety.manager.time.monotonic", lambda: expired_at)
    assert not svc.command.manual_active
    assert svc.modes.can_transition(Mode.NAVIGATION)
    assert svc.modes.transition(Mode.NAVIGATION)[0]


@pytest.mark.parametrize("target", [Mode.IDLE, Mode.EMERGENCY])
def test_stop_can_always_leave_live_manual(core_client, target):
    _, svc = core_client()
    assert svc.modes.transition(Mode.MANUAL)[0]
    assert svc.command.teleop(0.1, 0.0)[0]
    assert svc.modes.transition(target)[0]


def test_teleop_cannot_commit_after_navigation_took_an_expired_session(core_client, monkeypatch):
    _, svc = core_client()
    assert svc.modes.transition(Mode.MANUAL)[0]
    entered, proceed = Event(), Event()
    original_clip = svc.safety.clip

    def paused_clip(*args, **kwargs):
        entered.set()
        assert proceed.wait(5)
        return original_clip(*args, **kwargs)

    monkeypatch.setattr(svc.safety, "clip", paused_clip)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(svc.command.teleop, 0.1, 0.0)
        try:
            assert entered.wait(5)
            assert svc.modes.transition(Mode.NAVIGATION)[0]
        finally:
            proceed.set()
        assert pending.result(timeout=5) == (False, "MODE_CONFLICT")
    assert svc.modes.mode is Mode.NAVIGATION
    assert not svc.command.manual_active


def test_line_follow_refusal_preserves_navigation_state(core_client, monkeypatch):
    client, svc = core_client()
    cancelled = []
    monkeypatch.setattr(svc.nav, "cancel", lambda **kwargs: cancelled.append(kwargs))
    assert svc.modes.transition(Mode.MANUAL)[0]
    assert svc.command.teleop(0.1, 0.0)[0]
    response = client.put("/api/v1/line-follow/mode", json={"mode": "IR_LINE"}, headers=OPERATOR)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MODE_CONFLICT"
    assert cancelled == []
    assert svc.modes.mode is Mode.MANUAL
