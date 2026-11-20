"""D-1057: the placement zone verification record: bound slot and tier, before and after frames, common freshness."""
from __future__ import annotations

from pathlib import Path
import sys
import time

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "deploy/robot/omx", ROOT / "middleware/devices/omx/adapter"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cell_zone_verification as czv  # noqa: E402

SITE = {"col": 2, "row": 1}
CONFIG = {"sites": {"pallet-l0": {"layer": 0, **SITE}, "pallet-l2": {"layer": 2, **SITE}, "belt-l0": {"layer": 0, **SITE},
                    "belt": {**SITE}, "pallet-l1": {"layer": 1, "col": 5, "row": 1}, "pinky": {}}}
PASS = {"verified": True, "basis": czv.BASIS, "z_gate": {"verdict": "PASS"},
        "place_slot": {"top_zone": {"within_zone": True, "orientation_ok": True, "fill_ratio": 0.5}}}
BLANK = np.zeros((480, 640, 3), np.uint8)


class Cell:
    def __init__(self, cameras, offset=0.0, fail=(), image=None, stamps=None):
        self.cameras, self.offset, self.fail, self.calls = cameras, offset, set(fail), []
        self.image, self.stamps = image or {}, stamps or {}

    def frame_receipt(self, camera, *, previous=None, max_age_s=2.0, timeout_s=10.0):
        self.calls.append((camera, previous, max_age_s, dict(self.cameras), timeout_s))
        if camera in self.fail:
            raise ValueError("camera frame source has not advanced")
        now = time.time()
        return {"image": self.image.get(camera, BLANK), "camera": camera, "source_seq": 9,
                "source_stamp": self.stamps.get(camera, now) + self.offset, "captured_at": now, "jpeg_sha256": "abc"}


def before(side=True):
    return {"image": BLANK, "before_side": {"image": BLANK} if side else None}


FLOOR = {"top": {"c2r1": [300, 160, 360, 270]}, "floor": [[10, 10, 90, 60]], "floor_depth_mm": [600.0]}  # depth reference ON
REAL_DEPTH_AFTER = czv._depth_after
DEPTH = np.full((480, 640), 611, np.uint16)


def fake_depth(config, after):
    return DEPTH, {"source_seq": 3, "exposure_wall_estimate_s": time.time(), "valid_depth_ratio": 1.0, "raw_sha256": "d"}, None


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(czv, "FRAME_WAIT_S", 0.1)
    monkeypatch.setattr(czv, "_depth_after", fake_depth)
    seen = {}

    def stack(**kw):
        seen.update(kw)
        return {**PASS, "z_gate": dict(PASS["z_gate"])}

    monkeypatch.setattr(czv, "verify_stack_outcome_z_mm", stack)
    monkeypatch.setattr(czv, "verify_stack_outcome", stack)
    return seen


def test_measured_with_before_and_after_frames_of_both_cameras(fast):
    cell = Cell({"top": "u", "side": "u"})
    out = czv.measure(cell, before(), {**CONFIG, "zone_rois": FLOOR}, "pallet-l2", "belt", None)
    assert out["basis"] == czv.BASIS and out["verified"] is True and out["z_gate"]["verdict"] == "PASS"
    assert out["target"] == {"site": "pallet-l2", "area": "pallet", "col": 2, "row": 1, "tier": 3}
    assert fast["place"] == {"area": "pallet", "col": 2, "row": 1, "tier": 3}
    assert fast["before_side"] is BLANK and fast["before_top"] is BLANK  # both before frames reach the measurement
    assert fast["strict_target"] is True and fast["after_depth"] is DEPTH  # the pallet height gate gets the depth frame
    assert out["top"]["frame"]["camera"] == "top" and out["side"]["frame"]["camera"] == "side"


@pytest.mark.parametrize("site", ["pinky", "pallet-l1", "belt"])  # no layer, col out of range, layer missing
def test_a_target_missing_or_out_of_range_is_not_measured(fast, site):
    out = czv.measure(Cell({"top": "u", "side": "u"}), before(), CONFIG, site, "belt", None)
    assert out["verified"] is False and out["basis"].startswith("unverified:") and not fast  # the zone check never ran


