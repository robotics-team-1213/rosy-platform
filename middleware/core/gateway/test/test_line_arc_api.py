"""D-520 1-2: exit_segment on POST /api/v1/line-follow/junction, capability lane_arc, the
line_follow.arc status field and the arc config keys (start refusal)."""
from dataclasses import replace

import pytest

from core.line_follow_wiring import _line_follow_config
from test_line_junction_api import BODY, OPERATOR, URL, VIEWER, _active, _pose

SITE = dict(body_front_x_m=.08, body_rear_x_m=-.08, body_half_width_m=.06, body_lidar_x_m=0.,
            body_rotation_radius_m=.1, ir_guard_enabled=True, obstacle_mode='path',
            site_floor_map_id='lab-a')
SEGMENT = {"curvature_1pm": 3.98, "length_m": 0.3739, "outer_line_offset_m": 0.095,
           "end_place_id": "SE"}
ARC = {**BODY, "action": "left", "place_id": "SW", "turn_deg": 64.0, "map_id": "lab-a",
       "pivot_past_line_m": -0.05, "exit_segment": SEGMENT}


def _enable(services):
    lf = services.line_follow
    lf._config = replace(lf.config, arc_enabled=True, **SITE)


def test_exit_segment_validation_is_400(core_client):
    client, services, _ = _active(core_client)
    _enable(services)
    for bad in ({"curvature_1pm": 0.49}, {"curvature_1pm": -0.4}, {"curvature_1pm": 5.01},
                {"curvature_1pm": -5.01}, {"length_m": 0}, {"length_m": 1.01},
                {"outer_line_offset_m": 0.049}, {"outer_line_offset_m": 0.21}, {"end_place_id": ""},
                {"end_place_id": None}):
        segment = {k: v for k, v in {**SEGMENT, **bad}.items() if v is not None}
        response = client.post(URL, json={**ARC, "exit_segment": segment}, headers=OPERATOR)
        assert response.status_code == 400, bad
    without_map = {k: v for k, v in ARC.items() if k != "map_id"}
    assert client.post(URL, json=without_map, headers=OPERATOR).status_code == 400
    for action in ({"action": "stop", "turn_deg": None, "pivot_past_line_m": None},
                   {"turn_deg": None, "pivot_past_line_m": None}):
        body = {k: v for k, v in {**ARC, **action}.items() if v is not None}
        assert client.post(URL, json=body, headers=OPERATOR).status_code == 400, action


def test_exit_segment_is_refused_while_arc_is_off(core_client):
    client, _, _ = _active(core_client)
    refused = client.post(URL, json=ARC, headers=OPERATOR)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "LANE_ARC_UNAVAILABLE"


def test_exit_segment_is_stored_and_advance_m_ignored(core_client):
    client, services, clock = _active(core_client)
    _enable(services)
    _pose(services, clock)
    reply = client.post(URL, json={**ARC, "advance_m": 0.2}, headers=OPERATOR).json()
    assert reply == {"accepted": True, "junction_seq": 1, "state": "armed"}
    j = services.line_follow._junction
    assert j["exit_segment"] == SEGMENT and j["advance_m"] == 0.
    straight = {**BODY, "place_id": "SE", "map_id": "lab-a", "exit_segment": SEGMENT}
    assert client.post(URL, json=straight, headers=OPERATOR).json()["state"] == "armed"
    snapshot = client.get("/api/v1/robot/state", headers=VIEWER).json()["line_follow"]
    assert snapshot["arc"] is None  # no arc yet


def test_capability_lane_arc_follows_arc_enabled(core_client):
    client, services = core_client()
    services.state.set_velocity(0.0, 0.0)

    def base():
        return client.get("/api/v1/system/capabilities", headers=VIEWER).json()["controls"]["items"][0]

    assert base()["lane_arc"] is False
    _enable(services)
    assert base()["lane_arc"] is True


def test_config_keys_defaults_and_start_refusal():
    config = _line_follow_config({})
    # 2026-10-09 addendum: on by default; without the site floor declaration it is no capability
    assert (config.arc_enabled, config.arc_curvature_gain, config.arc_blind_max_m) == (True, 1.0, 1.0)
    on = _line_follow_config({**SITE, "arc_curvature_gain": 0.9})
    assert on.arc_enabled and on.arc_curvature_gain == 0.9
    assert _line_follow_config({**SITE, "arc_enabled": False}).arc_enabled is False
    for bad in (dict(arc_curvature_gain=0.79), dict(arc_curvature_gain=1.26),
                dict(arc_blind_max_m=0), dict(arc_blind_max_m=1.01), dict(arc_enabled=1)):
        with pytest.raises(ValueError):
            _line_follow_config({**SITE, **bad})
    # an IR guard speed of 0 is no lane_arc capability, not a refused start
    assert _line_follow_config({**SITE, "ir_guard_speed_scale": 0.}).arc_enabled is True


def test_bend_while_an_arc_runs_is_409(core_client):
    client, services, clock = _active(core_client)
    _enable(services)
    _pose(services, clock)
    lf = services.line_follow
    lf.observe_scan_points([(1.5, 1.5)], received_at=clock["t"])
    with lf._lock:
        lf._open_arc(dict(place_id="SW", action="left", map_id="lab-a", exit_segment=dict(SEGMENT)), clock["t"])
    assert lf._arc_running()
    bend = {**BODY, "action": "bend", "place_id": "SE", "turn_deg": 30.0, "map_id": "lab-a",
            "bend_in_m": 0.2, "bend_tol_m": 0.1, "bend_radius_m": 0.3}
    refused = client.post(URL, json=bend, headers=OPERATOR)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "JUNCTION_ARC_RUNNING"
