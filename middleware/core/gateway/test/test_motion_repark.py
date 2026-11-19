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
