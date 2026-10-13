"""G-16 (sim2real_gaps.yaml): the keep-mode boundary slope that D-468 extrapolates to the body.

The camera sees the paint only from ~0.18 m ahead and the receiver extends each boundary to the
body rear, so slope error dominates. Two biases tilted the fit: the frame's side edges cut the
outer part of the near paint, and a crosswalk's blob removal band erased one side of the lane
line. The fit now uses whole visible cross-sections outside the crosswalk, and uncertainty_m
carries the fit's slope error.
"""
import math
from pathlib import Path

import cv2
import numpy as np
import pytest

from control.sensing.perception.camera_ground import simulation_ground_plane
from control.sensing.perception.crosswalk_stripes import crosswalk_extent
from control.sensing.perception.lane_bev import BEV_CELL_M, BirdsEye
from control.sensing.perception.lane_containment import (
    PAINT_HALF_WIDTH_M, RECEIVER_EXTRAPOLATION_M, SLOPE_SIGMAS, containment_payload)
from control.sensing.perception.lane_keep import FIT_STRIDE, LaneKeeper
from control.sensing.perception.lane_keep_lines import extract_lines, fit_cells

REPO = Path(__file__).resolve().parents[3]
EVIDENCE = REPO / "docs" / "validation" / "d476-gazebo-rev1-2026-10-07" / "evidence" / "runs"
CAMERA_X = 0.03317  # Gazebo sensor pose x (line_follow.yaml camera_x_offset_m)
LANE_Y = 0.0925  # 260919 STL lane line centres
FRONT, REAR, HALF = 0.042, -0.076, 0.0566  # pinky_pro URDF footprint
#: Fitted heading of straight synthetic paint after the fix: within a tenth of a degree.
HEADING_TOLERANCE_DEG = 0.1


def gazebo_ground():
    return simulation_ground_plane(source="GAZEBO", simulation_enabled=True, use_sim_time=True, width_px=320,
                                   height_px=240, height_m=0.06343, pitch_rad=math.radians(8.0),
                                   hfov_rad=2*math.atan(160/281.6), max_range_m=0.6)


VIEW = BirdsEye(gazebo_ground(), 320, 240, CAMERA_X)
FIT_HALF = PAINT_HALF_WIDTH_M + FIT_STRIDE*BEV_CELL_M


def lines_of(lit, seed, fixed):
    """extract_lines on the keeper's thinned grid of ``lit`` (BEV bool), with or without the G-16 fit."""
    grid = (lit & VIEW.observable).astype(np.uint8)
    crosswalk = crosswalk_extent(grid, VIEW.x[:, 0], VIEW.y[0, :])
    thin = grid[::FIT_STRIDE, ::FIT_STRIDE].astype(bool)
    points = np.stack([VIEW.x[::FIT_STRIDE, ::FIT_STRIDE][thin], VIEW.y[::FIT_STRIDE, ::FIT_STRIDE][thin]], axis=1)

    kwargs = dict(usable=fit_cells(VIEW.seen, crosswalk), paint_half_m=FIT_HALF) if fixed else {}
    lines, _ = extract_lines(points, np.random.default_rng(seed), **kwargs)
    return lines


def headings_deg(lines):
    return [math.degrees(math.atan2(e["direction"][1], e["direction"][0])) for e in lines]


TAPES = (np.abs(VIEW.y-LANE_Y) <= PAINT_HALF_WIDTH_M) | (np.abs(VIEW.y+LANE_Y) <= PAINT_HALF_WIDTH_M)


def test_frame_edge_clipping_tilts_the_old_fit_and_not_the_whole_stroke_fit():
    # Straight lane lines: below ~0.23 m ahead the 59.2 deg view cuts their outer part.
    before = headings_deg(lines_of(TAPES, 0, fixed=False))
    after = lines_of(TAPES, 0, fixed=True)
    assert len(before) == len(after) == 2
    assert min(abs(h) for h in before) > 0.3  # near ends lean inward
    assert max(abs(h) for h in headings_deg(after)) <= HEADING_TOLERANCE_DEG
    assert all(e["slope_sd"] is not None and e["slope_sd"] > 0 for e in after)


def test_crosswalk_removal_no_longer_tilts_the_lane_lines():
    # 260919 crosswalk: four 25 mm bars at 40 mm pitch between the lane lines, ahead.
    bars = np.zeros_like(TAPES)
    for y in (-.06, -.02, .02, .06):
        bars |= (np.abs(VIEW.y-y) <= PAINT_HALF_WIDTH_M) & (VIEW.x >= .33) & (VIEW.x <= .45)
    worst_before = worst_after = 0.
    for seed in range(6):
        worst_before = max(worst_before, *map(abs, headings_deg(lines_of(TAPES | bars, seed, fixed=False))))
        after = lines_of(TAPES | bars, seed, fixed=True)
        assert len(after) == 2
        worst_after = max(worst_after, *map(abs, headings_deg(after)))
    assert worst_before > 3.
    assert worst_after <= HEADING_TOLERANCE_DEG


def test_without_usable_the_fit_and_entries_are_as_before():
    lines = lines_of(TAPES, 0, fixed=False)
    assert all("slope_sd" not in e for e in lines)


