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

    def frame_receipt(self, camera, *, previous=None, max_age_s=2.0):
        self.calls.append((camera, previous, max_age_s, dict(self.cameras)))
        if camera in self.fail:
            raise ValueError("camera frame source has not advanced")
        now = time.time()
        return {"image": self.image.get(camera, BLANK), "camera": camera, "source_seq": 9,
                "source_stamp": self.stamps.get(camera, now) + self.offset, "captured_at": now, "jpeg_sha256": "abc"}


def before(side=True):
    return {"image": BLANK, "before_side": {"image": BLANK} if side else None}


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(czv, "FRAME_WAIT_S", 0.1)
    seen = {}

    def stack(**kw):
        seen.update(kw)
        return {**PASS, "z_gate": dict(PASS["z_gate"])}

    monkeypatch.setattr(czv, "verify_stack_outcome_z_mm", stack)
    monkeypatch.setattr(czv, "verify_stack_outcome", stack)
    return seen


def test_measured_with_before_and_after_frames_of_both_cameras(fast):
    cell = Cell({"top": "u", "side": "u"})
    out = czv.measure(cell, before(), CONFIG, "pallet-l2", "belt", None)
    assert out["basis"] == czv.BASIS and out["verified"] is True and out["z_gate"]["verdict"] == "PASS"
    assert out["target"] == {"site": "pallet-l2", "area": "pallet", "col": 2, "row": 1, "tier": 3}
    assert fast["place"] == {"area": "pallet", "col": 2, "row": 1, "tier": 3}
    assert fast["before_side"] is BLANK and fast["before_top"] is BLANK  # both before frames reach the measurement
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
    class Slow(Cell):  # the side answer takes long: the top frame is then older than 2 s when they are judged together
        def frame_receipt(self, camera, **kw):
            row = super().frame_receipt(camera, **kw)
            if camera == "side":
                row["source_stamp"] = time.time() - 0.0
                monkeypatch.setattr(czv.time, "time", lambda real=time.time: real() + 2.5)
            return row

    out = czv.measure(Slow({"top": "u", "side": "u"}), before(), CONFIG, "pallet-l0", "belt", None)
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
    czv.record(row, tried, Cell({"top": "u", "side": "u"}), before(), CONFIG, "pallet-l0", "belt", None)
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
