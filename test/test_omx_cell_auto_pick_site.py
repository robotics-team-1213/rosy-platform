from __future__ import annotations

from pathlib import Path
import sys
import pytest

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


def test_belt_site_without_start_orders_by_reach_instead_of_key_error(monkeypatch):
    """2026-11-27: auto_pick_dry_run from the live belt site (moves, no start/place) died with KeyError 'start'."""
    import cell_auto_pick_plan as cap

    seen = []
    monkeypatch.setattr(cap, "predicted_pixel", lambda *a: (100, 100))
    monkeypatch.setattr(cap, "past_pan_limit", lambda *a: None)
    monkeypatch.setattr(cap, "past_park_reach", lambda *a: None)
    monkeypatch.setattr(cap, "finger_room", lambda _m, _r, _pf, o, *_a, **_kw: seen.append(o["raw_m"]) or {"margin_mm": None, "free_mm": [1.0, 1.0]})
    monkeypatch.setattr(cap, "reachable_ends", lambda *a: [])
    cfg = {"params": {"auto.neighbour_clear_mm": 0.0},
           "sites": {"belt": {"z": -0.0401, "moves": True, "moving_px": [260, 0, 370, 170], "auto_roi": [285, 15, 385, 168]}}}
    far = {"raw_m": [0.20, 0.10], "matched": True, "object": "c2", "long_axis_deg": 0.0, "centre_mm": [200, 100]}
    near = {"raw_m": [0.12, 0.05], "matched": True, "object": "c2", "long_axis_deg": 0.0, "centre_mm": [120, 50]}
    cat = [{"id": "c2", "length_mm": 60, "width_mm": 30}]
    usable, refused = cap.choose(None, cfg, {}, "belt", "pallet", [0.1, -0.05], [0, 0, 300, 300], [far, near], None, cat, {}, [], None, set(), None)
    assert not usable and len(refused) == 2
    assert seen == [[0.12, 0.05], [0.20, 0.10]]  # nearest to the arm axis first

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


def test_feel_hook_uses_limits_workspace_min_site_z_live_fk_and_skips_refused_reach(tmp_path, monkeypatch):
    import cell_feel
    import cell_pivot
    import cell_reach

    # 1. Uses site surface_z, plan.limits.workspace_min_m, live FK yaw, and skips candidate when z_step > 0 and reach refuses
    monkeypatch.setattr(cell_pivot, "joints_tcp", lambda state, **_kw: (0.10, 0.15, 0.02, 90.0))
    reach_verdicts = iter([{"verdict": "refuse"}, {"verdict": "pass"}])
    monkeypatch.setattr(cell_reach, "hook", lambda *_a, **_kw: (lambda: next(reach_verdicts)))

    class FakeCell:
        def act(self, cmd):
            if cmd == "state":
                return {"ok": True, "state": [0.0, 0.0, 0.0, 0.0, 0.0, 56.0]}
            return {"ok": True}

    picks = []
    commands = []

    def write_lib(_cfg, pick, _place, path):
        picks.append(dict(pick))
        return str(path)

    def run(cmd):
        commands.append(cmd)
        if cmd == "run grasp_pick":
            return {"ok": True, "holding": True}
        return {"ok": True}

    cfg = {
        "work_dir": str(tmp_path),
        "params": {"feel.enabled": 1, "feel.z_step_mm": 5.0, "feel.tries": 2},
        "sites": {"pinky": {"surface_z": 0.010}},
        "plan": {"limits": {"workspace_min_m": [-0.28, -0.28, 0.008]}},
    }
    target = {
        "site": "pinky",
        "pick": {"x": 0.10, "y": 0.15, "z": 0.012, "yaw_deg": 0.0},
        "place": {"x": 0.15, "y": 0.0, "z": 0.02, "yaw_deg": 0.0},
        "offset": 0.0,
    }
    fn = cell_feel.feel_hook(cfg, FakeCell(), target, write_lib)
    res = fn(run)
    assert res["holding"] is True
    # First candidate's reach refused with z_step > 0 -> must NOT run descend_pick/grasp_pick for candidate 0
    assert commands.count("run descend_pick") == 1 and commands.count("run grasp_pick") == 1
    # z clamped to plan.limits.workspace_min_m[2] = 0.008 (not descending to 0.012 - 0.008 = 0.004)
    assert picks[0]["z"] == 0.008 and picks[1]["z"] == 0.008

    # 2. Without workspace_min_m, site surface_z + 0.005 sets z_min, and live FK yaw (90) + offset (0) drives XY step
    picks.clear()
    monkeypatch.setattr(cell_reach, "hook", lambda *_a, **_kw: None)
    cfg2 = {"work_dir": str(tmp_path), "params": {"feel.enabled": 1, "feel.step_mm": 10.0, "feel.tries": 1}, "sites": {"pinky": {"surface_z": 0.020}}}
    target2 = {"site": "pinky", "pick": {"x": 0.10, "y": 0.15, "z": 0.020, "yaw_deg": 0.0}, "place": {"x": 0.15, "y": 0.0, "z": 0.02, "yaw_deg": 0.0}, "offset": 0.0}
    cell_feel.feel_hook(cfg2, FakeCell(), target2, write_lib)(run)
    assert picks[0]["z"] == 0.025  # surface_z 0.020 + 0.005
    assert picks[0]["x"] == 0.10 and picks[0]["y"] == pytest.approx(0.160, abs=1e-4)  # yaw 90 -> +y

    # 3. Legacy pick dict without "z" and without site config must not raise KeyError in feel_hook
    target_no_z = {"pick": {"x": 0.10, "y": 0.15, "yaw_deg": 0.0}, "place": {"x": 0.15, "y": 0.0, "z": 0.02, "yaw_deg": 0.0}}
    assert cell_feel.feel_hook({"work_dir": str(tmp_path), "params": {"feel.enabled": 1}}, FakeCell(), target_no_z, write_lib) is not None


