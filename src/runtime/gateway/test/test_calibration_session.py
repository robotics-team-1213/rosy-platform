"""D-321 addendum: the calibration session lease is visible and fences other tokens."""

import pytest

VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}
OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}
#: A different token with at least operator rank: the "other actor".
OTHER = {"Authorization": "Bearer rosy-dev-admin"}


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def lease(core_client):
    client, services = core_client()
    clock = _Clock()
    services.calibration._monotonic = clock
    services.state.set_velocity(0.0, 0.0)  # a live base for the teleop write gate
    return client, services, clock


def _open(client, headers=OPERATOR, **body):
    payload = {"kind": "drive", "label": "주행 보정", "ttl_s": 30}
    payload.update(body)
    return client.post("/api/v1/calibration/session", json=payload, headers=headers)


def _events(client, prefix="calibration."):
    body = client.get("/api/v1/events", headers=VIEWER).json()
    return [e for e in body["events"] if e["type"].startswith(prefix)]


def test_lifecycle_start_heartbeat_get_end(lease):
    client, _, clock = lease
    assert client.get("/api/v1/calibration/session", headers=VIEWER).json() == {"session": None}

    started = _open(client)
    assert started.status_code == 201
    session = started.json()["session"]
    assert session["kind"] == "drive"
    assert session["label"] == "주행 보정"
    assert session["ttl_s"] == 30
    assert session["owner"]["role"] == "operator"
    whoami = client.get("/api/v1/auth/whoami", headers=OPERATOR).json()
    assert session["owner"]["id"] == whoami["id"]

    clock.now += 20
    assert client.get("/api/v1/calibration/session",
                      headers=VIEWER).json()["session"]["remaining_s"] == 10
    beat = client.post(f"/api/v1/calibration/session/{session['id']}/heartbeat", headers=OPERATOR)
    assert beat.status_code == 200
    assert beat.json()["session"]["remaining_s"] == 30

    ended = client.delete(f"/api/v1/calibration/session/{session['id']}", headers=OPERATOR)
    assert ended.status_code == 200
    assert client.get("/api/v1/calibration/session", headers=VIEWER).json() == {"session": None}
    types = [e["type"] for e in _events(client)]
    assert types == ["calibration.session_started", "calibration.session_ended"]


def test_viewer_cannot_open_and_second_session_is_refused(lease):
    client, _, _ = lease
    assert _open(client, headers=VIEWER).status_code == 403
    assert _open(client).status_code == 201
    second = _open(client, headers=OTHER, kind="camera")
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "CALIBRATION_ACTIVE"
    assert second.json()["error"]["detail"]["session"]["kind"] == "drive"


def test_start_validates_kind_and_ttl(lease):
    client, _, _ = lease
    assert _open(client, kind="Drive!").status_code == 400
    assert _open(client, ttl_s=1).status_code == 400
    assert _open(client, ttl_s=301).status_code == 400


def test_only_owner_heartbeats_and_admin_may_force_end(lease):
    client, _, _ = lease
    session = _open(client).json()["session"]
    path = f"/api/v1/calibration/session/{session['id']}"
    assert client.post(path + "/heartbeat", headers=OTHER).status_code == 403
    assert client.post("/api/v1/calibration/session/nope/heartbeat",
                       headers=OPERATOR).status_code == 404
    # The admin token is not the owner but may clear a stuck lease.
    assert client.delete(path, headers=OTHER).status_code == 200


def test_non_owner_operator_cannot_end_the_session(core_client):
    client, services = core_client(config_overrides={"auth": {"tokens": [
        {"token": "rosy-dev-operator", "role": "operator"},
        {"token": "second-operator-token-0001", "role": "operator"},
        {"token": "rosy-dev-viewer", "role": "viewer"},
    ]}})
    session = _open(client).json()["session"]
    other_operator = {"Authorization": "Bearer second-operator-token-0001"}
    denied = client.delete(f"/api/v1/calibration/session/{session['id']}", headers=other_operator)
    assert denied.status_code == 403
    assert services.calibration.current() is not None


def test_session_expires_without_heartbeat(lease):
    client, _, clock = lease
    session = _open(client).json()["session"]
    clock.now += 30.5
    assert client.get("/api/v1/calibration/session", headers=VIEWER).json() == {"session": None}
    beat = client.post(f"/api/v1/calibration/session/{session['id']}/heartbeat", headers=OPERATOR)
    assert beat.status_code == 404
    expired = [e for e in _events(client) if e["type"] == "calibration.session_expired"]
    assert len(expired) == 1
    assert expired[0]["severity"] == "warning"
    assert expired[0]["data"]["session_id"] == session["id"]
    # The fence lifts with the lease.
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OTHER).status_code == 200


