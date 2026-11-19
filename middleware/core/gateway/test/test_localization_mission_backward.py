"""D-395 P2-7 `nudge_backward`: the exact mirror of `nudge_forward` into the rear sector.

Same fixtures as `test_localization_mission.py` (the `core_client` factory stands the robot
up); the scans here carry a rear window beside the front one.
"""

from __future__ import annotations

import dataclasses
import json
import math

import pytest

VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}
OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}
PATH = "/api/v1/localization/mission"


class _Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _state(state="CANDIDATES", frame="map") -> str:
    return json.dumps({"status": {"state": state, "pose_frame": frame, "request_id": None},
                       "pose": None, "stamp": 1.0})


def _scan(services, front_m: float = 2.0, rear_m: float = 2.0, *, within_deg: float = 10.0,
          rest_m: float = 2.0) -> dict:
    """360 one-degree beams: `front_m` within ±within_deg of the robot's front, `rear_m`
    within ±within_deg of its rear, `rest_m` elsewhere."""
    forward = services.line_follow.config.lidar_forward_deg
    ranges = []
    for i in range(360):
        offset = (i - forward + 180.0) % 360.0 - 180.0
        if abs(offset) <= within_deg:
            ranges.append(front_m)
        elif abs(abs(offset) - 180.0) <= within_deg:
            ranges.append(rear_m)
        else:
            ranges.append(rest_m)
    return {"ranges": ranges, "angle_min": 0.0, "angle_max": math.radians(359.0),
            "range_min": 0.05, "range_max": 8.0}


@pytest.fixture
def core(core_client):
    client, services = core_client()
    mission = services.loc_mission
    mission._clock = clock = _Clock()
    published: list[dict] = []
    mission.publish = published.append
    services.localization.on_state(_state())
    services.state.set_velocity(0.0, 0.0)
    mission.observe_odom(0.0, 0.0, 0.0)
    mission.observe_scan(_scan(services))
    services.clock, services.published = clock, published
    return client, services


def _start(client, kind="nudge_backward", distance=0.05, time_s=30.0, headers=OPERATOR):
    return client.post(PATH, headers=headers, json={"kind": kind, "max_distance_m": distance,
                                                    "max_time_s": time_s, "target": None})


def _code(response) -> str:
    return response.json()["error"]["code"]


def _step(services, dt=0.05, odom=None):
    services.clock.now += dt
    if odom is not None:
        services.loc_mission.observe_odom(*odom)
    services.loc_mission.observe_scan(services.loc_mission._scan[0])
    services.loc_mission.tick()


def _with_pinky_body(services):
    """The Pinky Pro URDF body keys of products/pinky_pro/profile/config/core.yaml."""
    from core_common.robot_body import PINKY_PRO as B
    lf = services.line_follow
    lf._config = dataclasses.replace(
        lf.config, body_front_x_m=B.front_x_m, body_rear_x_m=B.rear_x_m, body_lidar_x_m=B.lidar_x_m,
        body_half_width_m=B.half_width_m, body_rotation_radius_m=B.rotation_radius_m,
        body_ultrasonic_x_m=B.ultrasonic_x_m)


# --- the LiDAR-origin rule (no URDF body) ---------------------------------------------


def test_backward_refuses_when_the_rear_is_blocked_and_forward_still_needs_its_front(core):
    client, services = core
    services.loc_mission.observe_scan(_scan(services, front_m=0.2))       # only the front near
    assert _start(client).status_code == 202                              # the rear is clear
    services.loc_mission.end("cancelled")
    forward = _start(client, "nudge_forward")
    assert forward.status_code == 409 and _code(forward) == "path_not_clear"
    services.loc_mission.observe_scan(_scan(services, front_m=0.4, rear_m=0.2))   # only the rear near
    assert _start(client, "nudge_forward").status_code == 202             # the front is clear
    services.loc_mission.end("cancelled")
    refused = _start(client)
    assert refused.status_code == 409 and _code(refused) == "path_not_clear"
    assert "rear clearance" in refused.json()["error"]["message"]


@pytest.mark.parametrize("rear_m", [math.inf, 0.03, math.nan])
def test_backward_treats_a_rear_it_cannot_measure_as_blocked(core, rear_m):
    """inf, NaN or below range_min (0.05 here) across the rear: something may be too close."""
    client, services = core
    services.loc_mission.observe_scan(_scan(services, rear_m=rear_m, within_deg=25.0))
    assert _code(_start(client)) == "path_not_clear"


@pytest.mark.parametrize("distance", [0.11, 0.0])
def test_backward_never_exceeds_the_nudge_maximum(core, distance):
    client, _services = core
    assert _start(client, distance=distance).status_code == 400


def test_backward_commands_negative_linear_velocity_and_stops_at_its_distance(core):
    client, services = core
    assert _start(client, distance=0.03).status_code == 202
    _step(services, odom=(0.0, 0.0, 0.0))
    out = services.command.select_output()
    linear = services.loc_mission.config.nudge_linear
    assert out.angular == 0.0 and -linear <= out.linear < 0.0
    for i in range(1, 20):
        _step(services, odom=(-0.003 * i, 0.0, 0.0))
    assert client.get(PATH, headers=VIEWER).json() == {
        "kind": "nudge_backward", "state": "done", "reason": "done"}
    assert services.command.select_output().linear == 0.0