@pytest.mark.parametrize("bad", [{"layer": 3, "col": 2, "row": 1}, {"layer": 0, "col": 4, "row": 1},
                                 {"layer": 0, "col": 2, "row": 3}, {"layer": 0, "col": 2, "row": 1, "tier": 2},
                                 {"layer": True, "col": 2, "row": 1}])
def test_out_of_range_or_inconsistent_slot_values(fast, bad):
    out = czv.measure(Cell({"top": "u", "side": "u"}), before(), {"sites": {"pallet-l0": bad}}, "pallet-l0", "belt", None)
    assert out["verified"] is False and not fast


def test_missing_before_frames_forbid_the_two_camera_verification(fast):
    assert czv.measure(Cell({"top": "u", "side": "u"}), before(side=False), CONFIG, "pallet-l0", "belt", None)["verified"] is False
    assert czv.measure(Cell({"top": "u", "side": "u"}), None, CONFIG, "pallet-l0", "belt", None)["verified"] is False
    assert not fast


@pytest.mark.parametrize("fail", [("side",), ("top",)])
def test_one_camera_failing_is_not_verified(fail):
    out = czv.measure(Cell({"top": "u", "side": "u"}, fail=fail), before(), CONFIG, "pallet-l0", "belt", None)
    assert out["verified"] is False and out["basis"].startswith("unverified:")


@pytest.mark.parametrize("which", ["top", "side"])
def test_a_frame_captured_before_the_placement_finished_is_not_used(which):
    cell = Cell({"top": "u", "side": "u"}, stamps={which: time.time() - 5})
    out = czv.measure(cell, before(), CONFIG, "pallet-l0", "belt", None)
    assert out["verified"] is False and "before the placement finished" in out["basis"]


def test_both_frames_must_be_fresh_at_the_common_judging_time(monkeypatch):
    monkeypatch.setattr(czv, "MAX_FRAME_AGE_S", -1.0)  # every frame is already older than that when the two are judged together
    out = czv.measure(Cell({"top": "u", "side": "u"}), before(), CONFIG, "belt-l0", "belt", None)
    assert out["verified"] is False and "at the judging time" in out["basis"]


def test_a_failed_zone_measurement_or_unmeasured_top_zone_is_not_verified(monkeypatch):
    monkeypatch.setattr(czv, "verify_stack_outcome_z_mm", lambda **kw: {"verified": False, "basis": czv.BASIS,
                                                                        "z_gate": {"verdict": "FAIL"}})
    assert czv.measure(Cell({"top": "u", "side": "u"}), before(), CONFIG, "pallet-l0", "belt", None)["verified"] is False
    no_top = {**PASS, "place_slot": {"top_zone": None}}
    monkeypatch.setattr(czv, "verify_stack_outcome_z_mm", lambda **kw: dict(no_top))
    out = czv.measure(Cell({"top": "u", "side": "u"}), before(), CONFIG, "pallet-l0", "belt", None)
    assert out["verified"] is False  # verify_stack_outcome says True by default when nothing was measured on top


# Cell S (top camera only): the real zone measurement on a small synthetic scene, before and after.
S_CONFIG = {"sites": {"belt": {"place": [0.135, -0.045], "auto_roi": [309, 100, 634, 223]}}}
S_ROI = (309, 100, 634, 223)


def _belt(filled):
    img = BLANK.copy()
    if filled:
        img[110:215, 330:600] = (0, 140, 255)
    return img


def _cell_s(before_filled, after_filled, config=S_CONFIG, roi=S_ROI, **kw):
    cell = Cell({"top": "u"}, image={"top": _belt(after_filled)}, **kw)
    return czv.measure(cell, {"image": _belt(before_filled)}, config, "belt", "pinky", roi)


def test_cell_s_top_only_passes_when_the_zone_filled_up_since_before():
    out = _cell_s(False, True)
    assert out["basis"] == czv.TOP_ONLY_BASIS and out["verified"] is True
    assert out["target"] == {"site": "belt", "area": "belt", "roi": list(S_ROI), "tier": 1}
    assert out["side"] == {"available": False, "reason": "no side camera in this cell"}


