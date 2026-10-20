"""D-573 (c): the CORE crosswalk gate stops before a camera crosswalk zone, looks with the LiDAR and
crosses only after 5 s of continuous proof (rev 3); no timeout; a D-407 crosswalk_blocked stuck asks a human."""
import math
from pathlib import Path

import pytest

from core_common.protocol.lane_containment import LaneContainmentEvidence
from core_common.robot_body import PINKY_PRO
from core_features.line_follow.crosswalk import gate as gate_module
from core_features.line_follow.crosswalk import kernel as kernel_module
from core_features.line_follow.crosswalk.gate import CrosswalkGate, Scan, judge, scan_rays
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
    def __init__(self, enabled=True, edges=None, xw_u=0.02, lat_u=0.005, slope=0.0, **config):
        self.edges, self.slope = edges, slope   # slope: the lane's direction in the body frame (dy/dx)          # (left, right) inner paint edges the camera reports, or None
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
                       dict(side=side, slope=k, intercept_m=y, observed_x_min_m=0.1, observed_x_max_m=0.6)
                       for side, y, k in zip(("left", "right"), self.edges,
                                             self.slope if isinstance(self.slope, tuple) else (self.slope,) * 2)])
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
    text = "\n".join(Path(module.__file__).read_text(encoding="utf-8")
                     for module in (gate_module, kernel_module))
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


@pytest.mark.parametrize("reason,expected", [("looking", None), ("person", "person_present"), ("unknown", "look_unknown")])
def test_crosswalk_wait_blocks_a_zero_linear_pivot_candidate(reason, expected):
    s = Sim()
    if reason == "person":
        s.objects = [(0.60, 0.0, 0.03)]
    elif reason == "unknown":
        s.no_return = lambda angle: abs(angle) < 0.3
    s.to_stop()
    s.run(0.2 if reason == "looking" else 5.5)
    assert s.crosswalk.reason == expected
    pivot = LineFollowDecision(linear=0.0, angular=0.4, generation=1, mode=LineFollowMode.CAMERA_LINE)
    stopped = s.m._crosswalk_gate(s.t, pivot)
    assert stopped.linear == 0.0 and stopped.angular == 0.0


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


def test_wall_bases_read_as_the_lane_edges_do_not_hold_an_empty_crosswalk():
    """Gazebo lap 2026-10-14 (m3): the camera gave the wall bases 0.120 / 0.122 m either side as the
    lane edges; A's edge lay on the wall, its returns hit one edge cell every scan and the persistence
    rule answered person for good. The lane is no wider than its model, so the wall stays outside."""
    s = Sim(edges=(0.120, -0.122))
    s.objects = [(x / 100, side, 0.004) for x in range(0, 120) for side in (-0.121, 0.121)]
    s.to_stop()
    stop_t = s.t
    go = next(t for t, d in s.run(7.0) if d.linear > 0)
    assert go - stop_t <= 5.6


def test_a_poor_lane_reading_while_crossing_does_not_widen_the_way_ahead_into_the_walls():
    """D-573 개정 5 (Gazebo lap m15): on the stripes the camera's lane bound grew to 0.046 m; merged
    into the zone's edges it made the way ahead of the crossing body 0.14 m wide each side and the
    walls 0.117 m out held the crossing for good. The way ahead is the lane's own width about the
    body; a person in it still stops the crossing."""
    for person, moves in (([], True), ([(FAR - 0.02, 0.05, 0.02)], False)):
        s = Sim(edges=(0.079, -0.079))
        walls = [(x / 100, side, 0.004) for x in range(0, 120) for side in (-0.117, 0.117)]
        s.objects = walls
        s.to_stop()
        s.run(5.5)
        assert s.crosswalk.state == "crossing"
        end = s.t + 20.0
        while s.x + B.front_x_m < NEAR + 0.02:
            assert s.t < end, s.m.status()
            s.frame()
        s.lat_u, s.objects = 0.046, walls + person
        out = [d.linear for _, d in s.run(1.0)]
        assert (out[-1] > 0) is moves, (person, s.m.status().reason)


