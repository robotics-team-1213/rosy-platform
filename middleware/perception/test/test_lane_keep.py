"""D-364 §2: 'keep' lane keeper on synthetic floors rendered through the NOMINAL ground."""
import json
import math
from pathlib import Path

import numpy as np
import pytest
import yaml

from control.sensing.perception.camera_ground import nominal_ground_plane
from control.sensing.perception.lane_keep import CORNER_MAX_ERROR as CORNER_CAP, FLIP_WINDOW_FRAMES as FLIP_WINDOW, LaneKeeper
from control.sensing.perception.lane_keep import SIDE_X_M
from control.sensing.perception.lane_keep_pairs import is_pair, pair_conflicts

PKG = Path(__file__).resolve().parents[1]
PROFILE = yaml.safe_load((Path(__file__).resolve().parents[3] / "middleware" / "apps" / "device" / "pinky" / "profile" / "config" / "camera_nominal.yaml").read_text(encoding="utf-8"))
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


def test_follow_explanation_marks_only_the_chosen_pair_and_records_lane_width():
    obs, last = _keep(_render([(HALF, 0.0), (-HALF, 0.0)]))
    assert obs is not None
    assert last['lane_width_m'] == pytest.approx(2 * HALF)
    assert {b['side'] for b in last['boundaries'] if b.get('selected')} == {'left', 'right'}
    assert sum(bool(b.get('selected')) for b in last['candidates']) == 2


def test_hold_does_not_keep_a_previously_selected_boundary():
    keeper = LaneKeeper(camera_x_offset_m=X_OFFSET, smoothing=0.0)
    assert keeper.update(_render([(HALF, 0.0), (-HALF, 0.0)]), GROUND) is not None
    assert keeper.update(_render(), GROUND) is None
    assert not any(b.get('selected') for b in keeper.last['boundaries'])


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


def test_tracked_side_flips_after_persistent_wrong_side():
    # 20261005T134540Z (9dfk, frames 329-367): a boundary tracked 'left' slid
    # under the robot to y -0.05..-0.07 and kept its stale side while the robot
    # drove along it, so the one-sided target sat a half-width past the right
    # tape (error pinned at +1.0 toward the next lane). A crossing is through
    # in a frame or two; SIDE_FLIP_FRAMES of contradicting sides must hand the
    # line back to its ground side.
    keeper = LaneKeeper(camera_x_offset_m=X_OFFSET, smoothing=0.0)
    for y in (0.03, 0.01, -0.01, -0.04, -0.05, -0.05, -0.05, -0.05):
        obs = keeper.update(_render([(y, 0.0)]), GROUND, lane_half_width_m=HALF)
        assert obs is not None
    last = keeper.last
    assert last["boundaries"][0]["side"] == "right"
    assert last["target_m"][1] > -HALF + 0.02  # target back inside the lane, not past the tape
    assert last["error"] < -0.2  # steer left, away from the neighbour lane


def test_momentary_cross_under_the_robot_keeps_its_side():
    # The tracking rule exists for this: a boundary passing under the camera
    # for a frame or two is still the boundary it was (within SIDE_FLIP_M),
    # including one frame clearly on the other side.
    keeper = LaneKeeper(camera_x_offset_m=X_OFFSET, smoothing=0.0)
    for y in (0.06, 0.02, -0.02, -0.06):
        obs = keeper.update(_render([(y, 0.0)]), GROUND, lane_half_width_m=HALF)
        assert obs is not None
    assert keeper.last["boundaries"][0]["side"] == "left"


def test_transverse_stop_line_is_ignored():
    obs, last = _keep(_render([(HALF, 0.0), (-HALF, 0.0)], transverse_x=0.25))
    assert last["strategy"] == "both" and abs(obs.error) < 0.1
    assert last["transverse"], "the stop line should be reported as transverse"
    obs, last = _keep(_render([], transverse_x=0.25))
    assert obs is None and last["strategy"] == "none"


def test_candidates_list_every_line_with_its_reject_reason():
    # D-384 replay reads all fitted lines: accepted boundaries and rejects alike.
    obs, last = _keep(_render([(HALF, 0.0), (-HALF, 0.0)], transverse_x=0.25))
    accepted = [c for c in last["candidates"] if not c["rejected"]]
    rejected = [c for c in last["candidates"] if c["rejected"]]
    assert len(accepted) == len(last["boundaries"]) >= 2
    assert {c["side"] for c in accepted} == {"left", "right"}
    assert all(c["reason"] is None for c in accepted)
    assert any(c["reason"] == "transverse" for c in rejected)
    assert all("centre" not in c and "direction" not in c for c in last["candidates"])
    assert _keep(_render([]))[1]["candidates"] == []


def test_steep_line_far_outside_the_lane_is_not_sided():
    # Real 124745Z: 60-64 deg diagonals sided at y -0.30..-0.42 m (beyond the lane).
    image = _render([(HALF, 0.0), (-HALF, 0.0)])
    # A ~60 deg tape segment right of the lane only (x = 0.40 + (y + 0.13) / 1.73).
    segment = np.isfinite(X) & (np.abs(X - (0.40 + (Y + 0.13) / 1.73)) <= 0.015) & (Y < -0.14) & (Y > -0.3)
    image[segment] = 195
    obs, last = _keep(image)
    assert obs is not None and last["strategy"] == "both" and abs(obs.error) < 0.15
    assert all(abs(b["y_at_side_x_m"]) < 0.2 for b in last["boundaries"])
    steep = [c for c in last["candidates"] if c["reason"] == "steep_far"]
    assert steep and all(c["rejected"] and abs(c["heading_deg"]) > 45 for c in steep)


