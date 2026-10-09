"""D-559 리더 자취 재생: 자취 버퍼와 pure pursuit 를 운동학 로봇 두 대로 잰다."""

from __future__ import annotations

import math

import pytest
from core_features.swarm.trail import JOIN_MAX_M, Trail, TrailError, trail_twist

DT = 0.05
GAP = 0.6
SPEED = 0.15
MAX_W = 1.5


def leader_poses(segments, start=(0.0, 0.0, 0.0)):
    """(시간 s, linear, angular) 구간들 → DT 마다 리더 pose."""
    x, y, yaw = start
    out = [(x, y, yaw)]
    for seconds, v, w in segments:
        for _ in range(round(seconds / DT)):
            x += v * math.cos(yaw) * DT
            y += v * math.sin(yaw) * DT
            yaw += w * DT
            out.append((x, y, yaw))
    return out


def distance_to_path(px, py, path):
    best = math.inf
    for (ax, ay, _), (bx, by, _) in zip(path, path[1:]):
        vx, vy = bx - ax, by - ay
        n = vx * vx + vy * vy
        t = 0.0 if n == 0 else min(max(((px - ax) * vx + (py - ay) * vy) / n, 0.0), 1.0)
        best = min(best, math.hypot(px - ax - t * vx, py - ay - t * vy))
    return best


def run(path, follower=(-GAP, 0.0, 0.0), extra_s=8.0):
    """리더 표본을 하나씩 넣고 팔로워를 적분한다. (팔로워 자취, 마지막 출력, trail)."""
    fx, fy, fyaw = follower
    trail = Trail((fx, fy), path[0][:2])
    linear = 0.0
    trace, outputs = [], []
    for k in range(len(path) + round(extra_s / DT)):
        if k < len(path):
            assert trail.add(*path[k])
        linear, angular, reason = trail_twist(trail, fx, fy, fyaw, gap=GAP, max_speed=0.2,
                                              max_angular=MAX_W, prev_linear=linear, dt=DT)
        outputs.append((linear, angular, reason))
        fx += linear * math.cos(fyaw) * DT
        fy += linear * math.sin(fyaw) * DT
        fyaw += angular * DT
        trace.append((fx, fy, trail.progress))
    return trace, outputs, trail


def deviation(trace, path):
    """자취 = 팔로워 출발점에서 리더 출발점까지의 직선 + 리더가 지나간 길."""
    full = [(-GAP, 0.0, 0.0), *path]
    return max(distance_to_path(x, y, full) for x, y, _ in trace)


def test_straight_line_stays_on_the_line_and_stops_at_the_gap():
    path = leader_poses([(10.0, SPEED, 0.0)])
    trace, outputs, trail = run(path)
    assert deviation(trace, path) < 0.005
    assert trail.leader_s - trail.progress == pytest.approx(GAP, abs=0.02)
    assert outputs[-1][:2] == (0.0, 0.0)


def test_a_90_degree_turn_does_not_cut_the_corner():
    path = leader_poses([(5.0, SPEED, 0.0), (0.4 * math.pi / 2 / SPEED, SPEED, SPEED / 0.4),
                         (6.0, SPEED, 0.0)])
    trace, _, _ = run(path)
    assert deviation(trace, path) < 0.03


def test_an_in_place_pivot_corner_stays_within_the_lookahead_cut():
    """리더가 제자리에서 90° 돌면 꼭짓점이 생긴다. 깎는 양은 앞보기 길이로 묶인다."""
    path = leader_poses([(5.0, SPEED, 0.0), (math.pi / 2 / 0.8, 0.0, 0.8), (6.0, SPEED, 0.0)])
    trace, _, _ = run(path)
    assert deviation(trace, path) < 0.08


def test_an_s_curve_is_replayed():
    r = 0.5
    quarter = r * math.pi / 2 / SPEED
    path = leader_poses([(3.0, SPEED, 0.0), (quarter, SPEED, SPEED / r),
                         (quarter, SPEED, -SPEED / r), (quarter, SPEED, -SPEED / r),
                         (quarter, SPEED, SPEED / r), (4.0, SPEED, 0.0)])
    trace, _, _ = run(path)
    assert deviation(trace, path) < 0.03


def test_the_follower_stops_when_the_leader_stops_and_moves_again_after():
    path = leader_poses([(6.0, SPEED, 0.0), (10.0, 0.0, 0.0), (4.0, SPEED, 0.0)])
    trace, outputs, trail = run(path, extra_s=0.0)
    stop_end = round((6.0 + 10.0) / DT)
    assert outputs[stop_end - 1][0] == pytest.approx(0.0, abs=1e-3)
    gap_then = path[stop_end][0] - trace[stop_end - 1][0]
    assert GAP - 0.02 <= gap_then <= GAP + 0.05
    assert outputs[-1][0] > 0.05


