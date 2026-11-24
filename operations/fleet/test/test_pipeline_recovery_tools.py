"""Tests for guarded LLM/VLA recovery tools, D-1048 staged homing API guards, and Codex R2/R3 hardening."""
from __future__ import annotations

import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _app(tmp_path, monkeypatch, *, role_principal=None, named_requester=True):
    from tools.sim.bay_departure_sim import build_world_261026_site_map
    from fleet.server.sitemap import pipeline_routes as routes

    site, graph, _ = build_world_261026_site_map()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(routes, "_storage_dir", lambda: tmp_path)
    app = FastAPI()
    if role_principal is not None:
        @app.middleware("http")
        async def _inject_principal(request, call_next):
            ov = request.headers.get("X-Test-Principal")
            if ov:
                pid, _, role = ov.partition(":")
                request.state.site_principal = SimpleNamespace(principal_id=pid, role=role)
            else:
                request.state.site_principal = role_principal
            return await call_next(request)
    if not named_requester:
        from fastapi import HTTPException
        def _deny(_p): raise HTTPException(403, detail={"code": "OPERATOR_NAME_REQUIRED"})
        app.state.trip_requester_guards = [_deny]
    else:
        app.state.trip_requester_guards = [lambda p: None]
    routes.install_pipeline_routes(
        app,
        site_maps=SimpleNamespace(
            active=lambda: (1, site, graph, None),
            rules=SimpleNamespace(active_rules=lambda: None),
        ),
        amr_evidence_fn=lambda task: (
            app.state._test_amr_evidence(task)
            if getattr(app.state, "_test_amr_evidence", None) is not None else None
        ),
    )
    return app, TestClient(app)


def _seed_cams(app, *, arm_id="arm_b", seq=10, fresh=True, age_s=0.4):
    cams = ("arm_s_top", "arm_s_wrist") if arm_id == "arm_s" else ("top", "side", f"{arm_id}_wrist")
    now = time.time() - age_s
    for c in cams:
        app.state.cell_camera_quality[c] = {"fresh": fresh, "sequence": seq, "receipt_age_s": 0.4, "recorded_at": now, "quality": {}}
    return {c: seq for c in cams}


def _seed_abort(app, task_id="t-ab-1", *, cell_id="cell_s", arm_id="arm_s", robot_id="rosy_46",
                err=None, reason="TASK_ABORTED", folded=True, fix=None, depth=0):
    now = time.time()
    app.state.omx_cell_states[cell_id] = {"phase": "ABORTED", "amr_motion_inhibited": True, **({"robot_id": robot_id} if robot_id else {})}
    app.state.arm_live_states[arm_id] = {"folded": folded, "updated_at": now, "folded_updated_at": now}
    _seed_cams(app, arm_id=arm_id, seq=10)
    app.state.omx_cell_tasks[task_id] = {
        "task_id": task_id, "cell_id": cell_id, "arm_id": arm_id, "robot_id": robot_id,
        "src_site": "pinky", "dst_site": "belt", "tier": 1, "status": "ABORTED",
        "fallback_chain_depth": depth, "receipt": {"reason": reason},
        "hardware_telemetry": {**({"error": err} if err else {}), "stop_event": {"folded": folded}},
        "stage_result": {**({"reach_fix": fix} if fix else {})}, "created_at": now - 5,
    }


def _seed_ready_amr(app, robot_id="rosy_46"):
    from tools.sim.bay_departure_sim import build_world_261026_site_map
    from fleet.pipeline import resolve_omx_cells
    site, graph, _ = build_world_261026_site_map()
    xy = resolve_omx_cells(site, graph)["cell_s"].station_xy
    app.state._test_amr_evidence = lambda task: (
        None if task.get("robot_id") != robot_id else {
            "robot_id": task["robot_id"], "cell_id": task["cell_id"],
            "wheel_brake_locked": True, "bed_ready": True, "v_cmd_mps": 0.0,
            "observed_at": time.time(), "pose": {"x": xy[0], "y": xy[1], "yaw": 0.0},
        }
    )


