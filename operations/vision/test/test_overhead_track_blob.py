"""D-457 3: background_blob on synthetic frames (floor with lane paint + a dark robot square)."""

import math

import numpy as np
import pytest

from rosy_vision.track.background_blob import PROCESSOR_REVISION, BackgroundBlobDetector
from rosy_vision.track.model import ROBOT_TOP_HEIGHT_M, ROTATION_RADIUS_M, Calibration, Frame

CAL = Calibration(source_id="ceiling_north", map_id="map_v2_fleet", revision="paint-3f9a1c2b7d40",
                  image_to_map=(0.01, 0.0, 0.0, 0.0, -0.01, 3.6, 0.0, 0.0, 1.0),
                  image_size=(640, 360), track_bounds_m=(0.0, 0.0, 6.4, 3.6))


def _floor(width=640, height=360):
    image = np.full((height, width, 3), 120, np.uint8)
    image[:, 100:104] = 230
    image[200:204, :] = 230
    return image


def _with_square(side, cx=300, cy=150, image=None):
    image = _floor() if image is None else image
    half = side // 2
    image[cy - half: cy - half + side, cx - half: cx - half + side] = 30
    return image


def _learned(detector=None, calibration=CAL, floor=_floor):
    detector = detector or BackgroundBlobDetector()
    statuses = [detector.detect(Frame(floor(), index / 3), calibration).status for index in range(31)]
    assert statuses == ["LEARNING"] * 31
    return detector


def _calibration(image_to_map, bounds=(0.0, 0.0, 6.4, 3.6), size=(640, 360), hfov=None):
    return Calibration(source_id="ceiling_north", map_id="map_v2_fleet", revision="paint-3f9a1c2b7d40",
                       image_to_map=tuple(float(v) for v in np.asarray(image_to_map).ravel()),
                       image_size=size, track_bounds_m=bounds, hfov_deg=hfov)


def test_learning_needs_thirty_frames_and_ten_seconds():
    detector = BackgroundBlobDetector()
    statuses = [detector.detect(Frame(_floor(), index / 3), CAL).status for index in range(30)]
    assert statuses == ["LEARNING"] * 30
    assert detector.detect(Frame(_floor(), 10.0), CAL).status == "LEARNING"
    result = detector.detect(Frame(_floor(), 10.34), CAL)
    assert (result.status, result.detections) == ("OK", ())
    assert detector.processor_revision == PROCESSOR_REVISION == "background-blob/1"


def test_robot_sized_blob_is_found_at_its_floor_position():
    detector = _learned()
    result = detector.detect(Frame(_with_square(18), 11.0), CAL)
    assert result.status == "OK" and len(result.detections) == 1
    found = result.detections[0]
    assert found.x == pytest.approx(2.995, abs=0.006)
    assert found.y == pytest.approx(2.105, abs=0.006)
    assert found.footprint_m == pytest.approx(0.2031, abs=0.003)
    assert 0.0 < found.score <= 1.0


@pytest.mark.parametrize("side", [8, 30])
def test_blobs_outside_the_footprint_window_are_dropped(side):
    detector = _learned()
    assert detector.detect(Frame(_with_square(side), 11.0), CAL).detections == ()


def test_a_parked_robot_stays_foreground():
    detector = _learned()
    for index in range(40):
        result = detector.detect(Frame(_with_square(18), 11.0 + index / 3), CAL)
    assert len(result.detections) == 1


def test_more_than_thirty_percent_foreground_is_a_scene_change_and_relearns():
    detector = _learned()
    bright = np.full((360, 640, 3), 200, np.uint8)
    assert detector.detect(Frame(bright, 11.0), CAL).status == "SCENE_CHANGED"
    assert detector.detect(Frame(_floor(), 11.34), CAL).status == "LEARNING"


def test_reset_and_resolution_change_start_learning_again():
    detector = _learned()
    detector.reset()
    assert detector.detect(Frame(_floor(), 11.0), CAL).status == "LEARNING"
    other = _learned()
    assert other.detect(Frame(_floor(320, 180), 11.0), CAL).status == "LEARNING"


def test_blobs_outside_the_track_rectangle_are_ignored():
    narrow = Calibration(source_id="ceiling_north", map_id="map_v2_fleet", revision="paint-3f9a1c2b7d40",
                         image_to_map=CAL.image_to_map, image_size=(640, 360),
                         track_bounds_m=(0.0, 0.0, 2.0, 3.6))
    detector = _learned(calibration=narrow)
    result = detector.detect(Frame(_with_square(18), 11.0), narrow)
    assert (result.status, result.detections) == ("OK", ())


def test_large_frames_are_downscaled_before_detection():
    big = Calibration(source_id="ceiling_north", map_id="map_v2_fleet", revision="paint-3f9a1c2b7d40",
                      image_to_map=(0.005, 0.0, 0.0, 0.0, -0.005, 3.6, 0.0, 0.0, 1.0),
                      image_size=(1280, 720), track_bounds_m=(0.0, 0.0, 6.4, 3.6))

    def big_floor():
        image = np.full((720, 1280, 3), 120, np.uint8)
        image[:, 200:208] = 230
        return image

    detector = _learned(calibration=big, floor=big_floor)
    frame = big_floor()
    frame[282:318, 582:618] = 30
    result = detector.detect(Frame(frame, 11.0), big)
    assert len(result.detections) == 1
    found = result.detections[0]
    assert found.x == pytest.approx(2.9975, abs=0.01)
    assert found.y == pytest.approx(3.6 - 0.005 * 299.5, abs=0.01)
    assert found.footprint_m == pytest.approx(0.2031, abs=0.01)


