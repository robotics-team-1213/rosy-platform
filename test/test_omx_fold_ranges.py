"""Fold judgement narrowed by the arm's own park/home/standby poses; without them the coarse rule stays and says so."""
from pathlib import Path
import sys

DIR = Path(__file__).parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(DIR))
import cell_job_peer_health as ph  # noqa: E402
import cell_policy_timing as timing  # noqa: E402

HOME = [0.0, -58.0, 50.0, 50.0, -5.0, 58.1]
LIB = {"chunks": {"home": [HOME], "park": [[0.5, -57.0, 49.0, 51.0, -4.0, 58.0]]}}
CELL = {"plan": {"home": HOME, "park": HOME}}
REAL_1126 = [-0.02, -58.05, 54.97, 50.13, -4.96, 49.16]  # the pose 11-26 actually folded to
WRIST_OUT = [0.0, -58.0, 50.0, -10.0, -5.0, 58.1]  # lift/elbow pass the coarse rule, the wrist is stretched
ROLL_OUT = [0.0, -58.0, 50.0, 50.0, 60.0, 58.1]


def test_real_fold_is_folded_with_and_without_library():
    for src in ((), (LIB,), (CELL,), (LIB, CELL)):
        assert ph.live_folded({"state": REAL_1126}, *src) is True


def test_wrist_only_extension_is_refused_with_library_but_slips_through_coarse():
    assert ph.live_folded({"state": WRIST_OUT}) is True  # coarse fallback: the known gap
    assert ph.live_folded({"state": WRIST_OUT}, LIB) is False
    assert ph.live_folded({"state": ROLL_OUT}, LIB) is False
    assert ph.live_folded({"state": ROLL_OUT}, LIB, include_wrist_roll=False) is True
    assert ph.live_folded({"state": WRIST_OUT}, LIB, include_wrist_roll=False) is False
    assert ph.live_folded({"state": [0, -30.0, 50.0, 50.0, -5.0, 0]}, LIB) is False  # coarse still applies first


def test_fold_basis_and_unusable_library_fall_back():
    assert ph.fold_basis(LIB) == "calibrated" and ph.fold_basis(CELL) == "calibrated"
    for bad in (None, {}, {"chunks": {}}, {"chunks": {"home": []}}, {"chunks": {"home": [["x"] * 6]}}):
        assert ph.fold_basis(bad) == "coarse"
        assert ph.live_folded({"state": WRIST_OUT}, bad) is True


def test_calibrated_positions_use_library():
    cal = {n: {"id": 11 + i, "drive_mode": 0, "homing_offset": 0, "range_min": 0, "range_max": 4000}
           for i, n in enumerate(ph.FOLLOWER_JOINTS)}
    raw = [2000, 500, 3500, 2000, 2000, 2000]  # lift -75, elbow +75, wrist flex 0
    assert ph.calibrated_positions_folded(raw, cal) is True
    assert ph.calibrated_positions_folded(raw, cal, {"chunks": {"home": [[0, -75, 75, 0, 0, 0]]}}) is True
    assert ph.calibrated_positions_folded(raw, cal, LIB) is False  # wrist flex 0 is far from this arm's 50


def test_rest_diagnosis_forwards_library_to_hold_decision():
    status = {"state": WRIST_OUT, "ok": True, "holding": False, "chunk": None}
    assert timing.idle_at_home(status, HOME) is True  # coarse: wrist-only extension reads as folded, but it is not at home...
    assert timing.idle_at_home(status, HOME, LIB) is False


def test_rest_diagnosis_reports_basis():
    status = {"state": REAL_1126, "ok": True, "holding": False, "chunk": None}
    assert timing.rest_diagnosis(status, HOME)["fold_basis"] == "coarse"
    out = timing.rest_diagnosis({**status, "state": WRIST_OUT}, HOME, LIB)
    assert out["fold_basis"] == "calibrated" and out["folded"] is False
