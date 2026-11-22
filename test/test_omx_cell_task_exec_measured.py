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


def _act_setup(tmp_path, monkeypatch, *, act_cfg=None, cfg_override=None, live_folded=True, subprocess_res=None, returncode=0, handoff=None):
    (tmp_path / "with-session-arm-s-live.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (tmp_path / "chunks-arm-s-inplace-live.json").write_text("{}", encoding="utf-8")
    (tmp_path / "grasp-plan.json").write_text(json.dumps({"home": HOME}), encoding="utf-8")
    cfg_body = cfg_override if cfg_override is not None else {
        "io": str(tmp_path / "chunk-io-s"),
        "cameras": {},
        "work_dir": str(tmp_path),
        "plan_path": str(tmp_path / "grasp-plan.json"),
        "sites": {"pinky": {"auto_roi": [49, 139, 295, 305]}, "belt": {"auto_roi": [309, 100, 634, 223]}},
        "act_policy": act_cfg if act_cfg is not None else {
            "execution_allowed": True,
            "policy_root": "/home/robttt/omx_models/pinky_v1_aug2_act_200k",
            "policy_revision": "b" * 64,
            "cell_calibration": str(tmp_path / "arm_s.json"),
            "model_calibration": str(tmp_path / "pinky.json"),
        },
    }
    (tmp_path / "cell-auto-arm-s-live.json").write_text(
        cfg_body if isinstance(cfg_body, str) else json.dumps(cfg_body), encoding="utf-8"
    )
    monkeypatch.setattr(cte, "check_arm_hold", lambda arm: {"held": False})
    monkeypatch.setattr(cte, "measured_fold", lambda arm, prep, now=None: {"folded": live_folded, "state": [0.0] * 6, "fresh": True})
    monkeypatch.setattr(cte, "source_clearance", lambda *a, **k: {"objects": 0, "site": "pinky"})
    cmds = []
    zone_ok = {"basis": cte.TOP_ONLY_BASIS, "verified": True, "before_frames": {"top": "t-1-top.jpg"},
               "target": {"site": "belt", "area": "belt", "tier": 1, "roi": [309, 100, 634, 223]}}
    payload = subprocess_res if subprocess_res is not None else {
        "result": "chunks_done", "held": True, "parked": True, "park": PARK,
        "source": {"before": 1, "after": 0}, "took_one": True, "zone_verification": zone_ok,
    }
    monkeypatch.setattr(cte.subprocess, "run", lambda *a, **k: (cmds.append(a[0]) or subprocess.CompletedProcess(
        a, returncode, stdout="session up\n" + json.dumps(payload) + "\n", stderr="")))
    base_handoff = {
        **HANDOFF,
        "execution_mode": "act_policy",
        "max_chunks": 4,
        "presence": {"operator": "livsbittt", "at": time.time() - 5},
    }
    if handoff:
        base_handoff.update(handoff)
    return cte.execute_guarded_cell_task(base_handoff, prep_dir=tmp_path), cmds


def test_act_policy_exec_guards_and_verified_completion(tmp_path, monkeypatch):
    monkeypatch.setattr(cte, "check_arm_hold", lambda arm: {"held": False})
    bad_arm = cte.execute_guarded_cell_task({
        "task_id": "t-a", "cell_id": "cell_ab", "arm_id": "arm_a", "execution_mode": "act_policy",
        "presence": {"operator": "livsbittt", "at": time.time()},
    }, prep_dir=tmp_path)
    assert bad_arm["error"] == "ACT_POLICY_UNSUPPORTED_ARM"

    no_pres = cte.execute_guarded_cell_task({
        **HANDOFF, "execution_mode": "act_policy",
    }, prep_dir=tmp_path)
    assert no_pres["error"] == "PRESENCE_REQUIRED_FOR_ACT_POLICY"

    ok, cmds = _act_setup(tmp_path, monkeypatch)
    assert "error" not in ok
    assert ok["stage_result"]["task_verified"] is True
    assert ok["stage_result"]["verification"]["basis"] == cte.TOP_ONLY_BASIS
    assert ok["stage_result"]["verification"]["target"] == {"site": "belt", "area": "belt", "tier": 1, "roi": [309, 100, 634, 223]}
    assert ok["stage_result"]["verification"]["source"]["roi"] == [49, 139, 295, 305]
    assert ok["stage_result"]["source_clearance"] == {"objects": 0, "site": "pinky"}
    assert ok["stop_event"]["ok"] is True and ok["stop_event"]["folded"] is True
    assert ok["stop_event"]["readback"]["folded"] is True
    assert (tmp_path / "remeasure-t-1.json").is_file()
    rm_ctx = json.loads((tmp_path / "remeasure-t-1.json").read_text(encoding="utf-8"))
    assert rm_ctx["dst_roi"] == [309, 100, 634, 223] and rm_ctx["src_roi"] == [49, 139, 295, 305]
    assert "--paced-chunks" in cmds[0] and "--person-at-switch" in cmds[0]
    assert "--dest-site" in cmds[0] and "--task-id" in cmds[0]
    assert "cell_policy_drive.py" in cmds[0][2]

    # 65s remeasure on cell_s must pass dst_roi (belt) to czv.measure and src_roi (pinky) to source_clearance.
    import cv2
    import numpy as np
    import cell_remeasure as crm
    import cell_zone_verification as czv
    (tmp_path / "zone-before").mkdir(exist_ok=True)
    cv2.imwrite(str(tmp_path / "zone-before" / "t-1-top.jpg"), np.zeros((8, 8, 3), np.uint8))
    seen_rm = {}
    monkeypatch.setattr(czv, "measure", lambda cell, before, cfg, dst, src, roi: (
        seen_rm.update(zone_roi=roi) or {"verified": True, "basis": cte.TOP_ONLY_BASIS,
                                         "target": {"site": dst, "area": "belt", "tier": 1, "roi": roi}}))
    monkeypatch.setattr(cte, "source_clearance", lambda cfg, cat, roi, src: seen_rm.update(sc_roi=roi) or {"objects": 0, "site": src})
    monkeypatch.setattr("cell_pipeline.FifoCell", lambda *a, **k: object())
    crm.remeasure("t-1", {"complete": {"stage_result": ok["stage_result"], "hardware_telemetry": ok,
                                       "receipt": {"handoff_lease_id": "lease-1"}}}, tmp_path, now=time.time())
    assert seen_rm["zone_roi"] == [309, 100, 634, 223] and seen_rm["sc_roi"] == [49, 139, 295, 305]

    # Invalid task_ids and non-dict site configs fail closed before subprocess.
    for bad_tid in ("../bad", "-flag", ""):
        res_tid, c_tid = _act_setup(tmp_path, monkeypatch, handoff={"task_id": bad_tid})
        assert res_tid["error"] == "ACT_POLICY_INVALID_ARGS" and c_tid == []
    bad_site, c_site = _act_setup(tmp_path, monkeypatch, cfg_override={
        "io": str(tmp_path / "chunk-io-s"),
        "work_dir": str(tmp_path), "plan_path": str(tmp_path / "grasp-plan.json"),
        "sites": {"pinky": "not-a-dict", "belt": {"auto_roi": [309, 100, 634, 223]}},
        "act_policy": {"execution_allowed": True, "policy_root": "/m", "policy_revision": "b" * 64,
                       "cell_calibration": "a", "model_calibration": "p"},
    })
    assert bad_site["error"] == "ACT_POLICY_INVALID_ARGS" and c_site == []

    # Timeout writes human-hold to live arm_s FIFO naming convention (chunk-io-s, not chunk-io-arm-s).
    tmo_dir = tmp_path / "tmo"
    (tmo_dir / "chunk-io-s").mkdir(parents=True)
    fifo_file = tmo_dir / "chunk-io-s" / "chunk-cmd"
    fifo_file.write_bytes(b"")
    (tmo_dir / "with-session-arm-s-live.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (tmo_dir / "chunks-arm-s-inplace-live.json").write_text("{}", encoding="utf-8")
    (tmo_dir / "cell-auto-arm-s-live.json").write_text(json.dumps({
        "io": str(tmo_dir / "chunk-io-s"),
        "sites": {"pinky": {"auto_roi": [49, 139, 295, 305]}, "belt": {"auto_roi": [309, 100, 634, 223]}},
        "act_policy": {"execution_allowed": True, "policy_root": "/m", "policy_revision": "b" * 64,
                       "cell_calibration": "a", "model_calibration": "p"},
    }), encoding="utf-8")
    monkeypatch.setattr(cte.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired(a[0], 300)))
    tmo = cte.execute_guarded_cell_task({**HANDOFF, "execution_mode": "act_policy",
                                         "presence": {"operator": "livsbittt", "at": time.time() - 5}}, prep_dir=tmo_dir)
    assert tmo["error"] == "SUBPROCESS_TIMEOUT" and tmo["stop_event"]["timeout_hold"]["chunk-io-s"] == "human-hold sent"
    assert tmo["stop_event"]["timeout_hold_latched"] == {"chunk-io-s": False}
    written = fifo_file.read_text(encoding="utf-8")
    assert written.startswith("human-hold ") and len(written.split()) == 2

    # Passive act_shadow config alone or execution_allowed=False must fail closed (D-442 / D-1024).
    shadow_only, c1 = _act_setup(tmp_path, monkeypatch, cfg_override={
        "io": str(tmp_path / "chunk-io-s"),
        "sites": {"pinky": {"auto_roi": [49, 139, 295, 305]}, "belt": {"auto_roi": [309, 100, 634, 223]}},
        "act_shadow": {"policy_root": "/m", "policy_revision": "b" * 64, "cell_calibration": "a", "model_calibration": "p"},
    })
    assert shadow_only["error"] == "ACT_POLICY_CONFIG_MISSING" and c1 == []
    disallowed, c2 = _act_setup(tmp_path, monkeypatch, act_cfg={
        "execution_allowed": False, "policy_root": "/m", "policy_revision": "b" * 64,
        "cell_calibration": "a", "model_calibration": "p",
    })
    assert disallowed["error"] == "ACT_POLICY_CONFIG_MISSING" and c2 == []

    # Corrupt JSON, path traversal library, and leading-dash arguments fail closed before subprocess.
    corrupt, c3 = _act_setup(tmp_path, monkeypatch, cfg_override="{not-json")
    assert corrupt["error"] == "ACT_POLICY_CONFIG_INVALID" and c3 == []
    trav, c4 = _act_setup(tmp_path, monkeypatch, act_cfg={
        "execution_allowed": True, "policy_root": "/m", "policy_revision": "b" * 64,
        "cell_calibration": "a", "model_calibration": "p", "library": "../outside.json",
    })
    assert trav["error"] == "ACT_POLICY_LIBRARY_MISSING" and c4 == []
    bad_op, c5 = _act_setup(tmp_path, monkeypatch, handoff={"presence": {"operator": "-evil", "at": time.time() - 5}})
    assert bad_op["error"] == "ACT_POLICY_INVALID_ARGS" and c5 == []

    # Missing zone verification and out-of-tolerance park readback keep verified=False.
    no_zone, _ = _act_setup(tmp_path, monkeypatch, subprocess_res={
        "result": "chunks_done", "held": True, "parked": True, "park": PARK,
        "source": {"before": 1, "after": 0}, "took_one": True,
    })
    assert no_zone["stage_result"]["task_verified"] is False
    bad_fold, _ = _act_setup(tmp_path, monkeypatch, subprocess_res={
        "result": "chunks_done", "held": True, "parked": True,
        "park": {**PARK, "state": [20.0, -20.0, 10.0, 20.0, 20.0, 49.0]},
        "source": {"before": 1, "after": 0}, "took_one": True,
        "zone_verification": {"basis": cte.TOP_ONLY_BASIS, "verified": True,
                              "target": {"site": "belt", "area": "belt", "tier": 1, "roi": [309, 100, 634, 223]}},
    })
    assert bad_fold["stop_event"]["folded"] is False and bad_fold["stage_result"]["task_verified"] is False

    not_taken, _ = _act_setup(tmp_path, monkeypatch, subprocess_res={
        "result": "chunks_done", "held": False, "parked": True, "park": PARK,
        "source": {"before": 1, "after": 1}, "took_one": False,
        "zone_verification": {"basis": cte.TOP_ONLY_BASIS, "verified": True,
                              "target": {"site": "belt", "area": "belt", "tier": 1, "roi": [309, 100, 634, 223]}},
    })
    assert not_taken["stage_result"]["task_verified"] is False
    assert not_taken["stop_event"]["folded"] is True
    assert "error" in not_taken

    for bad_sc in ({"objects": 1, "site": "pinky"}, {"objects": None, "site": "pinky"}):
        monkeypatch.setattr(cte, "check_arm_hold", lambda arm: {"held": False})
        monkeypatch.setattr(cte, "measured_fold", lambda arm, prep, now=None: {"folded": True, "state": [0.0] * 6, "fresh": True})
        monkeypatch.setattr(cte, "source_clearance", lambda *a, **k: bad_sc)
        zone_ok_sc = {"basis": cte.TOP_ONLY_BASIS, "verified": True,
                      "target": {"site": "belt", "area": "belt", "tier": 1, "roi": [309, 100, 634, 223]}}
        monkeypatch.setattr(cte.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
            a, 0, stdout=json.dumps({"result": "chunks_done", "held": True, "parked": True, "park": PARK,
                                     "source": {"before": 1, "after": 0}, "took_one": True,
                                     "zone_verification": zone_ok_sc}) + "\n", stderr=""))
        bad = cte.execute_guarded_cell_task({
            **HANDOFF, "execution_mode": "act_policy", "max_chunks": 4,
            "presence": {"operator": "livsbittt", "at": time.time() - 5},
        }, prep_dir=tmp_path)
        assert bad["stage_result"]["task_verified"] is False and "error" in bad

    contact, _ = _act_setup(tmp_path, monkeypatch, returncode=1, subprocess_res={
        "result": "contact", "at": 1, "error": "strain", "source": {"before": 1, "after": 1}, "took_one": False,
    })
    assert contact["stage_result"]["task_verified"] is False and contact["error"] == "contact"

    # Fresh runner live.json confirms human_hold_latched cleanly on subprocess timeout.
    import cell_task_act as cta

    live_dir = tmp_path / "tmo_latched"
    (live_dir / "chunk-io-s").mkdir(parents=True)
    (live_dir / "chunk-io-s" / "chunk-cmd").write_bytes(b"")
    (live_dir / "with-session-arm-s-live.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (live_dir / "chunks-arm-s-inplace-live.json").write_text("{}", encoding="utf-8")
    (live_dir / "cell-auto-arm-s-live.json").write_text(json.dumps({
        "io": str(live_dir / "chunk-io-s"),
        "sites": {"pinky": {"auto_roi": [49, 139, 295, 305]}, "belt": {"auto_roi": [309, 100, 634, 223]}},
        "act_policy": {"execution_allowed": True, "policy_root": "/m", "policy_revision": "b" * 64,
                       "cell_calibration": "a", "model_calibration": "p"},
    }), encoding="utf-8")
    monkeypatch.setattr(cte.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired(a[0], 300)))
    real_open, real_close, live_fd = cta.os.open, cta.os.close, [None]

    def _open_latched(path, flags):
        fd = real_open(tmp_path / "tmo2-sink", cta.os.O_WRONLY | cta.os.O_CREAT | cta.os.O_TRUNC, 0o600)
        live_fd[0] = fd
        return fd

    def _close_latched(fd):
        real_close(fd)
        if fd == live_fd[0]:
            req = (tmp_path / "tmo2-sink").read_text(encoding="utf-8").strip().split()[1]
            (live_dir / "chunk-io-s" / "live.json").write_text(
                json.dumps({"t": time.time() + 0.01, "human_hold_latched": True, "torque_hold_commanded": True, "hold_req": req}), encoding="utf-8"
            )

    with monkeypatch.context() as mp:
        mp.setattr(cta.os, "open", _open_latched)
        mp.setattr(cta.os, "close", _close_latched)
        tmo2 = cte.execute_guarded_cell_task({**HANDOFF, "execution_mode": "act_policy",
                                              "presence": {"operator": "livsbittt", "at": time.time() - 5}}, prep_dir=live_dir)
    assert tmo2["stop_event"]["timeout_hold"] == {"chunk-io-s": "human-hold sent"}
    assert tmo2["stop_event"]["timeout_hold_latched"] == {"chunk-io-s": True}

    # Unconfirmed torque_hold_commanded, non-finite timestamp, or stale live.json keep timeout_hold_latched False.
    monkeypatch.setattr(cta.time, "sleep", lambda *_: None)
    mono = [0.0]
    monkeypatch.setattr(cta.time, "monotonic", lambda: (mono.__setitem__(0, mono[0] + 0.4) or mono[0]))
    for bad_live in (
        {"t": time.time(), "human_hold_latched": True, "torque_hold_commanded": False},
        {"t": float("inf"), "human_hold_latched": True, "torque_hold_commanded": True},
        {"t": time.time() - 2.0, "human_hold_latched": True, "torque_hold_commanded": True},
        {"t": time.time() + 0.0004, "human_hold_latched": True, "torque_hold_commanded": True},
        {"t": time.time() + 0.05, "human_hold_latched": True, "torque_hold_commanded": True},
        {"t": 10**400, "human_hold_latched": True, "torque_hold_commanded": True},
    ):
        mono[0] = 0.0
        (live_dir / "chunk-io-s" / "live.json").write_text(json.dumps(bad_live), encoding="utf-8")
        acks, latched = cta._hold_on_timeout(live_dir)
        assert acks == {"chunk-io-s": "human-hold sent"} and latched == {"chunk-io-s": False}

    case_a_fd = [None]
    with monkeypatch.context() as mp:
        mp.setattr(cta.os, "open", lambda _p, _f: (case_a_fd.__setitem__(0, real_open(tmp_path / "casea-sink", cta.os.O_WRONLY | cta.os.O_CREAT | cta.os.O_TRUNC, 0o600)) or case_a_fd[0]))
        mp.setattr(cta.os, "close", lambda fd: (real_close(fd), fd == case_a_fd[0] and (live_dir / "chunk-io-s" / "live.json").write_text(json.dumps({"t": time.time() + 0.05, "human_hold_latched": True, "torque_hold_commanded": True, "hold_req": "earlier-req"}), encoding="utf-8")))
        mono[0] = 0.0
        acks_a, lat_a = cta._hold_on_timeout(live_dir)
    assert acks_a == {"chunk-io-s": "human-hold sent"} and lat_a == {"chunk-io-s": False}