def test_expiry_timer_hook_emits_once(lease):
    client, services, clock = lease
    _open(client)
    clock.now += 31
    services.calibration.expire_due()
    services.calibration.expire_due()
    assert [e["type"] for e in _events(client)].count("calibration.session_expired") == 1


def test_non_owner_drive_and_mode_writes_get_409(lease):
    client, services, _ = lease
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OPERATOR).status_code == 200
    _open(client)

    for method, path, body in (
        ("post", "/api/v1/teleop", {"linear": 0.1, "angular": 0.0}),
        ("post", "/api/v1/mode", {"mode": "NAVIGATION"}),
        ("post", "/api/v1/mode", {"mode": "MANUAL"}),
        ("put", "/api/v1/line-follow/mode", {"mode": "IR_LINE"}),
        ("post", "/api/v1/line-follow/hold", None),
        ("post", "/api/v1/navigation/goal", {"x": 1.0, "y": 0.0}),
        ("post", "/api/v1/navigation/home", None),
        ("post", "/api/v1/swarm/follow", {"target_robot_id": "rosy_02"}),
    ):
        response = getattr(client, method)(path, json=body, headers=OTHER)
        assert response.status_code == 409, path
        assert response.json()["error"]["code"] == "CALIBRATION_ACTIVE", path
        assert response.json()["error"]["detail"]["session"]["label"] == "주행 보정"
    assert services.command.select_output().linear == 0.0


def test_non_owner_docking_is_fenced(core_client):
    client, services = core_client(capabilities={"docking": {"supported": True}})
    _open(client)
    for path, body in (("/api/v1/docking/dock", {"dock": "d1"}), ("/api/v1/docking/undock", None)):
        response = client.post(path, json=body, headers=OTHER)
        assert response.status_code == 409, (path, response.json())
        assert response.json()["error"]["code"] == "CALIBRATION_ACTIVE"


def test_non_owner_may_still_stop_through_idle(lease):
    client, services, _ = lease
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OPERATOR).status_code == 200
    _open(client)
    stopped = client.post("/api/v1/mode", json={"mode": "IDLE"}, headers=OTHER)
    assert stopped.status_code == 200
    assert stopped.json()["mode"] == "IDLE"


def test_owner_teleop_still_works_within_limits(lease):
    client, services, _ = lease
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OPERATOR).status_code == 200
    _open(client)
    r = client.post("/api/v1/teleop", json={"linear": 0.1, "angular": 0.0}, headers=OPERATOR)
    assert r.status_code == 200
    assert services.command.select_output().linear == pytest.approx(0.1)
    # D-342 limits still clamp the owner.
    client.post("/api/v1/teleop", json={"linear": 50.0, "angular": 0.0}, headers=OPERATOR)
    assert services.command.select_output().linear <= services.safety.limits.manual_linear + 1e-9
    services.command.clear_manual()


def test_estop_always_works_from_anyone(lease):
    client, services, _ = lease
    _open(client)
    stopped = client.post("/api/v1/safety/stop", headers=OTHER)
    assert stopped.status_code == 200
    assert services.safety.estop is True


def test_line_follow_off_stays_open_to_everyone(lease):
    client, _, _ = lease
    _open(client)
    off = client.put("/api/v1/line-follow/mode", json={"mode": "OFF"}, headers=OTHER)
    assert off.status_code == 200


def test_activity_is_in_robot_state_while_active(lease):
    client, _, clock = lease
    assert client.get("/api/v1/robot/state", headers=VIEWER).json()["activity"] is None
    session = _open(client, kind="camera", label="카메라 외부 보정").json()["session"]
    clock.now += 5
    activity = client.get("/api/v1/robot/state", headers=VIEWER).json()["activity"]
    assert activity == {
        "kind": "CALIBRATING",
        "session_id": session["id"],
        "calibration_kind": "camera",
        "label": "카메라 외부 보정",
        "owner": session["owner"],
        "started_at": session["started_at"],
        "remaining_s": 25.0,
    }
    client.delete(f"/api/v1/calibration/session/{session['id']}", headers=OPERATOR)
    assert client.get("/api/v1/robot/state", headers=VIEWER).json()["activity"] is None


def test_activity_is_in_the_ws_state_push(lease):
    client, _, _ = lease
    _open(client)
    with client.websocket_connect("/ws/state") as ws:
        ws.send_json({"type": "auth", "token": "rosy-dev-viewer"})
        frame = ws.receive_json()
    assert frame["activity"]["kind"] == "CALIBRATING"
    assert frame["activity"]["label"] == "주행 보정"


