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


class Camera:
    """A v4l2 camera whose frame mean grows with exposure like the top camera (2026-10-30: 10000 -> 61, 33000 -> 148)."""

    def __init__(self, exposure=3000, per_unit=0.0045, cap=33000):
        self.exposure, self.per_unit, self.cap, self.writes = exposure, per_unit, cap, []

    def run(self, cmd, **kw):
        if "-C" in cmd:
            return type("R", (), {"stdout": f"exposure_time_absolute: {self.exposure}\n"})()
        self.writes.append(cmd[3:])
        self.exposure = int(cmd[-1].split("=")[1])
        return type("R", (), {"stdout": ""})()

    def frame(self, name="top"):
        return np.full((48, 64), min(255.0, self.exposure * self.per_unit), np.uint8)


def test_a_dim_top_camera_is_exposed_into_the_band_and_a_lit_one_is_left_alone():
    cam = Camera()  # mean 13: the dim room
    report = pf.expose("/dev/video2", cam.frame, run=cam.run, wait=lambda s: None)
    assert report["set"] and report["ok"] and abs(report["mean"] - 140) <= 15
    assert cam.writes[0][:2] == ["-c", "auto_exposure=1"] and len(cam.writes) <= 4
    lit = Camera(exposure=29000)
    assert not pf.expose("/dev/video2", lit.frame, run=lit.run, wait=lambda s: None)["set"] and lit.writes == []


def test_ready_exposes_only_cameras_with_a_device_and_still_refuses_a_dark_room():
    cam = Camera(per_unit=0.0002)  # lights off: even the longest exposure stays dark
    config = {"cameras": {"top": {"url": "u", "device": "/dev/video2"}, "wrist": {"url": "w"}}}
    frames = {"top": cam.frame, "wrist": lambda name="wrist": np.full((48, 64), 140, np.uint8)}
    dark = pf.ready(lambda c: frames[c](), config, run=cam.run, wait=lambda s: None)
    assert cam.exposure == 33000 and len(dark) == 1 and dark[0].startswith("light top:")
