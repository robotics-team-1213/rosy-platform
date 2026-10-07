"""D-507 B9: the 260919 SW bend (~63 deg) is a bend, not a fork, an L-corner or a flip.

Replays the B8 SIM fixture clips (docs/validation/lane-trip-perception-2026-10-07, Gazebo camera
frames with ground-truth poses) through the product keeper with the D-495 SIM keeper settings,
each clip from LaneKeeper.reset(). Open loop: the poses are the old keeper's, so these pin the
per-frame reading, not the closed-loop path (that is the model PC SIM).
"""
import json
import math
from pathlib import Path

import numpy as np
import pytest

from control.sensing.perception.camera_ground import simulation_ground_plane
from control.sensing.perception.lane_keep import LaneKeeper
from control.sensing.perception.lane_keep_junction import _continues, _junction

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
#: width - pinky_pro URDF body half-width 0.0566 - paint half-width 0.0125 = 23.5 mm).
TARGET_MAX_M, TARGET_P90_M = HALF / 2, HALF - 0.0566 - 0.0125


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
        keeper.update(frame, ground, lane_half_width_m=HALF)
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


def test_the_bend_is_followed_not_lost(clips):
    for name in ("south_centre_lost", "premature_corner_left", "bend_flipping", "bend_fork"):
        assert [m["gt"] for b, m in clips[name] if b["target_m"] is None] == [], name


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
    assert _junction("left_only", [], [edge, arc], [], HALF, True, 0.3) is None
    a, b = _line((0.16, 0.09), (0.40, 0.09)), _line((0.16, 0.09), (0.33, 0.26))
    assert _junction("left_only", [], [a, b], [], HALF, True, 0.3) == "junction_fork"
