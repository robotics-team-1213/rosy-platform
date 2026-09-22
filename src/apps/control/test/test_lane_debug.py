"""Perception overlay renderer (spec §4.3): what the robot saw and chose."""

import numpy as np

from control.sensing.lane_boundaries import LaneBoundaryTracker
from control.sensing.lane_debug import PANEL_H, PANEL_W, next_publish_due, render_debug
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
    # Left is +y (LEFT positive, REP 103): forward-up in the panel puts it
    # on the panel's left, i.e. the smaller column index.
    green_cols, blue_cols = np.where(green)[1], np.where(blue)[1]
    assert green_cols.mean() < blue_cols.mean()


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
    with_obs_status = render_debug(frame, t, t.update(0.6, pose, frame, GROUND, **KW),
                                   mode="centre", pose=pose)[PANEL_H:, :PANEL_W]
    no_obs_status = img[PANEL_H:, :PANEL_W]
    # "output NONE (CORE stops)" is a whole extra line the confidence/error
    # lines never print, so the two status panels must not render identically.
    assert not np.array_equal(with_obs_status, no_obs_status)


def test_malformed_graph_does_not_raise():
    frame, t, obs, pose = _frame_and_tracker()
    bad_graphs = [
        "not-even-a-dict",
        123,
        None,
        {"segments": "not-a-dict"},
        {"segments": {"broken": {}}},                    # missing "points"
        {"segments": {"broken": {"points": "xy"}}},       # wrong point shape
        {"parking": "not-a-dict"},
        {"parking": {"points": "oops"}},
        {"parking": {"points": [(1, 2, 3)]}},             # wrong tuple arity
    ]
    for graph in bad_graphs:
        img = render_debug(frame, t, obs, mode="centre", pose=pose, graph=graph)
        assert img.shape == (2 * PANEL_H, 2 * PANEL_W, 3)


def test_rate_limiter_survives_float_jitter_at_a_matching_rate():
    """Camera 5 Hz, max_hz 5.0: 1.2 - 1.0 == 0.19999999999999996 < 0.2 in
    plain float subtraction, which must not read as "not yet due"."""
    assert next_publish_due(1.0, 1.2, 5.0) is True


def test_rate_limiter_still_throttles_a_genuinely_faster_frame():
    assert next_publish_due(1.0, 1.05, 5.0) is False


def test_rate_limiter_always_publishes_the_first_frame():
    assert next_publish_due(None, 0.0, 5.0) is True


def test_rate_limiter_treats_a_backwards_clock_as_due():
    assert next_publish_due(1.0, 0.5, 5.0) is True