def test_expiry_is_published_outside_the_lease_lock(lease):
    """Review item 5: a bus subscriber that reads the lease back must not block on it."""
    client, services, clock = lease
    seen = []

    def subscriber(event):
        if event.type == "calibration.session_expired":
            # A plain Lock held by the publisher would deadlock this read.
            acquired = services.calibration._lock.acquire(timeout=1.0)
            seen.append(acquired)
            if acquired:
                services.calibration._lock.release()
            seen.append(services.calibration.current())

    unsubscribe = services.events.subscribe(subscriber)
    try:
        _open(client)
        clock.now += 31
        assert services.calibration.current() is None
    finally:
        unsubscribe()
    assert seen == [True, None]


# --- review item 3: a lease starts only from a quiet robot; reference feed fenced ----


def test_start_is_refused_while_the_robot_is_busy(lease):
    client, services, _ = lease
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OPERATOR).status_code == 200
    assert _open(client).status_code == 201           # MANUAL, nothing running: allowed
    session_id = client.get("/api/v1/calibration/session", headers=VIEWER).json()["session"]["id"]
    client.delete(f"/api/v1/calibration/session/{session_id}", headers=OPERATOR)

    enabled = client.put("/api/v1/line-follow/mode", json={"mode": "IR_LINE"}, headers=OPERATOR)
    assert enabled.status_code == 200                  # NAVIGATION + line-follow active
    refused = _open(client)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "MODE_CONFLICT"
    assert services.calibration.current() is None


def test_start_is_refused_while_swarm_follow_is_armed(lease, monkeypatch):
    client, services, _ = lease
    monkeypatch.setattr(type(services.swarm), "active", property(lambda self: True))
    refused = _open(client)
    assert refused.status_code == 409 and "swarm" in refused.json()["error"]["message"]


def _pose_frame():
    from core_common.protocol.schemas import EnvelopeType
    return {"type": EnvelopeType.POSE.value,
            "payload": {"robot_id": "rosy_02", "pose": {"x": 1.0, "y": 0.0, "yaw": 0.0}, "seq": 1}}


def test_swarm_reference_frames_from_non_owners_are_dropped_during_a_lease(lease):
    client, services, _ = lease
    received = []
    services.swarm.on_reference_pose = received.append
    _open(client)
    for token, expected in (("rosy-dev-admin", 0), ("rosy-dev-operator", 1)):
        with client.websocket_connect(f"/ws/swarm/reference?token={token}") as socket:
            socket.send_json(_pose_frame())
            socket.send_json({"type": "ping"})
        assert len(received) == expected, token


# --- review item 4: limits, host restarts, pose/slam/power are fenced too ------------

ADMIN = OTHER   # rosy-dev-admin: an administrator that is not the lease owner


def test_non_owner_admin_cannot_move_the_safety_limits(lease):
    client, services, _ = lease
    before = services.safety.limits.manual_linear
    _open(client)
    refused = client.put("/api/v1/safety/limits", json={"manual_linear": 0.05}, headers=ADMIN)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "CALIBRATION_ACTIVE"
    assert services.safety.limits.manual_linear == before


@pytest.mark.parametrize("path,body", [
    ("/api/v1/host/release/install", {"release_id": "2026.10.01-001", "confirmed": True}),
    ("/api/v1/host/release/rollback", {"confirmed": True}),
    ("/api/v1/host/reboot", {"confirmed": True}),
])
def test_host_restarts_need_an_explicit_override_during_a_lease(lease, path, body):
    client, _, _ = lease
    _open(client)
    refused = client.post(path, json=body, headers=ADMIN)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "CALIBRATION_ACTIVE"
    assert "override_calibration" in refused.json()["error"]["message"]
    # With the flag the request goes on to the Host Agent (absent here, so not 409).
    forced = client.post(path, json={**body, "override_calibration": True}, headers=ADMIN)
    assert forced.status_code != 409 or forced.json()["error"]["code"] != "CALIBRATION_ACTIVE"


@pytest.mark.parametrize("path,body", [
    ("/api/v1/localization/initialpose", {"x": 0.0, "y": 0.0, "yaw": 0.0}),
    ("/api/v1/slam/start", None),
    ("/api/v1/slam/stop", None),
    ("/api/v1/slam/reset", None),
    ("/api/v1/power/mode", {"mode": "STANDBY"}),
])
def test_pose_slam_and_power_mode_are_fenced_for_non_owners(lease, path, body):
    client, _, _ = lease
    _open(client)
    response = client.post(path, json=body, headers=OTHER)
    assert response.status_code == 409, (path, response.json())
    assert response.json()["error"]["code"] == "CALIBRATION_ACTIVE"


def test_power_wake_stays_open(lease):
    client, _, _ = lease
    _open(client)
    assert client.post("/api/v1/power/wake", headers=OTHER).status_code == 200