def test_backward_stops_for_an_obstacle_behind(core):
    client, services = core
    assert _start(client, distance=0.10).status_code == 202
    _step(services, odom=(-0.01, 0.0, 0.0))
    services.loc_mission.observe_scan(_scan(services, rear_m=0.2))
    services.loc_mission.tick()
    assert client.get(PATH, headers=VIEWER).json() == {
        "kind": "nudge_backward", "state": "aborted", "reason": "obstacle"}
    assert services.command.select_output().linear == 0.0


# --- D-424 with the URDF body ----------------------------------------------------------


def test_backward_shortens_to_the_room_before_the_rear_stop_gap(core):
    """g(0.03) ~0.025 m (0.084 m from the LiDAR to the rear edge); 0.15 leaves 0.0655 m."""
    client, services = core
    _with_pinky_body(services)
    services.loc_mission.observe_scan(_scan(services, rear_m=0.15, within_deg=1.0))
    assert _start(client, distance=0.05).status_code == 202
    assert services.loc_mission._run.max_distance_m == 0.05
    services.loc_mission.end("cancelled")
    assert _start(client, distance=0.10).status_code == 202
    assert services.loc_mission._run.max_distance_m == pytest.approx(0.0655, abs=1e-3)


def test_backward_is_refused_when_the_rear_room_is_under_nudge_min(core):
    client, services = core
    _with_pinky_body(services)
    services.loc_mission.observe_scan(_scan(services, rear_m=0.09, within_deg=1.0))
    refused = _start(client, distance=0.05)
    assert refused.status_code == 409 and _code(refused) == "path_not_clear"
    assert "room before the stop gap" in refused.json()["error"]["message"]


def test_backward_stops_when_a_wall_reaches_the_rear_stop_gap_mid_run(core):
    client, services = core
    _with_pinky_body(services)
    assert _start(client, distance=0.10).status_code == 202
    _step(services, odom=(-0.01, 0.0, 0.0))
    assert services.loc_mission._run is not None
    services.loc_mission.observe_scan(_scan(services, rear_m=0.08, within_deg=1.0))
    services.loc_mission.tick()
    assert client.get(PATH, headers=VIEWER).json()["reason"] == "obstacle"


def test_forward_shortening_is_unchanged_with_the_body(core):
    client, services = core
    _with_pinky_body(services)
    services.loc_mission.observe_scan(_scan(services, front_m=0.15, within_deg=1.0))
    assert _start(client, "nudge_forward", distance=0.10).status_code == 202
    assert services.loc_mission._run.max_distance_m == pytest.approx(0.0655, abs=1e-3)


# --- a nudge is also an operator step on a LOCALIZED robot ------------------------------


def test_a_localized_robot_may_still_step_but_not_rotate(core):
    client, services = core
    services.localization.on_state(_state("LOCALIZED"))
    rotate = client.post(PATH, headers=OPERATOR, json={"kind": "rotate_in_place",
                                                       "max_distance_m": 0.0, "max_time_s": 30.0})
    assert rotate.status_code == 409 and _code(rotate) == "localized"
    assert _start(client).status_code == 202
    assert services.loc_mission._run.search is False


def test_a_step_started_localized_runs_to_its_distance_instead_of_ending_on_it(core):
    client, services = core
    services.localization.on_state(_state("LOCALIZED"))
    assert _start(client, distance=0.03).status_code == 202
    for i in range(20):
        _step(services, odom=(-0.003 * (i + 1), 0.0, 0.0))
        if services.loc_mission._run is None:
            break
    assert client.get(PATH, headers=VIEWER).json() == {
        "kind": "nudge_backward", "state": "done", "reason": "done"}


def test_a_search_nudge_started_unlocalized_still_ends_on_localized(core):
    client, services = core
    assert _start(client).status_code == 202
    assert services.loc_mission._run.search is True
    _step(services, odom=(-0.01, 0.0, 0.0))
    services.localization.on_state(_state("LOCALIZED"))
    assert client.get(PATH, headers=VIEWER).json()["reason"] == "localized"


def test_the_front_self_mask_never_hides_a_return_behind_the_robot(core):
    """Review 11-15: the mask is drawn in the front frame; rotated onto the rear sector it hid a
    real 0.2 m return behind the robot. The rear sector is now judged unmasked."""
    client, services = core
    lf = services.line_follow
    lf._config = dataclasses.replace(lf.config, lidar_self_mask=((-15.0, 15.0, 0.3),))
    services.loc_mission.observe_scan(_scan(services, rear_m=0.2))
    refused = _start(client)
    assert refused.status_code == 409 and "rear clearance" in refused.json()["error"]["message"]


def test_a_later_localized_event_does_not_cut_a_step_short(core):
    client, services = core
    services.localization.on_state(_state("LOCALIZED"))
    assert _start(client, distance=0.05).status_code == 202
    services.loc_mission.localized()
    assert services.loc_mission._run is not None and services.loc_mission._run.search is False
