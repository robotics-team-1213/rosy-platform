"""NAV-007 lane following — classical CV line error plus loss tracking.

A floor lane is a bright line on a dark floor. This subject turns a BGR frame
into a lateral error; a tracker turns the error stream into TRACKING/LOST.
Loss beyond the grace period means stop (`nav.lane_lost`) — never a blind
search drive. YOLO is not involved by design (SRS NAV-007).
"""

import numpy as np
import pytest

from control.sensing.perception.lane import (
    LANE_MAX_LINEAR_M_S,
    LaneObservation,
    LaneTracker,
    detect_lane_error,
)


def _lane_frame(offset_px: int = 0, width: int = 320, height: int = 240,
                line_px: int = 8) -> np.ndarray:
    """Dark floor, one bright vertical lane."""
    frame = np.full((height, width, 3), 40, dtype=np.uint8)
    cx = width // 2 + offset_px
    frame[:, max(0, cx - line_px // 2):cx + line_px // 2] = 230
    return frame


def test_centred_lane_reads_zero_error():
    obs = detect_lane_error(_lane_frame())
    assert isinstance(obs, LaneObservation)
    assert obs.error == pytest.approx(0.0, abs=0.02)
    assert 0.0 < obs.confidence <= 1.0


def test_right_lane_reads_positive_error():
    """Lane right of centre means steer right: error > 0, bounded to [-1, 1]."""
    obs = detect_lane_error(_lane_frame(offset_px=60))
    assert obs is not None
    assert obs.error == pytest.approx(60.0 / 160.0, abs=0.05)
    assert -1.0 <= obs.error <= 1.0


def test_left_lane_reads_negative_error():
    obs = detect_lane_error(_lane_frame(offset_px=-60))
    assert obs is not None
    assert obs.error < 0.0


def test_blank_floor_is_no_lane_not_a_guess():
    frame = np.full((240, 320, 3), 40, dtype=np.uint8)
    assert detect_lane_error(frame) is None


def test_lane_speed_cap_is_a_crawl():
    assert LANE_MAX_LINEAR_M_S == pytest.approx(0.10)


def test_centred_lane_commands_no_turn():
    from control.sensing.perception.lane import steer_correction
    assert steer_correction(0.0) == pytest.approx(0.0)


def test_right_lane_commands_right_turn():
    """오차 + (차선 우측) → 우회전 = 음각속도 (ROS CCW+)."""
    from control.sensing.perception.lane import steer_correction
    assert steer_correction(0.5, max_angular=1.0) == pytest.approx(-0.5)


def test_steering_saturates_at_max_angular():
    from control.sensing.perception.lane import steer_correction
    assert steer_correction(1.0, gain=2.0, max_angular=0.4) == pytest.approx(-0.4)
    assert steer_correction(-1.0, gain=2.0, max_angular=0.4) == pytest.approx(0.4)


def test_bad_steering_gains_fail_closed():
    from control.sensing.perception.lane import steer_correction
    with pytest.raises(ValueError):
        steer_correction(0.5, gain=-1.0)
    with pytest.raises(ValueError):
        steer_correction(float("inf"))
    # 범위 밖 오차는 던지지 않고 클램프한다 — 센서 글리치가 던지면 주행 중 정지다.
    assert steer_correction(2.0, max_angular=1.0) == pytest.approx(-1.0)


class TestLaneTracker:
    def _tracker(self, now=None):
        clock = now if now is not None else [1000.0]
        return LaneTracker(clock=lambda: clock[0] if isinstance(clock, list) else clock), clock

    def test_observations_track(self):
        tracker, _ = self._tracker()
        tracker.update(detect_lane_error(_lane_frame()), at=1000.0)
        assert tracker.state == "TRACKING"
        assert not tracker.stop_demanded(at=1001.0)

    def test_brief_gap_does_not_stop(self):
        tracker, _ = self._tracker()
        tracker.update(detect_lane_error(_lane_frame()), at=1000.0)
        tracker.update(None, at=1001.0)
        assert tracker.state == "TRACKING"
        assert not tracker.stop_demanded(at=1002.0)

    def test_loss_beyond_grace_demands_stop(self):
        """SRS: 3 s 상실이면 정지 + `nav.lane_lost`. 자동 재탐색 주행 없음."""
        tracker, _ = self._tracker()
        tracker.update(detect_lane_error(_lane_frame()), at=1000.0)
        tracker.update(None, at=1001.0)
        assert tracker.stop_demanded(at=1004.1)
        assert tracker.state == "LOST"

    def test_reacquire_clears_the_loss(self):
        tracker, _ = self._tracker()
        tracker.update(detect_lane_error(_lane_frame()), at=1000.0)
        tracker.update(None, at=1002.5)
        assert not tracker.stop_demanded(at=1002.5)
        tracker.update(detect_lane_error(_lane_frame()), at=1002.6)
        assert tracker.state == "TRACKING"
        assert not tracker.stop_demanded(at=1005.0)   # 재목격 후 2.4 s — 유예 안

    def test_never_seen_is_not_lost(self):
        tracker = LaneTracker()
        assert tracker.state == "IDLE"
        assert not tracker.stop_demanded(at=9999.0)


# --- Two-line lane-centre mode (260919 road track, map_v2_fleet) -----------
#
# Each lane is bounded by two ~25 mm white lines, centre-to-centre 185 mm.
# Frames are built by inverse projection through the same declared Gazebo
# geometry the launch uses, so the detector is tested against the metric
# model it trusts rather than against hand-placed pixel columns.

import math

from control.sensing.perception.camera_ground import simulation_ground_plane
from control.sensing.perception.lane import detect_lane_centre

_HALF = 0.0925
_W, _H = 320, 180
_FLOOR, _PAINT, _BODY = 109, 225, 218
_BODY_TOP_ROW = 139


def _gazebo_ground():
    ground = simulation_ground_plane(
        source="GAZEBO", simulation_enabled=True, use_sim_time=True,
        width_px=_W, height_px=_H, height_m=0.060194,
        pitch_rad=math.radians(25.0), hfov_rad=1.1519, max_range_m=0.6)
    assert ground is not None
    return ground


def _track_frame(ground, line_ys, *, paint_half_width=0.0125, bars=(),
                 bar_half_width=0.010, bar_range=(0.15, 0.25)):
    """Lines run the whole visible floor; `bars` are crosswalk bars parallel
    to travel, painted only between the `bar_range` distances."""
    frame = np.full((_H, _W), _FLOOR, dtype=np.uint8)
    for row in range(_H):
        distance = ground.distance(row)
        if distance is None:
            continue
        in_bar_range = bar_range[0] <= distance <= bar_range[1]
        for col in range(_W):
            lateral = ground.lateral(col, row)
            if any(abs(lateral - y) < paint_half_width for y in line_ys) or (
                    in_bar_range
                    and any(abs(lateral - y) < bar_half_width for y in bars)):
                frame[row, col] = _PAINT
    frame[_BODY_TOP_ROW:, :] = _BODY
    return frame


def _centre(frame, ground, **overrides):
    kwargs = dict(bright_threshold=220, lane_half_width_m=_HALF,
                  roi_top_fraction=0.25, roi_bottom_fraction=0.75)
    kwargs.update(overrides)
    return detect_lane_centre(frame, ground, **kwargs)


class TestLaneCentre:
    def test_centred_between_two_lines_reads_near_zero(self):
        ground = _gazebo_ground()
        obs = _centre(_track_frame(ground, (-_HALF, _HALF)), ground)
        assert isinstance(obs, LaneObservation)
        assert abs(obs.error) < 0.1
        assert 0.0 < obs.confidence <= 1.0

    def test_centred_straight_lane_scores_only_rows_that_can_see_it(self):
        """Rows so near that the frame is narrower than the lane cannot show
        a centred lane; counting them made a perfect frame look doubtful."""
        ground = _gazebo_ground()
        obs = _centre(_track_frame(ground, (-_HALF, _HALF)), ground)
        assert obs is not None
        assert obs.confidence >= 0.9

    def test_crosswalk_bars_inside_the_lane_are_not_boundary_lines(self):
        """Gazebo run 163611, frame_12: bars parallel to travel look like lane
        lines in any single row. Pair by the lane width, not by nearness."""
        ground = _gazebo_ground()
        frame = _track_frame(ground, (-_HALF, _HALF),
                             bars=(-0.05, -0.017, 0.017, 0.05))
        obs = _centre(frame, ground)
        assert obs is not None
        assert abs(obs.error) < 0.1
        assert obs.confidence >= 0.8

    def test_several_unpaired_runs_are_not_guessed_between(self):
        """Two runs too close to be a lane: no pair, no single-line fallback."""
        ground = _gazebo_ground()
        frame = _track_frame(ground, (-0.03, 0.03))
        assert _centre(frame, ground) is None

    def test_lane_shifted_right_steers_right(self):
        ground = _gazebo_ground()
        obs = _centre(_track_frame(ground, (-0.0425, 0.1425)), ground)
        assert obs is not None
        assert obs.error > 0.2

    def test_sitting_on_the_right_line_steers_left_back_into_the_lane(self):
        """The failure seen in Gazebo: latched onto one boundary. Only the
        lane to the left is in view here."""
        ground = _gazebo_ground()
        obs = _centre(_track_frame(ground, (-0.185, 0.0)), ground)
        assert obs is not None
        assert obs.error < -0.3

    def test_three_equally_spaced_lines_are_ambiguous_in_one_frame(self):
        """Known limitation: on a shared boundary with both lanes in view,
        the two candidate pairs tie on width, and the midpoint tie-break is
        also a tie. A single frame cannot choose the lane; this pins that
        the answer is a full-scale lane, not a blend between them."""
        ground = _gazebo_ground()
        obs = _centre(_track_frame(ground, (-0.185, 0.0, 0.185)), ground)
        assert obs is not None
        assert abs(obs.error) == pytest.approx(1.0)

    def test_only_the_right_line_visible_infers_the_centre(self):
        ground = _gazebo_ground()
        obs = _centre(_track_frame(ground, (_HALF,)), ground)
        assert obs is not None
        assert obs.error == pytest.approx(0.0, abs=0.1)

    def test_uncalibrated_camera_never_drives_lane_mode(self):
        ground = _gazebo_ground()
        frame = _track_frame(ground, (-_HALF, _HALF))
        assert _centre(frame, None) is None

    def test_washed_out_frame_is_no_lane(self):
        ground = _gazebo_ground()
        frame = np.full((_H, _W), 250, dtype=np.uint8)
        assert _centre(frame, ground) is None

    def test_robot_body_rows_are_not_a_line(self):
        ground = _gazebo_ground()
        frame = _track_frame(ground, ())
        assert _centre(frame, ground) is None
        # Threshold alone also keeps the 218 body out, even with the full band.
        assert _centre(frame, ground, roi_bottom_fraction=1.0) is None

    def test_wide_crossing_bar_is_not_a_boundary_line(self):
        """A stop line seen across the lane is far wider than a lane line."""
        ground = _gazebo_ground()
        frame = _track_frame(ground, ())
        frame[70:80, :] = _PAINT
        assert _centre(frame, ground) is None

    def test_bgr_frames_are_accepted(self):
        ground = _gazebo_ground()
        gray = _track_frame(ground, (-_HALF, _HALF))
        obs = _centre(np.dstack([gray, gray, gray]), ground)
        assert obs is not None
        assert abs(obs.error) < 0.1

    @pytest.mark.parametrize("overrides", [
        {"lane_half_width_m": 0.0},
        {"lane_half_width_m": float("nan")},
        {"roi_top_fraction": 1.0},
        {"roi_bottom_fraction": 0.2},
        {"roi_bottom_fraction": 1.5},
        {"bright_threshold": 255},
        {"washed_fraction": 0.0},
        {"max_line_width_m": 0.0},
        {"row_step": 0},
        {"row_step": True},
    ])
    def test_bad_arguments_fail_loudly(self, overrides):
        ground = _gazebo_ground()
        frame = _track_frame(ground, (-_HALF, _HALF))
        with pytest.raises(ValueError):
            _centre(frame, ground, **overrides)
