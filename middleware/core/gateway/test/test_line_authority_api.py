"""D-517 4 (M2), D-760 1-3: POST /api/v1/line-follow/authority, its validation and the status field."""
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


def test_selected_route_prior_reaches_accepted_authority(core_client):
    client, services, clock = _active(core_client)
    guide = dict(map_id='map-a', map_revision=2, heading_here_deg=0., heading_ahead_deg=20.,
                 ahead_m=.25, s_m=.5, off_route_m=.01, max_age_s=.8)
    response = client.post(URL, json=_body(clock, seq=1, route_guide=guide), headers=OPERATOR)
    assert response.status_code == 200 and response.json()['accepted']
    assert services.line_follow.route_guide().heading_ahead_deg == 20.


def test_route_prior_rejects_unknown_or_nonfinite_geometry(core_client):
    client, _, clock = _active(core_client)
    guide = dict(map_id='map-a', map_revision=2, heading_here_deg=0., heading_ahead_deg=20.,
                 ahead_m=.25, s_m=.5, off_route_m=.01, max_age_s=.8, pivot_ok=True)
    assert client.post(URL, json=_body(clock, seq=1, route_guide=guide), headers=OPERATOR).status_code == 400


def test_refused_unless_line_follow_is_active(core_client):
    client, _ = core_client()
    response = client.post(URL, json=_body({"t": 10.0}), headers=OPERATOR)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LINE_FOLLOW_NOT_ACTIVE"


@pytest.mark.parametrize("fields", [
    {"ttl_s": 0}, {"ttl_s": 5.01}, {"until_m": -0.1}, {"until_m": 10.5}, {"pose_stamp": 0},
    {"authority_id": ""}, {"leg_id": None}, {"seq": -1}, {"seq": 1.5}, {"shrink": "maybe"},
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


def test_a_five_second_ttl_is_accepted(core_client):
    client, _, clock = _active(core_client)
    answer = client.post(URL, json=_body(clock, ttl_s=5.0), headers=OPERATOR)
    assert answer.status_code == 200 and answer.json()["authority"]["expires_in_s"] == 5.0


def test_shrink_and_seq_reach_the_gate(core_client):
    client, _, clock = _active(core_client)
    assert client.post(URL, json=_body(clock, seq=3), headers=OPERATOR).json()["accepted"] is True
    shrunk = client.post(URL, json=_body(clock, until_m=0.0, shrink=True, seq=4), headers=OPERATOR).json()
    assert shrunk["accepted"] is True
    assert (shrunk["authority"]["state"], shrunk["authority"]["reason"]) == ("HOLDING", "authority_end")
    late = client.post(URL, json=_body(clock, seq=2), headers=OPERATOR)  # the older extend arrives last
    assert late.status_code == 200
    assert (late.json()["accepted"], late.json()["reason"]) == (False, "stale_seq")
    assert late.json()["authority"]["remaining_m"] == 0.0
    plain = client.post(URL, json=_body(clock, until_m=0.5), headers=OPERATOR)  # no seq on a leg that has one
    assert plain.status_code == 200
    assert (plain.json()["accepted"], plain.json()["reason"]) == (False, "seq_required")
    assert plain.json()["authority"]["remaining_m"] == 0.0


def test_a_shrink_with_nothing_held_grants_nothing(core_client):
    client, _, clock = _active(core_client)
    answer = client.post(URL, json=_body(clock, shrink=True), headers=OPERATOR)
    assert answer.status_code == 200
    assert (answer.json()["accepted"], answer.json()["reason"]) == (False, "shrink_none_held")
    assert answer.json()["authority"]["state"] == "NONE"