def test_the_look_area_follows_the_lane_direction_not_the_body_heading():
    """D-573 개정 5 6항 (Gazebo m23): the robot stood 0.1 rad off the lane at the stop; turned to the body's
    heading, the far end of the look area ran over the wall 0.117 m out and person_present held. The lane's
    direction is the seen edges' slope; in that frame the walls stay outside and the lane stays inside."""
    walls = [(x / 100, side + 0.1 * x / 100, 0.004) for x in range(0, 120) for side in (-0.117, 0.117)]
    s = Sim(edges=(0.079, -0.079), slope=0.1)
    s.objects = walls
    s.to_stop()
    assert any(d.linear > 0 for _, d in s.run(7.0))
    s = Sim(edges=(0.079, -0.079), slope=0.1)
    s.objects = walls + [(0.60, -0.060 + 0.06, 0.012)]       # in the lane at its far right edge
    s.to_stop()
    assert all(d.linear == 0 for _, d in s.run(7.0))


def test_an_edge_misread_with_another_slope_cannot_hide_the_other_lane_edge():
    """Review 2026-10-14: a straight lane with the left edge misread at slope 0.1 tilts the mean frame
    0.05 rad; the right edge's seen ends in that frame still bound A, so someone at its far end holds."""
    s = Sim(edges=(0.079, -0.079), slope=(0.1, 0.0))
    s.objects = [(0.60, -0.070, 0.012)]
    s.to_stop()
    assert all(d.linear == 0 for _, d in s.run(7.0))


def test_a_loose_lane_reading_on_the_stripes_does_not_turn_the_way_ahead():
    """Gazebo m24: while crossing, the camera read the stripes as a lane 0.08 m wide, slope 0.18, bound
    0.043 m; turned by it the way ahead ran over the wall and the crossing held for good. A reading looser
    than D-491's MAX_LATERAL_M is no lane: the zone's own frame stays, and a person in the way still holds."""
    walls = [(x / 100, side, 0.004) for x in range(0, 120) for side in (-0.117, 0.117)]
    for person, moves in (([], True), ([(FAR - 0.02, 0.0, 0.02)], False)):
        s = Sim(edges=(0.079, -0.079))
        s.objects = walls
        s.to_stop()
        s.run(5.5)
        assert s.crosswalk.state == "crossing"
        end = s.t + 20.0
        while s.x + B.front_x_m < NEAR + 0.02:
            assert s.t < end, s.m.status()
            s.frame()
        s.edges, s.slope, s.lat_u, s.objects = (0.0, -0.08), (0.36, 0.0), 0.043, walls + person
        out = [d.linear for _, d in s.run(1.0)]
        assert (out[-1] > 0) is moves, (person, s.m.status().reason)


def test_a_frame_without_the_line_keeps_the_last_corridor_for_its_ttl_in_the_same_odom_run():
    """Gazebo m25: a camera frame without the line cleared the lane evidence for a tick; without a corridor A
    widened in the zone's skewed frame, read unknown and restarted the 5 s clear window at every such tick."""
    s = Sim(edges=(0.079, -0.079))
    s.frame()
    held = s.m._fresh_corridor(s.t)
    assert held is not None
    s.m.observe(LineObservation(LineFollowMode.CAMERA_LINE, s.t, False, None, 0.0), received_at=s.t, source_now=s.t)
    assert s.m._return_evidence._lane is None and s.m._fresh_corridor(s.t + 0.1) is held
    s.linear = 0.08                                                   # moving: only for EVIDENCE_TTL_S
    s.m._standing_still = lambda now: False
    assert s.m._fresh_corridor(s.t + 0.31) is None
    s.m._standing_still = lambda now: True                            # standing still where it was seen
    here = SimpleNamespace(x=held[0].x, y=held[0].y, yaw=held[0].yaw)
    assert s.m._fresh_corridor(s.t + 5.0, here) is held
    for moved in (dict(x=here.x + 0.05), dict(yaw=here.yaw + 0.3)):    # drove or pivoted, then stopped (review)
        assert s.m._fresh_corridor(s.t + 5.0, SimpleNamespace(**{**vars(here), **moved})) is None
    s.m._return_evidence.reset()                                      # a new odom run: never the old corridor
    assert s.m._fresh_corridor(s.t + 0.1) is None