def test_a_reversing_leader_adds_no_trail_and_the_follower_stops():
    path = leader_poses([(6.0, SPEED, 0.0), (3.0, -0.1, 0.0)])
    trace, outputs, trail = run(path)
    assert trail.leader_s == pytest.approx(GAP + 6.0 * SPEED, abs=CRUMB_SLACK)
    assert outputs[-1][0] == 0.0
    assert trail.leader_s - trail.progress >= GAP - 0.02


CRUMB_SLACK = 0.04


def test_far_off_the_trail_holds_as_lost():
    trail = Trail((0.0, 0.0), (0.6, 0.0))
    linear, angular, reason = trail_twist(trail, 0.1, 0.4, 0.0, gap=0.3, max_speed=0.2,
                                          max_angular=MAX_W, prev_linear=0.0, dt=DT)
    assert (linear, angular, reason) == (0.0, 0.0, "trail_lost")


def test_a_loop_crossing_does_not_jump_progress_ahead():
    """자취가 스스로 겹친다: 원을 한 바퀴 돌고 출발점을 지나간다. 진행 위치는 매 틱 이동량만큼만 늘어난다."""
    r = 0.4
    path = leader_poses([(4.0, SPEED, 0.0), (2 * math.pi * r / SPEED, SPEED, SPEED / r),
                         (5.0, SPEED, 0.0)])
    trace, _, _ = run(path)
    steps = [b[2] - a[2] for a, b in zip(trace, trace[1:])]
    assert max(steps) < 0.2 * DT + 0.02
    assert deviation(trace, path) < 0.05


def test_join_and_jump_limits():
    with pytest.raises(TrailError) as raised:
        Trail((0.0, 0.0), (JOIN_MAX_M + 0.1, 0.0))
    assert raised.value.code == "TRAIL_JOIN_TOO_FAR"
    trail = Trail((0.0, 0.0), (0.5, 0.0))
    assert trail.add(0.5 + JOIN_MAX_M + 0.1, 0.0, 0.0) is False


def test_crumbs_far_behind_the_follower_are_pruned():
    path = leader_poses([(60.0, SPEED, 0.0)])
    _, _, trail = run(path)
    # 자르기는 점을 더할 때만 한다: 리더가 선 뒤 팔로워가 gap 까지 더 간 만큼은 남는다.
    assert trail.progress - trail._s[0] < 1.0 + GAP + 0.1
    assert len(trail._s) < 100


# --- SwarmManager trail 모드 ---------------------------------------------------

from core_common.protocol.schemas import SwarmFollowParams  # noqa: E402
from core_features.safety.manager import BatteryPolicy, SafetyManager, SpeedLimits  # noqa: E402
from core_features.state.manager import StateManager  # noqa: E402
from core_features.swarm import ReferencePose, SwarmError, SwarmManager  # noqa: E402
from test_swarm import CAPABLE, FakeClock, FakeEvents, FakeNav  # noqa: E402


class Rig:
    def __init__(self, gap=None):
        self.clock, self.events, self.nav = FakeClock(), FakeEvents(), FakeNav()
        self.state = StateManager(robot_id="rosy_01")
        self.safety = SafetyManager(SpeedLimits(), BatteryPolicy(), self.events)
        self.pose = (0.0, 0.0, 0.0, "map", 0.0)
        self.sent = []
        #: (gap, stop, resume) or None (stale); gap None = clear
        self.gap = gap or (lambda v, w, now: (None, 0.1, 0.13))
        self.swarm = SwarmManager(
            self.events, self.state, self.nav, self.safety, CAPABLE, clock=self.clock,
            map_id_provider=lambda: self.state.map_id, robot_id="rosy_01",
            pose_provider=lambda: self.pose, twist_sink=self.sent.append,
            obstacle_gap=lambda v, w, now: self.gap(v, w, now))

    def follow(self, **overrides):
        body = {"target_robot_id": "rosy_02", "distance": 0.5, "mode": "trail"}
        body.update(overrides)
        return self.swarm.follow(SwarmFollowParams(**body))

    def leader(self, x, y=0.0, yaw=0.0, frame="map", map_id=None):
        self.swarm.on_reference_pose(ReferencePose("rosy_02", x, y, yaw, frame=frame, map_id=map_id))

    def step(self, seconds=0.05):
        self.clock.advance(seconds)
        self.swarm.tick()
        self.swarm.trail_tick(self.clock.now)
        return self.sent[-1]

    def hold_reason(self):
        return self.swarm.state_payload()["trail"]["hold_reason"]


def test_trail_mode_sends_no_nav2_goal_and_drives_the_nav_slot():
    rig = Rig()
    rig.follow()
    for k in range(1, 30):
        rig.leader(0.5 + 0.03 * k)
        twist = rig.step()
    assert rig.nav.goals == []
    assert twist[0] > 0.1 and abs(twist[1]) < 1e-6
    assert rig.swarm.state_payload()["mode"] == "trail"


def test_trail_refuses_a_lateral_offset():
    rig = Rig()
    with pytest.raises(SwarmError) as raised:
        rig.follow(lateral=0.2)
    assert raised.value.code == "VALIDATION_ERROR"


