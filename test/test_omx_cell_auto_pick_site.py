from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))


def test_site_finger_params_override_global_params_for_finger_room(monkeypatch):
    import cell_auto_pick_plan as cap

    seen = []
    monkeypatch.setattr(cap, "predicted_pixel", lambda *a: (100, 100))
    monkeypatch.setattr(cap, "past_pan_limit", lambda *a: None)
    monkeypatch.setattr(cap, "past_park_reach", lambda *a: None)
    monkeypatch.setattr(
        cap,
        "finger_room",
        lambda _m, _r, _pf, _o, _e, params, **_kw: seen.append(params) or {"margin_mm": None, "free_mm": [24.0, 6.0]},
    )
    monkeypatch.setattr(cap, "reachable_ends", lambda *a: [])
    cfg = {
        "params": {"auto.finger_mm": 12.0, "auto.min_jaw_margin_mm": 1.0, "auto.neighbour_clear_mm": 0.0},
        "sites": {
            "pinky": {
                "start": [0.1, 0.14],
                "finger_params": {"auto.finger_mm": 0.0, "auto.min_jaw_margin_mm": 0.5, "evidence": "ignored"},
            }
        },
    }
    objs = [{"raw_m": [0.1, 0.14], "matched": True, "object": "c2", "long_axis_deg": 0.0, "centre_mm": [100, 140]}]
    cat = [{"id": "c2", "length_mm": 60, "width_mm": 30}]
    cap.choose(None, cfg, {}, "pinky", "belt", [0.1, -0.05], [0, 0, 300, 300], objs, None, cat, {}, [], None, set(), None)
    assert len(seen) == 1
    assert seen[0]["auto.finger_mm"] == 0.0 and seen[0]["auto.min_jaw_margin_mm"] == 0.5
    assert "evidence" not in seen[0]


def _beltend_room_fixture(tmp_path):
    import copy
    import json
    import cv2
    import numpy as np
    import cell_calibration as cal
    import cell_choices

    omx = Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"
    plan = json.loads((omx / "grasp-plan.example.json").read_text(encoding="utf-8"))
    plan["limits"]["workspace_min_m"] = [-0.30, -0.30, -0.10]
    cal_path = tmp_path / "cal.json"
    # Direct 1 mm/px mapping at z_view=0.015: x_m = (px - 200) / 1000, y_m = (200 - py) / 1000
    h = [[0.001, 0.0, -0.200], [0.0, -0.001, 0.200], [0.0, 0.0, 1.0]]
    cal_path.write_text(json.dumps({
        "schema": cal.SCHEMA,
        "sites": {
            "beltend": {"homography": h, "z_view": 0.015},
            "pinky": {"homography": h, "z_view": 0.015},
        },
    }), encoding="utf-8")
    catalog = [copy.deepcopy(e) for e in json.loads((omx / "object-catalog.example.json").read_text(encoding="utf-8"))["objects"]
               if e["id"] == "container-3"]
    config = {
        "cameras": {"top": {"height_m": 0.60, "center_px": [320, 240]}},
        "calibration_path": str(cal_path),
        "plan": plan,
        "params": {
            "objects.light": 255.0,
            "objects.surface_min_px": 12000,
            "auto.finger_mm": 2.0,
            "auto.neighbour_clear_mm": 14.0,
            "auto.min_jaw_margin_mm": 2.0,
            "auto.own_side_mm": 6.0,
        },
        "objects": {"hsv": [[[0, 80, 90], [20, 255, 255]], [[160, 80, 90], [180, 255, 255]]]},
        "sites": {
            "beltend": {
                "surface_z": 0.0,
                "z": 0.015,
                "yaw_deg": 0.0,
                "start": [0.135, 0.120],
                "place": [0.135, 0.120],
                "surface_px": [[275, 22], [363, 22], [363, 165], [275, 165]],
                "auto_roi": [271, 18, 367, 167],
                "surface_lab": [[55, 128, 128]],
            },
            "pinky": {
                "surface_z": 0.0,
                "z": 0.015,
                "yaw_deg": 0.0,
                "start": [0.100, -0.120],
                "place": [0.100, -0.120],
                "surface_px": [[240, 220], [360, 220], [360, 420], [240, 420]],
                "auto_roi": [235, 215, 365, 425],
                "surface_lab": [[55, 128, 128]],
            },
        },
    }
    return config, cal.load(cal_path), catalog, cell_choices.Choices(tmp_path / "choices.json"), cv2, np


