"""D-507 B9: the 260919 SW bend (~63 deg) is a bend, not a fork, an L-corner or a flip.

Replays the B8 SIM fixture clips (docs/validation/lane-trip-perception-2026-10-07, Gazebo camera
frames with ground-truth poses) through the product keeper with the D-495 SIM keeper settings,
each clip from LaneKeeper.reset(). Open loop: the poses are the old keeper's, so these pin the
per-frame reading, not the closed-loop path (that is the model PC SIM). The bend rules run only
with the keeper's bend_expected input (route context, default off); off, the keeper must decide
exactly as main on the real label frames (B9 device review: 0 of 29 HOLD -> drive frames right).
"""
import glob
import json
import math
import os
from pathlib import Path

import numpy as np
import pytest

from control.sensing.perception.camera_ground import simulation_ground_plane
from control.sensing.perception.lane_keep import LaneKeeper
from control.sensing.perception.lane_keep_junction import _continues, _junction
from control.sensing.perception.lane_keep_lines import PAINT_HALF_WIDTH_M
from test_lane_keep import GROUND, HALF as NOMINAL_HALF, PROFILE, X, Y, X_OFFSET, _render
import test_lane_corner as corner_world

REPO = Path(__file__).resolve().parents[3]
FIXTURE = REPO / "docs" / "validation" / "lane-trip-perception-2026-10-07" / "fixtures" / "b8_keeper_clips.npz"
CAMERA_X = 0.03317  # Gazebo sensor pose x (payload line_follow.yaml camera_x_offset_m)
HALF = 0.0925  # 260919 STL lane line centres 185 mm apart
#: Ground-truth lane centre (B8 result.md, world STL PaintMap): the south lane y -0.511 bends left
#: where its outer line (y -0.6035) turns at x -0.62; the spoke heading is the mean of the keeper's
#: diagonal heading + gt yaw over the fixture frames (63.5 deg, result.md "about 63").
CENTRE_Y, OUTER_CORNER, SPOKE = -0.511, (-0.62, -0.6035), math.radians(63.5)
#: Pursuit targets vs the true centre line -- the south lane's (straight on, its pursuit point may
#: lie past the vertex while the bend is further than the bend lookahead) or the spoke's: every
#: one in the inner half of the lane, and 90 % within the body's lateral play in the lane (half
#: width - pinky_pro URDF body half-width 0.0566 - paint half-width = 23.4 mm).
TARGET_MAX_M, TARGET_P90_M = HALF / 2, HALF - 0.0566 - PAINT_HALF_WIDTH_M


def _ground():
    return simulation_ground_plane(source="GAZEBO", simulation_enabled=True, use_sim_time=True, width_px=320,
                                   height_px=240, height_m=0.06343, pitch_rad=math.radians(8.0),
                                   hfov_rad=2 * math.atan(160 / 281.6), max_range_m=0.6)


def _vertex():
    """World point where the centre line turns into the spoke (outer line moved a half-width in)."""
    c, s = math.cos(SPOKE), math.sin(SPOKE)
    x0, y0 = OUTER_CORNER[0] - HALF * s, OUTER_CORNER[1] + HALF * c
    t = (CENTRE_Y - y0) / s
    return x0 + t * c, CENTRE_Y


def _off_centre(gt, target):
    """Distance of the keeper's target (base_link) from the ground-truth centre lines: the
    south lane's, or the spoke's from the vertex on."""
    c, s = math.cos(gt[2]), math.sin(gt[2])
    wx, wy = gt[0] + target[0] * c - target[1] * s, gt[1] + target[0] * s + target[1] * c
    vx, vy = _vertex()
    t = max(0.0, (wx - vx) * math.cos(SPOKE) + (wy - vy) * math.sin(SPOKE))
    return min(abs(wy - vy), math.hypot(wx - vx - t * math.cos(SPOKE), wy - vy - t * math.sin(SPOKE)))


@pytest.fixture(scope="module")
def clips():
    data = np.load(FIXTURE)
    meta = json.loads(str(data["meta"]))
    ground, out = _ground(), {}
    for frame, m in zip(data["frames"], meta):
        if m["clip"] not in out:
            out[m["clip"]] = (LaneKeeper(camera_x_offset_m=CAMERA_X, corner_turning=True), [])
        keeper, rows = out[m["clip"]]
        keeper.update(frame, ground, lane_half_width_m=HALF, bend_expected=True)
        rows.append((dict(keeper.last), m))
    return {name: rows for name, (_, rows) in out.items()}