def test_steep_diagonal_crossing_the_path_ahead_is_not_sided():
    # Real 124745Z frame 94: a ~60 deg mark from y -0.11 to +0.10, 0.33-0.45 m ahead.
    image = _render([(HALF, 0.0), (-HALF, 0.0)])
    segment = np.isfinite(X) & (np.abs(X - (0.33 + (Y + 0.11) / 1.73)) <= 0.015) & (Y > -0.11) & (Y < 0.10)
    image[segment] = 195
    obs, last = _keep(image)
    assert obs is not None and last["strategy"] == "both" and abs(obs.error) < 0.15
    assert all(abs(b["heading_deg"]) < 45 for b in last["boundaries"])
    assert [c for c in last["candidates"] if c["reason"] == "steep_crossing" and c["rejected"]]


def test_steep_segment_starting_at_the_lane_edge_is_still_sided():
    # A curving boundary seen far ahead: steep, extrapolates far at SIDE_X_M,
    # but its paint starts at the lane edge, so it stays a boundary.
    image = _render([(HALF, 0.0)])
    segment = np.isfinite(X) & (np.abs(X - (0.40 + (Y + 0.09) / 1.73)) <= 0.015) & (Y < -0.09) & (Y > -0.3)
    image[segment] = 195
    _, last = _keep(image)
    assert not [c for c in last["candidates"] if c["reason"] == "steep_far"]


def test_steep_far_line_is_sided_while_a_corner_is_latched():
    keeper = LaneKeeper(camera_x_offset_m=X_OFFSET, smoothing=0.0)
    image = _render([(HALF, 0.0), (-HALF, 0.0)])
    segment = np.isfinite(X) & (np.abs(X - (0.40 + (Y + 0.13) / 1.73)) <= 0.015) & (Y < -0.14) & (Y > -0.3)
    image[segment] = 195
    keeper._corner_side = "right"
    keeper.update(image, GROUND, lane_half_width_m=HALF)
    assert not [c for c in keeper.last["candidates"] if c["reason"] == "steep_far"]


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


def test_crosswalk_bars_beside_the_lane_lines_do_not_hide_them():
    # Bars parallel to travel light ONE flank of each lane line; a blob lights both.
    image = _render([(HALF, 0.0), (-HALF, 0.0)])
    bars = np.zeros(X.shape, bool)
    for centre in (-0.035, 0.035):
        bars |= np.isfinite(X) & (X > 0.20) & (X < 0.32) & (np.abs(Y - centre) <= 0.015)
    image[bars] = 195
    obs, last = _keep(image)
    assert last["strategy"] == "both" and abs(obs.error) < 0.15


def _segment(image, y0, slope, x0, x1):
    """Paint tape y = y0 + slope * x for x0 <= x <= x1 onto a _render image."""
    band = np.abs(Y - (y0 + slope * X)) <= TAPE_HALF * np.sqrt(1.0 + slope * slope)
    image[np.isfinite(X) & (X >= x0) & (X <= x1) & band] = 195
    return image


def _conflicts(last):
    return [c for c in last["candidates"] if c["reason"] == "pair_conflict"]


def test_chord_closing_on_the_lane_line_is_not_its_pair():
    # Real 124745Z frames 800-1017: a -17..-20 deg chord across crosswalk bars
    # on the right, 0.12 m from the left lane line at SIDE_X_M but closing to
    # half a lane at its near end, was paired with it (target pulled 3 cm left).
    image = _segment(_render([(0.045, 0.0)]), -0.055 + 0.15 * 0.306, -0.306, 0.15, 0.40)
    obs, last = _keep(image)
    assert last["strategy"] == "left_only" and obs.error > 0.4
    assert [b["side"] for b in last["boundaries"]] == ["left"]
    chord = _conflicts(last)
    assert len(chord) == 1 and chord[0]["rejected"] and chord[0]["heading_deg"] < -15


def test_junction_corner_stub_is_not_a_boundary():
    # Real 124745Z frames 95-252: a 7 cm stub across a junction-mouth corner on
    # the left, +30 deg and a lane width from the right lane line, was sided left.
    slope = 0.53
    image = _segment(_render([(-0.085, 0.0)]), 0.10 - 0.22 * slope, slope, 0.28, 0.35)
    obs, last = _keep(image)
    assert last["strategy"] == "right_only" and abs(obs.error) < 0.2
    assert [b["side"] for b in last["boundaries"]] == ["right"]
    chord = _conflicts(last)
    assert len(chord) == 1 and chord[0]["side"] == "left" and chord[0]["heading_deg"] > 20


