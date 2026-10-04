"""D-442 U1: autonomous requests must not take a live manual session."""

import pytest


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
    svc.state.set_velocity(0.0, 0.0)  # Host evidence prerequisite for the teleop API.
    # Admission tests keep the session alive independently of loaded host timing.
    # The separate expiry case checks the production 500 ms watchdog.
    svc.command.watchdog.timeout_ms = 60_000
    sent = []

    class Executor:
        def send_goal(self, spec, **kwargs):
            sent.append(spec)

        def cancel_goal(self):
            pass

    svc.nav.executor = Executor()
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OPERATOR).status_code == 200
    assert client.post("/api/v1/teleop", json={"linear": 0.1, "angular": 0.0}, headers=OPERATOR).status_code == 200
    assert svc.command.manual_active
    response = client.post(path, json=body, headers=OPERATOR)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MODE_CONFLICT"
    assert svc.modes.mode.value == "MANUAL"
    assert svc.command.manual_active
    out = svc.command.select_output()
    assert (out.linear, out.angular) == (0.1, 0.0)
    assert sent == []
    assert not svc.swarm.active


def test_line_follow_refusal_preserves_navigation_state(core_client, monkeypatch):
    client, svc = core_client()
    svc.state.set_velocity(0.0, 0.0)  # Host evidence prerequisite for the teleop API.
    svc.command.watchdog.timeout_ms = 60_000
    cancelled = []
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OPERATOR).status_code == 200
    assert client.post("/api/v1/teleop", json={"linear": 0.1, "angular": 0.0}, headers=OPERATOR).status_code == 200
    monkeypatch.setattr(svc.nav, "cancel", lambda **kwargs: cancelled.append(kwargs))
    response = client.put("/api/v1/line-follow/mode", json={"mode": "IR_LINE"}, headers=OPERATOR)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MODE_CONFLICT"
    assert cancelled == []
    assert svc.modes.mode.value == "MANUAL"
