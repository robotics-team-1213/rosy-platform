"""cell_calibrate: a clear pivot point is found next to a target; a moved camera makes every later step stale."""
import hashlib
import json
import math
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))
import cell_attempts  # noqa: E402
import cell_calibrate as cc  # noqa: E402

ROI = (0, 0, 400, 400)


def test_bound_map_reference_uses_saved_jpeg_and_interrupted_publish_fails_closed(tmp_path, monkeypatch):
    cv2 = pytest.importorskip("cv2")
    cal_path, ref_path = tmp_path / "map.json", tmp_path / "reference.jpg"
    config = {"sites": {"pinky": {"auto_roi": [0, 0, 30, 30], "surface_px": None}}}
    calibration = {"schema": cc.cal.SCHEMA, "sites": {"pinky": {"homography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}}}
    first = np.full((32, 32, 3), 80, np.uint8)
    cc.save_bound_map_reference(cal_path, ref_path, calibration, config, first)
    saved = json.loads(cal_path.read_text())
    assert saved["reference_top_sha256"] == hashlib.sha256(ref_path.read_bytes()).hexdigest()
    assert saved["reference_map_sha"] == cell_attempts.digest(saved["sites"])
    old_cal, old_ref = cal_path.read_bytes(), ref_path.read_bytes()
    monkeypatch.setattr(cv2, "imwrite", lambda *_: False)
    with pytest.raises(OSError, match="JPEG write failed"):
        cc.save_bound_map_reference(cal_path, ref_path, calibration, config, first)
    assert cal_path.read_bytes() == old_cal and ref_path.read_bytes() == old_ref
    monkeypatch.undo()
    original_replace = Path.replace

    def interrupted(self, target):
        if self.name == "map.pending.json":
            raise OSError("interrupted before map publish")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", interrupted)
    changed = json.loads(old_cal)
    changed["sites"]["pinky"]["note"] = "new map"
    with pytest.raises(OSError, match="interrupted"):
        cc.save_bound_map_reference(cal_path, ref_path, changed, config, np.full_like(first, 150))
    assert cal_path.read_bytes() == old_cal
    assert hashlib.sha256(ref_path.read_bytes()).hexdigest() != saved["reference_top_sha256"]


def test_consensus_repair_rebinds_the_existing_camera_reference(tmp_path, monkeypatch):
    cv2 = pytest.importorskip("cv2")
    cal_path, ref_path = tmp_path / "map.json", tmp_path / "reference.jpg"
    points = [{"pixel": [i * 10, i * 10 + 1], "arm_m": [i / 100, i / 100 + 0.01]}
              for i in range(5)]
    config = {"sites": {"pinky": {"auto_roi": [0, 0, 32, 32]}},
              "calibrate": {"map_sites": ["pinky"]}, "preflight": {"reference_top": str(ref_path)},
              "calibration_path": str(cal_path), "plan_path": str(tmp_path / "plan.json"),
              "work_dir": str(tmp_path), "io": str(tmp_path), "cameras": {"top": "http://unused"}}
    (tmp_path / "plan.json").write_text("{}")
    cc.save_bound_map_reference(cal_path, ref_path, {"schema": cc.cal.SCHEMA,
        "sites": {"pinky": {"points": points, "homography": np.eye(3).tolist()}}}, config,
        np.full((32, 32, 3), 80, np.uint8))
    before = json.loads(cal_path.read_text())
    import cell_pipeline as cp
    monkeypatch.setattr(cp, "FifoCell", lambda *_: type("Cell", (), {"frame": lambda self, _: np.full((32, 32, 3), 80, np.uint8)})())
    monkeypatch.setattr(cc, "check", lambda *_: {"consensus_repairable": True})
    monkeypatch.setattr(cc, "stale", lambda *_: ["consensus-repair"])
    monkeypatch.setattr(cc, "consensus", lambda points, _: points)
    monkeypatch.setattr(cc, "enough_agree", lambda *_: True)
    monkeypatch.setattr(cc.cal, "fit", lambda *_: np.eye(3) * 2)
    monkeypatch.setattr(cc.cal, "loo_error_mm", lambda *_: {"max": 1.0})
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    assert cc.main(["--config", str(config_path), "auto", "--commissioning", "--person-at-switch"]) == 0
    repaired = json.loads(cal_path.read_text())
    assert repaired["sites"] != before["sites"]
    assert repaired["reference_map_sha"] == cell_attempts.digest(repaired["sites"])
    assert repaired["reference_top_sha256"] == hashlib.sha256(ref_path.read_bytes()).hexdigest()
    repaired_bytes = cal_path.read_bytes()
    assert cv2.imwrite(str(ref_path), np.full((32, 32, 3), 120, np.uint8))
    assert cc.main(["--config", str(config_path), "auto", "--commissioning", "--person-at-switch"]) == 0
    assert cal_path.read_bytes() == repaired_bytes


def to_px(p):  # 1 px per mm, arm (0, 0.2) at pixel (200, 200)
    return (200 + p[0] * 1000, 200 + (p[1] - 0.2) * 1000)


def test_the_nearest_clear_point_avoids_the_box_and_stays_on_the_surface():
    mask = np.zeros((400, 400), np.uint8)
    mask[185:216, 185:216] = 255  # a 30 mm box at the target
    inside = np.ones((400, 400), np.uint8)
    inside[:, 260:] = 0  # the surface ends 60 mm to the +x side (a board beyond)
    p = cc.clear_point((0.0, 0.2), mask, ROI, inside, to_px, radius_px=30, reach_m=1.0)
    assert p is not None
    x, y = to_px(p)
    assert not mask[int(y) - 30:int(y) + 30, int(x) - 30:int(x) + 30].any() and x + 30 < 260
    assert cc.clear_point((0.0, 0.2), np.full((400, 400), 255, np.uint8), ROI, inside, to_px) is None  # nothing clear


def test_a_moved_camera_makes_the_map_regions_and_every_bias_stale():
    moved = cc.stale({"camera_moved": True, "targets": ["floor:-0.03,0.17"], "missing_bias": [], "missing_surface": []})
    assert moved == ["remap", "regions", "pivot-near floor:-0.03,0.17"]
    still = cc.stale({"camera_moved": False, "targets": [], "missing_bias": ["pinky:0.04,0.22"], "missing_surface": ["belt"]})
    assert still == ["pivot-near pinky:0.04,0.22", "surface belt"]
    assert cc.stale({"camera_moved": False, "missing_bias": [], "missing_surface": []}) == []


def test_reference_bytes_must_match_the_bound_calibration_before_camera_check(tmp_path, monkeypatch):
    cv2 = pytest.importorskip("cv2")
    import cell_preflight

    reference = tmp_path / "reference.jpg"
    assert cv2.imwrite(str(reference), np.full((32, 32, 3), 80, np.uint8))
    expected = hashlib.sha256(reference.read_bytes()).hexdigest()
    config = {"preflight": {"reference_top": str(reference)},
              "calibration_path": str(tmp_path / "map.json"), "sites": {}}
    monkeypatch.setattr(cell_preflight, "camera_shift_px", lambda *_: {"ok": True, "max_px": 0})
    calibration = {"sites": {}, "reference_top_sha256": expected,
                   "reference_map_sha": cell_attempts.digest({}),
                   "reference_geometry_sha": cell_attempts.digest({})}
    assert cc.check(config, calibration, [], np.full((32, 32, 3), 80, np.uint8))["camera_moved"] is False
    assert cv2.imwrite(str(reference), np.full((32, 32, 3), 120, np.uint8))
    found = cc.check(config, calibration, [], np.full((32, 32, 3), 80, np.uint8))
    assert found["camera_moved"] is True
    assert found["map_binding_error"] == "top camera map reference changed"
    assert cc.stale(found)[:2] == ["remap", "regions"]
    config["preflight"]["reference_sha256"] = expected
    assert cc.check(config, {"sites": {}}, [], np.full((32, 32, 3), 80, np.uint8))["map_binding_error"]
    config["preflight"].pop("reference_sha256")
    unbound = cc.check(config, {"sites": {}}, [], np.full((32, 32, 3), 80, np.uint8))
    assert unbound["map_binding_error"]
    assert unbound["camera_moved"] is True
    assert cv2.imwrite(str(reference), np.full((32, 32, 3), 80, np.uint8))
    changed_map = dict(calibration, sites={"floor": {}})
    assert cc.check(config, changed_map, [], np.full((32, 32, 3), 80, np.uint8))["map_binding_error"] == "top camera calibration changed"


def test_over_target_pivots_right_above_the_box_only_when_the_jaws_clear_its_top(tmp_path, monkeypatch):
    import cell_pivot

    seen = []
    monkeypatch.setattr(cell_pivot, "pivot_calibrate", lambda cell, config, point, *a: seen.append(point) or {"result": "stopped"})
    monkeypatch.setattr(cc, "auto_pivot_point", lambda *a: None)  # no clear floor point in this scene
    config = {"params": {"pivot.over_target": 1}, "pivot": {"z_view": 0.08}, "coarse": {"z_view": 0.118},
              "sites": {"floor": {"yaw_deg": 0.0, "surface_z": 0.006}}}
    far = {"regions": [{"site": "floor", "point_m": [0.0, 0.25], "bias_mm": [16.9, 0.0]}]}  # 50 mm away: not near enough
    _, problem = cc.self_calibrate(object(), config, {}, tmp_path / "cal.json", "floor", (0.0, 0.2), [{"raw_m": [0.0, 0.2]}],
                                   tmp_path, far, None, None)
    assert seen == [(0.0, 0.2)] and problem == "pivot: stopped"  # right over the target, even with the box there
    config["pivot"]["z_view"] = 0.06  # jaws 24 mm over a 30 mm box top on a 6 mm floor: below the 30 mm clearance
    config["params"]["pivot.clear_above_m"] = 0.05  # (the default would raise the view to 0.08 by itself)
    seen.clear()
    cc.self_calibrate(object(), config, {}, tmp_path / "cal.json", "floor", (0.0, 0.2), [{"raw_m": [0.0, 0.2]}],
                      tmp_path, far, None, None)
    assert (0.0, 0.2) not in seen


def test_the_pivot_view_height_follows_each_sites_surface():
    """2026-10-29: an absolute 0.08 m view (tuned on the floor) swung the jaws 3 mm over a box on the Pinky tray."""
    import cell_pivot

    config = {"params": None, "pivot": {"z_view": 0.08}, "coarse": {"z_view": 0.118},
              "sites": {"floor": {"surface_z": 0.006}, "pinky": {"surface_z": 0.0467}, "odd": {}}}
    assert cell_pivot.pivot_z_view(config, "floor") == 0.08
    assert cell_pivot.pivot_z_view(config, "pinky") == pytest.approx(0.1207)
    assert cell_pivot.pivot_z_view(config, "odd") == 0.08  # no surface known: as configured


def test_a_region_carried_from_another_site_does_not_skip_the_pivot(tmp_path, monkeypatch):
    """2026-10-30: the Pinky tray's region was the floor's bias copied over; the pivot was skipped and the pick came
    down on the box top."""
    import cell_pivot

    seen = []
    monkeypatch.setattr(cell_pivot, "pivot_calibrate", lambda cell, config, point, *a: seen.append(point) or {"result": "stopped"})
    config = {"params": {"pivot.over_target": 1}, "pivot": {}, "coarse": {"z_view": 0.08},
              "sites": {"pinky": {"yaw_deg": -67.8, "surface_z": 0.0467}}}
    region = {"site": "pinky", "point_m": [0.05, 0.2], "bias_mm": [4.2, -2.5], "measured": "2026-10-29",
              "source": "carried from the floor pivot on the same remapped top camera map"}
    args = ({}, tmp_path / "cal.json", "pinky", (0.0694, 0.2137), [{"raw_m": [0.0694, 0.2137]}], tmp_path)
    _, problem = cc.self_calibrate(object(), config, *args, {"regions": [region]}, None, None)
    assert seen == [(0.0694, 0.2137)] and problem == "pivot: stopped"
    fitted = {k: v for k, v in region.items() if k != "source"}  # the same region measured there: no pivot
    seen.clear()
    assert cc.self_calibrate(object(), config, *args, {"regions": [fitted]}, None, None)[1] is None and seen == []


def test_the_auto_pivot_point_judges_clutter_against_the_sites_measured_surface(monkeypatch):
    pytest.importorskip("cv2")
    import cell_objects
    import cell_observe
    seen = {}

    def foreground(img, roi, **kw):
        seen.update(kw)
        return np.zeros((roi[3] - roi[1], roi[2] - roi[0]), np.uint8)

    monkeypatch.setattr(cell_objects, "foreground", foreground)
    monkeypatch.setattr(cell_observe, "predicted_pixel", lambda c, k, s, p: to_px(p))
    cell = type("Cell", (), {"frame": lambda self, name: np.zeros((480, 640, 3), np.uint8)})()
    site = {"surface_lab": [74, 135, 88], "surface_px": [[0, 0], [399, 0], [399, 399], [0, 399]], "auto_roi": [100, 100, 300, 300]}
    assert cc.auto_pivot_point(cell, {"sites": {"pallet": site}}, {}, "pallet", (0.0, 0.2)) is not None
    assert seen["surface_lab"] == [74, 135, 88] and seen["surface_px"] == site["surface_px"]


def test_a_pivot_near_a_packed_column_goes_over_it_only_when_the_jaws_clear_both_layers():
    """2026-11-01: no 72 px empty patch beside the packed pallet columns (65-71 mm tall), so pivot-near marks the jaws
    right over the target, which needs the view height raised above the default 80 mm."""
    config = {"params": {"pivot.over_target": 1, "pivot.over_top_mm": 71.0}, "pivot": {"z_view": 0.08},
              "coarse": {"z_view": 0.118}, "sites": {"pallet": {"surface_z": -0.01}}}
    assert not cc.over_target(config, "pallet")  # 90 mm above the pallet, 19 mm over the top: below 30
    config["pivot"]["z_view"] = 0.10
    assert cc.over_target(config, "pallet")
    config["params"]["pivot.over_target"] = 0
    assert not cc.over_target(config, "pallet")


def test_a_pivot_over_a_packed_column_keeps_its_yaws_inside_the_arc_that_marked():
    """2026-11-02: over the packed pallet only base -40..+40 marked, so 4 marks need the narrower 20 degree set."""
    config = {"params": {"pivot.over_target": 1, "pivot.over_top_mm": 71.0}, "pivot": {"z_view": 0.10},
              "coarse": {"z_view": 0.118}, "sites": {"pallet": {"surface_z": -0.01, "yaw_deg": 90}}}
    over = cc.pivot_near_yaws(config, "pallet")
    assert over == [30, 50, 70, 90, 110, 130, 150] and sum(50 <= y <= 130 for y in over) >= 4
    config["params"]["pivot.over_target"] = 0
    assert cc.pivot_near_yaws(config, "pallet") == [10, 50, 90, 130, 170, 210]


def test_a_jaw_mark_split_into_pieces_over_a_box_top_counts_once_merged_and_noise_does_not():
    """2026-11-02: over a packed column the gripper body hid the fingers; the open-closed change came as 72, 165 and
    260 px pieces a few px apart, each under min_blob 300, and the pivot marked nothing."""
    pytest.importorskip("cv2")
    import cell_pivot

    closed = np.zeros((200, 200, 3), np.uint8)
    opened = closed.copy()
    opened[100:104, 80:104] = 255  # three pieces of one finger's change, 2-3 px apart
    opened[106:114, 75:99] = 255
    opened[116:131, 80:96] = 255
    assert cell_pivot.jaw_blobs(closed, opened, {"pivot.merge_px": 0}) == []
    merged = cell_pivot.jaw_blobs(closed, opened, {"pivot.merge_px": 3})
    assert len(merged) == 1 and merged[0][2] >= 300
    noise = closed.copy()
    for x in range(10, 190, 20):  # scattered 4x4 specks, 16 px apart: not one mark at any merge
        noise[50:54, x:x + 4] = 255
    assert cell_pivot.jaw_blobs(closed, noise, {"pivot.merge_px": 3}) == []


def test_a_remap_serves_the_sites_the_config_names_and_arm_a_keeps_its_three():
    """2026-11-02: arm B's pallet cell has no floor site; its remap is named by calibrate.map_sites."""
    arm_a = {"sites": {"floor": {}, "belt": {}, "board": {}}}
    assert cc.map_sites(arm_a) == ["floor", "belt"]
    arm_b = {"calibrate": {"map_sites": ["pallet", "stack"]}, "sites": {"pallet": {}, "stack": {}}}
    assert cc.map_sites(arm_b) == ["pallet", "stack"]


def test_an_arm_with_no_map_for_its_sites_is_remapped():
    """arm_a joined the pallet cell on 2026-11-03 with no pallet map; the camera had not moved, so nothing ran."""
    config = {"sites": {"pallet": {"surface_z": -0.01}}, "calibrate": {"map_sites": ["pallet"]}, "calibration_path": "x.json"}
    found = {"camera_moved": False, "targets": [], "missing_bias": [], "missing_surface": [],
             "missing_map": [s for s in cc.map_sites(config) if s not in {}]}
    assert found["missing_map"] == ["pallet"] and cc.stale(found)[:2] == ["remap", "regions"]


def test_a_map_whose_marks_disagree_is_not_kept():
    assert cc.map_agrees({"loo_error_mm": {"max": 5.2, "mean": 3.1}})
    assert not cc.map_agrees({"loo_error_mm": {"max": 52.34, "mean": 26.81}})  # arm_a 2026-11-04 over the boxes


def test_marks_so_far_predict_where_the_next_jaws_show():
    """arm_a 2026-11-04: the x=0.09 column marked cleanly; later blobs 50-80 px off were the shaking link."""
    marks = [((489.5, 331.7), (0.09, 0.08)), ((490.3, 363.3), (0.09, 0.10)), ((443.1, 332.6), (0.11, 0.08))]
    assert cc.predicted(marks[:2], (0.11, 0.10)) is None
    px = cc.predicted(marks, (0.11, 0.10))
    assert abs(px[0] - 444) < 3 and abs(px[1] - 364) < 3  # not the (434.7, 286.3) blob the remap took


def test_marks_on_one_line_predict_nothing():
    """arm_a 2026-11-04: three marks all at x=0.09 'predicted' every later point at x=0.09."""
    line = [((489.0, 331.5), (0.09, 0.08)), ((490.1, 363.5), (0.09, 0.10)), ((497.5, 395.2), (0.09, 0.12))]
    assert cc.predicted(line, (0.13, 0.10)) is None


def test_a_refused_move_folds_and_keeps_the_marks_so_far(tmp_path, monkeypatch):
    """arm_b 2026-11-05: 8 marks in, the next goto stalled on wrist roll -13; the remap threw them all away."""
    import types

    monkeypatch.setitem(sys.modules, "cell_pipeline", types.SimpleNamespace(write_library=lambda c, p, q, path: path))
    monkeypatch.setattr(cc.cell_pivot, "mark_jaws", lambda cell, config, near=None, **kw: to_px(cell.at))
    points = [[0.10, 0.10], [0.12, 0.12], [0.10, 0.14], [0.14, 0.10], [0.15, 0.15], [0.17, 0.12], [0.30, 0.30]]

    class Cell:
        def __init__(self, park_ok=True):
            self.at, self.cmds, self.park_ok, self.next = None, [], park_ok, None

        def frame(self, camera):
            return np.zeros((48, 64, 3), np.uint8)

        def act(self, command):
            self.cmds.append(command)
            if command.startswith("load"):
                self.next = next(p for p in points if f"remap-{sorted(points, key=lambda q: math.hypot(*q)).index(p)}." in command)
            if command == "goto above_pick":
                if self.next == [0.30, 0.30]:
                    return {"ok": False, "error": "contact in goto above_pick: wrist_roll lag"}
                self.at = self.next
            return {"ok": command != "park" or self.park_ok}

    config = {"coarse": {"z_view": 0.14}, "plan": {"approach_m": 0.04}, "sites": {"pallet": {"yaw_deg": 0.0}},
              "calibrate": {"map_sites": ["pallet"]}}
    cell, rows, seen = Cell(), [], []
    record = cc.remap(cell, config, points, tmp_path, log=rows.append,
                      at_stop=lambda state, status: seen.append((list(cell.cmds), status)))
    assert len(record["points"]) == 6 and cell.cmds[-1] == "park"
    # 2026-11-14: the stop's evidence is taken before the fold, and the log says what the runner said
    assert len(seen) == 1 and "park" not in seen[0][0] and "wrist_roll lag" in seen[0][1]["error"]
    assert any("wrist_roll lag" in str(row.get("error")) for row in rows if "stopped" in row)
    broken = cc.remap(Cell(), config, points, tmp_path, log=lambda row: None, at_stop=lambda *a: 1 / 0)
    assert len(broken["points"]) == 6  # a failing evidence hook still folds and keeps the marks
    import time

    monkeypatch.setattr(cc, "AT_STOP_S", 0.05)
    started = time.monotonic()
    stuck = cc.remap(Cell(), config, points, tmp_path, log=lambda row: None, at_stop=lambda *a: time.sleep(5))
    assert len(stuck["points"]) == 6 and time.monotonic() - started < 2  # a stuck camera does not hold the fold
    with pytest.raises(SystemExit, match="park failed"):
        cc.remap(Cell(park_ok=False), config, points, tmp_path, log=lambda row: None)


SCATTER = [(0, 0), (90, 0), (0, 90), (90, 90), (-90, 40), (40, -90), (-60, -60), (120, 30)]
GRID = [(0.10, 0.10), (0.12, 0.12), (0.10, 0.14), (0.14, 0.10), (0.15, 0.15), (0.17, 0.12), (0.13, 0.17), (0.18, 0.09)]


def test_consensus_keeps_the_larger_group_when_the_mark_flips_sides():
    marks = [(to_px(p), p) for p in GRID[:6]] + [((to_px(p)[0] + 70, to_px(p)[1] + 15), p) for p in GRID[6:]]
    assert cc.consensus(marks, 15.0) == marks[:6]
    assert cc.consensus(marks[:2], 15.0) == marks[:2]


def test_a_remap_recovers_when_its_first_marks_flip_and_reports_what_it_dropped(tmp_path, monkeypatch):
    """arm_b 2026-11-06: the first three marks mixed both groups and the prediction threw away every later mark."""
    import types

    monkeypatch.setitem(sys.modules, "cell_pipeline", types.SimpleNamespace(write_library=lambda c, p, q, path: path))
    points = sorted(GRID, key=lambda q: math.hypot(*q))
    flipped, gates = {points[1]}, []

    class Cell:
        def __init__(self):
            self.i = -1

        def frame(self, camera):
            return np.zeros((48, 64, 3), np.uint8)

        def act(self, command):
            self.i += command.startswith("load")
            return {"ok": True}

    def mark(cell, config, near=None, **kw):
        gates.append(near)
        p = points[cell.i]
        x, y = to_px(p)
        return (x + 70, y + 15) if p in flipped else (x, y)

    monkeypatch.setattr(cc.cell_pivot, "mark_jaws", mark)
    config = {"coarse": {"z_view": 0.14}, "plan": {"approach_m": 0.04}, "sites": {"pallet": {"yaw_deg": 0.0}},
              "calibrate": {"map_sites": ["pallet"]}}
    rows = []
    record = cc.remap(Cell(), config, [list(p) for p in points], tmp_path, log=rows.append)
    assert len(record["points"]) == 7 and [d["arm_m"] for d in record["dropped_marks"]] == [list(points[1])]
    assert record["loo_error_mm"]["max"] < 1.0 and gates[:4] == [None] * 4 and gates[-1] is not None
    assert any("dropped_marks" in row for row in rows)


def test_too_few_marks_that_agree_stop_the_remap_with_no_map(tmp_path, monkeypatch):
    import types

    monkeypatch.setitem(sys.modules, "cell_pipeline", types.SimpleNamespace(write_library=lambda c, p, q, path: path))
    points = sorted(GRID, key=lambda q: math.hypot(*q))

    class Cell:
        def __init__(self):
            self.i = -1

        def frame(self, camera):
            return np.zeros((48, 64, 3), np.uint8)

        def act(self, command):
            self.i += command.startswith("load")
            return {"ok": True}

    monkeypatch.setattr(cc.cell_pivot, "mark_jaws", lambda cell, config, near=None, **kw: (
        (to_px(points[cell.i])[0] + SCATTER[cell.i][0], to_px(points[cell.i])[1] + SCATTER[cell.i][1])))
    config = {"coarse": {"z_view": 0.14}, "plan": {"approach_m": 0.04}, "sites": {"pallet": {"yaw_deg": 0.0}},
              "calibrate": {"map_sites": ["pallet"]}}
    with pytest.raises(SystemExit, match="agree of 8"):
        cc.remap(Cell(), config, [list(p) for p in points], tmp_path, log=lambda row: None)


def test_a_scene_that_changed_during_the_remap_saves_no_map(tmp_path, monkeypatch):
    import types

    monkeypatch.setitem(sys.modules, "cell_pipeline", types.SimpleNamespace(write_library=lambda c, p, q, path: path))
    points = sorted(GRID, key=lambda q: math.hypot(*q))

    class Cell:
        def __init__(self):
            self.i, self.parked = -1, False

        def frame(self, camera):
            view = np.zeros((480, 640, 3), np.uint8)
            if self.parked:  # a box pushed while the arm was out
                view[100:200, 100:160] = (20, 90, 220)
            return view

        def act(self, command):
            self.i += command.startswith("load")
            self.parked |= command == "park"
            return {"ok": True}

    monkeypatch.setattr(cc.cell_pivot, "mark_jaws", lambda cell, config, near=None, **kw: to_px(points[cell.i]))
    config = {"coarse": {"z_view": 0.14}, "plan": {"approach_m": 0.04}, "sites": {"pallet": {"yaw_deg": 0.0}},
              "calibrate": {"map_sites": ["pallet"]}}
    with pytest.raises(SystemExit, match="scene changed"):
        cc.remap(Cell(), config, [list(p) for p in points], tmp_path, log=lambda row: None)
    kept = sorted(p.name for p in next((tmp_path / "remap-frames").iterdir()).iterdir())
    assert "before.jpg" in kept and "after.jpg" in kept and "07.jpg" in kept


def test_a_map_only_a_minority_of_the_marks_agree_on_is_refused():
    assert cc.enough_agree(5, 8) and cc.enough_agree(5, 9)
    assert not cc.enough_agree(5, 10)  # half: either side of the jaws could be the true one
    assert not cc.enough_agree(4, 4)


def test_colour_diff_marks_black_finger_over_iso_luma_orange_background():
    """2026-11-15: black fingers over orange/pink can match in grey luminance; channel-max diff still marks them."""
    cv2 = pytest.importorskip("cv2")
    import cell_pivot

    bg, finger = (0, 48, 73), (50, 50, 50)  # both ~50 in BGR->GRAY; B channel differs by 50 > diff_px (30)
    closed = np.full((200, 200, 3), bg, np.uint8)
    opened = closed.copy()
    closed[100:125, 100:125] = finger
    grey_diff = cv2.absdiff(cv2.cvtColor(closed, cv2.COLOR_BGR2GRAY), cv2.cvtColor(opened, cv2.COLOR_BGR2GRAY))
    assert int(grey_diff.max()) <= 1
    assert cell_pivot.jaw_blobs(closed, opened) == []  # the grey mask (settling, jaw axis) is unchanged
    blobs = cell_pivot.jaw_blobs(closed, opened, colour=True)  # mark_jaws' fallback
    assert len(blobs) == 1 and blobs[0][:2] == pytest.approx((112.0, 112.0), abs=1.0)


def test_mark_jaws_keep_writes_evidence_and_reports_no_changed_blob(tmp_path, monkeypatch):
    pytest.importorskip("cv2")
    import json
    import types
    import cell_pivot

    monkeypatch.setitem(sys.modules, "cell_pipeline", types.SimpleNamespace(grip_to=lambda cell, v: True))
    cell = types.SimpleNamespace(frame=lambda cam: np.zeros((100, 100, 3), np.uint8))
    config = {"plan": {"grip_open": 62.0}, "jaw_mark": {"closed": 50.5, "open": 62.0}}
    keep_dir, report = tmp_path / "keep", {}
    assert cell_pivot.mark_jaws(cell, config, sleep=lambda s: None, max_marks=2, keep=keep_dir, report=report) is None
    assert report["reason"] == "no changed blob"
    for i in range(2):
        for suffix in ("closed.jpg", "open.jpg", "mask.png", "json"):
            name = f"try-{i:02d}.{suffix}" if suffix == "json" else f"try-{i:02d}-{suffix}"
            assert (keep_dir / name).exists()
    info = json.loads((keep_dir / "try-00.json").read_text())
    assert info["blobs"] == [] and info["picked"] is None and info["rejected"] == "no changed blob"


# 2026-11-14 arm_b remap: its printed wrist holder touched link3/4 at wrist_flex 59.3 (real fixtures: the Plan C run
# config, the arm_b grasp plan; the arm's joint_max is the logged wrist window, never above 55.3)
FIX = ROOT / "test/fixtures/omx_arm_b_remap"


def arm_b(z_view=None, points="plan_c"):
    pytest.importorskip("yaml")
    config = json.loads((FIX / "config-planc.json").read_text())
    config["plan"] = json.loads((FIX / "plan.json").read_text())
    if z_view is not None:
        config["coarse"]["z_view"] = z_view
    if points is None:
        del config["calibrate"]["map_points"]
    return config


def test_a_wrist_flex_of_56_is_refused_before_motion_naming_joint_value_and_limit(tmp_path, monkeypatch):
    import types

    import cell_pipeline_io as cio

    library = {"names": ["wrist_flex.pos"], "chunks": {"above_pick": [[56.0]]}}
    planner = types.SimpleNamespace(Planner=lambda plan: types.SimpleNamespace(library=lambda: library))
    monkeypatch.setitem(sys.modules, "grasp_planner", planner)
    with pytest.raises(SystemExit, match=r"wrist_flex.pos target 56.0 is over this arm's joint_max 55.3"):
        cio.write_library(arm_b() | {"plan": {}}, {}, {}, tmp_path / "lib.json")
    assert not (tmp_path / "lib.json").exists()


def test_arm_b_default_remap_points_are_refused_with_the_failing_list():
    config = arm_b(z_view=0.14)  # the arm_b stack hover
    rows = cc.rp.plan(config, cc.MAP_POINTS)
    message = cc.rp.refusal(rows)
    bad = [r["point"] for r in rows if r["error"]]
    assert bad and message.startswith(f"remap refused, {len(bad)} of 12 points") and "wrist_flex.pos" in message
    assert [0.066, 0.195] in bad and all(str(p) in message for p in bad)


def test_the_plan_c_points_pass_the_arm_b_window():
    rows = cc.rp.plan(arm_b(), arm_b()["calibrate"]["map_points"])
    assert cc.rp.refusal(rows) is None and len(rows) == 5
    assert max(r["above_pick"]["wrist_flex.pos"] for r in rows) <= 55.3
    assert cc.rp.refusal(cc.rp.plan(arm_b(z_view=0.14), arm_b()["calibrate"]["map_points"]))  # the old hover fails


def test_plan_only_opens_no_port_and_exits_2_on_a_refusal(tmp_path, monkeypatch, capsys):
    import socket

    import cell_pipeline

    def no_open(*a, **k):
        raise AssertionError("plan-only opened a camera, FIFO or port")

    monkeypatch.setattr(cell_pipeline, "FifoCell", no_open)
    monkeypatch.setattr(socket.socket, "connect", no_open)
    for label, kw, code in (("plan_c", {}, 0), ("default", {"z_view": 0.14, "points": None}, 2)):
        config = {k: v for k, v in arm_b(**kw).items() if k != "plan"}
        config["plan_path"] = str(FIX / "plan.json")
        path = tmp_path / f"{label}.json"
        path.write_text(json.dumps(config))
        assert cc.main(["--config", str(path), "auto", "--plan-only"]) == code
        out = json.loads(capsys.readouterr().out)
        assert len(out["plan_only"]) == (5 if code == 0 else 12) and bool(out["refused"]) == bool(code)
        assert all("above_pick" in row for row in out["plan_only"])


# 2026-11-14 arm_a remap (camera_moved, max_px 29.5). 2026-11-15 read-only check of the real cell-arm-a-stack.json: pallet
# yaw 0, its plan equals arm_b's except grip_closed, no window in the config (the wrist window comes from logs), pallet rows
# at +y (map_points y 0.08-0.12); the fixture takes five of those points and arm_b's plan.json
FIX_A = ROOT / "test/fixtures/omx_arm_a_remap"


def arm_a(z_view=None, window=None):
    pytest.importorskip("yaml")
    config = json.loads((FIX_A / "config-planb.json").read_text())
    config["plan"] = json.loads((FIX / "plan.json").read_text())
    if z_view is not None:
        config["coarse"]["z_view"] = z_view
    if window is not None:
        config["joint_max"] = {"wrist_flex.pos": window}
    return config


def test_the_arm_a_points_pass_its_window_with_room_under_the_contact_at_60():
    config = arm_a()
    points = config["calibrate"]["map_points"]
    rows = cc.rp.plan(config, points)
    assert cc.rp.refusal(rows) is None and len(rows) == 5
    wrist = [r["above_pick"]["wrist_flex.pos"] for r in rows]
    assert 45 <= min(wrist) and max(wrist) <= 55.3  # also under arm_b's more careful bound
    assert all(math.hypot(*p) <= 0.18 for p in points)  # arm_a's wrist hit 95% of its cap at r 0.206
    assert all(0.09 <= x <= 0.13 and 0.08 <= y <= 0.12 for x, y in points)  # arm_a's real pallet rows, not arm_b's y 0
    assert config["tcp_x_m"] == 0.074 and config["sites"]["pallet"]["yaw_deg"] == 0
    assert cc.rp.refusal(cc.rp.plan(arm_a(window=51.5), points))  # the window really is the judge


def test_arm_a_default_points_are_refused_for_reach_not_for_the_window():
    config = arm_a(z_view=0.14)
    assert config["calibrate"]["max_reach_m"] == 0.18  # 2026-11-04 arm-a-pallet-map.md: wrist at 95% of its cap at r 0.206
    rows = cc.rp.plan(config, cc.MAP_POINTS)
    far = [r for r in rows if math.hypot(*r["point"]) > 0.18]
    assert len(far) >= 6 and all("beyond max_reach_m 0.18" in r["error"] for r in far)
    assert all(not r["error"] for r in rows if r not in far)  # the wrist window alone passes every default point
    message = cc.rp.refusal(rows)
    assert message and all(str(r["point"]) in message and f"r {math.hypot(*r['point']):.3f}" in message for r in far)
    strict = cc.rp.refusal(cc.rp.plan(arm_a(z_view=0.14, window=55.3), cc.MAP_POINTS))
    assert strict and "wrist_flex.pos" in strict  # the arm_b bound would refuse some of them
    del config["calibrate"]["max_reach_m"]
    assert cc.rp.refusal(cc.rp.plan(config, cc.MAP_POINTS)) is None and cc.rp.reach_note(config) == "no reach check"


def test_plan_only_accepts_the_arm_a_point_set(tmp_path, monkeypatch, capsys):
    import socket

    import cell_pipeline

    def no_open(*a, **k):
        raise AssertionError("plan-only opened a camera, FIFO or port")

    monkeypatch.setattr(cell_pipeline, "FifoCell", no_open)
    monkeypatch.setattr(socket.socket, "connect", no_open)
    config = {k: v for k, v in arm_a().items() if k != "plan"}
    config["plan_path"] = str(FIX / "plan.json")
    path = tmp_path / "arm_a.json"
    path.write_text(json.dumps(config))
    assert cc.main(["--config", str(path), "auto", "--plan-only"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out["plan_only"]) == 5 and out["refused"] is None and out["reach"] == "max_reach_m 0.18"
    del config["calibrate"]["max_reach_m"]  # missing limit: said so, never defaulted
    path.write_text(json.dumps(config))
    assert cc.main(["--config", str(path), "auto", "--plan-only"]) == 0
    assert json.loads(capsys.readouterr().out)["reach"] == "no reach check"
