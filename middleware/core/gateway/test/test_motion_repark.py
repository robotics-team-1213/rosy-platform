"""Fine re-park (D-1050): plan limits, the API admission, and the closed-loop sequence on simulated odometry."""

from __future__ import annotations

import math

import pytest

from core_features.localization.repark import MAX_RATE_RPS, MAX_SPEED_MPS, plan_repark
from test_localization_mission import OPERATOR, VIEWER, _scan, _state, core  # noqa: F401

PATH = "/api/v1/motion/repark"
NAMED = {"forward_m": 0.0, "left_m": 0.038, "operator_name": "kim"}


def test_plan_matches_the_measured_shift():
    kinds = [k for k, _ in plan_repark(0.0, 0.038)]
    assert kinds[:3] == ["turn", "drive", "restore"]
    turn, leg = plan_repark(0.0, 0.038)[:2]
    assert abs(math.sin(turn[1]) * leg[1] - 0.038) < 1e-9 and leg[1] <= 0.09
    assert plan_repark(0.0, -0.038)[0][1] < 0          # right shift turns right
    assert plan_repark(0.05, 0.0) == [("drive", 0.05)]


@pytest.mark.parametrize("fwd,left", [(0.0, 0.07), (0.11, 0.0), (0.0, 0.0), (-0.1, 0.06), (float("nan"), 0.0)])
def test_plan_refuses_beyond_the_caps(fwd, left):
    with pytest.raises(ValueError):
        plan_repark(fwd, left)


def test_the_heading_trim_ends_the_plan_and_is_bounded():
    assert plan_repark(0.0, 0.0, 10.0) == [("restore", pytest.approx(math.radians(10.0)))]
    assert plan_repark(0.05, 0.0, -5.0) == [("drive", 0.05), ("restore", pytest.approx(math.radians(-5.0)))]
    shifted = plan_repark(0.0, 0.038, 5.0)
    assert shifted[2] == ("restore", 0.0) and shifted[-1] == ("restore", pytest.approx(math.radians(5.0)))  # trim is last
    for bad in (25.1, -26.0, float("nan"), 0.5):  # past the cap, not a number, or below the 1 degree floor
        with pytest.raises(ValueError):
            plan_repark(0.0, 0.0, bad)
    with pytest.raises(ValueError):
        plan_repark(0.0, 0.0)  # nothing to move at all


def test_a_trim_only_repark_turns_in_place_to_start_heading_plus_trim(core):
    _client, services = core
    services.localization.on_state(_state("LOCALIZED"))
    services.loc_mission.observe_odom(0.0, 0.0, 0.0)
    services.loc_mission.repark.start(0.0, 0.0, 12.0)
    _run(services)
    status = services.loc_mission.repark.status()
    assert status["state"] == "done", status
    assert abs(services.loc_mission.odom_pose()[2] - math.radians(12.0)) < math.radians(1.5)
    assert abs(status["moved_robot_dxdy_m"]["forward_m"]) < 0.005 and abs(status["moved_robot_dxdy_m"]["left_m"]) < 0.005


def _run(services, limit_s=60.0):
    """Tick the bridge loop, integrating the arbiter's output into odometry; return the peak speeds."""
    x = y = yaw = 0.0
    peak_v = peak_w = 0.0
    dt = 0.05
    t = 0.0
    while t < limit_s and services.loc_mission.repark.status()["state"] == "running":
        out = services.command.select_output()
        peak_v, peak_w = max(peak_v, abs(out.linear)), max(peak_w, abs(out.angular))
        yaw += out.angular * dt
        x += out.linear * math.cos(yaw) * dt
        y += out.linear * math.sin(yaw) * dt
        services.clock.now += dt
        t += dt
        services.loc_mission.observe_odom(x, y, yaw)
        services.loc_mission.observe_scan(services.loc_mission._scan[0])
        services.loc_mission.tick()
    return peak_v, peak_w