def test_downscaled_position_uses_pixel_centres():
    big = _calibration((0.005, 0.0, 0.0, 0.0, -0.005, 3.6, 0.0, 0.0, 1.0), size=(1280, 720))
    detector = _learned(calibration=big, floor=lambda: np.full((720, 1280, 3), 120, np.uint8))
    frame = np.full((720, 1280, 3), 120, np.uint8)
    frame[282:318, 582:618] = 30  # centre pixel (599.5, 299.5) in the full frame
    found = detector.detect(Frame(frame, 11.0), big).detections[0]
    assert (found.x, found.y) == pytest.approx((0.005 * 599.5, 3.6 - 0.005 * 299.5), abs=1e-3)


def test_a_frame_smaller_than_the_calibration_is_mapped_through_it():
    detector = _learned(floor=lambda: _floor(320, 180))
    frame = _floor(320, 180)
    frame[70:79, 145:154] = 30  # 9 px square centred at (149, 74) = (298.5, 148.5) at 640x360
    result = detector.detect(Frame(frame, 11.0), CAL)
    assert len(result.detections) == 1
    found = result.detections[0]
    assert (found.x, found.y) == pytest.approx((2.985, 3.6 - 1.485), abs=1e-3)
    assert found.footprint_m == pytest.approx(0.2031, abs=0.003)


def test_a_frame_with_another_aspect_ratio_needs_calibration_from_the_first_frame():
    detector = BackgroundBlobDetector()
    result = detector.detect(Frame(_floor(640, 480), 0.0), CAL)
    assert (result.status, result.detections) == ("CALIBRATION_REQUIRED", ())
    _learned(detector)  # the refused frame did not count toward learning


def test_a_track_wholly_out_of_view_needs_calibration():
    away = _calibration(CAL.image_to_map, bounds=(10.0, 10.0, 12.0, 12.0))
    assert BackgroundBlobDetector().detect(Frame(_floor(), 0.0), away).status == "CALIBRATION_REQUIRED"
    behind = _calibration(HORIZON, bounds=(0.0, -50.0, 1.0, -40.0))
    assert BackgroundBlobDetector().detect(Frame(_floor(), 0.0), behind).status == "CALIBRATION_REQUIRED"


def test_a_clock_that_steps_back_while_learning_restarts_the_learning_time():
    detector = BackgroundBlobDetector()
    for index in range(30):
        assert detector.detect(Frame(_floor(), 1000.0 + index / 3), CAL).status == "LEARNING"
    assert detector.detect(Frame(_floor(), 5.0), CAL).status == "LEARNING"
    assert detector.detect(Frame(_floor(), 15.0), CAL).status == "LEARNING"
    assert detector.detect(Frame(_floor(), 15.34), CAL).status == "OK"


def test_a_floor_coloured_stripe_does_not_split_a_robot():
    detector = _learned()
    frame = _with_square(18)
    frame[149:151, 291:309] = 120  # e.g. a gap between the deck and the LiDAR
    result = detector.detect(Frame(frame, 11.0), CAL)
    assert len(result.detections) == 1
    assert result.detections[0].footprint_m == pytest.approx(0.2031, abs=0.003)


@pytest.mark.parametrize(("value", "found"), [(55, 1), (90, 0)])
def test_shadow_threshold_both_sides(value, found):
    detector = _learned()
    frame = _floor()
    frame[141:159, 291:309] = value  # 55/120 is darker than a shadow; 90/120 is a shadow
    assert len(detector.detect(Frame(frame, 11.0), CAL).detections) == found


def _square_px_calibration(side_px, diameter_m):
    scale = math.sqrt(math.pi * (diameter_m / 2) ** 2 / side_px ** 2)
    return _calibration((scale, 0.0, 0.0, 0.0, -scale, 3.6, 0.0, 0.0, 1.0))


def test_score_is_one_at_nominal_and_zero_at_both_window_edges():
    nominal = 2.0 * ROTATION_RADIUS_M
    at_nominal = _square_px_calibration(18, nominal)
    assert _learned(calibration=at_nominal).detect(
        Frame(_with_square(18), 11.0), at_nominal).detections[0].score == pytest.approx(1.0, abs=1e-6)
    low = 2.0 * math.sqrt(14 * 14 * 1e-4 / math.pi)  # 14 px square at 0.01 m/px, below nominal
    edge_low = BackgroundBlobDetector(footprint_m=(low - 1e-9, 0.26))
    assert _learned(edge_low).detect(Frame(_with_square(14), 11.0), CAL).detections[0].score < 1e-5
    high = 2.0 * math.sqrt(18 * 18 * 1e-4 / math.pi)  # 0.2031 m, above nominal
    edge_high = BackgroundBlobDetector(footprint_m=(0.12, high + 1e-9))
    assert _learned(edge_high).detect(Frame(_with_square(18), 11.0), CAL).detections[0].score < 1e-5


