"""Corner seed memory: a new corner side needs its closed-side boundary seen within CORNER_SEED_FRAMES.

The closed-side lane line shortens as an L-corner nears (its seen paint runs from the camera's near
edge to the corner), and a sparse paint source (learned paint every n-th frame) may first show the
corner line's open end after that line fell below a half-width. A seed taken only from the current
and the previous frame then never comes: v13c SIM run L 2026-10-10 held at the end of the west road
(camera_line_not_visible -> back-off -> camera_reselection_required) with the corner in view.
"""
from pathlib import Path

import numpy as np
import pytest

from control.sensing.perception.camera_ground import GroundPlane
from control.sensing.perception.lane_keep import CORNER_SEED_FRAMES, LaneKeeper
from test_lane_keep import GROUND, HALF, X_OFFSET, _render, _render_corner

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "v13c_corner_reacquire_20261010.npz"


def test_recorded_v13c_re_approach_acquires_the_left_corner():
    # Gazebo frames 63.0-65.0 s of run L (map_v2_fleet, west road end), re-approaching the corner
    # after a back-off: the v13c crop128 paint (model.onnx sha256 71edcb6d...) of each frame,
    # cleaned like the node. The right line shrinks below a half-width (64.125) and leaves the view
    # (64.25) before the corner line with its open left end is painted (64.375); the robot is then
    # held and sees the same frame. Before the seed memory every frame from 64.25 was no_boundary.
    data = np.load(FIXTURE)
    height_m, pitch_rad, focal_px, cx, cy, max_range_m, x_offset = data["ground"]
    ground = GroundPlane(height_m, pitch_rad, focal_px, cx, cy, max_range_m)
    masks = np.unpackbits(data["masks"], axis=-1)[..., :320]
    frame = np.zeros((240, 320, 3), np.uint8)
    keeper = LaneKeeper(camera_x_offset_m=float(x_offset), corner_turning=True)
    strategies = []
    for mask in masks:
        keeper.update(frame, ground, paint_mask=mask, lane_half_width_m=HALF)
        strategies.append(keeper.last["strategy"])
    stamps = [round(float(s), 3) for s in data["stamp"]]
    assert strategies[:stamps.index(64.25)] == ["right_only"] * stamps.index(64.25)
    assert strategies[stamps.index(64.375):] == ["corner_ahead"] * (len(stamps) - stamps.index(64.375))
    assert keeper._corner_side == "left"


@pytest.mark.parametrize("open_side, closed_y", [("left", -HALF), ("right", HALF)])
def test_closed_side_boundary_seeds_a_corner_seen_a_few_frames_later(open_side, closed_y):
    keeper = LaneKeeper(camera_x_offset_m=X_OFFSET, smoothing=0.0, corner_turning=True)
    keeper.update(_render([(closed_y, 0.0)]), GROUND, lane_half_width_m=HALF)
    for _ in range(3):  # paint gap: no line at all
        assert keeper.update(_render([]), GROUND, lane_half_width_m=HALF) is None
    assert keeper.update(_render_corner(0.26, open_side), GROUND, lane_half_width_m=HALF) is not None
    assert keeper.last["strategy"].startswith("corner_") and keeper._corner_side == open_side


def test_corner_seed_expires_and_never_comes_from_the_open_side():
    keeper = LaneKeeper(camera_x_offset_m=X_OFFSET, smoothing=0.0, corner_turning=True)
    keeper.update(_render([(-HALF, 0.0)]), GROUND, lane_half_width_m=HALF)
    for _ in range(CORNER_SEED_FRAMES):
        keeper.update(_render([]), GROUND, lane_half_width_m=HALF)
    assert keeper.update(_render_corner(0.26, "left"), GROUND, lane_half_width_m=HALF) is None
    keeper.reset()
    keeper.update(_render([(HALF, 0.0)]), GROUND, lane_half_width_m=HALF)  # open side only
    assert keeper.update(_render_corner(0.26, "left"), GROUND, lane_half_width_m=HALF) is None
    keeper.reset()  # a reset (camera gap, spin) forgets the seed
    keeper.update(_render([(-HALF, 0.0)]), GROUND, lane_half_width_m=HALF)
    keeper.reset()
    assert keeper.update(_render_corner(0.26, "left"), GROUND, lane_half_width_m=HALF) is None
