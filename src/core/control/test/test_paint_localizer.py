"""Prototype B: particle filter over the checked-in paint map."""

import math
import time

import numpy as np
import pytest
from control.sensing.paint_localizer import (
    GAP_MAX_S,
    GAP_MAX_TRAVEL_M,
    PaintLocalizer,
    PaintMap,
)
from lane_sim import CAM_X, GROUND, KW, stl_world

WORLD = stl_world()
START = (-1.26955, 0.24255, -math.pi / 2)


def localizer(pose=START, particles=300):
    return PaintLocalizer(PaintMap.from_bundle(), camera_x_offset_m=CAM_X,
                          particles=particles, seed=7).initialise(pose)


def test_a_still_robot_keeps_its_pose():
    loc = localizer()
    for k in range(5):
        estimate = loc.update(k * 0.2, START, WORLD.render(START), GROUND, **KW)
    assert math.dist(estimate.pose[:2], START[:2]) < 0.01
    assert abs(estimate.pose[2] - START[2]) < math.radians(3)


def test_it_corrects_a_lateral_odometry_error():
    """Odometry says straight ahead; the robot really drifts 3 cm sideways.
    Matching the paint must pull the estimate back to the true pose."""
    loc = localizer()
    true_pose, odom_pose = START, START
    for k in range(12):
        true_pose = (true_pose[0] + 0.0025, true_pose[1] - 0.016, true_pose[2])
        odom_pose = (odom_pose[0], odom_pose[1] - 0.016, odom_pose[2])
        estimate = loc.update(k * 0.2, odom_pose, WORLD.render(true_pose), GROUND, **KW)
    assert math.dist(estimate.pose[:2], true_pose[:2]) < math.dist(odom_pose[:2], true_pose[:2])
    assert math.dist(estimate.pose[:2], true_pose[:2]) < 0.02


def test_it_converges_once_the_slip_stops():
    """Same 30 mm slip, then 12 more steps without slip: odometry stays
    30 mm off, the paint pulls the estimate to within a few mm (measured
    2.7 mm at seed 7; 3.7 and 5.3 mm at seeds 1 and 2)."""
    loc = localizer()
    true_pose, odom_pose = START, START
    for k in range(24):
        slip = 0.0025 if k < 12 else 0.0
        true_pose = (true_pose[0] + slip, true_pose[1] - 0.016, true_pose[2])
        odom_pose = (odom_pose[0], odom_pose[1] - 0.016, odom_pose[2])
        estimate = loc.update(k * 0.2, odom_pose, WORLD.render(true_pose), GROUND, **KW)
    assert math.dist(odom_pose[:2], true_pose[:2]) > 0.029
    assert math.dist(estimate.pose[:2], true_pose[:2]) < 0.008


def test_it_follows_an_odometry_heading_bias():
    """Truth drives straight down the west lane; odometry believes it turns
    0.004 rad per 16 mm step (0.1 rad over 0.4 m). The per-metre yaw noise
    lets the paint hold the heading: worst of 8 seeds measured 2.03 deg
    (3.99 deg without MOTION_YAW_SIGMA_PER_M)."""
    worst = 0.0
    for seed in range(8):
        loc = PaintLocalizer(PaintMap.from_bundle(), camera_x_offset_m=CAM_X,
                             seed=seed).initialise(START)
        true_pose, odom_pose = START, START
        for k in range(25):
            true_pose = (true_pose[0], true_pose[1] - 0.016, true_pose[2])
            yaw = odom_pose[2] + 0.004
            odom_pose = (odom_pose[0] + 0.016 * math.cos(yaw),
                         odom_pose[1] + 0.016 * math.sin(yaw), yaw)
            estimate = loc.update(k * 0.2, odom_pose, WORLD.render(true_pose), GROUND, **KW)
        worst = max(worst, abs(estimate.pose[2] - true_pose[2]))
    assert worst < math.radians(3.0), math.degrees(worst)


