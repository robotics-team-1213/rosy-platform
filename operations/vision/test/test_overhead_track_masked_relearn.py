"""D-600: a learn leaves out the robot regions Fleet names and fills that floor once it is free."""

import numpy as np

from rosy_vision.track.background_blob import BAKED_SCORE_MAX, BackgroundBlobDetector, BackgroundStore
from rosy_vision.track.model import Calibration, Frame
from rosy_vision.track.robot_mask import FILL_CONFIRM_FRAMES, parse_regions

# 0.01 m per pixel, y up: pixel (u, v) is map (0.01 u, 3.6 - 0.01 v).
CAL = Calibration(source_id="ceiling_north", map_id="map_v2_fleet", revision="paint-3f9a1c2b7d40",
                  image_to_map=(0.01, 0.0, 0.0, 0.0, -0.01, 3.6, 0.0, 0.0, 1.0),
                  image_size=(640, 360), track_bounds_m=(0.0, 0.0, 6.4, 3.6))
PARKED = {"x": 3.0, "y": 2.1, "radius_m": 0.12}   # the square at pixel (300, 150)
MOVED = {"x": 4.5, "y": 2.1, "radius_m": 0.12}    # pixel (450, 150)


def _frame(*robots):
    image = np.full((360, 640, 3), 120, np.uint8)
    image[:, 100:104] = 230
    image[200:204, :] = 230
    for cx in robots:
        image[141:159, cx - 9:cx + 9] = 30
    return image


def _learn(detector, regions, robots=(300,), start=0.0):
    detector.set_occupied(regions)
    statuses = [detector.detect(Frame(_frame(*robots), start + index / 3), CAL).status for index in range(31)]
    assert statuses == ["LEARNING"] * 31
    return start + 31 / 3


def _live(result):
    return [d for d in result.detections if d.score > BAKED_SCORE_MAX]


def test_a_parked_robot_in_a_fleet_region_is_not_learned_and_stays_detected():
    detector = BackgroundBlobDetector()
    at = _learn(detector, [PARKED])
    found = _live(detector.detect(Frame(_frame(300), at), CAL))
    assert len(found) == 1 and abs(found[0].x - 3.0) < 0.02 and abs(found[0].y - 2.1) < 0.02
    assert len(detector.unknown_floor) == 1
    x, y, radius = detector.unknown_floor[0]
    assert abs(x - 3.0) < 0.03 and abs(y - 2.1) < 0.03 and 0.1 < radius < 0.25


def test_without_a_region_the_parked_robot_is_learned_as_before():
    detector = BackgroundBlobDetector()
    at = _learn(detector, [])
    assert _live(detector.detect(Frame(_frame(300), at), CAL)) == []
    assert detector.unknown_floor == ()


def test_unknown_floor_is_filled_once_the_robot_left_and_no_ghost_stays():
    detector = BackgroundBlobDetector()
    at = _learn(detector, [PARKED])
    detector.set_occupied([MOVED])
    for index in range(FILL_CONFIRM_FRAMES):
        result = detector.detect(Frame(_frame(450), at + index / 3), CAL)
        assert [round(d.x, 1) for d in _live(result)] == [4.5]   # the old spot shows no ghost
    assert detector.unknown_floor == ()
    # Filled from the live floor: the spot learns floor, a robot coming back is foreground.
    result = detector.detect(Frame(_frame(300), at + 2.0), CAL)
    assert [round(d.x, 1) for d in _live(result)] == [3.0]


def test_a_region_still_occupied_or_a_dark_pixel_is_never_filled():
    detector = BackgroundBlobDetector()
    at = _learn(detector, [PARKED])
    for index in range(6):   # Fleet still names the spot
        detector.detect(Frame(_frame(300), at + index), CAL)
    assert len(detector.unknown_floor) == 1
    detector.set_occupied([])   # Fleet lost the robot, but it is still there (dark)
    for index in range(6):
        result = detector.detect(Frame(_frame(300), at + 6 + index), CAL)
    assert len(detector.unknown_floor) == 1 and len(_live(result)) == 1


def test_a_robot_moving_during_the_learn_is_left_out_along_its_whole_path():
    detector = BackgroundBlobDetector()
    for index in range(31):
        cx = 300 + 5 * index
        detector.set_occupied([{"x": cx / 100, "y": 2.1, "radius_m": 0.12}])
        detector.detect(Frame(_frame(cx), index / 3), CAL)
    for cx in (300, 400, 450):
        detector.set_occupied([{"x": cx / 100, "y": 2.1, "radius_m": 0.12}])
        assert len(_live(detector.detect(Frame(_frame(cx), 11.0 + cx / 100), CAL))) == 1


def test_a_relearn_reuses_the_previous_background_under_the_robot():
    detector = BackgroundBlobDetector()
    at = _learn(detector, [], robots=())           # empty track first
    detector.relearn()
    at = _learn(detector, [PARKED], start=at)       # then a relearn with the robot parked
    assert detector.unknown_floor == ()             # the floor under it was known
    assert len(_live(detector.detect(Frame(_frame(300), at), CAL))) == 1


def test_the_kept_background_carries_its_unknown_floor_across_a_restart(tmp_path):
    store = BackgroundStore(tmp_path / "ceiling_north.npz")
    first = BackgroundBlobDetector(store=store)
    first.relearn()
    _learn(first, [PARKED])
    restarted = BackgroundBlobDetector(store=store)
    restarted.set_occupied([PARKED])
    result = restarted.detect(Frame(_frame(300), 100.0), CAL)
    assert len(_live(result)) == 1
    assert len(restarted.unknown_floor) == 1


def test_malformed_regions_are_dropped():
    assert parse_regions([PARKED, {"x": True, "y": 1, "radius_m": 0.1}, {"x": 1, "y": 1, "radius_m": 0},
                          {"x": float("nan"), "y": 1, "radius_m": 0.1}, "x", None]) == ((3.0, 2.1, 0.12),)
    assert parse_regions(None) == ()
