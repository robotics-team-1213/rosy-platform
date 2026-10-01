"""D-395 P2-7: CORE's check manoeuvre and homing missions (contract §2).

`services.loc_mission` is fed odometry and LiDAR the way the bridge feeds it and
ticked like the bridge's 20 Hz timer; the wheels are what `CommandManager.
select_output` (the 50 Hz final arbiter) returns.
"""

from __future__ import annotations

import json
import math
import threading

import pytest

VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}
OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}
ADMIN = {"Authorization": "Bearer rosy-dev-admin"}
PATH = "/api/v1/localization/mission"


class _Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _state(state="CANDIDATES", frame="map", request_id="req-1") -> str:
    return json.dumps({"status": {"state": state, "pose_frame": frame,
                                  "request_id": request_id if state == "CANDIDATES" else None},
                       "pose": None, "stamp": 1.0})


def _scan(services, front_m: float = 2.0, *, within_deg: float = 10.0, rest_m: float = 2.0) -> dict:
    """360 one-degree beams at `rest_m`, `front_m` within `within_deg` of the robot's front."""
    forward = services.line_follow.config.lidar_forward_deg
    ranges = []
    for i in range(360):
        offset = (i - forward + 180.0) % 360.0 - 180.0
        ranges.append(front_m if abs(offset) <= within_deg else rest_m)
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


def _start(client, kind="rotate_in_place", distance=0.0, time_s=30.0, headers=OPERATOR, target=None):
    return client.post(PATH, headers=headers, json={"kind": kind, "max_distance_m": distance,
                                                    "max_time_s": time_s, "target": target})


def _code(response) -> str:
    return response.json()["error"]["code"]


def _events(services, phase=None):
    rows = [e.data for e in services.events.history() if e.type == "localization.mission"]
    return [row for row in rows if phase is None or row["phase"] == phase]


def _step(services, dt=0.05, odom=None):
    services.clock.now += dt
    if odom is not None:
        services.loc_mission.observe_odom(*odom)
    services.loc_mission.observe_scan(services.loc_mission._scan[0])
    services.loc_mission.tick()


# --- refusals -------------------------------------------------------------------------


def test_a_localized_robot_is_refused(core):
    client, services = core
    services.localization.on_state(_state("LOCALIZED"))
    refused = _start(client)
    assert refused.status_code == 409 and _code(refused) == "localized"
    assert services.modes.mode.value == "IDLE" and _events(services) == []


def test_a_pre_d395_robot_answers_501(core_client):
    client, _services = core_client()
    assert _start(client).status_code == 501


def test_estop_is_refused(core):
    client, services = core
    services.safety.trigger_estop("test")
    refused = _start(client)
    assert refused.status_code == 409 and _code(refused) == "estop"


def test_a_robot_in_manual_or_already_on_a_mission_is_busy(core):
    client, services = core
    assert _start(client).status_code == 202
    again = _start(client)
    assert again.status_code == 409 and _code(again) == "busy"
    services.loc_mission.end("cancelled")
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OPERATOR).status_code == 200
    manual = _start(client)
    assert manual.status_code == 409 and _code(manual) == "busy"


def test_nudge_needs_a_clear_front(core):
    client, services = core
    services.loc_mission.observe_scan(_scan(services, front_m=0.2))
    refused = _start(client, "nudge_forward", 0.05)
    assert refused.status_code == 409 and _code(refused) == "path_not_clear"
    services.loc_mission.observe_scan(_scan(services, front_m=0.4))
    assert _start(client, "nudge_forward", 0.05).status_code == 202


def test_no_fresh_scan_is_not_a_clear_path(core):
    client, services = core
    services.clock.now += 1.0
    refused = _start(client)
    assert refused.status_code == 409 and _code(refused) == "path_not_clear"


@pytest.mark.parametrize("kind,distance,time_s", [
    ("nudge_forward", 0.11, 10.0), ("nudge_forward", 0.0, 10.0), ("rotate_in_place", 0.0, 0.0),
    ("rotate_in_place", 0.0, 121.0), ("lane_to_stopline", 1.5, 30.0), ("fly", 0.0, 10.0)])
def test_bounds_are_validated(core, kind, distance, time_s):
    client, _services = core
    assert _start(client, kind, distance, time_s).status_code == 400


