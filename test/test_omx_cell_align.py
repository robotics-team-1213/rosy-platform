"""cell_align: the next step comes from the measurements - pick when one is planned, else free a packed long box
with a lengthwise push (a pivot first when the lane's error is unmeasured), else hold."""
import json
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
import cell_pivot  # noqa: E402
import cell_align as cr  # noqa: E402

ROI = (0, 0, 200, 260)
BOX = {"object": "container-3", "centre_mm": [0.0, 100.0], "raw_m": [0.0, 0.1], "long_axis_deg": 90.0,
       "length_mm": 100, "width_mm": 30, "matched": True}


def to_px(p):  # 1 px per mm, arm (0, 0.1) at pixel (100, 100)
    return (100 + p[0] * 1000, 100 + (p[1] - 0.1) * 1000)


def packed_row():
    mask = np.zeros((260, 200), np.uint8)
    mask[50:151, 85:116] = 255  # the box, 100 x 30 mm along y
    mask[50:151, 120:151] = 255  # its neighbour 5 mm away on +x, flush ends
    return mask


def test_a_packed_long_box_is_slid_along_its_length_with_one_finger_leading():
    """2026-11-02: the 42 mm closed-jaw face reached the next column 4-5 mm away; one 20 mm finger pad leading fits
    inside the 30 mm face, and the trailing finger needs room behind it."""
    push = cr.free_push([BOX], packed_row(), ROI, to_px, None, 3.0)
    assert push["narrow"] and push["offset_mm"] == 0.0
    assert push["along_deg"] == -90.0  # toward -y: on +y the trailing finger would go down past the view's edge
    assert push["mm"] == pytest.approx(50 - 0.7 * 35 + 15) and push["at"] == pytest.approx([0.0, 0.1])
    shifted = cr.free_push([BOX], packed_row(), ROI, to_px, None, 12.0)  # the map's worst error: the line moves off it
    assert shifted["narrow"] and 0 < shifted["offset_mm"] <= 5.0
    tight = packed_row()
    tight[0:22, 90:111] = 255  # something where the trailing finger would go down: the wide face is the fallback
    wide = cr.free_push([BOX], tight, ROI, to_px, None, 3.0)
    assert wide is None or not wide["narrow"]


def test_nothing_slides_when_both_ends_are_blocked():
    mask = packed_row()
    mask[0:40, 60:120] = 255  # behind
    mask[160:220, 60:120] = 255  # ahead
    assert cr.free_push([BOX], mask, ROI, to_px, None, 3.0) is None


def scene(tmp_path, monkeypatch, dry, region=None):
    cal_path = tmp_path / "cal.json"
    cal_path.write_text("{}")
    if region:
        cell_pivot.bias_path(cal_path).write_text(json.dumps({"schema": cell_pivot.SCHEMA, "regions": [region]}))
    monkeypatch.setattr(cr.auto, "run_auto", lambda *a, **k: dry)
    monkeypatch.setattr(cr.auto, "observe", lambda *a: (None, None, [dict(BOX, length_mm=115, width_mm=36, centre_mm=[0.4, 99.7])], None))
    monkeypatch.setattr(cr.cell_objects, "foreground", lambda *a, **k: packed_row())
    monkeypatch.setattr(cr, "predicted_pixel", lambda c, k, s, p: to_px(p))
    cell = type("Cell", (), {"frame": lambda self, name: None})()
    config = {"params": None, "sites": {"pallet": {}}}
    catalog = [{"id": "container-3", "length_mm": 100, "width_mm": 30}]
    return lambda: cr.next_step(cell, config, {}, cal_path, catalog, ROI, "col1", "pallet", "col2top", tmp_path)


def test_the_next_step_is_pick_then_pivot_then_push_then_hold_from_what_is_measured(tmp_path, monkeypatch):
    planned = {"result": "planned", "attempts": [{"chosen": {"object": "container-3"}}]}
    assert scene(tmp_path, monkeypatch, planned)()["step"] == "pick"
    packed = {"result": "stopped: no usable object",
              "attempts": [{"refused": [{"centre_mm": [0.0, 100.0], "object": "container-3", "why": "no finger room: 9 / 5 mm"}]}]}
    step = scene(tmp_path, monkeypatch, packed)()  # no region: planned with the map's worst error (0 in this map)
    assert step["step"] == "push" and step["push"]["narrow"] and step["miss_mm"] == 0.0
    worst = {"loo_error_mm": {"max": 30.0}}
    monkeypatch.setattr(cr.cell_pivot, "map_record", lambda cal, site: worst)
    step = scene(tmp_path, monkeypatch, packed)()
    assert step["step"] == "pivot" and step["at"] == [0.0, 0.1], step  # fits only with an accepted pivot's error (5 mm)
    region = {"site": "pallet", "point_m": [0.0, 0.1], "bias_mm": [1.0, -1.0], "rms_mm": 2.0}
    step = scene(tmp_path, monkeypatch, packed, region)()  # measured here: its rms, not the map's worst
    assert step["step"] == "push" and step["miss_mm"] == 2.0
    other = {"result": "stopped: no usable object", "attempts": [{"refused": [{"centre_mm": [0.0, 100.0], "why": "tangled blob"}]}]}
    assert scene(tmp_path, monkeypatch, other)()["step"] == "hold"


def test_next_moves_only_as_one_supervised_step():
    with pytest.raises(SystemExit, match="person-at-switch"):
        cr.main(["--config", "x.json", "--catalog", "c.json", "--roi", "0", "0", "1", "1", "--from", "col1", "--dest", "d", "next"])