def test_the_fixture_is_the_b8_set(clips):
    assert {name: len(rows) for name, rows in clips.items()} == {
        "south_centre_straight": 13, "south_centre_lost": 11, "corner_exit_offset": 13,
        "premature_corner_left": 13, "bend_flipping": 21, "bend_fork": 11, "spoke_transverse": 7}


def test_one_connected_bend_line_is_never_a_fork(clips):
    assert [(n, m["gt"]) for n, rows in clips.items() for b, m in rows if b.get("reason") == "junction_fork"] == []


def test_the_bend_never_flips(clips):
    assert [(n, m["gt"]) for n, rows in clips.items() for b, m in rows if b.get("reason") == "flipping"] == []


def test_the_bend_diagonal_is_not_an_l_corner(clips):
    assert [(n, b["strategy"]) for n, rows in clips.items() for b, _ in rows
            if b["strategy"].startswith("corner")] == []


def test_the_bend_is_followed_from_its_entry(clips):
    for name in ("bend_flipping", "bend_fork"):
        assert [m["gt"] for b, m in clips[name] if b["target_m"] is None] == [], name
        assert any(b["strategy"] == "bend_left" for b, _ in clips[name]), name


def test_before_the_bend_the_lane_side_boundary_is_needed_and_the_target_stops_short(clips):
    # While the bend's centre line meets the path beyond CORNER_LOOKAHEAD_M the keeper keeps the
    # lane's own target, no further ahead than the bend line's crossing less a half-width; with
    # no lane-side boundary it holds (as main), never driving straight at the bend line.
    for name in ("south_centre_lost", "premature_corner_left"):
        for b, m in clips[name]:
            bend = [c for c in b["candidates"] if c.get("reason") == "bend"]
            if b["strategy"] == "bend_ahead":
                (x0, y0), (x1, y1) = sorted(map(tuple, bend[0]["ends_m"]))
                cross = x0 + (x1 - x0) * (0.0 - y0) / (y1 - y0)
                assert b["target_m"][0] <= cross - HALF + 1e-3, (name, m["gt"])
            if bend and not [c for c in b["candidates"] if c.get("rejected") is False and c.get("reason") is None]:
                assert b["target_m"] is None and b["reason"] in ("no_boundary", "junction_transverse"), (name, m["gt"])
    assert any(b["strategy"] == "bend_ahead" for b, _ in clips["south_centre_lost"])
    # At 66 deg (yaw -3.5) the outer diagonal beside the inner edge bending out is, in one frame,
    # a junction mouth too: it fails closed (route context decides, B11).
    assert [b["reason"] for b, _ in clips["premature_corner_left"] if b["target_m"] is None] == [
        "junction_transverse", "no_boundary", "no_boundary"]


def test_straight_lane_clips_are_unchanged(clips):
    for name in ("south_centre_straight", "corner_exit_offset"):
        assert {b["strategy"] for b, _ in clips[name]} == {"both"}, name


def test_the_real_junction_mouth_still_holds(clips):
    event = [b for b, m in clips["spoke_transverse"] if m["event"]]
    assert [b["reason"] for b in event] == ["junction_transverse"]


def test_targets_lie_on_the_true_centre_line(clips):
    offs = [(round(_off_centre(m["gt"], b["target_m"]), 3), name, m["gt"], b["strategy"])
            for name, rows in clips.items() if name != "spoke_transverse"  # at the roundabout
            for b, m in rows if b["target_m"] is not None]
    assert len(offs) > 60
    assert [o for o in offs if o[0] > TARGET_MAX_M] == []
    assert np.percentile([o[0] for o in offs], 90) <= TARGET_P90_M


def _line(near, far):
    return {"ends_m": [list(near), list(far)], "y_at_side_x_m": 0.05, "length_m": math.dist(near, far),
            "heading_deg": math.degrees(math.atan2(far[1] - near[1], far[0] - near[0]))}


