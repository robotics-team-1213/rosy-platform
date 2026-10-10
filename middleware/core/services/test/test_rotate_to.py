"""D-603: the CORE rotate-to-heading turn law and its mission (tolerance, timeout, clearance refusal,
guard stops, LOCALIZED neither refuses nor ends it). Pure: fakes for CORE's ports, no ROS, no motion."""

from __future__ import annotations

import math
import threading
from types import SimpleNamespace

import pytest

from core_common.protocol.localization import LocState
from core_features.command.arbitration import Mode, ModeMachine
from core_features.line_follow.model import LineFollowConfig
from core_features.localization.mission import LocalizationMission, MissionConfig, MissionRefused
from core_features.localization.rotate_to import rotate_goal, turn_rate

BODY = dict(body_front_x_m=.08, body_rear_x_m=-.08, body_half_width_m=.06, body_lidar_x_m=0.,
            body_rotation_radius_m=.1)


def _scan(rest_m: float = 1.0, near_m: float | None = None) -> dict:
    ranges = [rest_m] * 360
    if near_m is not None:
        ranges[90] = near_m
    return {"ranges": ranges, "angle_min": 0.0, "angle_max": math.radians(359.0),
            "range_min": 0.05, "range_max": 8.0}


class Rig:
    def __init__(self, *, localized=False, busy=None):
        self.now = 100.0
        self.twists: list = []
        self.modes = ModeMachine()
        self.safety = SimpleNamespace(estop=False, set_session_speed=lambda v: None)
        command = SimpleNamespace(set_nav_twist=lambda t: self.twists.append(t),
                                  clear_navigation=lambda: self.twists.append(None))
        state = SimpleNamespace(set_mode=lambda m: None, set_line_follow=lambda s: None)
        status = SimpleNamespace(state=LocState.LOCALIZED if localized else LocState.CANDIDATES, reason=None)
        self.loc = SimpleNamespace(status=lambda: status, gate=threading.RLock())
        line = SimpleNamespace(config=LineFollowConfig(**BODY), active=False)
        events = SimpleNamespace(publish=lambda *a, **k: None)
        self.m = LocalizationMission(events, command=command, modes=self.modes, state=state,
                                     safety=self.safety, line_follow=line, traffic_policy=None,
                                     localization=self.loc, busy=busy or (lambda: None),
                                     config=MissionConfig(), clock=lambda: self.now)
        self.yaw = 0.0
        self.feed()

    def feed(self, scan=None):
        self.m.observe_odom(0.0, 0.0, self.yaw)
        self.m.observe_scan(scan or _scan())

    def step(self, dt=0.05, scale=1.0, scan=None):
        """One 20 Hz tick, then the robot turns by the commanded rate (scaled: odom vs wheel)."""
        self.m.tick()
        twist = self.twists[-1] if self.twists else None
        self.now += dt
        if twist is not None:
            self.yaw += twist.angular * dt * scale
        self.feed(scan)


def test_goal_bounds():
    goal = rotate_goal(0.0, delta_deg=-90.0)
    assert goal.delta_rad == pytest.approx(-math.pi / 2) and goal.tol_rad == pytest.approx(math.radians(5))
    assert rotate_goal(3.0, yaw_odom=-3.0).delta_rad == pytest.approx(2 * math.pi - 6.0)
    for bad in (dict(), dict(delta_deg=10, yaw_odom=0.0), dict(delta_deg=181), dict(delta_deg=10, max_rate_dps=31),
                dict(delta_deg=10, timeout_s=16), dict(delta_deg=10, tol_deg=0.5), dict(delta_deg=math.nan)):
        with pytest.raises(ValueError):
            rotate_goal(0.0, **bad)


def test_turn_law_slows_near_the_goal_and_turns_back_an_overshoot():
    goal = rotate_goal(0.0, delta_deg=90.0, max_rate_dps=30.0)
    assert turn_rate(goal, 0.0, gain=1.5, min_rate=0.15) == pytest.approx(math.radians(30))
    assert turn_rate(goal, math.radians(80), gain=1.5, min_rate=0.15) == pytest.approx(1.5 * math.radians(10))
    assert turn_rate(goal, math.radians(84.5), gain=1.5, min_rate=0.15) == pytest.approx(0.15)
    assert turn_rate(goal, math.radians(87), gain=1.5, min_rate=0.15) is None
    assert turn_rate(goal, math.radians(97), gain=1.5, min_rate=0.15) < 0


