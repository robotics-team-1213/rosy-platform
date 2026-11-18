"""The cell task worker never calls the real arm on a refused handoff, and unknown sites and tiers are refused."""
from __future__ import annotations

import io
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "deploy/robot/omx", ROOT / "middleware/devices/omx/adapter"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cell_fleet_pipeline as cfp  # noqa: E402
import cell_task_worker as ctw  # noqa: E402

LOCKED = {"wheel_brake_locked": True, "bed_ready": True, "v_cmd_mps": 0.0}


def _run(tmp_path: Path, handoff: dict, tier: int = 1):
    hw_calls: list[dict] = []
    posted: list[dict] = []
    cell_id = handoff.get("cell_id", "cell_s")
    bound = {"handoff_lease_id": "lease-1", "task_id": "t-1", "tier": tier,
             "arm_id": "arm_s" if cell_id == "cell_s" else "arm_b", **handoff}

    def _req(method: str, path: str, body):
        if method == "GET":
            return {"tasks": [{"task_id": "t-1", "cell_id": cell_id, "tier": tier}],
                    "human_safety": {"active_estop": False, "human_detected": {}},
                    "cells": {cell_id: {"phase": "ARM_IN_BED_ZONE", "active_task_id": "t-1"}}}
        if path.endswith("/claim"):
            return {"claimed": True, "gate": {}, "handoff": bound}
        posted.append(body)
        return {"gate": {}, "task": {"status": body["phase"]}}

    def _hw(h):
        hw_calls.append(h)
        return {"arm": "arm_s", "events_count": 0, "stop_event": {}}

    pipe = cfp.FleetModelPipeline(tmp_path / "pipe")
    ctw.poll_and_execute_once(pipe, request_fn=_req, live_act_fn=_hw, prep_dir=tmp_path)
    return hw_calls, posted[0]


@pytest.mark.parametrize(
    "handoff,reason",
    [
        ({"cell_id": "cell_s"}, "AMR_NOT_LOCKED_AT_HANDOFF"),  # interlock keys missing
        ({**LOCKED, "cell_id": "cell_s", "wheel_brake_locked": False}, "AMR_NOT_LOCKED_AT_HANDOFF"),
        ({**LOCKED, "cell_id": "cell_s", "v_cmd_mps": float("nan")}, "AMR_NOT_LOCKED_AT_HANDOFF"),
        ({**LOCKED, "cell_id": "cell_s", "dst_site": "bellt"}, "UNKNOWN_SITE"),
        ({**LOCKED, "cell_id": "cell_ab", "src_site": "pinky"}, "UNKNOWN_SITE"),
        ({**LOCKED, "cell_id": "cell_ab", "dst_site": "pallet-l2"}, "UNKNOWN_SITE"),  # wrong level for tier 1
    ],
)
def test_refused_handoff_never_calls_the_arm(tmp_path: Path, handoff: dict, reason: str) -> None:
    hw_calls, body = _run(tmp_path, handoff)
    assert hw_calls == []
    assert body["phase"] == "ABORTED" and body["reason"] == reason
    assert body["hardware_telemetry"] == {"error": reason}


@pytest.mark.parametrize("cell_id", ["cell_s", "cell_ab"])
def test_unknown_tier_is_refused_by_the_handoff_check(tmp_path: Path, cell_id: str) -> None:
    from cell_fleet_handoff import handoff_refusal

    pipe = cfp.FleetModelPipeline(tmp_path / "pipe")
    assert handoff_refusal(pipe, {**LOCKED, "cell_id": cell_id}, 4) == "UNKNOWN_SITE"


def test_locked_handoff_without_measured_placement_is_aborted(tmp_path: Path) -> None:
    hw_calls, body = _run(tmp_path, {**LOCKED, "cell_id": "cell_s"})
    assert len(hw_calls) == 1  # the arm runs, but only measured placement releases
    assert body["phase"] == "ABORTED" and body["reason"] == "MEASURED_PLACEMENT_MISSING"
    assert body["receipt"]["simulated_success"] is False and body["receipt"]["physical_completion"] is False


def test_dispatch_path_cannot_complete_with_a_synthetic_stage(tmp_path: Path) -> None:
    hw_calls: list[dict] = []
    pipe = cfp.FleetModelPipeline(tmp_path / "pipe")
    with pytest.raises(RuntimeError, match="SIMULATED_STAGE_CANNOT_COMPLETE_FLEET_TASK"):
        pipe.dispatch_and_execute_fleet_r_cell_task(fleet_r_url="https://fleet.invalid", dst_site="bellt",
                                                    live_act_fn=hw_calls.append, request_fn=lambda *a: {})
    assert hw_calls == []


def test_pipeline_refuses_unknown_site_and_tier(tmp_path: Path) -> None:
    pipe = cfp.FleetModelPipeline(tmp_path / "pipe")
    with pytest.raises(ValueError, match="unknown site"):
        pipe.run_fleet_stage(arm_id="arm_s", src_site="pinky", dst_site="bellt")
    with pytest.raises(ValueError, match="tier"):
        pipe.prestage_cell_ab_handover(tier=4)


def test_worker_main_seals_legacy_live_jog_by_default(tmp_path: Path, monkeypatch) -> None:
    tok = tmp_path / "tok"
    tok.write_text("dummy-token", encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr(ctw, "make_default_request_fn", lambda *a, **k: (lambda m, p, b: calls.append(f"{m}:{p}") or {}))
    monkeypatch.setattr(ctw, "sync_cell_telemetry", lambda *a, **k: calls.append("sync") or {})
    monkeypatch.setattr(ctw, "execute_live_hardware_arm", lambda *a, **k: calls.append("live_jog") or {})

    ctw.main(["--once", "--token-file", str(tok), "--work-dir", str(tmp_path / "w"), "--prep-dir", str(tmp_path / "p")])
    assert "sync" in calls
    assert "live_jog" not in calls
    assert not any(c.startswith("POST:/api/fleet/pipeline/cell-tasks/claim") for c in calls)


def test_worker_skips_held_arm_before_claim_and_classifies_401(tmp_path: Path) -> None:
    from urllib.error import HTTPError

    tok = tmp_path / "tok"
    tok.write_text("short-token-value", encoding="utf-8")
    calls: list[str] = []

    def _req(method: str, path: str, body):
        calls.append(f"{method}:{path}")
        return {"tasks": [{"task_id": "t-held", "cell_id": "cell_ab", "arm_id": "arm_a", "tier": 1}],
                "human_safety": {"active_estop": False, "human_detected": {}},
                "cells": {"cell_ab": {"phase": "ARM_IN_BED_ZONE", "active_task_id": "t-held"}}}

    pipe = cfp.FleetModelPipeline(tmp_path / "pipe")
    ctw.poll_and_execute_once(pipe, request_fn=_req, live_act_fn=lambda h: {"ok": True}, prep_dir=tmp_path,
                              hold_check_fn=lambda arm: {"held": arm == "arm_a", "reason": "open hold"})
    assert calls == ["GET:/api/fleet/pipeline/cell-tasks?status=QUEUED"]

    err = HTTPError("https://192.168.1.93:8443/api/fleet/pipeline/cell-tasks", 401, "Unauthorized", {}, io.BytesIO(b""))
    diag = ctw.classify_poll_error(err, tok)
    assert diag["event"] == "poll_auth_error" and diag["status"] == 401 and diag["token_chars"] == len("short-token-value")
    assert "short-token-value" not in json.dumps(diag)