def test_the_shift_closes_on_odometry_within_the_speed_caps(core):
    client, services = core
    services.localization.on_state(_state("LOCALIZED"))
    started = client.post(PATH, json=NAMED, headers=OPERATOR)
    assert started.status_code == 202, started.text
    peak_v, peak_w = _run(services)
    status = client.get(PATH, headers=VIEWER).json()
    assert status["state"] == "done", status
    moved = status["moved_robot_dxdy_m"]
    assert abs(moved["left_m"] - 0.038) < 0.008 and abs(moved["forward_m"]) < 0.008
    assert peak_v <= MAX_SPEED_MPS + 1e-9 and peak_w <= MAX_RATE_RPS + 1e-9
    assert services.modes.mode.value == "IDLE"


def test_an_obstacle_mid_sequence_stops_and_reports_aborted(core):
    client, services = core
    services.localization.on_state(_state("LOCALIZED"))
    assert client.post(PATH, json=NAMED, headers=OPERATOR).status_code == 202
    services.loc_mission.observe_scan(_scan(services, front_m=0.06, rest_m=0.06))
    services.loc_mission._scan = (services.loc_mission._scan[0], services.clock.now)
    _run(services, limit_s=5.0)
    status = client.get(PATH, headers=VIEWER).json()
    assert status["state"] == "aborted" and status["reason"]
    assert services.command.select_output().angular == 0.0 and services.modes.mode.value == "IDLE"


def test_a_lease_end_stops_a_reparking_robot(core):
    client, services = core
    services.localization.on_state(_state("LOCALIZED"))
    assert client.post(PATH, json=NAMED, headers=OPERATOR).status_code == 202
    services.trip_lease.halt("expired")
    status = client.get(PATH, headers=VIEWER).json()
    assert status["state"] == "aborted" and status["reason"] == "cancelled"
    assert services.command.select_output().angular == 0.0 and services.command.select_output().linear == 0.0


def _open_lease(client, lease_id, **extra):
    response = client.put("/api/v1/trip-lease", headers=OPERATOR, json={
        "lease_id": lease_id, "trip_id": lease_id, "operator_name": "test", "holder": "test",
        "ttl_s": 5.0, **extra,
    })
    assert response.status_code == 200, response.text


def test_lease_expiring_inside_admission_refuses_the_first_segment(core, monkeypatch):
    client, services = core
    services.trip_lease._monotonic = services.clock
    services.localization.on_state(_state("LOCALIZED"))
    _open_lease(client, "original", job_id="job")
    ready = services.nav.require_ready

    def finish_readiness_check():
        ready()
        services.clock.now += 5.0
        services.loc_mission.observe_odom(0.0, 0.0, 0.0)
        services.loc_mission.observe_scan(_scan(services))

    monkeypatch.setattr(services.nav, "require_ready", finish_readiness_check)
    response = client.post(PATH, json=NAMED, headers=OPERATOR)
    assert response.status_code == 409, response.text
    assert services.loc_mission.runs_started == 0


@pytest.mark.parametrize("replace", [False, True])
def test_a_later_segment_cannot_inherit_authority_from_a_name_or_a_new_trip(core, replace):
    client, services = core
    services.localization.on_state(_state("LOCALIZED"))
    _open_lease(client, "original")
    assert client.post(PATH, json=NAMED, headers=OPERATOR).status_code == 202
    mission = services.loc_mission
    mission.observe_odom(0.0, 0.0, mission.repark._plan[0][1])
    mission.end("done")  # IDLE releases the ordinary trip between legs.
    assert services.trip_lease.current() is None
    if replace:
        _open_lease(client, "replacement")
    mission.repark.tick()
    assert mission.repark.status()["state"] == "aborted"
    assert mission.runs_started == 1
    output = services.command.select_output()
    assert (output.linear, output.angular) == (0.0, 0.0)


