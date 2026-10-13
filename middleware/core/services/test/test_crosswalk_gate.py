"""D-573 (c): the CORE crosswalk gate stops before a camera crosswalk zone, looks with the LiDAR and
crosses only after 5 s of continuous proof (rev 3); no timeout; a D-407 crosswalk_blocked stuck asks a human."""
import math
from pathlib import Path

import pytest

from core_common.protocol.lane_containment import LaneContainmentEvidence
from core_common.robot_body import PINKY_PRO
from core_features.line_follow import crosswalk_gate as gate_module
from core_features.line_follow.crosswalk_gate import CrosswalkGate, Scan, judge, scan_rays
from core_features.line_follow.manager import LineFollowManager
from core_features.line_follow.model import LineFollowConfig, LineFollowDecision, LineFollowMode, LineObservation
from core_features.line_follow.recovery.stuck.stuck_recovery import AnswerRefused

RANGE_MIN = 0.15     # D-573 Context 4: the Pinky LiDAR range_min
NEAR, FAR = 0.50, 0.70
B = PINKY_PRO
BODY = dict(body_front_x_m=B.front_x_m, body_rear_x_m=B.rear_x_m, body_half_width_m=B.half_width_m,
            body_rotation_radius_m=B.rotation_radius_m, body_lidar_x_m=B.lidar_x_m)


class Bus:
    def __init__(self):
        self.events = []

    def publish(self, name, **kwargs):
        self.events.append((name, kwargs.get("data") or {}))


def rays_at(x, objects, *, no_return=None, wall_m=1.5, step_deg=2):
    """Rays from the LiDAR at odom x (heading +x); objects are odom (x, y, radius) circles."""
    lx = x + B.lidar_x_m
    out = []
    for i in range(0, 360, step_deg):
        a = math.radians(i - 180)
        if no_return is not None and no_return(a):
            out.append((a, None))
            continue
        dx, dy, best = math.cos(a), math.sin(a), wall_m
        for ox, oy, r in objects:
            px, py = ox - lx, oy
            t = px * dx + py * dy
            d2 = px * px + py * py - t * t
            if t > 0 and d2 <= r * r:
                best = min(best, t - math.sqrt(r * r - d2))
        out.append((a, best))
    return tuple(out)


class Sim:
    def __init__(self, enabled=True, edges=None, xw_u=0.02, lat_u=0.005, **config):
        self.edges = edges          # (left, right) inner paint edges the camera reports, or None
        self.xw_u, self.lat_u = xw_u, lat_u   # crosswalk along-track bound (None = detector off), lane lateral
        self.t, self.x, self.linear = 1.0, 0.0, 0.0
        self.objects, self.no_return, self.scans = [], None, True
        self.bus = Bus()
        values = dict(BODY, obstacle_mode="path", crosswalk_gate_enabled=enabled)
        values.update(config)
        self.m = LineFollowManager(self.bus, clock=lambda: self.t, config=LineFollowConfig(**values))
        self.m.bind_recovery(calibration_active=lambda: False, console_linked=lambda: True,
                             linear_ceiling=lambda: 0.1)
        self.m.set_mode(LineFollowMode.CAMERA_LINE)
        self.tick_n = 0

    def frame(self, crosswalk=None, dt=0.05):
        self.t += dt
        self.x += self.linear * dt
        t, m = self.t, self.m
        m.observe_return_pose(stamp_ns=round(t * 1e9), source_now_ns=round(t * 1e9), frame="odom",
                              x=self.x, y=0.0, yaw=0.0, received_at=t)
        raw = dict(stamp=t, geometry_id="rig", ground_source="CALIBRATED", uncertainty_m=self.lat_u,
                   crosswalk_uncertainty_m=self.xw_u,
                   boundaries=[] if self.edges is None else [
                       dict(side=side, slope=0.0, intercept_m=y, observed_x_min_m=0.1, observed_x_max_m=0.6)
                       for side, y in zip(("left", "right"), self.edges)])
        if crosswalk is not None and crosswalk[0] - self.x >= 0.0:
            raw["crosswalk"] = dict(near_m=crosswalk[0] - self.x, far_m=crosswalk[1] - self.x)
        m.observe(LineObservation(LineFollowMode.CAMERA_LINE, t, True, 0.0, 0.9,
                                  containment=LaneContainmentEvidence.model_validate(raw)),
                  received_at=t, source_now=t)
        self.tick_n += 1
        if self.scans and self.tick_n % 2 == 0:       # 10 Hz LiDAR, 20 Hz ticks
            m.observe_crosswalk_scan(rays_at(self.x, self.objects, no_return=self.no_return),
                                     range_min=RANGE_MIN, received_at=t)
        d = m.tick(t)
        self.linear = d.linear
        return d

    def run(self, seconds, **kw):
        out = []
        end = self.t + seconds
        while self.t < end - 1e-9:
            out.append((self.t, self.frame(**kw)))
        return out

    def to_stop(self, limit_s=20.0):
        """Camera sees the crosswalk once, then drive until the gate stops the robot."""
        self.frame(crosswalk=(NEAR, FAR))
        end = self.t + limit_s
        while self.t < end:
            if self.frame().linear == 0.0 and self.m.status().reason.startswith("crosswalk"):
                return
        raise AssertionError("never stopped")

    @property
    def crosswalk(self):
        return self.m.status().crosswalk