def test_the_lane_width_cap_keeps_the_lane_and_gives_up_the_wall_side():
    """D-573 개정 4: with wall bases read as the edges, someone 0.09 m from the middle (beyond the
    body's own 0.077 m) still stops the crossing; someone 0.118 m out, against the wall, is no
    longer judged (the documented loss; D-422 keeps the body's own path). A change that sees that
    person again is welcome: update the second half then."""
    s = Sim(edges=(0.120, -0.122))
    s.objects = [(0.42, 0.075, 0.012)]                     # in the lane, reaching 0.087 m out
    s.to_stop()
    assert all(d.linear == 0 for _, d in s.run(7.0))
    s = Sim(edges=(0.120, -0.122))
    s.objects = [(0.42, 0.118, 0.004)]
    s.to_stop()
    assert any(d.linear > 0 for _, d in s.run(7.0))


def test_lane_edges_caps_raw_edges_only_and_pads_stay_outside():
    """Review: the cap is on what the camera saw; an edge alone, a lane-wide pair and the zone's
    uncertainty/drift pad are untouched (an off-centre robot keeps its real edges)."""
    from core_features.line_follow.crosswalk.gate import lane_edges, zone_of
    assert lane_edges(0.120, -0.122) == pytest.approx((0.078, -0.080))    # the lane's inner width
    # m6: with the corridor's pads (0.024 m there) the wall face (0.117 m) and its edge band stay outside
    assert lane_edges(0.120, -0.122)[0] + 0.024 < 0.117 - 0.0105
    assert lane_edges(0.109, -0.049) == (0.109, -0.049)        # 3 cm off-centre, a real lane
    # review: one far misread edge (the next lane's line) must not slide the lane off the body
    left, right = lane_edges(0.109, -0.29, body_half=0.0765)
    assert (left, right) == pytest.approx((0.0555, -0.1025))   # the lane stays about the body (0 inside)
    assert lane_edges(None, -0.122) == (None, -0.122) and lane_edges(0.14, None) == (0.14, None)
    anchor = SimpleNamespace(x=0.0, y=0.0, yaw=0.0, frame="odom")
    z = zone_of(dict(anchor=anchor, epoch=0, near=0.3, far=0.45, uncertainty=0.09, left=0.120, right=-0.122), 0.05)
    assert (z.left, z.right, z.lateral) == (pytest.approx(0.078), pytest.approx(-0.080), 0.09)
    geo = Geometry(front_x=0.04, rear_x=-0.07, lidar_x=-0.017, v_cross=0.04, s_wait=0.04, slow_from=0.08,
                   lane_half_m=0.10, body_half_m=0.077, strip_m=0.0, exit_m=0.15, end_margin=0.02)
    look = CrosswalkGate()._boxes(z, geo, front=0.0)[0]
    assert look[2:] == (pytest.approx(-0.170), pytest.approx(0.168))   # the pad is outside the cap


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

from core_features.line_follow.crosswalk.gate import Geometry, Zone

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


def _step(g, zone, geo, pose, t, scan, **more):
    return g.step(t, zones=[zone], pose=pose, key=(0, "odom"), still=True, scan=scan, geo=geo, cruise=0.08,
                  look_s=1.0, min_scans=8, report_s=10.0, stale_s=0.5, range_sigma_m=SIGMA,
                  persist_k=2, persist_n=3, **more)


def _look_between_walls(zone_yaw, corridor, psi=0.0, person=(), toggle=False):
    """The gate standing before a zone 0.30..0.45 m ahead on a lane whose walls stand 0.117 m either
    side; the zone's anchor is `zone_yaw` off the lane and the robot `psi` (the world is turned by
    -psi about the robot, which stays at yaw 0). Returns the reasons of 3 s."""
    px = 0.30 - 0.035 - B.front_x_m

    def world(x, y):
        c, sn = math.cos(-psi), math.sin(-psi)
        return px + c * (x - px) - sn * y, sn * (x - px) + c * y
    g = CrosswalkGate()
    zx, zy = world(0.0, 0.0)
    zone = Zone(key=(0, "odom"), x=zx, y=zy, yaw=zone_yaw - psi, near=0.30, far=0.45, margin=0.02, lateral=0.02)
    geo = Geometry(front_x=B.front_x_m, rear_x=B.rear_x_m, lidar_x=B.lidar_x_m, v_cross=0.04, s_wait=0.04,
                   slow_from=0.08, lane_half_m=0.10, body_half_m=B.half_width_m + 0.02, strip_m=0.0,
                   exit_m=0.15, end_margin=0.02)
    pose = SimpleNamespace(x=px, y=0.0, yaw=0.0)
    things = [(x / 200, side, 0.002) for x in range(-80, 320) for side in (-0.117, 0.117)] + list(person)
    things = [(*world(x, y), r) for x, y, r in things]
    out = []
    for i in range(30):
        t = 1.0 + i * 0.1
        seen = None if corridor is None or (toggle and i % 2) else (pose, *corridor)
        out.append(_step(g, zone, geo, pose, t, Scan(rays_at(px, things, step_deg=1), 0.05, t), corridor=seen)[1])
    return out


