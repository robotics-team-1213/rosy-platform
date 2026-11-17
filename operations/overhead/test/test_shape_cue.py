"""Panel 2026-11-18: ceiling-camera Pinky shape cue on real frames (shape_cue.py, background_blob.py).

data/ceiling_pinky: three ceiling_north frames (1280 x 720, 2026-11-18, static scene). Truth is the
body centre in frame pixels: R1 and R2 touch in the charging bays (R2 has its cable in), R3 carries
an orange box at S5 (centre from wheels, LiDAR and deck screws, cargo left out). The track mask is
a plain image rectangle around the mat, as a simple calibration's track_bounds_m gives.
"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from rosy_vision.track import shape_cue
from rosy_vision.track.background_blob import BackgroundBlobDetector
from rosy_vision.track.background_blob_helpers import _work_image
from rosy_vision.track.model import Calibration, Frame

DATA = Path(__file__).resolve().parent / "data" / "ceiling_pinky"
FRAMES = ("f0.jpg", "f3.jpg", "f6.jpg")
TRUTH = np.array([(603.0, 201.0), (644.0, 259.0), (1027.0, 441.0)])  # R1, R2 (touching), R3
TOLERANCE_PX = 12.0
TRACK_PX = (330, 130, 1280, 680)  # x0, y0, x1, y1 in frame pixels
M_PER_PX = 0.002
CAL = Calibration(source_id="ceiling_north", map_id="map_v2_fleet", revision="paint-shape-cue",
                  image_to_map=(M_PER_PX, 0.0, 0.0, 0.0, M_PER_PX, 0.0, 0.0, 0.0, 1.0),
                  image_size=(1280, 720),
                  track_bounds_m=tuple(v * M_PER_PX for v in TRACK_PX))


def _frame(name):
    image = cv2.imread(str(DATA / name))
    assert image is not None and image.shape == (720, 1280, 3)
    return image


def _track(shape):
    mask = np.zeros(shape[:2], np.uint8)
    x0, y0, x1, y1 = TRACK_PX
    mask[y0:y1, x0:x1] = 255
    return mask


def _find(image, mask):
    """shape_cue on the background_blob work copy; positions back in frame pixels (pixel centres)."""
    work = _work_image(image)
    scale = image.shape[1] / work.shape[1]
    small = cv2.resize(mask, (work.shape[1], work.shape[0]), interpolation=cv2.INTER_NEAREST)
    found = shape_cue.find_robots(work, small)
    return [((r.u + 0.5) * scale - 0.5, (r.v + 0.5) * scale - 0.5, r) for r in found]


def _match(found, truth):
    """Index of the detection within tolerance of each truth point, or None."""
    out = []
    for point in truth:
        dist = [np.hypot(x - point[0], y - point[1]) for x, y, _ in found]
        out.append(int(np.argmin(dist)) if dist and min(dist) <= TOLERANCE_PX else None)
    return out


@pytest.mark.parametrize("name", FRAMES)
def test_each_robot_is_found_once_near_its_body_centre(name):
    image = _frame(name)
    found = _find(image, _track(image.shape))
    matched = _match(found, TRUTH)
    assert None not in matched and len(set(matched)) == 3
    assert len(found) == 3  # no false detection on the track


@pytest.mark.parametrize("name", FRAMES)
def test_touching_robots_get_no_heading_and_the_lone_one_does(name):
    image = _frame(name)
    found = _find(image, _track(image.shape))
    r1, r2, r3 = (found[k][2] for k in _match(found, TRUTH))
    assert r1.heading_mod180 is None and r2.heading_mod180 is None
    assert r3.heading_mod180 is not None
    assert min(r3.heading_mod180, 180.0 - r3.heading_mod180) < 10.0  # axle vertical in the image


@pytest.mark.parametrize("code", [cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180])
def test_rotated_frames_still_give_three_robots(code):
    image = _frame(FRAMES[0])
    height, width = image.shape[:2]
    x, y = TRUTH[:, 0], TRUTH[:, 1]
    truth = np.c_[height - 1 - y, x] if code == cv2.ROTATE_90_CLOCKWISE else np.c_[width - 1 - x, height - 1 - y]
    rotated = cv2.rotate(image, code)
    found = _find(rotated, cv2.rotate(_track(image.shape), code))
    matched = _match(found, truth)
    assert None not in matched and len(found) == 3


def test_thresholds_follow_the_exposure():
    image = (_frame(FRAMES[0]).astype(np.float32) * 0.7).astype(np.uint8)
    found = _find(image, _track(image.shape))
    assert None not in _match(found, TRUTH) and len(found) == 3


def test_an_empty_grey_track_has_no_robots():
    image = np.full((360, 640, 3), 120, np.uint8)
    assert shape_cue.find_robots(image, np.full((360, 640), 255, np.uint8)) == []


def test_robots_parked_while_learning_are_reported_while_and_after_learning():
    frames = [_frame(name) for name in FRAMES]
    detector = BackgroundBlobDetector()
    truth_m = TRUTH * M_PER_PX
    results = [detector.detect(Frame(frames[index % 3], index / 3), CAL) for index in range(31)]
    results += [detector.detect(Frame(frames[index % 3], 12.0 + index / 3), CAL) for index in range(6)]
    assert detector._ready  # MOG2 learned with the robots in view
    for result in results:
        assert result.status == "OK" and len(result.detections) == 3
        for x, y in truth_m:
            assert min(np.hypot(d.x - x, d.y - y) for d in result.detections) <= TOLERANCE_PX * M_PER_PX