def test_too_little_whole_paint_keeps_the_found_axis_and_states_no_error():
    # Nothing usable: no whole cross-section, so the steering axis must stay the found piece's.
    points = np.stack([VIEW.x[::FIT_STRIDE, ::FIT_STRIDE][TAPES[::FIT_STRIDE, ::FIT_STRIDE] & VIEW.observable[::FIT_STRIDE, ::FIT_STRIDE]],
                       VIEW.y[::FIT_STRIDE, ::FIT_STRIDE][TAPES[::FIT_STRIDE, ::FIT_STRIDE] & VIEW.observable[::FIT_STRIDE, ::FIT_STRIDE]]], axis=1)
    plain, _ = extract_lines(points, np.random.default_rng(0))
    blind, _ = extract_lines(points, np.random.default_rng(0), usable=lambda xy: np.zeros(len(xy), bool), paint_half_m=FIT_HALF)
    assert len(plain) == len(blind) == 2
    for a, b in zip(plain, blind):
        assert np.array_equal(a["centre"], b["centre"]) and np.array_equal(a["direction"], b["direction"])
        assert a["along"] == b["along"]
        assert b["slope_sd"] is None and b["offset_sd"] is None


def keeper(slope_sd, length=.15, far=.33, offset_sd=0.):
    return {"boundaries": [dict(selected=True, side=side, slope_sd=slope_sd, offset_sd=offset_sd,
                                ends_m=[[far-length, y], [far, y]])
                           for side, y in (("left", LANE_Y), ("right", -LANE_Y))]}


def uncertainty(k):
    return containment_payload(k, gazebo_ground(), stamp=1., source="GAZEBO", camera_x=CAMERA_X)["uncertainty_m"]


def test_uncertainty_adds_the_fit_error_over_the_receiver_lever():
    projection = uncertainty(keeper(0.))
    assert uncertainty(keeper(.01)) == pytest.approx(projection+SLOPE_SIGMAS*.01*(.15+RECEIVER_EXTRAPOLATION_M))
    assert uncertainty(keeper(.01, offset_sd=.002)) == pytest.approx(
        projection+SLOPE_SIGMAS*(.01*(.15+RECEIVER_EXTRAPOLATION_M)+.002))
    # Larger slope error states more; the slope term grows with the lever (support + extrapolation).
    assert uncertainty(keeper(.02)) > uncertainty(keeper(.01)) > projection
    term = {length: uncertainty(keeper(.01, length, .43))-uncertainty(keeper(0., length, .43)) for length in (.15, .25)}
    assert term[.25] > term[.15]


@pytest.mark.parametrize("bad", [None, float("nan"), -1.])
def test_a_boundary_without_a_stated_fit_error_leaves_uncertainty_unknown(bad):
    assert uncertainty(keeper(bad)) is None
    assert uncertainty(keeper(0., offset_sd=bad)) is None
    for key in ("slope_sd", "offset_sd"):
        k = keeper(0.)
        del k["boundaries"][0][key]
        assert uncertainty(k) is None


def test_keeper_and_containment_share_one_paint_half_width():
    from control.sensing.perception import lane_containment, lane_keep_lines
    assert lane_containment.PAINT_HALF_WIDTH_M is lane_keep_lines.PAINT_HALF_WIDTH_M
    node = (REPO / "middleware" / "perception" / "control" / "line_observer_node.py").read_text(encoding="utf-8")
    # The node hands its validated read-only lane_paint_half_width_m to the keeper too.
    assert "paint_half_width_m=self._paint_half_width_m)" in node.split("LaneKeeper(", 1)[1].split(")\n", 1)[0] + ")"
    with pytest.raises(ValueError):
        LaneKeeper(paint_half_width_m=-.001)


def margin(boundaries):
    """lane_return.Corridor.margin for the URDF body (g16_probe.py)."""
    e = {b["side"]: (b["slope"], b["intercept_m"]) for b in boundaries}
    (ls, li), (rs, ri) = e["left"], e["right"]
    return min(min((ls*x+li-HALF)/math.hypot(1, ls), (-HALF-(rs*x+ri))/math.hypot(1, rs)) for x in (FRONT, REAR))


#: STL margin at both captures (result.md, G-16 table: 0.0234 m; the robot sits mid-lane).
STL_MARGIN_M = 0.0234
#: The replayed margin must be this close to the STL one (was -0.0075 m at C, 0.0104 north).
MARGIN_TOLERANCE_M = 0.003


@pytest.mark.parametrize("frame", ["g16_C_frame0.png", "g16_north_frame0.png"])
def test_g16_frames_replay_to_the_stl_margin_inside_the_stated_uncertainty(frame):
    k = LaneKeeper(camera_x_offset_m=CAMERA_X, corner_turning=True)
    g = gazebo_ground()
    assert k.update(cv2.imread(str(EVIDENCE/frame)), g) is not None
    payload = containment_payload(k.last, g, stamp=1., source="GAZEBO", camera_x=CAMERA_X)
    assert len(payload["boundaries"]) == 2
    raw = margin(payload["boundaries"])
    assert raw == pytest.approx(STL_MARGIN_M, abs=MARGIN_TOLERANCE_M)
    # The stated uncertainty covers what is left, and the corridor it erodes stays inside the paint.
    assert abs(raw-STL_MARGIN_M) <= payload["uncertainty_m"]
    assert raw-payload["uncertainty_m"] <= STL_MARGIN_M
