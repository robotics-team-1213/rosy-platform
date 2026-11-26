"""Adding map_from follower sites re-binds the map without a remap; any other geometry change still remaps."""
import json
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_calibrate as cc  # noqa: E402
import cell_map_followers as mf  # noqa: E402
import cell_preflight  # noqa: E402
from cell_auto_evidence import bound_map_error  # noqa: E402
from cell_calibrate_bound import save_bound_map_reference  # noqa: E402

REC = {"homography": [[0.005, 0.0, -0.5], [0.0, 0.005, -0.5], [0.0, 0.0, 1.0]], "z_view": 0.1,
       "loo_error_mm": {"mean": 2.0, "max": 3.0},
       "points": [{"pixel": [100 + 200 * x, 100 + 200 * y], "arm_m": [x, y]} for x, y in ((0.0, 0.1), (0.04, 0.1), (0.0, 0.14))]}
FRAME = np.full((32, 32, 3), 80, np.uint8)


@pytest.fixture
def cell(tmp_path, monkeypatch):
    ref, cal_path = tmp_path / "reference.jpg", tmp_path / "map.json"
    cfg = {"preflight": {"reference_top": str(ref)}, "calibration_path": str(cal_path), "work_dir": str(tmp_path),
           "cameras": {"top": {"height_m": 0.65, "center_px": [320, 240]}}, "coarse": {"z_view": 0.1},
           "calibrate": {"map_sites": ["floor", "pallet"]}, "params": {},
           "sites": {"floor": {"yaw_deg": 0.0, "surface_z": 0.006, "start": [0.02, 0.12], "auto_roi": [0, 0, 10, 10]},
                     "pallet": {"yaw_deg": 0.0, "surface_z": 0.03, "start": [0.03, 0.12], "auto_roi": [10, 0, 20, 10]}}}
    cal = {"schema": cc.cal.SCHEMA, "sites": {"floor": dict(REC), "pallet": dict(REC, z_view=0.12)}}
    save_bound_map_reference(cal_path, ref, cal, cfg, FRAME)
    monkeypatch.setattr(cell_preflight, "camera_shift_px", lambda *_: {"ok": True, "max_px": 0.0})
    for i in range(2):  # the ship followers added after the remap
        cfg["sites"][f"ship-h{i}"] = {"yaw_deg": 0.0, "surface_z": 0.03, "auto_roi": [20 + i, 0, 30, 10], "map_from": "pallet"}
    return cfg, json.loads(cal_path.read_text()), ref, cal_path


def _check(cfg, cal):
    return cc.check(cfg, cal, [], FRAME, params=cfg["params"])


def test_follower_only_addition_rebinds_without_remap(cell):
    cfg, cal, ref, cal_path = cell
    before = {name: json.dumps(rec, sort_keys=True) for name, rec in cal["sites"].items()}
    ref_bytes = ref.read_bytes()
    found = _check(cfg, cal)
    assert found["rebind_followers"] == ["ship-h0", "ship-h1"] and not found["camera_moved"]
    assert cc.stale(found) == ["rebind-followers"]
    assert mf.rebind(cfg, cal, cal_path, found, 6.0) == {"rebind-followers": ["ship-h0", "ship-h1"]}
    saved = json.loads(cal_path.read_text())
    assert ref.read_bytes() == ref_bytes  # the bound JPEG is kept, not re-encoded
    assert bound_map_error(saved, cfg, ref_bytes) is None
    assert {n: json.dumps(saved["sites"][n], sort_keys=True) for n in before} == before
    assert saved["sites"]["ship-h0"] == saved["sites"]["pallet"]
    assert cc.stale(_check(cfg, saved)) == []


def test_changed_existing_site_keeps_remap(cell):
    cfg, cal, _, _ = cell
    cfg["sites"]["floor"]["auto_roi"] = [0, 0, 11, 10]
    found = _check(cfg, cal)
    assert "rebind_followers" not in found and found["camera_moved"]


def test_removed_site_keeps_remap(cell):
    cfg, cal, _, _ = cell
    del cfg["sites"]["floor"]
    assert "rebind_followers" not in _check(cfg, cal)


def test_follower_of_unmapped_parent_keeps_remap(cell):
    cfg, cal, _, _ = cell
    cfg["sites"]["ship-h1"]["map_from"] = "belt"
    assert "rebind_followers" not in _check(cfg, cal)
    cfg["sites"]["ship-h1"]["map_from"] = "ship-h0"  # a parent that is itself new
    assert "rebind_followers" not in _check(cfg, cal)


def test_changed_reference_image_keeps_remap(cell):
    cfg, cal, ref, _ = cell
    assert cv2.imwrite(str(ref), np.full((32, 32, 3), 120, np.uint8))
    found = _check(cfg, cal)
    assert "rebind_followers" not in found and found["map_binding_error"] == "top camera map reference changed"


def test_camera_shift_keeps_remap(cell, monkeypatch):
    cfg, cal, _, _ = cell
    monkeypatch.setattr(cell_preflight, "camera_shift_px", lambda *_: {"ok": True, "max_px": 9.0})
    assert "rebind_followers" not in _check(cfg, cal)


def test_legacy_calibration_without_per_site_record_rebinds_followers(cell):
    cfg, cal, ref, cal_path = cell
    cal.pop("reference_geometry_sites")
    found = _check(cfg, cal)
    assert found["rebind_followers"] == ["ship-h0", "ship-h1"] and cc.stale(found) == ["rebind-followers"]
    assert mf.rebind(cfg, cal, cal_path, found, 6.0) == {"rebind-followers": ["ship-h0", "ship-h1"]}
    saved = json.loads(cal_path.read_text())
    assert bound_map_error(saved, cfg, ref.read_bytes()) is None and "reference_geometry_sites" in saved


def test_legacy_calibration_with_a_changed_existing_site_keeps_remap(cell):
    cfg, cal, _, _ = cell
    cal.pop("reference_geometry_sites")
    cfg["sites"]["pallet"]["auto_roi"] = [10, 0, 21, 10]
    found = _check(cfg, cal)
    assert "rebind_followers" not in found and found["map_binding_error"] == mf.GEOMETRY_CHANGED


def test_per_site_record_of_another_generation_keeps_remap(cell):
    cfg, cal, _, _ = cell
    cal["reference_geometry_sites"]["geometry_sha"] = "stale"
    assert "rebind_followers" not in _check(cfg, cal)
