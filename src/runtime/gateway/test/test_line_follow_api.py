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


def test_ir_fallback_requires_confirmed_camera_hold_and_calibrated_control(core_client):
    revision = "a" * 64
    client, services = core_client(config_overrides={
        "line_follow": {"ir_calibration_revision": revision},
    })
    services.line_follow.set_mode(LineFollowMode.CAMERA_LINE)
    services.line_follow._status = services.line_follow.status().model_copy(
        update={"state": "LOST", "reason": "camera_reselection_required"}
    )

    blocked = client.put("/api/v1/line-follow/mode", json={"mode": "IR_LINE"}, headers=OPERATOR)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "IR_FALLBACK_NOT_READY"
    assert services.line_follow.mode is LineFollowMode.CAMERA_LINE

    services.control_adapter = type("Adapter", (), {
        "enabled": True, "calibration_revision": "ir-calibration-r1",
    })()
    services.safety.policy_required = True
    services.line_follow.observe(LineObservation(
        source=LineFollowMode.IR_LINE, stamp=1.0, visible=True,
        error=0.05, confidence=0.95, ir_calibrated=True,
        calibration_revision=revision,
    ))

    accepted = client.put("/api/v1/line-follow/mode", json={"mode": "IR_LINE"}, headers=OPERATOR)
    assert accepted.status_code == 200
    assert accepted.json()["mode"] == "IR_LINE"
    assert accepted.json()["state"] == "WAITING"
    assert services.command.select_output().linear == 0.0


def test_ir_fallback_refuses_missing_or_mismatched_line_calibration(core_client):
    revision = "b" * 64
    client, services = core_client(config_overrides={
        "line_follow": {"ir_calibration_revision": revision},
    })
    services.line_follow.bind_clock(lambda: 1.0)  # isolate revision refusal from HTTP scheduling age
    services.line_follow.set_mode(LineFollowMode.CAMERA_LINE)
    services.line_follow._status = services.line_follow.status().model_copy(
        update={"state": "LOST", "reason": "camera_reselection_required"}
    )
    services.control_adapter = type("Adapter", (), {
        "enabled": True, "calibration_revision": "sensor-policy-r1",
    })()
    services.safety.policy_required = True
    services.line_follow.observe(LineObservation(
        source=LineFollowMode.IR_LINE, stamp=1.0, visible=True,
        error=0.05, confidence=0.95, ir_calibrated=True,
        calibration_revision="c" * 64,
    ))

    rejected = client.put("/api/v1/line-follow/mode", json={"mode": "IR_LINE"}, headers=OPERATOR)

    assert rejected.status_code == 409
    assert rejected.json()["error"]["detail"]["reasons"] == [
        "IR_CALIBRATION_REVISION_MISMATCH",
    ]
    assert services.line_follow.mode is LineFollowMode.CAMERA_LINE


def test_ir_fallback_is_not_automatic_and_requires_camera_failure(core_client):
    client, services = core_client()
    services.control_adapter = type("Adapter", (), {
        "enabled": True, "calibration_revision": "ir-calibration-r1",
    })()
    services.safety.policy_required = True
    client.put("/api/v1/line-follow/mode", json={"mode": "CAMERA_LINE"}, headers=OPERATOR)
    services.line_follow.tick()
    rejected = client.put("/api/v1/line-follow/mode", json={"mode": "IR_LINE"}, headers=OPERATOR)
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "IR_FALLBACK_NOT_READY"
    assert services.line_follow.mode is LineFollowMode.CAMERA_LINE


def test_line_follow_needs_drive_not_nav2_and_hold_to_run_expires(core_client):
    """D-344 §7·§8: motor 런타임(Nav2 없음)에서도 켜지고, 운전자 확인이 끊기면 스스로 멈춘다."""
    client, services = core_client()
    services.capability._data["navigation"]["goal_navigation"] = False
    clock = {"t": 100.0}
    services.line_follow.bind_clock(lambda: clock["t"])

    enabled = client.put("/api/v1/line-follow/mode",
                         json={"mode": "CAMERA_LINE", "hold_s": 0.5}, headers=OPERATOR)
    assert enabled.status_code == 200, enabled.json()
    assert services.line_follow.hold_required

    # 신선한 카메라 차선 증거로 따라가는 중
    services.line_follow.observe(LineObservation(
        source=LineFollowMode.CAMERA_LINE, stamp=clock["t"], visible=True, error=0.1, confidence=0.9),
        received_at=clock["t"], source_now=clock["t"])
    tracking = services.line_follow.tick(clock["t"] + 0.1)
    assert tracking.linear > 0

    clock["t"] += 0.4
    assert client.post("/api/v1/line-follow/hold", headers=OPERATOR).status_code == 200
    services.line_follow.observe(LineObservation(
        source=LineFollowMode.CAMERA_LINE, stamp=clock["t"], visible=True, error=0.0, confidence=0.9),
        received_at=clock["t"], source_now=clock["t"])
    assert services.line_follow.tick(clock["t"] + 0.3).linear > 0          # 갱신 덕분에 아직 유지

    released = services.line_follow.tick(clock["t"] + 0.6)                 # 0.5 s 넘게 갱신 없음
    assert released.linear == 0.0 and released.angular == 0.0
    assert services.line_follow.status().reason == "driver_released"
    assert not services.line_follow.active
    assert client.post("/api/v1/line-follow/hold", headers=OPERATOR).status_code == 409


def test_hold_endpoint_requires_operator_and_rejects_bad_hold(core_client):
    client, services = core_client()
    assert client.post("/api/v1/line-follow/hold", headers=VIEWER).status_code == 403
    assert client.put("/api/v1/line-follow/mode",
                      json={"mode": "CAMERA_LINE", "hold_s": 5}, headers=OPERATOR).status_code == 400
    # hold_s 없는 기존 호출은 그대로 — 만료가 없다
    assert client.put("/api/v1/line-follow/mode",
                      json={"mode": "CAMERA_LINE"}, headers=OPERATOR).status_code == 200
    assert not services.line_follow.hold_required