def test_to_square_is_unsupported(core):
    client, services = core
    refused = _start(client, "to_square", 0.5, 30.0, target={"square": [0.86, -0.52]})
    assert refused.status_code == 409 and _code(refused) == "unsupported"
    assert "follow-up" in refused.json()["error"]["message"]
    assert services.modes.mode.value == "IDLE"


# --- auth and lease -------------------------------------------------------------------


def test_start_needs_localize_assist_and_status_is_viewer(core):
    client, _services = core
    forbidden = _start(client, headers=VIEWER)
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["detail"] == {"capability": "LOCALIZE_ASSIST"}
    assert client.get(PATH, headers=VIEWER).json() == {"kind": None, "state": "idle", "reason": None}


def test_a_calibration_lease_refuses_others_but_not_its_owner(core):
    client, _services = core
    opened = client.post("/api/v1/calibration/session", headers=ADMIN,
                         json={"kind": "drive", "label": "drive", "ttl_s": 30})
    assert opened.status_code in (200, 201)
    refused = _start(client)
    assert refused.status_code == 409 and _code(refused) == "calibration_lease"
    assert _start(client, headers=ADMIN).status_code == 202


# --- running: the final arbiter, bounds and ends ------------------------------------


def test_rotate_turns_through_the_final_arbiter_until_one_turn(core):
    client, services = core
    started = _start(client)
    assert started.status_code == 202 and started.json()["state"] == "running"
    assert services.modes.mode.value == "NAVIGATION"
    _step(services, odom=(0.0, 0.0, 0.0))
    out = services.command.select_output()
    assert out.linear == 0.0 and 0.0 < out.angular <= services.loc_mission.config.rotate_angular
    yaw = 0.0
    for _ in range(40):                      # 40 x 0.16 rad > 2 pi
        yaw += 0.16
        _step(services, odom=(0.0, 0.0, yaw))
    assert services.modes.mode.value == "IDLE"
    assert services.command.select_output().angular == 0.0
    assert client.get(PATH, headers=VIEWER).json() == {
        "kind": "rotate_in_place", "state": "done", "reason": "done"}
    assert [e["phase"] for e in _events(services)] == ["started", "done"]
    assert services.published == [
        {"kind": "rotate_in_place", "state": "running", "reason": None},
        {"kind": "rotate_in_place", "state": "done", "reason": "done"}]


def test_a_mission_times_out(core):
    client, services = core
    assert _start(client, time_s=1.0).status_code == 202
    for _ in range(25):
        _step(services, odom=(0.0, 0.0, 0.0))
    assert client.get(PATH, headers=VIEWER).json()["reason"] == "timeout"
    assert services.modes.mode.value == "IDLE"


def test_stale_odometry_aborts(core):
    client, services = core
    assert _start(client).status_code == 202
    for _ in range(12):
        _step(services)                       # no odometry
    assert client.get(PATH, headers=VIEWER).json() == {
        "kind": "rotate_in_place", "state": "aborted", "reason": "odometry_stale"}


def test_nudge_stops_at_its_distance(core):
    client, services = core
    assert _start(client, "nudge_forward", 0.05).status_code == 202
    _step(services, odom=(0.0, 0.0, 0.0))
    out = services.command.select_output()
    assert out.angular == 0.0 and 0.0 < out.linear <= services.loc_mission.config.nudge_linear
    for i in range(1, 30):
        _step(services, odom=(0.003 * i, 0.0, 0.0))
    assert client.get(PATH, headers=VIEWER).json()["reason"] == "done"
    assert services.command.select_output().linear == 0.0


def test_nudge_stops_for_an_obstacle(core):
    client, services = core
    assert _start(client, "nudge_forward", 0.10).status_code == 202
    _step(services, odom=(0.01, 0.0, 0.0))
    services.loc_mission.observe_scan(_scan(services, front_m=0.2))
    services.loc_mission.tick()
    assert client.get(PATH, headers=VIEWER).json() == {
        "kind": "nudge_forward", "state": "aborted", "reason": "obstacle"}
    assert services.command.select_output().linear == 0.0


def test_localized_ends_the_mission_at_once(core):
    client, services = core
    assert _start(client).status_code == 202
    _step(services, odom=(0.0, 0.0, 0.1))
    services.localization.on_state(_state("LOCALIZED"))
    assert client.get(PATH, headers=VIEWER).json()["reason"] == "localized"
    assert services.modes.mode.value == "IDLE"
    assert services.command.select_output().angular == 0.0


