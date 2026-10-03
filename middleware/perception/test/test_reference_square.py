"""D-395 rev. 1 §6: the HSV reference-square detector on synthetic floor images."""
import math

import numpy as np
import perception_data
import pytest

from control.sensing.perception.camera_ground import GroundPlane, focal_from_hfov
from control.sensing.perception.reference_square import (
    HsvSquareDetector,
    SquareDetector,
    SquareObservation,
)

W, H = 320, 180
CAM_X = .034
#: Real Pinky camera is near-horizontal (pitch ~11.8 deg, height ~0.059 m, 2026-10-01 fit).
GROUND = GroundPlane(height_m=.059, pitch_rad=math.radians(11.8), focal_px=focal_from_hfov(W, 1.1519),
                     principal_x=W / 2, principal_y=H / 2, max_range_m=.8)
CARPET, WALL, WHITE = (100, 104, 108), (185, 185, 185), (235, 235, 235)
RED, BLUE = (40, 40, 200), (200, 70, 30)   # BGR


def floor_grid():
    """Base_link (forward, left) of every pixel's floor point; NaN above the horizon."""
    fwd, left = np.full((H, W), np.nan), np.full((H, W), np.nan)
    for r in range(H):
        d = GROUND.distance(r)
        if d is not None:
            fwd[r] = d + CAM_X
            left[r] = [-GROUND.lateral(c, r) for c in range(W)]
    return fwd, left


FWD, LEFT = floor_grid()


def render(squares=(), lines=(), ring=RED, core=BLUE):
    """Carpet floor, wall above the horizon, axis-aligned squares (centre, outer, core sizes)."""
    img = np.empty((H, W, 3), np.uint8)
    img[:] = CARPET
    img[np.isnan(FWD)] = WALL
    for (cx, cy), outer, inner in squares:
        dx, dy = np.abs(FWD - cx), np.abs(LEFT - cy)
        img[(dx <= outer[0] / 2) & (dy <= outer[1] / 2)] = ring
        img[(dx <= inner[0] / 2) & (dy <= inner[1] / 2)] = core
    for left in lines:
        img[np.abs(LEFT - left) <= .0125] = WHITE
    return img


SQUARE_B = ((.13, .14), (.08, .09))


def test_the_detector_satisfies_the_backend_contract():
    assert isinstance(HsvSquareDetector(CAM_X), SquareDetector)


@pytest.mark.parametrize("centre", [(.30, 0.), (.30, .06), (.45, -.08), (.60, .05)])
def test_a_square_ahead_gives_its_bearing_and_range(centre):
    found = HsvSquareDetector(CAM_X).detect(render([(centre, *SQUARE_B)]), GROUND)
    assert len(found) == 1
    obs = found[0]
    assert obs.bearing_rad == pytest.approx(math.atan2(centre[1], centre[0]), abs=math.radians(3))
    assert obs.range_m == pytest.approx(math.hypot(*centre), abs=.03)
    assert obs.confidence > .6


@pytest.mark.parametrize("image", [
    render(),                                                  # bare carpet
    render(lines=(.09, -.09)),                                 # white lane paint
    render([((.3, 0.), *SQUARE_B)], ring=CARPET),              # blue patch without a ring
    render([((.3, 0.), *SQUARE_B)], core=RED),                 # red patch without a core
])
def test_carpet_paint_and_half_squares_are_not_squares(image):
    assert HsvSquareDetector(CAM_X).detect(image, GROUND) == []


def test_no_ground_plane_means_no_observation():
    assert HsvSquareDetector(CAM_X).detect(render([((.3, 0.), *SQUARE_B)]), None) == []


def test_beyond_trusted_range_keeps_the_bearing_without_a_range():
    near = GroundPlane(height_m=.059, pitch_rad=math.radians(11.8), focal_px=GROUND.focal_px,
                       principal_x=W / 2, principal_y=H / 2, max_range_m=.2)
    found = HsvSquareDetector(CAM_X).detect(render([((.45, .05), *SQUARE_B)]), near)
    assert len(found) == 1 and found[0].range_m is None
    assert found[0].bearing_rad > 0
    assert isinstance(found[0], SquareObservation)


# --- D-395 rev. 11: horizon gate and one detection per square (NMS) ----------------------------

def _stripe(img, centre, width_px):
    """A 1-3 px bright stripe (glare, tape) cut through the blue core's middle column."""
    core = np.argwhere((np.abs(FWD - centre[0]) <= .045) & (np.abs(LEFT - centre[1]) <= .04))
    col = int(np.median(core[:, 1]))
    out = img.copy()
    band = slice(col - width_px + 1, col + width_px)
    blue = np.all(out[:, band] == BLUE, axis=-1)
    out[:, band][blue] = WHITE
    return out


@pytest.mark.parametrize("centre", [(.30, 0.), (.30, .06), (.45, -.08), (.60, .05)])
@pytest.mark.parametrize("width_px", [1, 2, 3])
def test_a_stripe_through_the_core_is_still_one_square(centre, width_px):
    """Audit 2026-10-02: a 1 px stripe split 4 of 4 squares into 2 detections at confidence 1.0."""
    found = HsvSquareDetector(CAM_X).detect(_stripe(render([(centre, *SQUARE_B)]), centre, width_px), GROUND)
    assert len(found) == 1
    assert found[0].range_m == pytest.approx(math.hypot(*centre), abs=.03)
    assert found[0].bearing_rad == pytest.approx(math.atan2(centre[1], centre[0]), abs=math.radians(6))


def test_a_ring_and_core_above_the_horizon_is_not_a_floor_square():
    """Blue wall tape behind a red cable (real frame 133221Z/000068): no floor point, no square."""
    img = render()
    top = int(GROUND.horizon_row / 2)
    img[top - 9:top + 9, 140:180] = RED
    img[top - 4:top + 4, 150:170] = BLUE
    assert HsvSquareDetector(CAM_X).detect(img, GROUND) == []


def _real_frame(index):
    import cv2
    path = perception_data.label_file(perception_data.SESSION_133221Z, 'frames', index)
    img = cv2.imread(str(path))
    h, w = img.shape[:2]
    ground = GroundPlane(height_m=.059, pitch_rad=math.radians(11.8), focal_px=focal_from_hfov(w, 1.1519),
                         principal_x=w / 2, principal_y=h / 2, max_range_m=.8)
    return img, ground


def test_real_frame_with_wall_tape_and_a_red_cable_keeps_only_the_floor_square():
    """133221Z/000068 before the fix: the real square (23.9 deg, 0.368 m) plus two unranged
    hits on blue wall tape behind a red cable (0.2 and -12.9 deg). Zero false detections now;
    the real floor square stays."""
    img, ground = _real_frame(68)
    found = HsvSquareDetector(CAM_X).detect(img, ground)
    assert len(found) == 1
    assert found[0].range_m == pytest.approx(.368, abs=.01)
    assert math.degrees(found[0].bearing_rad) == pytest.approx(23.9, abs=1.)


def test_real_frame_key_square_is_one_detection_at_its_range():
    img, ground = _real_frame(78)
    found = HsvSquareDetector(CAM_X).detect(img, ground)
    assert len(found) == 1
    assert found[0].range_m == pytest.approx(.385, abs=.01)
    assert math.degrees(found[0].bearing_rad) == pytest.approx(10.1, abs=1.)
