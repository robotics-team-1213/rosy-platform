"""D-1078 OMX autonomous execution tests: ACT lease + guarded stop-proof without weakening guards."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "deploy/robot/omx", ROOT / "middleware/devices/omx/adapter"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cell_auto_setup as cas  # noqa: E402
import cell_presence as cp  # noqa: E402
import cell_task_act as cta  # noqa: E402
import cell_task_act_run as ctar  # noqa: E402
import cell_task_exec as cte  # noqa: E402


def _setup_act_tree(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    rev = "a" * 64
    wrapper = tmp_path / "with-session-arm-s-live.sh"
    wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
    lib = tmp_path / "chunks-arm-s-inplace-live.json"
    lib.write_text(json.dumps({"home": [0, -58, 50, 50, -5, 58]}), encoding="utf-8")
    cfg = tmp_path / "cell-auto-arm-s-live.json"
    cfg.write_text(json.dumps({
        "arm_id": "arm_s",
        "io": str(tmp_path / "chunk-io-s"),
        "plan_path": str(lib),
        "sites": {"pinky": {"auto_roi": [0, 0, 10, 10]}, "belt": {}},
        "act_policy": {
            "execution_allowed": True,
            "policy_root": str(tmp_path / "policy"),
            "policy_revision": rev,
            "cell_calibration": str(tmp_path / "cell-cal.json"),
            "model_calibration": str(tmp_path / "model-cal.json"),
            "library": lib.name,
            "max_chunks": 4,
        },
    }), encoding="utf-8")
    return wrapper, cfg, lib, rev


def test_act_policy_allows_autonomous_mode_without_person_at_switch(tmp_path: Path, monkeypatch):
    wrapper, cfg, lib, _rev = _setup_act_tree(tmp_path)
    handoff = {
        "task_id": "t-act-auto", "cell_id": "cell_s", "arm_id": "arm_s",
        "src_site": "pinky", "dst_site": "belt", "tier": 1, "handoff_lease_id": "lease-1",
    }

    monkeypatch.delenv("ROSY_OMX_AUTONOMOUS_POLICY", raising=False)
    refused = cta.plan_act_policy_task(handoff, arm_id="arm_s", prep_dir=tmp_path, wrapper=wrapper, cfg=cfg, default_roi=(0, 0, 10, 10))
    assert refused["error"] == "PRESENCE_REQUIRED_FOR_ACT_POLICY"

    auto_handoff = {**handoff, "approval_mode": "autonomous_policy", "approved_by": "autonomous_policy"}
    planned = cta.plan_act_policy_task(auto_handoff, arm_id="arm_s", prep_dir=tmp_path, wrapper=wrapper, cfg=cfg, default_roi=(0, 0, 10, 10))
    assert "plan" in planned

    seen_cmd: list[str] = []

    def fake_run(cmd, **_kw):
        seen_cmd.extend(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"result": "released", "parked": True, "took_one": True}), stderr="")

    monkeypatch.setattr(ctar, "act_verdict", lambda *a, **k: {
        "fold": {"folded": True, "state": [0, -58, 50, 50, -5, 58]},
        "live_fold": {"folded": True}, "folded": True, "took_one": True,
        "zone": {"verified": True, "basis": "top_camera_only_target_zone", "target": {"site": "belt", "tier": 1, "roi": [0, 0, 10, 10]}},
        "zone_ok": True, "verified": True,
    })
    out = ctar.execute_act_policy_task(
        auto_handoff, planned["plan"], arm_id="arm_s", wrapper=wrapper, cfg=cfg, cat=tmp_path / "cat.json",
        lease_owner="worker-1", tools_root_fn=lambda: tmp_path, run_fn=fake_run, last_json_fn=lambda s: json.loads(s),
        measured_fold_fn=lambda *_a: {"folded": True}, fold_readback_fn=lambda *_a: {"folded": True},
        plan_home_fn=lambda *_a: [0, -58, 50, 50, -5, 58], write_context_fn=lambda *_a, **_k: None,
        timeout_exc=subprocess.TimeoutExpired, prep_dir=tmp_path,
    )
    assert out["stage_result"]["task_verified"] is True
    assert "--policy-lease" in seen_cmd and "--person-at-switch" not in seen_cmd
    idx = seen_cmd.index("--operator")
    assert seen_cmd[idx + 1] == "autonomous_policy"


def test_guarded_exec_passes_stop_proof_when_autonomous(tmp_path: Path, monkeypatch):
    (tmp_path / "with-session-arm-s-live.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (tmp_path / "grasp-plan.json").write_text(json.dumps({"home": [0, -58, 50, 50, -5, 58]}), encoding="utf-8")
    (tmp_path / "cell-auto-arm-s-live.json").write_text(json.dumps({"plan_path": str(tmp_path / "grasp-plan.json")}), encoding="utf-8")
    monkeypatch.setattr(cte, "check_arm_hold", lambda _arm: {"held": False})
    monkeypatch.setattr(cte, "measured_fold", lambda *_a, **_k: {"folded": True, "fresh": True})
    monkeypatch.setattr(cte, "source_clearance", lambda *_a, **_k: {"objects": 0, "site": "pinky"})
    recorded: list[list[str]] = []
    monkeypatch.setattr(cte.subprocess, "run", lambda cmd, **_k: recorded.append(cmd) or subprocess.CompletedProcess(
        cmd, 0, stdout=json.dumps({"result": "placed", "attempts": []}), stderr=""))
    handoff = {
        "task_id": "t-auto-ik", "cell_id": "cell_s", "arm_id": "arm_s", "tier": 1,
        "handoff_lease_id": "lease-2", "src_site": "pinky", "dst_site": "belt",
        "approval_mode": "autonomous_policy",
    }
    cte.execute_guarded_cell_task(handoff, prep_dir=tmp_path)
    assert "--stop-proof" in recorded[0]
    assert "--person-at-switch" not in recorded[0]
    assert cp.effective_operator(handoff) == "autonomous_policy"


def test_open_cell_stop_proof_binds_commissioning_and_fails_closed(tmp_path: Path, monkeypatch):
    import cell_stop_proof  # noqa: E402

    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps({"arm_id": "arm_s", "work_dir": str(tmp_path), "calibration_path": str(tmp_path / "cal.json"), "cameras": {}}), encoding="utf-8")
    monkeypatch.setattr(cas, "load_config", lambda _p: json.loads(cfg_path.read_text(encoding="utf-8")))
    monkeypatch.setattr(cas, "fifo_cell", lambda cfg, _c: (cfg, SimpleNamespace()))
    monkeypatch.setattr(cas.cell_attempts, "start", lambda *a, **k: None)
    monkeypatch.setattr(cas.cd, "start", lambda *a, **k: None)

    args = SimpleNamespace(
        config=cfg_path, source="pinky", dest="belt", want_object=None, want_colour=None,
        layers_below=None, task_id="t-sp", handoff_lease_id="l-1", verify_zones=True,
        map_only=False, dry_run=False, stop_proof=True, commissioning=False, person_at_switch=False,
    )
    monkeypatch.setattr(cell_stop_proof, "session_proof", lambda *_a, **_k: {"ok": True, "schema": "rosy.stop-proof.v1", "arms": ["arm_s"]})
    cfg, *_ = cas.open_cell(args, commissioning=False)
    assert cfg["_commissioning"]["stop_proof"]["ok"] is True

    monkeypatch.setattr(cell_stop_proof, "session_proof", lambda *_a, **_k: {"ok": False, "code": "STOP_PROOF_NOT_FOLDED", "reason": "arm_s: not folded"})
    with pytest.raises(SystemExit, match="STOP_PROOF_NOT_FOLDED"):
        cas.open_cell(args, commissioning=False)

    monkeypatch.setenv("ROSY_OMX_AUTONOMOUS_POLICY", "1")
    assert cp.autonomous_policy_enabled({"requires_presence_confirm": True, "approval_mode": "autonomous_policy"}) is False
