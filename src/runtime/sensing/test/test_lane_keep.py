"""D-353 §2: 'keep' lane keeper on synthetic floors rendered through the NOMINAL ground."""
from pathlib import Path

import numpy as np
import pytest
import yaml

from control.sensing.perception.camera_ground import nominal_ground_plane
from control.sensing.perception.lane_keep import LaneKeeper

PKG = Path(__file__).resolve().parents[1]
PROFILE = yaml.safe_load((PKG / "config" / "camera_nominal_pinky_pro.yaml").read_text(encoding="utf-8"))
GROUND = nominal_ground_plane(source="NOMINAL", allowed=True, width_px=320, height_px=240,
                              profile=PROFILE)
X_OFFSET = float(PROFILE["x_offset_m"])
HALF = 0.0925
TAPE_HALF = 0.015


def _floor_xy():
    """base_link (x, y) of every pixel's floor point; NaN at/above the horizon."""
    rows, cols = np.mgrid[0:240, 0:320].astype(float)
    angle = GROUND.pitch_rad + np.arctan((rows - GROUND.principal_y) / GROUND.focal_px)
    with np.errstate(divide="ignore", invalid="ignore"):
        forward = np.where(angle > 0, GROUND.height_m / np.tan(angle), np.nan)
        denominator = (GROUND.focal_px * np.sin(GROUND.pitch_rad)
                       + (rows - GROUND.principal_y) * np.cos(GROUND.pitch_rad))
        right = GROUND.height_m * (cols - GROUND.principal_x) / denominator
    return forward + X_OFFSET, np.where(np.isfinite(forward), -right, np.nan)


X, Y = _floor_xy()


def _render(lines=(), transverse_x=None, wall_y=None):
    """Grey textured carpet, white tape lines y = y0 + slope * x, optional stop
    line across at transverse_x and a white wall standing at y = wall_y (right)."""
    rng = np.random.default_rng(7)
    grey = 100 + rng.normal(0, 8, X.shape)
    white = np.zeros(X.shape, bool)
    floor = np.isfinite(X)
    for y0, slope in lines:
        white |= floor & (np.abs(Y - (y0 + slope * X)) <= TAPE_HALF)
    if transverse_x is not None:
        white |= floor & (np.abs(X - transverse_x) <= 0.02)
    image = np.where(white, 195.0, grey)
    image[~floor] = 60.0  # background beyond the floor
    if wall_y is not None:
        wall = (floor & (Y < wall_y)) | (~floor & (np.arange(320)[None, :] > 200))
        image[wall] = 225.0
    image = np.clip(image, 0, 255).astype(np.uint8)
    return np.dstack([image] * 3)


def _keep(image, **kw):
    keeper = LaneKeeper(camera_x_offset_m=X_OFFSET, smoothing=0.0)
    return keeper.update(image, GROUND, lane_half_width_m=HALF, **kw), keeper.last


def test_centred_lane_reads_near_zero_with_both_boundaries():
    obs, last = _keep(_render([(HALF, 0.0), (-HALF, 0.0)]))
    assert obs is not None and abs(obs.error) < 0.1
    assert last["strategy"] == "both" and obs.confidence >= 0.8
    sides = sorted(b["side"] for b in last["boundaries"])
    assert sides == ["left", "right"]
    assert last["target_px"] is not None


@pytest.mark.parametrize("shift, sign", [(0.04, -1), (-0.04, +1)])
def test_off_centre_steers_back_with_core_sign(shift, sign):
    # shift > 0: the lane lies to the robot's left (robot right of centre),
    # so CORE must turn left: angular = -gain * error > 0 needs error < 0.
    obs, last = _keep(_render([(HALF + shift, 0.0), (-HALF + shift, 0.0)]))
    assert last["strategy"] == "both"
    assert obs.error * sign > 0.02
    assert last["target_m"][1] * sign < -0.025  # lane centre on the other side of base_link


def test_one_line_targets_inside_the_lane_not_the_line():
    obs, last = _keep(_render([(HALF, 0.0)]))
    assert last["strategy"] == "left_only"
    target_y = last["target_m"][1]
    assert abs(target_y) < 0.03 and abs(target_y - HALF) > 0.06
    assert obs.confidence < 0.8 and abs(obs.error) < 0.05
    obs, last = _keep(_render([(-HALF, 0.0)]))
    assert last["strategy"] == "right_only" and abs(last["target_m"][1]) < 0.03


def test_one_line_under_the_robot_is_classified_by_ground_side():
    # A single line 3.5 cm left: still the LEFT boundary, target a half-width right of it.
    obs, last = _keep(_render([(0.035, 0.0)]))
    assert last["strategy"] == "left_only"
    assert last["target_m"][1] < -0.04 and obs.error > 0.02  # steer right, away from the line


def test_transverse_stop_line_is_ignored():
    obs, last = _keep(_render([(HALF, 0.0), (-HALF, 0.0)], transverse_x=0.25))
    assert last["strategy"] == "both" and abs(obs.error) < 0.1
    assert last["transverse"], "the stop line should be reported as transverse"
    obs, last = _keep(_render([], transverse_x=0.25))
    assert obs is None and last["strategy"] == "none"


def test_white_wall_is_not_a_boundary():
    obs, last = _keep(_render([(HALF, 0.0), (-HALF, 0.0)], wall_y=-0.16))
    assert obs is not None and last["strategy"] == "both" and abs(obs.error) < 0.15
    assert all(abs(b["y_at_side_x_m"]) < 0.13 for b in last["boundaries"])
    # Wall alone: nothing to keep.
    obs, last = _keep(_render([], wall_y=-0.16))
    assert obs is None


def test_nothing_or_no_ground_is_hold():
    assert _keep(_render([]))[0] is None
    keeper = LaneKeeper()
    assert keeper.update(_render([(HALF, 0.0)]), None) is None
    assert keeper.last["reason"] == "no_ground"


def test_smoothing_uses_previous_targets_only():
    keeper = LaneKeeper(camera_x_offset_m=X_OFFSET, smoothing=0.5)
    centred = keeper.update(_render([(HALF, 0.0), (-HALF, 0.0)]), GROUND, lane_half_width_m=HALF)
    shifted = keeper.update(_render([(HALF + 0.04, 0.0), (-HALF + 0.04, 0.0)]), GROUND,
                            lane_half_width_m=HALF)
    alone = _keep(_render([(HALF + 0.04, 0.0), (-HALF + 0.04, 0.0)]))[0]
    assert alone.error < shifted.error < centred.error + 0.01
    with pytest.raises(ValueError):
        LaneKeeper(smoothing=1.0)


def test_error_grows_with_offset():
    small = _keep(_render([(HALF + 0.02, 0.0), (-HALF + 0.02, 0.0)]))[0]
    large = _keep(_render([(HALF + 0.06, 0.0), (-HALF + 0.06, 0.0)]))[0]
    assert large.error < small.error < 0.0


def test_node_wires_keep_mode_on_the_labelled_ground():
    text = (PKG / "control" / "line_observer_node.py").read_text(encoding="utf-8")
    uses_ground = text.split("def _camera_mode_uses_ground", 1)[1].split("def ", 1)[0]
    assert "'keep'" in uses_ground
    assert "self._lane_keeper.update(" in text
    assert "frame, self._ground(frame.shape[1], frame.shape[0])" in text