def test_estop_ends_the_mission(core):
    client, services = core
    assert _start(client).status_code == 202
    _step(services, odom=(0.0, 0.0, 0.1))
    assert client.post("/api/v1/safety/stop", headers=OPERATOR).status_code == 200
    assert services.command.select_output().angular == 0.0
    assert client.get(PATH, headers=VIEWER).json()["reason"] == "estop"


def test_a_manual_takeover_cancels_the_mission(core):
    client, services = core
    assert _start(client).status_code == 202
    _step(services, odom=(0.0, 0.0, 0.1))
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OPERATOR).status_code == 200
    assert client.get(PATH, headers=VIEWER).json()["reason"] == "cancelled"
    assert services.modes.mode.value == "MANUAL"


def test_nav2_output_is_dropped_while_a_mission_owns_the_wheels(core):
    client, services = core
    from core.bridge import docking_mode
    from core_features.command.manager import Twist
    assert _start(client).status_code == 202
    assert docking_mode.route_nav_cmd_vel(services, Twist(0.2, 0.0)) is False


# --- lane_to_stopline -------------------------------------------------------------


def test_lane_mission_starts_line_follow_without_localized_and_crawls(core):
    client, services = core
    assert _start(client, "lane_to_stopline", 0.3).status_code == 202
    assert services.line_follow.active and services.line_follow.mode.value == "CAMERA_LINE"
    assert services.safety.session_linear == services.loc_mission.config.lane_linear
    for i in range(1, 40):
        _step(services, odom=(0.01 * i, 0.0, 0.0))
    assert client.get(PATH, headers=VIEWER).json() == {
        "kind": "lane_to_stopline", "state": "done", "reason": "done"}
    assert not services.line_follow.active and services.safety.session_linear is None
    assert services.modes.mode.value == "IDLE"


def test_lane_mission_ends_at_a_stop_line(core):
    client, services = core
    from core_features.traffic_policy import RoadEvidence
    assert _start(client, "lane_to_stopline", 0.6).status_code == 202
    _step(services, odom=(0.01, 0.0, 0.0))
    services.traffic_policy.observe(RoadEvidence(
        source="CAMERA_ROAD", stamp=services.clock.now, map_id="m", scene_revision="s",
        stop_line_visible=True, stop_line_distance_m=0.10, stop_line_confidence=0.9))
    services.traffic_policy.gate(0.04, 0.0)    # the line-follow tick refreshes the status
    _step(services, odom=(0.02, 0.0, 0.0))
    assert client.get(PATH, headers=VIEWER).json()["reason"] == "stop_line"
    assert not services.line_follow.active


def test_line_follow_off_cancels_the_lane_mission(core):
    client, services = core
    assert _start(client, "lane_to_stopline", 0.3).status_code == 202
    assert client.put("/api/v1/line-follow/mode", headers=OPERATOR,
                      json={"mode": "OFF"}).status_code == 200
    assert client.get(PATH, headers=VIEWER).json()["reason"] == "cancelled"
    assert services.safety.session_linear is None


def test_the_public_lane_route_stays_gated(core):
    client, _services = core
    refused = client.put("/api/v1/line-follow/mode", headers=OPERATOR, json={"mode": "CAMERA_LINE"})
    assert refused.status_code == 409 and _code(refused) == "NOT_LOCALIZED"


# --- the halt lock ---------------------------------------------------------------


def test_a_start_waits_for_the_localization_gate(core):
    """A state change holds the gate while it lands; a start checks under the same gate,
    so LOCALIZED arriving meanwhile refuses the start instead of racing it."""
    client, services = core
    result: dict = {}
    with services.localization.gate:
        worker = threading.Thread(target=lambda: result.setdefault("r", _start(client)), daemon=True)
        worker.start()
        worker.join(timeout=0.3)
        assert worker.is_alive()                      # blocked on the gate
        services.localization.on_state(_state("LOCALIZED"))
    worker.join(timeout=5.0)
    assert result["r"].status_code == 409 and _code(result["r"]) == "localized"
    assert services.modes.mode.value == "IDLE"


