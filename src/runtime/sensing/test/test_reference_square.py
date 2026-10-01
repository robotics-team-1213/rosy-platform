"""D-395 rev. 1 §6: the HSV reference-square detector on synthetic floor images."""
import math

import numpy as np
import pytest

from control.sensing.perception.camera_ground import GroundPlane, focal_from_hfov
from control.sensing.perception.reference_square import (
    HsvSquareDetector, SquareDetector, SquareObservation)

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
