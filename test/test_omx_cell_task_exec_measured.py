"""D-1057: the cell task executor reports measured placement and a measured fold, never a single placed flag."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
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
