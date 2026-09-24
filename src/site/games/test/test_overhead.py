"""Ceiling camera. Skips when OpenCV is not installed."""

from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from games.host.overhead import OverheadCamera, detect_ball
from games.host.robots import load_match

MATCH = Path(__file__).resolve().parents[1] / "config" / "match.yaml"


def _dictionary():
    return cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)


def _marker(marker_id: int, size: int = 48):
    dictionary = _dictionary()
    return (getattr(cv2.aruco, "generateImageMarker", None) or cv2.aruco.drawMarker)(dictionary, marker_id, size)


def _stamp(canvas, marker_id: int, x: int, y: int, size: int = 48):
    tile = _marker(marker_id, size)
    canvas[y : y + size, x : x + size] = cv2.cvtColor(tile, cv2.COLOR_GRAY2BGR)


def _pitch_frame(*, goals: bool = False, mouth: bool = False):
    canvas = np.full((240, 400, 3), 30, dtype=np.uint8)
    _stamp(canvas, 10, 16, 16)
    _stamp(canvas, 11, 336, 16)
    _stamp(canvas, 12, 336, 176)
    _stamp(canvas, 13, 16, 176)
    _stamp(canvas, 1, 80, 96)
    _stamp(canvas, 2, 260, 96)
    if goals:
        _stamp(canvas, 20, 16, 96)
        _stamp(canvas, 21, 336, 96)
    if mouth:
        canvas[96:144, 8:28] = (0, 220, 0)
        canvas[96:144, 372:392] = (0, 220, 0)
    cv2.circle(canvas, (200, 120), 12, (0, 140, 255), -1)
    return canvas


def test_orange_blob_is_the_ball():
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    cv2.circle(frame, (80, 60), 10, (0, 140, 255), -1)
    uv = detect_ball(frame, (5, 80, 80), (25, 255, 255))
    assert uv is not None
    assert abs(uv[0] - 80) < 8
    assert abs(uv[1] - 60) < 8


def test_observe_frame_finds_ball_and_both_robots():
    setup = load_match(MATCH)
    cam = OverheadCamera(setup, capture=object())
    obs = cam.observe_frame(_pitch_frame())
    assert not obs.lost_ball
    assert obs.ball is not None
    assert abs(obs.ball.x) < 0.35
    assert abs(obs.ball.y) < 0.25
    assert setup.field.home_id in obs.robots
    assert setup.field.away_id in obs.robots
    assert not obs.lost_robots


def test_missing_corners_do_not_invent_a_pose():
    setup = load_match(MATCH)
    cam = OverheadCamera(setup, capture=object())
    blank = np.full((240, 400, 3), 30, dtype=np.uint8)
    obs = cam.observe_frame(blank)
    assert obs.lost_ball
    assert obs.ball is None
    assert obs.lost_robots == frozenset({setup.field.home_id, setup.field.away_id})


def test_goal_markers_update_the_field_metre_mouths():
    setup = load_match(MATCH)
    cam = OverheadCamera(setup, capture=object())
    obs = cam.observe_frame(_pitch_frame(goals=True))
    assert obs.home_goal is not None
    assert obs.away_goal is not None
    home_x = sum(p[0] for p in obs.home_goal) / 4
    away_x = sum(p[0] for p in obs.away_goal) / 4
    assert home_x < 0
    assert away_x > 0
    assert setup.field.in_home_goal(*obs.home_goal[0]) or home_x <= -setup.field.length_m / 4


def test_missing_both_goal_markers_keeps_field_end_geometry():
    setup = load_match(MATCH)
    cam = OverheadCamera(setup, capture=object())
    obs = cam.observe_frame(_pitch_frame())
    assert obs.home_goal is None
    assert obs.away_goal is None


def test_hsv_mouth_can_stand_in_when_markers_are_hidden(tmp_path):
    text = MATCH.read_text(encoding="utf-8")
    text += "\ngoals:\n  hsv_low: [40, 80, 80]\n  hsv_high: [80, 255, 255]\n"
    path = tmp_path / "match.yaml"
    path.write_text(text, encoding="utf-8")
    setup = load_match(path)
    cam = OverheadCamera(setup, capture=object())
    obs = cam.observe_frame(_pitch_frame(mouth=True))
    assert obs.home_goal is not None
    assert obs.away_goal is not None
    assert sum(p[0] for p in obs.home_goal) / 4 < 0
    assert sum(p[0] for p in obs.away_goal) / 4 > 0
