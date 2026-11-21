"""D-1057: the read-only slot overlay draws the zone table and says which place points it could not convert."""
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

import cell_slot_overlay as overlay  # noqa: E402

CONFIG = {"sites": {"pallet": {"place": [0.153, -0.128], "z": 0.005, "auto_roi": [246, 148, 400, 405]}}}


def test_overlay_draws_every_slot_roi_and_reports_the_unconvertible_place_point(tmp_path, capsys):
    frame, config, out = tmp_path / "top.png", tmp_path / "cell.json", tmp_path / "overlay.png"
    cv2.imwrite(str(frame), np.zeros((480, 640, 3), np.uint8))
    config.write_text(json.dumps(CONFIG), encoding="utf-8")
    before = config.read_bytes()
    assert overlay.main(["--config", str(config), "--frame", str(frame), "--out", str(out)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["slots"] == 6 and report["place_points_omitted"] == ["pallet"]
    image = cv2.imread(str(out))
    assert image.shape == (480, 640, 3) and image[165, 370].tolist() == [0, 200, 0]  # corner of slot c2r1
    assert image[148, 246].tolist() == [255, 160, 0]  # the site's auto_roi
    assert config.read_bytes() == before  # read-only


def test_overlay_refuses_to_overwrite_its_inputs(tmp_path):
    frame, config = tmp_path / "top.png", tmp_path / "cell.json"
    cv2.imwrite(str(frame), np.zeros((10, 10, 3), np.uint8))
    config.write_text("{}", encoding="utf-8")
    assert overlay.main(["--config", str(config), "--frame", str(frame), "--out", str(frame)]) == 2
    assert overlay.main(["--config", str(config), "--frame", str(frame), "--out", str(tmp_path / "x.txt")]) == 2
    assert overlay.main(["--config", str(config), "--frame", str(tmp_path / "none.png"), "--out", str(tmp_path / "o.png")]) == 2
