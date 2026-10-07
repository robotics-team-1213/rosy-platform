"""D-494 decision 4: POST /api/v1/line-follow/junction, its gate and the snapshot field."""
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
                                    "state": "unresolved", "seq": 2, "turn_deg": None,
                                    "reason": None, "pivot_basis": None}
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
                 {**BODY, "action": "stop", "stop_after_m": 2.5},
                 {**BODY, "turn_deg": 10}, {**BODY, "action": "left", "turn_deg": -90},
                 {**BODY, "action": "right", "turn_deg": 90}, {**BODY, "action": "left", "turn_deg": 0},
                 {**BODY, "action": "left", "turn_deg": 151},
                 {**BODY, "action": "left", "advance_m": 0.1},
                 {**BODY, "action": "left", "turn_deg": 90, "advance_m": 0.31}):
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


def test_turn_request_arms_and_reports_turn_deg(core_client):
    """D-495: left/right with turn_deg arm a bounded turn; old requests stay unresolved."""
    client, services, clock = _active(core_client)
    body = {**BODY, "action": "right", "turn_deg": -90, "advance_m": 0.2}
    assert client.post(URL, json=body, headers=OPERATOR).json() == {
        "accepted": True, "junction_seq": 1, "state": "armed"}
    _tick(services, clock)
    junction = client.get("/api/v1/robot/state", headers=VIEWER).json()["line_follow"]["junction"]
    assert (junction["state"], junction["turn_deg"]) == ("armed", -90)


def test_keep_debug_corner_turning_is_the_junction_turn_evidence(core_client):
    _, services, clock = _active(core_client)
    assert services.line_follow.supports_junction_turn is False
    services.line_follow.bind_return_motion(lambda now, v, w: True, proof_configured=lambda: True)
    for corner, expected in ((True, True), (False, False), ("yes", False)):
        raw = json.dumps({"reason": "no_boundary", "stamp": 100.0, "corner_turning": corner})
        observation.keep_junction(services, raw, source_now=100.1, received_at=clock["t"])
        assert services.line_follow.supports_junction_turn is expected


def test_refused_while_manual_control_is_active(core_client):
    """Review L6: the same manual-released rule as the other motion endpoints."""
    client, services = core_client()
    services.state.set_velocity(0.0, 0.0)
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OPERATOR).status_code == 200
    assert client.post("/api/v1/teleop", json={"linear": 0.05, "angular": 0.0},
                       headers=OPERATOR).status_code == 200
    refused = client.post(URL, json=BODY, headers=OPERATOR)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "MODE_CONFLICT"


def test_repeat_of_a_finished_instruction_is_409_already_done(core_client):
    """Review L1 (final): the HTTP shape of JUNCTION_ALREADY_DONE."""
    client, services, clock = _active(core_client)
    services.line_follow._junction_done_place = ("J1", "left")   # a finished left at J1
    body = {**BODY, "action": "left", "turn_deg": 90}
    refused = client.post(URL, json=body, headers=OPERATOR)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "JUNCTION_ALREADY_DONE"
    assert client.post(URL, json={**body, "place_id": "J2"}, headers=OPERATOR).json()["accepted"] is True



def test_packaged_default_keeps_the_d498_site_basis_off():
    """D-498: no robot turns on the site basis from code; a bad overlay refuses to load."""
    from pathlib import Path

    import pytest
    import yaml

    from core.services import _line_follow_config
    default = Path(__file__).resolve().parents[4] / "contracts" / "foundation" / "config" / "rosy_default.yaml"
    raw = yaml.safe_load(default.read_text(encoding="utf-8"))["line_follow"]
    assert raw["junction_turn_site_accepted"] is False
    assert _line_follow_config(raw).junction_turn_site_accepted is False
    with pytest.raises(ValueError, match="junction_turn_site_accepted"):
        _line_follow_config({**raw, "junction_turn_site_accepted": True})   # IR guard still off
    with pytest.raises(ValueError, match="true or false"):
        _line_follow_config({**raw, "junction_turn_site_accepted": "yes"})
    assert _line_follow_config({**raw, "junction_turn_site_accepted": True,
                                "ir_guard_enabled": True}).junction_turn_site_accepted is True


D507 = {**BODY, "action": "left", "turn_deg": 90, "map_id": "site_a",
        "expect_in_m": 0.5, "expect_tol_m": 0.1, "pivot_past_line_m": 0.1}


def _pose(services, clock):
    stamp = round(clock["t"] * 1e9)
    services.line_follow.observe_return_pose(stamp_ns=stamp, source_now_ns=stamp, frame="odom",
                                             x=0.0, y=0.0, yaw=0.0, received_at=clock["t"])


def test_d507_window_and_pivot_fields_validation(core_client):
    client, services, clock = _active(core_client)
    for bad in ({"expect_in_m": 0}, {"expect_in_m": 2.01}, {"expect_tol_m": 0},
                {"expect_tol_m": 0.31}, {"pivot_past_line_m": -0.01}, {"pivot_past_line_m": 0.31},
                {"map_id": "bad id"}, {"map_id": ""}, {"expect_tol_m": None},
                {"expect_in_m": None}):
        body = {k: v for k, v in {**D507, **bad}.items() if v is not None}
        assert client.post(URL, json=body, headers=OPERATOR).status_code == 400, body
    for pivot_without_turn in ({**BODY, "pivot_past_line_m": 0.1},
                               {**BODY, "action": "left", "pivot_past_line_m": 0.1}):
        assert client.post(URL, json=pivot_without_turn, headers=OPERATOR).status_code == 400
    refused = client.post(URL, json=D507, headers=OPERATOR)  # no odom yet: cannot place it
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "JUNCTION_ODOM_STALE"
    _pose(services, clock)
    assert client.post(URL, json=D507, headers=OPERATOR).json() == {
        "accepted": True, "junction_seq": 1, "state": "armed"}
    straight = {**BODY, "place_id": "J2", "map_id": "site_a", "expect_in_m": 0.5, "expect_tol_m": 0.1}
    assert client.post(URL, json=straight, headers=OPERATOR).json()["state"] == "armed"


def test_d507_keep_debug_junction_ahead_reaches_the_manager(core_client):
    _, services, clock = _active(core_client)
    raw = json.dumps({"reason": "junction_transverse", "stamp": clock["t"], "junction_ahead_m": 0.25})
    observation.keep_junction(services, raw, source_now=clock["t"], received_at=clock["t"])
    assert services.line_follow._junction_ahead == (0.25, "junction_transverse")
    for bad in (True, "0.2", -0.1, None):
        raw = json.dumps({"reason": "junction_fork", "stamp": clock["t"], "junction_ahead_m": bad})
        observation.keep_junction(services, raw, source_now=clock["t"], received_at=clock["t"])
        assert services.line_follow._junction_ahead == (None, "junction_fork")