def test_the_look_area_follows_the_lane_seen_now_not_the_zones_older_anchor():
    """D-573 개정 5 (Gazebo lap m6-m13): the anchor of a zone seen earlier is a few degrees off the
    lane seen now; that slope over the look area used to widen it by 0.02-0.03 m into the walls
    0.117 m from the lane middle and person_present never cleared. Judged in the frame of the
    lane seen now the area is the lane plus the camera's own bound, and the walls stay outside."""
    for yaw in (0.0, 0.03, -0.03):                 # m8: 0.024 rad, the camera's own bound 0.02 m
        reasons = _look_between_walls(yaw, (0.079, -0.079, 0.02))
        assert "crosswalk_person_present" not in reasons and reasons[-1] is None, (yaw, reasons[-3:])
    # no lane seen now: the corridor's full width in the zone's own frame, as before (the wall holds)
    assert "crosswalk_person_present" in _look_between_walls(0.03, None)
    # the camera reads the wall bases as the edges: the lane's inner width stands in
    reasons = _look_between_walls(0.03, (0.120, -0.122, 0.02))
    assert "crosswalk_person_present" not in reasons and reasons[-1] is None


@pytest.mark.parametrize("psi", [0.04, -0.04])
def test_a_person_at_the_far_lane_edge_holds_a_robot_standing_askew(psi):
    """Review 2026-10-14: the lane seen now is known in the robot's own heading; askew by psi, the
    far end of the look area tilts off the lane. The edges over their seen range (0.1-0.4 m) and
    their slope beyond it keep the lane's far edge inside."""
    seen = (0.079 - min(psi * 0.1, psi * 0.4), -0.079 - max(psi * 0.1, psi * 0.4), 0.005, abs(psi), 0.4)
    for side in (0.075, -0.075):
        reasons = _look_between_walls(0.0, seen, psi=psi, person=[(0.57, side, 0.012)])
        assert None not in reasons and "crosswalk_person_present" in reasons, (side, reasons[-3:])


def test_a_lane_seen_on_and_off_between_ticks_never_clears_a_person():
    reasons = _look_between_walls(0.03, (0.079, -0.079, 0.02), person=[(0.40, 0.05, 0.02)], toggle=True)
    assert None not in reasons


def _cross_between_walls(*, seen_while_looking=True, walls=True, person=()):
    """D-573 개정 5 8항 (Gazebo m34/m35): a zone imaged 0.1 rad off the lane (no edges of its own) on a
    lane whose walls stand 0.117 m either side. The robot looks (with the lane seen if
    `seen_while_looking`), then crosses along the lane with no corridor at all (the camera's lane bound
    above MAX_LATERAL_M); `person` appears once it moves. Returns [(cap, reason, remembered lane yaw)]."""
    px = 0.30 - 0.035 - B.front_x_m
    g = CrosswalkGate()
    zone = Zone(key=(0, "odom"), x=0.0, y=0.0, yaw=0.1, near=0.30, far=0.45, margin=0.02, lateral=0.02)
    geo = Geometry(front_x=B.front_x_m, rear_x=B.rear_x_m, lidar_x=B.lidar_x_m, v_cross=0.04, s_wait=0.04,
                   slow_from=0.08, lane_half_m=0.10, body_half_m=B.half_width_m + 0.02, strip_m=0.0,
                   exit_m=0.15, end_margin=0.02)
    things = [(x / 200, side, 0.002) for x in range(-80, 320) for side in (-0.117, 0.117)] if walls else []
    out, moving = [], False
    for i in range(200):
        t = 1.0 + i * 0.1
        pose = SimpleNamespace(x=px, y=0.0, yaw=0.0)
        seen = (pose, 0.079, -0.079, 0.02) if seen_while_looking and not moving else None
        scan = Scan(rays_at(px, things + (list(person) if moving else []), step_deg=1), 0.05, t)
        cap, reason = _step(g, zone, geo, pose, t, scan, corridor=seen)
        out.append((cap, reason, getattr(g, "_lane_yaw", None)))
        if cap is None and moving:
            return out                                  # past the zone
        if cap:
            moving, px = True, px + cap * 0.1
    return out