def test_stop_gap_comes_from_the_body_and_range_min():
    s = Sim()
    s.frame()
    s.m.observe_crosswalk_scan((), range_min=RANGE_MIN, received_at=s.t)
    geo = s.m._crosswalk_geometry()
    assert geo.s_wait == pytest.approx(RANGE_MIN - (B.front_x_m - B.lidar_x_m) + 0.02)
    assert geo.s_wait == pytest.approx(0.11, abs=0.002)       # D-573 2: Pinky nominal about 0.11 m
    text = Path(gate_module.__file__).read_text(encoding="utf-8")
    assert "0.15" not in text and "0.22" not in text           # no D-384 hand constants


def test_stops_before_the_near_edge_with_the_zone_outside_the_blind_band():
    s = Sim()
    s.to_stop()
    s.run(0.3)
    front = s.x + B.front_x_m
    assert front < NEAR - 0.10
    assert NEAR - (s.x + B.lidar_x_m) >= RANGE_MIN
    assert s.crosswalk.state in ("looking", "waiting")


def test_empty_look_then_crosses_and_closes():
    s = Sim(edges=(0.09, -0.09))                              # lane edges: the camera watched the ground
    s.to_stop()
    stop_t = s.t
    go = next(t for t, d in s.run(7.0) if d.linear > 0)
    assert 5.0 <= go - stop_t <= 5.6
    assert s.crosswalk.state == "crossing"
    assert s.m.status().linear <= 0.04 + 1e-9
    s.run(15.0)
    assert s.x + B.rear_x_m > FAR
    assert s.m.status().crosswalk is None                     # past the zone: null, not absent


def test_paint_only_scene_is_clear():
    """The camera keeps seeing the painted crosswalk every frame; paint is never an obstacle."""
    s = Sim()
    s.to_stop()
    stop_t = s.t
    go = next(t for t, d in s.run(7.0, crosswalk=(NEAR, FAR)) if d.linear > 0)
    assert go - stop_t <= 5.6


@pytest.mark.parametrize("obj", [(0.60, 0.0, 0.03),      # on the crosswalk
                                 (0.60, 0.17, 0.03),     # in a waiting strip
                                 (0.85, 0.0, 0.03)])     # in the exit strip
def test_person_present_waits_without_timeout_and_asks_a_human(obj):
    s = Sim(crosswalk_approach_default_m=0.10)
    s.objects = [obj]
    s.to_stop()
    s.run(9.0)
    assert s.m.status().stuck is None
    s.run(2.0)
    stuck = s.m.status().stuck
    assert stuck.cause == "crosswalk_blocked" and stuck.detail == "person_present"
    assert stuck.decisions == ["WAIT", "MANUAL", "ABORT"]
    opened = [d for n, d in s.bus.events if n == "nav.line_stuck_opened"]
    assert opened[-1]["cause"] == "crosswalk_blocked" and opened[-1]["detail"] == "person_present"
    assert all(d.linear == 0.0 and d.angular == 0.0 for _, d in s.run(120.0, dt=0.1))
    assert s.crosswalk.reason == "person_present"