def test_turn_ends_done_within_tolerance_and_leaves_idle():
    rig = Rig(localized=True)  # LOCALIZED neither refuses nor ends a turn
    rig.m.start_rotate_to(delta_deg=-60.0)
    assert rig.modes.mode is Mode.NAVIGATION and rig.m.owns_wheels
    for _ in range(200):
        rig.step()
        if rig.m.status()["state"] != "running":
            break
    status = rig.m.status()
    assert status["state"] == "done" and status["reason"] == "done" and abs(status["final_err_deg"]) <= 5.0
    assert rig.modes.mode is Mode.IDLE and rig.twists[-1] is None
    assert math.degrees(rig.yaw) == pytest.approx(-60.0, abs=5.0)
    assert all(abs(t.angular) <= math.radians(20.0) + 1e-9 for t in rig.twists if t is not None)


def test_odom_over_rotation_shows_as_real_heading_error_for_fleet_to_correct():
    rig = Rig()
    rig.m.start_rotate_to(delta_deg=90.0)
    real = 0.0
    for _ in range(300):
        before = rig.yaw
        rig.step()
        real += (rig.yaw - before) / 1.1   # odom reads 10 % more than the wheels turned
        if rig.m.status()["state"] != "running":
            break
    assert rig.m.status()["state"] == "done" and math.degrees(real) < 85.0


def test_timeout_and_overturn_abort():
    rig = Rig()
    rig.m.start_rotate_to(delta_deg=90.0, timeout_s=1.0)
    for _ in range(30):
        rig.step(scale=0.0)   # wheels do not move
    assert rig.m.status()["reason"] == "timeout" and rig.m.status()["state"] == "aborted"
    rig = Rig()
    rig.m.start_rotate_to(delta_deg=10.0)
    for _ in range(100):
        rig.step(scale=-1.0)  # odom turns the other way: never converges
        if rig.m.status()["state"] != "running":
            break
    assert rig.m.status()["reason"] == "overturn"


def test_refusals_before_any_motion():
    rig = Rig()
    rig.feed(_scan(near_m=0.11))
    with pytest.raises(MissionRefused) as err:
        rig.m.start_rotate_to(delta_deg=30.0)
    assert err.value.code == "ROTATE_CLEARANCE"
    assert err.value.detail == {"nearest_m": pytest.approx(0.11, abs=1e-3), "need_m": pytest.approx(0.13)}
    rig = Rig(busy=lambda: "line follow is active")
    with pytest.raises(MissionRefused, match="line follow") as err:
        rig.m.start_rotate_to(delta_deg=30.0)
    assert err.value.code == "MOTION_BUSY"
    rig = Rig()
    rig.safety.estop = True
    with pytest.raises(MissionRefused) as err:
        rig.m.start_rotate_to(delta_deg=30.0)
    assert err.value.code == "EMERGENCY_ACTIVE"
    rig = Rig()
    rig.now += 1.0  # odometry 1 s old
    with pytest.raises(MissionRefused) as err:
        rig.m.start_rotate_to(delta_deg=30.0)
    assert err.value.code == "ODOMETRY_STALE"
    rig = Rig()
    rig.m.start_rotate_to(delta_deg=30.0)
    with pytest.raises(MissionRefused) as err:
        rig.m.start_rotate_to(delta_deg=30.0)
    assert err.value.code == "MOTION_BUSY"


@pytest.mark.parametrize("guard,reason", [("estop", "estop"), ("obstacle", "obstacle"), ("mode", "cancelled"),
                                          ("lidar", "obstacle_sensor_stale")])
def test_guards_stop_a_running_turn(guard, reason):
    rig = Rig()
    rig.m.start_rotate_to(delta_deg=120.0)
    rig.step()
    if guard == "estop":
        rig.safety.estop = True
    elif guard == "obstacle":
        rig.feed(_scan(near_m=0.105))
    elif guard == "mode":
        rig.modes.transition(Mode.IDLE)
    else:
        rig.m.observe_odom(0.0, 0.0, rig.yaw)
        rig.now += 1.0
        rig.m.observe_odom(0.0, 0.0, rig.yaw)
    rig.m.tick()
    assert rig.m.status()["state"] == "aborted" and rig.m.status()["reason"] == reason
    assert rig.twists[-1] is None


def test_localized_ends_a_search_mission_but_not_a_turn():
    rig = Rig()
    rig.m.start_rotate_to(delta_deg=90.0)
    rig.m.localized()
    assert rig.m.status()["state"] == "running"
    rig.m.end("cancelled")
    rig.m.start("rotate_in_place", 0.0, 30.0)
    rig.m.localized()
    assert rig.m.status() == {"kind": "rotate_in_place", "state": "done", "reason": "localized"}
