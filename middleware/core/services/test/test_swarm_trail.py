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
    assert trail.leader_s == pytest.approx(6.0 * SPEED + 0.0, abs=CRUMB_SLACK)
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