def test_moving_answers_are_refused_for_crosswalk_blocked():
    s = Sim()
    s.objects = [(0.60, 0.0, 0.03)]
    s.to_stop()
    s.run(11.0)
    sid = s.m.status().stuck.stuck_id
    for decision in ("RESUME", "BACK_AND_RETRY", "YIELD"):
        with pytest.raises(AnswerRefused) as refused:
            s.m.stuck_decision(sid, decision, by="console", yield_m=0.2, yield_turn_rad=0.0)
        assert refused.value.code == "STUCK_DECISION_REFUSED"
    assert s.m.stuck_decision(sid, "WAIT", by="console") == "hold"
    assert all(d.linear == 0.0 for _, d in s.run(2.0))
    assert s.m.stuck_decision(sid, "ABORT", by="console") == "idle"
    assert s.m.mode is LineFollowMode.OFF


def test_person_leaves_then_the_stuck_clears_and_the_robot_crosses():
    s = Sim()
    s.objects = [(0.60, 0.0, 0.03)]
    s.to_stop()
    s.run(11.0)
    s.objects = []
    go = next(t for t, d in s.run(7.0) if d.linear > 0)
    assert s.m.status().stuck is None
    closed = [d for n, d in s.bus.events if n == "nav.line_stuck_closed"]
    assert closed[-1]["reason"] == "cleared"
    assert go > 0


def test_one_bad_scan_restarts_the_window():
    s = Sim()
    s.to_stop()
    s.run(0.6)
    s.objects = [(0.60, 0.0, 0.03)]
    s.run(0.1)
    s.objects = []
    bad_t = s.t
    go = next(t for t, d in s.run(8.0) if d.linear > 0)
    assert go - bad_t >= 5.0 - 0.05 - 1e-6      # the bad scan is at most one tick before bad_t


@pytest.mark.parametrize("hole", [lambda a: abs(a) < 0.3, lambda a: 0.3 < a < 0.8])
def test_no_return_rays_over_the_area_are_unknown(hole):
    s = Sim()
    s.no_return = hole
    s.to_stop()
    assert all(d.linear == 0.0 for _, d in s.run(5.0))
    assert s.crosswalk.reason == "look_unknown"


def test_a_shadowed_area_is_unknown():
    s = Sim()
    s.to_stop()
    s.objects = [(s.x + B.front_x_m + 0.04, 0.0, 0.01)]    # in front of A, hides part of it
    assert all(d.linear == 0.0 for _, d in s.run(5.0))
    assert s.crosswalk.reason == "look_unknown"


def test_stale_scan_is_not_clear():
    s = Sim()
    s.to_stop()
    s.scans = False
    assert all(d.linear == 0.0 for _, d in s.run(12.0))
    assert s.crosswalk.reason == "sensor_stale"
    assert s.m.status().stuck.detail == "sensor_stale"


def test_zone_lost_after_arming_stops_for_good():
    s = Sim()
    s.frame(crosswalk=(NEAR, FAR))
    s.run(0.5)
    assert s.crosswalk is not None
    s.m.invalidate_return_pose()                  # odom epoch change: the anchor is gone
    assert all(d.linear == 0.0 for _, d in s.run(30.0))
    assert s.crosswalk.reason == "zone_lost"
    assert s.m.status().stuck.detail == "zone_lost"


def test_crossing_holds_for_a_return_ahead_but_not_for_a_waiting_strip_inside_the_zone():
    s = Sim(crosswalk_approach_default_m=0.10)
    s.to_stop()
    s.run(5.5)
    assert s.crosswalk.state == "crossing"
    end = s.t + 20.0
    while s.x + B.front_x_m < NEAR + 0.02:
        assert s.t < end, s.m.status()
        s.frame()
    s.objects = [(NEAR + 0.08, 0.20, 0.015)]     # waiting strip only: keep crossing
    assert all(d.linear > 0 for _, d in s.run(0.5))
    s.objects = [(FAR - 0.02, 0.0, 0.02)]        # zone ahead of the body: stop
    s.run(0.2)
    assert s.frame().linear == 0.0
    assert s.m.status().reason == "crosswalk_person_present"


