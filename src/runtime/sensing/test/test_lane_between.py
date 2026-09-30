"""'between' camera lane mode — image-space two-boundary lane keeper.

The real Pinky has no ground plane (camera_homography_enabled=false), so the
metric lane modes cannot run and 'line' steers onto a lone boundary line. The
keeper steers to the midpoint of the two inner edges and, with one boundary,
to a point a learned lane width inside it.
"""

from pathlib import Path

import numpy as np
import pytest

from control.sensing.perception.lane import (
    LaneBetweenKeeper,
    detect_lane_between,
    detect_lane_error,
    steer_correction,
)

W, H, LINE = 320, 240, 8


def _frame(*centres: int, wall_rows: int = 0) -> np.ndarray:
    """Dark carpet, bright vertical boundary lines at the given columns."""
    frame = np.full((H, W, 3), 40, dtype=np.uint8)
    for cx in centres:
        frame[:, max(0, cx - LINE // 2):max(0, cx + LINE // 2)] = 230
    if wall_rows:
        frame[:wall_rows, :] = 240
    return frame


def test_centred_lane_reads_zero_error():
    obs = detect_lane_between(_frame(64, 256))
    assert obs is not None
    assert abs(obs.error) < 0.02
    assert obs.confidence == pytest.approx(1.0)


def test_robot_drifted_right_steers_left_back_to_the_middle():
    # Robot right of the lane centre: both lines shift left in the image.
    obs = detect_lane_between(_frame(34, 226))
    assert obs is not None
    assert obs.error < -0.1
    assert steer_correction(obs.error) > 0.0   # CCW+, i.e. turn left


def test_only_left_line_targets_inside_the_lane_not_the_line():
    left = 100
    obs = detect_lane_between(_frame(left))
    assert obs is not None
    target = W / 2 + obs.error * W / 2
    assert target > left + LINE             # inside the lane, right of the line
    assert obs.error > 0.0                  # steer right, away from the line
    assert obs.confidence < 1.0             # one-sided is weaker evidence
    # Regression: the centroid mode sits on the line and steers left over it.
    legacy = detect_lane_error(_frame(left))
    assert legacy is not None and legacy.error < 0.0
    assert abs((W / 2 + legacy.error * W / 2) - left) < LINE


def test_only_right_line_targets_inside_the_lane():
    right = 220
    obs = detect_lane_between(_frame(right))
    assert obs is not None
    target = W / 2 + obs.error * W / 2
    assert target < right - LINE
    assert obs.error < 0.0
    legacy = detect_lane_error(_frame(right))
    assert legacy is not None and legacy.error > 0.0


def test_no_lines_is_not_visible():
    assert detect_lane_between(_frame()) is None


def test_white_wall_in_upper_image_is_ignored():
    obs = detect_lane_between(_frame(64, 256, wall_rows=100))
    assert obs is not None
    assert abs(obs.error) < 0.02


def test_one_sided_uses_lane_width_learned_when_both_were_seen():
    keeper = LaneBetweenKeeper()
    for _ in range(30):
        both = keeper.update(_frame(100, 220))          # 120 px apart
        assert both is not None and abs(both.error) < 0.02
    obs = keeper.update(_frame(100))
    assert obs is not None
    target = W / 2 + obs.error * W / 2
    # Inner edge 103 plus half the learned inner width (~112 px) = ~159.
    assert target == pytest.approx(160.0, abs=4.0)


def test_boundary_past_image_centre_keeps_its_side():
    keeper = LaneBetweenKeeper()
    assert keeper.update(_frame(64, 256)) is not None
    # Drift so the right line nears the centre over successive frames; the
    # reference follows the target so the right line stays "right".
    for shift in range(0, 130, 10):
        obs = keeper.update(_frame(64 - shift, 256 - shift))
        assert obs is not None and obs.error < 0.02
    # The right line now sits left of the image centre (136 < 160) and is
    # still read as the right boundary; a fresh keeper would call it left.
    assert obs.error < -0.5
    assert detect_lane_between(_frame(136)).error > 0.0


def test_invalid_arguments_rejected():
    with pytest.raises(ValueError):
        detect_lane_between(_frame(64, 256), roi_top_fraction=1.0)
    with pytest.raises(ValueError):
        LaneBetweenKeeper(default_lane_width_fraction=0.0)


def test_line_observer_wires_between_mode_without_changing_the_default():
    node = Path(__file__).resolve().parents[1] / 'control' / 'line_observer_node.py'
    source = node.read_text(encoding='utf-8')
    assert "self.declare_parameter('camera_lane_mode', 'line', _READ_ONLY)" in source
    assert "elif mode == 'between':" in source
    assert 'self._between_keeper.update(' in source
