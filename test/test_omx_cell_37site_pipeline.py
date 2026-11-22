"""End-to-end tests for the 37-site canonical coordinate, 1-3 tier stacking, and verification pipeline in OMX Cell."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "deploy/robot/omx", ROOT / "middleware/devices/omx/adapter"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cell_area_zones as caz  # noqa: E402
from cell_fleet_handoff import handoff_refusal, run_contract_handoff_stage  # noqa: E402
import cell_fleet_pipeline as cfp  # noqa: E402
import cell_site_target as cst  # noqa: E402
import cell_task_exec as cte  # noqa: E402
import cell_task_worker as ctw  # noqa: E402
import cell_zone_verification as czv  # noqa: E402

LOCKED = {"wheel_brake_locked": True, "bed_ready": True, "v_cmd_mps": 0.0}
HOME = [0.0, -58.0, 50.0, 50.0, -5.0, 58.1]
PARK = {"command": "park", "ok": True, "settled": True, "fault": None, "state": [0.5, -57.0, 49.0, 51.0, -4.0, 58.0], "t": 12.0}
BLANK = np.zeros((480, 640, 3), np.uint8)
DEPTH = np.full((480, 640), 611, np.uint16)


def test_all_37_canonical_wire_and_sim_sites_resolve_roundtrip():
    doc = json.loads((ROOT / "shared/web/cell-site-map.json").read_text(encoding="utf-8"))
    seen = set()
    for zone in doc["zones"]:
        for slot in zone["slots"]:
            for t in slot["tiers"]:
                wire = f"{zone['id']}-r{slot['row']}-c{slot['columns'][0]}-l{t['tier']}"
                r_id = cst.resolve_cell_ab_site(t["id"], t["tier"], allow_belt_temp=False)
                r_wire = cst.resolve_cell_ab_site(wire, None, allow_belt_temp=False)
                r_sim = cst.resolve_cell_ab_site(t["item"], t["tier"], allow_belt_temp=False)
                assert r_id == r_wire == r_sim
                assert r_id["sim_site"] == t["item"] and r_id["tier"] == t["tier"]
                seen.add(t["id"])
    assert len(seen) == 37
    assert cst.resolve_cell_ab_site("ship-stern-l0", 1, allow_belt_temp=False) is None


def test_worker_handoff_refuses_disallowed_arms_tiers_and_unknown_sites_before_arm(tmp_path: Path):
    pipe = cfp.FleetModelPipeline(tmp_path / "pipe")
    assert handoff_refusal(pipe, {**LOCKED, "cell_id": "cell_ab", "arm_id": "arm_b", "src_site": "belt", "dst_site": "yard:r1-s2-t2"}, 2) is None
    assert handoff_refusal(pipe, {**LOCKED, "cell_id": "cell_ab", "arm_id": "arm_a", "src_site": "belt", "dst_site": "temp_a:r1-s1-t3"}, 3) is None
    assert handoff_refusal(pipe, {**LOCKED, "cell_id": "cell_ab", "arm_id": "arm_b", "src_site": "belt", "dst_site": "temp_b:r2-s1-t1"}, 1) is None

    for bad in (
        {"arm_id": "arm_b", "src_site": "belt", "dst_site": "temp_a:r1-s1-t1", "tier": 1},
        {"arm_id": "arm_a", "src_site": "belt", "dst_site": "temp_b:r1-s1-t1", "tier": 1},
        {"arm_id": "arm_b", "src_site": "belt", "dst_site": "stand:r1-s1-t1", "tier": 1},
        {"arm_id": "arm_a", "src_site": "belt", "dst_site": "yard:r1-s2-t2", "tier": 1},
        {"arm_id": "arm_a", "src_site": "pinky", "dst_site": "yard:r1-s2-t1", "tier": 1},
        {"arm_id": "arm_a", "src_site": "belt", "dst_site": "ship-stern-l0", "tier": 1},
    ):
        assert handoff_refusal(pipe, {**LOCKED, "cell_id": "cell_ab", **bad}, bad["tier"]) == "UNKNOWN_SITE"

    hw_calls: list[dict] = []

    def req(method: str, path: str, body):
        if method == "GET":
            return {"tasks": [{"task_id": "t-bad", "cell_id": "cell_ab", "arm_id": "arm_b", "tier": 1}],
                    "human_safety": {"active_estop": False, "human_detected": {}},
                    "cells": {"cell_ab": {"phase": "ARM_IN_BED_ZONE", "active_task_id": "t-bad"}}}
        if path.endswith("/claim"):
            return {"claimed": True, "gate": {}, "handoff": {
                **LOCKED, "task_id": "t-bad", "cell_id": "cell_ab", "arm_id": "arm_b",
                "tier": 1, "handoff_lease_id": "l-1", "src_site": "belt", "dst_site": "temp_a:r1-s1-t1",
            }}
        return {"gate": {}, "task": {"status": "ABORTED"}}

    runs = ctw.poll_and_execute_once(pipe, request_fn=req, live_act_fn=hw_calls.append, prep_dir=tmp_path)
    assert hw_calls == [] and runs[0]["omx_result"]["receipt"]["reason"] == "UNKNOWN_SITE"
    stage = run_contract_handoff_stage(pipe, {**LOCKED, "cell_id": "cell_ab", "arm_id": "arm_a", "src_site": "belt", "dst_site": "stand:r1-s1-t1"}, tier=1)
    assert stage["receipt"]["cell_id"] == "cell_ab" and stage["stage_result"] is not None


def test_executor_normalizes_canonical_targets_refuses_uncalibrated_and_emits_place(tmp_path: Path, monkeypatch):
    for w in ("with-session-arm-a-par.sh", "with-session-arm-b-par.sh"):
        (tmp_path / w).write_text("#!/bin/sh\n", encoding="utf-8")
    (tmp_path / "grasp-plan.json").write_text(json.dumps({"home": HOME}), encoding="utf-8")
    cfg = {
        "plan_path": str(tmp_path / "grasp-plan.json"),
        "sites": {
            "beltend": {},
            "ship-h1r2": {"place": [0.15, -0.10], "surface_z": -0.01},
            "tmp-a-1": {"place": [0.05, 0.14], "surface_z": 0.01},
        },
    }
    (tmp_path / "cell-arm-a-stack.json").write_text(json.dumps(cfg), encoding="utf-8")
    (tmp_path / "cell-arm-b-stack.json").write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(cte, "check_arm_hold", lambda _arm: {"held": False})
    monkeypatch.setattr(cte, "measured_fold", lambda _a, _p, now=None: {"folded": True, "state": None, "fresh": True})
    monkeypatch.setattr(cte, "source_clearance", lambda *a, **k: {"objects": 0})
    cmds: list[list[str]] = []

    def fake_run(cmd, **k):
        cmds.append(list(cmd))
        dest_arg = cmd[cmd.index("--dest") + 1]
        tid = cmd[cmd.index("--task-id") + 1]
        resolved = cst.resolve_cell_ab_site(dest_arg, None, allow_belt_temp=False)
        parsed = {"result": "placed", "attempts": [{
            "verify": {"verified": True, "inside": True, "basis": "map"},
            "transfer": {"result": "placed", "steps": [PARK]},
            "zone_verification": {
                "verified": True, "basis": "predefined_side_and_top_target_zones",
                "z_gate": {"verdict": "PASS"},
                "target": {"site": dest_arg, "site_id": resolved["site_id"], "area": resolved["area"],
                           "col": resolved["col"], "row": resolved["row"], "tier": resolved["tier"]},
            },
        }]}
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(parsed), stderr="")

    monkeypatch.setattr(cte.subprocess, "run", fake_run)
    uncal = cte.execute_guarded_cell_task({
        "task_id": "t-uncal", "cell_id": "cell_ab", "arm_id": "arm_b", "tier": 2,
        "handoff_lease_id": "l-u", "src_site": "belt", "dst_site": "yard:r3-s1-t2",
    }, prep_dir=tmp_path)
    assert uncal["error"] == "SITE_NOT_CALIBRATED" and cmds == []

    wrong_arm = cte.execute_guarded_cell_task({
        "task_id": "t-wrong-arm", "cell_id": "cell_ab", "arm_id": "arm_b", "tier": 1,
        "handoff_lease_id": "l-w", "src_site": "belt", "dst_site": "temp_a:r1-s1-t1",
    }, prep_dir=tmp_path)
    assert wrong_arm["error"] == "SITE_ARM_NOT_ALLOWED" and cmds == []

    ok = cte.execute_guarded_cell_task({
        "task_id": "t-yard-2", "cell_id": "cell_ab", "arm_id": "arm_b", "tier": 2,
        "handoff_lease_id": "l-2", "src_site": "belt", "dst_site": "yard-r1-c4-l2",
    }, prep_dir=tmp_path)
    assert cmds[0][cmds[0].index("--dest") + 1] == "ship-h1r2-l1"
    assert ok["stage_result"]["task_verified"] is True
    assert ok["stage_result"]["place"] == {
        "area": "yard", "site": "ship-h1r2-l1", "site_id": "yard:r1-s2-t2", "col": 1, "row": 2, "tier": 2,
    }


def test_zone_verification_uses_site_rois_and_blocks_temp_aliasing_to_c1r1(monkeypatch):
    monkeypatch.setattr(czv, "FRAME_WAIT_S", 0.1)
    monkeypatch.setattr(czv, "_depth_after", lambda *a: (
        DEPTH, {"source_seq": 3, "exposure_wall_estimate_s": time.time(), "valid_depth_ratio": 1.0, "raw_sha256": "d"}, None))
    seen: dict = {}

    def fake_stack(**kw):
        seen.update(kw)
        return {"verified": True, "basis": czv.BASIS, "z_gate": {"verdict": "PASS"},
                "place_slot": {"top_zone": {"within_zone": True, "orientation_ok": True, "fill_ratio": 0.5}}}

    monkeypatch.setattr(czv, "verify_stack_outcome_z_mm", fake_stack)
    monkeypatch.setattr(czv, "verify_stack_outcome", fake_stack)

    class Cell:
        cameras = {"top": "u", "side": "u"}

        def frame_receipt(self, camera, **_kw):
            now = time.time()
            return {"image": BLANK, "camera": camera, "source_seq": 5, "source_stamp": now, "captured_at": now, "jpeg_sha256": "x"}

    before = {"image": BLANK, "before_side": {"image": BLANK}}
    # temp_a must NOT alias c1r1 when zone_rois.floor is enabled without tmp-a-1!
    cfg_missing_temp = {
        "sites": {"tmp-a-1": {"place": [0.05, 0.14], "surface_z": 0.01}},
        "zone_rois": {"top": {"c1r1": [10, 10, 40, 40]}, "floor": [[10, 10, 80, 60]], "floor_depth_mm": [600.0]},
    }
    refused = czv.measure(Cell(), before, cfg_missing_temp, "tmp-a-1", "belt", None)
    assert refused["verified"] is False and "tmp-a-1" in refused["basis"] and not seen

    cfg_temp = {
        "sites": {"tmp-a-1-l1": {"layer": 1, "place": [0.05, 0.14], "surface_z": 0.04}},
        "zone_rois": {"top": {"tmp-a-1": [240, 365, 292, 433]}, "floor": [[10, 10, 80, 60]], "floor_depth_mm": [600.0]},
    }
    ok_temp = czv.measure(Cell(), before, cfg_temp, "tmp-a-1-l1", "belt", None)
    assert ok_temp["verified"] is True and ok_temp["z_gate"]["verdict"] == "PASS"
    assert seen["after_depth"] is DEPTH and seen["place"]["base_site"] == "tmp-a-1" and seen["place"]["tier"] == 2
    assert cst.top_slot_roi(cfg_temp["zone_rois"], seen["place"]) == (240, 365, 292, 433)


def test_stand_with_floor_rois_and_worker_slot_arm_calibration_guards(monkeypatch):
    import cell_area_zones as caz
    import cell_fleet_handoff as cfh
    import cell_presence as cp

    # Real verify_stack_outcome on stand must verify top orientation + fill without depth when floor ROIs exist.
    monkeypatch.setattr(caz, "detect_side_self_profile_landmarks", lambda _img: [])
    before_side = np.zeros((480, 640, 3), dtype=np.uint8)
    after_side = np.full((480, 640, 3), 1, dtype=np.uint8)
    before_top = np.full((480, 640, 3), 2, dtype=np.uint8)
    after_top = np.full((480, 640, 3), 3, dtype=np.uint8)

    def fake_eval(img, roi, **_kw):
        roi_t = tuple(roi)
        if img is before_top and roi_t == (355, 40, 415, 160):
            return {"within_zone": True, "fill_ratio": 0.55, "offset_px": 0.0, "orientation_ok": True}
        if img is after_top and roi_t == (410, 30, 570, 125):
            return {"within_zone": True, "fill_ratio": 0.52, "offset_px": 0.0, "orientation_ok": True}
        return {"within_zone": False, "fill_ratio": 0.05, "offset_px": 0.0, "orientation_ok": True}

    monkeypatch.setattr(caz, "evaluate_zone", fake_eval)
    stand_rois = {"top": {"stand": [410, 30, 570, 125]}, "floor": [[10, 10, 80, 60]], "floor_depth_mm": [600.0]}
    stand_ok = caz.verify_stack_outcome(
        before_side=before_side, after_side=after_side, before_top=before_top, after_top=after_top,
        pick={"area": "belt", "col": 1, "row": 1, "tier": 1},
        place={"area": "stand", "base_site": "stand", "col": 1, "row": 1, "tier": 1, "yaw_deg": 0.0},
        strict_target=True, zone_rois=stand_rois, after_depth=None,
    )
    assert stand_ok["verified"] is True and stand_ok["depth_reference"] is None

    # Arm, cross-plate, and calibration guards on legacy temp_plate_* and stand tier mismatch.
    assert cst.arm_refusal("temp_plate_a", "pallet-l0", "arm_b") == "SITE_ARM_NOT_ALLOWED"
    assert cst.arm_refusal("belt", "temp_plate_b", "arm_a") == "SITE_ARM_NOT_ALLOWED"
    assert cst.arm_refusal("temp_plate_a", "stand", "arm_a") is None
    assert cst.validate_cell_ab_handoff("temp_a:r1-s1-t1", "temp_b:r1-s1-t1", 1, "") == "UNKNOWN_SITE"
    assert cst.calibration_refusal({"stand": {"place": [0.2, -0.1], "surface_z": 0.02}}, "belt", "stand:r1-s1", 2) == "STAND_NOT_CALIBRATED"
    assert cst.calibration_refusal({"pallet-l0": {"place": [0.0, 0.0], "surface_z": 0.0}}, "temp_plate_a", "pallet-l0", 1) == "SITE_NOT_CALIBRATED"

    # Strict slot, site_id, and verification.target binding at zone_acceptance and cell_ab_place_verified.
    handoff = {"cell_id": "cell_ab", "arm_id": "arm_b", "dst_site": "ship-h1r2-l1", "dst_site_id": "yard:r1-s2-t2",
               "dst_area": "yard", "dst_slot": {"col": 1, "row": 2, "tier": 2}, "tier": 2}
    valid_target = {"site": "ship-h1r2-l1", "site_id": "yard:r1-s2-t2", "area": "yard", "col": 1, "row": 2, "tier": 2}
    assert cp.zone_acceptance({"verified": True, "basis": cp.ZONE_BASIS, "target": valid_target}, handoff, "ship-h1r2-l1") is True
    assert cp.zone_acceptance({"verified": True, "basis": cp.ZONE_BASIS, "target": {"site": "ship-h1r2-l1", "area": "yard", "col": 1, "row": 2, "tier": 2}}, handoff, "ship-h1r2-l1") is False
    assert cp.zone_acceptance({"verified": True, "basis": cp.ZONE_BASIS, "target": {**valid_target, "col": 2}}, handoff, "ship-h1r2-l1") is False

    good_place = {"area": "yard", "site": "ship-h1r2-l1", "site_id": "yard:r1-s2-t2", "col": 1, "row": 2, "tier": 2}
    good_ver = {"target": valid_target}
    assert cst.cell_ab_place_verified(handoff, good_place, {"verdict": "PASS"}, 2, good_ver) is True
    assert cst.cell_ab_place_verified(handoff, {"area": "yard", "site": "ship-h1r2-l1", "site_id": "yard:r1-s2-t2", "tier": 2}, {"verdict": "PASS"}, 2, good_ver) is False
    assert cst.cell_ab_place_verified(handoff, {"area": "yard", "site": "ship-h1r2-l1", "col": 1, "row": 2, "tier": 2}, {"verdict": "PASS"}, 2, good_ver) is False
    assert cst.cell_ab_place_verified(handoff, good_place, {"verdict": "PASS"}, 2, {"target": {**valid_target, "site_id": "yard:r2-s2-t2"}}) is False
    assert cst.cell_ab_place_verified(handoff, good_place, {"verdict": "PASS"}, 2, {}) is False

    stand_handoff = {"cell_id": "cell_ab", "arm_id": "arm_a", "dst_site": "stand", "dst_site_id": "stand:r1-s1-t1",
                     "dst_area": "stand", "dst_slot": {"col": 1, "row": 1, "tier": 1}, "tier": 1}
    assert cst.cell_ab_place_verified(stand_handoff, {"area": "stand", "site": "stand", "site_id": "stand:r1-s1-t1", "col": 1, "row": 1, "tier": 1}, {}, 1, {"target": {"site_id": "stand:r1-s1-t1", "area": "stand", "col": 1, "row": 1, "tier": 1}}) is True
    assert cst.cell_ab_place_verified(stand_handoff, {"area": "stand", "site": "stand", "col": 1, "row": 1, "tier": 1}, {}, 1, {"target": {"site_id": "stand:r1-s1-t1", "area": "stand", "col": 1, "row": 1, "tier": 1}}) is False

    # Unchecked omitted arm_id fails on cross-plate handoff.
    assert cfh.handoff_refusal(None, {"wheel_brake_locked": True, "bed_ready": True, "v_cmd_mps": 0.0,
                                      "cell_id": "cell_ab", "src_site": "temp_a:r1-s1-t1", "dst_site": "temp_b:r1-s1-t1"}, 1) == "UNKNOWN_SITE"
