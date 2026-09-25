"""D-143 operator API and composition-root contracts."""

from core_features.command.arbitration import Mode
from core_features.command.manager import Twist
from core_features.line_follow.manager import LineFollowMode, LineObservation


VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}
OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}


def test_line_follow_status_is_viewable_and_mode_change_requires_operator(core_client):
    client, services = core_client()

    initial = client.get("/api/v1/line-follow", headers=VIEWER)
    assert initial.status_code == 200
    assert initial.json()["mode"] == "OFF"
    assert client.put(
        "/api/v1/line-follow/mode", json={"mode": "IR_LINE"}, headers=VIEWER,
    ).status_code == 403

    enabled = client.put(
        "/api/v1/line-follow/mode", json={"mode": "IR_LINE"}, headers=OPERATOR,
    )
    assert enabled.status_code == 200
    assert enabled.json()["mode"] == "IR_LINE"
    assert enabled.json()["state"] == "WAITING"
    assert services.modes.mode is Mode.NAVIGATION
    assert services.command.select_output().linear == 0.0


def test_line_follow_mode_rejects_unknown_values_and_estop(core_client):
    client, services = core_client()
    assert client.put(
        "/api/v1/line-follow/mode", json={"mode": "FUSED"}, headers=OPERATOR,
    ).status_code == 400

    services.safety.trigger_estop("test")
    blocked = client.put(
        "/api/v1/line-follow/mode", json={"mode": "CAMERA_LINE"}, headers=OPERATOR,
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "EMERGENCY_ACTIVE"


def test_line_follow_status_is_in_the_robot_snapshot(core_client):
    client, services = core_client()
    client.put(
        "/api/v1/line-follow/mode", json={"mode": "CAMERA_LINE"}, headers=OPERATOR,
    )
    services.line_follow.observe(
        LineObservation(
            source=LineFollowMode.CAMERA_LINE,
            stamp=1.0,
            visible=True,
            error=0.25,
            confidence=0.9,
        )
    )
    services.line_follow.tick()
    services.state.set_line_follow(services.line_follow.status())

    snapshot = client.get("/api/v1/robot/state", headers=VIEWER).json()
    assert snapshot["line_follow"]["mode"] == "CAMERA_LINE"
    assert snapshot["line_follow"]["state"] == "TRACKING"
    assert snapshot["line_follow"]["error"] == 0.25


def test_mode_change_and_estop_disarm_line_follow_without_auto_resume(core_client):
    client, services = core_client()
    client.put(
        "/api/v1/line-follow/mode", json={"mode": "IR_LINE"}, headers=OPERATOR,
    )
    assert services.line_follow.active

    changed = client.post(
        "/api/v1/mode", json={"mode": "MANUAL"}, headers=OPERATOR,
    )
    assert changed.status_code == 200
    assert services.line_follow.mode is LineFollowMode.OFF

    client.put(
        "/api/v1/line-follow/mode", json={"mode": "IR_LINE"}, headers=OPERATOR,
    )
    services.safety.trigger_estop("test")
    assert services.line_follow.mode is LineFollowMode.OFF
    assert services.command.select_output() == Twist()


def test_turning_line_follow_off_returns_navigation_to_idle(core_client):
    client, services = core_client()
    client.put(
        "/api/v1/line-follow/mode", json={"mode": "IR_LINE"}, headers=OPERATOR,
    )
    disabled = client.put(
        "/api/v1/line-follow/mode", json={"mode": "OFF"}, headers=OPERATOR,
    )

    assert disabled.status_code == 200
    assert disabled.json()["mode"] == "OFF"
    assert services.modes.mode is Mode.IDLE


def test_off_does_not_cancel_an_unrelated_navigation_session(core_client):
    client, services = core_client()
    client.post("/api/v1/mode", json={"mode": "NAVIGATION"}, headers=OPERATOR)

    disabled = client.put(
        "/api/v1/line-follow/mode", json={"mode": "OFF"}, headers=OPERATOR,
    )

    assert disabled.status_code == 200
    assert services.modes.mode is Mode.NAVIGATION