def test_a_dropped_chord_keeps_its_side_next_frame():
    # Dropped chords are still tracked: one drifting across the robot's path
    # is not re-sided as the other lane boundary (teleop replay: 40 -> 21
    # frames whose error moved by more than 0.5).
    slope = 0.47
    keeper = _keeper()
    first = _segment(_render([(-0.085, 0.0)]), 0.04 - 0.22 * slope, slope, 0.18, 0.36)
    keeper.update(first, GROUND, lane_half_width_m=HALF)
    assert [c["side"] for c in _conflicts(keeper.last)] == ["left"]
    keeper.update(_segment(_render(), -0.015 - 0.22 * slope, slope, 0.18, 0.36), GROUND, lane_half_width_m=HALF)
    assert keeper.last["strategy"] == "left_only"
    assert _keep(_segment(_render(), -0.015 - 0.22 * slope, slope, 0.18, 0.36))[1]["strategy"] == "right_only"


def test_a_short_true_boundary_is_kept_by_its_partner():
    # A long skew stray (+35 deg) out-paints a short true right line, but that
    # line pairs with the left lane line: the stray is not allowed to drop it.
    image = _segment(_render([(HALF, 0.0)]), -0.0925, 0.0, 0.28, 0.36)
    image = _segment(image, 0.12 - 0.30 * 0.7, 0.7, 0.30, 0.43)
    obs, last = _keep(image)
    # At the URDF-nominal lens height (0.0634 m, D-397) the 35 deg stray fits at ~30 deg.
    assert any(c["heading_deg"] > 25 for c in last["candidates"]), "the stray must be fitted"
    assert last["strategy"] == "both" and abs(obs.error) < 0.15
    assert any(b["side"] == "right" and abs(b["heading_deg"]) < 10 for b in last["boundaries"])
    # The partner (the true left lane line) stays straight: the stray did not bend it.
    assert any(b["side"] == "left" and abs(b["heading_deg"]) < 5 for b in last["boundaries"])
    assert not _conflicts(last)


def test_steep_lines_are_never_pair_conflicts():
    # Junction crossings steeper than CONFLICT_MAX_HEADING_RAD are left to the
    # steep and junction rules, not dropped as a skew couple.
    image = _segment(_render([(HALF, 0.0)]), -0.09 - 0.22 * -1.19, -1.19, 0.20, 0.26)
    _, last = _keep(image)
    assert any(abs(c["heading_deg"]) > 45 for c in last["candidates"])
    assert not _conflicts(last)


def _record(y, heading_deg, length, side):
    direction = np.array([math.cos(math.radians(heading_deg)), math.sin(math.radians(heading_deg))])
    centre = np.array([0.30, y + (0.30 - 0.22) * direction[1] / direction[0]])
    ends = [centre - direction * length / 2, centre + direction * length / 2]
    return {"y_at_side_x_m": y, "heading_deg": heading_deg, "length_m": length, "side": side,
            "centre": centre, "direction": direction, "ends_m": [[float(p[0]), float(p[1])] for p in ends]}


def test_a_tied_conflict_drops_the_line_further_from_the_robot():
    left, right = _record(0.06, 20.0, 0.2, "left"), _record(-0.12, -20.0, 0.2, "right")
    assert pair_conflicts([left], [right], HALF, SIDE_X_M) == [right]
    left, right = _record(0.12, 20.0, 0.2, "left"), _record(-0.06, -20.0, 0.2, "right")
    assert pair_conflicts([left], [right], HALF, SIDE_X_M) == [left]


def test_conflicts_settle_strongest_line_first():
    # L1 loses to R1; R2 would lose to L1 alone. Whatever the list order, the
    # dropped L1 must not drop R2 too.
    l1, r1 = _record(0.09, 35.0, 0.25, "left"), _record(-0.09, 0.0, 0.30, "right")
    r2 = _record(-0.05, -20.0, 0.10, "right")
    assert pair_conflicts([l1], [r2, r1], HALF, SIDE_X_M) == [l1]
    assert pair_conflicts([l1], [r1, r2], HALF, SIDE_X_M) == [l1]


def test_a_short_true_left_boundary_is_kept_by_its_partner():
    # Mirror of the right-side exemption: a stronger skew stray on the right
    # does not drop a short left line that pairs with the right lane line.
    left = _record(0.09, 0.0, 0.08, "left")
    stray, right = _record(-0.06, -35.0, 0.20, "right"), _record(-0.09, 0.0, 0.30, "right")
    assert pair_conflicts([left], [stray, right], HALF, SIDE_X_M) == []
    assert pair_conflicts([left], [stray], HALF, SIDE_X_M) == [left]


def test_paint_along_the_heading_outweighs_length():
    # cos^2 weight: a longer line at 35 deg loses to a shorter straight one.
    longer, straight = _record(0.09, 35.0, 0.25, "left"), _record(-0.09, 0.0, 0.20, "right")
    assert pair_conflicts([longer], [straight], HALF, SIDE_X_M) == [longer]


def _drop_steep_left(monkeypatch, min_heading_deg):
    import control.sensing.perception.lane_keep as lk
    real = lk.pair_conflicts
    monkeypatch.setattr(lk, "pair_conflicts", lambda left, right, half, side_x: real(left, right, half, side_x)
                        + [b for b in left if b["heading_deg"] > min_heading_deg])


def test_a_dropped_branch_still_holds_the_fork(monkeypatch):
    _drop_steep_left(monkeypatch, 30.0)
    slope = np.tan(np.radians(45.0))
    image = _render([(HALF, 0.0), (0.05 - slope * 0.22, slope)])
    keeper = _corner_keeper()
    assert keeper.update(image, GROUND, lane_half_width_m=HALF) is None
    assert keeper.last["reason"] == "junction_fork"
    assert [c["side"] for c in keeper.last["candidates"] if c["reason"] == "pair_conflict"] == ["left"]
    assert [b["side"] for b in keeper.last["boundaries"]] == ["left"]


