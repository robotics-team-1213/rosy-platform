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
        stage="park_only", request_id="req-p1", expires_at=time.time() + 60,
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

    # Runtime safety fence checks: (1) tripped after start blocks motion admission; (2) watcher sends human-hold mid-motion.
    fence_state = {"human_hold": False, "stop_generation": 0, "updated_at": time.time()}
    rt_fence = tmp_path / "rt-fence.json"
    rt_fence.write_text(json.dumps(fence_state), encoding="utf-8")
    sent_cmds = []

    class _RuntimeCell:
        def act(self, cmd):
            sent_cmds.append(cmd)
            return {"ok": True}

    def _late_trip_recover(fenced_cell, *_a, **_kw):
        assert fenced_cell.act("state")["ok"] is True
        fence_state["stop_generation"] = 1
        fence_state["updated_at"] = time.time()
        rt_fence.write_text(json.dumps(fence_state), encoding="utf-8")
        res_move = fenced_cell.act("recover-unlatch")
        assert res_move["ok"] is False and res_move["error"] == "STOP_GENERATION_PREEMPTED"
        return {"schema": "rosy.omx-auto-fold.v1", "result": "folded", "steps": []}

    monkeypatch.setattr(cell_pipeline, "FifoCell", lambda *_a: _RuntimeCell())
    rc3 = run_cli_main(
        ["--arm", "arm_b", "--config", str(arm_cfg), "--library", str(lib_p), "--site", "s", "--roi", "0", "0", "10", "10",
         "--out", str(out_p), "--stop-generation", "0", "--safety-fence", str(rt_fence),
         "--expires-at", str(time.time() + 60)],
        launch_fn=lambda *a, **k: {}, recover_fn=_late_trip_recover,
        candidate_names_fn=lambda: ["park"], choice_key="auto_fold.candidate", schema="rosy.omx-auto-fold.v1",
    )
    assert rc3 == 3 and "recover-unlatch" not in sent_cmds and "human-hold" in sent_cmds
    assert json.loads(out_p.read_text(encoding="utf-8"))["reason"] == "STOP_GENERATION_PREEMPTED"

    import threading
    from cell_auto_fold_stages import FencedCell
    fence_state["stop_generation"] = 0
    fence_state["updated_at"] = time.time()
    rt_fence.write_text(json.dumps(fence_state), encoding="utf-8")
    hold_seen = threading.Event()
    park_cmds = []

    class _SlowMotionCell:
        def act(self, cmd):
            park_cmds.append(cmd)
            if cmd == "human-hold":
                hold_seen.set()
                return {"ok": True}
            assert hold_seen.wait(timeout=1.5), "watcher did not issue bounded human-hold during motion"
            return {"ok": True}

    fc = FencedCell(_SlowMotionCell(), lambda: "HUMAN_HOLD_ACTIVE" if json.loads(rt_fence.read_text())["human_hold"] else None, poll_s=0.02)
    fence_state["human_hold"] = True
    rt_fence.write_text(json.dumps(fence_state), encoding="utf-8")
    # First simulate pre-check passing then flipping mid-call:
    flipped = {"v": False}

    def _flip_check():
        if not flipped["v"]:
            flipped["v"] = True
            return None
        return "HUMAN_HOLD_ACTIVE"

    fc2 = FencedCell(_SlowMotionCell(), _flip_check, poll_s=0.02)
    mid_res = fc2.act("park-slow")
    assert mid_res["ok"] is False and mid_res["error"] == "HUMAN_HOLD_ACTIVE" and "human-hold" in park_cmds
    fc2.close()

    # Checked fold-from-hold is also fence-guarded (admission + watcher) and watcher survives fast jog ACK into settle wait.
    checked_cmds = []

    class _CheckedAndSettleCell:
        def act(self, cmd):
            checked_cmds.append(cmd)
            return {"ok": True}

        def checked(self, cmd, assessment):
            checked_cmds.append(("checked", cmd, assessment))
            return {"ok": True}

    raw = _CheckedAndSettleCell()
    flip_chk = {"v": False}

    def _chk_flip():
        if not flip_chk["v"]:
            flip_chk["v"] = True
            return None
        return "STOP_GENERATION_PREEMPTED"

    with FencedCell(raw, _chk_flip, poll_s=0.02) as fchk:
        assert fchk.checked("fold-from-hold 0 0 0 0 0 0", {"session_id": "s1", "library_sha256": "h1"})["ok"] is True
        # During jog settling sleep after fast ACK, watcher stays alive and trips on STOP_GENERATION_PREEMPTED!
        time.sleep(0.08)
        assert "human-hold" in checked_cmds and fchk.tripped_reason == "STOP_GENERATION_PREEMPTED"
        blocked_chk = fchk.checked("fold-from-hold 0 0 0 0 0 0", {"session_id": "s1", "library_sha256": "h1"})
        assert blocked_chk["ok"] is False and blocked_chk["error"] == "STOP_GENERATION_PREEMPTED"
        assert len([c for c in checked_cmds if isinstance(c, tuple)]) == 1


