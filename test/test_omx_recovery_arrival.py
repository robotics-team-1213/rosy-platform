from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "deploy/robot/omx"), str(ROOT / "middleware/devices/omx/adapter")]
import cell_auto_pick_plan
import cell_recovery_placement_live_view as view


@pytest.mark.parametrize(("neighbor", "aligned", "verified"), [(False, True, True), (True, True, False),
                                                               (False, False, False)])
def test_arrival_must_be_new_and_camera_still_aligned(monkeypatch, neighbor, aligned, verified):
    cfg = {"params": {}, "sites": {"board": {"place": [0, 0], "auto_roi": [0, 0, 99, 99],
                                           "surface_px": [[0, 0], [99, 0], [99, 99], [0, 99]]}}}
    before, after = {"image": "before"}, {"image": "after"}
    cargo = {"length_mm": 3, "width_mm": 2, "object_id": "red"}
    obj = {"centre_mm": [7, 0], "raw_m": [0.007, 0], "matched": True, "object": "red",
           "long_axis_deg": 0, "length_mm": 3, "width_mm": 2}
    monkeypatch.setattr(view, "camera_aligned", lambda ref, image, params: image == "before" or aligned)
    monkeypatch.setattr(view, "predicted_pixel", lambda c, cal, name, xy: [50 + 1000 * v for v in xy])
    monkeypatch.setattr(cell_auto_pick_plan, "observe", lambda *a, image: (None, None,
                        [obj] if image == "after" or neighbor else [], None))
    result = view.verify_arrival(cfg, {"sites": {"board": {"homography": [[1]]}}}, "board",
                                 cargo, [], None, before, after, None)
    assert result["verified"] is verified
