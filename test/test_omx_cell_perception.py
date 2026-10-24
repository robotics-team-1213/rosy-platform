"""Box centre and yaw from the profile's colour rules, and the start gate that refuses a moved or turned box."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

OMX = Path(__file__).parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    spec = importlib.util.spec_from_file_location("cell_perception", OMX / "cell_perception.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
finally:
    sys.path.remove(str(OMX))

PROFILE = m.load_profile(OMX / "cell-profile.example.json")
HOME = PROFILE["home"]


def top_frame(cx, cy, yaw, side=32):
    """White tray, a mauve-grey box (how the top camera reads the brown box) at (cx, cy) turned by yaw."""
    img = np.full((480, 640, 3), (240, 230, 200), np.uint8)
    corners = cv2.boxPoints(((cx, cy), (side, side), yaw)).astype(np.int32)
    cv2.fillPoly(img, [corners], (110, 95, 115))
    cv2.line(img, (100, 300), (220, 300), (20, 20, 20), 4)  # a black cable below the tray: never the box
    return img


@pytest.mark.parametrize("yaw", [0, 20, 38])
def test_the_top_view_finds_the_box_centre_and_yaw(yaw):
    box = m.top_box(top_frame(150, 230, yaw), PROFILE)
    assert box["found"] and box["cx"] == pytest.approx(150, abs=2) and box["cy"] == pytest.approx(230, abs=2)
    assert m.yaw_gap(box["yaw"], yaw) <= 3


def test_nothing_box_coloured_on_the_tray_is_not_found():
    img = np.full((480, 640, 3), (240, 230, 200), np.uint8)
    assert m.top_box(img, PROFILE) == {"found": False}


def test_the_wrist_view_reports_centre_and_area():
    img = np.full((480, 640, 3), (200, 200, 200), np.uint8)
    cv2.rectangle(img, (250, 120), (450, 300), (30, 90, 200), -1)  # orange-brown in BGR
    box = m.wrist_box(img, PROFILE)
    assert box["found"] and box["cx"] == pytest.approx(350, abs=2) and box["area"] == pytest.approx(201 * 181, rel=0.05)


def test_yaw_gap_treats_a_square_box_as_repeating_every_90_degrees():
    assert m.yaw_gap(2, 88) == pytest.approx(4) and m.yaw_gap(0, 45) == 45


@pytest.mark.parametrize("state, frame, kinds", [
    (HOME, top_frame(134.5, 239.5, 0), []),
    (HOME, top_frame(136.5, 228.5, 0), ["box_moved"]),  # 11 px toward the belt: the jaws caught the box edge (2026-10-25)
    (HOME, top_frame(173, 222, 38), ["box_moved", "box_turned"]),  # the 2026-10-24 miss
    ([HOME[0] + 10, *HOME[1:]], top_frame(134.5, 239.5, 0), ["arm_not_home"]),
    (HOME, np.full((480, 640, 3), (240, 230, 200), np.uint8), ["box_not_seen"]),
])
def test_the_start_gate_names_what_is_not_where_the_taught_chunks_begin(state, frame, kinds):
    result = m.start_check(state, m.top_box(frame, PROFILE), PROFILE)
    assert [i["kind"] for i in result["issues"]] == kinds and result["ok"] is (not kinds)


def test_a_profile_without_its_parts_is_refused(tmp_path):
    bad = json.loads((OMX / "cell-profile.example.json").read_text())
    del bad["reference"]
    path = tmp_path / "p.json"
    path.write_text(json.dumps(bad))
    with pytest.raises(SystemExit, match="reference"):
        m.load_profile(path)