def test_a_dropped_diverging_boundary_still_holds_the_junction_mouth(monkeypatch):
    # The junction-mouth scene with its diverging line dropped: still a hold.
    _drop_steep_left(monkeypatch, 15.0)
    slope = np.tan(np.radians(25.0))
    image = _render([(HALF - slope * 0.22, slope), (HALF + 0.06, 0.0)], transverse_x=0.30)
    keeper = _corner_keeper()
    assert keeper.update(image, GROUND, lane_half_width_m=HALF) is None
    assert keeper.last["reason"] == "junction_transverse"
    assert [c["side"] for c in keeper.last["candidates"] if c["reason"] == "pair_conflict"] == ["left"]


def test_a_dropped_line_past_the_corner_still_vetoes_it(monkeypatch):
    # A left line running on past an L-corner line open to the left: no corner,
    # even when that line was dropped from the pairing.
    _drop_steep_left(monkeypatch, -90.0)
    image = np.maximum(_render_corner(0.25, "left"), _render([(HALF, 0.0)]))
    keeper = _corner_keeper()
    keeper.update(image, GROUND, lane_half_width_m=HALF)
    assert _conflicts(keeper.last) and not keeper.last["strategy"].startswith("corner")


def test_lane_lines_splayed_by_the_nominal_ground_still_pair():
    # NOMINAL pitch errors splay the two lines of one lane by several degrees.
    obs, last = _keep(_render([(HALF, 0.09), (-HALF, -0.09)]))
    assert last["strategy"] == "both" and abs(obs.error) < 0.1
    assert not _conflicts(last)


def test_outward_splay_keeps_both_boundaries_within_the_seen_lane_width():
    # Replay: nominal projection splays the left/right lines by 27/-8 deg.
    # Each is within the boundary heading limit; their common stretch stays
    # a lane wide. Dropping the left line adds a rightward steering bias.
    left = _record(0.10, 27.0, 0.10, "left")
    right = _record(-0.111, -8.0, 0.23, "right")
    assert is_pair(left, right, 2 * HALF, SIDE_X_M)
    assert pair_conflicts([left], [right], HALF, SIDE_X_M) == []
    target, strategy = _keeper()._choose([left], [right], HALF)
    assert strategy == "both" and abs(target[1]) < 0.02


def test_outward_splay_does_not_relax_the_seen_width_or_individual_heading():
    right = _record(-0.111, -8.0, 0.23, "right")
    assert not is_pair(_record(0.20, 27.0, 0.114, "left"), right, 2 * HALF, SIDE_X_M)
    assert not is_pair(_record(0.10, 35.0, 0.10, "left"), right, 2 * HALF, SIDE_X_M)
    # A closing chord gets no outward-splay exception.
    left = _record(0.09, -27.0, 0.06, "left")
    right = _record(-0.09, 8.0, 0.06, "right")
    assert not is_pair(left, right, 2 * HALF, SIDE_X_M)


def test_steep_crossing_near_the_path_is_not_a_lone_lane_boundary():
    # Replay: a transverse marking projects to 61 deg, spanning both sides
    # of the path, but its extrapolated offset is less than one lane width.
    slope = math.tan(math.radians(61.0))
    image = _segment(_render(), -0.121 - 0.241 * slope, slope, 0.241, 0.434)
    obs, last = _keep(image)
    assert obs is None and last['target_m'] is None
    assert any(c['reason'] == 'steep_crossing' for c in last['candidates'])


def test_short_steep_boundary_near_the_path_is_not_a_full_lane_crossing():
    # A curve approaches the path but does not span the lane. Mere contact
    # with the path tolerance is insufficient evidence of a transverse mark.
    image = _segment(_render(), 0.04 - 0.22 * 1.5, 1.5, 0.20, 0.27)
    obs, last = _keep(image)
    assert obs is not None
    assert not any(c['reason'] == 'steep_crossing' for c in last['candidates'])


def test_outward_splay_requires_an_observed_common_stretch():
    left = _record(0.10, 27.0, 0.10, "left")
    right = _record(-0.111, -8.0, 0.05, "right")
    shift = 0.4 * right['direction']
    right['centre'] += shift
    right['ends_m'] = [(np.asarray(end) + shift).tolist() for end in right['ends_m']]
    assert not is_pair(left, right, 2 * HALF, SIDE_X_M)


def test_crosswalk_blob_does_not_erase_a_continuous_lane_boundary():
    # Several wide bars produce the largest RANSAC diagonal, which is a blob.
    # The continuous left boundary is still supported by thin paint and a
    # dark flank; it must survive the failed diagonal hypothesis.
    image = _render([(0.09, 0.0)])
    for centre in (-0.08, -0.02, 0.04):
        bars = np.isfinite(X) & (X > 0.18) & (X < 0.30) & (np.abs(Y - centre) <= 0.02)
        image[bars] = 195
    obs, last = _keep(image)
    assert obs is not None and last['strategy'] == 'left_only'
    assert abs(last['target_m'][1]) < 0.02


