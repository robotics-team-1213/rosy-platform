"""D-1057: the placement zone verification record: fresh frames, existing zone measurements, honest basis."""
from __future__ import annotations

from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "deploy/robot/omx", ROOT / "middleware/devices/omx/adapter"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cell_zone_verification as czv  # noqa: E402

CONFIG = {"sites": {"pallet-l0": {"layer": 0, "col": 2, "row": 1}, "pallet-l2": {"layer": 2, "col": 2, "row": 1},
                    "belt": {"col": 1, "row": 1}, "pinky": {}}}
PASS = {"verified": True, "basis": czv.BASIS, "z_gate": {"verdict": "PASS"}, "place_slot": {"top_zone": {"within_zone": True}}}


class Cell:
    def __init__(self, cameras, age=0.1, fail=()):
        self.cameras, self.age, self.fail, self.calls = cameras, age, set(fail), []

    def frame_receipt(self, camera, *, previous=None, max_age_s=2.0):
        self.calls.append((camera, previous, max_age_s))
        if camera in self.fail:
            raise ValueError("camera frame source has not advanced")
        now = time.time()
        return {"image": object(), "camera": camera, "source_seq": 9, "source_stamp": now - self.age,
                "captured_at": now, "jpeg_sha256": "abc"}


@pytest.fixture(autouse=True)
def zones(monkeypatch):
    seen = {}

    def stack(**kw):
        seen.update(kw)
        return dict(PASS)

    monkeypatch.setattr(czv, "verify_stack_outcome_z_mm", stack)
    monkeypatch.setattr(czv, "verify_stack_outcome", stack)
    monkeypatch.setattr(czv, "evaluate_zone", lambda img, roi, **kw: {"within_zone": True, "fill_ratio": 0.5, "roi": list(roi)})
    return seen


def test_measured_with_fresh_side_and_top_frames(zones):
    cell = Cell({"top": "u", "side": "u"})
    out = czv.measure(cell, {"image": object()}, CONFIG, "pallet-l2", "belt", None)
    assert out["basis"] == czv.BASIS and out["verified"] is True and out["z_gate"]["verdict"] == "PASS"
    assert out["top"]["frame"]["camera"] == "top" and out["side"]["frame"]["camera"] == "side"
    assert out["measured_at"] >= out["top"]["frame"]["captured_at"]
    assert zones["place"] == {"area": "pallet", "col": 2, "row": 1, "tier": 3}
    assert all(max_age == czv.MAX_FRAME_AGE_S for _, _, max_age in cell.calls)


@pytest.mark.parametrize("fail", [("side",), ("top",)])
def test_one_camera_failing_is_not_verified(fail):
    out = czv.measure(Cell({"top": "u", "side": "u"}, fail=fail), None, CONFIG, "pallet-l0", "belt", None)
    assert out["verified"] is False and out["basis"].startswith("unverified:") and out["basis"] != czv.BASIS


@pytest.mark.parametrize("which", ["top", "side"])
def test_a_frame_older_than_two_seconds_is_not_verified(which):
    class Old(Cell):
        def frame_receipt(self, camera, **kw):
            self.age = 2.5 if camera == which else 0.1
            return super().frame_receipt(camera, **kw)

    out = czv.measure(Old({"top": "u", "side": "u"}), None, CONFIG, "pallet-l0", "belt", None)
    assert out["verified"] is False and "older than" in out["basis"]


def test_a_failed_zone_measurement_is_not_verified(monkeypatch):
    monkeypatch.setattr(czv, "verify_stack_outcome_z_mm", lambda **kw: {"verified": False, "basis": czv.BASIS,
                                                                        "z_gate": {"verdict": "FAIL"}})
    out = czv.measure(Cell({"top": "u", "side": "u"}), None, CONFIG, "pallet-l0", "belt", None)
    assert out["verified"] is False and out["z_gate"]["verdict"] == "FAIL"


def test_cell_without_a_side_camera_never_claims_the_two_camera_basis():
    out = czv.measure(Cell({"top": "u"}), None, CONFIG, "belt", "pinky", (1, 2, 30, 40))
    assert out["basis"] == czv.TOP_ONLY_BASIS != czv.BASIS
    assert out["side"] == {"available": False, "reason": "no side camera in this cell"}
    assert out["verified"] is True and out["top"]["zone"]["roi"] == [1, 2, 30, 40]


def test_record_puts_the_measurements_on_the_attempt_row():
    row, tried = {"observed": 1}, {"verify": {"verified": True}, "transfer": {"steps": []}}
    czv.record(row, tried, Cell({"top": "u", "side": "u"}), None, CONFIG, "pallet-l0", "belt", None)
    assert row["verify"] == {"verified": True} and row["transfer"] == {"steps": []}
    assert row["zone_verification"] is tried["zone_verification"] and row["zone_verification"]["verified"] is True


def test_missing_target_slot_is_not_verified():
    out = czv.measure(Cell({"top": "u", "side": "u"}), None, CONFIG, "pinky", "belt", None)
    assert out["verified"] is False and "col/row" in out["basis"]


def test_executor_refuses_the_top_only_record_and_accepts_the_two_camera_record(tmp_path, monkeypatch):
    import test_omx_cell_task_exec_measured as helpers

    for zone, expected in ((czv.measure(Cell({"top": "u"}), None, CONFIG, "belt", "pinky", (1, 2, 30, 40)), False),
                           (czv.measure(Cell({"top": "u", "side": "u"}), None, CONFIG, "pallet-l0", "belt", None), True)):
        out = helpers._exec(tmp_path, monkeypatch, {"result": "placed", "attempts": [helpers._attempt(zone=zone)]})
        assert out["stage_result"]["task_verified"] is expected
        assert out["stage_result"]["verification"]["basis"] == zone["basis"]