def test_outbox_abort_reason_codes():
    assert outbox_mod.abort_reason({"review_required": True, "error": "FOLD_READBACK_MISSING"}) == "REVIEW_REQUIRED"
    assert outbox_mod.abort_reason({"error": "FOLD_READBACK_MISSING"}) == "FOLD_READBACK_MISSING"
    assert outbox_mod.abort_reason({"error": "UNCALIBRATED_DISPLACED_SITE"}) == "UNCALIBRATED_DISPLACED_SITE"
    assert outbox_mod.abort_reason({"error": "SITE_NOT_CALIBRATED"}) == "SITE_NOT_CALIBRATED"
    assert outbox_mod.abort_reason({"error": "STAND_REQUIRES_ARM_A"}) == "STAND_REQUIRES_ARM_A"
    assert outbox_mod.abort_reason({"error": "untrusted USB diagnostic"}) == "MEASURED_PLACEMENT_MISSING"
    assert outbox_mod.abort_reason({}) == "MEASURED_PLACEMENT_MISSING"


def test_omx_safe_home_rejects_missing_or_nonfinite_expiry(tmp_path, monkeypatch):
    # 1. Telemetry sync skips missing/NaN/inf expires_at before launching.
    launched = []
    pending_resp = {
        "ok": True, "schema": "rosy.pipeline.cell-quality.v1", "human_hold": False, "safety_stop_generation": 0,
        "pending_safe_home_arms": {},
    }

    def fake_urlopen(req, context=None, timeout=6):
        class _Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        return _Resp(b"{}") if "8767/state.json" in req.full_url else _Resp(json.dumps(pending_resp).encode("utf-8"))

    for req_id, exp_val, expected_detail in (
        ("r-miss", None, "SAFE_HOME_EXPIRY_MISSING"),
        ("r-nan", float("nan"), "SAFE_HOME_EXPIRY_INVALID"),
        ("r-inf", float("inf"), "SAFE_HOME_EXPIRY_INVALID"),
        ("r-bool", True, "SAFE_HOME_EXPIRY_INVALID"),
        ("r-str", "bad", "SAFE_HOME_EXPIRY_INVALID"),
        ("r-big", 10**400, "SAFE_HOME_EXPIRY_INVALID"),
    ):
        spec = {"request_id": req_id, "strategy": "release_and_lift", "stop_generation": 0}
        if exp_val is not None:
            spec["expires_at"] = exp_val
        pending_resp["pending_safe_home_arms"] = {"arm_b": spec}
        qout = sync_mod.sync_cell_telemetry(
            "https://fleet.invalid", "tok", prep_dir=tmp_path, urlopen_fn=fake_urlopen, tls_verified=True,
            allow_safe_home=True, launch_auto_fold_fn=lambda *a, **k: launched.append(a) or {"started": True},
        )
        ack = json.loads((tmp_path / ".safe-home-acks.json").read_text(encoding="utf-8"))[req_id]
        assert qout.get("ok") is True and (tmp_path / ".safety-fence.json").is_file()
        assert ack["outcome"] == "skipped" and ack["detail"] == expected_detail
    assert launched == []

    # 2. cell_auto_fold.launch rejects missing/non-finite/bool/str/overflow expiry before wrapper invocation.
    import omx_incident
    import omx_incident_auto
    monkeypatch.setattr(omx_incident, "INCIDENTS", tmp_path / "inc")
    monkeypatch.setattr(omx_incident_auto, "note_event", lambda _e: None)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    cfg = tmp_path / "af.json"
    cfg.write_text(json.dumps({"arm_b": {"wrapper": "w", "config": "c", "library": "l", "site": "s", "roi": [0, 0, 10, 10], "cwd": str(cwd)}}), encoding="utf-8")
    link = SimpleNamespace(hold=lambda: SimpleNamespace(incident_ids=["inc-exp"]))
    run_calls = []
    for bad_exp, expected_why in (
        (None, "SAFE_HOME_EXPIRY_MISSING"),
        (float("nan"), "SAFE_HOME_EXPIRY_INVALID"),
        (float("inf"), "SAFE_HOME_EXPIRY_INVALID"),
        (True, "SAFE_HOME_EXPIRY_INVALID"),
        ("bad", "SAFE_HOME_EXPIRY_INVALID"),
        (10**400, "SAFE_HOME_EXPIRY_INVALID"),
    ):
        res = auto_fold_mod.launch(
            "arm_b", cfg, link=link, run=lambda *a, **k: run_calls.append(a),
            stage="park_only", request_id="req-bad", expires_at=bad_exp,
        )
        assert res["result"] == "skipped" and res["why"] == expected_why
    assert run_calls == [] and not (tmp_path / "inc" / "auto-fold-inc-exp-park.json").exists()

    # 3. Motion admission rejects missing/NaN/inf/expired/bool/str/overflow on Fleet fence, while legacy full still runs.
    from cell_auto_fold_stages import _safety_fence_error, run_cli_main
    import cell_pipeline  # noqa: F401
    monkeypatch.setattr(cell_pipeline, "FifoCell", lambda *_a: SimpleNamespace(act=lambda _c: {"ok": True}))
    monkeypatch.setenv("ROSY_RECOVERY_INCIDENT", "inc-cli-exp")
    lib_p, prm_p, cal_p, arm_cfg = tmp_path / "l.json", tmp_path / "p.json", tmp_path / "c.json", tmp_path / "a.json"
    lib_p.write_text(json.dumps({"chunks": {"home": [[0] * 6]}, "gripper_closed": 5.0, "fps": 30}), encoding="utf-8")
    prm_p.write_text(json.dumps({"schema": "rosy.omx-cell-params.v1", "params": {}}), encoding="utf-8")
    cal_p.write_text("{}", encoding="utf-8")
    arm_cfg.write_text(json.dumps({"io": str(tmp_path), "cameras": {}, "params_path": str(prm_p),
                                   "calibration_path": str(cal_p), "sites": {"s": {}}}), encoding="utf-8")
    fence_p = tmp_path / "f.json"
    fence_p.write_text(json.dumps({"human_hold": False, "stop_generation": 0, "updated_at": time.time()}), encoding="utf-8")
    out_p = tmp_path / "o.json"
    recover_calls = []
    for extra, reason in (
        ([], "SAFE_HOME_EXPIRY_MISSING"),
        (["--expires-at", "nan"], "SAFE_HOME_EXPIRY_INVALID"),
        (["--expires-at", "inf"], "SAFE_HOME_EXPIRY_INVALID"),
        (["--expires-at", str(time.time() - 5)], "SAFE_HOME_EXPIRED"),
    ):
        rc = run_cli_main(
            ["--arm", "arm_b", "--config", str(arm_cfg), "--library", str(lib_p), "--site", "s",
             "--roi", "0", "0", "10", "10", "--out", str(out_p), "--stop-generation", "0",
             "--safety-fence", str(fence_p), *extra],
            launch_fn=lambda *a, **k: {}, recover_fn=lambda *a, **k: recover_calls.append("bad") or {"result": "folded"},
            candidate_names_fn=lambda: ["park"], choice_key="auto_fold.candidate", schema="rosy.omx-auto-fold.v1",
        )
        assert rc == 3 and json.loads(out_p.read_text(encoding="utf-8"))["reason"] == reason
    for bad_exp in (True, "bad", 10**400):
        assert _safety_fence_error(
            SimpleNamespace(stage="park_only", safety_fence=str(fence_p), stop_generation=0, expires_at=bad_exp)
        ) == "SAFE_HOME_EXPIRY_INVALID"
    assert recover_calls == []
    rc_legacy = run_cli_main(
        ["--arm", "arm_b", "--config", str(arm_cfg), "--library", str(lib_p), "--site", "s",
         "--roi", "0", "0", "10", "10", "--out", str(out_p), "--stage", "full"],
        launch_fn=lambda *a, **k: {}, recover_fn=lambda *a, **k: {"schema": "rosy.omx-auto-fold.v1", "result": "folded"},
        candidate_names_fn=lambda: ["park"], choice_key="auto_fold.candidate", schema="rosy.omx-auto-fold.v1",
    )
    assert rc_legacy == 0 and json.loads(out_p.read_text(encoding="utf-8"))["result"] == "folded"