def test_blob_retry_does_not_invent_a_boundary_on_a_solid_patch():
    from control.sensing.perception.lane_keep_lines import extract_lines
    x, y = np.meshgrid(np.arange(0.15, 0.45, 0.005), np.arange(-0.10, 0.10, 0.005))
    fitted, blobs = extract_lines(np.column_stack((x.ravel(), y.ravel())), np.random.default_rng(0))
    assert not fitted and blobs


def _render_corner(line_x, open_side):
    """An L-corner: the outer boundary of the next lane runs across at
    x = line_x from the closed side's lane line toward the open side; the
    closed side's lane line runs up to it. The inner side has no line left."""
    sign = 1.0 if open_side == "left" else -1.0
    rng = np.random.default_rng(7)
    image = 100 + rng.normal(0, 8, X.shape)
    floor = np.isfinite(X)
    outer = -sign * HALF
    across = floor & (np.abs(X - line_x) <= TAPE_HALF) & (sign * (Y - outer) >= -TAPE_HALF)
    side = floor & (np.abs(Y - outer) <= TAPE_HALF) & (X <= line_x + TAPE_HALF)
    image = np.where(across | side, 195.0, image)
    image[~floor] = 60.0
    return np.dstack([np.clip(image, 0, 255).astype(np.uint8)] * 3)


@pytest.mark.parametrize("open_side, sign", [("left", -1), ("right", +1)])
def test_l_corner_goes_straight_then_turns_toward_the_open_side(open_side, sign):
    keeper = LaneKeeper(camera_x_offset_m=X_OFFSET, smoothing=0.0, corner_turning=True)
    far = keeper.update(_render_corner(0.40, open_side), GROUND, lane_half_width_m=HALF)
    assert far is not None and abs(far.error) < 0.15  # corner still ahead: straight on
    near = keeper.update(_render_corner(0.19, open_side), GROUND, lane_half_width_m=HALF)
    assert keeper.last["strategy"] == f"corner_{open_side}"
    # CORE: angular = -gain * error; a left turn needs error < 0.
    assert near is not None and near.error * sign > 0.3


def test_corner_side_needs_an_open_end_or_a_latch():
    # Near the corner the open end can fall outside the view; a fresh keeper
    # must not guess a side from a line spanning the whole view (stop line, T).
    obs, last = _keep(_render([], transverse_x=0.19))
    assert obs is None and last["strategy"] == "none"
    keeper = LaneKeeper(camera_x_offset_m=X_OFFSET, smoothing=0.0, corner_turning=True)
    keeper.update(_render_corner(0.40, "left"), GROUND, lane_half_width_m=HALF)
    latched = keeper.update(_render([], transverse_x=0.19), GROUND, lane_half_width_m=HALF)
    assert keeper.last["strategy"] == "corner_left" and latched.error < -0.3
    # Both boundaries in view again clear the latch.
    keeper.update(_render([(HALF, 0.0), (-HALF, 0.0)]), GROUND, lane_half_width_m=HALF)
    assert keeper.update(_render([], transverse_x=0.19), GROUND, lane_half_width_m=HALF) is None


def test_cold_corner_without_a_side_boundary_holds():
    # The closed-side line has left the view. A cropped crossbar alone cannot
    # establish which physical lane the robot should turn into.
    keeper = LaneKeeper(camera_x_offset_m=X_OFFSET, smoothing=0.0, corner_turning=True)
    assert keeper.update(_render_corner(0.26, "left"), GROUND, lane_half_width_m=HALF) is None
    assert keeper.last["strategy"] == "none"
    keeper.update(_render([(HALF, 0.0)]), GROUND, lane_half_width_m=HALF)
    assert keeper.update(_render_corner(0.26, "left"), GROUND, lane_half_width_m=HALF) is None


def test_short_closed_side_fragment_cannot_seed_a_turn():
    # 10/6 candidate: an across line plus a 61 mm edge fragment at the image border.
    a, b = np.array([0.25, -0.128]), np.array([0.328, 0.096])
    direction = (b - a) / np.linalg.norm(b - a)
    transverse = [((a + b) / 2, direction, [a, b], False)]
    keeper = LaneKeeper(corner_turning=True)
    assert keeper._corner(transverse, HALF, [], [{"side": "left", "length_m": 0.061}]) is None
    assert keeper._corner(transverse, HALF, [], [{"side": "left", "length_m": 0.185}]) is not None


def test_new_short_fragment_cannot_become_a_one_side_target():
    # A 61 mm fragment at the image border is not an established lane edge.
    keeper = LaneKeeper()
    line = {"side": "left", "length_m": 0.061, "y_at_side_x_m": 0.144,
            "tracked": False, "pursuit_m": [0.25, 0.01]}
    target, strategy = keeper._choose([line], [], HALF)
    assert target is None and strategy == "none"
    line["tracked"] = True
    target, strategy = keeper._choose([line], [], HALF)
    assert target is not None and strategy == "left_only"
    line["tracked"] = False
    target, strategy = keeper._choose([line], [], HALF, bend_expected=True)
    assert target is not None and strategy == "left_only"


