"""Motion names a camera detection only when one robot and one detection moved alike and the rest stood still."""
from fleet.localization.motion_match import MotionMatcher
from fleet.server.identity import IdentityConfig

CONFIG = IdentityConfig()
MIN_MOVE_M, WINDOW_S = CONFIG.motion_min_move_m, CONFIG.motion_window_s

BAY, LANE, BOX = (-0.37, 0.48), (0.85, -0.48), (-0.70, 0.09)


def _matcher(points, robots):
    m = MotionMatcher(CONFIG.track_step_m, min_move_m=CONFIG.motion_min_move_m, tol_m=CONFIG.motion_tol_m,
                      still_m=CONFIG.motion_still_m, window_s=CONFIG.motion_window_s)
    assert m.observe(0.0, points, robots) is None   # the first frame is the baseline
    return m


def test_the_one_detection_that_moved_like_the_robot_is_named():
    m = _matcher([BAY, LANE, BOX], {"rosy_45": (0.17, -0.09), "rosy_46": (1.0, 1.0)})
    # y8xs 2026-11-21: its own map says 0.196 m (any direction: the frames differ), the camera saw 0.196 m
    assert m.observe(1.0, [(-0.37, 0.38), LANE, BOX], {"rosy_45": (0.24, -0.02), "rosy_46": (1.0, 1.0)}) is None
    robot, point, moved = m.observe(2.0, [(-0.37, 0.285), LANE, BOX], {"rosy_45": (0.31, 0.047), "rosy_46": (1.0, 1.0)})
    assert robot == "rosy_45" and point == (-0.37, 0.285) and abs(moved - 0.196) < 0.005


def test_two_things_moving_or_a_wrong_distance_names_nothing():
    robots0, robots1 = {"rosy_45": (0.0, 0.0), "rosy_46": (1.0, 1.0)}, {"rosy_45": (0.2, 0.0), "rosy_46": (1.0, 1.0)}
    m = _matcher([BAY, LANE, BOX], robots0)
    assert m.observe(1.0, [(-0.37, 0.28), (0.85, -0.38), BOX], robots1) is None     # a second detection moved too
    m = _matcher([BAY, LANE, BOX], robots0)
    assert m.observe(1.0, [(-0.37, 0.38), LANE, BOX], robots1) is None               # 0.10 m seen, 0.20 m reported
    m = _matcher([BAY, LANE, BOX], robots0)
    both = {"rosy_45": (0.2, 0.0), "rosy_46": (1.2, 1.0)}
    assert m.observe(1.0, [(-0.37, 0.28), LANE, BOX], both) is None                  # two robots moved
    m = _matcher([BAY, LANE, BOX], robots0)
    assert m.observe(1.0, [BAY, LANE, BOX], {"rosy_45": (0.0, MIN_MOVE_M + 0.05), "rosy_46": (1.0, 1.0)}) is None  # a pose jump, nothing moved


def test_a_lost_track_a_silent_robot_or_an_old_baseline_starts_over():
    robots = {"rosy_45": (0.0, 0.0)}
    m = _matcher([BAY, LANE], robots)
    assert m.observe(1.0, [BAY], {"rosy_45": (0.2, 0.0)}) is None                    # a detection vanished
    m = _matcher([BAY, LANE], {"rosy_45": (0.0, 0.0), "rosy_46": (1.0, 1.0)})
    assert m.observe(1.0, [(-0.37, 0.28), LANE], {"rosy_45": (0.2, 0.0), "rosy_46": None}) is None   # rosy_46 went silent
    m = _matcher([BAY, LANE], robots)
    assert m.observe(WINDOW_S + 1.0, [(-0.37, 0.28), LANE], {"rosy_45": (0.2, 0.0)}) is None         # too old: new baseline
    robot, _point, _moved = m.observe(WINDOW_S + 2.0, [(-0.37, 0.08), LANE], {"rosy_45": (0.4, 0.0)})
    assert robot == "rosy_45"