def test_release_during_a_repark_leg_stops_the_next_wheel_command(core):
    client, services = core
    services.localization.on_state(_state("LOCALIZED"))
    _open_lease(client, "original", job_id="job")
    assert client.post(PATH, json=NAMED, headers=OPERATOR).status_code == 202
    mission = services.loc_mission
    mission.tick()
    assert services.command.select_output().angular != 0.0
    response = client.delete("/api/v1/trip-lease/original", headers=OPERATOR)
    assert response.status_code == 200, response.text
    mission.tick()
    assert mission.repark.status()["state"] == "aborted"
    output = services.command.select_output()
    assert (output.linear, output.angular) == (0.0, 0.0)


@pytest.mark.parametrize("final_odom", ["expired", "nonfinite", "clock_backwards"])
def test_done_requires_a_measured_final_pose(core, final_odom):
    client, services = core
    services.localization.on_state(_state("LOCALIZED"))
    assert client.post(PATH, json=dict(NAMED, forward_m=.03, left_m=0), headers=OPERATOR).status_code == 202
    mission = services.loc_mission
    mission.observe_odom(.03, 0.0, 0.0)
    mission.end("done")
    if final_odom == "expired":
        services.clock.now += mission.config.sensor_stale_s + .01
    elif final_odom == "nonfinite":
        mission.observe_odom(float("nan"), 0.0, 0.0)
    else:
        services.clock.now -= 1
    mission.repark.tick()
    assert client.get(PATH, headers=VIEWER).json() == {"state": "aborted", "reason": "odometry_stale"}
    receipt = client.get(PATH + "/run", headers=VIEWER).json()["operation"]
    assert (receipt["phase"], receipt["result"]) == ("TERMINAL", "FAILED")


@pytest.mark.parametrize("bad_pose", [(float("nan"), 0., 0.), (0., 0., float("inf"))])
def test_a_bad_odometry_sample_during_motion_invalidates_the_whole_leg(core, bad_pose):
    client, services = core
    services.localization.on_state(_state("LOCALIZED"))
    assert client.post(PATH, json=dict(NAMED, forward_m=.03, left_m=0), headers=OPERATOR).status_code == 202
    mission = services.loc_mission
    mission.tick()
    assert services.command.select_output().linear > 0
    mission.observe_odom(*bad_pose)
    mission.observe_odom(.03, 0., 0.)  # fresh again before the timer, but the leg lost continuity
    mission.tick()
    assert mission.repark.status()["reason"] == "odometry_stale"
    output = services.command.select_output()
    assert (output.linear, output.angular) == (0., 0.)


@pytest.mark.parametrize(("left", "expected"), [(.01496, "done"), (.01504, "aborted")])
def test_final_offset_uses_full_precision_before_formatting(core, left, expected):
    client, services = core
    mission = services.loc_mission
    services.localization.on_state(_state("LOCALIZED"))
    assert client.post(PATH, json=dict(NAMED, forward_m=.04, left_m=0), headers=OPERATOR).status_code == 202
    mission.observe_odom(.04, left, 0.)
    mission.tick()
    result = mission.repark.status()
    assert result["state"] == expected
    assert result["moved_robot_dxdy_m"] == {"forward_m": .04, "left_m": .015}


def test_named_operator_cannot_resume_after_an_intervening_trip(core):
    client, services = core
    services.localization.on_state(_state("LOCALIZED"))
    assert client.post(PATH, json=NAMED, headers=OPERATOR).status_code == 202
    _open_lease(client, "intervening", job_id="job")
    assert client.delete("/api/v1/trip-lease/intervening", headers=OPERATOR).status_code == 200
    services.loc_mission.tick()
    assert services.loc_mission.repark.status()["state"] == "aborted"


def test_job_lease_renewal_allows_all_repark_segments_to_finish(core):
    client, services = core
    services.localization.on_state(_state("LOCALIZED"))
    _open_lease(client, "job-lease", job_id="job")
    assert client.post(PATH, json={"left_m": .038}, headers=OPERATOR).status_code == 202
    _open_lease(client, "job-lease", job_id="job")
    _run(services)
    assert services.loc_mission.repark.status()["state"] == "done"
    assert services.loc_mission.runs_started == 4