def test_short_fragment_requires_a_boundary_seen_in_the_previous_image():
    full = _render([(HALF, 0.0), (-HALF, 0.0)])
    fragment = _render([(HALF, 0.0)])
    fragment[np.isfinite(X) & ((X < 0.22) | (X > 0.30))] = 100

    fresh = _keeper()
    assert fresh.update(fragment, GROUND, lane_half_width_m=HALF) is None
    assert fresh.last["strategy"] == "none"

    tracked = _keeper()
    assert tracked.update(full, GROUND, lane_half_width_m=HALF) is not None
    obs = tracked.update(fragment, GROUND, lane_half_width_m=HALF)
    assert obs is not None and tracked.last["strategy"] == "left_only"
    assert tracked.last["boundaries"][0]["tracked"] is True
    assert abs(tracked.last["target_m"][1]) < 0.03


def test_mid_turn_keeps_turning_toward_the_new_lane():
    # Latched left, then the robot has turned ~15 deg left: the corner line now
    # runs at 75 deg and its meeting point with the heading has moved away.
    keeper = LaneKeeper(camera_x_offset_m=X_OFFSET, smoothing=0.0, corner_turning=True)
    keeper.update(_render_corner(0.40, "left"), GROUND, lane_half_width_m=HALF)
    slope = np.tan(np.radians(75.0))
    obs = keeper.update(_render([(-slope * 0.30, slope)]), GROUND, lane_half_width_m=HALF)
    assert keeper.last["strategy"] == "corner_left"
    assert obs is not None and obs.error < -0.3


def test_latched_corner_follows_the_outer_line_below_the_transverse_angle():
    # 40 deg into a left turn the next lane's outer line runs at +50 deg: not
    # transverse any more, but still the corner line, not a side boundary.
    keeper = LaneKeeper(camera_x_offset_m=X_OFFSET, smoothing=0.0, corner_turning=True)
    keeper.update(_render_corner(0.40, "left"), GROUND, lane_half_width_m=HALF)
    slope = np.tan(np.radians(50.0))
    obs = keeper.update(_render([(-slope * 0.22, slope)]), GROUND, lane_half_width_m=HALF)
    assert keeper.last["strategy"] == "corner_left"
    assert obs is not None and obs.error < 0.0


def test_corner_turning_is_opt_in():
    keeper = LaneKeeper(camera_x_offset_m=X_OFFSET, smoothing=0.0)
    keeper.update(_render_corner(0.40, "left"), GROUND, lane_half_width_m=HALF)
    keeper.update(_render_corner(0.19, "left"), GROUND, lane_half_width_m=HALF)
    assert not keeper.last["strategy"].startswith("corner")


def test_node_wires_keep_mode_on_the_labelled_ground():
    text = (PKG / "control" / "line_observer_node.py").read_text(encoding="utf-8")
    uses_ground = text.split("def _camera_mode_uses_ground", 1)[1].split("def ", 1)[0]
    assert "'keep'" in uses_ground
    assert "self._lane_keeper.update(" in text
    assert "ground = self._ground(frame.shape[1], frame.shape[0])" in text
    assert "frame, ground, paint_mask=paint," in text   # D-408 paint source
    assert "corner_turning=bool(self.get_parameter('lane_corner_turning').value)" in text


def _keeper(**kw):
    return LaneKeeper(camera_x_offset_m=X_OFFSET, smoothing=0.0, **kw)


def test_a_line_drifting_across_keeps_its_side():
    # Last frame the lone line was the LEFT boundary; now it has drifted 3.5 cm
    # right of base_link. A fresh keeper calls it right; the tracked one keeps
    # it left and keeps steering right, back into the lane.
    assert _keep(_render([(-0.035, 0.0)]))[1]["strategy"] == "right_only"
    keeper = _keeper()
    keeper.update(_render([(0.02, 0.0)]), GROUND, lane_half_width_m=HALF)
    assert keeper.last["strategy"] == "left_only"
    obs = keeper.update(_render([(-0.035, 0.0)]), GROUND, lane_half_width_m=HALF)
    assert keeper.last["strategy"] == "left_only" and obs.error > 0.9
    assert keeper.last["boundaries"][0]["tracked"] is True


def test_tracked_side_flips_on_clear_evidence():
    keeper = _keeper()
    keeper.update(_render([(0.02, 0.0)]), GROUND, lane_half_width_m=HALF)
    keeper.update(_render([(-0.035, 0.0)]), GROUND, lane_half_width_m=HALF)
    assert keeper.last["strategy"] == "left_only"
    # Now 9 cm right of the robot: past SIDE_FLIP_M, it is the right boundary.
    keeper.update(_render([(-0.09, 0.0)]), GROUND, lane_half_width_m=HALF)
    assert keeper.last["strategy"] == "right_only"
    # A line that turned 31 deg (not continuous) is sided by geometry alone.
    keeper = _keeper()
    keeper.update(_render([(0.02, 0.0)]), GROUND, lane_half_width_m=HALF)
    keeper.update(_render([(-0.035 - 0.6 * 0.22, 0.6)]), GROUND, lane_half_width_m=HALF)
    assert keeper.last["strategy"] == "right_only"


def test_one_sided_choice_prefers_the_boundary_seen_last_frame():
    # Two lone lines, closer than a lane width: the left one a bit nearer.
    # After the right one was the boundary, it stays the boundary.
    keeper = _keeper()
    keeper.update(_render([(-0.06, 0.0)]), GROUND, lane_half_width_m=HALF)
    obs = keeper.update(_render([(0.045, 0.0), (-0.06, 0.0)]), GROUND, lane_half_width_m=HALF)
    assert keeper.last["strategy"] == "right_only" and obs.error < 0.0
    fresh = _keep(_render([(0.045, 0.0), (-0.06, 0.0)]))[1]
    assert fresh["strategy"] == "left_only"