def test_a_crossing_that_loses_the_lane_keeps_the_lanes_direction_not_the_zones():
    out = _cross_between_walls()
    crossing = out[next(i for i, (cap, _, _) in enumerate(out) if cap):]
    assert crossing[-1][0] is None, out[-3:]                          # crossed and closed
    assert all(cap for cap, _, _ in crossing[:-1]), [r for _, r, _ in crossing if r]
    assert crossing[-2][2] == pytest.approx(0.0) and crossing[-1][2] is None   # forgotten with the zone


def test_a_person_in_the_lane_still_holds_a_crossing_that_lost_the_lane():
    out = _cross_between_walls(person=[(0.40, 0.03, 0.02)])
    assert out[-1][0] == 0.0 and out[-1][1] == "crosswalk_person_present", out[-3:]


def test_a_zone_never_seen_with_a_lane_keeps_its_own_frame():
    out = _cross_between_walls(seen_while_looking=False, walls=False)
    assert out[-1][0] is None and all(yaw is None for _, _, yaw in out)
    assert "crosswalk_person_present" in _look_between_walls(0.03, None)   # with the walls: as before


def test_an_armed_zone_the_robot_turned_away_from_disarms_with_a_lane_in_view():
    """Review 2026-10-14: turning the frame to the lane seen now must not hide the turn from
    _on_course (a zone left behind at a junction would ride along the new road)."""
    g, zone, geo = _looking_gate()
    ahead = SimpleNamespace(x=0.0, y=0.0, yaw=0.0)
    assert _step(g, zone, geo, ahead, 1.0, Scan((), 0.05, 1.0), corridor=(ahead, 0.079, -0.079, 0.02)) == (None, None)
    assert g.zone is not None
    for yaw in (math.radians(60), 0.35):            # another road; just past MAX_TURN_RAD
        away = SimpleNamespace(x=0.10, y=0.0, yaw=yaw)
        _step(g, zone, geo, away, 1.1, Scan((), 0.05, 1.1), corridor=(away, 0.079, -0.079, 0.02))
        assert g.zone is None, yaw
        _step(g, zone, geo, ahead, 1.2, Scan((), 0.05, 1.2))


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


def _skewed_then_aligned(person=()):
    """A zone first seen 0.25 rad off the lane (mid-turn), then again square to it, between walls at
    +-0.125 m with no lane seen: rev 7 re-anchors to the aligned sighting before the stop."""
    g, _, geo = _looking_gate()
    skewed = Zone(key=(0, "odom"), x=0.0, y=0.0, yaw=0.25, near=0.30, far=0.45, margin=0.02, lateral=0.01)
    aligned = Zone(key=(0, "odom"), x=0.0, y=0.0, yaw=0.0, near=0.30, far=0.45, margin=0.02, lateral=0.01)
    stop_x = 0.30 - 0.035 - B.front_x_m
    walls = [(x / 200, side, 0.002) for x in range(-80, 320) for side in (-0.125, 0.125)] + list(person)
    far = SimpleNamespace(x=stop_x - 0.5, y=0.0, yaw=0.0)
    first = _step(g, skewed, geo, far, 0.5, Scan(rays_at(far.x, walls, step_deg=1), 0.05, 0.5))
    assert g._state == "armed", first
    pose = SimpleNamespace(x=stop_x, y=0.0, yaw=0.0)
    reasons = []
    for i in range(30):
        t = 1.0 + i * 0.1
        reasons.append(g.step(t, zones=[skewed, aligned], pose=pose, key=(0, "odom"), still=True,
                              scan=Scan(rays_at(pose.x, walls, step_deg=1), 0.05, t), geo=geo, cruise=0.08,
                              look_s=1.0, min_scans=8, report_s=10.0, stale_s=0.5, range_sigma_m=SIGMA,
                              persist_k=2, persist_n=3)[1])
    return g, reasons


