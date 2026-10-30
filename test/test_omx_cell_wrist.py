"""cell_wrist: the wrist view's shift from a reference, through a per-arm J, corrects the pick before the descent;
anything the view cannot vouch for is refused (no descent)."""
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_auto_pick as auto  # noqa: E402
import cell_wrist as cw  # noqa: E402

HSV = ([35, 80, 60], [90, 255, 255])
J = [[0.5, 0.0], [0.0, -0.5]]  # 2 px per mm, v grows toward -y
BAND = {"yaw_lo": -180, "yaw_hi": 180, "J": J, "ref": {"u": 320, "v": 240, "area": 120 * 60, "axis_deg": 0.0}}


def frame(cx=320, cy=240, w=120, h=60, extra=None):
    img = np.full((480, 640, 3), 90, np.uint8)
    cv2.rectangle(img, (int(cx - w / 2), int(cy - h / 2)), (int(cx + w / 2) - 1, int(cy + h / 2) - 1), (40, 190, 50), -1)
    if extra:
        cv2.rectangle(img, *extra, (40, 190, 50), -1)
    return img


def test_the_container_is_measured_and_a_cut_or_second_blob_is_flagged():
    seen = cw.observe(frame(400, 200), *HSV)
    assert seen["found"] and abs(seen["cx"] - 400) < 1 and abs(seen["cy"] - 200) < 1 and seen["blobs"] == 1
    assert abs(seen["area"] - 7200) < 200 and seen["fill"] > 0.95
    assert min(seen["axis_deg"], 180 - seen["axis_deg"]) < 2  # the long side is horizontal
    assert cw.observe(frame(40, 240), *HSV)["cut"]
    far = cw.observe(frame(extra=((500, 400), (580, 460))), *HSV, near=(320, 240))
    assert far["blobs"] == 1 and abs(far["cx"] - 320) < 1  # a container elsewhere in the frame is not in the way
    beside = cw.observe(frame(extra=((382, 210), (440, 270))), *HSV, near=(320, 240))
    assert beside["blobs"] == 2  # one right beside it: the jaws may meet it
    assert not cw.observe(np.full((480, 640, 3), 90, np.uint8), *HSV)["found"]


def test_fit_recovers_j_from_offset_hovers_and_refuses_a_degenerate_set():
    A = np.array([[2.0, 0.3], [-0.2, -1.8]])
    xy = [(dx, dy) for dx in (-8, 0, 8) for dy in (-8, 0, 8)]
    rng = np.random.default_rng(0)
    uv = [A @ p + (320, 240) + rng.normal(0, 0.5, 2) for p in xy]
    fitted = cw.fit(xy, uv)
    assert np.allclose(fitted["J"], np.linalg.inv(A), atol=0.02) and fitted["rms_px"] < 1.5
    with pytest.raises(ValueError):
        cw.fit([(0, k) for k in range(9)], [(320, 240 + 2 * k) for k in range(9)])  # one line: no x information


def test_verdicts_pass_correct_and_refuse():
    centred = cw.observe(frame(), *HSV)
    assert cw.judge(centred, BAND)["verdict"] == "pass"
    off = cw.judge(cw.observe(frame(340, 220), *HSV), BAND)  # 20 px right, 20 px up -> 10 mm x, +10 mm y
    assert off["verdict"] == "correct" and off["dx_mm"] == pytest.approx(10, abs=0.6) and off["dy_mm"] == pytest.approx(10, abs=0.6)
    assert "over" in cw.judge(cw.observe(frame(400, 240), *HSV), BAND)["why"]  # 40 mm in one step
    assert "disagree" in cw.judge(cw.observe(frame(360, 240), *HSV), BAND, total_mm=15)["why"]
    assert cw.judge(cw.observe(frame(w=60, h=40), *HSV), BAND)["why"].startswith("area")
    assert cw.judge({"found": False}, BAND)["why"] == "container not seen"