@pytest.mark.parametrize("gap", [0.02, 0.0])
def test_tape_at_the_base_of_a_wall_filling_the_view_is_kept(gap):
    # Heading ~31 deg into a white wall on the left that fills most of the
    # floor view; the outer tape runs along its base (with or without a strip
    # of carpet between). The wall must not become floor (a blob swallowing
    # the tape) and the tape must not be masked with the wall.
    slope, wall_y = -0.6, 0.12
    image = _render([(wall_y - gap - TAPE_HALF, slope)])
    floor = np.isfinite(X)
    image[floor & (Y > wall_y + slope * X)] = 215
    image[~floor] = 215
    obs, last = _keep(image)
    assert obs is not None and last["blobs"] == 0
    assert any(abs(b["heading_deg"] + 31.0) < 5.0 for b in last["boundaries"])


def _corner_keeper():
    return _keeper(corner_turning=True)


def test_junction_mouth_holds_with_corner_turning():
    # A lone left boundary bending out of the lane (+25 deg) and a line across
    # ahead: a junction mouth, not a lane to follow. With corner turning the
    # keeper holds; the plain keeper (device default) keeps its boundary.
    slope = np.tan(np.radians(25.0))
    image = _render([(HALF - slope * 0.22, slope)], transverse_x=0.30)
    keeper = _corner_keeper()
    assert keeper.update(image, GROUND, lane_half_width_m=HALF) is None
    assert keeper.last["reason"] == "junction_transverse"
    obs, last = _keep(image)
    assert obs is not None and last["strategy"] == "left_only"


def test_fork_on_the_followed_side_holds_with_corner_turning():
    # Two left boundaries splitting by 45 deg: which one bounds the lane is unknown.
    slope = np.tan(np.radians(45.0))
    image = _render([(HALF, 0.0), (0.05 - slope * 0.22, slope)])
    keeper = _corner_keeper()
    assert keeper.update(image, GROUND, lane_half_width_m=HALF) is None
    assert keeper.last["reason"] == "junction_fork"


def test_reversing_hard_steering_holds_with_corner_turning():
    # The lone boundary jumps from one side to the other every frame: hard
    # left, hard right, hard left... After two reversals the keeper holds.
    frames = [_render([(0.035, 0.0)]), _render([(-0.035, 0.0)])] * 2
    keeper = _corner_keeper()
    results = [keeper.update(f, GROUND, lane_half_width_m=HALF) for f in frames]
    assert all(r is not None for r in results[:2])
    assert results[-1] is None and keeper.last["reason"] == "flipping"
    plain = _keeper()
    assert all(plain.update(f, GROUND, lane_half_width_m=HALF) is not None for f in frames)


def test_line_across_between_two_lane_lines_is_not_a_corner():
    # Both lane lines in view and a line across ahead (a stop line, or the
    # far edge of a junction): the lane is followed and no corner is latched,
    # so the next frame without the lane lines is not a corner either.
    keeper = _corner_keeper()
    obs = keeper.update(_render([(HALF, 0.0), (-HALF, 0.0)], transverse_x=0.30), GROUND,
                        lane_half_width_m=HALF)
    assert keeper.last["strategy"] == "both" and abs(obs.error) < 0.15
    assert keeper.update(_render([], transverse_x=0.19), GROUND, lane_half_width_m=HALF) is None


def test_corner_turn_command_is_capped():
    keeper = _corner_keeper()
    keeper.update(_render_corner(0.40, "left"), GROUND, lane_half_width_m=HALF)
    obs = keeper.update(_render_corner(0.19, "left"), GROUND, lane_half_width_m=HALF)
    assert keeper.last["strategy"] == "corner_left"
    assert -CORNER_CAP - 1e-9 <= obs.error < -0.3


def test_flipping_hold_is_sticky_until_both_lane_lines_are_seen():
    keeper = _corner_keeper()
    for f in [_render([(0.035, 0.0)]), _render([(-0.035, 0.0)])] * 2:
        keeper.update(f, GROUND, lane_half_width_m=HALF)
    assert keeper.last["reason"] == "flipping"
    # A calm lone boundary does not release the hold ...
    for _ in range(FLIP_WINDOW + 2):
        assert keeper.update(_render([(HALF, 0.0)]), GROUND, lane_half_width_m=HALF) is None
    # ... the lane seen on both sides does.
    assert keeper.update(_render([(HALF, 0.0), (-HALF, 0.0)]), GROUND,
                         lane_half_width_m=HALF) is not None


@pytest.mark.parametrize("y", [0.05, -0.05])
def test_a_washed_frame_forgets_the_tracked_sides(y):
    # A line tracked on the other side, then a washed-out frame: the next line
    # is sided afresh by its own geometry, not inherited across the gap.
    keeper = _keeper()
    keeper.update(_render([(-y * 0.1, 0.0)]), GROUND, lane_half_width_m=HALF)
    assert keeper.last["strategy"] == ("right_only" if y > 0 else "left_only")
    washed = np.full((240, 320, 3), 100, np.uint8)   # glare over most of the floor
    washed[:, 110:] = 240
    washed[:80] = 60
    assert keeper.update(washed, GROUND, lane_half_width_m=HALF) is None
    assert keeper.last["reason"] == "washed"
    keeper.update(_render([(y, 0.0)]), GROUND, lane_half_width_m=HALF)
    assert keeper.last["strategy"] == ("left_only" if y > 0 else "right_only")
    assert keeper.last["boundaries"][0]["tracked"] is False