@pytest.mark.parametrize("before_filled, after_filled", [(True, True), (False, False)])
def test_cell_s_top_only_refuses_a_zone_that_was_full_before_or_is_empty_after(before_filled, after_filled):
    assert _cell_s(before_filled, after_filled)["verified"] is False


def test_cell_s_top_only_keeps_the_before_frame_roi_and_freshness_requirements():
    assert _cell_s(False, True, roi=None)["verified"] is False
    assert _cell_s(False, True, config={"sites": {"belt": {"layer": 1}}})["verified"] is False
    assert czv.measure(Cell({"top": "u"}), None, S_CONFIG, "belt", "pinky", S_ROI)["verified"] is False
    stale = _cell_s(False, True, stamps={"top": time.time() - 5})
    assert stale["verified"] is False and "before the placement finished" in stale["basis"]


def test_record_puts_the_measurements_on_the_attempt_row():
    row, tried = {"observed": 1}, {"verify": {"verified": True}, "transfer": {"steps": []}}
    czv.record(row, tried, Cell({"top": "u", "side": "u"}), before(), {**CONFIG, "_fleet_task": True}, "pallet-l0", "belt", None)
    assert row["verify"] == {"verified": True} and row["transfer"] == {"steps": []}
    assert row["zone_verification"] is tried["zone_verification"] and row["zone_verification"]["verified"] is True


def test_side_frame_source_falls_back_to_the_episodes_side_stream_of_the_same_config():
    config = {**CONFIG, "episodes": {"cameras": {"side": "http://127.0.0.1:8767/frame/side.jpg"}}}
    cell = Cell({"top": "u", "wrist": "u"})
    out = czv.measure(cell, before(), config, "pallet-l0", "belt", None)
    assert out["basis"] == czv.BASIS and out["verified"] is True
    assert [c[3]["side"] for c in cell.calls if c[0] == "side"] == ["http://127.0.0.1:8767/frame/side.jpg"]
    assert "side" not in cell.cameras  # the cell's own camera map is left as it was
    assert czv.before_side(cell, config)["camera"] == "side" and "side" not in cell.cameras
    assert czv.before_side(Cell({"top": "u"}), CONFIG) is None


# The real zone measurements (not replaced): a small synthetic scene for col 2, row 1, tier 1 (the ROIs of cell_area_zones).
def _scene(side_filled, top_filled):
    side, top = BLANK.copy(), BLANK.copy()
    orange = (0, 140, 255)  # BGR: hue ~16, saturated and bright
    if side_filled:
        side[252:315, 226:296] = orange
    if top_filled:
        top[165:270, 370:420] = orange  # taller than wide: vertical container
    return {"side": side, "top": top}


REAL_CONFIG = {"sites": {"belt-l0": {"layer": 0, "col": 2, "row": 1}}}


def _real(after, before_images):
    cell = Cell({"top": "u", "side": "u"}, image=after)
    before_frame = {"image": before_images["top"], "before_side": {"image": before_images["side"]}}
    return czv.measure(cell, before_frame, REAL_CONFIG, "belt-l0", "pinky", None)


@pytest.fixture
def real_zones(monkeypatch):
    import cell_area_zones

    monkeypatch.setattr(czv, "verify_stack_outcome", cell_area_zones.verify_stack_outcome)


def test_real_measurement_verifies_a_container_that_appeared_in_both_target_zones(real_zones):
    out = _real(_scene(True, True), _scene(False, False))
    assert out["basis"] == czv.BASIS and out["verified"] is True
    assert out["top"]["zone"]["within_zone"] is True and out["place_slot"]["after_fill"] > 0.3


def test_real_measurement_refuses_a_container_that_was_already_there(real_zones):
    out = _real(_scene(True, True), _scene(True, False))  # the side zone was already full before the transfer
    assert out["verified"] is False


def test_real_measurement_refuses_when_one_target_zone_is_empty(real_zones):
    assert _real(_scene(True, False), _scene(False, False))["verified"] is False  # nothing in the top zone
    assert _real(_scene(False, True), _scene(False, False))["verified"] is False  # nothing in the side zone