def test_flag_off_changes_nothing():
    s = Sim(enabled=False)
    s.objects = [(0.60, 0.0, 0.03)]
    s.frame(crosswalk=(NEAR, FAR))
    assert all(d.linear > 0 for _, d in s.run(3.0))
    assert s.m.status().reason is None or not s.m.status().reason.startswith("crosswalk")
    assert "crosswalk" in s.m.status().model_dump()          # D-573 6 개정 2026-10-10: reported anyway
    assert not s.m.wants_crosswalk_scan


def test_snapshot_reports_unknown_before_the_camera_watched_and_the_zone_inside():
    s = Sim()
    s.frame()
    dumped = s.m.status().model_dump()
    assert dumped["crosswalk"]["state"] == "unknown"           # D-573 6 개정: no seen lane edges yet
    assert "crosswalk_reported" not in dumped
    s.frame(crosswalk=(NEAR, FAR))
    s.frame()
    zone = s.m.status().model_dump()["crosswalk"]
    assert zone["state"] in ("armed", "approaching") and zone["zone_id"] and zone["source"] == "camera"


def test_gate_never_lifts_a_zero_or_raises_a_speed():
    s = Sim()
    s.to_stop()
    s.run(5.5)
    assert s.crosswalk.state == "crossing"
    zero = LineFollowDecision(generation=1, mode=LineFollowMode.CAMERA_LINE)
    assert s.m._crosswalk_gate(s.t, zero) == zero
    slow = LineFollowDecision(linear=0.01, angular=0.1, generation=1, mode=LineFollowMode.CAMERA_LINE)
    assert s.m._crosswalk_gate(s.t, slow) == slow


def test_estop_and_mode_off_reset_the_gate():
    s = Sim()
    s.objects = [(0.60, 0.0, 0.03)]
    s.to_stop()
    s.m.stop("estop")
    assert s.m.tick(s.t).linear == 0.0
    s.m.set_mode(LineFollowMode.CAMERA_LINE)
    assert s.m._xwalk.zone is None and s.crosswalk.state == "unknown"


def test_body_stop_still_wins_while_crossing():
    s = Sim()
    s.to_stop()
    s.run(5.5)
    assert s.crosswalk.state == "crossing"
    lidar = [(B.front_x_m + 0.01 - B.lidar_x_m, 0.0)]           # a return touching the body front
    s.m.observe_body_points(lidar, range_min=RANGE_MIN, received_at=s.t)
    s.m.observe_scan_points(lidar, received_at=s.t)
    assert s.m.tick(s.t).linear == 0.0
    assert s.m.status().reason == "obstacle_ahead"


def test_judge_counts_only_lidar_returns():
    scan = Scan(rays=tuple((math.radians(a), 2.0) for a in range(-180, 180)), range_min=RANGE_MIN, at=0.0)
    assert judge(scan, [(0.5, 0.7, -0.2, 0.2)], (0.0, 0.0), 0.0) is None
    blind = Scan(scan.rays, range_min=0.6, at=0.0)
    assert judge(blind, [(0.5, 0.7, -0.2, 0.2)], (0.0, 0.0), 0.0) == "look_unknown"


def test_scan_rays_marks_missing_returns_unknown():
    rays = scan_rays(dict(ranges=[1.0, float("inf"), 0.0, float("nan"), 9.0], angle_min=0.0,
                          angle_increment=0.1, range_max=8.0), forward_deg=0.0)
    assert [r for _, r in rays] == [1.0, None, None, None, None]


def test_pure_gate_has_no_opinion_without_a_zone():
    g = CrosswalkGate()
    assert g.step(0.0, zones=[], pose=None, key=None, still=True, scan=None, geo=None, cruise=0.08,
                  look_s=1.0, min_scans=8, report_s=10.0, stale_s=0.5) == (None, None)
    assert g.status(0.0) is None


