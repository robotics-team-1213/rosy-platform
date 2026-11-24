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
    monkeypatch.setattr(cc, "auto_pivot_point", lambda *a: None)  # no clear tray point: over the box is the fallback
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
    config["sites"]["pallet"]["pivot_yaws"] = [25, 45, 155]
    assert cc.pivot_near_yaws(config, "pallet") == [25, 45, 155]
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


def test_a_one_jaw_map_is_remapped_when_the_config_asks_for_a_tcp_map():
    """2026-11-17 arm_a: the 11-15 map followed one jaw; with calibrate.tcp_marks it must be measured again."""
    one_jaw = {"sites": {"pallet": {"homography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}}}
    tcp_map = {"sites": {"pallet": {"homography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "marks": "tcp"}}}
    asks = {"calibrate": {"tcp_marks": True}}
    assert cc.rp.missing_maps(asks, one_jaw, ["pallet"]) == ["pallet"]
    assert cc.rp.missing_maps(asks, tcp_map, ["pallet"]) == []
    assert cc.rp.missing_maps({}, one_jaw, ["pallet"]) == []  # without the key, as before
    assert cc.rp.missing_maps({}, {"sites": {}}, ["pallet"]) == ["pallet"]


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
    assert len(seen) == 1 and "park" not in seen[0][0][1:] and "wrist_roll lag" in seen[0][1]["error"]
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
            if self.i >= 0:  # a box pushed while the arm was out
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


def test_remap_parks_before_reference_and_ignores_moving_belt(tmp_path, monkeypatch):
    import types

    monkeypatch.setitem(sys.modules, "cell_pipeline", types.SimpleNamespace(write_library=lambda c, p, q, path: path))
    points = sorted(GRID, key=lambda q: math.hypot(*q))

    class Cell:
        def __init__(self):
            self.i, self.parked = -1, False

        def frame(self, camera):
            view = np.zeros((480, 640, 3), np.uint8)
            if not self.parked:  # unparked entry arm pose must not pollute `before`
                view[20:120, 300:400] = (200, 200, 200)
            if self.i >= 0:  # running belt + configured ignore rect
                view[90:200, 320:500] = (180, 180, 180)
                view[10:80, 10:60] = (180, 180, 180)
            return view

        def act(self, command):
            self.i += command.startswith("load")
            self.parked = command == "park"
            return {"ok": True}

    monkeypatch.setattr(cc.cell_pivot, "mark_jaws", lambda cell, config, near=None, **kw: to_px(points[cell.i]))
    config = {
        "coarse": {"z_view": 0.14}, "plan": {"approach_m": 0.04},
        "sites": {"pallet": {"yaw_deg": 0.0}, "belt": {"moving_px": [291, 83, 638, 265]}},
        "scene_ignore_px": [[0, 0, 75, 300]],
        "calibrate": {"map_sites": ["pallet"]},
    }
    record = cc.remap(Cell(), config, [list(p) for p in points], tmp_path, log=lambda row: None)
    assert len(record["points"]) == len(points)


def _tcp_remap(tmp_path, monkeypatch, shows, pairs):
    """A remap over GRID at FK yaw 0 whose mark is the jaw `shows[i]` (ref|other), with both jaws' blobs at `pairs`."""
    import types

    def write(c, pose, _place, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"chunks": {"above_pick": [[pose["x"], pose["y"], pose["z"], pose["yaw_deg"], 0.0]]}}))
        return path

    monkeypatch.setitem(sys.modules, "cell_pipeline", types.SimpleNamespace(write_library=write))
    monkeypatch.setattr(cc.cell_pivot, "joints_tcp", lambda s, **k: tuple(s[:4]))
    points = sorted(GRID, key=lambda q: math.hypot(*q))
    o = (0.054 * math.cos(math.radians(79.0)), 0.054 * math.sin(math.radians(79.0)))
    jaw = {"ref": -0.5, "other": 0.5}

    class Cell:
        def __init__(self):
            self.i = -1

        def frame(self, camera):
            return np.zeros((48, 64, 3), np.uint8)

        def act(self, command):
            self.i += command.startswith("load")
            return {"ok": True}

    def mark(cell, config, near=None, report=None, **kw):
        p, i = points[cell.i], cell.i
        seen = [to_px((p[0] + s * o[0], p[1] + s * o[1])) for s in ((jaw[shows[i]], -jaw[shows[i]]) if i in pairs else (jaw[shows[i]],))]
        report.update(reason=None, side=None, blobs=[[x, y, 400.0] for x, y in seen])
        return seen[0]

    monkeypatch.setattr(cc.cell_pivot, "mark_jaws", mark)
    config = {"coarse": {"z_view": 0.14}, "plan": {"approach_m": 0.04}, "sites": {"pallet": {"yaw_deg": 0.0}},
              "calibrate": {"map_sites": ["pallet"], "tcp_marks": True}}
    return cc.remap(Cell(), config, [list(p) for p in points], tmp_path, log=lambda row: None), points


def test_a_tcp_remap_labels_the_seen_jaw_at_every_point_and_maps_the_tcp(tmp_path, monkeypatch):
    """arm_a 2026-11-15: the remap marks were one jaw 28 mm off the TCP (one point the other jaw), so every pivot bias
    held that offset (29.9 mm, refused). Labelled jointly, a pair fixing which jaw is which, the map is the TCP's."""
    shows = ["ref", "ref", "other", "ref", "ref", "other", "ref", "ref"]
    record, points = _tcp_remap(tmp_path, monkeypatch, shows, pairs={4, 6})
    assert record["marks"] == "tcp" and len(record["points"]) == 8 and record["loo_error_mm"]["max"] < 0.5
    H = np.array(record["homography"])
    for p in points:  # the TCP's pixel (the jaws' middle) maps to the TCP
        assert 1000 * math.dist(cc.cal.to_arm(H, to_px(p)), p) < 0.5
    labels = json.loads(next((tmp_path / "remap-frames").iterdir()).joinpath("labels.json").read_text())
    assert labels["sides"] == shows and labels["pairs"] == [4, 6] and labels["why"] is None


def test_a_tcp_remap_that_cannot_tell_the_jaws_apart_saves_no_map(tmp_path, monkeypatch):
    # one yaw, one jaw everywhere, no pair: "all ref" and "all other" fit alike and put the map 54 mm apart
    with pytest.raises(SystemExit, match="jaw sides ambiguous"):
        _tcp_remap(tmp_path, monkeypatch, ["ref"] * 8, pairs=set())


def test_a_tcp_remap_does_not_gate_mark_jaws_on_unlabelled_jaw_predictions(tmp_path, monkeypatch):
    """Under tcp_marks, unlabelled marks mix both jaws (~54 mm apart), so near=predicted(...) must be skipped."""
    import types

    def write(c, pose, _place, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"chunks": {"above_pick": [[pose["x"], pose["y"], pose["z"], pose["yaw_deg"], 0.0]]}}))
        return path

    monkeypatch.setitem(sys.modules, "cell_pipeline", types.SimpleNamespace(write_library=write))
    monkeypatch.setattr(cc.cell_pivot, "joints_tcp", lambda s, **k: tuple(s[:4]))
    points = sorted(GRID, key=lambda q: math.hypot(*q))
    o = (0.054 * math.cos(math.radians(79.0)), 0.054 * math.sin(math.radians(79.0)))
    jaw = {"ref": -0.5, "other": 0.5}
    shows = ["ref", "other", "ref", "other", "ref", "other", "ref", "other"]
    pairs, gates = {1, 2, 5}, []

    class Cell:
        def __init__(self):
            self.i = -1

        def frame(self, camera):
            return np.zeros((48, 64, 3), np.uint8)

        def act(self, command):
            self.i += command.startswith("load")
            return {"ok": True}

    def mark(cell, config, near=None, report=None, **kw):
        gates.append(near)
        p, i = points[cell.i], cell.i
        seen = [to_px((p[0] + s * o[0], p[1] + s * o[1])) for s in ((jaw[shows[i]], -jaw[shows[i]]) if i in pairs else (jaw[shows[i]],))]
        kept = [b for b in seen if near is None or math.dist(b, near[0][0]) <= near[1]]
        if not kept:
            report.update(reason="blobs outside near", blobs=[[x, y, 400.0] for x, y in seen])
            return None
        report.update(reason=None, side=None, blobs=[[x, y, 400.0] for x, y in seen])
        return kept[0]

    monkeypatch.setattr(cc.cell_pivot, "mark_jaws", mark)
    config = {"coarse": {"z_view": 0.14}, "plan": {"approach_m": 0.04}, "sites": {"pallet": {"yaw_deg": 0.0}},
              "calibrate": {"map_sites": ["pallet"], "tcp_marks": True}}
    record = cc.remap(Cell(), config, [list(p) for p in points], tmp_path, log=lambda row: None)
    assert all(g is None for g in gates)
    assert record["marks"] == "tcp" and len(record["points"]) == 8 and record["loo_error_mm"]["max"] < 0.5


def test_a_map_only_a_minority_of_the_marks_agree_on_is_refused():
    assert cc.enough_agree(5, 8) and cc.enough_agree(5, 9)
    assert not cc.enough_agree(5, 10)  # half: either side of the jaws could be the true one
    assert not cc.enough_agree(4, 4)


def test_cell_calibrate_clears_bias_cache_on_cell_pivot_bias():
    assert "cell_pivot._BIAS_CACHE" not in (ROOT / "deploy/robot/omx/cell_calibrate.py").read_text(encoding="utf-8")
    assert "cell_pivot_bias._BIAS_CACHE.clear()" in (ROOT / "deploy/robot/omx/cell_calibrate.py").read_text(encoding="utf-8")


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


def test_check_reports_over_limit_bias_instead_of_crashing(tmp_path):
    pytest.importorskip("cv2")
    cal_path = tmp_path / "cal.json"
    cal_path.write_text(json.dumps({"sites": {"floor": {"homography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}}}))
    cc.cell_pivot.bias_path(cal_path).write_text(json.dumps({
        "schema": cc.cell_pivot.SCHEMA,
        "regions": [{"site": "floor", "point_m": [0.0, 0.17], "bias_mm": [26.0, 20.0]}],
    }))
    config = {"calibration_path": str(cal_path), "preflight": {}, "sites": {"floor": {"surface_z": 0.006}},
              "calibrate": {"map_sites": ["floor"]}}
    found = cc.check(config, json.loads(cal_path.read_text()), [("floor", (0.0, 0.17))], np.zeros((32, 32, 3), np.uint8))
    assert "max_bias_mm" in found["bias_error"] and found["missing_bias"] == ["floor:0.0,0.17"]
    assert "pivot-near floor:0.0,0.17" in cc.stale(found)


PIVOT_CONFIG = {"params": {"pivot.over_target": 1}, "pivot": {"z_view": 0.1, "points": [[0.15, 0.05]], "clear_first": True},
                "coarse": {"z_view": 0.118}, "sites": {"pallet": {"yaw_deg": 0.0, "surface_z": -0.01}}}


def test_without_clear_first_an_over_target_site_keeps_the_reviewed_over_target_set(monkeypatch):
    """Review 2026-11-17: the clear-point circle at a packed over-target site is a new pose set until checked."""
    tried = []
    monkeypatch.setattr(cc, "auto_pivot_point", lambda *a: tried.append(a) or (0.15, 0.05))
    config = {**PIVOT_CONFIG, "pivot": {k: v for k, v in PIVOT_CONFIG["pivot"].items() if k != "clear_first"}}
    assert cc.pivot_point(object(), config, {}, "pallet", (0.16, 0.06)) == ([0.16, 0.06], True) and tried == []
    seen = []
    import cell_pivot
    monkeypatch.setattr(cell_pivot, "pivot_calibrate", lambda cell, config, point, *a: seen.append(point) or {"result": "stopped"})
    cc.self_calibrate(object(), config, {}, Path("cal.json"), "pallet", (0.16, 0.06), [], Path("."), {"regions": []}, None, None)
    assert seen == [(0.16, 0.06)] and tried == []


def test_a_clear_point_is_pivoted_with_the_full_circle_before_the_box_is_tried(monkeypatch):
    """2026-11-17 panel: with over_target on, arm_b went straight over the box (±60 deg = exactly the 120 deg minimum,
    FK 116 deg refused) and pivot.points was never tried."""
    tried = []
    monkeypatch.setattr(cc, "auto_pivot_point", lambda cell, config, cal, site, start: tried.append(tuple(start)) or tuple(start))
    point, over = cc.pivot_point(object(), PIVOT_CONFIG, {}, "pallet", (0.16, 0.06))
    assert (point, over) == ([0.15, 0.05], False) and tried == [(0.15, 0.05)]
    assert cc.pivot_near_yaws(PIVOT_CONFIG, "pallet", over) == [-80, -40, 0, 40, 80, 120]


def test_the_box_is_pivoted_over_only_when_no_clear_point_serves_it(monkeypatch):
    monkeypatch.setattr(cc, "auto_pivot_point", lambda *a: None)
    point, over = cc.pivot_point(object(), PIVOT_CONFIG, {}, "pallet", (0.16, 0.06))
    assert (point, over) == ([0.16, 0.06], True)
    assert cc.pivot_near_yaws(PIVOT_CONFIG, "pallet", over) == [-60, -40, -20, 0, 20, 40, 60]
    far = {**PIVOT_CONFIG, "params": {"pivot.over_target": 0}}
    assert cc.pivot_point(object(), far, {}, "pallet", (0.16, 0.06)) == (None, False)


def test_a_clear_point_beyond_the_bias_reach_is_not_used(monkeypatch):
    monkeypatch.setattr(cc, "auto_pivot_point", lambda cell, config, cal, site, start: (start[0] + 0.2, start[1]))
    assert cc.pivot_point(object(), PIVOT_CONFIG, {}, "pallet", (0.16, 0.06)) == ([0.16, 0.06], True)


def test_depth_verify_passes_a_fresh_depth_frame_on_a_depth_top_camera(tmp_path, monkeypatch):
    """2026-11-17: `auto --only depth-verify` never passed depth, so every D435 cell reported missing_depth."""
    import cell_cal_eval
    import cell_pipeline as cp

    frame = np.full((32, 32, 3), 80, np.uint8)
    depth = np.full((480, 640), 600, np.uint16)
    seen = {}
    monkeypatch.setattr(cp, "FifoCell", lambda *_: type("Cell", (), {"frame": lambda self, _: frame})())
    monkeypatch.setattr(cc, "check", lambda *_: {})
    monkeypatch.setattr(cc, "stale", lambda *_: [])
    monkeypatch.setattr(cc, "depth_capture", lambda: depth)
    monkeypatch.setattr(cell_cal_eval, "verify_profile_depth",
                        lambda config, cal, bias, **kw: seen.update(kw) or {"verdict": "ok"})
    (tmp_path / "plan.json").write_text("{}")
    for device, expect in (("/dev/v4l/by-id/rosy-realsense-d435-color", depth), ("/dev/v4l/by-id/rosy-arm_s_jieli", None)):
        config = {"sites": {}, "calibration_path": str(tmp_path / "cal.json"), "plan_path": str(tmp_path / "plan.json"),
                  "work_dir": str(tmp_path), "io": str(tmp_path),
                  "cameras": {"top": {"url": "http://127.0.0.1:8767/frame/top.jpg", "device": device}}}
        path = tmp_path / "config.json"
        path.write_text(json.dumps(config))
        seen.clear()
        assert cc.main(["--config", str(path), "auto", "--only", "depth-verify", "--verify",
                        "--commissioning", "--person-at-switch"]) == 0
        assert seen["depth"] is expect


def test_moving_rects_includes_belt_and_moves_sites():
    import cell_scene_guard as sg

    cfg = {
        "sites": {
            "belt": {"auto_roi": [300, 20, 400, 120]},
            "pinky": {"moves": True, "auto_roi": [100, 0, 310, 200]},
            "board": {"auto_roi": [430, 350, 580, 440]},
        }
    }
    assert sg.moving_rects(cfg) == [[300, 20, 400, 120], [100, 0, 310, 200]]


@pytest.mark.parametrize(
    ("site_extra", "low_zones", "expected_z_to", "error_fragment"),
    [
        ({}, (), 0.010, None),
        ({"probe_z_to_m": -0.020}, [{"x": [0.10, 0.20], "y": [-0.05, 0.05], "z_min_m": -0.030}], -0.020, None),
        ({"probe_z_to_m": -0.020}, [{"x": [0.30, 0.40], "y": [-0.05, 0.05], "z_min_m": -0.030}], None, "outside low_zones"),
        ({"probe_z_to_m": -0.040}, [{"x": [0.10, 0.20], "y": [-0.05, 0.05], "z_min_m": -0.030}], None, "outside low_zones"),
        ({"probe_z_to_m": -0.020}, [{"x": [0.10, 0.20], "y": [-0.05, 0.05], "z_min_m": -0.015}, {"x": [0.10, 0.20], "y": [-0.05, 0.05], "z_min_m": -0.040}], None, "outside low_zones"),
        ({"probe_z_to_m": -0.020}, [{"x": [0.10, 0.20], "y": [-0.05, 0.05], "z_min_m": False}], None, "invalid low_zones entry"),
        ({"probe_z_to_m": -0.020}, [{"x": [float("-inf"), float("inf")], "y": [-0.05, 0.05], "z_min_m": -0.030}], None, "invalid low_zones entry"),
        ({"probe_z_to_m": True}, (), None, "invalid probe_z_to_m"),
        ({"probe_z_to_m": "-0.02"}, (), None, "invalid probe_z_to_m"),
        ({"probe_z_to_m": float("nan")}, (), None, "invalid probe_z_to_m"),
        ({"probe_z_to_m": 0.10}, (), None, "invalid probe_z_to_m"),
        ({"probe_z_to_m": -0.051}, (), None, "invalid probe_z_to_m"),
        ({"place": [0.15]}, (), None, "invalid place"),
        ({"place": {"a": 1, "b": 2}}, (), None, "invalid place"),
        ({"place": [True, 0.0]}, (), None, "invalid place"),
        ({"yaw_deg": True}, (), None, "invalid yaw_deg"),
    ],
)
def test_surface_step_gates_probe_z_to_m_against_low_zones(tmp_path, monkeypatch, capsys, site_extra, low_zones, expected_z_to, error_fragment):
    pytest.importorskip("cv2")
    import cell_pipeline as cp
    import cell_surface

    cal_path = tmp_path / "cal.json"
    cal_path.write_text(json.dumps({"schema": cc.cal.SCHEMA, "sites": {}}), encoding="utf-8")
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({"limits": {"low_zones": low_zones}}), encoding="utf-8")
    config = {
        "calibration_path": str(cal_path),
        "plan_path": str(plan_path),
        "work_dir": str(tmp_path),
        "io": str(tmp_path),
        "cameras": {"top": "http://unused"},
        "sites": {"pallet": {"place": [0.15, 0.0], "yaw_deg": 0.0, **site_extra}},
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(config), encoding="utf-8")
    calls = {"probe": [], "touch": 0}
    monkeypatch.setattr(cp, "FifoCell", lambda *a: type("Cell", (), {"frame": lambda self, _: np.zeros((32, 32, 3), np.uint8)})())
    monkeypatch.setattr(cc, "check", lambda *a: {})
    monkeypatch.setattr(cc, "stale", lambda *a: ["surface pallet"])
    monkeypatch.setattr(cell_surface, "probe_library", lambda plan, x, y, yaw, z_from, z_to, tcp_x_m=None: calls["probe"].append(z_to) or {"chunks": {}})
    monkeypatch.setattr(cell_surface, "touch", lambda *a, **kw: calls.__setitem__("touch", calls["touch"] + 1) or {"result": "touched", "surface_z": -0.01})
    assert cc.main(["--config", str(cfg_path), "auto", "--only", "surface", "--commissioning", "--person-at-switch"]) == 0
    out = capsys.readouterr().out
    if error_fragment is None:
        assert calls["probe"] == [expected_z_to] and calls["touch"] == 1
    else:
        assert calls["probe"] == [] and calls["touch"] == 0 and error_fragment in out


def test_check_reports_low_zone_gaps_for_mapped_low_site(tmp_path):
    pytest.importorskip("cv2")
    cal_path, ref_path = tmp_path / "cal.json", tmp_path / "ref.jpg"
    # x_m = px / 1000, y_m = (200 - py) / 1000
    h = [[0.001, 0.0, 0.0], [0.0, -0.001, 0.200], [0.0, 0.0, 1.0]]
    cal_data = {"schema": cc.cal.SCHEMA, "sites": {"beltend": {"homography": h, "z_view": -0.0571}}}
    plan_path = tmp_path / "plan.json"
    plan = {
        "limits": {
            "workspace_min_m": [-0.28, -0.28, 0.005],
            "low_zones": [{"x": [0.05, 0.25], "y": [0.05, 0.17], "z_min_m": -0.0601}],
        }
    }
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    frame = np.random.default_rng(0).integers(0, 255, (128, 128, 3), dtype=np.uint8)
    config = {
        "calibration_path": str(cal_path),
        "plan_path": str(plan_path),
        "preflight": {"reference_top": str(ref_path)},
        "cameras": {"top": {"height_m": 0.596, "center_px": [303, 367]}},
        "calibrate": {"map_sites": ["beltend"]},
        "sites": {
            "beltend": {
                "surface_z": -0.0721,
                "z": -0.0571,
                "start": [0.135, 0.105],
                "place": [0.135, 0.105],
                "surface_px": [[100, 150], [180, 150], [180, 0], [100, 0]],
            }
        },
    }
    cc.save_bound_map_reference(cal_path, ref_path, cal_data, config, frame)
    cal_data = json.loads(cal_path.read_text(encoding="utf-8"))
    found = cc.check(config, cal_data, [], frame)
    assert "low_zone_gaps" in found and len(found["low_zone_gaps"]) == 1
    gap = found["low_zone_gaps"][0]
    assert gap["site"] == "beltend" and gap["uncovered_y_m"][1] == pytest.approx(0.20, abs=0.002)
    assert cc.stale(found) == []
    plan["limits"]["low_zones"][0]["y"] = [0.05, 0.21]
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    found_ok = cc.check(config, cal_data, [], frame)
    assert "low_zone_gaps" not in found_ok


def test_low_zone_gaps_respects_first_match_z_min():
    h = [[0.001, 0.0, 0.0], [0.0, -0.001, 0.200], [0.0, 0.0, 1.0]]
    cal_data = {"sites": {"beltend": {"homography": h, "z_view": -0.0571}}}
    config = {
        "plan": {
            "limits": {
                "workspace_min_m": [-0.28, -0.28, 0.005],
                "low_zones": [
                    {"x": [0.05, 0.25], "y": [0.05, 0.25], "z_min_m": -0.030},
                    {"x": [0.05, 0.25], "y": [0.05, 0.25], "z_min_m": -0.065},
                ],
            }
        },
        "cameras": {"top": {"height_m": 0.596, "center_px": [303, 367]}},
        "sites": {"beltend": {"surface_z": -0.0721, "z": -0.0571, "start": [0.15, 0.15]}},
    }
    gaps = cc.low_zone_gaps(config, cal_data)
    assert len(gaps) == 1 and gaps[0]["site"] == "beltend"


def test_remap_persists_observations_for_offline_replay_on_scene_moved_and_tcp_marks(tmp_path, monkeypatch):
    import types

    monkeypatch.setitem(sys.modules, "cell_pipeline", types.SimpleNamespace(write_library=lambda c, p, q, path: path))
    points = sorted(GRID, key=lambda q: math.hypot(*q))

    class MovedCell:
        def __init__(self):
            self.i = -1

        def frame(self, camera):
            view = np.zeros((480, 640, 3), np.uint8)
            if self.i >= 0:
                view[100:200, 100:160] = (20, 90, 220)
            return view

        def act(self, command):
            self.i += command.startswith("load")
            return {"ok": True}

    monkeypatch.setattr(cc.cell_pivot, "mark_jaws", lambda cell, config, near=None, **kw: to_px(points[cell.i]))
    cfg = {"coarse": {"z_view": 0.14}, "plan": {"approach_m": 0.04},
           "sites": {"pallet": {"yaw_deg": 0.0}}, "calibrate": {"map_sites": ["pallet"]}}
    work_a = tmp_path / "run_a"
    with pytest.raises(SystemExit, match="scene changed"):
        cc.remap(MovedCell(), cfg, [list(p) for p in points], work_a, log=lambda row: None)

    frames_dir = next((work_a / "remap-frames").iterdir())
    obs = json.loads((frames_dir / "observations.json").read_text(encoding="utf-8"))
    assert obs["schema"] == cc.rp.OBSERVATIONS_SCHEMA and len(obs["marks"]) == len(points) and obs["scene_moved"]

    with pytest.raises(SystemExit, match="scene changed"):
        cc.rp.replay_observations(frames_dir, cfg, log=lambda row: None)

    cfg_ignored = {**cfg, "scene_ignore_px": [[90, 90, 170, 210]]}
    obs_before = (frames_dir / "observations.json").read_bytes()
    rec = cc.rp.replay_observations(frames_dir, cfg_ignored, log=lambda row: None)
    assert (frames_dir / "observations.json").read_bytes() == obs_before
    assert len(rec["points"]) == len(points) and cc.map_agrees(rec, None)

    # tcp_marks=True saves seen_jaws and replays offline without touching labels.json.
    shows = ["ref", "ref", "other", "ref", "ref", "other", "ref", "ref"]
    work_tcp = tmp_path / "run_tcp"
    live_tcp, tcp_pts = _tcp_remap(work_tcp, monkeypatch, shows, pairs={4, 6})
    frames_tcp = next((work_tcp / "remap-frames").iterdir())
    labels_path = frames_tcp / "labels.json"
    labels_bytes = labels_path.read_bytes()
    labels_path.unlink()
    cfg_tcp = {"coarse": {"z_view": 0.14}, "plan": {"approach_m": 0.04},
               "sites": {"pallet": {"yaw_deg": 0.0}}, "calibrate": {"map_sites": ["pallet"], "tcp_marks": True}}
    replay_tcp = cc.rp.replay_observations(frames_tcp, cfg_tcp, log=lambda row: None)
    assert not labels_path.exists() and replay_tcp["marks"] == "tcp"
    assert np.allclose(replay_tcp["homography"], live_tcp["homography"])
    assert len(replay_tcp["points"]) == len(tcp_pts) and len(labels_bytes) > 0


def test_replay_observations_fail_closed_and_cli_check_offline_only(tmp_path, monkeypatch, capsys):
    import cell_pipeline as cp
    import types

    monkeypatch.setitem(sys.modules, "cell_pipeline", types.SimpleNamespace(write_library=lambda c, p, q, path: path))
    points = sorted(GRID, key=lambda q: math.hypot(*q))

    class BoxCell:
        def __init__(self):
            self.i = -1

        def frame(self, camera):
            view = np.zeros((480, 640, 3), np.uint8)
            if self.i >= 0:
                view[100:200, 100:160] = (20, 90, 220)
            return view

        def act(self, command):
            self.i += command.startswith("load")
            return {"ok": True}

    monkeypatch.setattr(cc.cell_pivot, "mark_jaws", lambda cell, config, near=None, **kw: to_px(points[cell.i]))
    cfg_orig = {"coarse": {"z_view": 0.14}, "plan": {"approach_m": 0.04},
                "sites": {"pallet": {"yaw_deg": 0.0}}, "calibrate": {"map_sites": ["pallet"]}}
    with pytest.raises(SystemExit, match="scene changed"):
        cc.remap(BoxCell(), cfg_orig, [list(p) for p in points], tmp_path, log=lambda row: None)
    frames_dir = next((tmp_path / "remap-frames").iterdir())

    # Mismatched tcp_marks config fails closed.
    with pytest.raises(SystemExit, match="tcp_marks mismatch"):
        cc.rp.replay_observations(frames_dir, {**cfg_orig, "scene_ignore_px": [[90, 90, 170, 210]], "calibrate": {"map_sites": ["pallet"], "tcp_marks": True}})

    # CLI check --replay-frames works completely offline without FifoCell or touching cal.json.
    plan_path, cal_path, cfg_path = tmp_path / "plan.json", tmp_path / "cal.json", tmp_path / "config.json"
    plan_path.write_text("{}", encoding="utf-8")
    cal_raw = json.dumps({"schema": cc.cal.SCHEMA, "sites": {}})
    cal_path.write_text(cal_raw, encoding="utf-8")
    cfg_cli = {**cfg_orig, "scene_ignore_px": [[90, 90, 170, 210]], "plan_path": str(plan_path), "calibration_path": str(cal_path)}
    cfg_path.write_text(json.dumps(cfg_cli), encoding="utf-8")

    monkeypatch.setattr(cp, "FifoCell", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not open FifoCell")))
    capsys.readouterr()
    assert cc.main(["--config", str(cfg_path), "check", "--replay-frames", str(frames_dir)]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["agrees"] is True and len(out["record"]["points"]) == len(points)
    assert cal_path.read_text(encoding="utf-8") == cal_raw

    with pytest.raises(SystemExit, match="offline read-only"):
        cc.main(["--config", str(cfg_path), "auto", "--replay-frames", str(frames_dir)])

    # Missing artifact & wrong schema fail closed.
    (frames_dir / "after.jpg").unlink()
    with pytest.raises(SystemExit, match="missing required artifact"):
        cc.rp.replay_observations(frames_dir, cfg_cli)
    obs = json.loads((frames_dir / "observations.json").read_text(encoding="utf-8"))
    (frames_dir / "observations.json").write_text(json.dumps({**obs, "schema": "wrong.v0"}), encoding="utf-8")
    (frames_dir / "after.jpg").write_bytes(b"")
    with pytest.raises(SystemExit, match="schema"):
        cc.rp.replay_observations(frames_dir, cfg_cli)


def test_map_from_site_is_synced_on_remap_and_stale_copy_flagged_in_check(tmp_path, monkeypatch):
    cv2 = pytest.importorskip("cv2")
    import cell_pipeline as cp
    import cell_preflight
    import types

    ref_path = tmp_path / "ref.jpg"
    assert cv2.imwrite(str(ref_path), np.full((32, 32, 3), 80, np.uint8))
    ref_sha = hashlib.sha256(ref_path.read_bytes()).hexdigest()
    h_new = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    h_old = [[1.0, 0.0, 42.0], [0.0, 1.0, 50.0], [0.0, 0.0, 1.0]]
    config = {
        "preflight": {"reference_top": str(ref_path)},
        "calibration_path": str(tmp_path / "cal.json"),
        "plan_path": str(tmp_path / "plan.json"),
        "work_dir": str(tmp_path),
        "io": str(tmp_path),
        "cameras": {"top": {"height_m": 0.65, "center_px": [320, 240]}},
        "coarse": {"z_view": 0.118},
        "plan": {"approach_m": 0.04},
        "calibrate": {"map_sites": ["floor"], "map_points": [[-0.06, 0.15]]},
        "sites": {
            "floor": {"yaw_deg": -67.8, "surface_z": 0.006, "auto_roi": [0, 0, 20, 20], "surface_px": None},
            "belt": {"yaw_deg": -14.4, "surface_z": 0.028, "map_from": "floor", "auto_roi": [10, 0, 30, 20], "surface_px": None},
        },
    }
    monkeypatch.setattr(cell_preflight, "camera_shift_px", lambda *_: {"ok": True, "max_px": 0.0})

    def _bound(sites):
        return {
            "schema": cc.cal.SCHEMA,
            "sites": sites,
            "reference_top_sha256": ref_sha,
            "reference_map_sha": cell_attempts.digest(sites),
            "reference_geometry_sha": cell_attempts.digest({
                n: {k: s.get(k) for k in ("auto_roi", "surface_px", "map_from")}
                for n, s in config["sites"].items()
            }),
        }

    frame = np.full((32, 32, 3), 80, np.uint8)
    assert "belt" not in cc.check(config, _bound({"floor": {"homography": h_new}}), [], frame)["missing_map"]
    assert "belt" in cc.check(config, _bound({"floor": {"homography": h_new}, "belt": {"homography": h_old}}), [], frame)["missing_map"]
    assert "belt" not in cc.check(config, _bound({"floor": {"homography": h_new}, "belt": {"homography": h_new}}), [], frame)["missing_map"]
    assert cc._map_write_sites(config) == ["floor", "belt"]

    # End-to-end remap writes both floor and its map_from follower belt.
    cal_path, cfg_path = tmp_path / "cal.json", tmp_path / "config.json"
    (tmp_path / "plan.json").write_text("{}", encoding="utf-8")
    cal_path.write_text(json.dumps(_bound({"floor": {"homography": h_old}, "belt": {"homography": h_old}})), encoding="utf-8")
    cfg_path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(cp, "FifoCell", lambda *a, **kw: types.SimpleNamespace(frame=lambda *_: frame))
    monkeypatch.setattr(cc, "check", lambda *a, **kw: {"camera_moved": True, "targets": [], "missing_bias": [], "missing_surface": [], "missing_map": []})
    monkeypatch.setattr(cc, "remap", lambda *a, **kw: {"homography": h_new, "loo_error_mm": {"max": 1.5, "mean": 1.0}, "points": []})
    monkeypatch.setattr(cc, "move_regions", lambda cfg, *a: cfg)
    monkeypatch.setattr(cc.rp, "plan", lambda *a, **kw: [])
    monkeypatch.setattr(cc.rp, "refusal", lambda *a, **kw: None)
    monkeypatch.setitem(sys.modules, "cell_hooks", types.SimpleNamespace(stills=lambda *a, **kw: types.SimpleNamespace(close=lambda: None)))

    assert cc.main(["--config", str(cfg_path), "auto", "--only", "remap", "regions", "--commissioning", "--person-at-switch"]) == 0
    saved = json.loads(cal_path.read_text(encoding="utf-8"))
    assert saved["sites"]["floor"]["homography"] == h_new
    assert saved["sites"]["belt"]["homography"] == h_new

    # consensus-repair copies the repaired parent record to map_from followers (even if follower has old/no points).
    pts_5 = [{"pixel": [i * 10, i * 10 + 1], "arm_m": [i / 100, i / 100 + 0.01]} for i in range(5)]
    repaired_cal = _bound({"floor": {"homography": h_old, "points": pts_5}, "belt": {"homography": h_old}})
    cal_path.write_text(json.dumps(repaired_cal), encoding="utf-8")
    monkeypatch.setattr(cc, "check", lambda *a, **kw: {"camera_moved": False, "consensus_repairable": True, "targets": [], "missing_bias": [], "missing_surface": [], "missing_map": []})
    monkeypatch.setattr(cc, "consensus", lambda points, _: points)
    monkeypatch.setattr(cc, "enough_agree", lambda *_: True)
    monkeypatch.setattr(cc, "repair_record", lambda _cfg, _rec, _kept: {"homography": h_new, "loo_error_mm": {"max": 1.0}, "points": pts_5})
    assert cc.main(["--config", str(cfg_path), "auto", "--only", "consensus-repair", "--commissioning", "--person-at-switch"]) == 0
    repaired_saved = json.loads(cal_path.read_text(encoding="utf-8"))
    assert repaired_saved["sites"]["floor"]["homography"] == h_new
    assert repaired_saved["sites"]["belt"]["homography"] == h_new


def test_pivot_near_does_not_overwrite_concurrent_config_edits(tmp_path, monkeypatch):
    import cell_pipeline as cp
    import types

    cal_path, plan_path, cfg_path = tmp_path / "cal.json", tmp_path / "plan.json", tmp_path / "config.json"
    plan_path.write_text("{}", encoding="utf-8")
    cal_path.write_text(json.dumps({"schema": cc.cal.SCHEMA, "sites": {"floor": {"homography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}}}), encoding="utf-8")
    initial = {
        "calibration_path": str(cal_path),
        "plan_path": str(plan_path),
        "work_dir": str(tmp_path),
        "io": str(tmp_path),
        "cameras": {"top": {"height_m": 0.65, "center_px": [320, 240]}},
        "coarse": {"z_view": 0.118},
        "plan": {"approach_m": 0.04},
        "sites": {"floor": {"yaw_deg": -67.8, "surface_z": 0.006}},
        "pivot": {"geometry": {"radius_mm": 26.3, "phase_deg": 80.1}},
    }
    cfg_path.write_text(json.dumps(initial), encoding="utf-8")
    monkeypatch.setattr(cp, "FifoCell", lambda *a, **kw: types.SimpleNamespace(frame=lambda *_: np.zeros((32, 32, 3), np.uint8)))
    monkeypatch.setattr(cc, "check", lambda *a, **kw: {"camera_moved": False, "targets": ["floor:-0.06,0.15"], "missing_bias": ["floor:-0.06,0.15"], "missing_surface": [], "missing_map": []})

    def _mock_pivot_near(*a, **kw):
        # Simulate another session updating pivot.geometry while pivot_near is running.
        external = json.loads(cfg_path.read_text(encoding="utf-8"))
        external["pivot"]["geometry"] = {"radius_mm": 31.8, "phase_deg": 75.6}
        cfg_path.write_text(json.dumps(external), encoding="utf-8")
        return {"pivot-near floor:-0.06,0.15": "calibrated"}

    monkeypatch.setattr(cc, "pivot_near", _mock_pivot_near)
    assert cc.main(["--config", str(cfg_path), "auto", "--only", "pivot-near", "--targets", "floor:-0.06,0.15", "--commissioning", "--person-at-switch"]) == 0
    after = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert after["pivot"]["geometry"] == {"radius_mm": 31.8, "phase_deg": 75.6}


def test_pivot_near_logs_json_and_returns_refusal_diagnostics(tmp_path, monkeypatch, capsys):
    import cell_pivot, cell_pivot_precheck

    cfg = {
        "cameras": {"top": {"height_m": 0.65, "center_px": [320, 240], "frame_wh": [640, 480]}},
        "coarse": {"z_view": 0.118}, "plan": {"approach_m": 0.04},
        "sites": {"belt": {"yaw_deg": -14.4, "surface_z": 0.028}},
    }
    monkeypatch.setattr(cc, "pivot_point", lambda *a: ([0.115, -0.05], False))
    monkeypatch.setattr(cell_pivot_precheck, "pivot_precheck", lambda *a: [])

    def fake_piv(cell, config, point, yaws, cal, site, work, sleep, log):
        log({"pivot": yaws[0], "mark_px": None})
        return {
            "result": "marks disagree: 11.3 mm from their centre",
            "bias": {"bias_mm": [-10.0, -20.0], "rms_mm": 11.3, "radius_mm": 26.3, "phase_deg": 80.1,
                     "yaws_fk_deg": [45.0, 65.0], "jaw_sides": ["ref", "other"], "dropped": 1},
        }

    monkeypatch.setattr(cell_pivot, "pivot_calibrate", fake_piv)
    out = cc.pivot_near(object(), cfg, {}, tmp_path / "cal.json", "pivot-near belt:0.115,-0.05", tmp_path)
    logged = json.loads(capsys.readouterr().out.strip())
    assert logged["pivot"] == -94.4 and logged["mark_px"] is None
    assert out["pivot-near belt:0.115,-0.05"].startswith("marks disagree")
    assert out["bias"] == [-10.0, -20.0] and out["rms_mm"] == 11.3 and out["radius_mm"] == 26.3
    assert out["phase_deg"] == 80.1 and out["yaws_fk_deg"] == [45.0, 65.0] and out["jaw_sides"] == ["ref", "other"] and out["dropped"] == 1


def test_self_calibrate_uses_site_pivot_yaws_only_when_over_target(tmp_path, monkeypatch):
    import cell_pivot

    seen_yaws = []
    monkeypatch.setattr(cell_pivot, "pivot_calibrate", lambda c, cfg, pt, yaws, *a: seen_yaws.append(list(yaws)) or {"result": "stopped"})
    monkeypatch.setattr(cc, "auto_pivot_point", lambda *a: None)
    cfg = {"params": {"pivot.over_target": 1}, "pivot": {"z_view": 0.08}, "coarse": {"z_view": 0.118},
           "sites": {"belt": {"yaw_deg": -14.4, "surface_z": 0.028, "pivot_yaws": [35, 45, 55, 65, 75]}}}
    cc.self_calibrate(object(), cfg, {}, tmp_path / "cal.json", "belt", (0.115, -0.05), [], tmp_path, {"regions": []}, None, None)
    assert seen_yaws == [[35, 45, 55, 65, 75]]
    seen_yaws.clear()
    cfg["pivot"]["yaws"] = [20, 40]
    cc.self_calibrate(object(), cfg, {}, tmp_path / "cal.json", "belt", (0.115, -0.05), [], tmp_path, {"regions": []}, None, None)
    assert seen_yaws == [[20, 40]]
    seen_yaws.clear()
    del cfg["pivot"]["yaws"]
    cfg["params"]["pivot.over_target"] = 0
    cfg["pivot"]["points"] = [(0.115, -0.05)]
    cc.self_calibrate(object(), cfg, {}, tmp_path / "cal.json", "belt", (0.115, -0.05), [], tmp_path, {"regions": []}, None, None)
    assert seen_yaws == [[-94.4, -54.4, -14.4, 25.6, 65.6, 105.6]]


def test_check_emits_advisory_bias_coverage_and_leverage_without_changing_stale(tmp_path, monkeypatch):
    cv2 = pytest.importorskip("cv2")
    import cell_map_fit, cell_preflight, cell_pivot

    ref_path, cal_path = tmp_path / "ref.jpg", tmp_path / "cal.json"
    assert cv2.imwrite(str(ref_path), np.full((32, 32, 3), 80, np.uint8))
    ref_sha = hashlib.sha256(ref_path.read_bytes()).hexdigest()
    pts = [{"pixel": [100 + 200 * x, 100 + 200 * y], "arm_m": [x, y]} for x, y in ((0.0, 0.1), (0.04, 0.1), (0.0, 0.14), (0.04, 0.14))]
    rec = {"homography": [[0.005, 0.0, -0.5], [0.0, 0.005, -0.5], [0.0, 0.0, 1.0]], "z_view": 0.1,
           "loo_error_mm": {"mean": 2.0, "max": 3.0}, "points": pts}
    sites_cal = {"floor": rec, "belt": dict(rec)}
    cfg = {
        "preflight": {"reference_top": str(ref_path)}, "calibration_path": str(cal_path), "work_dir": str(tmp_path),
        "cameras": {"top": {"height_m": 0.65, "center_px": [320, 240]}}, "coarse": {"z_view": 0.1},
        "calibrate": {"map_sites": ["floor", "belt"]}, "params": {"verify.map_sigma_max_mm": 5.0},
        "sites": {
            "floor": {"yaw_deg": 0.0, "surface_z": 0.006, "start": [0.02, 0.12]},
            "belt": {"yaw_deg": 0.0, "surface_z": 0.028, "start": [0.40, 0.40]},
        },
    }
    cal = {"schema": cc.cal.SCHEMA, "sites": sites_cal, "reference_top_sha256": ref_sha,
           "reference_map_sha": cell_attempts.digest(sites_cal),
           "reference_geometry_sha": cell_attempts.digest({n: {k: s.get(k) for k in ("auto_roi", "surface_px", "map_from")} for n, s in cfg["sites"].items()})}
    bias_file = cell_pivot.bias_path(cal_path)
    cell_pivot.save_bias(bias_file, {"site": "floor", "point_m": [0.02, 0.12], "bias_mm": [1.0, 1.0],
                                     "map_sha": cell_attempts.digest(rec), "carried_from": "old"})
    monkeypatch.setattr(cell_preflight, "camera_shift_px", lambda *_: {"ok": True, "max_px": 0.0})
    found = cc.check(cfg, cal, [], np.full((32, 32, 3), 80, np.uint8), params=cfg["params"])
    assert {g["site"] for g in found["bias_coverage_gaps"]} == {"floor", "belt"}
    assert [w["site"] for w in found["map_leverage_warn"]] == ["belt"]
    assert cc.stale(found) == []
    lev = cell_map_fit.plan_leverage([[0.0, 0.1], [0.04, 0.1], [0.0, 0.14], [0.04, 0.14]], cfg["sites"], limit_mm=5.0)
    assert [w["site"] for w in lev["warnings"]] == ["belt"]


def test_wide_pose_fit_keeps_pose_loo_and_pose_loo_errors_and_site_sigma(tmp_path):
    import cv2
    import cell_frame as cf
    import cell_map_fit

    K = np.array([[618.53, 0.0, 322.32], [0.0, 618.67, 236.60], [0.0, 0.0, 1.0]])
    R_cb = cv2.Rodrigues(np.array([np.pi, 0.0, 0.0]))[0] @ cv2.Rodrigues(np.array([0.14, -0.10, 0.3]))[0]
    t_cb = np.array([0.12, 0.08, 0.61])
    cam_pose = (R_cb, t_cb)
    up = (R_cb.T @ np.array([0.0, 0.0, 1.0])).tolist()
    z_view = 0.12
    # Wide XY span (>= 0.10 m x >= 0.05 m), with blobs physically 20 mm above z_view
    blob_z = z_view + 0.020
    grid_xy = [(-0.04, 0.10), (0.04, 0.10), (0.12, 0.10), (-0.04, 0.18), (0.04, 0.18), (0.12, 0.18), (0.00, 0.14), (0.08, 0.14)]
    marks = [(cf.project((x, y, blob_z), K, np.zeros(5), cam_pose), (x, y)) for x, y in grid_xy]
    lens = tmp_path / "lens.json"
    lens.write_text(json.dumps({"K": K.tolist(), "dist": [0.0] * 5}), encoding="utf-8")
    cfg = {"cameras": {"top": {"height_m": 0.61, "center_px": [322.32, 236.60]}},
           "calibrate": {"intrinsics": str(lens), "up": up}}

    rec = cc.rp.fit_remap_marks(cfg, z_view, tcp_marks=False, marks=marks, seen_jaws=[], write_labels=False, log=lambda _: None)
    assert rec["upright"] is True
    assert rec["fitted_cz_m"] == pytest.approx(0.61 - 0.020, abs=0.004)
    assert rec["implied_blob_dz_mm"] == pytest.approx(20.0, abs=4.0)
    # Must keep pose loo_error_mm rather than overwriting with affine cal.loo_error_mm
    assert rec["loo_error_mm"] != rec["affine_fit"]["loo_error_mm"] or rec["loo_error_mm"]["max"] < 1.0
    assert rec["loo_error_mm"]["max"] < rec["affine_fit"]["loo_error_mm"]["max"]

    # _pose_loo_errors must not double-invert camera_in_base
    rows = cell_map_fit.loo_residuals(rec, cfg)
    assert len(rows) == len(grid_xy)
    assert max(r["loo_dist_mm"] for r in rows) < 1.5

    # site_sigma_summary evaluates leverage at the z_view pixel directly (no target_z parallax shift)
    pt = [0.04, 0.14]
    px_zview = cc.cal.to_pixel(rec["homography"], pt)
    expected_sig = cell_map_fit.predict_sigma_mm(rec, px_zview)
    summary = cell_map_fit.site_sigma_summary(rec, [pt], cfg["cameras"]["top"], target_z=-0.05)
    assert summary["max_mm"] == expected_sig and summary["mean_mm"] == expected_sig

    # If free height diverges > 60 mm from cam_h - z_view, fitted_map falls back to fixed height
    cfg_far = {"cameras": {"top": {"height_m": 0.72}}, "calibrate": {"intrinsics": str(lens), "up": up}}
    rec_fb = cc.fitted_map(cfg_far, marks, z_view)
    pose_fb = rec_fb.get("pose_fit", rec_fb)
    assert pose_fb["fitted_cz_m"] == pytest.approx(0.72, abs=1e-4)
    assert pose_fb["implied_blob_dz_mm"] == 0.0


def test_remap_uses_measured_fk_and_reruns_jaw_labelling_after_outlier_drop(tmp_path, monkeypatch):
    import types

    def write(c, pose, _place, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"chunks": {"above_pick": [[pose["x"], pose["y"], pose["z"], pose["yaw_deg"], 0.0]]}}))
        return path

    monkeypatch.setitem(sys.modules, "cell_pipeline", types.SimpleNamespace(write_library=write))
    # Live state has true FK position shifted (+3 mm, -2 mm) and yaw=15 deg (different from planned 0 deg)
    true_yaw = 15.0
    monkeypatch.setattr(cc.cell_pivot, "joints_tcp", lambda s, **k: (s[0] + 0.003, s[1] - 0.002, s[2], true_yaw) if len(s) == 6 else tuple(s[:4]))
    points = sorted(GRID, key=lambda q: math.hypot(*q))
    o = (0.054 * math.cos(math.radians(true_yaw + 79.0)), 0.054 * math.sin(math.radians(true_yaw + 79.0)))
    shows = ["ref", "other", "ref", "other", "ref", "other", "ref", "other"]
    pairs = {0, 3, 6}

    class LiveFkCell:
        def __init__(self):
            self.i = -1

        def frame(self, camera):
            return np.zeros((48, 64, 3), np.uint8)

        def act(self, command):
            self.i += command.startswith("load")
            if command == "state" and self.i >= 0:
                p = points[self.i]
                return {"ok": True, "state": [p[0], p[1], 0.14, true_yaw, 0.0, 56.0]}
            return {"ok": True}

    def mark(cell, config, near=None, report=None, **kw):
        p = points[cell.i]
        fk_tcp = (p[0] + 0.003, p[1] - 0.002)
        if cell.i == 1:  # corrupt mark at index 1 (80 px outlier)
            px = (to_px(fk_tcp)[0] + 80.0, to_px(fk_tcp)[1] - 60.0)
            report.update(reason=None, side=None, blobs=[[px[0], px[1], 400.0]])
            return px
        s = -0.5 if shows[cell.i] == "ref" else 0.5
        seen = [to_px((fk_tcp[0] + k * o[0], fk_tcp[1] + k * o[1])) for k in ((s, -s) if cell.i in pairs else (s,))]
        report.update(reason=None, side=None, blobs=[[x, y, 400.0] for x, y in seen])
        return seen[0]

    monkeypatch.setattr(cc.cell_pivot, "mark_jaws", mark)
    config = {"coarse": {"z_view": 0.14}, "plan": {"approach_m": 0.04}, "sites": {"pallet": {"yaw_deg": 0.0}},
              "calibrate": {"map_sites": ["pallet"], "tcp_marks": True}}
    record = cc.remap(LiveFkCell(), config, [list(p) for p in points], tmp_path, log=lambda row: None)
    assert len(record["points"]) == 7 and len(record["dropped_marks"]) == 1
    assert record["loo_error_mm"]["max"] < 0.5
    # Verify marks recorded measured FK coordinates (+0.003, -0.002), not planned GRID
    for pt in record["points"]:
        assert 1000 * math.dist(cc.cal.to_arm(record["homography"], pt["pixel"]), pt["arm_m"]) < 0.5
    obs = json.loads(next((tmp_path / "remap-frames").iterdir()).joinpath("observations.json").read_text())
    assert obs["seen_jaws"][0]["yaw"] == true_yaw
    assert obs["seen_jaws"][0]["tcp"] == pytest.approx([points[0][0] + 0.003, points[0][1] - 0.002], abs=1e-6)