def test_rev7_a_zone_first_seen_mid_turn_takes_the_aligned_sighting_and_clears_between_walls():
    g, reasons = _skewed_then_aligned()
    assert abs(g._zone.yaw) < 1e-9 and g._first_yaw == 0.25     # the anchor moved; 'turned away' keeps the first
    assert "crosswalk_person_present" not in reasons and reasons[-1] is None, reasons[-3:]


def test_rev7_a_person_in_the_lane_still_holds_after_the_re_anchor():
    _, reasons = _skewed_then_aligned(person=[(0.40, 0.03, 0.02)])
    assert None not in reasons[10:] and "crosswalk_person_present" in reasons


def _map_walls(s, right=None, left=None, band=0.01, ahead=1.0):
    """D-573 rev 8: Fleet's route prior names map walls beside the lane, bound to the odom sample now."""
    import dataclasses
    from types import SimpleNamespace
    s.m._config = dataclasses.replace(s.m._config, crosswalk_map_wall_band_m=band)
    prior = SimpleNamespace(wall_left_m=left, wall_right_m=right, wall_ahead_m=ahead, heading_here_deg=0.0)
    # Fleet refreshes the prior every step: bound to the newest odom sample
    s.m.route_guide_binding = lambda now=None: dict(prior=prior, stamp_ns=s.m._return_evidence.trail.samples[-1].stamp_ns)


def _wall(y_face):
    return [(x / 100, y_face - 0.01, 0.01) for x in range(0, 120)]   # returns on a face at y_face


def test_a_map_wall_beside_the_lane_lets_an_empty_crosswalk_be_crossed():
    """v2 lap r46a/b at the west crosswalk: no seen corridor, A padded past the outer wall on the right."""
    held = Sim()
    held.objects = _wall(-0.115)
    held.to_stop()
    assert all(d.linear == 0.0 for _, d in held.run(7.0))          # without map walls the wall holds
    s = Sim()
    s.objects = _wall(-0.115)
    s.to_stop()
    _map_walls(s, right=-0.115)
    stop_t = s.t
    go = next(t for t, d in s.run(7.0) if d.linear > 0)
    assert go - stop_t <= 5.6


def test_a_person_inside_a_map_wall_still_holds_and_the_body_path_is_never_clipped():
    s = Sim()
    s.objects = _wall(-0.115) + [(NEAR + 0.1, -0.09, 0.012)]       # a figure 1.3 cm off the wall
    s.to_stop()
    _map_walls(s, right=-0.115)
    assert all(d.linear == 0.0 for _, d in s.run(7.0))
    s = Sim()
    s.objects = [(NEAR + 0.1, -0.03, 0.01)]                        # in the body's own path
    s.to_stop()
    _map_walls(s, right=-0.01)                                     # a wrong map wall inside the body path
    assert all(d.linear == 0.0 for _, d in s.run(7.0))


def test_map_walls_are_unused_without_the_band():
    s = Sim()
    s.objects = _wall(-0.115)
    s.to_stop()
    _map_walls(s, right=-0.115, band=None)
    assert all(d.linear == 0.0 for _, d in s.run(7.0))


def test_a_map_wall_on_the_left_is_clipped_the_same_way():
    s = Sim()
    s.objects = [(x, -y, r) for x, y, r in _wall(-0.115)]
    s.to_stop()
    _map_walls(s, left=0.115)
    stop_t = s.t
    assert next(t for t, d in s.run(7.0) if d.linear > 0) - stop_t <= 5.6


def test_a_map_wall_ending_before_the_look_area_does_not_clip_past_its_end():
    """Review 2026-10-19: an opening past a wall's end is floor; the look there is not clipped."""
    s = Sim()
    s.objects = _wall(-0.115)
    s.to_stop()
    _map_walls(s, right=-0.115, ahead=0.2)            # Fleet: the wall runs only 0.2 m on from the robot
    assert all(d.linear == 0.0 for _, d in s.run(7.0))


