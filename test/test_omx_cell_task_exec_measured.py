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


def _exec(tmp_path, monkeypatch, parsed, *, home=HOME, returncode=0):
    (tmp_path / "with-session-arm-s-live.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    # as in the real cell config: the home lives in the grasp plan file that `plan_path` names, not in the config JSON
    (tmp_path / "grasp-plan.json").write_text(json.dumps({"home": home} if home else {}), encoding="utf-8")
    (tmp_path / "cell-auto-arm-s-live.json").write_text(json.dumps({"plan_path": str(tmp_path / "grasp-plan.json")}), encoding="utf-8")
    monkeypatch.setattr(cte, "check_arm_hold", lambda arm: {"held": False})
    monkeypatch.setattr(cte.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, returncode, stdout=CLI_NOISE + json.dumps(parsed, indent=1, default=str) + "\n", stderr=""))  # as cell_auto_pick prints it
    return cte.execute_guarded_cell_task(HANDOFF, prep_dir=tmp_path)


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
    else:  # a real park readback still folds on its own: the fold and the placement are separate measurements
        assert out["stop_event"]["folded"] is True


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