def test_an_obstacle_stop_at_an_armed_crosswalk_never_backs_off():
    """Gazebo baseline 2026-10-10: D-407 backed off and re-approached a standing person."""
    s = Sim(recovery_local_enabled=True, obstacle_escalate_s=1.0, recovery_ask_s=1.0)
    s.frame(crosswalk=(NEAR, FAR))
    s.run(0.5)
    lidar = [(B.front_x_m + 0.01 - B.lidar_x_m, 0.0)]          # someone right at the body front
    for _ in range(80):
        s.m.observe_body_points(lidar, range_min=RANGE_MIN, received_at=s.t + 0.05)
        s.m.observe_scan_points(lidar, received_at=s.t + 0.05)
        assert s.frame().linear <= 0.0 + 1e-12 and s.linear >= 0.0
    stuck = s.m.status().stuck
    assert stuck.cause == "crosswalk_blocked" and stuck.detail == "person_present"
    assert not [n for n, _ in s.bus.events if n == "nav.line_stuck_local_attempt"]


LANE_HALF = 0.079    # map_v2_fleet: 158 mm between the inner paint edges


def test_the_track_wall_beside_the_lane_is_outside_the_look_area():
    """SIM 2026-10-10: the west track wall 0.13 m right of the lane centre held an empty crosswalk."""
    s = Sim(edges=(LANE_HALF, -LANE_HALF))
    s.objects = [(x / 100, -0.13 - 0.01, 0.01) for x in range(0, 120)]   # a wall of returns
    s.to_stop()
    stop_t = s.t
    go = next(t for t, d in s.run(7.0) if d.linear > 0)
    assert go - stop_t <= 5.6


def test_a_person_inside_the_seen_lane_corridor_still_stops():
    s = Sim(edges=(LANE_HALF, -LANE_HALF))
    s.objects = [(0.60, -0.07, 0.02)]           # beside the body path, on the lane
    s.to_stop()
    assert all(d.linear == 0.0 for _, d in s.run(3.0))
    assert s.crosswalk.reason == "person_present"


def test_the_corridor_never_narrower_than_the_body():
    s = Sim(edges=(0.02, -0.02))                # a misread narrow lane
    s.objects = [(0.60, 0.07, 0.01)]            # inside the body half width + margin
    s.to_stop()
    assert all(d.linear == 0.0 for _, d in s.run(3.0))


# ---- D-573 rev 2: per-cell persistence in the noise band at the look-area edge ------------------
import random
from types import SimpleNamespace

from core_features.line_follow.crosswalk_gate import Geometry, Zone

SIGMA = 0.0035      # measured C1 range noise, 0-0.5 m (8kcn 2026-10-10, p90 0.0031, max 0.0034)
EDGE = 0.08


def pure_rig(points_per_scan, *, scans=30, period=0.1, sigma=SIGMA, k=2, n=3):
    """The gate standing before a zone 0.30..0.45 m ahead (corridor +-EDGE); points_per_scan(i)
    gives the base-frame circles (x, y, r) of scan i. Returns [(t, cap, reason)]."""
    g = CrosswalkGate()
    zone = Zone(key=(0, "odom"), x=0.0, y=0.0, yaw=0.0, near=0.30, far=0.45, left=EDGE, right=-EDGE)
    geo = Geometry(front_x=B.front_x_m, rear_x=B.rear_x_m, lidar_x=B.lidar_x_m, v_cross=0.04, s_wait=0.04,
                   slow_from=0.08, lane_half_m=0.10, body_half_m=B.half_width_m + 0.02, strip_m=0.0,
                   exit_m=0.15, end_margin=0.02)
    pose = SimpleNamespace(x=0.30 - 0.035 - B.front_x_m, y=0.0, yaw=0.0)
    out = []
    for i in range(scans):
        t = 1.0 + i * period
        rays = rays_at(pose.x, [(pose.x + x, y, r) for x, y, r in points_per_scan(i)], step_deg=1)
        scan = Scan(rays, 0.05, t)
        cap, reason = g.step(t, zones=[zone], pose=pose, key=(0, "odom"), still=True, scan=scan, geo=geo,
                             cruise=0.08, look_s=1.0, min_scans=8, report_s=10.0, stale_s=0.5,
                             range_sigma_m=sigma, persist_k=k, persist_n=n)
        out.append((t, cap, reason))
    return out


