"""cell_scale: a 7-segment scale display read through the top camera; an unreadable frame is None, never a guess."""
import json
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
import cell_scale as sc  # noqa: E402

# segments as drawn by a display, independent of the reader's boxes: (x0, y0, x1, y1) in a 10 x 18 digit
DRAW = {"a": (2, 0, 8, 2), "b": (8, 1, 10, 9), "c": (8, 9, 10, 17), "d": (2, 16, 8, 18), "e": (0, 9, 2, 17),
        "f": (0, 1, 2, 9), "g": (2, 8, 8, 10)}
LIT = {"0": "abcdef", "1": "bc", "2": "abdeg", "3": "abcdg", "4": "bcfg", "5": "acdfg", "6": "acdefg", "7": "abc",
       "8": "abcdefg", "9": "abcdfg", " ": ""}


def display(text, scale=6):
    """A light LCD with dark digits, `scale` px per unit (a 18-unit digit is 108 px before it is shrunk)."""
    w = len(text) * 13 * scale
    img = np.full((22 * scale, w), 200, np.uint8)
    for i, ch in enumerate(text):
        for s in LIT[ch]:
            x0, y0, x1, y1 = DRAW[s]
            ox, oy = (i * 13 + 1) * scale, 2 * scale
            cv2.rectangle(img, (ox + x0 * scale, oy + y0 * scale), (ox + x1 * scale - 1, oy + y1 * scale - 1), 30, -1)
    return img


def frame(text, digit_px=12, seed=0):
    """The display seen by the top camera: shrunk so a digit is `digit_px` tall, slightly turned, with noise."""
    big = display(text)
    k = digit_px / (18 * 6)
    small = cv2.resize(big, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    h, w = small.shape
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = src + np.float32([[300, 200], [302, 197], [303, 199], [300, 202]])
    img = cv2.warpPerspective(small, cv2.getPerspectiveTransform(src, dst), (640, 480), borderValue=120)
    img = np.clip(img + np.random.default_rng(seed).normal(0, 4, img.shape), 0, 255).astype(np.uint8)
    # the display's digit area: one 13-unit pitch per digit, from x = 1 unit, y = 2 .. 20 units
    corners = [[1, 2], [len(text) * 13, 2], [len(text) * 13, 20], [1, 20]]
    M = cv2.getPerspectiveTransform(src, dst)
    pts = cv2.perspectiveTransform(np.float32([[[x * 6 * k, y * 6 * k] for x, y in corners]]), M)[0]
    return img, {"display_px": pts.tolist(), "digits": len(text), "decimals": 2, "unit": "g", "dark_digits": True, "digit_frac": 10 / 13}


@pytest.mark.parametrize("digit_px", [9, 12, 18, 40])  # the top camera sees a 1 cm digit as about 11 px
@pytest.mark.parametrize("text, value", [("  4823", 48.23), ("   000", 0.0), (" 96711", 967.11)])
def test_digits_from_nine_to_forty_pixels_tall_are_read(text, value, digit_px):
    hits = sum(sc.read_display(*frame(text, digit_px, seed=s)) == pytest.approx(value) for s in range(20))
    assert hits == 20


def test_a_garbled_or_empty_display_is_unreadable():
    img, spec = frame("  4823")
    img[:] = 120  # the display gone (glare, covered)
    assert sc.read_display(img, spec) is None
    img, spec = frame("      ")
    assert sc.read_display(img, spec) is None


def test_stable_waits_for_repeats_and_accept():
    seq = iter([None, 0.0, 0.0, 12.0, 48.2, 48.23, 48.23, 48.23, 48.23, 48.23])
    t = [0.0]
    v = sc.stable(lambda: next(seq), wait=lambda s: t.__setitem__(0, t[0] + s), clock=lambda: t[0], accept=lambda v: v > 0)
    assert v == 48.23
    t = [0.0]
    assert sc.stable(lambda: 1.0 + t[0], wait=lambda s: t.__setitem__(0, t[0] + s), clock=lambda: t[0]) is None


def test_enrol_writes_the_catalogue_and_conditions_and_refuses_an_unknown_object(tmp_path):
    cat = tmp_path / "catalog.json"
    cat.write_text(json.dumps({"schema": "rosy.omx-object-catalog.v1", "objects": [
        {"id": "container-2", "length_mm": 60, "width_mm": 30, "top_height_mm": 30}]}))
    cell = tmp_path / "cell.json"
    cell.write_text(json.dumps({"operating_conditions": {"payload_kg": None, "installation_revision": "x"}}))
    entry = sc.enrol(cat, "container-2", sc.to_kg(48.23, "g"), "48.23 g", cell)
    assert entry["mass_kg"] == 0.04823 and entry["mass_measured"]["source"] == "cell_scale"
    assert json.loads(cat.read_text())["objects"][0]["mass_kg"] == 0.04823
    cond = json.loads(cell.read_text())["operating_conditions"]
    assert cond["payload_kg"] == 0.04823 and cond["object_dimensions_m"] == [0.06, 0.03, 0.03] and cond["installation_revision"] == "x"
    with pytest.raises(SystemExit):
        sc.enrol(cat, "mystery-box", 0.01, "10.00 g")