def test_leaving_localized_halt_does_not_run_while_missions_are_idle(core):
    client, services = core
    services.localization.on_state(_state("LOCALIZED"))
    services.localization.on_state(_state("SUSPECT"))
    assert _start(client).status_code == 202          # SUSPECT: missions allowed
    assert services.modes.mode.value == "NAVIGATION"


# --- review fixes: blind spots, rotate guard, cleared slot, staleness for every kind -----


@pytest.mark.parametrize("front_m", [math.inf, 0.03, math.nan])
def test_nudge_treats_a_front_it_cannot_measure_as_blocked(core, front_m):
    """inf, NaN or below range_min (0.05 here) across the front: something may be too close to see."""
    client, services = core
    services.loc_mission.observe_scan(_scan(services, front_m=front_m, within_deg=25.0))
    refused = _start(client, "nudge_forward", 0.05)
    assert refused.status_code == 409 and _code(refused) == "path_not_clear"


def test_nudge_stops_when_the_front_goes_blind_mid_run(core):
    client, services = core
    assert _start(client, "nudge_forward", 0.10).status_code == 202
    _step(services, odom=(0.01, 0.0, 0.0))
    services.loc_mission.observe_scan(_scan(services, front_m=math.inf, within_deg=25.0))
    services.loc_mission.tick()
    assert client.get(PATH, headers=VIEWER).json()["reason"] == "obstacle"
    assert services.command._nav_twist is None


def test_nudge_ignores_its_own_body_in_the_self_mask(core):
    import dataclasses
    client, services = core
    services.loc_mission.observe_scan(_scan(services, front_m=0.10, within_deg=4.0))
    assert _code(_start(client, "nudge_forward", 0.05)) == "path_not_clear"     # not masked: blocked
    lf = services.line_follow
    lf._config = dataclasses.replace(lf.config, lidar_self_mask=((-5.0, 5.0, 0.12),))
    services.loc_mission.observe_scan(_scan(services, front_m=0.10, within_deg=4.0))
    assert _start(client, "nudge_forward", 0.05).status_code == 202


def test_rotate_is_refused_with_anything_within_20_cm(core):
    client, services = core
    sample = _scan(services)
    sample["ranges"][90] = 0.15                         # beside the robot, not in front
    services.loc_mission.observe_scan(sample)
    refused = _start(client)
    assert refused.status_code == 409 and _code(refused) == "path_not_clear"
    sample = {**sample, "ranges": [*sample["ranges"][:90], 0.30, *sample["ranges"][91:]]}
    services.loc_mission.observe_scan(sample)           # each scan is a new sample
    assert _start(client).status_code == 202


@pytest.mark.parametrize("kind,distance", [("rotate_in_place", 0.0), ("lane_to_stopline", 0.3)])
def test_a_stale_lidar_ends_every_kind(core, kind, distance):
    client, services = core
    assert _start(client, kind, distance).status_code == 202
    for _ in range(12):                                  # odometry fresh, LiDAR silent
        services.clock.now += 0.05
        services.loc_mission.observe_odom(0.0, 0.0, 0.0)
        services.loc_mission.tick()
    assert client.get(PATH, headers=VIEWER).json()["reason"] == "obstacle_sensor_stale"
    assert services.command._nav_twist is None


@pytest.mark.parametrize("end", ["done", "timeout", "localized", "estop", "cancelled"])
def test_every_end_clears_the_velocity_slot(core, end):
    client, services = core
    from core_features.command.arbitration import Mode
    assert _start(client).status_code == 202
    _step(services, odom=(0.0, 0.0, 0.1))
    assert services.command._nav_twist is not None
    services.loc_mission.end(end)
    assert services.command._nav_twist is None
    if services.modes.mode is Mode.IDLE:               # the slot, not just the mode, is empty
        services.modes.transition(Mode.NAVIGATION)
        assert services.command.select_output().angular == 0.0


def test_the_bridge_ticks_missions_on_the_line_clock():
    """Under use_sim_time the line clock is the ROS clock; the mission must run on it too."""
    import ast
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "core" / "bridge" / "ros_bridge.py").read_text(
        encoding="utf-8")
    calls = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)
             and getattr(node.func, "attr", None) == "bind_clock"
             and "loc_mission" in ast.unparse(node.func)]
    assert [ast.unparse(c.args[0]) for c in calls] == ["self._line_clock"]
