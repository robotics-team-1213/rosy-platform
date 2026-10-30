"""cell_site_track: a moved robot's tray polygon and place point follow it; a frame without it is refused."""
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
import cell_site_track as st  # noqa: E402

PX = lambda p: (320 + p[0] * 1000 * 1.1, 240 + (p[1] - 0.2) * 1000 * 1.1)  # noqa: E731  1.1 px/mm, not mirrored
POLY = [[150, 180], [250, 180], [250, 250], [150, 250]]


def robot(dx=0.0, dy=0.0, turn=0.0):
    """A textured 'robot' around POLY on a plain floor, moved by (dx, dy) px and turned about the polygon centre."""
    rng = np.random.default_rng(3)
    img = np.full((480, 640, 3), 120, np.uint8)
    body = np.zeros((480, 640, 3), np.uint8)
    for _ in range(60):
        x, y = int(rng.integers(110, 290)), int(rng.integers(120, 290))
        cv2.rectangle(body, (x, y), (x + int(rng.integers(4, 20)), y + int(rng.integers(4, 20))), [int(v) for v in rng.integers(0, 255, 3)], -1)
    inside = np.zeros((480, 640), np.uint8)
    cv2.rectangle(inside, (110, 120), (300, 300), 255, -1)
    M = cv2.getRotationMatrix2D((200, 215), turn, 1.0)
    M[:, 2] += (dx, dy)
    body, inside = cv2.warpAffine(body, M, (640, 480)), cv2.warpAffine(inside, M, (640, 480))
    img[inside > 0] = body[inside > 0]
    return img


def test_a_moved_and_turned_robot_moves_its_polygon_and_place():
    ref, cur = robot(), robot(dx=30, dy=40, turn=10)
    m = st.motion(ref, cur, POLY)
    assert m["ok"] and m["turn_deg"] == pytest.approx(-10, abs=1.0)  # getRotationMatrix2D turns counter-clockwise
    assert st.moved_px(m["M"], [[200, 215]])[0] == pytest.approx([230, 255], abs=1.5)


def test_follow_writes_the_moved_site_and_a_blank_frame_is_refused(tmp_path):
    cv2.imwrite(str(tmp_path / "ref.jpg"), robot())
    config = {"params": None, "sites": {"pinky": {"yaw_deg": -67.8, "place": [0.0, 0.2], "start": [0.0, 0.2], "track": {
        "reference": "ref.jpg", "surface_px": POLY, "place_px": [320, 240], "yaw_deg": -67.8}}}}
    moved, report = st.follow(config, "pinky", robot(dx=22), PX, tmp_path)
    assert report["tracked"] and moved["sites"]["pinky"]["place"] == pytest.approx([0.020, 0.2], abs=0.0015)  # 22 px = 20 mm
    assert moved["sites"]["pinky"]["surface_px"][0] == pytest.approx([172, 180], abs=1.5)
    assert moved["sites"]["pinky"]["yaw_deg"] == pytest.approx(-67.8, abs=1.0)
    same, report = st.follow(config, "pinky", np.full((480, 640, 3), 120, np.uint8), PX, tmp_path)
    assert not report["tracked"] and "not found" in report["why"] and same is config


def test_raw_at_inverts_the_map():
    assert st.raw_at(PX, PX((0.031, 0.177))) == pytest.approx((0.031, 0.177), abs=1e-6)