def test_raw_keys_role_cas_refusal_replay_and_rollback(tmp_path, monkeypatch):
    app, client = _app(tmp_path, monkeypatch, role_principal=SimpleNamespace(principal_id="svc-bot", role="service"))
    _seed_abort(app, "t-root", folded=True, robot_id=None)
    sha = client.get("/api/fleet/pipeline/recovery-tools").json()["active_failures"][0]["context_sha256"]

    r = client.post("/api/fleet/pipeline/recovery-tools/invoke", json={
        "tool_name": "safe_fold_home", "arguments": {"pose": [0, 0, 0]}, "caller_kind": "llm_agent",
        "request_id": "req-raw", "expected_context_sha256": sha, "root_task_id": "t-root", "rationale": "bad",
    })
    assert r.status_code == 422 and r.json()["detail"]["code"] == "FORBIDDEN_RAW_COMMAND_KEY"

    spoof = client.post("/api/fleet/pipeline/recovery-tools/invoke", json={
        "tool_name": "safe_fold_home", "arguments": {}, "caller_kind": "operator",
        "request_id": "req-spoof", "expected_context_sha256": sha, "root_task_id": "t-root", "rationale": "spoof",
    })
    assert spoof.status_code == 403 and spoof.json()["detail"]["code"] == "CALLER_KIND_ROLE_MISMATCH"

    mm_payload = {
        "tool_name": "enqueue_displaced_recovery", "arguments": {"site": "belt_far", "robot_id": "rosy_99"},
        "caller_kind": "llm_agent", "request_id": "req-mm", "expected_context_sha256": sha,
        "root_task_id": "t-root", "rationale": "inject robot_id",
    }
    mm1 = client.post("/api/fleet/pipeline/recovery-tools/invoke", json=mm_payload)
    mm2 = client.post("/api/fleet/pipeline/recovery-tools/invoke", json=mm_payload)
    assert mm1.status_code == 409 and mm2.status_code == 409 and mm2.json()["detail"]["code"] == "TARGET_MISMATCH_AFTER_CAS"

    # Service cannot enqueue real displaced/ACT fallback without operator approval (403), while vla_shadow succeeds.
    _seed_abort(app, "t-svc-gate", folded=True, robot_id="rosy_46")
    sha_sg = next(f for f in client.get("/api/fleet/pipeline/recovery-tools").json()["active_failures"] if f["root_task_id"] == "t-svc-gate")["context_sha256"]
    svc_disp = client.post("/api/fleet/pipeline/recovery-tools/invoke", json={
        "tool_name": "enqueue_displaced_recovery", "arguments": {"site": "belt_far"}, "caller_kind": "llm_agent",
        "request_id": "req-svc-disp", "expected_context_sha256": sha_sg, "root_task_id": "t-svc-gate", "rationale": "service try",
    })
    assert svc_disp.status_code == 403 and svc_disp.json()["detail"]["code"] == "OPERATOR_APPROVAL_REQUIRED_FOR_FALLBACK_ENQUEUE"
    svc_act = client.post("/api/fleet/pipeline/recovery-tools/invoke", json={
        "tool_name": "enqueue_vla_act_fallback", "arguments": {"mode": "act", "max_chunks": 2}, "caller_kind": "vla_agent",
        "request_id": "req-svc-act", "expected_context_sha256": sha_sg, "root_task_id": "t-svc-gate", "rationale": "service act",
    })
    assert svc_act.status_code == 403
    svc_sh = client.post("/api/fleet/pipeline/recovery-tools/invoke", json={
        "tool_name": "enqueue_vla_act_fallback", "arguments": {"mode": "vla_shadow", "max_chunks": 2}, "caller_kind": "vla_agent",
        "request_id": "req-svc-sh", "expected_context_sha256": sha_sg, "root_task_id": "t-svc-gate", "rationale": "shadow proposal",
    })
    assert svc_sh.status_code == 200 and svc_sh.json()["result"]["vla_executed"] is False

    # Operator displaced recovery sets requires_presence_confirm=True -> /claim enforces D-911 presence even when AMR ready.
    app2, client2 = _app(tmp_path, monkeypatch, role_principal=SimpleNamespace(principal_id="op-kim", role="operator"))
    _seed_abort(app2, "t-disp", folded=True, robot_id="rosy_46")
    _seed_ready_amr(app2, "rosy_46")
    sha2 = client2.get("/api/fleet/pipeline/recovery-tools").json()["active_failures"][0]["context_sha256"]
    ok = client2.post("/api/fleet/pipeline/recovery-tools/invoke", json={
        "tool_name": "enqueue_displaced_recovery", "arguments": {"site": "belt_far"}, "caller_kind": "operator",
        "request_id": "req-d", "expected_context_sha256": sha2, "root_task_id": "t-disp", "rationale": "recover",
    })
    assert ok.status_code == 200 and ok.json()["result"]["requires_presence_confirm"] is True
    tid = ok.json()["result"]["task"]["task_id"]
    app2.state.omx_cell_states["cell_s"] = {"phase": "RELEASED", "amr_motion_inhibited": False}
    monkeypatch.setenv("ROSY_FLEET_CELL_OWNERS", "cell_s=omx-svc-s")
    claim = client2.post("/api/fleet/pipeline/cell-tasks/claim", headers={"X-Test-Principal": "omx-svc-s:service"}, json={"cell_id": "cell_s", "task_id": tid}).json()
    assert claim["claimed"] is False and claim["reason"] == "PRESENCE_CONFIRMATION_REQUIRED"

    # Depth>=1 block and ledger save rollback on disk fault.
    _seed_abort(app2, "t-deep", folded=False, depth=1)
    from fleet.server.sitemap import pipeline_routes as routes
    monkeypatch.setattr(routes, "write_ledger", lambda *_a, **_k: (_ for _ in ()).throw(OSError("disk full")))
    f_deep = next(f for f in client2.get("/api/fleet/pipeline/recovery-tools").json()["active_failures"] if f["root_task_id"] == "t-deep")
    assert f_deep["eligible_tools"]["enqueue_vla_act_fallback"]["reason"] == "FALLBACK_DEPTH_EXCEEDED"
    try:
        client2.post("/api/fleet/pipeline/recovery-tools/invoke", json={
            "tool_name": "safe_fold_home", "arguments": {"arm_id": "arm_s", "strategy": "auto_fold"},
            "caller_kind": "operator", "request_id": "req-rb", "expected_context_sha256": f_deep["context_sha256"],
            "root_task_id": "t-deep", "rationale": "rollback test",
        })
    except Exception:
        pass
    assert "arm_s" not in app2.state.pending_safe_home_arms