def test_a_still_filter_roughens_its_heading():
    """Stopped 6 deg off (either side): with no motion only the time-based
    roughening lets the particles find the heading. Worst of 4 seeds x 2
    sides after 5 s measured 2.07 deg (3.98 deg without it)."""
    worst = 0.0
    frame = WORLD.render(START)
    for seed in range(4):
        for error in (math.radians(6.0), -math.radians(6.0)):
            loc = PaintLocalizer(PaintMap.from_bundle(), camera_x_offset_m=CAM_X,
                                 seed=seed).initialise((START[0], START[1], START[2] + error))
            for k in range(26):
                estimate = loc.update(k * 0.2, START, frame, GROUND, **KW)
            worst = max(worst, abs(estimate.pose[2] - START[2]))
    assert worst < math.radians(2.5), math.degrees(worst)


def test_a_frame_with_no_paint_lowers_the_match_score():
    loc = localizer()
    blank = np.full((180, 320), 109, np.uint8)
    estimate = loc.update(0.0, START, blank, GROUND, **KW)
    assert estimate.match < 0.3


def test_no_ground_or_no_pose_is_no_estimate():
    loc = localizer()
    assert loc.update(0.0, None, WORLD.render(START), GROUND, **KW) is None
    assert loc.update(0.0, START, WORLD.render(START), None, **KW) is None


def test_a_cleared_filter_stays_cleared_until_initialised_again():
    """Global initialisation is out of scope (design §6): once the state is
    dropped (a gap longer than GAP_MAX_S) there is no estimate until a known
    pose is given again."""
    loc = localizer()
    frame = WORLD.render(START)
    assert loc.update(0.0, None, frame, GROUND, **KW) is None
    assert loc.update(GAP_MAX_S + 0.2, None, frame, GROUND, **KW) is None
    assert loc.update(GAP_MAX_S + 0.4, START, frame, GROUND, **KW) is None
    loc.initialise(START)
    assert loc.update(GAP_MAX_S + 0.6, START, frame, GROUND, **KW) is not None


def _walk(steps, start=START, step_m=0.016):
    """Straight poses down the west lane from START."""
    return [(start[0], start[1] - k * step_m, start[2]) for k in range(steps)]


def test_a_short_gap_keeps_the_particles():
    """One missing pose and one missing ground frame: no output and no
    predict during the gap, then the odometry increment across it is
    applied at once and the estimate carries on."""
    loc = localizer()
    poses = _walk(10)
    for k in range(4):
        loc.update(k * 0.2, poses[k], WORLD.render(poses[k]), GROUND, **KW)
    assert loc.update(0.8, None, WORLD.render(poses[4]), GROUND, **KW) is None
    assert loc.update(1.0, poses[5], WORLD.render(poses[5]), None, **KW) is None
    for k in range(6, 10):
        estimate = loc.update(k * 0.2, poses[k], WORLD.render(poses[k]), GROUND, **KW)
    assert estimate is not None
    assert math.dist(estimate.pose[:2], poses[-1][:2]) < 0.01


def test_a_gap_longer_than_its_timeout_clears_the_filter():
    loc = localizer()
    frame = WORLD.render(START)
    loc.update(0.0, START, frame, GROUND, **KW)
    assert loc.update(0.2, None, frame, GROUND, **KW) is None
    assert loc.update(0.2 + GAP_MAX_S + 0.01, START, frame, GROUND, **KW) is None
    assert loc.update(0.4 + GAP_MAX_S, START, frame, GROUND, **KW) is None


def test_a_gap_that_travelled_too_far_clears_the_filter():
    loc = localizer()
    loc.update(0.0, START, WORLD.render(START), GROUND, **KW)
    assert loc.update(0.2, None, WORLD.render(START), GROUND, **KW) is None
    moved = (START[0], START[1] - GAP_MAX_TRAVEL_M - 0.005, START[2])
    assert loc.update(0.4, moved, WORLD.render(moved), GROUND, **KW) is None
    assert loc.update(0.6, moved, WORLD.render(moved), GROUND, **KW) is None


