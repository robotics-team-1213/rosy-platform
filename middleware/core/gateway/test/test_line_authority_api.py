"""D-517 4 (M2): POST /api/v1/line-follow/authority, its validation and the status field."""
import pytest

VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}
OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}
URL = "/api/v1/line-follow/authority"
WALL = 1_800_000_000.0


def _body(clock, **fields):
    return {"authority_id": "trip-1:1", "leg_id": "trip-1:0", "pose_stamp": WALL + clock["t"],
            "until_m": 1.0, "ttl_s": 2.0, **fields}


def _active(core_client, odom=True):
    client, services = core_client()
    clock = {"t": 10.0}
    lf = services.line_follow
    lf.bind_clock(lambda: clock["t"])
    lf._wall = lambda: WALL + clock["t"]
    assert client.put("/api/v1/line-follow/mode", json={"mode": "CAMERA_LINE"},
                      headers=OPERATOR).status_code == 200
    if odom:
        stamp = round(clock["t"] * 1e9)
        lf.observe_return_pose(stamp_ns=stamp, source_now_ns=stamp, frame="odom", x=0., y=0., yaw=0.,
                               received_at=clock["t"])
    return client, services, clock


def test_viewer_is_forbidden(core_client):
    client, _, clock = _active(core_client)
    assert client.post(URL, json=_body(clock), headers=VIEWER).status_code == 403


def test_refused_unless_line_follow_is_active(core_client):
    client, _ = core_client()
    response = client.post(URL, json=_body({"t": 10.0}), headers=OPERATOR)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LINE_FOLLOW_NOT_ACTIVE"


@pytest.mark.parametrize("fields", [
    {"ttl_s": 0}, {"ttl_s": 2.5}, {"until_m": -0.1}, {"until_m": 10.5}, {"pose_stamp": 0},
    {"authority_id": ""}, {"leg_id": None},
])
def test_invalid_fields_are_400(core_client, fields):
    client, _, clock = _active(core_client)
    response = client.post(URL, json=_body(clock, **fields), headers=OPERATOR)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_without_odom_the_authority_is_refused(core_client):
    client, _, clock = _active(core_client, odom=False)
    response = client.post(URL, json=_body(clock), headers=OPERATOR)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "AUTHORITY_ODOM_STALE"


def test_a_stale_pose_stamp_is_refused(core_client):
    client, _, clock = _active(core_client)
    response = client.post(URL, json=_body(clock, pose_stamp=WALL + clock["t"] - 10), headers=OPERATOR)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "AUTHORITY_POSE_STALE"
    status = client.get("/api/v1/line-follow", headers=VIEWER).json()
    assert status["authority"]["state"] == "NONE"  # refused: enforced, nothing held


def test_accepted_and_shown_only_while_enforced(core_client):
    client, _, clock = _active(core_client)
    assert "authority" not in client.get("/api/v1/line-follow", headers=VIEWER).json()
    answer = client.post(URL, json=_body(clock), headers=OPERATOR).json()
    assert answer["accepted"] is True and answer["authority"]["state"] == "FREE"
    shown = client.get("/api/v1/line-follow", headers=VIEWER).json()["authority"]
    assert shown == {"state": "FREE", "authority_id": "trip-1:1", "leg_id": "trip-1:0", "remaining_m": 1.0,
                     "expires_in_s": 2.0, "reason": None}
    smaller = client.post(URL, json=_body(clock, until_m=0.5), headers=OPERATOR).json()
    assert (smaller["accepted"], smaller["reason"]) == (False, "shrink")