def _band_point(rng):
    """A noise return inside A within 3 sigma of its right edge, at a random place along it."""
    return (0.31 + rng.random() * 0.13, -EDGE + 0.003 + rng.random() * (3 * SIGMA - 0.006), 0.003)


def test_random_noise_in_the_edge_band_still_clears():
    rng = random.Random(7)
    out = pure_rig(lambda i: [_band_point(rng)])
    assert any(cap and cap > 0 for _, cap, _ in out)


def test_a_consistent_return_in_the_edge_band_is_a_person():
    out = pure_rig(lambda i: [(0.37, -EDGE + 2 * SIGMA, 0.003)])
    assert all(cap == 0.0 for _, cap, _ in out[1:])
    assert out[-1][2] == "crosswalk_person_present"


def test_a_return_deeper_than_the_band_is_a_person_at_once():
    out = pure_rig(lambda i: [(0.37, 0.0, 0.02)] if i >= 5 else [], scans=8)
    assert out[5][2] == "crosswalk_person_present"


def test_dropout_over_the_area_is_unknown_not_clear():
    g_out = []
    rng = random.Random(3)
    out = pure_rig(lambda i: [_band_point(rng)], scans=5)
    # a scan whose rays over A carry no return
    g = CrosswalkGate()
    zone = Zone(key=(0, "odom"), x=0.0, y=0.0, yaw=0.0, near=0.30, far=0.45, left=EDGE, right=-EDGE)
    geo = Geometry(front_x=B.front_x_m, rear_x=B.rear_x_m, lidar_x=B.lidar_x_m, v_cross=0.04, s_wait=0.04,
                   slow_from=0.08, lane_half_m=0.10, body_half_m=B.half_width_m + 0.02, strip_m=0.0,
                   exit_m=0.15, end_margin=0.02)
    pose = SimpleNamespace(x=0.30 - 0.035 - B.front_x_m, y=0.0, yaw=0.0)
    for i in range(20):
        t = 1.0 + i * 0.1
        rays = rays_at(pose.x, [], no_return=lambda a: abs(a) < 0.5, step_deg=1)
        g_out.append(g.step(t, zones=[zone], pose=pose, key=(0, "odom"), still=True, scan=Scan(rays, 0.05, t),
                            geo=geo, cruise=0.08, look_s=1.0, min_scans=8, report_s=10.0, stale_s=0.5,
                            range_sigma_m=SIGMA, persist_k=2, persist_n=3))
    assert all(cap == 0.0 for cap, _ in g_out) and g_out[-1][1] == "crosswalk_look_unknown"
    assert out  # the noisy rig above ran



def test_the_wall_beside_the_exit_does_not_stop_the_crossing():
    """SIM 2026-10-10 crosswalk 2: 0.05 x travel of assumed drift since the zone's first image put
    the track wall 0.115 m beside the lane into the exit strip; the fresh lane edges keep it out."""
    s = Sim(edges=(LANE_HALF, -LANE_HALF))
    s.objects = [(x / 200, 0.12, 0.005) for x in range(0, 300)]   # a wall surface at y 0.115
    s.frame(crosswalk=(NEAR, FAR))
    end = s.t + 30.0
    while s.crosswalk is None or s.crosswalk.state != "crossing":
        assert s.t < end, s.m.status()
        s.frame()
    while s.x + B.rear_x_m < FAR + 0.05:
        assert s.t < end, s.m.status()
        assert s.frame().linear > 0, s.m.status()