def test_end_to_start_continuity():
    # B8 bend_fork: spoke outer edge (61 deg) then the roundabout arc (-9 deg), 0.035-0.044 m apart.
    edge, arc = _line((0.156, -0.073), (0.283, 0.156)), _line((0.309, 0.128), (0.432, 0.109))
    assert _continues(edge, arc) and not _continues(arc, edge)
    # Two branches leaving the same point (a fork) start together: no continuity.
    a, b = _line((0.16, 0.09), (0.40, 0.09)), _line((0.16, 0.09), (0.33, 0.26))
    assert not _continues(a, b) and not _continues(b, a)


def test_connected_pieces_are_not_fork_branches_but_split_branches_are():
    edge, arc = _line((0.156, -0.073), (0.283, 0.156)), _line((0.309, 0.128), (0.432, 0.109))
    assert _junction("left_only", [], [edge, arc], [], HALF, True, 0.3, continuity=True) == (None, None)
    assert _junction("left_only", [], [edge, arc], [], HALF, True, 0.3)[0] == "junction_fork"  # gate off: as main
    a, b = _line((0.16, 0.09), (0.40, 0.09)), _line((0.16, 0.09), (0.33, 0.26))
    assert _junction("left_only", [], [a, b], [], HALF, True, 0.3, continuity=True)[0] == "junction_fork"


def _diagonal(image, x0, slope, y_lo, y_hi):
    """Tape x = x0 + (y + 0.11) / slope for y_lo < y < y_hi onto a nominal _render image."""
    image[np.isfinite(X) & (np.abs(X - (x0 + (Y + 0.11) / slope)) <= 0.015) & (Y > y_lo) & (Y < y_hi)] = 195
    return image


def _corner_keep(image):
    keeper = LaneKeeper(camera_x_offset_m=X_OFFSET, smoothing=0.0, corner_turning=True)
    keeper.update(image, GROUND, lane_half_width_m=NOMINAL_HALF, bend_expected=True)
    return keeper.last


@pytest.mark.parametrize("x0", [0.10, 0.15])
def test_a_lane_spanning_mark_beside_a_lane_line_running_on_is_no_bend(x0):
    # Real 124745Z frame 94: a square mark projected at ~60 deg across the lane, here reaching
    # past the left edge, with the right lane line running on past it: a stop line, not a bend.
    last = _corner_keep(_diagonal(_render([(-NOMINAL_HALF, 0.0)]), x0, 1.73, -0.11, 0.13))
    assert not last["strategy"].startswith("bend")
    assert not [c for c in last["candidates"] if c.get("reason") == "bend"]


def test_a_junction_mouth_with_a_70_degree_line_across_still_holds():
    # A lone left boundary bending out (+25 deg) and a 70 deg line across ahead: the lane goes on
    # past the line on the open side, so it is no bend and the junction mouth still holds.
    slope = np.tan(np.radians(25.0))
    image = _diagonal(_render([(NOMINAL_HALF - slope * 0.22, slope)]), 0.30, np.tan(np.radians(70.0)), -0.15, 0.25)
    last = _corner_keep(image)
    assert last["reason"] == "junction_transverse"


@pytest.mark.parametrize("cut", [0.30, 0.25, 0.22])
def test_a_junction_mouth_whose_boundary_ends_before_the_line_still_holds(cut):
    # The boundary bending out stops short of the 70 deg line across: the line could start a
    # bend, but junction rules are judged first and see it as the transverse mark it also is.
    slope = np.tan(np.radians(25.0))
    image = _render([])
    band = np.isfinite(X) & (X <= cut) & (np.abs(Y - (NOMINAL_HALF - slope * 0.22 + slope * X)) <= 0.015)
    image[band] = 195
    last = _corner_keep(_diagonal(image, 0.30, np.tan(np.radians(70.0)), -0.15, 0.25))
    assert last["reason"] == "junction_transverse"


def test_the_plain_keeper_ignores_a_bend_without_the_route_expecting_one():
    # The same lost-boundary SIM frames without bend_expected: no bend reading at all.
    data = np.load(FIXTURE)
    keeper = LaneKeeper(camera_x_offset_m=CAMERA_X, corner_turning=True)
    for frame, m in zip(data["frames"], json.loads(str(data["meta"]))):
        if m["clip"] == "south_centre_lost":
            keeper.update(frame, _ground(), lane_half_width_m=HALF)
            assert not keeper.last["strategy"].startswith("bend")
            assert not [c for c in keeper.last["candidates"] if c.get("reason") == "bend"]


