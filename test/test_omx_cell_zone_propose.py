"""D-1057: the zone proposal tool finds tray grooves on a synthetic tray and says null with a reason when it cannot."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "deploy/robot/omx", ROOT / "middleware/devices/omx/adapter"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cell_zone_propose as propose  # noqa: E402


def _tray():
    img = np.full((480, 640, 3), 90, np.uint8)
    img[149:296, 285:414] = 190  # the white tray
    img[160:290, 329:332] = 165  # two vertical grooves and one horizontal groove
    img[160:290, 368:371] = 165
    img[198:201, 290:410] = 165
    return img


def test_top_grooves_split_the_tray_into_three_columns_and_two_rows():
    out = propose.propose_top(_tray())
    assert out["tray_bbox"] == [285, 149, 414, 296]
    rois = out["rois"]
    assert rois["c1r1"][0] == 285 and rois["c3r2"][2] == 414 and rois["c1r1"][1] == 149 and rois["c1r2"][3] == 296
    assert abs(rois["c1r1"][2] - 330) <= 2 and abs(rois["c2r1"][2] - 370) <= 2 and abs(rois["c1r1"][3] - 199) <= 2
    assert all(v is not None for v in rois.values()) and not out["reasons"]


def test_top_without_grooves_is_null_with_a_reason():
    img = np.full((480, 640, 3), 90, np.uint8)
    img[149:296, 285:414] = 190
    out = propose.propose_top(img)
    assert all(v is None for v in out["rois"].values()) and "vertical grooves" in out["reasons"]["c2r1"]
    assert propose.propose_top(np.full((480, 640, 3), 90, np.uint8))["rois"]["c1r1"] is None


def test_side_with_no_clear_pallet_is_all_null_with_reasons():
    out = propose.propose_side(np.full((480, 640, 3), 120, np.uint8))
    assert all(v is None for v in out["rois"].values()) and all(out["reasons"].values())


def test_the_cli_writes_only_the_proposal_files_and_a_ready_to_paste_zone_rois(tmp_path, capsys):
    top, side = tmp_path / "top.png", tmp_path / "side.png"
    cv2.imwrite(str(top), _tray())
    cv2.imwrite(str(side), np.full((480, 640, 3), 120, np.uint8))
    paths = {k: tmp_path / f"{k}.out" for k in ("json", "top", "side")}
    out_json, out_top, out_side = tmp_path / "p.json", tmp_path / "t.png", tmp_path / "s.png"
    assert propose.main(["--top", str(top), "--side", str(side), "--out", str(out_json), "--top-png", str(out_top),
                         "--side-png", str(out_side)]) == 0
    doc = json.loads(out_json.read_text(encoding="utf-8"))
    assert set(doc["zone_rois"]["top"]) == {f"c{c}r{r}" for c in (1, 2, 3) for r in (1, 2)} and doc["zone_rois"]["side"] == {}
    assert cv2.imread(str(out_top)).shape == (480, 640, 3) and "not_applied" in doc
    assert sorted(p.name for p in tmp_path.iterdir()) == ["p.json", "s.png", "side.png", "t.png", "top.png"]
    assert propose.main(["--top", str(tmp_path / "none.png"), "--side", str(side), "--out", str(out_json),
                         "--top-png", str(out_top), "--side-png", str(out_side)]) == 2
    del paths
