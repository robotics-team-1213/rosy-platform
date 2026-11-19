"""floor_paint_gate: a robot's pink-tape gate from its own frames covers the tape and refuses without one."""
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import floor_paint_gate as fpg  # noqa: E402


def frame(tape_hsv=(173, 70, 205)):
    img = np.full((240, 320, 3), (105, 105, 105), np.uint8)
    img[:, 140:170] = cv2.cvtColor(np.uint8([[tape_hsv]]), cv2.COLOR_HSV2BGR)[0, 0]
    img[200:230, 20:60] = cv2.cvtColor(np.uint8([[(10, 200, 230)]]), cv2.COLOR_HSV2BGR)[0, 0]  # an orange box
    return img


def test_the_gate_covers_the_tape_and_not_orange(tmp_path):
    out = fpg.gate([frame()])
    lo = (out["values"]["pink_h_low"], out["values"]["pink_min_saturation"], out["values"]["pink_min_value"])
    hsv = cv2.cvtColor(frame(), cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, lo, (out["values"]["pink_h_high"], 255, 255)) > 0
    assert mask[100, 150] and not mask[210, 40]
    rid = fpg.CalibrationStore(tmp_path).add("r", "floor_paint", out["values"], method="t")
    assert fpg.CalibrationStore(tmp_path).load("r", "floor_paint", rid)["values"] == out["values"]


def test_no_tape_in_view_is_refused():
    with pytest.raises(ValueError):
        fpg.gate([np.full((240, 320, 3), 105, np.uint8)])