def test_while_crossing_the_area_follows_the_body_not_the_drifted_corridor():
    """SIM 2026-10-10 crosswalk 2: no fresh lane edges on the stripes, the zone corridor plus
    0.05 x travel of drift reached the wall 0.115 m beside the lane; the body path did not."""
    s = Sim(edges=(LANE_HALF, -LANE_HALF))
    s.objects = [(x / 200, 0.12, 0.005) for x in range(0, 300)]
    s.frame(crosswalk=(NEAR, FAR))
    end = s.t + 30.0
    while s.crosswalk is None or s.crosswalk.state != "crossing":
        assert s.t < end, s.m.status()
        s.frame()
    s.edges = None                               # the stripes hide the lane edges from here
    while s.x + B.front_x_m < FAR + 0.03:
        s.frame()
        assert s.t < end, s.m.status()
    while s.x + B.rear_x_m < FAR + 0.05:
        assert s.t < end, s.m.status()
        assert s.frame().linear > 0, s.m.status()


# ---- Safety review 2026-10-10 (ac25f5321) ---------------------------------------------------------
def _looking_gate():
    g = CrosswalkGate()
    zone = Zone(key=(0, "odom"), x=0.0, y=0.0, yaw=0.0, near=0.30, far=0.45, left=EDGE, right=-EDGE)
    geo = Geometry(front_x=B.front_x_m, rear_x=B.rear_x_m, lidar_x=B.lidar_x_m, v_cross=0.04, s_wait=0.04,
                   slow_from=0.08, lane_half_m=0.10, body_half_m=B.half_width_m + 0.02, strip_m=0.0,
                   exit_m=0.15, end_margin=0.02)
    return g, zone, geo


def _step(g, zone, geo, pose, t, scan):
    return g.step(t, zones=[zone], pose=pose, key=(0, "odom"), still=True, scan=scan, geo=geo, cruise=0.08,
                  look_s=1.0, min_scans=8, report_s=10.0, stale_s=0.5, range_sigma_m=SIGMA,
                  persist_k=2, persist_n=3)


@pytest.mark.parametrize("rays", [
    (),                                                             # a scan without rays
    tuple((math.radians(a), 2.0) for a in range(90, 271)),          # only the rear half: A outside FOV
])
def test_a_scan_that_does_not_cover_the_area_is_unknown(rays):
    g, zone, geo = _looking_gate()
    pose = SimpleNamespace(x=0.30 - 0.035 - B.front_x_m, y=0.0, yaw=0.0)
    out = [_step(g, zone, geo, pose, 1.0 + i * 0.1, Scan(rays, 0.05, 1.0 + i * 0.1)) for i in range(20)]
    assert all(cap == 0.0 for cap, _ in out)
    assert out[-1][1] == "crosswalk_look_unknown"


@pytest.mark.parametrize("pose", [
    SimpleNamespace(x=0.10, y=0.0, yaw=math.radians(60)),       # turned away at a junction
    SimpleNamespace(x=0.10, y=0.25, yaw=0.0),                   # beside the zone's lane
])
def test_an_armed_zone_the_robot_turned_away_from_disarms(pose):
    g, zone, geo = _looking_gate()
    ahead = SimpleNamespace(x=0.0, y=0.0, yaw=0.0)
    assert _step(g, zone, geo, ahead, 1.0, Scan((), 0.05, 1.0)) == (None, None)
    assert g.zone is not None                                   # armed far away
    _step(g, zone, geo, pose, 1.1, Scan((), 0.05, 1.1))
    assert g.zone is None and g.status(1.1) is None


def test_the_gate_needs_the_d422_path_mode():
    with pytest.raises(ValueError):
        LineFollowConfig(**BODY, crosswalk_gate_enabled=True, obstacle_mode="sector")


# ---- D-573 rev 3 (2026-10-10 user): 5 s of continuous clear, then cross ----------------------------
def _go_after(s, seconds):
    return next((t for t, d in s.run(seconds) if d.linear > 0), None)


def test_five_seconds_of_continuous_clear_then_crosses_without_asking_anyone():
    s = Sim()
    s.to_stop()
    stop_t = s.t
    assert _go_after(s, 4.8) is None                         # clear is observed, never cut short
    go = _go_after(s, 2.0)
    assert go is not None and 5.0 <= go - stop_t <= 5.6
    assert s.crosswalk.state == "crossing"
    assert not [n for n, _ in s.bus.events if n == "nav.line_stuck_opened"]