def test_tight_site_roi_inside_clear_frame_avoids_false_edge_of_view(tmp_path):
    import cell_auto_pick_plan as cap

    config, calibration, catalog, choices, cv2, np = _beltend_room_fixture(tmp_path)
    img = np.full((480, 640, 3), (55, 55, 55), np.uint8)
    # 30x90 px red container inside surface_px (x<=363), 5 px from tight roi[2]=367
    cv2.rectangle(img, (332, 35), (362, 125), (40, 40, 220), -1)
    roi = config["sites"]["beltend"]["auto_roi"]
    class DummyCell:
        def frame(self, _): return img
    _, mask, objects, err = cap.observe(DummyCell(), config, calibration, "beltend", roi, catalog, image=img)
    assert err is None and len(objects) == 1
    usable_old, refused_old = cap.choose(None, config, calibration, "beltend", "pinky", [0.10, -0.12], roi,
                                         objects, mask, catalog, {"regions": []}, choices, tmp_path)
    assert not usable_old and refused_old[0]["why"].startswith("edge of view:")
    room_view = cap.finger_room_view(img, config, "beltend", roi, mask)
    assert room_view is not None and room_view[1][2] > roi[2]
    usable, refused = cap.choose(None, config, calibration, "beltend", "pinky", [0.10, -0.12], roi,
                                 objects, mask, catalog, {"regions": []}, choices, tmp_path, room_view=room_view)
    assert len(usable) == 1 and not refused


def test_obstacle_just_outside_tight_site_roi_still_blocks_fingers(tmp_path):
    import cell_auto_pick_plan as cap

    config, calibration, catalog, choices, cv2, np = _beltend_room_fixture(tmp_path)
    img = np.full((480, 640, 3), (55, 55, 55), np.uint8)
    cv2.rectangle(img, (332, 35), (362, 125), (40, 40, 220), -1)
    # Neighbour container sitting 12 px past the target's right edge — completely outside roi[2]=367!
    cv2.rectangle(img, (374, 40), (402, 120), (40, 140, 220), -1)
    roi = config["sites"]["beltend"]["auto_roi"]
    class DummyCell:
        def frame(self, _): return img
    _, mask, objects, err = cap.observe(DummyCell(), config, calibration, "beltend", roi, catalog, image=img)
    assert err is None and len(objects) == 1
    room_view = cap.finger_room_view(img, config, "beltend", roi, mask)
    usable, refused = cap.choose(None, config, calibration, "beltend", "pinky", [0.10, -0.12], roi,
                                 objects, mask, catalog, {"regions": []}, choices, tmp_path, room_view=room_view)
    assert not usable and refused[0]["why"].startswith("neighbour clearance:")


def test_true_camera_frame_edge_still_refuses_as_edge_of_view(tmp_path):
    import cell_auto_pick_plan as cap

    config, calibration, catalog, choices, cv2, np = _beltend_room_fixture(tmp_path)
    img = np.full((480, 640, 3), (55, 55, 55), np.uint8)
    # Container flush near left edge x=0 of camera frame (px=20 -> left edge x=5, only 5 mm to frame edge x=0)
    cv2.rectangle(img, (5, 35), (35, 125), (40, 40, 220), -1)
    roi = [0, 18, 96, 167]
    config["cameras"]["top"] = {"height_m": 0.60, "center_px": [20, 80]}
    config["sites"]["beltend"]["surface_px"] = [[2, 22], [90, 22], [90, 165], [2, 165]]
    config["sites"]["beltend"]["auto_roi"] = roi
    class DummyCell:
        def frame(self, _): return img
    _, mask, objects, err = cap.observe(DummyCell(), config, calibration, "beltend", roi, catalog, image=img)
    assert err is None and len(objects) == 1
    room_view = cap.finger_room_view(img, config, "beltend", roi, mask)
    assert room_view is not None and room_view[1][0] == 0
    usable, refused = cap.choose(None, config, calibration, "beltend", "pinky", [0.10, -0.12], roi,
                                 objects, mask, catalog, {"regions": []}, choices, tmp_path, room_view=room_view)
    assert not usable and refused[0]["why"].startswith("edge of view:")


def test_finger_room_view_without_surface_lab_uses_site_roi_median_only():
    import cv2
    import numpy as np
    import cell_auto_pick_plan as cap

    img = np.full((480, 640, 3), (120, 120, 120), np.uint8)
    roi = [100, 100, 180, 180]
    img[roi[1]:roi[3], roi[0]:roi[2]] = (50, 50, 50)
    # Isolated patch matching outside brightness placed inside `roi`: if surface_lab mistakenly used
    # the padded ROI median (80% bright 120), this (115,115,115) patch would vanish (|dL| < 40).
    cv2.rectangle(img, (148, 120), (170, 150), (115, 115, 115), -1)
    config = {
        "params": {"objects.light": 40.0, "objects.chroma": 25.0, "objects.drop_shadow": 0, "objects.surface_min_px": 12000},
        "objects": {},
        "sites": {"beltend": {}},
    }
    rmask, mroi = cap.finger_room_view(img, config, "beltend", roi)
    assert not rmask[roi[1] - mroi[1] + 5:roi[1] - mroi[1] + 25, roi[0] - mroi[0] + 5:roi[0] - mroi[0] + 25].any()
    assert rmask[135 - mroi[1], 159 - mroi[0]] > 0
