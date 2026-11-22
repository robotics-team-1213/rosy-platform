"""Contract and cell-emitter tests for rosy.omx-failure-context.v1 (D-1072)."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import cell_failure_context as cfc  # noqa: E402
from core_common.protocol.cell_failure_context import (  # noqa: E402
    CELL_READINESS_SCHEMA,
    CellFailureContext,
    CellReadiness,
    FailureContextFence,
    canonical_sha256,
)


def _sample_inputs():
    correlation = {
        "attempt_id": "20261123T031400Z-002",
        "run_id": "20261123T031400Z",
        "job_id": "20261123-031401-a1b2c3",
        "task_id": "ct-0042",
        "policy_revision": "a" * 64,
    }
    generation = {"cell_state_gen": 10, "authority_epoch": 2, "dispatch_generation": 5}
    measurement = {
        "outcome": {"result": "contact", "fail_stage": "lift", "attempt_cause": "lift_stall", "error": "stopped at lift"},
        "why": {"verdict": "blocked", "by": "measurement", "joint": "wrist_flex", "lag_end": 2.25},
        "kinematics_and_health": {"max_home_err_units": 2.5},
        "holding_and_fold": {
            "still_holding": {"measured": False, "tcp_low_for_release": True},
            "live_fold": {"folded": True, "at_rest_tol_8": True},
        },
        "incident": {"local_held": False, "fleet_held": False, "latched_motors": {}, "windup_hits_count": 0, "caps_restored": True},
        "trace_ref": {"file": "trace-tail.jsonl", "bytes": 12, "sha256": hashlib.sha256(b"row\n").hexdigest()},
    }
    spatial = {
        "sites": {"src_raw": "belt", "dst_raw": "yard:r2-s1-t1", "is_amr_bed": False},
        "calibration": {"top_shift_px": {"moved": False, "max_px": 2.1, "limit_px": 6.0}, "missing_map": []},
        "perception": {"detected_objects": [{"object": "c3"}]},
        "workspace_occupancy": {"arms": {"arm_a": {"held": False, "folded": True}}, "fleet_safety": {"active_estop": False}},
    }
    visual = {
        "camera_manifest": {
            "top": {"status": "ok", "required_for_mode": True, "source_seq": 10, "source_stamp": 100.0, "age_at_stop_s": 0.2},
            "arm_b_wrist": {"status": "missing_device", "required_for_mode": False, "error": "absent"},
        },
        "frames": [
            {
                "id": "top-tip",
                "file": "top-tip.jpg",
                "camera": "top",
                "kind": "tip_crop",
                "t_rel_s": 0.0,
                "source_seq": 10,
                "bytes": 4,
                "sha256": hashlib.sha256(b"\xff\xd8\xff\xd9").hexdigest(),
            }
        ],
        "gaps": [{"camera": "arm_b_wrist", "why": "absent"}],
    }
    return correlation, generation, measurement, spatial, visual


def test_emitter_bundle_validates_through_pydantic_contract():
    corr, gen, meas, spat, vis = _sample_inputs()
    bundle = cfc.build_bundle(
        bundle_id="20261123T031500Z-arm_b-stop",
        kind="stop",
        arm_id="arm_b",
        cell_id="cell_ab",
        executor_mode="ik_auto_pick",
        correlation=corr,
        generation=gen,
        measurement=meas,
        spatial=spat,
        visual=vis,
        created_at_s=1000.0,
        monotonic_s=50.0,
    )
    model = CellFailureContext.model_validate(bundle)
    assert model.context_sha256 == bundle["context_sha256"]
    assert model.history_and_constraints.measured_vetoes == []
    verbs = [m.verb for m in model.history_and_constraints.allowed_fallback_menu]
    assert "retry_ik_slower" in verbs and "escalate_human" in verbs


def test_contract_rejects_extra_nan_oversize_depth_b64_tamper_and_missing_cam():
    corr, gen, meas, spat, vis = _sample_inputs()
    bundle = cfc.build_bundle(
        bundle_id="b-1", kind="stop", arm_id="arm_a", cell_id="cell_ab", executor_mode="ik_auto_pick",
        correlation=corr, generation=gen, measurement=meas, spatial=spat, visual=vis, created_at_s=100.0, monotonic_s=10.0,
    )
    with pytest.raises(ValidationError):
        CellFailureContext.model_validate({**bundle, "unexpected": 1})
    bad_tamper = {**bundle, "arm_id": "arm_s"}
    with pytest.raises(ValidationError):
        CellFailureContext.model_validate(bad_tamper)
    bad_b64 = json.loads(json.dumps(bundle))
    bad_b64["measurement"]["note"] = "data:image/jpeg;base64,AAAA"
    bad_b64["context_sha256"] = canonical_sha256(bad_b64, omit_keys=("context_sha256", "freshness"))
    with pytest.raises(ValidationError):
        CellFailureContext.model_validate(bad_b64)
    deep = json.loads(json.dumps(bundle))
    deep["measurement"]["a"] = {"b": {"c": {"d": {"e": {"f": 1}}}}}
    deep["context_sha256"] = canonical_sha256(deep, omit_keys=("context_sha256", "freshness"))
    with pytest.raises(ValidationError):
        CellFailureContext.model_validate(deep)
    big = json.loads(json.dumps(bundle))
    big["measurement"]["pad"] = "x" * 50_000
    big["context_sha256"] = canonical_sha256(big, omit_keys=("context_sha256", "freshness"))
    with pytest.raises(ValidationError):
        CellFailureContext.model_validate(big)
    miss = json.loads(json.dumps(bundle))
    miss["visual"]["frames"][0]["camera"] = "arm_b_wrist"
    miss["context_sha256"] = canonical_sha256(miss, omit_keys=("context_sha256", "freshness"))
    with pytest.raises(ValidationError):
        CellFailureContext.model_validate(miss)
    with pytest.raises(ValidationError):
        FailureContextFence(expected_context_sha256="b" * 64, expected_cell_state_gen=1, max_age_s=float("nan"))


def test_cell_readiness_and_digest_validation():
    core = {
        "schema": CELL_READINESS_SCHEMA,
        "observed_at": 1234.5,
        "max_age_s": 5.0,
        "cell_state_gen": 7,
        "arms": {"arm_s": {"folded": True}, "arm_a": {"folded": True}, "arm_b": {"folded": False}},
        "blocking_refusals": ["OUT_OF_HOME_POSE"],
        "allowed_tiers_now": [0, 1],
    }
    core["readiness_digest"] = canonical_sha256(core)
    ready = CellReadiness.model_validate(core)
    assert ready.cell_state_gen == 7
    with pytest.raises(ValidationError):
        CellReadiness.model_validate({**core, "readiness_digest": "0" * 64})


def test_all_16_measured_vetoes_triggered():
    _, _, meas, spat, vis = _sample_inputs()
    meas["kinematics_and_health"]["max_home_err_units"] = 88.5
    spat["calibration"]["top_shift_px"] = {"moved": True, "max_px": 8.7, "limit_px": 6.0}
    spat["calibration"]["missing_map"] = ["pallet"]
    meas["incident"] = {"local_held": True, "fleet_held": False, "latched_motors": {"14": 1}, "windup_hits_count": 1, "caps_restored": False}
    meas["holding_and_fold"]["live_fold"] = {"folded": False, "at_rest_tol_8": False}
    meas["holding_and_fold"]["still_holding"] = {"measured": True, "tcp_low_for_release": False}
    spat["sites"]["is_amr_bed"] = True
    vis["camera_manifest"]["arm_b_wrist"]["required_for_mode"] = True
    spat["workspace_occupancy"]["peer_ab_session_locked"] = True
    spat["workspace_occupancy"]["fleet_safety"] = {"active_estop": True}
    spat["perception"]["detected_objects"] = []
    meas["outcome"]["attempt_cause"] = "empty"
    vetoes = cfc.compute_measured_vetoes(meas, spat, vis, pending_intent_present=True, repeat_unknown_tripped=True)
    assert {v["code"] for v in vetoes} == set(cfc.MEASURED_VETO_CODES)


def test_fallback_menu_forbids_policy_autoswap_and_enforces_depth_and_tiers():
    policy_menu = {m["verb"]: m for m in cfc.build_allowed_fallback_menu("act_paced", "lift_stall", [])}
    ik_prop = policy_menu["propose_ik_fallback_for_policy"]
    assert ik_prop["tier"] == 1 and ik_prop["stratum"] == "tier1_propose" and ik_prop["requires_human_operator"] is True
    assert "retry_ik_slower" not in policy_menu

    depth_menu = cfc.build_allowed_fallback_menu("act_paced", "lift_stall", [], fallback_chain_depth=2)
    for item in depth_menu:
        if item["verb"] != "escalate_human":
            assert not item["preconditions_met"] and "CHAIN_DEPTH_EXCEEDED" in item["blocked_by"]

    d1019_menu = {m["verb"]: m for m in cfc.build_allowed_fallback_menu("ik_auto_pick", "no_room", [], has_declared_alternates=True, dest_full_pre_motion=True)}
    assert d1019_menu["redirect_alt_dest"]["tier"] == 2 and d1019_menu["redirect_alt_dest"]["requires_human_operator"] is False

    manual_unwedge = {m["verb"]: m for m in cfc.build_allowed_fallback_menu("ik_auto_pick", "lift_stall", [], auto_fold_armed=False)}
    assert manual_unwedge["home_unwedge"]["tier"] == 3 and manual_unwedge["home_unwedge"]["requires_person_at_switch"] is True
    armed_unwedge = {m["verb"]: m for m in cfc.build_allowed_fallback_menu("ik_auto_pick", "lift_stall", [], auto_fold_armed=True)}
    assert armed_unwedge["home_unwedge"]["tier"] == 2 and armed_unwedge["home_unwedge"]["stratum"] == "tier2_auto"


def test_storage_retention_hold_pinning_assets_and_fence(tmp_path):
    corr, gen, meas, spat, vis = _sample_inputs()
    jpg, trace = b"\xff\xd8\xff\xe0test\xff\xd9", b'{"t":1.0}\n'
    for idx, bid in enumerate(("b-0", "b-1", "b-2")):
        b = cfc.build_bundle(
            bundle_id=bid, kind="stop", arm_id="arm_b", cell_id="cell_ab", executor_mode="ik_auto_pick",
            correlation=corr, generation=gen, measurement=meas, spatial=spat, visual=vis, created_at_s=100.0 + idx, monotonic_s=10.0 + idx,
        )
        cfc.write_bundle(tmp_path, b, {"top-tip.jpg": jpg, "trace-tail.jsonl": trace}, pinned_bundle_ids=("b-0",), max_failure_bundles=2)

    listed = cfc.list_bundles(tmp_path, arm="arm_b")
    assert [r["bundle_id"] for r in listed] == ["b-2", "b-0"]
    assert (tmp_path / "b-0" / "bundle.json").is_file() and not (tmp_path / "b-1").exists()

    loaded = cfc.load_bundle(tmp_path, "b-2", current_cell_state_gen=10, now_s=110.0)
    assert loaded["freshness"]["still_valid_for_action"] is True
    CellFailureContext.model_validate(loaded)

    asset_path, mime, sha = cfc.resolve_asset(tmp_path, "b-2", "top-tip.jpg")
    assert mime == "image/jpeg" and sha == hashlib.sha256(jpg).hexdigest() and asset_path.is_file()

    with pytest.raises(ValueError):
        cfc.resolve_asset(tmp_path, "b-2", "../b-0/top-tip.jpg")
    (tmp_path / "b-2" / "top-tip.jpg").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="sha256"):
        cfc.resolve_asset(tmp_path, "b-2", "top-tip.jpg")

    ok, code, _ = cfc.check_fence(loaded, expected_context_sha256=loaded["context_sha256"], expected_cell_state_gen=10, current_cell_state_gen=10, now_s=110.0)
    assert ok and code is None
    for bad_kw in (
        {"expected_context_sha256": "0" * 64, "expected_cell_state_gen": 10, "current_cell_state_gen": 10, "now_s": 110.0},
        {"expected_context_sha256": loaded["context_sha256"], "expected_cell_state_gen": 10, "current_cell_state_gen": 11, "now_s": 110.0},
        {"expected_context_sha256": loaded["context_sha256"], "expected_cell_state_gen": 10, "current_cell_state_gen": 10, "now_s": 150.0},
        {"expected_context_sha256": loaded["context_sha256"], "expected_cell_state_gen": 10, "current_cell_state_gen": 10, "now_s": 110.0, "active_holds": ("arm_b",)},
    ):
        ok, code, reasons = cfc.check_fence(loaded, **bad_kw)
        assert not ok and code == "STALE_FAILURE_CONTEXT" and reasons


def test_redact_context_strips_private_ips_home_paths_and_secrets():
    raw = {
        "url": "http://100.64.0.42:8781/readiness",
        "lan": "192.168.50.10",
        "unix": "/home/alice/.config/rosy/cell-job-api.token",
        "win": r"C:\Users\bob\AppData\Local\Rosy\token",
        "headers": {"Authorization": "Bearer secret-abc-123", "X-API-Key": "sk-live-999"},
        "msg": "bearer abc+def/ghi== and Bearer xyz123456=7",
        "api_key": "sk-test",
        "safe_float": "version 10.2.3.4-rc1",
    }
    red = cfc.redact_context(raw)
    assert "100.64.0.42" not in red["url"] and "[REDACTED_IP]" in red["url"]
    assert red["lan"] == "[REDACTED_IP]"
    assert red["unix"].startswith("/home/[USER]/")
    assert red["win"].startswith("[USER_HOME]\\")
    assert red["headers"]["Authorization"] == "[REDACTED]"
    assert red["headers"]["X-API-Key"] == "[REDACTED]"
    assert red["api_key"] == "[REDACTED]"
    assert "abc+def/ghi==" not in red["msg"] and "xyz123456=7" not in red["msg"]


def test_pr1_hardening_traversal_roundtrip_amr_bed_and_fail_closed_fence(tmp_path):
    corr, gen, meas, spat, vis = _sample_inputs()
    for bad_id in (".", "..", ".hidden", "a..b"):
        with pytest.raises(ValueError, match="bundle_id"):
            cfc.build_bundle(
                bundle_id=bad_id, kind="stop", arm_id="arm_b", cell_id="cell_ab", executor_mode="ik_auto_pick",
                correlation=corr, generation=gen, measurement=meas, spatial=spat, visual=vis,
            )
    b = cfc.build_bundle(
        bundle_id="roundtrip-1", kind="stop", arm_id="arm_b", cell_id="cell_ab", executor_mode="ik_auto_pick",
        correlation=corr, generation=gen, measurement=meas, spatial=spat, visual=vis, created_at_s=100, monotonic_s=10,
    )
    with pytest.raises(ValueError, match="bundle_id"):
        cfc.write_bundle(tmp_path, {**b, "bundle_id": ".."})
    with pytest.raises(ValueError, match="bundle_id"):
        cfc.load_bundle(tmp_path, "..")

    model = CellFailureContext.model_validate(b)
    dumped = model.model_dump(mode="json", by_alias=True)
    assert CellFailureContext.model_validate(dumped).bundle_id == "roundtrip-1"

    # Tampered in-memory body must fail check_fence even when context_sha256 field is unchanged.
    tampered = json.loads(json.dumps(b))
    tampered["arm_id"] = "arm_a"
    ok, code, _ = cfc.check_fence(tampered, expected_context_sha256=b["context_sha256"], expected_cell_state_gen=10, current_cell_state_gen=10, now_s=105.0)
    assert not ok and code == "STALE_FAILURE_CONTEXT"

    # Missing cell_state_gen, NaN max_age_s, ttl_s > 30, and future created_at_s fail closed.
    bad_gen = json.loads(json.dumps(b))
    del bad_gen["generation"]["cell_state_gen"]
    assert not cfc.check_fence(bad_gen, expected_context_sha256=b["context_sha256"], expected_cell_state_gen=0, current_cell_state_gen=0, now_s=105.0)[0]
    assert not cfc.check_fence(b, expected_context_sha256=b["context_sha256"], expected_cell_state_gen=10, current_cell_state_gen=10, now_s=105.0, max_age_s=float("nan"))[0]
    assert not cfc.check_fence({**b, "ttl_s": 99.0}, expected_context_sha256=b["context_sha256"], expected_cell_state_gen=10, current_cell_state_gen=10, now_s=105.0)[0]
    assert not cfc.check_fence(b, expected_context_sha256=b["context_sha256"], expected_cell_state_gen=10, current_cell_state_gen=10, now_s=90.0)[0]

    # Direct cell_job_api motion verbs must be blocked by AMR_BED_REQUIRES_FLEET_R.
    spat_bed = json.loads(json.dumps(spat))
    spat_bed["sites"]["is_amr_bed"] = True
    vetoes_bed = cfc.compute_measured_vetoes(meas, spat_bed, vis)
    menu_bed = {m["verb"]: m for m in cfc.build_allowed_fallback_menu("ik_auto_pick", "lift_stall", vetoes_bed)}
    for verb in ("retry_ik_slower", "align_push"):
        assert not menu_bed[verb]["preconditions_met"] and "AMR_BED_REQUIRES_FLEET_R" in menu_bed[verb]["blocked_by"]

    # None / omitted safety fields fail closed.
    meas_none = json.loads(json.dumps(meas))
    meas_none["holding_and_fold"] = {"live_fold": {"folded": False}, "still_holding": {"measured": True}}
    spat_none = json.loads(json.dumps(spat))
    spat_none["workspace_occupancy"] = {"arms": {"arm_a": {"session_lock_held": True}}}
    codes = {v["code"] for v in cfc.compute_measured_vetoes(meas_none, spat_none, vis)}
    assert {"EXTENDED_TORQUE_DROP_FORBIDDEN", "HOLDING_HIGH_NO_RELEASE", "PEER_ARM_LOCKED_OR_HELD"} <= codes