# Trimmed from the real cell configs (cell PC, 2026-11-19): site place xy only (no col/row), cameras top and wrist, side only
# under episodes.cameras. No personal paths, tokens or addresses are kept.
REAL_AB = {"cameras": {"top": {}, "wrist": {}}, "episodes": {"cameras": {"side": "http://127.0.0.1:8767/frame/side.jpg"}},
           "sites": {"pallet": {"surface_z": -0.01, "z": 0.005, "yaw_deg": -90.0, "tier_step_m": 0.0324,
                                "place": [0.153, -0.128], "auto_roi": [246, 148, 400, 405]}}}


@pytest.mark.parametrize("dest", ["pallet-l0", "pallet-l2"])
def test_real_cell_a_b_config_has_the_side_stream_but_no_slot_so_stays_unverified(dest):
    import cell_place_fit

    config = cell_place_fit.with_tiers(REAL_AB)[0]
    out = czv.measure(Cell({"top": "u", "wrist": "u"}), before(), config, dest, "pallet-l0", None)
    assert out["side"]["available"] is True and out["verified"] is False and "col/row" in out["basis"]


def test_a_pallet_without_a_fresh_depth_frame_is_not_verified(monkeypatch):
    monkeypatch.setattr(czv, "_depth_after", lambda config, after: (None, None, "depth capture unavailable"))
    out = czv.measure(Cell({"top": "u", "side": "u"}), before(), {**CONFIG, "zone_rois": {**FLOOR, "top": {"c2r1": [1, 2, 30, 40]}}},
                      "pallet-l0", "belt", None)
    assert out["verified"] is False and "depth capture unavailable" in out["basis"]


def test_the_depth_capture_is_the_existing_cell_depth_source_and_must_be_exposed_after_the_placement(monkeypatch, tmp_path):
    import cell_depth

    seen = {}

    def capture(device, out_raw, *, timeout_s):
        seen.update(device=device, timeout_s=timeout_s)
        return DEPTH, {"source_seq": 1, "exposure_wall_estimate_s": time.time() - 30, "valid_depth_ratio": 1.0}

    monkeypatch.setattr(cell_depth, "capture_top_depth_z16_receipt", capture)
    depth, receipt, why = REAL_DEPTH_AFTER({"cameras": {"top": {"depth_device": "/dev/depth-x"}}}, time.time())
    assert depth is None and "before the placement finished" in why
    assert seen == {"device": "/dev/depth-x", "timeout_s": czv.DEPTH_WAIT_S}
    monkeypatch.setattr(cell_depth, "capture_top_depth_z16_receipt", lambda *a, **k: None)
    assert REAL_DEPTH_AFTER({}, time.time())[2] == "depth capture unavailable"


def test_a_stuck_camera_read_gets_only_the_time_that_is_left():
    cell = Cell({"top": "u", "side": "u"})
    czv.measure(cell, before(), CONFIG, "pallet-l0", "belt", None)
    assert cell.calls and all(call[4] <= max(0.2, czv.FRAME_WAIT_S) + 1e-9 for call in cell.calls)  # not the 10 s default


def test_pallet_without_floor_rois_keeps_the_old_height_gate_and_takes_no_depth(monkeypatch):
    # Real verify_stack_outcome_z_mm without the depth reference: the old current-frame calibration check cannot report ok
    # (no independent side Z reference), so the gate is UNKNOWN and the record is not verified. No depth capture is made.
    import cell_area_zones

    monkeypatch.setattr(czv, "verify_stack_outcome_z_mm", cell_area_zones.verify_stack_outcome_z_mm)
    monkeypatch.setattr(czv, "_depth_after", lambda config, after: (_ for _ in ()).throw(AssertionError("no depth capture")))
    cell = Cell({"top": "u", "side": "u"}, image=_scene(True, True))
    out = czv.measure(cell, {"image": BLANK, "before_side": {"image": BLANK}}, {"sites": {"pallet-l0": {"layer": 0, **SITE}}},
                      "pallet-l0", "belt", None)
    assert out["verified"] is False and "depth" not in out