@pytest.mark.parametrize("bad", ["person", "unknown"])
def test_a_bad_scan_at_4_9_s_restarts_the_five_second_window(bad):
    s = Sim()
    s.to_stop()
    assert _go_after(s, 4.9) is None
    if bad == "person":
        s.objects = [(0.60, 0.0, 0.03)]
    else:
        s.no_return = lambda a: abs(a) < 0.3
    s.run(0.1)
    s.objects, s.no_return = [], None
    bad_t = s.t
    go = _go_after(s, 8.0)
    assert go is not None and go - bad_t >= 5.0 - 0.05 - 1e-6


@pytest.mark.parametrize("clear_s,min_scans", [(2.0, 16), (3.0, 24)])
def test_clear_window_is_configurable(clear_s, min_scans):
    s = Sim(crosswalk_clear_s=clear_s, crosswalk_look_min_scans=min_scans)
    s.to_stop()
    stop_t = s.t
    go = _go_after(s, clear_s + 2.0)
    assert go is not None and clear_s <= go - stop_t <= clear_s + 0.6


@pytest.mark.parametrize("bad", ["person", "unknown"])
def test_three_second_site_window_restarts_after_occupied_or_unknown_scan(bad):
    s = Sim(crosswalk_clear_s=3.0, crosswalk_look_min_scans=24)
    s.to_stop()
    assert _go_after(s, 2.9) is None
    if bad == "person":
        s.objects = [(0.60, 0.0, 0.03)]
    else:
        s.no_return = lambda a: abs(a) < 0.3
    s.run(0.1)
    s.objects, s.no_return = [], None
    bad_t = s.t
    go = _go_after(s, 6.0)
    assert go is not None and go - bad_t >= 3.0 - 0.05 - 1e-6


def test_no_human_report_while_the_area_is_clearing():
    """A person leaves after 8 s: the 10 s report must not fire inside the 5 s clear window."""
    s = Sim()
    s.objects = [(0.60, 0.0, 0.03)]
    s.to_stop()
    s.run(8.0)
    s.objects = []
    go = _go_after(s, 8.0)
    assert go is not None
    assert not [n for n, _ in s.bus.events if n == "nav.line_stuck_opened"]


def test_clear_window_defaults_and_report_ordering():
    c = LineFollowConfig()
    assert c.crosswalk_clear_s == 5.0 and c.crosswalk_look_min_scans == 40
    assert c.crosswalk_report_s > c.crosswalk_clear_s
    with pytest.raises(ValueError):
        LineFollowConfig(crosswalk_clear_s=10.0, crosswalk_report_s=10.0)


def test_a_parsed_copy_keeps_the_crosswalk_key_d555_hub():
    """Fleet's hub re-parses the robot snapshot: null (gate on, outside a zone) must stay, absent stays absent."""
    from core_common.protocol.schemas import LineFollowStatus

    assert LineFollowStatus.model_validate({"crosswalk": None}).model_dump()["crosswalk"] is None
    assert "crosswalk" not in LineFollowStatus.model_validate({}).model_dump()


def test_a_bare_reported_flag_without_the_key_stays_unknown():
    """rosy-b3 review: an input flag alone must not become null = positively outside a zone."""
    from core_common.protocol.schemas import LineFollowStatus

    assert "crosswalk" not in LineFollowStatus.model_validate({"crosswalk_reported": True}).model_dump()


def test_state_snapshot_round_trips_an_unknown_crosswalk_and_refuses_a_malformed_one():
    import pydantic
    from core_common.protocol.schemas import StateSnapshot

    unknown = {"state": "unknown", "reason": "not_watched", "source": "camera"}
    snap = StateSnapshot.model_validate({"robot_id": "r", "line_follow": {"crosswalk": unknown}})
    again = StateSnapshot.model_validate(snap.model_dump(mode="json"))
    assert again.model_dump(mode="json")["line_follow"]["crosswalk"]["state"] == "unknown"
    for bad in ("outside", {"zone_id": "z1"}, 3):
        with pytest.raises(pydantic.ValidationError):
            StateSnapshot.model_validate({"robot_id": "r", "line_follow": {"crosswalk": bad}})