class Cell:
    def __init__(self, frames, answers=None):
        self.frames, self.answers, self.sent = list(frames), answers or {}, []

    def frame(self, camera):
        assert camera == "wrist"
        return self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]

    def act(self, command):
        self.sent.append(command)
        return {"ok": True, **self.answers.get(command, {})}


def test_align_corrects_once_then_passes_and_replans_from_the_corrected_pick():
    cell = Cell([frame(340, 220)] * 3 + [frame()] * 3)
    asked = []
    out = cw.align(cell, "wrist", BAND, HSV, lambda dx, dy: asked.append((dx, dy)) or "replan.json")
    assert out["verdict"] == "pass" and len(out["iterations"]) == 2
    assert asked[0][0] == pytest.approx(10, abs=0.6) and cell.sent == ["load replan.json", "goto above_pick"]


def test_a_refused_wrist_view_parks_without_the_descent():
    cell = __import__("test_omx_cell_auto_pick").Scripted()
    refuse = {"verdict": "refuse", "dx_mm": 0, "dy_mm": 0, "total_mm": 0}
    moved = auto.transfer_folded(cell, "lib.json", closed=46.6, wrist=lambda: refuse)
    assert moved["result"] == "misaligned" and "run descend_pick" not in cell.commands and cell.commands[-1] == "park"


def test_no_hook_without_the_flag_or_a_calibration_for_this_arm(tmp_path):
    target = {"pick": {"x": 0, "y": 0.2, "z": 0.02, "yaw_deg": -67.8}, "place": {}}
    config = {"params": None, "wrist": {"cal_path": str(tmp_path / "cal.json")}, "work_dir": str(tmp_path)}
    assert cw.hook(config, None, target, None) is None  # wrist.enabled defaults to 0
    (tmp_path / "cal.json").write_text('{"schema": "rosy.omx-wrist-cal.v1", "arms": {"A": {"bands": [%s]}}}' % str(BAND).replace("'", '"'))
    enabled = dict(config, params={"wrist.enabled": 1}, arm_id="S")
    assert cw.hook(enabled, None, target, None) is None  # arm A is calibrated, arm S is not
    assert cw.hook(dict(enabled, arm_id="A", wrist=dict(config["wrist"], hsv_min=HSV[0], hsv_max=HSV[1])), None, target, None) is not None


def test_calibration_hovers_nine_offsets_fits_j_and_saves_a_band_per_arm(tmp_path):
    import cell_wrist_cal as cal

    A = np.array([[2.0, 0.0], [0.0, -2.0]])  # what the camera does: 2 px per mm of box offset
    state = {"pick": None}

    class Hovering(Cell):
        def frame(self, camera):
            dx = (state["pick"]["x"] - 0.05) * 1000
            dy = (state["pick"]["y"] - 0.2) * 1000
            u, v = A @ (-dx, -dy) + (320, 240)  # the gripper moved +d sees the box at -d
            return frame(u, v)

    def write(pick):
        state["pick"] = pick
        return "lib.json"

    cell = Hovering([None])
    body = cal.calibrate(cell, "wrist", HSV, {"x": 0.05, "y": 0.2, "z": 0.06, "yaw_deg": -67.8}, write)
    assert body["n"] == 9 and np.allclose(body["J"], np.linalg.inv(A), atol=0.03)
    assert abs(body["ref"]["u"] - 320) < 1 and abs(body["ref"]["v"] - 240) < 1 and cell.sent[-1] == "park"
    path = tmp_path / "wrist-cal.json"
    cal.save(path, "S", -67.8, 45, body, "wrist")
    cal.save(path, "A", 20.0, 45, body, "arm_a_wrist")
    saved = __import__("json").loads(path.read_text())
    assert set(saved["arms"]) == {"S", "A"} and cw.band_for(saved, "S", -60) and cw.band_for(saved, "A", -60) is None
