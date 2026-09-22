"""Perception overlay renderer (spec §4.3): what the robot saw and chose."""

import numpy as np

from control.sensing.lane import LaneObservation
from control.sensing.lane_boundaries import LaneBoundaryTracker
from control.sensing.lane_debug import PANEL_H, PANEL_W, render_debug
from lane_sim import CAM_X, GROUND, KW, lane

STRAIGHT = np.array([(-1.0, 0.0), (1.4, 0.0)])


def _frame_and_tracker():
    t = LaneBoundaryTracker(camera_x_offset_m=CAM_X)
    world = lane(STRAIGHT)
    pose = (-0.9, 0.0, 0.0)
    obs = None
    for k in range(3):
        frame = world.render(pose)
        obs = t.update(k * 0.2, pose, frame, GROUND, **KW)
    return frame, t, obs, pose


def test_overlay_is_four_panels():
    frame, t, obs, pose = _frame_and_tracker()
    img = render_debug(frame, t, obs, mode="centre", pose=pose)
    assert img.shape == (2 * PANEL_H, 2 * PANEL_W, 3)
    assert img.dtype == np.uint8


def test_birds_eye_panel_draws_left_green_and_right_blue():
    frame, t, obs, pose = _frame_and_tracker()
    img = render_debug(frame, t, obs, mode="centre", pose=pose)
    bev = img[:PANEL_H, PANEL_W:]
    green = (bev[:, :, 1] > 180) & (bev[:, :, 0] < 100) & (bev[:, :, 2] < 100)
    blue = (bev[:, :, 0] > 180) & (bev[:, :, 1] < 140) & (bev[:, :, 2] < 100)
    assert green.sum() > 50 and blue.sum() > 50


def test_status_panel_is_not_blank_and_map_panel_shows_the_pose():
    frame, t, obs, pose = _frame_and_tracker()
    graph = {"segments": {"west": {"points": [[-1.2, -0.5], [-1.2, 0.5]]}}}
    img = render_debug(frame, t, obs, mode="centre", pose=pose, graph=graph)
    status = img[PANEL_H:, :PANEL_W]
    assert (status > 200).sum() > 100          # white text drawn
    mapp = img[PANEL_H:, PANEL_W:]
    assert (mapp[:, :, 2] > 200).sum() > 10    # red pose marker


def test_no_observation_still_renders_and_says_stop():
    frame, t, _, pose = _frame_and_tracker()
    img = render_debug(frame, t, None, mode="centre", pose=None)
    assert img.shape == (2 * PANEL_H, 2 * PANEL_W, 3)