def test_node_resets_the_keeper_after_a_camera_gap():
    text = (PKG / "control" / "line_observer_node.py").read_text(encoding="utf-8")
    keep = text.split("elif mode == 'keep':", 1)[1].split("elif mode in", 1)[0]
    assert "KEEP_MAX_FRAME_GAP_S" in keep and "self._lane_keeper.reset()" in keep


def test_junction_transverse_reports_the_line_distance_in_base_footprint_x():
    # D-507 §5: the stop line is painted at base_link x = 0.30 (the render grid
    # is base_link, X_OFFSET puts the camera ahead of it): the key is that x.
    slope = np.tan(np.radians(25.0))
    keeper = _corner_keeper()
    keeper.update(_render([(HALF - slope * 0.22, slope)], transverse_x=0.30), GROUND, lane_half_width_m=HALF)
    assert keeper.last["reason"] == "junction_transverse"
    assert keeper.last["junction_ahead_m"] == pytest.approx(0.30, abs=0.03)
    assert json.loads(json.dumps(keeper.last, default=float))["junction_ahead_m"] == keeper.last["junction_ahead_m"]


def test_junction_fork_reports_the_diverging_branch_near_end():
    slope = np.tan(np.radians(45.0))
    keeper = _corner_keeper()
    keeper.update(_render([(HALF, 0.0), (0.05 - slope * 0.22, slope)]), GROUND, lane_half_width_m=HALF)
    assert keeper.last["reason"] == "junction_fork"
    branch = max(keeper.last["boundaries"], key=lambda b: b["heading_deg"])
    assert keeper.last["junction_ahead_m"] == pytest.approx(min(p[0] for p in branch["ends_m"]), abs=1e-3)
    assert 0.0 < keeper.last["junction_ahead_m"] < 0.6


def test_no_junction_reason_carries_no_junction_ahead_key():
    keeper = _corner_keeper()
    keeper.update(_render(), GROUND, lane_half_width_m=HALF)  # nothing seen: no_boundary
    assert keeper.last["reason"] == "no_boundary" and "junction_ahead_m" not in keeper.last
    plain = LaneKeeper(camera_x_offset_m=X_OFFSET, smoothing=0.0)
    slope = np.tan(np.radians(25.0))
    plain.update(_render([(HALF - slope * 0.22, slope)], transverse_x=0.30), GROUND, lane_half_width_m=HALF)
    assert "junction_ahead_m" not in plain.last


def test_every_frame_carries_the_junction_ahead_marker():
    # D-507 §5: CORE reads junction_ahead_v to know this build reports junction_ahead_m.
    keeper = _corner_keeper()
    keeper.update(_render(), GROUND, lane_half_width_m=HALF)
    assert keeper.last["junction_ahead_v"] == 1 and "junction_ahead_m" not in keeper.last
    slope = np.tan(np.radians(25.0))
    keeper.update(_render([(HALF - slope * 0.22, slope)], transverse_x=0.30), GROUND, lane_half_width_m=HALF)
    assert keeper.last["junction_ahead_v"] == 1 and "junction_ahead_m" in keeper.last
    assert _keep(_render([(0.0, 0.0)]))[1]["junction_ahead_v"] == 1


def test_keep_debug_carries_bounded_ground_paint_points_without_selecting_a_boundary():
    _, last = _keep(_render([(HALF, 0.0), (-HALF, 0.0)]))
    points = last["paint_points_m"]
    assert last["paint_points_v"] == 1
    assert 8 <= len(points) <= 48
    assert all(len(point) == 2 and 0.10 <= point[0] <= 0.40 for point in points)
    assert any(point[1] > 0.05 for point in points)
    assert any(point[1] < -0.05 for point in points)
    assert len({min(11, int((point[0] - 0.10) / 0.025)) for point in points}) >= 8
    assert all(point == [round(point[0], 3), round(point[1], 3)] for point in points)
    assert json.loads(json.dumps(last))["paint_points_m"] == points
    assert len(json.dumps({"paint_points_v": 1, "paint_points_m": points}).encode()) < 2048
    assert _keep(_render())[1]["paint_points_m"] == []


def test_right_only_fork_reports_the_diverging_branch_near_end():
    # Mirror of the left fork: outward flips, so the branch pick must flip with it.
    slope = np.tan(np.radians(-45.0))
    keeper = _corner_keeper()
    keeper.update(_render([(-HALF, 0.0), (-0.05 - slope * 0.22, slope)]), GROUND, lane_half_width_m=HALF)
    assert keeper.last["reason"] == "junction_fork"
    branch = min(keeper.last["boundaries"], key=lambda b: b["heading_deg"])
    assert keeper.last["junction_ahead_m"] == pytest.approx(min(p[0] for p in branch["ends_m"]), abs=1e-3)
    assert 0.0 < keeper.last["junction_ahead_m"] < 0.6
