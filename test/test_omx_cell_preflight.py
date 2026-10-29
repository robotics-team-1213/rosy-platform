"""cell_preflight: a moved top camera, a stale camera channel or another arm session fail the check before motion."""
import json
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_preflight as pf  # noqa: E402


def scene():
    rng = np.random.default_rng(1)
    img = (rng.random((480, 640)) * 60 + 90).astype(np.uint8)
    for k in range(40):
        x, y = rng.integers(20, 600), rng.integers(20, 440)
        cv2.rectangle(img, (int(x), int(y)), (int(x) + 25, int(y) + 15), int(rng.integers(0, 255)), -1)
    return img


def test_a_rotated_and_shifted_camera_is_measured_and_a_still_one_is_not():
    ref = scene()
    assert pf.camera_shift_px(ref, ref)["max_px"] < 1
    M = cv2.getRotationMatrix2D((320, 240), 7, 1.05)
    M[:, 2] += (20, 30)  # 2026-10-28: about 7 degrees, 5 % and 20-45 px
    moved = cv2.warpAffine(ref, M, (640, 480))
    assert pf.camera_shift_px(ref, moved)["max_px"] > 20


def test_checks_fail_on_a_stale_camera_a_moved_view_and_another_session(tmp_path):
    ref = scene()
    cv2.imwrite(str(tmp_path / "ref.jpg"), ref)
    shifted = cv2.warpAffine(ref, np.float32([[1, 0, 25], [0, 1, 30]]), (640, 480))
    pages = {"/state.json": json.dumps({"top": {"fresh": True}, "front": {"fresh": False}}).encode(),
             "/frame/top.jpg": cv2.imencode(".jpg", shifted)[1].tobytes()}
    config = {"episodes": {"cameras": {"top": "u", "front": "u"}}, "preflight": {"reference_top": str(tmp_path / "ref.jpg")}}

    class Ran:
        stdout = "1\n"

    rows = {name: ok for name, ok, _ in pf.checks(config, "http://v", 6, fetch=lambda url: pages[url[len("http://v"):]],
                                                    run=lambda *a, **k: Ran())}
    assert rows == {"camera top": True, "camera front": False, "light top": True, "top camera pose": False,
                    "other arm session": False}


def test_a_dark_frame_says_the_lights_are_off_and_a_lit_one_passes():
    rows = pf.lights({"top": np.full((480, 640), 1, np.uint8), "wrist": scene(), "front": None})
    assert [ok for _, ok, _ in rows] == [False, True, False]
    assert "lights are off" in rows[0][2] and rows[2][2] == "no frame"