#: Real label frames (gitignored data/perception, D-226; ROSY_PERCEPTION_LABELS overrides) and
#: main's decision on each (fixtures/b9_real_label_frames_main.json, main 6945440e5).
LABELS = Path(os.environ.get("ROSY_PERCEPTION_LABELS", REPO / "data" / "perception" / "labels"))
MAIN_DECISIONS = json.loads((Path(__file__).parent / "fixtures" / "b9_real_label_frames_main.json")
                            .read_text(encoding="utf-8"))["decisions"]
#: B9 device review: frames that drove at the wall baseboard, the paint or across a junction hold.
MUST_HOLD = ([f"20260930T124745Z/{i:06d}.jpg" for i in [*range(35, 40), *range(63, 68)]]
             + [f"20260930T133221Z/{i:06d}.jpg" for i in [256, *range(267, 285)]])


def _real_decisions(bend_expected):
    cv2 = pytest.importorskip("cv2")
    sessions = sorted(glob.glob(str(LABELS / "*" / "frames")))
    if len(sessions) < 2:
        pytest.skip(f"real label frames not present under {LABELS} (gitignored data, D-226)")
    out = {}
    for frames in sessions:
        keeper = LaneKeeper(camera_x_offset_m=float(PROFILE["x_offset_m"]), corner_turning=True)
        name = Path(frames).parent.name.split("_")[0]
        for path in sorted(glob.glob(os.path.join(frames, "*.jpg"))):
            keeper.update(cv2.resize(cv2.imread(path), (320, 240)), GROUND, lane_half_width_m=NOMINAL_HALF,
                          bend_expected=bend_expected)
            last = keeper.last
            out[f"{name}/{Path(path).name}"] = [last["strategy"], last.get("reason"), last.get("error"),
                                                last.get("target_m"), last.get("junction_ahead_m")]
    return out


def test_real_frames_without_a_bend_expected_decide_as_main():
    got = _real_decisions(False)
    assert len(got) == len(MAIN_DECISIONS) == 434
    assert [k for k in MAIN_DECISIONS if got[k] != MAIN_DECISIONS[k]] == []


def test_real_frames_the_review_rejected_hold_even_with_a_bend_expected():
    got = _real_decisions(True)
    assert [(k, got[k][:2]) for k in MUST_HOLD if got[k][3] is not None] == []
    assert [k for k in MAIN_DECISIONS if MAIN_DECISIONS[k][3] is None and got[k][3] is not None] == []
    # Re-review: a bend line's frames (248-249) must not delay the side flip of the 46 deg line whose
    # near end sits on the path (250-254) -- that drove full left at the left band.
    assert [(k, got[k][:3]) for k in (f"20260930T133221Z/{i:06d}.jpg" for i in range(250, 255))
            if got[k][2] is not None and got[k][2] < -0.5] == []


@pytest.mark.parametrize("bend_expected", [False, True])
@pytest.mark.parametrize("side, yaw_deg", [(s, y) for s in ("LEFT", "RIGHT") for y in (-18, -12, 0, 12, 18)])
def test_a_yawed_l_corner_is_turned_or_held_never_driven_across(side, yaw_deg, bend_expected):
    # Closed loop (test_lane_corner world, CORE command law) from 0.30 m before the corner line:
    # the keeper either completes the turn into the new lane or holds where it starts (yawed
    # toward the open side the corner line is not read: fail closed), whether or not a bend is
    # expected there. It never drives on across the paint.
    sign = 1.0 if side == "LEFT" else -1.0
    keeper = LaneKeeper(camera_x_offset_m=corner_world.CAM_X, corner_turning=True)
    start = (corner_world.X_T - 0.30, 0.0, math.radians(yaw_deg))
    pose, rects = start, corner_world.l_corner(side)
    for _ in range(150):
        obs = keeper.update(corner_world.render(pose, rects), corner_world.GROUND,
                            lane_half_width_m=corner_world.H, bend_expected=bend_expected)
        pose = corner_world._step(pose, obs)
        assert pose[0] < corner_world.X_T, "drove past the corner line"
    turned = (abs(pose[2] - sign * math.pi / 2) < math.radians(20) and sign * pose[1] > 0.15
              and abs(pose[0] - (corner_world.X_T - corner_world.H)) < corner_world.H)
    assert turned or pose == start
    assert turned == (sign * yaw_deg <= 0)
