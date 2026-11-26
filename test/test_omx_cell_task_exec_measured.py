"""D-1057: the cell task executor reports measured placement and a measured fold, never a single placed flag."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "deploy/robot/omx", ROOT / "middleware/devices/omx/adapter"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cell_fleet_pipeline as cfp  # noqa: E402
import cell_task_exec as cte  # noqa: E402
import cell_task_worker as ctw  # noqa: E402

HOME = [0.0, -58.0, 50.0, 50.0, -5.0, 58.1]
ZONE = {"verified": True, "basis": "predefined_side_and_top_target_zones", "z_gate": {"verdict": "PASS"},
        "target": {"site": "belt", "area": "belt", "col": 2, "row": 1, "tier": 1}}
PARK = {"command": "park", "ok": True, "settled": True, "fault": None, "state": [0.5, -57.0, 49.0, 51.0, -4.0, 58.0], "t": 12.5}
HANDOFF = {"task_id": "t-1", "cell_id": "cell_s", "arm_id": "arm_s", "tier": 1, "handoff_lease_id": "lease-1",
           "src_site": "pinky", "dst_site": "belt"}


# Log lines with braces, as the CLI and its session wrapper print before the final indented JSON object.
CLI_NOISE = 'wrapper: starting {"session": "x"}\nconfig {a} loaded\n{\n'.replace("{\n", "") + "\n"


def _attempt(verify=None, park=PARK, zone=ZONE):
    steps = [{"command": "run lift_place", "ok": True}] + ([park] if park is not None else [])
    row = {"verify": verify if verify is not None else {"found": True, "inside": True, "verified": True, "basis": "map"},
           "transfer": {"result": "placed", "steps": steps}}
    return {**row, **({"zone_verification": zone} if zone is not None else {})}


def _exec(tmp_path, monkeypatch, parsed, *, home=HOME, returncode=0, handoff=None, live_folded=True, record=None):
    (tmp_path / "with-session-arm-s-live.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    # as in the real cell config: the home lives in the grasp plan file that `plan_path` names, not in the config JSON
    (tmp_path / "grasp-plan.json").write_text(json.dumps({"home": home} if home else {}), encoding="utf-8")
    (tmp_path / "cell-auto-arm-s-live.json").write_text(json.dumps({"plan_path": str(tmp_path / "grasp-plan.json")}), encoding="utf-8")
    monkeypatch.setattr(cte, "check_arm_hold", lambda arm: {"held": False})
    # main's telemetry reader and the post-carry source look: the live runner state says folded and fresh; nothing is left at the source
    monkeypatch.setattr(cte, "measured_fold", lambda arm, prep, now=None: {"folded": live_folded, "state": None, "fresh": True})
    monkeypatch.setattr(cte, "source_clearance", lambda *a, **k: {"objects": 0, "site": "pinky"})
    monkeypatch.setattr(cte.subprocess, "run", lambda *a, **k: (record.append(a[0]) if record is not None else None) or subprocess.CompletedProcess(
        a, returncode, stdout=CLI_NOISE + json.dumps(parsed, indent=1, default=str) + "\n", stderr=""))  # as cell_auto_pick prints it
    return cte.execute_guarded_cell_task(handoff or HANDOFF, prep_dir=tmp_path)


def test_measured_placement_and_fold_fill_every_field(tmp_path, monkeypatch):
    out = _exec(tmp_path, monkeypatch, {"result": "placed", "attempts": [_attempt()]})
    stage, stop = out["stage_result"], out["stop_event"]
    assert stage["task_verified"] is True and stage["verification"]["verified"] is True
    assert stage["verification"]["basis"] == "predefined_side_and_top_target_zones"
    assert stage["verification"]["placement"]["basis"] == "map"  # the top-frame check is carried as measured
    assert stop["ok"] is True and stop["folded"] is True and stop["state"] == PARK["state"]
    assert stop["readback"]["tolerance"] == cte.FOLD_TOLERANCE and isinstance(out["measured_at"], float)
    assert "error" not in out


@pytest.mark.parametrize("parsed", [
    {"result": "placed"},                                         # the old single flag with no record behind it
    {"result": "placed", "attempts": []},
    {"result": "placed", "attempts": [{"verify": {"verified": True, "inside": False, "basis": "map"}}]},
    {"result": "placed", "attempts": [_attempt(verify={"found": False, "inside": False, "verified": False})]},
    {"result": "stopped: contact", "attempts": [_attempt()]},
])
def test_placed_flag_alone_never_verifies_or_folds(tmp_path, monkeypatch, parsed):
    out = _exec(tmp_path, monkeypatch, parsed)
    assert out["stage_result"]["task_verified"] is False and out["error"]
    if not parsed.get("attempts") or "transfer" not in parsed["attempts"][0]:
        assert out["stop_event"]["folded"] is False and out["stop_event"]["ok"] is False
    else:  # the park readback is measured on its own, but the arm is released as folded only after a verified placement
        assert out["stop_event"]["readback"]["folded"] is True and out["stop_event"]["folded"] is False


def test_without_a_zone_measurement_the_basis_is_not_claimed(tmp_path, monkeypatch):
    out = _exec(tmp_path, monkeypatch, {"result": "placed", "attempts": [_attempt(zone=None)]})
    verification = out["stage_result"]["verification"]
    assert out["stage_result"]["task_verified"] is False and verification["verified"] is False
    assert verification["basis"] == "map" and verification["z_gate"]["verdict"] == "UNKNOWN"
    assert out["stop_event"]["folded"] is True  # the fold is measured on its own


@pytest.mark.parametrize("park, home", [
    (None, HOME),                                                              # no park step at all
    ({**PARK, "settled": False}, HOME),
    ({**PARK, "ok": False}, HOME),
    ({**PARK, "fault": "contact"}, HOME),
    ({**PARK, "state": [0.0, -50.0, 50.0, 50.0, -5.0, 58.0]}, HOME),         # 8 deg off home
    ({**PARK, "state": [float("nan")] * 6}, HOME),
    ({**PARK, "state": None}, HOME),
    ({"command": "run lift_place", "ok": True, "settled": True, "state": HOME}, HOME),  # last step is not a park
    (PARK, None),                                                             # config names no home
])
def test_fold_needs_a_settled_park_readback_at_home(tmp_path, monkeypatch, park, home):
    out = _exec(tmp_path, monkeypatch, {"result": "placed", "attempts": [_attempt(park=park)]}, home=home)
    assert out["stop_event"]["folded"] is False and out["stop_event"]["ok"] is False
    assert out["error"] == "FOLD_READBACK_MISSING"


def test_fold_tolerance_boundary():
    edge = {**PARK, "state": [HOME[0] + cte.FOLD_TOLERANCE] + HOME[1:]}
    assert cte.fold_readback({"transfer": {"steps": [edge]}}, HOME)["folded"] is True
    over = {**PARK, "state": [HOME[0] + cte.FOLD_TOLERANCE + 0.01] + HOME[1:]}
    assert cte.fold_readback({"transfer": {"steps": [over]}}, HOME)["folded"] is False
    assert cte.FOLD_TOLERANCE == pytest.importorskip("chunk_runner_guards").SETTLE_TOL


def _poll(tmp_path, hw):
    posted = []

    def req(method, path, body):
        if method == "GET":
            return {"tasks": [{"task_id": "t-1", "cell_id": "cell_s", "tier": 1},],
                    "human_safety": {"active_estop": False, "human_detected": {}},
                    "cells": {"cell_s": {"phase": "ARM_IN_BED_ZONE", "active_task_id": "t-1"}}}
        if path.endswith("/claim"):
            return {"claimed": True, "gate": {}, "handoff": {**HANDOFF, "wheel_brake_locked": True, "bed_ready": True,
                                                              "v_cmd_mps": 0.0}}
        posted.append((path, body))
        return {"gate": {}, "task": {"status": body.get("phase", "RELEASED")}}

    ctw.poll_and_execute_once(cfp.FleetModelPipeline(tmp_path / "pipe"), request_fn=req, live_act_fn=lambda h: hw,
                              prep_dir=tmp_path)
    return posted


def test_worker_posts_owner_evidence_before_complete_with_the_same_objects(tmp_path, monkeypatch):
    out = _exec(tmp_path, monkeypatch, {"result": "placed", "attempts": [_attempt()]})
    posted = _poll(tmp_path, out)
    assert [p.rsplit("/", 1)[1] for p, _ in posted] == ["owner-evidence", "complete"]
    evidence, complete = posted[0][1], posted[1][1]
    assert complete["phase"] == "RELEASED" and evidence["measured_at"] == out["measured_at"]
    for key in ("receipt", "stage_result", "hardware_telemetry"):
        assert evidence[key] == complete[key]
    assert evidence["handoff_lease_id"] == "lease-1" and complete["hardware_telemetry"]["stop_event"]["folded"] is True


def test_worker_aborts_and_sends_no_owner_evidence_when_the_fold_is_unmeasured(tmp_path, monkeypatch):
    out = _exec(tmp_path, monkeypatch, {"result": "placed", "attempts": [_attempt(park=None)]})
    posted = _poll(tmp_path, out)
    assert [p.rsplit("/", 1)[1] for p, _ in posted] == ["complete"] and posted[0][1]["phase"] == "ABORTED"


def test_worker_aborts_without_a_measurement_time(tmp_path, monkeypatch):
    out = _exec(tmp_path, monkeypatch, {"result": "placed", "attempts": [_attempt()]})
    posted = _poll(tmp_path, {k: v for k, v in out.items() if k != "measured_at"})
    assert [p.rsplit("/", 1)[1] for p, _ in posted] == ["complete"] and posted[0][1]["reason"] == "MEASURED_PLACEMENT_MISSING"


def test_home_comes_from_the_plan_file_and_five_joints_are_compared(tmp_path, monkeypatch):
    five = [0.8, -62.2, 53.1, 51.6, 45.2]  # the shape of grasp-plan.example.json
    state = [0.5, -61.0, 52.0, 52.0, 44.0, 12.0]  # the sixth value is the jaw and does not count
    out = _exec(tmp_path, monkeypatch, {"result": "placed", "attempts": [_attempt(park={**PARK, "state": state})]}, home=five)
    assert out["stop_event"]["folded"] is True and out["stop_event"]["readback"]["home"] == five
    assert cte.plan_home({"plan_path": str(tmp_path / "missing.json")}) is None
    assert cte.plan_home({}) is None


def test_the_indented_multi_line_cli_output_is_parsed():
    text = CLI_NOISE + json.dumps({"result": "placed", "attempts": [{"verify": {"verified": True}}]}, indent=1) + "\n"
    assert cte.last_json_object(text)["attempts"][0]["verify"] == {"verified": True}
    assert cte.last_json_object("no json here {") == {} and cte.last_json_object('{"a": 1} trailing') == {}


@pytest.mark.parametrize("target", [
    {"site": "belt", "area": "belt", "col": 2, "row": 1, "tier": 2},     # another tier than the handoff's
    {"site": "pallet-l0", "area": "pallet", "col": 2, "row": 1, "tier": 1},  # another site than the handoff's dst
    {"site": "belt", "area": "belt", "col": None, "row": 1, "tier": 1},
    None,
])
def test_a_measurement_of_another_slot_or_tier_does_not_verify_the_task(tmp_path, monkeypatch, target):
    zone = {**ZONE, "target": target}
    out = _exec(tmp_path, monkeypatch, {"result": "placed", "attempts": [_attempt(zone=zone)]})
    assert out["stage_result"]["task_verified"] is False


TOP_ONLY = {"verified": True, "basis": "top_camera_only_target_zone",
            "target": {"site": "belt", "area": "belt", "roi": [309, 100, 634, 223], "tier": 1}}


def test_cell_s_accepts_the_top_camera_only_basis_but_cell_ab_does_not(tmp_path, monkeypatch):
    parsed = {"result": "placed", "attempts": [_attempt(zone=TOP_ONLY)]}
    s = _exec(tmp_path, monkeypatch, parsed)
    assert s["stage_result"]["task_verified"] is True and s["stage_result"]["verification"]["basis"] == "top_camera_only_target_zone"
    ab = _exec(tmp_path, monkeypatch, parsed, handoff={**HANDOFF, "cell_id": "cell_ab"})
    assert ab["stage_result"]["task_verified"] is False


@pytest.mark.parametrize("target", [{"site": "belt", "tier": 1}, {"site": "pallet", "area": "pallet", "roi": [1, 2, 3, 4], "tier": 1},
                                    {"site": "belt", "roi": [1, 2, 3, 4], "tier": 2}])
def test_cell_s_top_only_still_needs_the_task_zone_and_tier(tmp_path, monkeypatch, target):
    out = _exec(tmp_path, monkeypatch, {"result": "placed", "attempts": [_attempt(zone={**TOP_ONLY, "target": target})]})
    assert out["stage_result"]["task_verified"] is False


def test_both_fold_measurements_must_agree(tmp_path, monkeypatch):
    # the attempt's park readback is folded, but main's live runner state says it is not: the arm is not released as folded
    out = _exec(tmp_path, monkeypatch, {"result": "placed", "attempts": [_attempt()]}, live_folded=False)
    assert out["stop_event"]["folded"] is False and out["stop_event"]["readback"]["folded"] is True
    assert out["stop_event"]["live"]["folded"] is False and out["error"] == "FOLD_READBACK_MISSING"
    assert out["stage_result"]["source_clearance"] == {"objects": 0, "site": "pinky"}


def _flags(tmp_path, monkeypatch, handoff):
    cmds = []
    _exec(tmp_path, monkeypatch, {"result": "placed", "attempts": [_attempt()]}, handoff={**HANDOFF, **handoff}, record=cmds)
    return [c for c in cmds[-1] if c in ("--commissioning", "--person-at-switch")]


def test_the_worker_never_declares_a_person_at_the_switch(tmp_path, monkeypatch):
    import time

    assert _flags(tmp_path, monkeypatch, {}) == []                                   # no presence: the reviewed envelope path
    assert _flags(tmp_path, monkeypatch, {"presence": None}) == []
    ok = {"presence": {"operator": "ops-kim", "at": time.time() - 10}}
    assert _flags(tmp_path, monkeypatch, ok) == ["--commissioning", "--person-at-switch"]  # only a confirmed task
    for bad in ({"operator": "ops-kim", "at": time.time() - 4000},                  # expired
                {"operator": "", "at": time.time()}, {"operator": "site-console", "at": time.time()},   # anonymous
                {"operator": "development-x", "at": time.time()}, {"operator": "ops-kim"}, {"at": time.time()}, "ops-kim"):
        assert _flags(tmp_path, monkeypatch, {"presence": bad}) == [], bad


def test_a_run_held_by_the_envelope_is_reported_as_review_required(tmp_path, monkeypatch):
    for reason in ("not_reviewed", "evidence_changed", "acceptance_not_met"):
        out = _exec(tmp_path, monkeypatch, {"result": f"held: {reason}", "attempts": []})
        assert out["review_required"] is True and out["stage_result"]["task_verified"] is False
    out = _exec(tmp_path, monkeypatch, {"result": "held: source moved before transfer", "attempts": []})
    assert "review_required" not in out  # another hold is not a review problem
    assert _exec(tmp_path, monkeypatch, {"result": "placed", "attempts": [_attempt()]})["commissioning"] is False


def test_open_cell_ignores_a_commissioning_mark_stored_in_the_config_file_and_warns(tmp_path, monkeypatch, capsys):
    import cell_auto_setup as setup

    stored = {"cameras": {}, "work_dir": str(tmp_path), "io": str(tmp_path / "io"), "calibration_path": "cal.json",
              "_commissioning": {"person_at_switch": True}}
    monkeypatch.setattr(setup, "load_config", lambda path: dict(stored))
    monkeypatch.setattr(setup.cell_attempts, "start", lambda *a, **k: None)
    monkeypatch.setattr(setup.cp, "FifoCell", lambda *a, **k: None)
    monkeypatch.setattr(setup.cp, "KEEP", {})
    args = SimpleNamespace(config=None, dry_run=True, task_id="t-1")
    config = setup.open_cell(args)[0]  # no --commissioning on this run
    assert "_commissioning" not in config and "ignored" in capsys.readouterr().err
    assert setup.open_cell(args, True)[0]["_commissioning"] == {"person_at_switch": True}  # only this run's own flag sets it


@pytest.mark.parametrize("arm_id", ["arm_a", "arm_b", "arm_s"])
def test_worker_act_binds_request_without_starting_a_physical_session(tmp_path, monkeypatch, arm_id):
    import hashlib

    import cell_policy_start_gate as start_gate

    monkeypatch.setattr(start_gate, "read_state_range", lambda _root: {})  # statistics present; the gate itself has its own tests
    monkeypatch.setattr(cte, "check_arm_hold", lambda *_: {"held": False})
    calls, drive = [], {"out": {"result": "refused", "reason": "POLICY_LEASE_UNACKED", "at": 0, "parked": False}}
    monkeypatch.setattr(cte.subprocess, "run", lambda cmd, **_kw: calls.append(cmd) or subprocess.CompletedProcess(
        cmd, 0 if drive["out"].get("result") == "released" else 1, stdout=json.dumps(drive["out"]), stderr=""))
    wrap, cfg, _, _, _ = cte._arm_run_spec(arm_id, tmp_path)
    assert wrap.is_file()
    ab = arm_id != "arm_s"
    checkpoint = tmp_path / "model"
    checkpoint.mkdir()
    weights = b"test-only checkpoint"
    revision = hashlib.sha256(weights).hexdigest()
    (checkpoint / "model.safetensors").write_bytes(weights)
    (checkpoint / "config.json").write_text(json.dumps({
        "type": "act",
        "input_features": {"observation.state": {"shape": [6]}, "observation.images.top": {"shape": [3, 8, 8]},
                           "observation.environment_state": {"shape": [10]}},
        "output_features": {"action": {"shape": [6]}},
    }))
    units = checkpoint / "UNITS.json"
    units.write_text(json.dumps({"arm": arm_id, "state": "sim_rad", "gripper": "sim_jaw"}))
    (tmp_path / f"arm-cal-{arm_id}.json").write_text(json.dumps(
        {"arm_id": arm_id, "held_30mm": 53, "gap_mm_per_unit": 5}))
    (tmp_path / "chunks-arm-s-inplace-live.json").write_text("{}")
    source, destination = ("belt", "yard:r1-s2-t1") if ab else ("pinky", "belt")
    config = {
        "arm_id": arm_id, "io": f"chunk-io-{arm_id[-1]}", "work_dir": str(tmp_path), "cameras": {"top": "top"},
        "sites": {"pinky": {"auto_roi": [0, 0, 4, 4]}, "ship-h1r0": {"place": [0, 0], "surface_z": 0},
                  "belt": {"auto_roi": [0, 0, 4, 4], "surface_z": 0.1}},
        "act_policy": {"execution_allowed": True, "policy_root": str(checkpoint), "policy_revision": revision,
                       "cell_calibration": "cell.json", "model_calibration": "model.json",
                       "library": "chunks-arm-s-inplace-live.json"},
    }
    cfg.write_text(json.dumps(config))
    task = {**HANDOFF, "cell_id": "cell_ab" if ab else "cell_s", "arm_id": arm_id, "execution_mode": "act_policy",
            "src_site": source, "dst_site": destination, "presence": {"operator": "onsite", "at": time.time()}}
    run = lambda: cte.execute_guarded_cell_task(task, prep_dir=tmp_path)
    result = run()  # the runner never armed the pushed lease: the drive refused before any motion
    assert result["error"] == "PHYSICAL_POLICY_LEASE_OWNER_UNAVAILABLE"
    assert result["stage_result"]["task_verified"] is False
    assert result["stop_event"]["folded"] is False
    assert result["inference_performed"] is False and result["motion_issued"] is False
    assert len(calls) == 1 and "--policy-lease" in calls[0] and "--person-at-switch" in calls[0]
    assert (calls[0][calls[0].index("--goal-site") + 1] == destination) if ab else "--goal-site" not in calls[0]
    if ab:
        saved_belt = config["sites"]["belt"]
        config["sites"]["belt"] = {}
        cfg.write_text(json.dumps(config))
        assert run()["error"] == "SITE_NOT_CALIBRATED"
        config["sites"]["belt"] = saved_belt
        cfg.write_text(json.dumps(config))
        assert result["stage_result"]["policy_request"] == {
            "weights_sha256": revision, "goal_site": destination, "goal_slot": 0, "destination": "ship-h1r0-l0"}
        def no_statistics(_root):
            raise ValueError("POLICY_STATE_STATS_MISSING: checkpoint")

        monkeypatch.setattr(start_gate, "read_state_range", no_statistics)
        assert run()["error"] == "POLICY_STATE_STATS_MISSING"  # the exact Fleet refusal code
        monkeypatch.setattr(start_gate, "read_state_range", lambda _root: {})
        units.write_text(json.dumps({"arm": "arm_b" if arm_id == "arm_a" else "arm_a", "state": "sim_rad", "gripper": "sim_jaw"}))
        assert run()["error"] == "ACT_POLICY_MODEL_BINDING_MISMATCH"
        task["dst_site"] = "pallet-l0"
        assert run()["error"] == "ACT_POLICY_INVALID_TARGET"
        config["io"] = "chunk-io-s"
        cfg.write_text(json.dumps(config))
        assert run()["error"] == "ACT_POLICY_ARM_BINDING_MISMATCH"
    task["presence"] = {}
    assert run()["error"] == "PRESENCE_REQUIRED_FOR_ACT_POLICY"


def test_worker_act_dry_run_reports_no_physical_evidence(tmp_path, monkeypatch):
    token = tmp_path / "token"
    token.write_text("test")
    observed = {}

    def poll(_pipeline, *, live_act_fn, **_kwargs):
        observed.update(live_act_fn({**HANDOFF, "execution_mode": "act_policy"}))
        return []

    monkeypatch.setattr(ctw, "poll_and_execute_once", poll)
    monkeypatch.setattr(ctw, "execute_live_hardware_arm", lambda *_a, **_k: pytest.fail("legacy dispatch"))
    monkeypatch.setattr(ctw, "execute_guarded_cell_task", lambda *_a, **_k: pytest.fail("physical dispatch"))
    ctw.main(["--once", "--token-file", str(token), "--work-dir", str(tmp_path / "work"), "--prep-dir", str(tmp_path),
              "--allow-legacy-live-jog", "--execute-mode", "sealed", "--dry-run-hw"])
    assert observed["error"] == "ACT_POLICY_DRY_RUN" and observed["events_count"] == 0
    assert observed["stage_result"]["task_verified"] is False and observed["stop_event"]["folded"] is False


def test_cell_s_remeasure_uses_separate_source_and_destination_regions(tmp_path, monkeypatch):
    import cv2
    import numpy as np
    import cell_remeasure as crm
    import cell_zone_verification as czv
    config = {"work_dir": str(tmp_path), "io": "unused", "cameras": {}}
    cfg = tmp_path / "cell.json"
    cfg.write_text(json.dumps(config))
    zone = {"target": {"roi": [309, 100, 634, 223]}, "before_frames": {"top": "t-1-top.jpg"}}
    crm.write_context(cfg, config, HANDOFF, "arm_s", tmp_path, "belt", "pinky", [49, 139, 295, 305], zone,
                      cat_path=tmp_path / "objects.json")
    stage = {"source_clearance": {}, "verification": {"placement": {"verified": True, "inside": True}}}
    hardware = {"stop_event": {"readback": {"folded": True}}}
    monkeypatch.setattr(cte, "measured_fold", lambda *_a: {"folded": True})
    (tmp_path / "zone-before").mkdir(exist_ok=True)
    cv2.imwrite(str(tmp_path / "zone-before" / "t-1-top.jpg"), np.zeros((8, 8, 3), np.uint8))
    seen_rm = {}
    monkeypatch.setattr(czv, "measure", lambda cell, before, cfg, dst, src, roi: (
        seen_rm.update(zone_roi=roi) or {"verified": True, "basis": cte.TOP_ONLY_BASIS,
                                         "target": {"site": dst, "area": "belt", "tier": 1, "roi": roi}}))
    monkeypatch.setattr(cte, "source_clearance", lambda cfg, cat, roi, src: seen_rm.update(sc_roi=roi) or {"objects": 0, "site": src})
    monkeypatch.setattr("cell_pipeline.FifoCell", lambda *a, **k: object())
    crm.remeasure("t-1", {"complete": {"stage_result": stage, "hardware_telemetry": hardware,
                                       "receipt": {"handoff_lease_id": "lease-1"}}}, tmp_path, now=time.time())
    assert seen_rm["zone_roi"] == [309, 100, 634, 223] and seen_rm["sc_roi"] == [49, 139, 295, 305]

def test_policy_drive_resolves_valid_io_relative_to_config_and_rejects_missing_io(tmp_path, monkeypatch):
    cfg_dir, other_cwd = tmp_path / "cfg_root", tmp_path / "worker_cwd"
    io_name = "custom-arm-io "
    real_io, decoy_io = cfg_dir / io_name, other_cwd / io_name
    for d in (real_io, decoy_io):
        d.mkdir(parents=True)
    (real_io / "chunk-cmd").write_bytes(b"")
    (decoy_io / "chunk-cmd").write_bytes(b"")
    (cfg4 := cfg_dir / "cell.json").write_text(json.dumps({
        "arm_id": "arm_s", "io": io_name, "cameras": {},
        "sites": {"pinky": {"auto_roi": [0, 0, 10, 10]}, "belt": {}},
        "act_policy": {"execution_allowed": True, "policy_root": str(tmp_path), "policy_revision": "a" * 64,
                       "cell_calibration": str(tmp_path / "cell-cal.json"), "model_calibration": str(tmp_path / "m-cal.json")},
    }), encoding="utf-8")
    (tmp_path / "cell-cal.json").write_text("{}", encoding="utf-8")
    (tmp_path / "m-cal.json").write_text("{}", encoding="utf-8")
    (tmp_path / "lib4.json").write_text(json.dumps({"fps": 30, "gripper_closed": 46.6, "chunks": {"home": [[0] * 6], "reach": [[0] * 6, [1, 0, 0, 0, 0, 0]]}}), encoding="utf-8")

    monkeypatch.chdir(other_cwd)
    import cell_pipeline as cp
    import cell_policy_drive as cpd
    seen_io = []

    class CapCell:
        def __init__(self, io_dir, *_a, **_kw):
            seen_io.append(Path(io_dir))

        def act(self, cmd):
            return {"command": cmd, "ok": True, "settled": True, "holding": False, "state": [0] * 6}

    with monkeypatch.context() as mp:
        mp.setattr(cp, "FifoCell", CapCell)
        mp.setattr(cpd, "calibration_offset", lambda *_a: [0.0] * 6)
        mp.setattr(cpd, "demonstrated_range", lambda *_a: ([-100.0] * 6, [100.0] * 6))
        import cell_policy_start_gate as start_gate
        mp.setattr(start_gate, "read_state_range", lambda _root: {"min": [-1e3] * 6, "max": [1e3] * 6})
        mp.setattr(cpd.lrs, "LeRobotShadow", lambda *_a, **_kw: SimpleNamespace(
            sim_rule=None, goal_size=None, image_views=(), files={},
            inputs=lambda st, _f, **_k: ({"s": st}, {}), infer=lambda _o: SimpleNamespace(chunk=[[0.0] * 6] * 16),
        ))
        rc = cpd.main(["--config", str(cfg4), "--library", str(tmp_path / "lib4.json"), "--policy-root", str(tmp_path),
                       "--policy-revision", "a" * 64, "--cell-calibration", str(tmp_path / "cell-cal.json"),
                       "--model-calibration", str(tmp_path / "m-cal.json"), "--operator", "livsbittt", "--max-chunks", "1", "--dry-run"])
    assert rc == 0 and seen_io == [real_io]

    for bad_cfg_body in (
        {"arm_id": "arm_s", "io": "", "cameras": {}},
        {"arm_id": "arm_s", "io": None, "cameras": {}},
        {"arm_id": "arm_s", "cameras": {}},
    ):
        (bad_cfg := cfg_dir / "bad-empty-io.json").write_text(json.dumps(bad_cfg_body), encoding="utf-8")
        with monkeypatch.context() as mp:
            mp.setattr(cp, "FifoCell", lambda *_a, **_kw: pytest.fail("invalid io must not construct FifoCell"))
            mp.setattr(cpd.lrs, "LeRobotShadow", lambda *_a, **_kw: pytest.fail("invalid io must not initialize LeRobotShadow"))
            with pytest.raises(SystemExit) as exc_info:
                cpd.main(["--config", str(bad_cfg), "--library", str(tmp_path / "lib4.json"), "--policy-root", str(tmp_path),
                          "--policy-revision", "a" * 64, "--cell-calibration", str(tmp_path / "cell-cal.json"),
                          "--model-calibration", str(tmp_path / "m-cal.json"), "--operator", "livsbittt", "--max-chunks", "1", "--dry-run"])
            assert exc_info.value.code == 2

def test_guarded_exec_honors_calibrated_displaced_to_or_fails_closed(tmp_path, monkeypatch):
    (tmp_path / "with-session-arm-s-live.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (tmp_path / "grasp-plan.json").write_text(json.dumps({"home": HOME}), encoding="utf-8")
    monkeypatch.setattr(cte, "check_arm_hold", lambda arm: {"held": False})
    monkeypatch.setattr(cte, "measured_fold", lambda arm, prep, now=None: {"folded": True, "state": None, "fresh": True})
    monkeypatch.setattr(cte, "source_clearance", lambda *a, **k: {"objects": 0, "site": "belt_far"})
    cmds = []
    monkeypatch.setattr(cte.subprocess, "run", lambda *a, **k: (cmds.append(a[0]) or subprocess.CompletedProcess(
        a, 0, stdout=json.dumps({"result": "placed", "attempts": [_attempt()]}) + "\n", stderr="")))

    # Without displaced site in cfg.sites, fail closed before running subprocess.
    (tmp_path / "cell-auto-arm-s-live.json").write_text(json.dumps({
        "plan_path": str(tmp_path / "grasp-plan.json"),
        "sites": {"pinky": {"auto_roi": [1, 2, 3, 4]}, "belt": {"auto_roi": [5, 6, 7, 8]}},
    }), encoding="utf-8")
    uncal = cte.execute_guarded_cell_task({**HANDOFF, "displaced_to": "belt_far"}, prep_dir=tmp_path)
    assert uncal["error"] == "UNCALIBRATED_DISPLACED_SITE" and cmds == []
    bad_site = cte.execute_guarded_cell_task({**HANDOFF, "displaced_to": "unknown_zone"}, prep_dir=tmp_path)
    assert bad_site["error"] == "UNCALIBRATED_DISPLACED_SITE" and cmds == []

    # With calibrated belt_far in cfg.sites, run --from belt_far with belt_far auto_roi.
    (tmp_path / "cell-auto-arm-s-live.json").write_text(json.dumps({
        "plan_path": str(tmp_path / "grasp-plan.json"),
        "sites": {"pinky": {"auto_roi": [1, 2, 3, 4]}, "belt": {"auto_roi": [5, 6, 7, 8]},
                  "belt_far": {"auto_roi": [10, 20, 30, 40]}},
    }), encoding="utf-8")
    ok = cte.execute_guarded_cell_task({**HANDOFF, "displaced_to": "belt_far"}, prep_dir=tmp_path)
    assert "error" not in ok and len(cmds) == 1
    cmd = cmds[0]
    assert cmd[cmd.index("--from") + 1] == "belt_far"
    assert cmd[cmd.index("--roi") + 1 : cmd.index("--roi") + 5] == ["10", "20", "30", "40"]

    # ACT mode rejects non-empty displaced_to before subprocess launch.
    cmds.clear()
    act_bad = cte.execute_guarded_cell_task({**HANDOFF, "execution_mode": "act_policy", "displaced_to": "bogus"},
                                            prep_dir=tmp_path)
    assert act_bad["error"] == "UNCALIBRATED_DISPLACED_SITE" and cmds == []


def _act_task(tmp_path, monkeypatch, drive_out, *, took_one_zone=True):
    """An S act_policy task whose drive (the subprocess) printed `drive_out`; fold and zone are the measured values."""
    import hashlib

    import cell_task_act_run as run_mod

    checkpoint = tmp_path / "model"
    checkpoint.mkdir()
    (checkpoint / "model.safetensors").write_bytes(b"w")
    revision = hashlib.sha256(b"w").hexdigest()
    wrap, cfg, _, _, _ = cte._arm_run_spec("arm_s", tmp_path)
    (tmp_path / "chunks-arm-s-inplace-live.json").write_text("{}")
    cfg.write_text(json.dumps({
        "arm_id": "arm_s", "io": "chunk-io-s", "sites": {"pinky": {"auto_roi": [0, 0, 4, 4]}, "belt": {}},
        "act_policy": {"execution_allowed": True, "policy_root": str(checkpoint), "policy_revision": revision,
                       "cell_calibration": "c.json", "model_calibration": "m.json"}}))
    monkeypatch.setattr(cte, "check_arm_hold", lambda *_: {"held": False})
    monkeypatch.setattr(cte, "measured_fold", lambda *a, **k: {"folded": True, "state": None})
    monkeypatch.setattr(cte, "fold_readback", lambda *a, **k: {"folded": True, "state": [0] * 6})
    monkeypatch.setattr(cte, "source_clearance", lambda *a, **k: {"objects": 0})
    wrote = []
    monkeypatch.setattr(cte, "write_context", lambda *a, **k: wrote.append(a))
    monkeypatch.setattr(run_mod, "zone_acceptance", lambda *a: took_one_zone)
    monkeypatch.setattr(cte.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 0, stdout=json.dumps(drive_out), stderr=""))
    task = {**HANDOFF, "execution_mode": "act_policy", "presence": {"operator": "onsite", "at": time.time()}}
    return cte.execute_guarded_cell_task(task, prep_dir=tmp_path), wrote


_DRIVE_OK = {"result": "released", "parked": True, "park": {**PARK}, "source": {"before": 1, "after": 0}, "took_one": True,
             "zone_verification": ZONE}


def test_act_with_an_armed_lease_runs_and_is_verified_only_on_took_one_and_zone(tmp_path, monkeypatch):
    out, wrote = _act_task(tmp_path, monkeypatch, _DRIVE_OK)
    assert out["stage_result"]["task_verified"] is True and out["stop_event"]["folded"] is True and wrote
    assert "error" not in out


@pytest.mark.parametrize("change,zone_ok", [({"took_one": False}, True), ({"took_one": None}, True), ({}, False)])
def test_act_not_verified_without_both_took_one_and_the_zone(tmp_path, monkeypatch, change, zone_ok):
    out, wrote = _act_task(tmp_path, monkeypatch, {**_DRIVE_OK, **change}, took_one_zone=zone_ok)
    assert out["stage_result"]["task_verified"] is False and not wrote and out["error"] == "released"


def test_act_unarmed_runner_is_refused_and_a_timeout_names_the_watchdog(tmp_path, monkeypatch):
    out, _ = _act_task(tmp_path, monkeypatch, {"result": "refused", "reason": "POLICY_LEASE_UNACKED", "parked": False})
    assert out["error"] == "PHYSICAL_POLICY_LEASE_OWNER_UNAVAILABLE" and out["motion_issued"] is False

    def timeout(cmd, **_kw):
        raise subprocess.TimeoutExpired(cmd, 300)

    monkeypatch.setattr(cte.subprocess, "run", timeout)
    task = {**HANDOFF, "execution_mode": "act_policy", "presence": {"operator": "onsite", "at": time.time()}}
    out = cte.execute_guarded_cell_task(task, prep_dir=tmp_path)
    assert out["error"] == "SUBPROCESS_TIMEOUT" and out["stop_event"]["lease_watchdog"] is True