def test_timeout_hold_dispatches_configured_first_and_preserves_colliding_or_missing_endpoints(tmp_path, monkeypatch):
    import cell_task_act as cta

    # 1: Configured owner dispatched first and all existing FIFOs written at t=0 before shared-deadline polling.
    prep1 = tmp_path / "p1"
    cfg1, s1, r2s1 = tmp_path / "cfg_io", prep1 / "chunk-io-s", prep1 / "chunk-io-s-r2s"
    for d in (cfg1, s1, r2s1):
        d.mkdir(parents=True)
        (d / "chunk-cmd").write_bytes(b"")
    clk, events, real_open, real_close = [0.0], [], cta.os.open, cta.os.close
    monkeypatch.setattr(cta.time, "monotonic", lambda: clk[0])
    monkeypatch.setattr(cta.time, "sleep", lambda dt: clk.__setitem__(0, clk[0] + dt))
    with monkeypatch.context() as mp:
        mp.setattr(cta.os, "open", lambda path, flags: (events.append((Path(path).parent.name, clk[0])), real_open(path, flags))[1])
        acks1, lat1 = cta._hold_on_timeout(prep1, {"io": str(cfg1)}, confirm_wait_s=0.35, poll_s=0.05)
    assert events == [("cfg_io", 0.0), ("chunk-io-s", 0.0), ("chunk-io-s-r2s", 0.0)]
    assert clk[0] <= 0.35 + 1e-6 and all(lat1[k] is False for k in ("cfg_io", "chunk-io-s", "chunk-io-s-r2s"))

    # 2: Same-name colliding directories (configured OSError, fallback latched) preserve distinct receipts.
    prep2 = tmp_path / "p2"
    cfg2, fb2 = tmp_path / "custom" / "chunk-io-s", prep2 / "chunk-io-s"
    for d in (cfg2, fb2):
        d.mkdir(parents=True)
        (d / "chunk-cmd").write_bytes(b"")
    fb_fd = [None]

    def _open_col(path, flags):
        if Path(path).parent == cfg2:
            raise OSError("no reader")
        fd = real_open(tmp_path / "col-sink", cta.os.O_WRONLY | cta.os.O_CREAT | cta.os.O_TRUNC, 0o600)
        fb_fd[0] = fd
        return fd

    def _close_col(fd):
        real_close(fd)
        if fd == fb_fd[0]:
            req = (tmp_path / "col-sink").read_text(encoding="utf-8").strip().split()[1]
            (fb2 / "live.json").write_text(json.dumps({"t": time.time() + 0.01, "human_hold_latched": True, "torque_hold_commanded": True, "hold_req": req}), encoding="utf-8")

    with monkeypatch.context() as mp:
        mp.setattr(cta.os, "open", _open_col)
        mp.setattr(cta.os, "close", _close_col)
        acks2, lat2 = cta._hold_on_timeout(prep2, {"io": str(cfg2)}, confirm_wait_s=0.05, poll_s=0.01)
    assert len(acks2) == 2 and lat2[str(cfg2)] is False and "error:" in acks2[str(cfg2)] and lat2[str(fb2)] is True
    assert "chunk-io-s" not in acks2 and "chunk-io-s" not in lat2

    # 3: Missing configured FIFO with same-name fallback emits explicit missing receipt and never uses short key.
    prep3 = tmp_path / "p3"
    cfg3_missing, fb3 = tmp_path / "missing" / "chunk-io-s", prep3 / "chunk-io-s"
    fb3.mkdir(parents=True)
    (fb3 / "chunk-cmd").write_bytes(b"")
    fb3_fd = [None]

    def _open_miss(path, flags):
        fd = real_open(tmp_path / "miss-sink", cta.os.O_WRONLY | cta.os.O_CREAT | cta.os.O_TRUNC, 0o600)
        fb3_fd[0] = fd
        return fd

    def _close_miss(fd):
        real_close(fd)
        if fd == fb3_fd[0]:
            req = (tmp_path / "miss-sink").read_text(encoding="utf-8").strip().split()[1]
            (fb3 / "live.json").write_text(json.dumps({"t": time.time() + 0.01, "human_hold_latched": True, "torque_hold_commanded": True, "hold_req": req}), encoding="utf-8")

    with monkeypatch.context() as mp:
        mp.setattr(cta.os, "open", _open_miss)
        mp.setattr(cta.os, "close", _close_miss)
        acks3, lat3 = cta._hold_on_timeout(prep3, {"io": str(cfg3_missing)}, confirm_wait_s=0.05, poll_s=0.01)
    assert acks3[str(cfg3_missing)] == "error: FileNotFoundError" and lat3[str(cfg3_missing)] is False
    assert lat3[str(fb3)] is True and "chunk-io-s" not in acks3 and "chunk-io-s" not in lat3

    # 4: Relative custom `io` (including trailing whitespace) resolves against cfg.parent identically across _hold_on_timeout, execute_act_policy_task, and cell_policy_drive.main.
    prep4, cfg_dir, other_cwd = tmp_path / "p4", tmp_path / "cfg_root", tmp_path / "worker_cwd"
    io_name = "custom-arm-io "
    real_io, decoy_io = cfg_dir / io_name, other_cwd / io_name
    for d in (prep4, real_io, decoy_io):
        d.mkdir(parents=True)
    (real_io / "chunk-cmd").write_bytes(b"")
    (decoy_io / "chunk-cmd").write_bytes(b"")
    (prep4 / "chunks-arm-s-inplace-live.json").write_text("{}", encoding="utf-8")
    (wrap4 := tmp_path / "wrap.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (cfg4 := cfg_dir / "cell.json").write_text(json.dumps({
        "arm_id": "arm_s", "io": io_name, "cameras": {},
        "sites": {"pinky": {"auto_roi": [0, 0, 10, 10]}, "belt": {}},
        "act_policy": {"execution_allowed": True, "policy_root": str(tmp_path), "policy_revision": "a" * 64,
                       "cell_calibration": str(tmp_path / "cell-cal.json"), "model_calibration": str(tmp_path / "m-cal.json")},
    }), encoding="utf-8")
    (tmp_path / "cell-cal.json").write_text("{}", encoding="utf-8")
    (tmp_path / "m-cal.json").write_text("{}", encoding="utf-8")
    (tmp_path / "lib4.json").write_text(json.dumps({"fps": 30, "gripper_closed": 46.6, "chunks": {"home": [[0] * 6], "reach": [[0] * 6, [1, 0, 0, 0, 0, 0]]}}), encoding="utf-8")

    opened4, rel_fd = [], [None]

    def _open_rel(path, flags):
        opened4.append(str(path))
        fd = real_open(tmp_path / "rel-sink", cta.os.O_WRONLY | cta.os.O_CREAT | cta.os.O_TRUNC, 0o600)
        rel_fd[0] = fd
        return fd

    def _close_rel(fd):
        real_close(fd)
        if fd == rel_fd[0]:
            req = (tmp_path / "rel-sink").read_text(encoding="utf-8").strip().split()[1]
            (real_io / "live.json").write_text(
                json.dumps({"t": time.time() + 0.01, "human_hold_latched": True, "torque_hold_commanded": True, "hold_req": req}), encoding="utf-8"
            )

    monkeypatch.chdir(other_cwd)
    with monkeypatch.context() as mp:
        mp.setattr(cta.os, "open", _open_rel)
        mp.setattr(cta.os, "close", _close_rel)
        tmo4 = cta.execute_act_policy_task(
            {"task_id": "t-rel", "cell_id": "cell_s", "src_site": "pinky", "dst_site": "belt",
             "presence": {"operator": "livsbittt", "at": time.time() - 2}},
            arm_id="arm_s", prep_dir=prep4, wrapper=wrap4, cfg=cfg4, cat=tmp_path / "cat.json", default_roi=(0, 0, 10, 10),
            lease_owner="w1", tools_root_fn=lambda: tmp_path,
            run_fn=lambda *_a, **_kw: (_ for _ in ()).throw(subprocess.TimeoutExpired("cmd", 300)),
            last_json_fn=lambda _s: {}, measured_fold_fn=lambda *_a, **_kw: {}, source_clearance_fn=lambda *_a, **_kw: {},
            fold_readback_fn=lambda *_a, **_kw: {}, plan_home_fn=lambda *_a, **_kw: [], write_context_fn=lambda *_a, **_kw: None,
            timeout_exc=subprocess.TimeoutExpired,
        )
    assert opened4 == [str(real_io / "chunk-cmd")]
    assert tmo4["stop_event"]["timeout_hold"] == {io_name: "human-hold sent"}
    assert tmo4["stop_event"]["timeout_hold_latched"] == {io_name: True}

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
        mp.setattr(cpd.lrs, "LeRobotShadow", lambda *_a, **_kw: SimpleNamespace(
            sim_rule=None, goal_size=None, image_views=(), files={},
            inputs=lambda st, _f, **_k: ({"s": st}, {}), infer=lambda _o: SimpleNamespace(chunk=[[0.0] * 6] * 16),
        ))
        rc = cpd.main(["--config", str(cfg4), "--library", str(tmp_path / "lib4.json"), "--policy-root", str(tmp_path),
                       "--policy-revision", "a" * 64, "--cell-calibration", str(tmp_path / "cell-cal.json"),
                       "--model-calibration", str(tmp_path / "m-cal.json"), "--operator", "livsbittt", "--max-chunks", "1", "--dry-run"])
    assert rc == 0 and seen_io == [real_io]

    # 5: Omitted, empty, or non-string `io` fails closed before subprocess in execute_act_policy_task AND before checkpoint/FifoCell load in cell_policy_drive.main.
    for bad_cfg_body in (
        {"arm_id": "arm_s", "io": "", "cameras": {}},
        {"arm_id": "arm_s", "io": None, "cameras": {}},
        {"arm_id": "arm_s", "cameras": {}},
    ):
        res_bad_io, cmds_bad_io = _act_setup(tmp_path, monkeypatch, cfg_override={
            **bad_cfg_body,
            "sites": {"pinky": {"auto_roi": [49, 139, 295, 305]}, "belt": {"auto_roi": [309, 100, 634, 223]}},
            "act_policy": {"execution_allowed": True, "policy_root": str(tmp_path), "policy_revision": "a" * 64,
                           "cell_calibration": str(tmp_path / "cell-cal.json"), "model_calibration": str(tmp_path / "m-cal.json")},
        })
        assert res_bad_io["error"] == "ACT_POLICY_CONFIG_MISSING" and cmds_bad_io == []

        (bad_cfg := cfg_dir / "bad-empty-io.json").write_text(json.dumps(bad_cfg_body), encoding="utf-8")
        with monkeypatch.context() as mp:
            mp.setattr(cp, "FifoCell", lambda *_a, **_kw: pytest.fail("invalid io must not construct FifoCell"))
            mp.setattr(cpd.lrs, "LeRobotShadow", lambda *_a, **_kw: pytest.fail("invalid io must not initialize LeRobotShadow"))
            with pytest.raises(SystemExit) as exc_info:
                cpd.main(["--config", str(bad_cfg), "--library", str(tmp_path / "lib4.json"), "--policy-root", str(tmp_path),
                          "--policy-revision", "a" * 64, "--cell-calibration", str(tmp_path / "cell-cal.json"),
                          "--model-calibration", str(tmp_path / "m-cal.json"), "--operator", "livsbittt", "--max-chunks", "1", "--dry-run"])
            assert exc_info.value.code == 2

    # 6: OSError from fallback or configured `fifo.exists()` skips broken fallbacks and records explicit configured error without aborting HOLD.
    prep6, cfg6 = tmp_path / "p6", tmp_path / "cfg6_io"
    fb6 = prep6 / "chunk-io-s"
    prep6b, cfg6b = tmp_path / "p6b", tmp_path / "cfg6b_io"
    fb6b = prep6b / "chunk-io-s"
    for d in (cfg6, fb6, cfg6b, fb6b):
        d.mkdir(parents=True)
        (d / "chunk-cmd").write_bytes(b"")
    perm_targets: dict[int, Path] = {}
    orig_exists = cta.Path.exists

    def _exists_perm(self):
        if self in (fb6 / "chunk-cmd", cfg6b / "chunk-cmd"):
            raise PermissionError("unreadable fifo")
        return orig_exists(self)

    def _open_perm(path, flags):
        sink_p = tmp_path / f"perm-sink-{len(perm_targets)}"
        fd = real_open(sink_p, cta.os.O_WRONLY | cta.os.O_CREAT | cta.os.O_TRUNC, 0o600)
        perm_targets[fd] = (Path(path).parent, sink_p)
        return fd

    def _close_perm(fd):
        real_close(fd)
        if item := perm_targets.get(fd):
            parent, sink_p = item
            req = sink_p.read_text(encoding="utf-8").strip().split()[1]
            (parent / "live.json").write_text(json.dumps({"t": time.time() + 0.01, "human_hold_latched": True, "torque_hold_commanded": True, "hold_req": req}), encoding="utf-8")

    with monkeypatch.context() as mp:
        mp.setattr(cta.Path, "exists", _exists_perm)
        mp.setattr(cta.os, "open", _open_perm)
        mp.setattr(cta.os, "close", _close_perm)
        acks6, lat6 = cta._hold_on_timeout(prep6, {"io": str(cfg6)}, confirm_wait_s=0.05, poll_s=0.01)
        acks6b, lat6b = cta._hold_on_timeout(prep6b, {"io": str(cfg6b)}, confirm_wait_s=0.05, poll_s=0.01)
    assert acks6["cfg6_io"] == "human-hold sent" and lat6["cfg6_io"] is True and "chunk-io-s" not in lat6
    assert acks6b["cfg6b_io"] == "error: PermissionError" and lat6b["cfg6b_io"] is False and lat6b["chunk-io-s"] is True

    # 7: Configured owner FIFO opens/writes BEFORE fallback paths are probed, and Python 3.12 symlink-loop `RuntimeError` on `resolve()` never blocks HOLD.
    prep7, cfg7 = tmp_path / "p7", tmp_path / "cfg7_io"
    fb7 = prep7 / "chunk-io-s"
    prep7b, cfg7b = tmp_path / "p7b", tmp_path / "cfg7b_io"
    fb7b = prep7b / "chunk-io-s"
    for d in (cfg7, fb7, cfg7b, fb7b):
        d.mkdir(parents=True)
        (d / "chunk-cmd").write_bytes(b"")
    orig_resolve = cta.Path.resolve
    loop_events: list[tuple[str, str]] = []
    loop_targets: dict[int, tuple[Path, Path]] = {}

    def _resolve_loop(self, strict: bool = False):
        loop_events.append(("resolve", self.parent.name))
        if self in (fb7 / "chunk-cmd", cfg7b / "chunk-cmd"):
            raise RuntimeError(f"Symlink loop from {self}")
        return orig_resolve(self, strict=strict)

    def _open_loop(path, flags):
        loop_events.append(("open", Path(path).parent.name))
        sink_p = tmp_path / f"loop-sink-{len(loop_targets)}"
        fd = real_open(sink_p, cta.os.O_WRONLY | cta.os.O_CREAT | cta.os.O_TRUNC, 0o600)
        loop_targets[fd] = (Path(path).parent, sink_p)
        return fd

    def _close_loop(fd):
        real_close(fd)
        if item := loop_targets.get(fd):
            parent, sink_p = item
            req = sink_p.read_text(encoding="utf-8").strip().split()[1]
            (parent / "live.json").write_text(json.dumps({"t": time.time() + 0.01, "human_hold_latched": True, "torque_hold_commanded": True, "hold_req": req}), encoding="utf-8")

    with monkeypatch.context() as mp:
        mp.setattr(cta.Path, "resolve", _resolve_loop)
        mp.setattr(cta.os, "open", _open_loop)
        mp.setattr(cta.os, "close", _close_loop)
        acks7, lat7 = cta._hold_on_timeout(prep7, {"io": str(cfg7)}, confirm_wait_s=0.05, poll_s=0.01)
        acks7b, lat7b = cta._hold_on_timeout(prep7b, {"io": str(cfg7b)}, confirm_wait_s=0.05, poll_s=0.01)
    assert loop_events[:2] == [("resolve", "cfg7_io"), ("open", "cfg7_io")]
    assert acks7["cfg7_io"] == "human-hold sent" and lat7["cfg7_io"] is True and "chunk-io-s" not in acks7 and "chunk-io-s" not in lat7
    assert acks7b["cfg7b_io"] == "error: RuntimeError" and lat7b["cfg7b_io"] is False and lat7b["chunk-io-s"] is True

    # 8: Distinct per-endpoint hold_req tokens reject cross-endpoint live.json echo and confirm only exact match.
    prep_b, cfg_b = tmp_path / "pb", tmp_path / "cfgb_io"
    fb_b = prep_b / "chunk-io-s"
    for d in (cfg_b, fb_b):
        d.mkdir(parents=True)
        (d / "chunk-cmd").write_bytes(b"")
    b_fds, b_reqs, swap_mode = {}, {}, [True]

    def _open_b(path, flags):
        sink_p = tmp_path / f"b-sink-{Path(path).parent.name}-{swap_mode[0]}"
        fd = real_open(sink_p, cta.os.O_WRONLY | cta.os.O_CREAT | cta.os.O_TRUNC, 0o600)
        b_fds[fd] = (Path(path).parent, sink_p)
        return fd

    def _close_b(fd):
        real_close(fd)
        if item := b_fds.pop(fd, None):
            parent, sink_p = item
            b_reqs[parent.name] = sink_p.read_text(encoding="utf-8").strip().split()[1]
            if len(b_reqs) == 2:
                assert b_reqs["cfgb_io"] != b_reqs["chunk-io-s"]
                cfg_req, fb_req = (b_reqs["chunk-io-s"], b_reqs["cfgb_io"]) if swap_mode[0] else (b_reqs["cfgb_io"], b_reqs["chunk-io-s"])
                (cfg_b / "live.json").write_text(json.dumps({"t": time.time() + 0.05, "human_hold_latched": True, "torque_hold_commanded": True, "hold_req": cfg_req}), encoding="utf-8")
                (fb_b / "live.json").write_text(json.dumps({"t": time.time() + 0.05, "human_hold_latched": True, "torque_hold_commanded": True, "hold_req": fb_req}), encoding="utf-8")

    with monkeypatch.context() as mp:
        mp.setattr(cta.os, "open", _open_b)
        mp.setattr(cta.os, "close", _close_b)
        _, lat_swap = cta._hold_on_timeout(prep_b, {"io": str(cfg_b)}, confirm_wait_s=0.06, poll_s=0.01)
        assert lat_swap == {"cfgb_io": False, "chunk-io-s": False}
        b_reqs.clear()
        swap_mode[0] = False
        _, lat_ok = cta._hold_on_timeout(prep_b, {"io": str(cfg_b)}, confirm_wait_s=0.06, poll_s=0.01)
        assert lat_ok == {"cfgb_io": True, "chunk-io-s": True}

    # 9: Huge integer timestamp (10**400) in configured live.json never blocks fallback dispatch or raises OverflowError.
    prep9, cfg9 = tmp_path / "p9", tmp_path / "cfg9_io"
    fb9 = prep9 / "chunk-io-s"
    for d in (cfg9, fb9):
        d.mkdir(parents=True)
        (d / "chunk-cmd").write_bytes(b"")
    (cfg9 / "live.json").write_text(json.dumps({"t": 10**400, "human_hold_latched": True, "torque_hold_commanded": True}), encoding="utf-8")
    fds9 = {}

    def _open9(path, flags):
        sink_p = tmp_path / f"p9-sink-{Path(path).parent.name}"
        fd = real_open(sink_p, cta.os.O_WRONLY | cta.os.O_CREAT | cta.os.O_TRUNC, 0o600)
        fds9[fd] = (Path(path).parent, sink_p)
        return fd

    def _close9(fd):
        real_close(fd)
        if item := fds9.pop(fd, None):
            parent, sink_p = item
            req = sink_p.read_text(encoding="utf-8").strip().split()[1]
            t_out = 10**400 if parent == cfg9 else time.time() + 0.05
            (parent / "live.json").write_text(json.dumps({"t": t_out, "human_hold_latched": True, "torque_hold_commanded": True, "hold_req": req}), encoding="utf-8")

    with monkeypatch.context() as mp:
        mp.setattr(cta.os, "open", _open9)
        mp.setattr(cta.os, "close", _close9)
        acks9, lat9 = cta._hold_on_timeout(prep9, {"io": str(cfg9)}, confirm_wait_s=0.05, poll_s=0.01)
    assert acks9 == {"cfg9_io": "human-hold sent", "chunk-io-s": "human-hold sent"}
    assert lat9 == {"cfg9_io": False, "chunk-io-s": True}


def test_act_policy_park_receipt_requires_owner_park_command_label(tmp_path, monkeypatch):
    zone_ok = {"basis": cte.TOP_ONLY_BASIS, "verified": True, "before_frames": {"top": "t-1-top.jpg"},
               "target": {"site": "belt", "area": "belt", "tier": 1, "roi": [309, 100, 634, 223]}}
    base_res = {"result": "chunks_done", "held": True, "parked": True,
                "source": {"before": 1, "after": 0}, "took_one": True, "zone_verification": zone_ok}

    for park_val, expect_ok in (
        ({**PARK, "command": "run park"}, True),
        ({**PARK, "command": "checked s1 h1 park"}, True),
        ({"ok": True, "settled": True, "state": PARK["state"]}, False),
        ({**PARK, "command": "run policy"}, False),
        ({**PARK, "human_hold_latched": True}, False),
    ):
        out, _ = _act_setup(tmp_path, monkeypatch, subprocess_res={**base_res, "park": park_val})
        assert out["stop_event"]["folded"] is expect_ok
        assert out["stage_result"]["task_verified"] is expect_ok
