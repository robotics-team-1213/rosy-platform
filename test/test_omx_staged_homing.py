"""Tests for OMX-side D-1048 staged homing, HTTPS telemetry sync, safety-fence fail-closed guards & outbox codes."""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "deploy" / "robot" / "omx", ROOT / "middleware" / "devices" / "omx" / "adapter"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cell_auto_fold as auto_fold_mod  # noqa: E402
import cell_camera_telemetry_sync as sync_mod  # noqa: E402
import cell_result_outbox as outbox_mod  # noqa: E402


def test_omx_sync_tls_expiry_inflight_and_park_only_preserves_hold(tmp_path, monkeypatch):
    launched = []
    pending_resp = {
        "ok": True, "schema": "rosy.pipeline.cell-quality.v1", "human_hold": False, "safety_stop_generation": 0,
        "pending_safe_home_arms": {"arm_b": {"request_id": "r1", "strategy": "release_and_lift", "expires_at": time.time() + 60}},
    }

    def fake_urlopen(req, context=None, timeout=6):
        class _Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        if "8767/state.json" in req.full_url:
            return _Resp(b"{}")
        return _Resp(json.dumps(pending_resp).encode("utf-8"))

    for url, ver in (("http://fleet.invalid", True), ("https://fleet.invalid", False)):
        out = sync_mod.sync_cell_telemetry(
            url, "tok", prep_dir=tmp_path, urlopen_fn=fake_urlopen, tls_verified=ver, allow_safe_home=True,
            launch_auto_fold_fn=lambda *a, **k: launched.append(a) or {"started": True},
        )
        assert out["safe_home_blocked_reason"] == "UNVERIFIED_TLS" and launched == []

    sync_mod.sync_cell_telemetry(
        "https://fleet.invalid", "tok", prep_dir=tmp_path, urlopen_fn=fake_urlopen, tls_verified=True, allow_safe_home=True,
        launch_auto_fold_fn=lambda arm, **k: launched.append((arm, k["stage"], k["request_id"])) or {"started": True},
    )
    assert len(launched) == 1 and launched[0] == ("arm_b", "release_and_lift", "r1")

    # Temporary hold/empty pending response MUST NOT prune 'started'/'in_flight' marker!
    pending_resp["pending_safe_home_arms"] = {}
    sync_mod.sync_cell_telemetry(
        "https://fleet.invalid", "tok", prep_dir=tmp_path, urlopen_fn=fake_urlopen, tls_verified=True, allow_safe_home=True,
        launch_auto_fold_fn=lambda *a, **k: {"started": True},
    )
    assert "r1" in json.loads((tmp_path / ".safe-home-acks.json").read_text(encoding="utf-8"))

    # Incomplete HTTP 200 (both with and without pending_safe_home_arms) unlinks .safety-fence.json and blocks fail-closed.
    incomplete_out = sync_mod.sync_cell_telemetry(
        "https://fleet.invalid", "tok", prep_dir=tmp_path, tls_verified=True, allow_safe_home=True,
        urlopen_fn=lambda req, **_k: io.BytesIO(b"{}") if "8767" in req.full_url else io.BytesIO(b"{}"),
        launch_auto_fold_fn=lambda *a, **k: launched.append("BAD_INC") or {"started": True},
    )
    assert incomplete_out["safe_home_blocked_reason"] == "INCOMPLETE_SAFETY_FENCE" and not (tmp_path / ".safety-fence.json").exists()

    # Expired request skips without launching.
    pending_resp["pending_safe_home_arms"] = {"arm_b": {"request_id": "r-exp", "strategy": "auto_fold", "expires_at": time.time() - 5}}
    sync_mod.sync_cell_telemetry(
        "https://fleet.invalid", "tok", prep_dir=tmp_path, urlopen_fn=fake_urlopen, tls_verified=True, allow_safe_home=True,
        launch_auto_fold_fn=lambda *a, **k: launched.append("BAD") or {"started": True},
    )
    assert json.loads((tmp_path / ".safe-home-acks.json").read_text(encoding="utf-8"))["r-exp"]["outcome"] == "skipped"

    # human-hold ok=False refuses to report risen_for_visual_verify; park_only skips omx_incident.clear!
    class _FailHoldCell:
        def act(self, cmd):
            if cmd == "human-hold":
                return {"ok": False}
            return {"ok": True, "state": [0.0, -40.0, 45.0, 20.0, 10.0, 40.0], "target": [0.0, -40.0, 45.0, 20.0, 10.0, 5.0]}

    res_fail = auto_fold_mod.recover(
        _FailHoldCell(), [0.0, -60.0, 50.0, 50.0, 45.0, 5.0], 5.0,
        plan=lambda s: [s], look=lambda _f: {"clear": True}, reserve=lambda _f: {"ok": True},
        release=lambda: None, release_and_rise=lambda _c: {"result": "risen"}, low=lambda _s: True, stage="release_and_lift",
    )
    assert res_fail["result"] == "held" and res_fail["reason"] == "HOLD_AFTER_LIFT_FAILED"

    import omx_incident
    import omx_incident_auto
    monkeypatch.setattr(omx_incident, "INCIDENTS", tmp_path / "inc")
    monkeypatch.setattr(omx_incident_auto, "note_event", lambda _e: None)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    cfg = tmp_path / "af.json"
    cfg.write_text(json.dumps({"arm_b": {"wrapper": "w", "config": "c", "library": "l", "site": "s", "roi": [0, 0, 10, 10], "cwd": str(cwd)}}), encoding="utf-8")
    cleared = []

    def fake_run(cmd, **_kw):
        Path(cmd[cmd.index("--out") + 1]).write_text(json.dumps({"result": "folded", "candidate": "park", "home": [0] * 6}), encoding="utf-8")
        (cwd / "session.json").write_text(json.dumps({"arm": "arm_b", "torque_after": {"11": 0}}), encoding="utf-8")
        return SimpleNamespace(stdout="", stderr="")

    res_pk = auto_fold_mod.launch(
        "arm_b", cfg, link=SimpleNamespace(hold=lambda: SimpleNamespace(incident_ids=["inc-p1"])),
        run=fake_run, sleep=lambda _s: None, clear=lambda *a, **k: cleared.append(a),
        stage="park_only", request_id="req-p1",
    )
    assert res_pk["result"] == "parked_for_visual_verify" and cleared == []
    assert json.loads((tmp_path / "inc" / "auto-fold-req-req-p1.result.json").read_text(encoding="utf-8"))["outcome"] == "completed"

    # Missing safety-fence fails closed in auto_fold_stages (never runs recover_fn).
    from cell_auto_fold_stages import run_cli_main
    called = []
    lib_p = tmp_path / "lib.json"
    lib_p.write_text(json.dumps({"chunks": {"home": [[0] * 6]}, "gripper_closed": 5.0, "fps": 30}), encoding="utf-8")
    prm_p = tmp_path / "params.json"
    prm_p.write_text(json.dumps({"schema": "rosy.omx-cell-params.v1", "params": {}}), encoding="utf-8")
    cal_p = tmp_path / "cal.json"
    cal_p.write_text("{}", encoding="utf-8")
    arm_cfg = tmp_path / "arm_cfg.json"
    arm_cfg.write_text(json.dumps({"io": str(tmp_path), "cameras": {}, "params_path": str(prm_p),
                                   "calibration_path": str(cal_p), "sites": {"s": {}}}), encoding="utf-8")
    out_p = tmp_path / "stage_out.json"
    monkeypatch.setenv("ROSY_RECOVERY_INCIDENT", "inc-fence")
    import omx_adapter.chunk_library  # noqa: F401
    import cell_pipeline  # noqa: F401
    monkeypatch.setattr(cell_pipeline, "FifoCell", lambda *_a: SimpleNamespace(act=lambda _c: {"ok": True}))
    rc = run_cli_main(
        ["--arm", "arm_b", "--config", str(arm_cfg), "--library", str(lib_p), "--site", "s", "--roi", "0", "0", "10", "10",
         "--out", str(out_p), "--stop-generation", "1", "--safety-fence", str(tmp_path / "missing-fence.json")],
        launch_fn=lambda *a, **k: {}, recover_fn=lambda *a, **k: called.append(True) or {"result": "folded"},
        candidate_names_fn=lambda: ["park"], choice_key="auto_fold.candidate", schema="rosy.omx-auto-fold.v1",
    )
    assert rc == 3 and called == [] and json.loads(out_p.read_text(encoding="utf-8"))["reason"] == "SAFETY_FENCE_MISSING"
    # Fresh fence with --stop-generation omitted STILL fails closed!
    valid_fence = tmp_path / "fresh-fence.json"
    valid_fence.write_text(json.dumps({"human_hold": False, "stop_generation": 0, "updated_at": time.time()}), encoding="utf-8")
    rc2 = run_cli_main(
        ["--arm", "arm_b", "--config", str(arm_cfg), "--library", str(lib_p), "--site", "s", "--roi", "0", "0", "10", "10",
         "--out", str(out_p), "--safety-fence", str(valid_fence)],
        launch_fn=lambda *a, **k: {}, recover_fn=lambda *a, **k: called.append(True) or {"result": "folded"},
        candidate_names_fn=lambda: ["park"], choice_key="auto_fold.candidate", schema="rosy.omx-auto-fold.v1",
    )
    assert rc2 == 3 and called == [] and json.loads(out_p.read_text(encoding="utf-8"))["reason"] == "STOP_GENERATION_PREEMPTED"


def test_outbox_abort_reason_codes():
    assert outbox_mod.abort_reason({"review_required": True, "error": "FOLD_READBACK_MISSING"}) == "REVIEW_REQUIRED"
    assert outbox_mod.abort_reason({"error": "FOLD_READBACK_MISSING"}) == "FOLD_READBACK_MISSING"
    assert outbox_mod.abort_reason({"error": "UNCALIBRATED_DISPLACED_SITE"}) == "UNCALIBRATED_DISPLACED_SITE"
    assert outbox_mod.abort_reason({}) == "MEASURED_PLACEMENT_MISSING"