def test_invalid_pose_before_mission_admission_prevents_nudge(core, monkeypatch):
    client, services = core
    services.localization.on_state(_state("LOCALIZED"))
    mission = services.loc_mission
    start = mission.start

    def invalidate_then_start(*args, **kwargs):
        mission.observe_odom(float("nan"), 0., 0.)
        return start(*args, **kwargs)

    monkeypatch.setattr(mission, "start", invalidate_then_start)
    response = client.post(PATH, json=dict(NAMED, forward_m=.03, left_m=0), headers=OPERATOR)
    assert response.status_code == 409 and response.json()["error"]["code"] == "ODOMETRY_STALE"
    assert mission.runs_started == 0


def test_unnamed_request_cannot_borrow_a_lease_opened_during_admission(core, monkeypatch):
    client, services = core
    services.localization.on_state(_state("LOCALIZED"))
    capture = services.trip_lease.repark_authority

    def capture_before_trip(token, name):
        original = capture(token, name)
        services.trip_lease.open(lease_id="later", trip_id="later", holder="test", operator_name="test",
                                 owner_id=token, ttl_s=5.)
        return original

    monkeypatch.setattr(services.trip_lease, "repark_authority", capture_before_trip)
    response = client.post(PATH, json={"left_m": .038}, headers=OPERATOR)
    assert response.status_code == 409 and services.loc_mission.runs_started == 0


def test_a_shortened_leg_stops_before_the_next_segment(core):
    client, services = core
    services.localization.on_state(_state("LOCALIZED"))
    assert client.post(PATH, json=NAMED, headers=OPERATOR).status_code == 202   # turn, drive, restore
    runner, mission = services.loc_mission.repark, services.loc_mission
    turn = runner._plan[0][1]
    mission.observe_odom(0.0, 0.0, turn)
    mission.end("done")                           # the turn finished
    runner.tick()
    assert runner.status()["state"] == "running" and mission.status()["kind"] == "nudge_forward"
    mission.observe_odom(0.01 * math.cos(turn), 0.01 * math.sin(turn), turn)   # the LiDAR cut the leg to 1 cm ...
    mission.end("done")                           # ... and the nudge still reports done
    runner.tick()
    status = runner.status()
    assert status["state"] == "aborted" and status["reason"] == "short_of_request"
    assert mission.status()["kind"] == "nudge_forward"   # the restore turn never started


def test_admission_and_refusals(core):
    client, services = core
    assert client.post(PATH, json={"left_m": 0.03}, headers=OPERATOR).status_code == 403
    assert client.post(PATH, json=NAMED, headers=VIEWER).status_code == 403
    too_far = client.post(PATH, json={**NAMED, "left_m": 0.08}, headers=OPERATOR)
    assert too_far.status_code == 400 and too_far.json()["error"]["code"] == "VALIDATION_ERROR"
    assert client.post(PATH, json=NAMED, headers=OPERATOR).status_code == 202
    busy = client.post(PATH, json=NAMED, headers=OPERATOR)
    assert busy.status_code == 409
    stopped = client.delete(PATH, headers=OPERATOR).json()
    assert stopped["state"] == "aborted" and services.modes.mode.value == "IDLE"


def test_a_foreign_mission_between_segments_is_not_ours_to_end_or_adopt(core):
    client, services = core
    services.localization.on_state(_state("LOCALIZED"))
    assert client.post(PATH, json=NAMED, headers=OPERATOR).status_code == 202
    runner, mission = services.loc_mission.repark, services.loc_mission
    mission.end("cancelled")                                    # our turn ends ...
    mission.start("nudge_forward", 0.05, 5.0)                   # ... and a foreign nudge takes the wheels
    runner.tick()
    assert runner.status()["state"] == "aborted" and runner.status()["reason"] == "segment_lost"
    assert mission.status()["state"] == "running"               # the foreign run was left alone