# --- review item 9: stop paths, cancels, /do, concurrency ----------------------------


def test_viewer_token_can_estop_during_a_lease(lease):
    client, services, _ = lease
    _open(client)
    stopped = client.post("/api/v1/safety/stop", headers=VIEWER)
    assert stopped.status_code == 200
    assert services.safety.estop is True


@pytest.mark.parametrize("method,path,body", [
    ("post", "/api/v1/navigation/cancel", None),
    ("post", "/api/v1/swarm/cancel", None),
    ("put", "/api/v1/line-follow/mode", {"mode": "OFF"}),
    ("post", "/api/v1/mode", {"mode": "IDLE"}),
])
def test_cancel_and_stop_routes_stay_open_to_non_owners(lease, method, path, body):
    client, _, _ = lease
    _open(client)
    response = getattr(client, method)(path, json=body, headers=OTHER)
    assert response.status_code == 200, (path, response.json())


def test_docking_cancel_stays_open_to_non_owners(core_client):
    client, _ = core_client(capabilities={"docking": {"supported": True}})
    _open(client)
    assert client.post("/api/v1/docking/cancel", headers=OTHER).status_code == 200


@pytest.mark.parametrize("step", [
    {"do": "move", "linear": 0.1, "angular": 0.0},
    {"do": "navigate", "x": 1.0, "y": 0.0},
    {"do": "home"},
    {"do": "follow", "target_robot_id": "rosy_02"},
])
def test_intent_do_is_fenced_like_the_routes_it_calls(lease, step):
    client, services, _ = lease
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OPERATOR).status_code == 200
    _open(client)
    response = client.post("/api/v1/do", json=step, headers=OTHER)
    assert response.status_code == 409, response.json()
    assert response.json()["error"]["code"] == "CALIBRATION_ACTIVE"
    assert services.command.select_output().linear == 0.0


def test_intent_do_stop_stays_open(lease):
    client, services, _ = lease
    _open(client)
    assert client.post("/api/v1/do", json={"do": "stop"}, headers=OTHER).status_code == 200
    assert services.safety.estop is True


def test_concurrent_starts_open_exactly_one_lease(lease):
    """Many tokens racing POST /calibration/session: one owner, the rest CALIBRATION_ACTIVE."""
    import threading

    _, services, _ = lease
    from core_features.calibration import CalibrationSessionError

    results: list[str] = []
    barrier = threading.Barrier(16)

    def attempt(index: int) -> None:
        barrier.wait()
        try:
            services.calibration.start(kind="drive", label=f"t{index}", ttl_s=30,
                                       owner_id=f"tok-{index}", owner_role="operator")
            results.append("opened")
        except CalibrationSessionError as exc:
            results.append(exc.code)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert results.count("opened") == 1
    assert results.count("CALIBRATION_ACTIVE") == 15
    owner = services.calibration.current()["owner"]["id"]
    # Heartbeats racing expiry: the owner keeps it, nobody else can renew it.
    errors: list[str] = []

    def beat(token: str) -> None:
        for _ in range(50):
            try:
                services.calibration.heartbeat(services.calibration.current()["id"], token)
            except CalibrationSessionError as exc:
                errors.append(exc.code)

    racers = [threading.Thread(target=beat, args=(owner,)),
              threading.Thread(target=beat, args=("tok-intruder",))]
    for thread in racers:
        thread.start()
    for thread in racers:
        thread.join(timeout=5)
    assert set(errors) == {"FORBIDDEN"} and len(errors) == 50
    assert services.calibration.current()["owner"]["id"] == owner


def test_contract_documents_ownership_revocation_and_battery_return():
    """Review item 8: the API Ref and the D-321 addendum state the lease edge cases."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[4]
    reference = (root / "docs/reference/ROSY API & Protocol Reference.md").read_text(encoding="utf-8")
    adr = (root / "docs/adr/D-321-attended-calibration-g4-mapping.md").read_text(encoding="utf-8")
    for text in (reference, adr):
        assert "토큰 단위" in text                     # ownership is per token
        assert "`ttl_s` 가 지" in text and "DELETE" in text   # revoked token keeps it until TTL
        assert "RETURN_HOME" in text                   # battery return ignores the lease
        assert "override_calibration" in text


def test_slam_save_stays_open_to_non_owners(lease):
    """Saving a map does not move the robot or change what the owner measures."""
    client, _, _ = lease
    _open(client)
    response = client.post("/api/v1/slam/save", json={"name": "cal_map"}, headers=OTHER)
    assert response.status_code != 409 or response.json()["error"]["code"] != "CALIBRATION_ACTIVE"
    assert response.status_code in (200, 501), response.json()