def test_incident_bound_home_requires_commissioned_capability_and_returns_late_exact_receipt(tmp_path, monkeypatch):
    import cell_auto_fold_stages as stages
    incident, rid = "a" * 32, "bound-r"
    cfg = tmp_path / "auto-fold.json"
    monkeypatch.setenv("ROSY_AUTO_FOLD_CONFIG", str(cfg))
    wrapper = tmp_path / "wrap.sh"
    wrapper.touch()
    wrapper.chmod(0o755)
    cfg.write_text(json.dumps({"arm_s": {"wrapper": str(wrapper), "cwd": str(tmp_path), "config": cfg.name,
                                         "library": cfg.name, "roi": [0, 0, 10, 10], "site": "s"}}))
    posted, launched = [], []
    def launch(arm, *, expected_incident_id, **kw):
        launched.append((arm, expected_incident_id, kw["stage"]))
        return {"started": True}
    spec = {"request_id": rid, "arm_id": "arm_s", "strategy": "auto_fold", "stop_generation": 1,
            "root_task_id": f"home-recovery:arm_s:{incident}", "expires_at": time.time() + 60}
    response = {"schema": "rosy.pipeline.cell-quality.v1", "human_hold": False, "safety_stop_generation": 1,
                "pending_safe_home_arms": {"arm_s": spec}}
    def fetch(req, **_):
        if "8767" in req.full_url:
            return io.BytesIO(b"{}")
        posted.append(json.loads(req.data))
        return io.BytesIO(json.dumps(response).encode())
    def sync():
        return sync_mod.sync_cell_telemetry("https://fleet.invalid", "tok", tmp_path, fetch, tls_verified=True,
                                            allow_safe_home=True, launch_auto_fold_fn=launch)
    sync()
    assert posted[-1]["incident_bound_home_arms"] == ["arm_s"] and posted[-1]["incident_bound_home"] is True
    assert launched == [("arm_s", incident, "full")]
    response["pending_safe_home_arms"] = {}
    sync()
    assert posted[-1]["safe_home_acks"][0]["outcome"] == "started"
    stages.write_req_result(tmp_path / "incidents", rid, "arm_s", "full",
                            {"result": "cleared", "bound_incident_id": incident,
                             "incident_id": incident, "evidence": {"incident_id": incident}})
    sync()
    assert posted[-1]["safe_home_acks"] == [{"request_id": rid, "arm_id": "arm_s", "incident_id": incident,
                                            "outcome": "completed", "cleared_incident_id": incident}]
    assert len(launched) == 1

    response["pending_safe_home_arms"] = {"arm_s": {**spec, "request_id": "wrong", "incident_id": "b" * 32}}
    sync()
    assert len(launched) == 1
    acks = json.loads((tmp_path / ".safe-home-acks.json").read_text())
    assert acks["wrong"]["detail"] == "HOME_RECOVERY_BINDING_INVALID"
    assert sync_mod._home_result_ack(tmp_path, "arm_b", rid, incident)["outcome"] == "failed"
    monkeypatch.setenv("ROSY_AUTO_FOLD_CONFIG", str(cfg.with_suffix(".pending")))
    cfg.rename(cfg.with_suffix(".pending"))
    sync()
    assert not posted[-1]["incident_bound_home"] and not posted[-1]["incident_bound_home_arms"]

    import omx_incident
    from core_common.protocol.arm_incident.home_recovery import HOME_RECOVERY_REASON
    hold = {"fleet_held": True, "fleet_reason": HOME_RECOVERY_REASON, "incident_ids": [incident]}
    monkeypatch.setattr(omx_incident, "status", lambda arm: hold if arm == "arm_s" else {})
    for root in (None, "historical-aborted-task"):
        response["pending_safe_home_arms"] = {"arm_s": {**spec, "root_task_id": root, "request_id": "old-r"}}
        sync()
        ack = json.loads((tmp_path / ".safe-home-acks.json").read_text())["old-r"]
        assert ack["outcome"] == "skipped" and ack["detail"] == "HOME_RECOVERY_BINDING_REQUIRED"
        assert len(launched) == 1
