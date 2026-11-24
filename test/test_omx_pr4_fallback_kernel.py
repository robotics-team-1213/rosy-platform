"""PR-4 tests: 9-verb fallback kernel, VLM convergence/TOCTOU fence, and ACT failure classification."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
OMX = ROOT / "deploy/robot/omx"
if str(OMX) not in sys.path:
    sys.path.insert(0, str(OMX))
if str(ROOT / "contracts/foundation") not in sys.path:
    sys.path.insert(0, str(ROOT / "contracts/foundation"))

import cell_choices  # noqa: E402
import cell_diagnose as dg  # noqa: E402
import cell_executor as ce  # noqa: E402
import cell_failure_context as cfc  # noqa: E402
import cell_failure_scenarios as cfs  # noqa: E402
import cell_job_api as api  # noqa: E402
import cell_job_client as jc  # noqa: E402
import cell_recovery as rec  # noqa: E402
import cell_requests as reqs  # noqa: E402
import cell_task_act as cta  # noqa: E402
import cell_vlm_facts as vfacts  # noqa: E402
import cell_vlm_orchestrator as orch  # noqa: E402

JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 16 + b"\xff\xd9"


def _sample_bundle(
    *,
    bundle_id: str = "20261123T050000Z-arm_a-stop",
    arm_id: str = "arm_a",
    kind: str = "stop",
    executor_mode: str = "ik_auto_pick",
    attempt_cause: str = "lift_stall",
    cell_state_gen: int = 3,
    repeat_unknown_tripped: bool = False,
    created_at_s: float | None = None,
    ttl_s: float = 30.0,
) -> dict:
    meas = {
        "outcome": {"attempt_cause": attempt_cause, "result_text": f"stopped: {attempt_cause}"},
        "incident": {"local_held": False, "fleet_held": False, "windup_hits_count": 0, "caps_restored": True},
        "holding_and_fold": {"live_fold": {"folded": True}},
        "pose_and_health": {"arm_pose_state": "folded_home"},
    }
    spat = {
        "sites": {"source": "belt", "dest": "yard:r1-s1-t1", "is_amr_bed": False},
        "calibration": {"top_shift_px": {"moved": False, "max_px": 1.0, "limit_px": 6.0}, "missing_map": []},
        "workspace_occupancy": {"arms": {}, "fleet_safety": {"active_estop": False, "human_detected": False}},
    }
    vis = {
        "camera_manifest": {"top": {"status": "ok", "required_for_mode": True}},
        "frames": [{"camera": "top", "file": "top-00.jpg", "t_rel_s": -0.2, "source_seq": 7, "source_stamp": 100.0}],
    }
    return cfc.build_bundle(
        bundle_id=bundle_id,
        kind=kind,
        arm_id=arm_id,
        cell_id="cell_ab" if arm_id in ("arm_a", "arm_b") else "cell_s",
        executor_mode=executor_mode,
        correlation={"task_id": "t-1"},
        generation={"cell_state_gen": cell_state_gen},
        measurement=meas,
        spatial=spat,
        visual=vis,
        history={"repeat_unknown_tripped": repeat_unknown_tripped},
        created_at_s=time.time() if created_at_s is None else created_at_s,
        ttl_s=ttl_s,
        auto_fold_armed=True,
    )


def test_policy_diagnose_classify_and_scenarios_complete():
    cases = [
        ("policy: timing_late", "", "policy_timing_late"),
        ("policy: jaw_gate", "", "policy_jaw_gate"),
        ("policy: chunk_refused", "", "policy_chunk_refused"),
        ("policy: zone_unverified", "", "policy_zone_unverified"),
        ("policy: stalled", "", "policy_stalled"),
        ("policy: contact", "", "policy_contact"),
        ("policy: missing_calibration", "", "policy_missing_calibration"),
        ("refused", "policy chunk is late, all action times passed", "policy_timing_late"),
        ("act_exit_1", "model calibration invalid", "policy_missing_calibration"),
        ("stopped: released after a stop", "", "lift_stall"),
    ]
    for raw, reason, expected in cases:
        got = dg.classify_failure(raw, reason)
        assert got["cause"] == expected
        assert got["stratum"] == ("human_only" if expected != "lift_stall" else "recoverable")
    bundle = _sample_bundle(kind="policy_fail", executor_mode="act_paced", attempt_cause="policy_jaw_gate")
    assert dg.classify_failure(bundle)["cause"] == "policy_jaw_gate"
    hyb = dg.classify_failure("stopped: unexpected", "", exec_mode="hybrid")
    assert hyb["cause"] == "policy_chunk_refused" and hyb["stratum"] == "human_only" and hyb["requires_human_operator"] is True
    summary = cfs.run_all(cfs.SCENARIOS, workers=4)
    assert summary["failed"] == [] and summary["passed"] == len(cfs.SCENARIOS)


def test_select_fallback_menu_limits_and_escalate_to_request(tmp_path):
    assert rec.MAX_AI_FALLBACK_PER_TASK == 2
    assert len(rec.FALLBACK_VERBS) == 9
    b = _sample_bundle(attempt_cause="lift_stall")
    sel_ok = rec.select_fallback(b, proposed_verb="retry_ik_slower", fallback_chain_depth=0)
    assert sel_ok["verb"] == "retry_ik_slower" and sel_ok["escalate"] is True and sel_ok["requires_human_operator"] is True

    # Auto selection obeys measurement why preference (too_fast -> retry_ik_slower, blocked -> align_push).
    assert rec.select_fallback(b, why_row={"by": "measurement", "hypothesis": "too_fast"})["verb"] == "retry_ik_slower"
    assert rec.select_fallback(b, why_row={"by": "measurement", "hypothesis": "blocked"})["verb"] == "align_push"

    # Depth limit & repeat_unknown always escalate.
    assert rec.select_fallback(b, proposed_verb="retry_ik_slower", fallback_chain_depth=2)["verb"] == "escalate_human"
    assert rec.select_fallback(b, proposed_verb="retry_ik_slower", fallback_chain_depth=-1)["verb"] == "escalate_human"
    assert rec.select_fallback(b, proposed_verb="retry_ik_slower", fallback_chain_depth=True)["verb"] == "escalate_human"
    b_rep = _sample_bundle(attempt_cause="misaligned", repeat_unknown_tripped=True)
    assert rec.select_fallback(b_rep, proposed_verb="align_push")["verb"] == "escalate_human"
    assert rec.select_fallback(b, proposed_verb="invented_verb")["verb"] == "escalate_human"

    # Auto selection on policy bundle picks propose_ik_fallback_for_policy (top-level executor_mode).
    b_pol = _sample_bundle(kind="policy_fail", executor_mode="act_paced", attempt_cause="policy_timing_late")
    assert rec.select_fallback(b_pol)["verb"] == "propose_ik_fallback_for_policy"
    sel_pol = rec.select_fallback(b_pol, proposed_verb="propose_ik_fallback_for_policy")
    assert sel_pol["verb"] == "propose_ik_fallback_for_policy" and sel_pol["tier"] == 1 and sel_pol["requires_human_operator"] is True

    # Tampered SHA or forged/re-signed menu cannot weaken Tier-1 gates.
    forged = json.loads(json.dumps(b_pol))
    for item in forged["history_and_constraints"]["allowed_fallback_menu"]:
        if item["verb"] == "propose_ik_fallback_for_policy":
            item["tier"] = 2
            item["requires_human_operator"] = False
    assert rec.select_fallback(forged, proposed_verb="propose_ik_fallback_for_policy")["verb"] == "escalate_human"
    forged["context_sha256"] = cfc.canonical_sha256(forged)
    resigned = rec.select_fallback(forged, proposed_verb="propose_ik_fallback_for_policy")
    assert resigned["tier"] == 1 and resigned["requires_human_operator"] is True

    opened = rec.escalate_to_request(b, selection=sel_ok, reason="lift stalled repeatedly", root=tmp_path)
    opened_again = rec.escalate_to_request(b, selection=sel_ok, reason="duplicate call", root=tmp_path)
    assert opened_again["id"] == opened["id"]
    loaded = reqs.load(opened["id"], root=tmp_path)
    assert loaded["kind"] == "check" and loaded["bundle_id"] == b["bundle_id"] and loaded["selected_verb"] == "retry_ik_slower"
    reqs.answer(opened["id"], result="pass", by="human_op", root=tmp_path)
    reopened = rec.escalate_to_request(b, selection=sel_ok, reason="re-escalated after answered", root=tmp_path)
    assert reopened["id"] != opened["id"] and reopened["status"] == "open"


def _make_api_client(tmp_path, monkeypatch, *, gen: int = 1, bundle: dict | None = None, held: bool = False):
    wd = tmp_path / "cell"
    wd.mkdir(exist_ok=True)
    bundle_root = tmp_path / "bundles"
    if bundle is not None:
        cfc.write_bundle(bundle_root, bundle, {"top-00.jpg": JPG})
    monkeypatch.setattr(api, "_whole_cell_lock_held", lambda *_a, **_k: False)
    monkeypatch.setattr(api, "_session_lock_held", lambda *_a, **_k: False)
    monkeypatch.setattr(api, "_check_depth_lock_held", lambda *_a, **_k: False)
    runner = api.Runner(
        wd, lock_dir=wd, bundle_root=bundle_root,
        incident_check_fn=lambda _a: "held" if held else None,
        fleet_safety_check_fn=lambda _a: {"online": True, "blocked": False},
    )
    while runner.state_gen() < gen:
        runner._state_gen.bump()
    srv = api.make_server("127.0.0.1", 0, "secret-tok", runner)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    monkeypatch.setattr(vfacts, "collect_frames", lambda _c, views=(): ([], []))
    return srv, runner, jc.CellJobClient(f"http://127.0.0.1:{srv.server_address[1]}", token="secret-tok")


def test_propose_fallback_schema_and_toctou_fence(tmp_path, monkeypatch):
    bundle = _sample_bundle(cell_state_gen=2)
    srv, runner, client = _make_api_client(tmp_path, monkeypatch, gen=2, bundle=bundle)
    try:
        seen_schemas = []

        def vlm_ok(prompt, images, schema):
            seen_schemas.append(schema)
            assert images and "lift_stall" in prompt
            return {"verb": "home_unwedge", "reason": "fold arm safely first"}

        res = orch.propose_fallback(client, vlm_ok, arm="arm_a", request_root=tmp_path / "reqs")
        assert res["status"] == "proposed" and res["verb"] == "home_unwedge"
        assert seen_schemas[0].get("strict") is True
        assert set(seen_schemas[0]["properties"]["verb"]["enum"]) <= set(rec.FALLBACK_VERBS)

        # Depth limit and VLM failure fail closed without permitting unsafe verbs.
        vlm_called = False

        def vlm_should_not_run(*_a):
            nonlocal vlm_called
            vlm_called = True
            return {"verb": "home_unwedge", "reason": "should not run"}

        esc_depth = orch.propose_fallback(client, vlm_should_not_run, arm="arm_a", request_root=tmp_path / "reqs_d", fallback_chain_depth=2)
        assert esc_depth["status"] == "escalated" and vlm_called is False

        esc_err = orch.propose_fallback(client, lambda *_a: (_ for _ in ()).throw(RuntimeError("timeout")), arm="arm_a", request_root=tmp_path / "reqs_e")
        assert esc_err["status"] == "escalated" and esc_err["verb"] == "escalate_human"

        # Invalid/NaN/bool cell_state_gen or observed_at, dirty/active arm, 5s max_age cap, or peer A/B faults fail closed.
        now = time.time()
        ok_nan, _, _ = vfacts.verify_context_fence(bundle, {"schema": "rosy.cell-readiness.v1", "observed_at": float("nan"), "cell_state_gen": 2, "arms": {"arm_a": {}}})
        ok_bool, _, _ = vfacts.verify_context_fence(bundle, {"schema": "rosy.cell-readiness.v1", "observed_at": now, "cell_state_gen": True, "arms": {"arm_a": {}}})
        assert ok_nan is False and ok_bool is False
        ok_old, _, _ = vfacts.verify_context_fence(bundle, {"schema": "rosy.cell-readiness.v1", "observed_at": now - 6.0, "max_age_s": 30.0, "cell_state_gen": 2, "arms": {"arm_a": {}}})
        ok_dirty, _, _ = vfacts.verify_context_fence(bundle, {"schema": "rosy.cell-readiness.v1", "observed_at": now, "cell_state_gen": 2, "arms": {"arm_a": {"dirty": True}}})
        ok_job, _, _ = vfacts.verify_context_fence(bundle, {"schema": "rosy.cell-readiness.v1", "observed_at": now, "cell_state_gen": 2, "arms": {"arm_a": {"active_job_id": "j2"}}})
        ok_peer_held, _, _ = vfacts.verify_context_fence(bundle, {"schema": "rosy.cell-readiness.v1", "observed_at": now, "cell_state_gen": 2, "arms": {"arm_a": {}, "arm_b": {"incident_held": True}}})
        ok_peer_unfold, _, _ = vfacts.verify_context_fence(bundle, {"schema": "rosy.cell-readiness.v1", "observed_at": now, "cell_state_gen": 2, "arms": {"arm_a": {}, "arm_b": {"session_lock_held": True, "folded": False}}})
        assert not any((ok_old, ok_dirty, ok_job, ok_peer_held, ok_peer_unfold))

        # Bundle replacement on /failures/latest during VLM call triggers STALE_FAILURE_CONTEXT.
        def vlm_then_new_bundle(prompt, images, schema):
            b2 = _sample_bundle(bundle_id="20261123T050001Z-arm_a-stop", cell_state_gen=2)
            cfc.write_bundle(tmp_path / "bundles", b2, {"top-00.jpg": JPG})
            return {"verb": "home_unwedge", "reason": "stale bundle"}

        stale_b = orch.propose_fallback(client, vlm_then_new_bundle, arm="arm_a", request_root=tmp_path / "reqs_b")
        assert stale_b["status"] == "stale" and stale_b["reason"] == "STALE_FAILURE_CONTEXT"

        # Drift between VLM call and post-VLM readiness fence -> STALE_FAILURE_CONTEXT.
        def vlm_then_drift(prompt, images, schema):
            runner._state_gen.bump()
            return {"verb": "home_unwedge", "reason": "late reply"}

        stale = orch.propose_fallback(client, vlm_then_drift, arm="arm_a", request_root=tmp_path / "reqs2")
        assert stale["status"] == "stale" and stale["reason"] == "STALE_FAILURE_CONTEXT"
    finally:
        srv.shutdown()
        srv.server_close()


def test_verify_job_outcome_rejects_fake_exit_zero_success(tmp_path, monkeypatch):
    client = SimpleNamespace(readiness=lambda: {"schema": "rosy.cell-readiness.v1", "arms": {"arm_a": {"folded": None}}})
    monkeypatch.setattr(vfacts, "query_incident", lambda *_a, **_k: {"arm": "arm_a", "held": False})

    bad_cases = [
        ("auto_pick", {"exit": 0, "log": json.dumps({"result": "stopped: contact"})}, False),
        ("auto_pick", {"exit": 0, "log": json.dumps({"result": "placed"})}, False),
        ("cell_policy_drive", {"exit": 0, "log": json.dumps({"result": "chunks_done"})}, False),
        ("home", {"exit": 0, "log": json.dumps({"ok": False})}, False),
        ("cell_policy_drive", {"exit": 0, "log": json.dumps({"result": "released", "parked": False, "took_one": True})}, False),
        ("cell_policy_drive", {"exit": 0, "log": json.dumps({"result": "released", "took_one": False})}, False),
        ("cell_policy_drive", {"exit": 0, "log": json.dumps({"result": "released", "zone_verification": {"verified": False}})}, False),
        ("cell_policy_drive", {"exit": 0, "log": ""}, False),
        ("cell_policy_drive", {"exit": 0, "log": json.dumps({"result": "released", "took_one": True})}, True),
    ]
    for job, res, held_post in bad_cases:
        monkeypatch.setattr(vfacts, "query_incident", lambda *_a, h=held_post, **_k: {"arm": "arm_a", "held": h, "reason": "hold" if h else ""})
        status, ver = vfacts.verify_job_outcome(client, job, "arm_a", res, collect_facts=True, dry_run=False)
        assert status == "failed", (job, res, ver)

    monkeypatch.setattr(vfacts, "query_incident", lambda *_a, **_k: {"arm": "arm_a", "held": False})
    # collect_facts=False still enforces post-motion readiness/incident safety checks.
    st_cf_false, _ = vfacts.verify_job_outcome(
        client, "auto_pick", "arm_a",
        {"exit": 0, "log": json.dumps({"result": "placed", "took_one": True})},
        collect_facts=False, dry_run=False,
        readiness_after={"arms": {"arm_a": {"folded": False}}},
    )
    assert st_cf_false == "failed"

    # structured_result survives empty/truncated logs.
    st_struct, ver_struct = vfacts.verify_job_outcome(
        client, "cell_policy_drive", "arm_a",
        {"exit": 0, "log": "truncated...", "structured_result": {"result": "released", "took_one": True}},
        collect_facts=False, dry_run=False,
        readiness_after={"arms": {"arm_a": {"folded": True}}},
    )
    assert st_struct == "completed" and ver_struct["job_summary"] == {"result": "released", "took_one": True}

    # folded=None in readiness fails closed.
    st_none, _ = vfacts.verify_job_outcome(
        client, "cell_policy_drive", "arm_a",
        {"exit": 0, "log": json.dumps({"result": "released", "took_one": True})},
        collect_facts=True, dry_run=False,
    )
    assert st_none == "failed"

    status_ok, ver_ok = vfacts.verify_job_outcome(
        client, "cell_policy_drive", "arm_a",
        {"exit": 0, "log": json.dumps({"result": "released", "took_one": True})},
        collect_facts=True, dry_run=False,
        readiness_after={"arms": {"arm_a": {"folded": True}}},
    )
    assert status_ok == "completed" and ver_ok["job_summary"] == {"result": "released", "took_one": True}

    # Unfolded live state triggers fail-closed even when summary looked good.
    st_unfolded, _ = vfacts.verify_job_outcome(
        client, "auto_pick", "arm_a",
        {"exit": 0, "log": json.dumps({"result": "placed", "took_one": True})},
        readiness_after={"arms": {"arm_a": {"folded": False}}},
    )
    assert st_unfolded == "failed"


def test_cell_executor_and_task_act_failure_metadata(tmp_path):
    assert ce.EXECUTOR_CANDIDATES == ("ik_chunk", "smolvla", "act_policy")
    assert ce.APPROVED_REAL_EXECUTORS == frozenset({"ik_chunk"})
    ch = cell_choices.Choices(tmp_path / "choices.json")
    rec_row = ce.record_act_outcome(ch, "t-act-1", False, "policy chunk late", failure_class="policy_timing_late")
    assert rec_row["outcome"] == "failed" and ch.data["values"]["exec.act_policy"][0]["tries"] == 1

    prep = tmp_path / "prep"
    prep.mkdir()
    wrapper = prep / "wrapper.sh"
    wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
    (prep / "chunks-arm-s-inplace-live.json").write_text("{}", encoding="utf-8")
    cfg = prep / "cfg.json"
    cfg.write_text(json.dumps({
        "io": str(prep),
        "sites": {"pinky": {"auto_roi": [0, 0, 10, 10]}, "belt": {"auto_roi": [20, 20, 40, 40]}},
        "act_policy": {
            "execution_allowed": True, "policy_root": "/m", "policy_revision": "a" * 64,
            "cell_calibration": "c.json", "model_calibration": "m.json",
        },
    }), encoding="utf-8")
    out = cta.execute_act_policy_task(
        {"task_id": "act-fail-1", "cell_id": "cell_s", "src_site": "pinky", "dst_site": "belt",
         "presence": {"operator": "livsbittt", "at": time.time() - 2}},
        arm_id="arm_s", prep_dir=prep, wrapper=wrapper, cfg=cfg, cat=prep / "cat.json",
        default_roi=(0, 0, 10, 10), lease_owner="w1", tools_root_fn=lambda: prep,
        run_fn=lambda cmd, **_k: subprocess.CompletedProcess(
            cmd, 1, stdout=json.dumps({
                "result": "refused", "reason": "policy chunk is late, all action times passed",
                "failure_bundle_id": "20261123T050000Z-arm_s-policy_fail",
                "episode_ref": "ep_closed_001", "source": {"before": 1, "after": 1}, "took_one": False,
            }) + "\n", stderr=""
        ),
        last_json_fn=json.loads,
        measured_fold_fn=lambda *_a: {"folded": True, "state": [0.0] * 6, "fresh": True},
        source_clearance_fn=lambda *_a: {"objects": 1},
        fold_readback_fn=lambda *_a: {"folded": True, "state": [0.0] * 6},
        plan_home_fn=lambda *_a: [0.0] * 6,
        write_context_fn=lambda *_a, **_k: None,
        timeout_exc=subprocess.TimeoutExpired,
        choices=ch,
    )
    assert out["stage_result"]["task_verified"] is False
    assert out["failure_class"] == "policy_timing_late"
    assert out["failure_stratum"] == "human_only" and out["requires_named_approval"] is True
    assert out["episode_ref"] == "ep_closed_001"
    assert out["failure_bundle_id"] == "20261123T050000Z-arm_s-policy_fail"
    assert ch.data["values"]["exec.act_policy"][0]["tries"] == 2

    # held stop skips record_act_outcome and does not misclassify as zone_unverified.
    out_held = cta.execute_act_policy_task(
        {"task_id": "act-fail-2", "cell_id": "cell_s", "src_site": "pinky", "dst_site": "belt",
         "presence": {"operator": "livsbittt", "at": time.time() - 2}},
        arm_id="arm_s", prep_dir=prep, wrapper=wrapper, cfg=cfg, cat=prep / "cat.json",
        default_roi=(0, 0, 10, 10), lease_owner="w1", tools_root_fn=lambda: prep,
        run_fn=lambda cmd, **_k: subprocess.CompletedProcess(
            cmd, 1, stdout=json.dumps({"result": "held", "reason": "operator hold", "took_one": False}) + "\n", stderr=""
        ),
        last_json_fn=json.loads,
        measured_fold_fn=lambda *_a: {"folded": True, "state": [0.0] * 6, "fresh": True},
        source_clearance_fn=lambda *_a: {"objects": 1},
        fold_readback_fn=lambda *_a: {"folded": True, "state": [0.0] * 6},
        plan_home_fn=lambda *_a: [0.0] * 6,
        write_context_fn=lambda *_a, **_k: None,
        timeout_exc=subprocess.TimeoutExpired,
        choices=ch,
    )
    assert out_held["failure_class"] == "policy_chunk_refused"
    assert out_held["failure_stratum"] == "human_only" and out_held["requires_named_approval"] is True
    assert ch.data["values"]["exec.act_policy"][0]["tries"] == 2

    # released without zone_verification classifies as policy_zone_unverified + human_only.
    out_unver = cta.execute_act_policy_task(
        {"task_id": "act-fail-3", "cell_id": "cell_s", "src_site": "pinky", "dst_site": "belt",
         "presence": {"operator": "livsbittt", "at": time.time() - 2}},
        arm_id="arm_s", prep_dir=prep, wrapper=wrapper, cfg=cfg, cat=prep / "cat.json",
        default_roi=(0, 0, 10, 10), lease_owner="w1", tools_root_fn=lambda: prep,
        run_fn=lambda cmd, **_k: subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps({"result": "released", "parked": True, "took_one": True}) + "\n", stderr=""
        ),
        last_json_fn=json.loads,
        measured_fold_fn=lambda *_a: {"folded": True, "state": [0.0] * 6, "fresh": True},
        source_clearance_fn=lambda *_a: {"objects": 0},
        fold_readback_fn=lambda *_a: {"folded": True, "state": [0.0] * 6},
        plan_home_fn=lambda *_a: [0.0] * 6,
        write_context_fn=lambda *_a, **_k: None,
        timeout_exc=subprocess.TimeoutExpired,
        choices=ch,
    )
    assert out_unver["failure_class"] == "policy_zone_unverified"
    assert out_unver["failure_stratum"] == "human_only" and out_unver["requires_named_approval"] is True
