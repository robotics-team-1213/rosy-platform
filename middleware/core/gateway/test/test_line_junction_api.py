"""D-491 decision 4: POST /api/v1/line-follow/junction, its gate and the snapshot field."""
import json

from core.bridge import observation
from core_features.line_follow.manager import LineFollowMode, LineObservation

VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}
OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}
OTHER = {"Authorization": "Bearer rosy-dev-admin"}
URL = "/api/v1/line-follow/junction"
BODY = {"action": "straight", "place_id": "J1", "expires_s": 5}


def _active(core_client):
    client, services = core_client()
    clock = {"t": 10.0}
    services.line_follow.bind_clock(lambda: clock["t"])
    assert client.put("/api/v1/line-follow/mode", json={"mode": "CAMERA_LINE"},
                      headers=OPERATOR).status_code == 200
    return client, services, clock


def _tick(services, clock, dt=0.05):
    clock["t"] += dt
    lf = services.line_follow
    lf.observe(LineObservation(source=LineFollowMode.CAMERA_LINE, stamp=clock["t"], visible=True,
                               error=0.0, confidence=0.9), received_at=clock["t"])
    decision = lf.tick(clock["t"])
    services.state.set_line_follow(lf.status())
    return decision


def test_viewer_is_forbidden(core_client):
    client, _, _ = _active(core_client)
    assert client.post(URL, json=BODY, headers=VIEWER).status_code == 403


def test_refused_unless_line_follow_is_active(core_client):
    client, _ = core_client()
    response = client.post(URL, json=BODY, headers=OPERATOR)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LINE_FOLLOW_NOT_ACTIVE"


def test_accepted_with_seq_and_visible_in_the_snapshot(core_client):
    client, services, clock = _active(core_client)
    first = client.post(URL, json=BODY, headers=OPERATOR).json()
    assert first == {"accepted": True, "junction_seq": 1, "state": "armed"}
    second = client.post(URL, json={**BODY, "action": "left", "place_id": "J2"},
                         headers=OPERATOR).json()
    assert second == {"accepted": True, "junction_seq": 2, "state": "unresolved"}
    assert _tick(services, clock).linear == 0.0
    snapshot = client.get("/api/v1/robot/state", headers=VIEWER).json()["line_follow"]
    assert snapshot["junction"] == {"pending_action": "left", "place_id": "J2",
                                    "state": "unresolved", "seq": 2}
    assert (snapshot["state"], snapshot["reason"]) == ("HOLD", "junction_unresolved")
    assert client.get("/api/v1/line-follow", headers=VIEWER).json()["junction"]["seq"] == 2
    assert services.line_follow.mode is LineFollowMode.CAMERA_LINE  # no mode change


def test_expired_instruction_stops_at_a_detected_junction(core_client):
    client, services, clock = _active(core_client)
    client.post(URL, json={**BODY, "expires_s": 1}, headers=OPERATOR)
    assert _tick(services, clock).linear > 0
    clock["t"] += 2.0
    services.line_follow.observe_junction("junction_transverse", clock["t"])
    assert _tick(services, clock).linear == 0.0
    junction = client.get("/api/v1/robot/state", headers=VIEWER).json()["line_follow"]["junction"]
    assert junction["state"] == "waiting" and junction["pending_action"] is None


def test_calibration_lease_fences_other_tokens(core_client):
    client, services = core_client()
    assert client.post("/api/v1/calibration/session", json={
        "kind": "drive", "label": "주행 보정", "ttl_s": 30}, headers=OPERATOR).status_code == 201
    assert client.put("/api/v1/line-follow/mode", json={"mode": "CAMERA_LINE"},
                      headers=OPERATOR).status_code == 200
    refused = client.post(URL, json=BODY, headers=OTHER)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "CALIBRATION_ACTIVE"
    assert client.post(URL, json=BODY, headers=OPERATOR).status_code == 200


def test_validation(core_client):
    client, _, _ = _active(core_client)
    for body in ({**BODY, "action": "north"}, {**BODY, "expires_s": 31},
                 {**BODY, "expires_s": 0}, {k: v for k, v in BODY.items() if k != "expires_s"},
                 {**BODY, "place_id": ""}, {**BODY, "stop_after_m": 0.2},
                 {**BODY, "action": "stop", "stop_after_m": 2.5}):
        assert client.post(URL, json=body, headers=OPERATOR).status_code == 400, body
    ok = client.post(URL, json={**BODY, "action": "stop", "stop_after_m": 0.3}, headers=OPERATOR)
    assert ok.json()["state"] == "executing"


def test_keep_debug_junction_reason_feeds_the_manager(core_client):
    _, services, clock = _active(core_client)
    raw = json.dumps({"reason": "junction_fork", "stamp": 100.0})
    observation.keep_junction(services, raw, source_now=100.1, received_at=clock["t"])
    assert _tick(services, clock).linear == 0.0
    assert services.line_follow.status().reason == "junction_waiting"


def test_stale_or_other_keep_debug_is_not_a_sighting(core_client):
    _, services, clock = _active(core_client)
    for raw, now in ((json.dumps({"reason": "junction_fork", "stamp": 100.0}), 105.0),
                     (json.dumps({"reason": "no_boundary", "stamp": 100.0}), 100.1),
                     ("not json", 100.1), ("[1]", 100.1)):
        observation.keep_junction(services, raw, source_now=now, received_at=clock["t"])
    assert _tick(services, clock).linear > 0