def test_at_most_sixteen_detections_keep_the_highest_scores():
    detector = _learned()
    frame = _floor()
    spots = [(130 + 30 * k, row) for row in (50, 100) for k in range(9)][:17]
    for cx, cy in spots[:16]:
        _with_square(17, cx, cy, frame)
    _with_square(12, *spots[16], frame)  # 0.135 m: in the window, lowest score
    result = detector.detect(Frame(frame, 11.0), CAL)
    assert len(result.detections) == 16
    assert all(found.footprint_m > 0.18 for found in result.detections)


def test_a_new_calibration_mid_stream_rebuilds_the_track_mask():
    detector = _learned()
    narrow = _calibration(CAL.image_to_map, bounds=(0.0, 0.0, 2.0, 3.6))
    assert len(detector.detect(Frame(_with_square(18), 11.0), CAL).detections) == 1
    assert detector.detect(Frame(_with_square(18), 11.34), narrow).detections == ()
    assert len(detector.detect(Frame(_with_square(18), 11.67), CAL).detections) == 1


# The floor homography below has its horizon at image row v = 100; rows below it are behind
# the camera and map to (nan, nan). Map y < -1 is the mirror image of those rows.
HORIZON = ((0.01, 0.0, 0.0), (0.0, 0.01, 0.0), (0.0, -0.01, 1.0))


@pytest.mark.parametrize(("bounds", "found"), [((0.0, -2.0, 1.0, 0.3), 0), ((0.0, -2.0, 10.0, 3.0), 1)])
def test_track_mask_follows_the_horizon(bounds, found, recwarn):
    calibration = _calibration(HORIZON, bounds=bounds)
    detector = _learned(calibration=calibration, floor=lambda: np.full((360, 640, 3), 120, np.uint8))
    frame = np.full((360, 640, 3), 120, np.uint8)
    frame[47:54, 297:304] = 30  # maps near (6.0, 1.0): in front of the horizon
    result = detector.detect(Frame(frame, 11.0), calibration)
    assert result.status == "OK" and len(result.detections) == found
    assert not [w for w in recwarn if issubclass(w.category, RuntimeWarning)]


def test_a_blob_beyond_the_horizon_is_dropped(recwarn):
    calibration = _calibration(HORIZON, bounds=(-100.0, -100.0, 100.0, 100.0))
    detector = _learned(calibration=calibration, floor=lambda: np.full((360, 640, 3), 120, np.uint8))
    frame = np.full((360, 640, 3), 120, np.uint8)
    frame[240:260, 290:310] = 30
    result = detector.detect(Frame(frame, 11.0), calibration)
    assert (result.status, result.detections) == ("OK", ())
    assert not [w for w in recwarn if issubclass(w.category, RuntimeWarning)]


def test_known_lens_corrects_position_and_size_for_the_robot_height():
    width, height, hfov, camera = 640, 360, 60.0, (3.2, 1.8, 2.0)
    focal = (width / 2) / math.tan(math.radians(hfov) / 2)
    k = np.array([[focal, 0.0, width / 2], [0.0, focal, height / 2], [0.0, 0.0, 1.0]])
    down = np.diag([1.0, -1.0, -1.0])
    map_to_image = k @ np.column_stack([down[:, 0], down[:, 1], -down @ np.asarray(camera)])
    image_to_map = np.linalg.inv(map_to_image)
    calibration = _calibration(image_to_map, hfov=hfov)
    plain = _calibration(image_to_map)
    frame = np.full((height, width, 3), 120, np.uint8)
    frame[75:125, 475:525] = 30  # 50 px square centred at (499.5, 99.5)
    floor = lambda: np.full((height, width, 3), 120, np.uint8)  # noqa: E731

    seen = _learned(calibration=plain, floor=floor).detect(Frame(frame, 11.0), plain).detections[0]
    corrected = _learned(calibration=calibration, floor=floor).detect(Frame(frame, 11.0), calibration).detections[0]

    keep = (camera[2] - ROBOT_TOP_HEIGHT_M) / camera[2]
    expected = (camera[0] + (seen.x - camera[0]) * keep, camera[1] + (seen.y - camera[1]) * keep)
    assert (corrected.x, corrected.y) == pytest.approx(expected, abs=1e-6)
    assert corrected.footprint_m == pytest.approx(seen.footprint_m * keep, rel=1e-6)
    assert math.hypot(corrected.x - seen.x, corrected.y - seen.y) > 0.03


@pytest.mark.parametrize("kwargs", [
    {"footprint_m": (0.3, 0.2)}, {"footprint_m": (0.0, 0.2)}, {"learning_frames": 0},
    {"learning_min_s": -1.0}, {"scene_change_fraction": 0.0}, {"robot_height_m": -0.1},
])
def test_bad_settings_are_refused(kwargs):
    with pytest.raises(ValueError):
        BackgroundBlobDetector(**kwargs)