def test_a_lost_stream_holds_and_a_new_sample_resumes():
    rig = Rig()
    rig.follow()
    rig.leader(1.2)
    assert rig.step()[0] > 0
    rig.clock.advance(1.1)
    assert rig.step() is None
    assert rig.hold_reason() == "stream_lost"
    rig.leader(1.25)
    assert rig.step() is not None


def test_odom_frame_samples_hold_and_map_samples_resume():
    rig = Rig()
    rig.follow()
    rig.leader(1.2)
    rig.leader(1.3, frame="odom")
    assert rig.step() is None
    assert rig.hold_reason() == "reference_frame_not_map"
    assert ("swarm.hold", {"reason": "reference_frame_not_map",
                           "formation": "follow:rosy_02@0.50/0.00"}) in rig.events.published
    rig.leader(1.3)
    assert rig.step()[0] > 0
    rig.leader(1.35, frame=None)                         # a leader that does not say
    assert rig.step() is None and rig.hold_reason() == "reference_frame_not_map"


def test_own_odom_pose_holds():
    rig = Rig()
    rig.follow()
    rig.leader(1.2)
    rig.pose = (0.0, 0.0, 0.0, "odom", 0.0)
    assert rig.step() is None
    assert rig.hold_reason() == "own_pose_not_map"
    rig.pose = (0.0, 0.0, 0.0, "map", 0.6)               # a map pose that stopped updating
    assert rig.step() is None
    assert rig.hold_reason() == "own_pose_stale"


def test_a_leader_too_far_to_join_ends_the_follow():
    rig = Rig()
    rig.follow()
    rig.leader(2.0)
    assert not rig.swarm.active
    assert rig.sent[-1] is None
    assert any(t == "swarm.aborted" and d["reason"] == "trail_join_too_far"
               for t, d in rig.events.published)


def test_a_leader_jump_latches_trail_lost():
    """10 Hz samples: a 0.5 m step is a relocalisation, not driving (bound 0.3 m + ceiling x dt)."""
    rig = Rig()
    rig.follow()
    rig.leader(1.0)
    rig.clock.advance(0.1)
    rig.leader(1.5)
    assert rig.step() is None
    rig.leader(1.55)
    assert rig.step() is None
    assert rig.hold_reason() == "trail_lost"


def test_after_a_stream_gap_the_jump_bound_grows_with_time():
    rig = Rig()
    rig.follow()
    rig.leader(0.6)
    rig.clock.advance(5.0)                                # a 5 s cut, leader drove 0.6 m on
    rig.leader(1.2)
    assert rig.swarm.state_payload()["trail"]["leader_s"] == pytest.approx(1.2)


def test_the_body_stop_resumes_only_past_the_gap_that_stopped_it():
    """Path-mode gaps scale with speed: the slow restart twist must not use its own small resume."""
    gaps = {"gap": None}
    rig = Rig(gap=lambda v, w, now: (gaps["gap"], 0.02 + 0.5 * v, 0.05 + 0.5 * v))
    rig.follow()
    rig.leader(1.2)
    for _ in range(10):
        rig.step()                                       # up to speed (0.15): stop 0.095, resume 0.125
    gaps["gap"] = 0.09
    assert rig.step() is None
    gaps["gap"] = 0.10                                   # beyond the 0.025 m/s restart's resume 0.0625
    assert rig.step() is None and rig.hold_reason() == "obstacle"
    gaps["gap"] = 0.13
    assert rig.step()[0] > 0


def test_the_body_stop_holds_with_hysteresis_and_a_stale_sensor_holds():
    gaps = {"gap": None}
    rig = Rig(gap=lambda v, w, now: None if gaps["gap"] == "stale" else (gaps["gap"], 0.10, 0.13))
    rig.follow()
    rig.leader(1.2)
    assert rig.step()[0] > 0
    gaps["gap"] = 0.08
    assert rig.step() is None and rig.hold_reason() == "obstacle"
    gaps["gap"] = 0.12                                   # between stop and resume: still held
    assert rig.step() is None
    gaps["gap"] = 0.2
    assert rig.step()[0] > 0
    gaps["gap"] = "stale"
    assert rig.step() is None and rig.hold_reason() == "obstacle_sensor_stale"


def test_map_mismatch_holds_and_estop_cancels_and_clears_the_slot():
    rig = Rig()
    rig.state.set_map_id("site_a")
    rig.follow()
    rig.leader(1.2, map_id="site_a")
    assert rig.step()[0] > 0
    rig.leader(1.25, map_id="site_b")
    assert rig.step() is None and rig.hold_reason() == "map_mismatch"
    rig.safety.trigger_estop("test")
    rig.swarm.tick()
    assert not rig.swarm.active and rig.sent[-1] is None
    rig.swarm.trail_tick(rig.clock.now)
    assert rig.sent[-1] is None