def test_a_carry_that_is_not_a_fleet_task_skips_the_extra_reads():
    cell = Cell({"top": "u", "side": "u"})
    row, tried = {}, {"verify": {"verified": True}, "transfer": {"steps": []}}
    czv.record(row, tried, cell, before(), CONFIG, "pallet-l0", "belt", None)  # no _fleet_task in the config
    assert cell.calls == [] and row["zone_verification"]["verified"] is False and "not a Fleet task" in row["zone_verification"]["basis"]


def test_the_check_is_pinned_to_the_target_slot_even_when_another_slot_holds_the_container(real_zones):
    # target col 2 row 2 is empty; a container sits in col 1 row 1. The shared function's substitute zones would find it.
    import cell_area_zones

    side, top = _scene(True, False)["side"], BLANK.copy()
    top[165:270, 315:368] = (0, 140, 255)
    args = dict(before_side=BLANK, after_side=side, before_top=BLANK, after_top=top, pick={"area": "belt"},
                place={"area": "belt", "col": 2, "row": 2, "tier": 1})
    strict = cell_area_zones.verify_stack_outcome(**args, strict_target=True)
    assert strict["verified"] is False and strict["place_slot"]["top_zone"]["roi"] == [370, 271, 420, 380]
    assert strict["place_slot"]["top_zone"]["within_zone"] is False


def test_zone_rois_from_the_cell_config_replace_the_constant_tables_for_this_check_only(fast):
    rois = {"top": {"c2r1": [300, 160, 360, 270]}, "side": {"c2t1": [200, 250, 290, 315]}}
    out = czv.measure(Cell({"top": "u", "side": "u"}), before(), {**CONFIG, "zone_rois": rois}, "pallet-l0", "belt", None)
    assert fast["zone_rois"] == rois and out["zone_rois"] == rois
    fast.clear()
    czv.measure(Cell({"top": "u", "side": "u"}), before(), CONFIG, "pallet-l0", "belt", None)
    assert "zone_rois" not in fast  # no override in the config: the verification path passes none, so the constants apply


@pytest.mark.parametrize("bad", [{"top": {"c4r1": [1, 2, 3, 4]}}, {"top": {"c2r1": [1, 2, 3]}}, {"top": {"c2r1": [5, 2, 3, 9]}},
                                 {"side": {"c2t1": [0, 0, 700, 100]}}, {"top": {"c2r1": [1.5, 2, 30, 40]}}, {"x": {}}, [1]])
def test_a_malformed_zone_table_refuses_instead_of_falling_back(fast, bad):
    out = czv.measure(Cell({"top": "u", "side": "u"}), before(), {**CONFIG, "zone_rois": bad}, "pallet-l0", "belt", None)
    assert out["verified"] is False and "zone_rois" in out["basis"] and not fast


def test_the_shared_function_uses_a_named_zone_and_the_constants_elsewhere(real_zones):
    import cell_area_zones

    side = BLANK.copy()
    side[260:310, 200:280] = (0, 140, 255)  # a container in a side zone that differs from the table's col 2 tier 1
    top = BLANK.copy()
    top[165:270, 300:360] = (0, 140, 255)  # and in a top zone left of the table's col 2 row 1
    args = dict(before_side=BLANK, after_side=side, before_top=BLANK, after_top=top, pick={"area": "belt"},
                place={"area": "belt", "col": 2, "row": 1, "tier": 1}, strict_target=True)
    default = cell_area_zones.verify_stack_outcome(**args)
    named = cell_area_zones.verify_stack_outcome(**args, zone_rois={"top": {"c2r1": [300, 160, 360, 270]},
                                                                  "side": {"c2t1": [200, 250, 290, 315]}})
    assert default["verified"] is False and named["verified"] is True
    assert named["place_slot"]["top_zone"]["roi"] == [300, 160, 360, 270]
    assert cell_area_zones.TOP_ROI_BY_COL_ROW[(2, 1)] == (370, 165, 420, 270)  # the shared table itself is untouched