def test_the_clip_lines_follow_the_body_since_the_priors_odom_sample():
    """Moved 2 cm right and 0.1 m on since Fleet's sample: the wall is 2 cm nearer, drift widens it again."""
    import dataclasses
    from types import SimpleNamespace
    s = Sim()
    s.frame()
    m = s.m
    m._config = dataclasses.replace(m._config, crosswalk_map_wall_band_m=0.01)
    pose = SimpleNamespace(x=0.5, y=-0.02, yaw=0.0, frame="odom")
    m._return_evidence._image_pose = lambda ns: SimpleNamespace(x=0.4, y=0.0, yaw=0.0, frame="odom")
    prior = SimpleNamespace(wall_left_m=0.12, wall_right_m=-0.13, wall_ahead_m=0.6, heading_here_deg=0.0)
    m.route_guide_binding = lambda now=None: dict(prior=prior, stamp_ns=1)
    lane, left, right, ahead = m._crosswalk_walls(s.t, pose)
    drift = m._config.crosswalk_odom_error_fraction * math.hypot(0.1, 0.02)
    inset = 0.01 + 3 * m._config.crosswalk_range_sigma_m
    assert lane == 0.0
    assert left == pytest.approx(0.12 + 0.02 - inset + drift) and right == pytest.approx(-0.13 + 0.02 + inset - drift)
    assert ahead == pytest.approx(0.6 - 0.1 - drift)
    m._return_evidence._image_pose = lambda ns: SimpleNamespace(x=0.4, y=0.0, yaw=0.0, frame="other")
    assert m._crosswalk_walls(s.t, pose) is None       # another odom frame: no clip


def test_a_lane_turned_off_the_zone_axis_is_clipped_slice_by_slice():
    """v2 lap r48a: 5 deg between the lane and the zone axis; one sweep over all of A undid the clip."""
    from types import SimpleNamespace
    from core_features.line_follow.crosswalk.kernel import CLIP_SLICE_M, CrosswalkGate, Geometry, Zone
    gate = CrosswalkGate()
    skew = math.radians(-5.0)
    gate._walls = (skew, None, -0.1, 1.0)
    z = Zone(key=(1, "odom"), x=0.0, y=0.0, yaw=0.0, near=0.1, far=0.35)
    geo = Geometry(front_x=0.06, rear_x=-0.06, lidar_x=0.0, v_cross=0.04, s_wait=0.1, slow_from=0.2,
                   lane_half_m=0.1, body_half_m=0.06, strip_m=0.0, exit_m=0.2, end_margin=0.01)
    boxes = gate._clip(((0.1, 0.35, -0.15, 0.15),), z, geo, SimpleNamespace(x=0.0, y=0.0, yaw=0.0))
    assert len(boxes) == 5 and all(b[1] - b[0] <= CLIP_SLICE_M + 1e-9 for b in boxes)
    for x0, x1, lo, hi in boxes:       # each slice at the turned line's outermost point over it, never nearer
        assert lo == pytest.approx(-0.1 / math.cos(skew) + math.tan(skew) * x1) and hi == 0.15


def test_a_body_turned_off_the_zone_axis_keeps_the_clip_at_the_wall_not_at_its_heading_sweep():
    """v2 lap r50a: the body 0.1 rad off the zone axis; a heading sweep over A put the floor on the wall."""
    from types import SimpleNamespace
    from core_features.line_follow.crosswalk.kernel import CrosswalkGate, Geometry, Zone
    gate = CrosswalkGate()
    gate._walls = (0.0, None, -0.095, 1.0)
    z = Zone(key=(1, "odom"), x=0.0, y=0.0, yaw=0.0, near=0.1, far=0.35)
    geo = Geometry(front_x=0.06, rear_x=-0.06, lidar_x=0.0, v_cross=0.04, s_wait=0.1, slow_from=0.2,
                   lane_half_m=0.1, body_half_m=0.07, strip_m=0.0, exit_m=0.2, end_margin=0.01)
    boxes = gate._clip(((0.1, 0.55, -0.15, 0.15),), z, geo, SimpleNamespace(x=0.0, y=0.0, yaw=0.1))
    assert all(lo == pytest.approx(-0.095) for _, _, lo, _ in boxes)
    gate._walls = (0.0, None, -0.03, 1.0)                       # a wrong map wall inside the body path
    boxes = gate._clip(((0.1, 0.55, -0.15, 0.15),), z, geo, SimpleNamespace(x=0.0, y=0.0, yaw=0.1))
    assert all(lo == pytest.approx(-0.07) for _, _, lo, _ in boxes)
