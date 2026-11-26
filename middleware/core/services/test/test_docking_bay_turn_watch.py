"""Every in-place turn is closed on the LiDAR yaw change (bay_turn_watch.py; y8xs 2026-11-20: wheels turned, the body did not).

The sim's LiDAR answer is the world's own yaw increment times `follow`: 1.0 = the body follows the wheels, 0.0 = it does not."""

from __future__ import annotations

import math
from types import SimpleNamespace

from core_common.protocol.schemas import DockState
from core_features.docking.bay_scan_pose import BayScanPose
from core_features.docking.manager import DockPhase
from test_docking_bay import DT, a_bay, done


def run(p, follow=1.0, answer=True, limit_s=300.0, feed=True, lag=0.0, seen=None):
    sample = SimpleNamespace(name="scan")
    last = {}
    yaws = []                                  # (clock, world yaw): the LiDAR answers describe the world as it was lag seconds ago
    t0, k = p.clock.now, 0
    while p.clock.now - t0 < limit_s:
        if k % 2 == 0:
            p.detector.capture()
            p.manager.note_body_scan(None, None, None, p.clock.now)
            if feed:
                p.manager.note_bay_scan_sample(sample, lag)
        p.manager.tick()
        yaws.append((p.clock.now, p.world.pose[2]))
        if seen is not None and p.manager.status().last_event not in seen:
            seen.append(p.manager.status().last_event)
        if p.manager.phase is DockPhase.TURNING and "yaw" not in last:
            last["yaw"] = p.world.pose[2]
        request = p.manager.bay_scan_request() if answer else None
        if request is not None and "yaw" in last:
            cap = next((y for c, y in reversed(yaws) if c <= p.clock.now - lag), yaws[0][1])
            d = math.remainder(cap - last["yaw"], math.tau)
            inc = (follow(d) if callable(follow) else follow) * d
            last["yaw"] = cap
            p.manager.note_bay_scan_match(BayScanPose(x=0.0, y=0.0, heading=inc, inliers=0.9, margin=0.5, median_m=0.01),
                                          request_id=request[0])
        if done(p.manager):
            break
        p.world.step()
        p.clock.now += DT
        k += 1


def test_a_turn_the_lidar_sees_the_body_follow_completes():
    p = a_bay()
    p.manager.dock()
    run(p)
    assert p.manager.state is DockState.DOCKED, p.manager._error


def test_a_turn_the_body_does_not_follow_stops_and_fails():
    # odometry says turned, the LiDAR says (almost) not: no blind continuation
    p = a_bay()
    p.manager.dock()
    run(p, follow=0.2)
    assert p.manager.state is DockState.DOCK_FAILED and "turn not followed by the body" in p.manager._error, p.manager._error
    assert not [c for ph, c in p.world.commands if ph is DockPhase.ACQUIRING]


def test_a_turn_with_a_scan_feed_but_no_scan_match_is_not_verified_and_stops():
    p = a_bay()
    p.manager.dock()
    run(p, answer=False)
    assert p.manager.state is DockState.DOCK_FAILED and "not verified by LiDAR" in p.manager._error, p.manager._error


def test_without_a_scan_feed_the_turn_is_odometry_only_as_before():
    p = a_bay()
    p.manager.dock()
    t0 = p.clock.now
    k = 0
    while p.clock.now - t0 < 300.0 and not done(p.manager):
        if k % 2 == 0:
            p.detector.capture()
            p.manager.note_body_scan(None, None, None, p.clock.now)
        p.manager.tick()
        p.world.step()
        p.clock.now += DT
        k += 1
    assert p.manager.state is DockState.DOCKED, p.manager._error

def test_a_robot_that_cannot_turn_clockwise_is_turned_the_other_way_and_docks():
    # y8xs: cw odometry -24 deg = LiDAR -0.5 deg, ccw fine. The staging turn is cw (_turn_dir -1): flipped once, outside the row.
    p = a_bay()
    p.manager.dock()
    run(p, follow=lambda d: 0.0 if d < 0 else 1.0)
    assert p.manager.state is DockState.DOCKED, p.manager._error
    assert p.manager._bay_phases._tw_flipped
    assert any(c[1] > 0 for ph, c in p.world.commands if ph is DockPhase.TURNING)


def test_a_robot_that_follows_in_neither_direction_fails_after_one_flip():
    p = a_bay()
    p.manager.dock()
    run(p, follow=0.0)
    assert p.manager.state is DockState.DOCK_FAILED and "turn not followed by the body" in p.manager._error, p.manager._error


def test_a_scan_feed_that_stops_during_the_turn_stops_the_turn():
    p = a_bay()
    p.manager.dock()
    state = {"n": 0}
    orig = p.manager.note_bay_scan_sample

    def cut(sample, lag=0.0):
        state["n"] += 1
        if state["n"] < 6:
            orig(sample, lag)
    p.manager.note_bay_scan_sample = cut
    run(p)
    assert p.manager.state is DockState.DOCK_FAILED and "no fresh scan" in p.manager._error, p.manager._error


def test_the_watch_is_cleared_when_the_turn_is_over():
    p = a_bay()
    p.manager.dock()
    run(p)
    assert p.manager._bay_phases._tw is None

def test_no_scan_sample_ever_means_no_turn_when_the_scan_feed_is_required():
    p = a_bay()
    p.manager._cfg.bay_turn_needs_scan = True
    p.manager.dock()
    run(p, feed=False)
    assert p.manager.state is DockState.DOCK_FAILED and "needs the LiDAR scan feed" in p.manager._error, p.manager._error
    assert not [c for ph, c in p.world.commands if ph is DockPhase.TURNING and c[1] != 0.0]