def test_situational_d1048_staged_homing_owner_auth_and_3cam_guards(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSY_FLEET_CELL_OWNERS", "cell_s=omx-owner-s;cell_ab=omx-owner-ab")
    app, client = _app(tmp_path, monkeypatch, role_principal=SimpleNamespace(principal_id="op-kim", role="operator"))
    _seed_abort(app, "t-armb", cell_id="cell_ab", arm_id="arm_b", robot_id="rosy_46", err="FOLD_READBACK_MISSING", folded=False, fix=[0.1, 0.0])

    app.state.omx_cell_tasks["t-complete-fold"] = {
        "task_id": "t-complete-fold", "cell_id": "cell_ab", "arm_id": "arm_b", "robot_id": "rosy_46",
        "robot_kind": "pinky", "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0},
        "src_site": "belt", "dst_site": "pallet", "tier": 1, "status": "RUNNING", "handoff_lease_id": "L1",
    }
    client.post("/api/fleet/pipeline/cell-tasks/t-complete-fold/complete", json={
        "phase": "ABORTED", "handoff_lease_id": "L1", "stage_result": {"reach_fix": [0.1, 0.0]},
        "hardware_telemetry": {"error": "FOLD_READBACK_MISSING", "stop_event": {"folded": False}},
    })
    assert "rosy_46" not in app.state.repark_requests

    f = next(x for x in client.get("/api/fleet/pipeline/recovery-tools").json()["active_failures"] if x["root_task_id"] == "t-armb")
    assert client.post("/api/fleet/pipeline/recovery-tools/invoke", json={
        "tool_name": "safe_fold_home", "arguments": {"arm_id": "arm_b", "strategy": "release_and_lift"},
        "caller_kind": "operator", "request_id": "step-lift", "expected_context_sha256": f["context_sha256"],
        "root_task_id": "t-armb", "rationale": "lift",
    }).status_code == 200

    # Non-owner & cross-cell owner (cell_s) cannot submit arm_b acks or cell_ab telemetry; cell_ab owner succeeds.
    from fleet.server.pipeline_recovery_policy import effective_stop_fence

    p_no = tmp_path / "no"
    p_no.mkdir()
    app_no, client_no = _app(p_no, monkeypatch, role_principal=SimpleNamespace(principal_id="omx-owner-s", role="service"))
    app_no.state.pending_safe_home_arms["arm_b"] = {
        "request_id": "req-x", "root_task_id": "t-armb", "strategy": "release_and_lift",
        "stop_generation": effective_stop_fence(app_no.state)[1], "expires_at": time.time() + 60,
    }
    app_no.state.arm_live_states["arm_b"] = {"folded": False}
    client_no.post("/api/fleet/pipeline/cell-quality", json={
        "cameras": {"top": {"fresh": True, "sequence": 99}},
        "arm_states": {"arm_b": {"folded": True}},
        "safe_home_acks": [{"arm_id": "arm_b", "request_id": "req-x", "outcome": "risen_for_visual_verify"}],
    })
    assert "arm_b" in app_no.state.pending_safe_home_arms
    assert app_no.state.arm_live_states["arm_b"]["folded"] is False
    assert "top" not in app_no.state.cell_camera_quality

    p_own = tmp_path / "own"
    p_own.mkdir()
    app_own, client_own = _app(p_own, monkeypatch, role_principal=SimpleNamespace(principal_id="omx-owner-ab", role="service"))
    app_own.state.pending_safe_home_arms["arm_b"] = {
        "request_id": "req-x", "root_task_id": "t-armb", "strategy": "release_and_lift",
        "stop_generation": effective_stop_fence(app_own.state)[1], "expires_at": time.time() + 60,
    }
    client_own.post("/api/fleet/pipeline/cell-quality", json={
        "safe_home_acks": [{"arm_id": "arm_b", "request_id": "req-x", "outcome": "risen_for_visual_verify"}]
    })
    assert "arm_b" not in app_own.state.pending_safe_home_arms

    # Resume primary app flow: 'started' keeps pending lock; terminal ack unlocks lift visual check and blocks auto_fold.
    client.post("/api/fleet/pipeline/cell-quality", json={
        "safe_home_acks": [{"arm_id": "arm_b", "request_id": "step-lift", "strategy": "auto_fold", "outcome": "started"}]
    })
    assert "arm_b" in app.state.pending_safe_home_arms
    _seed_cams(app, arm_id="arm_b", seq=12)
    client.post("/api/fleet/pipeline/cell-quality", json={
        "safe_home_acks": [{"arm_id": "arm_b", "request_id": "step-lift", "outcome": "risen_for_visual_verify"}]
    })
    f2 = next(x for x in client.get("/api/fleet/pipeline/recovery-tools").json()["active_failures"] if x["root_task_id"] == "t-armb")
    assert f2["homing_strategies"]["auto_fold"]["reason"] == "HOMING_LOCKED:AWAITING_LIFT_VISUAL_VERIFY"

    _seed_cams(app, arm_id="arm_b", seq=15)
    sha2b = next(x for x in client.get("/api/fleet/pipeline/recovery-tools").json()["active_failures"] if x["root_task_id"] == "t-armb")["context_sha256"]
    assert client.post("/api/fleet/pipeline/recovery-tools/invoke", json={
        "tool_name": "record_visual_checkpoint",
        "arguments": {"arm_id": "arm_b", "stage": "after_lift", "verdict": "CLEAR", "cargo_detached": True,
                      "gripper_open": True, "overhead_clear": True, "cameras_checked": {"top": 15, "side": 15, "arm_b_wrist": 15},
                      "observation_summary": "3 cams clear"},
        "caller_kind": "operator", "request_id": "v-ok-lift", "expected_context_sha256": sha2b,
        "root_task_id": "t-armb", "rationale": "3cam ok",
    }).status_code == 200
    sha3 = next(x for x in client.get("/api/fleet/pipeline/recovery-tools").json()["active_failures"] if x["root_task_id"] == "t-armb")["context_sha256"]
    assert client.post("/api/fleet/pipeline/recovery-tools/invoke", json={
        "tool_name": "safe_fold_home", "arguments": {"arm_id": "arm_b", "strategy": "guarded_slow_park"},
        "caller_kind": "operator", "request_id": "step-park", "expected_context_sha256": sha3,
        "root_task_id": "t-armb", "rationale": "park",
    }).status_code == 200
    _seed_cams(app, arm_id="arm_b", seq=18)
    client.post("/api/fleet/pipeline/cell-quality", json={
        "safe_home_acks": [{"arm_id": "arm_b", "request_id": "step-park", "outcome": "completed"}]
    })
    # POST /arm-holds/clear MUST reject 409 before after_park visual+folded verification passes!
    premature_clr = client.post("/api/fleet/pipeline/arm-holds/clear", json={"arm_id": "arm_b", "note": "too early"})
    assert premature_clr.status_code == 409 and premature_clr.json()["detail"]["code"] == "STAGED_HOMING_VISUAL_VERIFY_REQUIRED"

    _seed_cams(app, arm_id="arm_b", seq=20)
    app.state.arm_live_states["arm_b"] = {"folded": True, "updated_at": time.time(), "folded_updated_at": time.time()}
    sha4 = next(x for x in client.get("/api/fleet/pipeline/recovery-tools").json()["active_failures"] if x["root_task_id"] == "t-armb")["context_sha256"]
    v_park = client.post("/api/fleet/pipeline/recovery-tools/invoke", json={
        "tool_name": "record_visual_checkpoint",
        "arguments": {"arm_id": "arm_b", "stage": "after_park", "verdict": "FOLDED_HOME", "cargo_detached": True,
                      "gripper_open": True, "overhead_clear": True, "cameras_checked": {"top": 20, "side": 20, "arm_b_wrist": 20},
                      "observation_summary": "folded"},
        "caller_kind": "operator", "request_id": "v-park", "expected_context_sha256": sha4,
        "root_task_id": "t-armb", "rationale": "verify park",
    })
    assert v_park.status_code == 200 and v_park.json()["result"]["ready_for_hold_clear"] is True
    # Pruned running stage -> SKIPPED still blocks /arm-holds/clear AND blocks auto_fold fallback!
    p_sk = tmp_path / "sk"
    p_sk.mkdir()
    app_sk, client_sk = _app(p_sk, monkeypatch, role_principal=SimpleNamespace(principal_id="op-kim", role="operator"))
    _seed_abort(app_sk, "t-sk", cell_id="cell_ab", arm_id="arm_b", robot_id="rosy_46", folded=False)
    app_sk.state.pending_safe_home_arms["arm_b"] = {
        "request_id": "sk-1", "root_task_id": "t-sk", "arm_id": "arm_b",
        "strategy": "guarded_slow_park", "expires_at": time.time() - 10, "stop_generation": 0,
    }
    app_sk.state.pipeline_homing_sessions["t-sk"] = {
        "root_task_id": "t-sk", "arm_id": "arm_b", "stage": "RUNNING_GUARDED_SLOW_PARK", "last_strategy": "guarded_slow_park",
    }
    client_sk.post("/api/fleet/pipeline/cell-quality", json={})
    assert app_sk.state.pipeline_homing_sessions["t-sk"]["stage"] == "SKIPPED"
    sk_clr = client_sk.post("/api/fleet/pipeline/arm-holds/clear", json={"arm_id": "arm_b", "note": "clear skipped"})
    assert sk_clr.status_code == 409 and sk_clr.json()["detail"]["code"] == "STAGED_HOMING_VISUAL_VERIFY_REQUIRED"
    sk_f = next(x for x in client_sk.get("/api/fleet/pipeline/recovery-tools").json()["active_failures"] if x["root_task_id"] == "t-sk")
    assert sk_f["homing_strategies"]["auto_fold"]["reason"] == "HOMING_LOCKED:SKIPPED"

    # Mismatched AND unknown ("done") ack outcomes on guarded_slow_park escalate to HOLD_GUARD_TRIPPED.
    for out_str, rid in (("risen_for_visual_verify", "sk-bad"), ("done", "sk-unk")):
        app_sk.state.pending_safe_home_arms["arm_b"] = {
            "request_id": rid, "root_task_id": "t-sk", "arm_id": "arm_b", "strategy": "guarded_slow_park",
            "stop_generation": effective_stop_fence(app_sk.state)[1], "expires_at": time.time() + 60,
        }
        client_sk.post("/api/fleet/pipeline/cell-quality", json={
            "safe_home_acks": [{"arm_id": "arm_b", "request_id": rid, "outcome": out_str}]
        })
        assert "arm_b" not in app_sk.state.pending_safe_home_arms
        assert app_sk.state.pipeline_homing_sessions["t-sk"]["stage"] == "HOLD_GUARD_TRIPPED"

    assert client.post("/api/fleet/pipeline/arm-holds/clear", json={"arm_id": "arm_b", "note": "verified folded"}).status_code == 200


def test_pinky_reroute_preserves_root(tmp_path, monkeypatch):
    app, client = _app(tmp_path, monkeypatch, role_principal=SimpleNamespace(principal_id="op-kim", role="operator"))
    app.state.pinky_tasks["pt-1"] = {"task_id": "pt-1", "robot_id": "rosy_46", "status": "FAILED"}
    monkeypatch.setenv("ROSY_FLEET_PINKY_TASK_DISPATCH", "1")
    fp = next(f for f in client.get("/api/fleet/pipeline/recovery-tools").json()["active_failures"] if f["root_task_id"] == "pinky:pt-1")
    rr = client.post("/api/fleet/pipeline/recovery-tools/invoke", json={
        "tool_name": "dispatch_pinky_reroute", "arguments": {"target_place": "S3"}, "caller_kind": "operator",
        "request_id": "pk-1", "expected_context_sha256": fp["context_sha256"],
        "root_task_id": "pinky:pt-1", "rationale": "reroute once",
    })
    assert rr.status_code == 200
    pid = rr.json()["result"]["pinky_task"]["task_id"]
    app.state.pinky_tasks[pid]["status"] = "FAILED"
    fp2 = next(f for f in client.get("/api/fleet/pipeline/recovery-tools").json()["active_failures"] if f["root_task_id"] == "pinky:pt-1")
    assert fp2["eligible_tools"]["dispatch_pinky_reroute"]["reason"] == "RECOVERY_CAP_EXCEEDED"

    app_u, client_u = _app(tmp_path, monkeypatch, role_principal=SimpleNamespace(principal_id="anon", role="operator"), named_requester=False)
    app_u.state.pinky_tasks["pt-u"] = {"task_id": "pt-u", "robot_id": "rosy_46", "status": "FAILED"}
    fu = next(f for f in client_u.get("/api/fleet/pipeline/recovery-tools").json()["active_failures"] if f["root_task_id"] == "pinky:pt-u")
    den = client_u.post("/api/fleet/pipeline/recovery-tools/invoke", json={
        "tool_name": "dispatch_pinky_reroute", "arguments": {"target_place": "S3"}, "caller_kind": "operator",
        "request_id": "pk-u", "expected_context_sha256": fu["context_sha256"],
        "root_task_id": "pinky:pt-u", "rationale": "unnamed",
    })
    assert den.status_code == 403 and den.json()["detail"]["code"] == "REQUESTER_NOT_NAMED"
