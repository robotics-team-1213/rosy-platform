"""Exact-point post-eval observations can attest only to the height actually visited."""
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
for sub in ("deploy/robot/omx", "middleware/devices/omx/adapter"):
    sys.path.insert(0, str(ROOT / sub))

import cell_attempts
import cell_cal_monitor
import cell_route_visit as visit


SITE = "tmp-b-2-l1"
POINT = [0.15, 0.10]


@pytest.fixture
def setup(tmp_path):
    ref = tmp_path / "top.jpg"
    im = np.random.default_rng(42).integers(0, 256, size=(480, 640, 3), dtype=np.uint8)
    assert cv2.imwrite(str(ref), im)
    frame = cv2.imread(str(ref))
    cfg = {"arm_id": "arm_b", "tcp_x_m": .074, "work_dir": str(tmp_path),
           "preflight": {"reference_top": str(ref)}, "sites": {SITE: {"z": .1, "place": list(POINT)}},
           "cameras": {"top": {"height_m": .6, "center_px": [320, 240]}},
           "zone_rois": {"top": {"tmp-b-2": [140, 90, 160, 110]}}}
    rec = {"homography": [[.001, 0, 0], [0, .001, 0], [0, 0, 1]], "z_view": .1}
    maps = {SITE: rec}
    cal = {"sites": maps, "reference_top_sha256": hashlib.sha256(ref.read_bytes()).hexdigest(),
           "reference_map_sha": cell_attempts.digest(maps),
           "reference_geometry_sha": cell_attempts.digest({SITE: dict(auto_roi=None, surface_px=None, map_from=None)})}
    fk = [(*POINT, .1, 0), (*POINT, .1, 180)]
    extra = visit.visit_evidence(cfg, cal, SITE, frame, POINT, [[130, 100], [170, 100]], fk)
    assert extra.get("route_visit")
    extra.update(place_xy=POINT, yaw_pair=True, geometry_dependent=False, finger_ok=True,
                 scene_ok=True, jaw_sides=["ref", "ref"])
    cell_cal_monitor.record_observation(cfg, site=SITE, map_sha=cell_attempts.digest(rec),
                                        source="visit", raw_mm=[0, 0], residual_mm=[0, 0], extra=extra)
    return cfg, cal


def test_bound_pair_only_verifies_hover_height(setup):
    cfg, cal = setup
    result = visit.exact_visit(cfg, cal, SITE, POINT)
    assert result["verified_at_visit_height"] and not result["verified"]
    assert result["observed_xy_m"] == pytest.approx(POINT)
    assert result["observed_z_m"] == [.1, .1]
    assert not visit.exact_visit(cfg, cal, SITE, [.16, .1])["verified_at_visit_height"]
    cfg["zone_rois"]["top"]["tmp-b-2"][0] += 2
    assert "footprint changed" in visit.exact_visit(cfg, cal, SITE, POINT)["reason"]


@pytest.mark.parametrize("change", ["legacy", "wrong_arm", "new_map", "point", "yaw", "future", "bad_pixels",
                                    "tcp", "reference", "stopped", "displaced_jaws", "wrong_fk"])
def test_refuses_incomplete_or_mismatched_evidence(setup, change):
    cfg, cal = setup
    ledger = cell_cal_monitor.monitor_path(cfg)
    row = json.loads(ledger.read_text())
    if change == "legacy":
        row.pop("route_visit")
    elif change == "wrong_arm":
        row["arm_id"] = "arm_a"
    elif change == "new_map":
        row["map_sha"] = "older"
    elif change == "point":
        row["place_xy"] = [.16, .1]
    elif change == "yaw":
        row["route_visit"]["fk_xyzyaw"][1][3] = 50
    elif change == "future":
        row["ts"] += 3600
    elif change == "bad_pixels":
        row["route_visit"]["jaw_pixels"][1] = [130, 100]
    elif change == "tcp":
        cfg["tcp_x_m"] += .01
    elif change == "reference":
        Path(cfg["preflight"]["reference_top"]).write_bytes(b"replaced")
    elif change == "stopped":
        row["accepted"] = False
    elif change == "displaced_jaws":
        for pixel in row["route_visit"]["jaw_pixels"]:
            pixel[0] += 10
    elif change == "wrong_fk":
        row["route_visit"]["fk_xyzyaw"][1][0] += .02
    ledger.write_text(json.dumps(row) + "\n")
    result = visit.exact_visit(cfg, cal, SITE, POINT)
    assert not result["verified_at_visit_height"] and not result["verified"]