def test_covariance_grows_without_paint_and_shrinks_with_it():
    loc = localizer()
    blank = np.full((180, 320), 109, np.uint8)
    for k in range(5):
        weak = loc.update(k * 0.2, START, blank, GROUND, **KW)
    for k in range(5, 12):
        strong = loc.update(k * 0.2, START, WORLD.render(START), GROUND, **KW)
    assert strong.spread_m < weak.spread_m


def _along_lateral_sigma(loc, yaw):
    p = loc._particles[:, :2] - loc._particles[:, :2].mean(axis=0)
    along = p[:, 0] * math.cos(yaw) + p[:, 1] * math.sin(yaw)
    return float(along.std()), float((-p[:, 0] * math.sin(yaw) + p[:, 1] * math.cos(yaw)).std())


def test_the_along_track_spread_follows_the_wheel_scale_not_the_sideways_slip():
    """1 m straight in 16 mm steps with no paint in view: only the motion
    noise spreads the particles. Along a straight or gently bending lane
    the paint never constrains the along-track direction either, so this is
    the spread the filter carries down a corridor. Sideways it must stay
    wide enough for the slip test (0.16 m/m); along-track it must stay
    well under MAX_SPREAD_M, or a long corridor trips the SPREAD stop with
    an estimate a few mm off (all-lane tour, seed 3: LOCALISE_STOP on
    east:r at 20.0 mm, 98 % of it along-track, estimate 1.7 mm off)."""
    from control.sensing.route_map import MAX_SPREAD_M
    blank = np.full((180, 320), 109, np.uint8)
    worst_along, least_lateral = 0.0, math.inf
    for seed in range(4):
        loc = PaintLocalizer(PaintMap.from_bundle(), camera_x_offset_m=CAM_X,
                             seed=seed).initialise(START)
        before = _along_lateral_sigma(loc, START[2])
        for k, pose in enumerate(_walk(64)):
            loc.update(k * 0.2, pose, blank, GROUND, **KW)
        along, lateral = _along_lateral_sigma(loc, START[2])
        worst_along = max(worst_along, math.sqrt(max(0.0, along ** 2 - before[0] ** 2)))
        least_lateral = min(least_lateral, math.sqrt(max(0.0, lateral ** 2 - before[1] ** 2)))
    assert worst_along < 0.75 * MAX_SPREAD_M, worst_along
    assert least_lateral > MAX_SPREAD_M, least_lateral


def test_the_paint_map_leaves_out_the_wall_footprint_but_keeps_crosswalk_bars():
    """The perimeter wall's 8 bottom-face triangles are floor-height in the
    STL, but in Gazebo the 155 mm wall stands on them: the camera never sees
    them as paint. Crosswalk bars are paint the camera does see."""
    paint = PaintMap.from_bundle()
    # Wall strips (5 mm, at the map edge): the nearest lane line is 28 mm
    # (west) and 14 mm (north) in from the strip's centre.
    assert paint.distance_at(np.array([[-1.4025, 0.0], [0.0, 0.6275]])).min() > 0.01
    # A crosswalk bar beside the west road (0.121 m bar, measured centre).
    assert paint.distance_at(np.array([[-1.29, -0.146]]))[0] == 0.0
    # The lane centre at the scenario start is clear of paint.
    assert paint.distance_at(np.array([START[:2]]))[0] > 0.05


def test_one_update_fits_the_frame_budget():
    """30 ms per frame on the Windows host at 300 particles (plan Task 4)."""
    loc = localizer()
    frame = WORLD.render(START)
    loc.update(0.0, START, frame, GROUND, **KW)          # BEV lookup tables
    times = []
    for k in range(1, 11):
        t0 = time.perf_counter()
        loc.update(k * 0.2, START, frame, GROUND, **KW)
        times.append(time.perf_counter() - t0)
    assert float(np.median(times)) <= 0.030, times


@pytest.mark.parametrize("bad", [0, -5, 2.5, True])
def test_particle_count_must_be_a_positive_integer(bad):
    with pytest.raises(ValueError):
        PaintLocalizer(PaintMap.from_bundle(), camera_x_offset_m=CAM_X, particles=bad)
