"""Prototype B: particle filter over the checked-in paint map."""

import math
import time

import numpy as np
import pytest
from control.sensing.paint_localizer import PaintLocalizer, PaintMap
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
    dropped there is no estimate until a known pose is given again."""
    loc = localizer()
    assert loc.update(0.0, None, WORLD.render(START), GROUND, **KW) is None
    assert loc.update(0.2, START, WORLD.render(START), GROUND, **KW) is None
    loc.initialise(START)
    assert loc.update(0.4, START, WORLD.render(START), GROUND, **KW) is not None


def test_covariance_grows_without_paint_and_shrinks_with_it():
    loc = localizer()
    blank = np.full((180, 320), 109, np.uint8)
    for k in range(5):
        weak = loc.update(k * 0.2, START, blank, GROUND, **KW)
    for k in range(5, 12):
        strong = loc.update(k * 0.2, START, WORLD.render(START), GROUND, **KW)
    assert strong.spread_m < weak.spread_m


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