def test_a_fresh_dock_may_flip_its_staging_turn_again():
    p = a_bay()
    p.manager.dock()
    run(p, follow=lambda d: 0.0 if d < 0 else 1.0)
    assert p.manager._bay_phases._tw_flipped
    q = a_bay()
    q.manager._bay_phases._tw_flipped = True
    q.manager.dock()
    run(q, follow=lambda d: 0.0 if d < 0 else 1.0)
    assert q.manager.state is DockState.DOCKED, q.manager._error        # the stale flag was reset, so it could flip

def test_a_lagging_scan_is_compared_with_the_wheels_at_its_own_capture_time():
    # panel A/B: a scan 0.6 s old at turn rate is ~10+ deg behind the odometry of the moment it arrives; compared at equal timestamps it agrees
    p = a_bay()
    p.manager.dock()
    run(p, lag=0.6)
    assert p.manager.state is DockState.DOCKED, p.manager._error


def test_the_flip_and_each_watch_verdict_show_in_last_event():
    p = a_bay()
    p.manager.dock()
    seen = []
    run(p, follow=lambda d: 0.0 if d < 0 else 1.0, seen=seen)
    assert any(e and e.startswith("turn watch: odometry") for e in seen), seen
    assert any(e and e.startswith("turn flipped: cw did not move the body") for e in seen), seen
    assert any(e and "(after the flip)" in e for e in seen), seen


def test_a_robot_that_failed_cw_turns_ccw_first_at_its_next_dock_and_the_config_can_force_a_sense():
    p = a_bay()
    p.manager._bay_phases._turn_bad_dir = -1.0
    p.manager.dock()
    run(p, follow=lambda d: 0.0 if d < 0 else 1.0)
    assert p.manager.state is DockState.DOCKED and not p.manager._bay_phases._tw_flipped      # no failed cw attempt at all
    turning = [c[1] for ph, c in p.world.commands if ph is DockPhase.TURNING and c[1] != 0.0]
    assert turning and all(w > 0 for w in turning)
    q = a_bay()
    q.manager._cfg.bay_turn_first_dir = 1
    q.manager.dock()
    run(q)
    assert q.manager.state is DockState.DOCKED
    assert all(c[1] >= 0 for ph, c in q.world.commands if ph is DockPhase.TURNING)

def test_odometry_reading_4_percent_more_than_the_lidar_over_a_half_turn_still_follows_and_closes():
    # round 21: 182/175 and 180/172 deg: the gap grows with the turn; the 8 deg floor plus 6 % of the turn allows it
    p = a_bay()
    p.manager.dock()
    run(p, follow=0.96)
    assert p.manager.state is DockState.DOCKED, p.manager._error


def test_a_clearly_unfollowed_turn_still_fails_with_the_proportional_allowance():
    p = a_bay()
    p.manager.dock()
    run(p, follow=0.85)                               # 27 deg short over 180: beyond floor + 6 %
    assert p.manager.state is DockState.DOCK_FAILED and "not followed" in p.manager._error, p.manager._error


def test_a_turn_that_stalls_mid_way_fails_on_the_strict_window():
    p = a_bay()
    p.manager.dock()
    done_deg = {"v": 0.0}

    def follow(d):
        done_deg["v"] += abs(math.degrees(d))
        return 1.0 if done_deg["v"] < 40.0 else 0.0                       # follows the first 40 deg, then the body stops
    run(p, follow=follow)
    assert p.manager.state is DockState.DOCK_FAILED and "not followed" in p.manager._error, p.manager._error


def test_a_staging_turn_the_lidar_finds_8_deg_short_is_closed_on_the_lidar():
    p = a_bay()
    p.manager.dock()
    seen = []
    # the body follows 95 %: ends ~9 deg short of the 180; odometry agrees within the allowance, the LiDAR closure turns on
    run(p, follow=0.955, seen=seen)
    assert p.manager.state is DockState.DOCKED, p.manager._error
    assert any(e and e.startswith("turn closed on the LiDAR") for e in seen), seen


def test_pitin_over_pi_target_and_flipped_cw_past_threshold_do_not_false_overshoot():
    import pytest
    from test_docking_bay_pitin import _at_the_junction

    p, bp = _at_the_junction(0.562, bay_heading=167.0)
    assert abs(bp._turn_want - math.radians(167.0)) < 1e-6
    pose = bp._odometry()
    bp._turn_dir = -1.0
    bp._turn_want, bp._turn_passed_pi = math.pi + 0.25, False
    bp._turn_target = pose[2] + bp._turn_dir * (math.pi + 0.25)
    bp._tw_start(pose[2], p.clock.now, want=math.pi + 0.25)
    bp._tick_turning(p.clock.now)
    assert p.manager.state is not DockState.DOCK_FAILED
    bp._tw_flipped = False
    bp._tw = {"lidar": -0.30, "lidar_odo": -0.30}
    bp._turn_dir = -1.0
    bp._h._cfg.bay_turn_flip_max_rad = 0.50
    assert bp._tw_flip(pose, p.clock.now) is True
    assert bp._turn_want == pytest.approx(math.pi + 0.30) and bp._turn_passed_pi is False
    bp._tick_turning(p.clock.now)
    assert p.manager.state is not DockState.DOCK_FAILED