def test_run_auto_passes_blend_flag_matching_choose(tmp_path, monkeypatch):
    import cell_auto_pick as cap_main
    import cell_auto_evidence as cae
    import cell_choices
    import cell_pivot

    bias_calls = []
    orig_bias_at = cell_pivot.bias_at

    def spy_bias_at(data, site, pt, reach_mm=None, params=None, *, pivot_only=False, blend=False):
        bias_calls.append((pivot_only, blend))
        return {"site": site, "point_m": list(pt), "bias_mm": [1.0, 2.0], "blended_n": 2}

    monkeypatch.setattr(cell_pivot, "bias_at", spy_bias_at)
    monkeypatch.setattr(cae, "map_pose_preflight", lambda *a, **kw: None)
    monkeypatch.setattr(cae, "track_sites", lambda _c, cfg, _cal, _s, _d, r, *_a: (cfg, r, None))
    monkeypatch.setattr(cae, "source_frame", lambda _c, path: ({"image": None}, {"path": str(path)}, None))
    monkeypatch.setattr(cae, "destination_view", lambda *a, **kw: (None, None))
    monkeypatch.setattr(cap_main, "observe", lambda *a, **kw: (None, None, [{"raw_m": [0.1, 0.1], "centre_mm": [100.0, 100.0], "object": "c1", "long_axis_deg": 0.0}], None))
    monkeypatch.setattr(cap_main, "finger_room_view", lambda *a, **kw: None)
    choose_calls = []

    def fake_choose(*a, **kw):
        choose_calls.append(1)
        return ([{"object": {"raw_m": [0.1, 0.1], "centre_mm": [100.0, 100.0], "object": "c1", "long_axis_deg": 0.0}, "offset": 90,
                  "bias_region": {"site": "pinky", "point_m": [0.1, 0.1], "bias_mm": [1.0, 2.0], "blended_n": 2},
                  "bias_mm": [1.0, 2.0], "approach_m": 0.04, "library": tmp_path / "lib.json",
                  "pick": {"x": 0.1, "y": 0.1, "z": 0.02, "yaw_deg": 0.0},
                  "place": {"x": 0.1, "y": 0.1, "z": 0.02, "yaw_deg": 0.0}}], [])

    monkeypatch.setattr(cap_main, "choose", fake_choose)
    monkeypatch.setattr(cap_main, "self_calibrate", lambda *a: (a[8], None))
    monkeypatch.setattr(cae, "pre_motion_frame", lambda *a, **kw: (None, None, "stop_after_bias_check"))
    monkeypatch.setattr(cap_main, "Guarded", lambda *a: object())
    cfg = {
        "calibrate": {"blend_bias": True},
        "calibration_path": str(tmp_path / "cal.json"),
        "sites": {"pinky": {"start": [0.1, 0.1], "place": [0.1, 0.1], "yaw_deg": 0.0}},
    }
    cell = type("C", (), {"act": lambda self, cmd: {"ok": True}, "frame": lambda self, cam: None})()
    cap_main.run_auto(cell, cfg, {"sites": {}}, tmp_path / "cal.json", [], [0, 0, 100, 100],
                      "pinky", "pinky", tmp_path, cell_choices.Choices(tmp_path / "ch.json"), dry_run=False, attempts=1)
    assert len(choose_calls) == 1  # blend=True matched target["bias_region"], so choose() was not called twice
    assert bias_calls == [(False, True), (False, True)]
    assert orig_bias_at is not None
