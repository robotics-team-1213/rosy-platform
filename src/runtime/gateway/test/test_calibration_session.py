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
