"""D-1057 2-9 & unattended pick-and-place multi-site / 2-tier / jaw / envelope unit suite (no hardware)."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import ssl
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "deploy/robot/omx", ROOT / "middleware/devices/omx/adapter"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cell_auto_fold as caf  # noqa: E402
import cell_auto_pick_plan as cap  # noqa: E402
import cell_bed_ready as cbr  # noqa: E402
import cell_corridor as cc  # noqa: E402
import cell_feel  # noqa: E402
import cell_fleet_handoff as cfh  # noqa: E402
import cell_fleet_pipeline as cfp  # noqa: E402
import cell_job_api as cja  # noqa: E402
import cell_job_client as cjc  # noqa: E402
import cell_job_spec as cjs  # noqa: E402
import cell_pinch  # noqa: E402
import cell_place_fit as cpf  # noqa: E402
import cell_presence as cpr  # noqa: E402
import cell_remeasure as crm  # noqa: E402
import cell_result_outbox as cro  # noqa: E402
import cell_site_target as cst  # noqa: E402
import cell_task_exec as cte  # noqa: E402
import cell_task_runner as ctr  # noqa: E402
import cell_task_worker as ctw  # noqa: E402

# ---------------------------------------------------------------------------
# Ported D-1057 2-9 bed_ready + worker observation tests (cbe80fed5b)
# ---------------------------------------------------------------------------

POLY = [[60, 167], [281, 162], [283, 266], [69, 261]]
H = [[0.001, 0.0, 0.0], [0.0, 0.001, 0.0], [0.0, 0.0, 1.0]]
CAL = {"sites": {"pinky~coarse": {"homography": H}}}
UNMOVED = {"camera_moved": False, "camera_shift": {"ok": True, "max_px": 0.4}}
TASK = {"task_id": "t-1", "cell_id": "cell_s", "robot_id": "pinky_1", "src_site": "pinky", "dst_site": "belt"}
_RNG = np.random.default_rng(7)
TEXTURE = _RNG.integers(120, 250, (480, 640)).astype(np.uint8)
READY = {"verdict": "READY", "reasons": [], "frames": []}


def scene(dx=0, bed=True):
    import cv2

    img = np.full((480, 640), 60, np.uint8)
    if bed:
        mask = np.zeros_like(img)
        cv2.fillPoly(mask, [np.int32(POLY) + [dx, 0]], 1)
        img[mask > 0] = np.roll(TEXTURE, dx, axis=1)[mask > 0]
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def frames(*images, age=0.3):
    t = time.time() - age - 1.2
    return [{"image": im, "source_seq": 5 + i, "source_stamp": t + 0.6 * i, "jpeg_sha256": f"{i}" * 64}
            for i, im in enumerate(images)]


@pytest.fixture
def bed_config(tmp_path):
    import cv2

    ref = tmp_path / "bed-ref.png"
    cv2.imwrite(str(ref), cv2.cvtColor(scene(), cv2.COLOR_BGR2GRAY))
    sha = hashlib.sha256(ref.read_bytes()).hexdigest()
    return {"scene_ignore_px": [[0, 0, 75, 300]],
            "sites": {"pinky": {"auto_roi": [49, 139, 295, 305], "surface_px": POLY,
                                "bed_reference": {"image": str(ref), "sha256": sha, "band_px": 8, "min_score": 0.6,
                                                  "still_mean_max": 0.2, "captured": "2026-11-21"}}}}


def on_bed(*centres):
    return [{"matched": True, "hull_px": [[x - 5, y - 5], [x + 5, y - 5], [x + 5, y + 5], [x - 5, y + 5]]} for x, y in centres]


def _run_bed(config, monkeypatch, got=None, *, check=UNMOVED, fold=True, objects=None, error=None, task=TASK):
    seen = []
    monkeypatch.setattr(cbr, "read_frames", lambda cell: frames(scene(), scene(), scene()) if got is None else got)

    def observe(cell, cfg, cal, site, roi, catalog, *, image=None):
        seen.append(roi)
        return image, None, on_bed((170, 215)) if objects is None else objects, error

    out = cbr.judge(None, config, CAL, [], task, fold={"folded": fold}, check=lambda frame: check, observe=observe,
                    config_sha256="c" * 64)
    return out, seen


def test_the_reference_scene_three_times_is_ready(bed_config, monkeypatch):
    out, seen = _run_bed(bed_config, monkeypatch)
    assert out["verdict"] == "READY" and out["reasons"] == [] and out["objects"] == 1
    assert out["bed"]["offset_px"] == [0, 0] and out["bed"]["score"] > 0.99 and out["bed"]["tol_px"] == pytest.approx(20.0)
    assert [f["source_seq"] for f in out["frames"]] == [5, 6, 7] and out["roi"] == [49, 139, 295, 305]
    assert seen == [[49, 139, 295, 305]]


@pytest.mark.parametrize("case, reason", [
    ("no_reference", "NO_BED_REFERENCE"), ("reference_changed", "BED_REFERENCE_MISMATCH"), ("no_frames", "NO_FRESH_FRAMES"),
    ("stale_frames", "NO_FRESH_FRAMES"), ("calibration_unverified", "CALIBRATION_UNVERIFIED"),
    ("camera_moved", "CALIBRATION_UNVERIFIED"), ("arm_not_folded", "ARM_NOT_FOLDED"), ("observe_error", "OBSERVATION_FAILED"),
    ("check_raises", "OBSERVATION_FAILED"), ("loading_task", "LOAD_DIRECTION_UNSUPPORTED"),
])
def test_what_cannot_be_measured_is_unknown(bed_config, monkeypatch, case, reason):
    kw = {}
    if case == "no_reference":
        del bed_config["sites"]["pinky"]["bed_reference"]
    elif case == "reference_changed":
        bed_config["sites"]["pinky"]["bed_reference"]["sha256"] = "0" * 64
    elif case == "stale_frames":
        kw["got"] = frames(scene(), scene(), scene(), age=2.5)
    elif case == "calibration_unverified":
        kw["check"] = {"camera_moved": False, "no_reference": True}
    elif case == "camera_moved":
        kw["check"] = {**UNMOVED, "camera_moved": True}
    elif case == "arm_not_folded":
        kw["fold"] = False
    elif case == "observe_error":
        kw["error"] = "no map for pinky"
    elif case not in ("no_frames", "check_raises"):
        kw["task"] = {**TASK, "src_site": "belt", "dst_site": "pinky"}
    if case == "no_frames":
        monkeypatch.setattr(cbr, "read_frames", lambda cell: None)
        out = cbr.judge(None, bed_config, CAL, [], TASK, fold={"folded": True}, check=lambda f: UNMOVED,
                        observe=lambda *a, **k: pytest.fail("observed without frames"))
    elif case == "check_raises":
        monkeypatch.setattr(cbr, "read_frames", lambda cell: frames(scene(), scene(), scene()))

        def boom(frame):
            raise OSError("reference frame unreadable")
        out = cbr.judge(None, bed_config, CAL, [], TASK, fold={"folded": True}, check=boom, observe=pytest.fail)
    else:
        out, _ = _run_bed(bed_config, monkeypatch, **kw)
    assert out["verdict"] == "UNKNOWN" and out["reasons"] == [reason]


def test_a_bed_off_by_2_cm_and_1_px_or_missing_is_not_ready(bed_config, monkeypatch):
    out, _ = _run_bed(bed_config, monkeypatch, frames(scene(21), scene(21), scene(21)))
    assert out["verdict"] == "NOT_READY" and out["reasons"] == ["BED_OFF_POSE"] and out["bed"]["offset_px"] == [21, 0]
    out, _ = _run_bed(bed_config, monkeypatch, frames(scene(19), scene(19), scene(19)))
    assert out["verdict"] == "READY"
    out, _ = _run_bed(bed_config, monkeypatch, frames(*(scene(bed=False),) * 3))
    assert out["verdict"] == "NOT_READY" and out["reasons"] == ["BED_NOT_SEEN"]


def test_moving_bed_empty_bed_and_object_off_the_bed_are_not_ready(bed_config, monkeypatch):
    out, _ = _run_bed(bed_config, monkeypatch, frames(scene(0), scene(0), scene(3)))
    assert out["verdict"] == "NOT_READY" and out["reasons"] == ["BED_MOVING"]
    out, _ = _run_bed(bed_config, monkeypatch, objects=[{"matched": False, "hull_px": [[170, 215]]}])
    assert out["verdict"] == "NOT_READY" and out["reasons"] == ["BED_EMPTY"] and out["objects"] == 0
    out, _ = _run_bed(bed_config, monkeypatch, objects=on_bed((170, 215), (40, 300)))
    assert out["verdict"] == "NOT_READY" and out["reasons"] == ["OBJECT_OFF_BED"]


@pytest.mark.parametrize("key", ["auto_roi", "surface_px"])
def test_without_the_configured_roi_the_code_default_is_never_used(bed_config, monkeypatch, key):
    del bed_config["sites"]["pinky"][key]
    out, seen = _run_bed(bed_config, monkeypatch)
    assert out["verdict"] == "UNKNOWN" and out["reasons"] == ["NO_SITE_ROI"] and seen == []


def test_read_frames_takes_three_advancing_frames_over_a_second():
    class Cell:
        seq = 0

        def frame_receipt(self, camera, *, previous=None, max_age_s=2.0, timeout_s=10.0):
            Cell.seq += 1
            return {"image": None, "camera": camera, "source_seq": Cell.seq, "source_stamp": time.time(), "jpeg_sha256": "x"}

    got = cbr.read_frames(Cell())
    assert len(got) == 3 and got[-1]["source_stamp"] - got[0]["source_stamp"] >= cbr.SPAN_S
    assert [f["source_seq"] for f in got] == sorted({f["source_seq"] for f in got})


def test_observe_bed_without_a_cell_config_is_unknown(tmp_path):
    out = cbr.observe_bed(tmp_path, TASK)
    assert out["verdict"] == "UNKNOWN" and out["reasons"] == ["OBSERVATION_FAILED"]


def _poll(tmp_path, cell_id, observe, *, claimed=True, observation_fails=False):
    calls = []

    def request(method, path, body):
        calls.append((method, path, body))
        if method == "GET":
            return {"tasks": [{"task_id": "t-1", "cell_id": cell_id, "tier": 1, "robot_id": "pinky_1"}],
                    "human_safety": {"active_estop": False, "human_detected": {}},
                    "cells": {cell_id: {"phase": "ARM_IN_BED_ZONE", "active_task_id": "t-1"}}}
        if path.endswith("/bed-observation"):
            if observation_fails:
                raise OSError("Fleet unreachable")
            return {"ok": True}
        if path.endswith("/claim"):
            return {"claimed": False, "gate": {}} if not claimed else {"claimed": True, "gate": {}, "handoff": {}}
        return {"gate": {}, "task": {"status": "ABORTED"}}

    ctw.poll_and_execute_once(cfp.FleetModelPipeline(tmp_path / "pipe"), request_fn=request,
                              live_act_fn=lambda h: pytest.fail("the arm ran"), prep_dir=tmp_path, bed_observe_fn=observe)
    return [path for method, path, _ in calls if method == "POST"], calls


def test_cell_s_sends_one_observation_before_the_claim_and_cell_ab_none(tmp_path):
    posts, calls = _poll(tmp_path, "cell_s", lambda task: dict(READY), claimed=False)
    assert posts == ["/api/fleet/pipeline/cell-tasks/t-1/bed-observation", "/api/fleet/pipeline/cell-tasks/claim"]
    assert calls[1][2]["robot_id"] == "pinky_1" and calls[1][2]["verdict"] == "READY"
    posts, _ = _poll(tmp_path, "cell_ab", lambda task: pytest.fail("observed a cell A/B task"), claimed=False)
    assert posts == ["/api/fleet/pipeline/cell-tasks/claim"]


@pytest.mark.parametrize("fault", ["observe_raises", "observe_returns_junk", "post_fails"])
def test_an_observation_fault_still_tries_the_claim_and_a_refused_claim_never_runs_the_arm(tmp_path, fault):
    def observe(task):
        if fault == "observe_raises":
            raise RuntimeError("camera service down")
        return None if fault == "observe_returns_junk" else dict(READY)

    posts, calls = _poll(tmp_path, "cell_s", observe, claimed=False, observation_fails=fault == "post_fails")
    assert posts[-1] == "/api/fleet/pipeline/cell-tasks/claim"
    if fault != "post_fails":
        assert calls[1][2]["verdict"] == "UNKNOWN" and calls[1][2]["reasons"] == ["OBSERVATION_FAILED"]


# ---------------------------------------------------------------------------
# Unattended pick-and-place pipeline tests
# ---------------------------------------------------------------------------


def test_make_ca_urlopen_pops_caller_context_and_uses_pinned_ca(monkeypatch, tmp_path):
    ca_file = tmp_path / "ca.pem"
    ca_file.write_text("dummy", encoding="utf-8")
    pinned = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    other = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    seen = {}
    monkeypatch.setattr(cte.ssl, "create_default_context", lambda cafile=None: pinned)
    monkeypatch.setattr(cte, "urlopen", lambda req, **kw: seen.update(req=req, kw=kw) or "ok")
    opener = cte.make_ca_urlopen(ca_file)
    assert opener("req-1", context=other, timeout=5) == "ok"
    assert seen["kw"]["context"] is pinned and seen["kw"]["timeout"] == 5


def test_execute_guarded_cell_task_resolves_pallet_tier_and_handles_timeout(tmp_path, monkeypatch):
    wrappers = tmp_path / "tools" / "deploy/robot/omx/session-wrappers"
    wrappers.mkdir(parents=True)
    (wrappers / "with-session-arm-b-par.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps({"home": [0.0] * 6}), encoding="utf-8")
    prep = tmp_path / "prep"
    prep.mkdir()
    (prep / "cell-arm-b-stack.json").write_text(json.dumps({
        "plan_path": str(plan_file),
        "sites": {"belt": {"auto_roi": [0, 0, 10, 10]}, "pallet": {"place": [0.2, 0.0], "surface_z": 0.0}},
    }), encoding="utf-8")
    monkeypatch.setattr(cte, "tools_root", lambda: tmp_path / "tools")
    monkeypatch.setattr(cte, "check_arm_hold", lambda arm: {"held": False})
    cmds = []

    def fake_run(cmd, **kw):
        cmds.append(cmd)
        if len(cmds) == 2:
            raise subprocess.TimeoutExpired(cmd, 300)
        return SimpleNamespace(returncode=1, stdout='{"result": "stopped"}', stderr="")

    monkeypatch.setattr(cte.subprocess, "run", fake_run)
    monkeypatch.setattr(cte, "measured_fold", lambda arm, p: {"folded": False, "fresh": False})
    handoff = {"task_id": "t-p2", "cell_id": "cell_ab", "tier": 2, "src_site": "belt", "dst_site": "pallet"}
    cte.execute_guarded_cell_task(handoff, prep_dir=prep)
    assert cmds[0][cmds[0].index("--dest") + 1] == "pallet-l1"

    timed = cte.execute_guarded_cell_task(handoff, prep_dir=prep)
    assert timed["error"] == "SUBPROCESS_TIMEOUT" and timed["stage_result"]["task_verified"] is False


def test_handoff_refusal_and_ab_completion_multisite_contracts():
    locked = {"wheel_brake_locked": True, "bed_ready": True, "v_cmd_mps": 0.0}
    assert cfh.handoff_refusal(None, {**locked, "cell_id": "cell_ab", "arm_id": "arm_a", "src_site": "belt", "dst_site": "temp_a:r1-s1-t1"}, tier=1) is None
    assert cfh.handoff_refusal(None, {**locked, "cell_id": "cell_ab", "arm_id": "arm_b", "src_site": "belt", "dst_site": "temp_b:r1-s1-t1"}, tier=1) is None
    assert cfh.handoff_refusal(None, {**locked, "cell_id": "cell_ab", "arm_id": "arm_a", "src_site": "belt", "dst_site": "stand:r1-s1-t1"}, tier=1) is None
    assert cfh.handoff_refusal(None, {**locked, "cell_id": "cell_ab", "arm_id": "arm_b", "src_site": "belt", "dst_site": "temp_a:r1-s1-t1"}, tier=1) == "UNKNOWN_SITE"
    assert cfh.handoff_refusal(None, {**locked, "cell_id": "cell_ab", "arm_id": "arm_a", "src_site": "belt", "dst_site": "temp_b:r1-s1-t1"}, tier=1) == "UNKNOWN_SITE"
    assert cfh.handoff_refusal(None, {**locked, "cell_id": "cell_ab", "arm_id": "arm_b", "src_site": "stand", "dst_site": "belt"}, tier=1) == "UNKNOWN_SITE"
    assert cfh.handoff_refusal(None, {**locked, "cell_id": "cell_ab", "arm_id": "arm_a", "src_site": "belt", "dst_site": "temp_plate_a"}, tier=1) == "UNKNOWN_SITE"
    assert cfh.handoff_refusal(None, {**locked, "cell_id": "cell_ab", "arm_id": "arm_a", "src_site": "pinky", "dst_site": "pallet"}, tier=1) == "UNKNOWN_SITE"
    assert cfh.handoff_refusal(None, {**locked, "cell_id": "cell_ab", "arm_id": "arm_b", "src_site": "belt", "dst_site": "pallet-l2"}, tier=1) == "UNKNOWN_SITE"

    ta_target = {"site_id": "temp_a:r1-s1-t1", "area": "temp_a", "col": 1, "row": 1, "tier": 1}
    ta_handoff = {"cell_id": "cell_ab", "arm_id": "arm_a", "dst_site": "tmp-a-1", "dst_site_id": "temp_a:r1-s1-t1",
                  "dst_area": "temp_a", "dst_slot": {"col": 1, "row": 1, "tier": 1}, "tier": 1}
    ta_place = {"area": "temp_a", "site": "tmp-a-1", "site_id": "temp_a:r1-s1-t1", "col": 1, "row": 1, "tier": 1}
    assert cst.cell_ab_place_verified(ta_handoff, ta_place, {"verdict": "PASS"}, 1, {"target": ta_target}) is True
    assert cst.cell_ab_place_verified(ta_handoff, ta_place, {"verdict": "UNKNOWN"}, 1, {"target": ta_target}) is False
    assert cst.cell_ab_place_verified({"dst_site": "pallet"}, {"area": "pallet", "tier": 2}, {"verdict": "UNKNOWN"}, 2) is False
    assert cst.cell_ab_place_verified({"dst_site": "pallet"}, {"area": "pallet", "tier": 2}, {"verdict": "PASS"}, 2) is True


def test_worker_aborts_cell_s_when_source_clearance_objects_is_null(tmp_path):
    posted = []

    def request(method, path, body):
        posted.append((method, path, body))
        if method == "GET":
            return {"tasks": [{"task_id": "t-s", "cell_id": "cell_s", "tier": 1, "robot_id": "pinky_1"}],
                    "human_safety": {"active_estop": False, "human_detected": {}}, "cells": {}}
        if path.endswith("/claim"):
            return {"claimed": True, "gate": {"cell_can_claim": True},
                    "handoff": {"task_id": "t-s", "cell_id": "cell_s", "tier": 1, "handoff_lease_id": "l-1",
                                "src_site": "pinky", "dst_site": "belt"}}
        return {"ok": True, "gate": {}, "task": {"status": "ABORTED"}}

    def act(_h):
        return {
            "arm": "arm_s", "measured_at": time.time(),
            "stage_result": {"directive_id": "t-s", "arm_id": "arm_s", "task_verified": True,
                             "verification": {"verified": True, "basis": cpr.TOP_ONLY_BASIS,
                                              "placement": {"verified": True, "inside": True},
                                              "target": {"site": "belt", "tier": 1, "roi": [0, 0, 10, 10]}},
                             "source_clearance": {"objects": None, "error": "obs fail"}},
            "stop_event": {"command": "stop", "ok": True, "folded": True},
        }

    ctw.poll_and_execute_once(cfp.FleetModelPipeline(tmp_path / "pipe"), request_fn=request,
                              live_act_fn=act, prep_dir=tmp_path, bed_observe_fn=lambda _t: dict(READY))
    comp = [b for m, p, b in posted if m == "POST" and p.endswith("/complete")]
    assert len(comp) == 1 and comp[0]["phase"] == "ABORTED"


def test_remeasure_passes_reused_and_refreshes_cell_s_clearance_and_outbox_409_keeps(tmp_path, monkeypatch):
    import cv2

    crm.write_context(tmp_path / "c.json", {}, {"task_id": "skip"}, "arm_s", tmp_path, "belt", "pinky", [0, 0, 10, 10], None)
    assert not crm.context_path(tmp_path, "skip").exists()

    work = tmp_path / "work"
    (work / "zone-before").mkdir(parents=True)
    cv2.imwrite(str(work / "zone-before" / "top.png"), np.zeros((20, 20, 3), np.uint8))
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"io": str(tmp_path / "io"), "cameras": {"top": {}}, "work_dir": str(work),
                               "sites": {"belt": {"place": [0.1, 0.1]}, "pinky": {"auto_roi": [0, 0, 10, 10]}}}), encoding="utf-8")
    cat = tmp_path / "catalog.json"
    cat.write_text("[]", encoding="utf-8")
    handoff = {"task_id": "t-r", "cell_id": "cell_s", "tier": 1, "handoff_lease_id": "l-r", "arm_id": "arm_s"}
    crm.write_context(cfg, {"work_dir": str(work)}, handoff, "arm_s", tmp_path, "belt", "pinky", [0, 0, 10, 10],
                      {"before_frames": {"top": "top.png"}}, cat_path=cat)
    assert json.loads(crm.context_path(tmp_path, "t-r").read_text(encoding="utf-8"))["cat"] == str(cat)

    seen_obs = {}
    import cell_zone_verification as czv
    import cell_task_exec as _cte
    monkeypatch.setattr(czv, "measure", lambda cell, before, *a: seen_obs.update(before=before) or {
        "verified": True, "basis": cpr.TOP_ONLY_BASIS, "target": {"site": "belt", "tier": 1, "roi": [0, 0, 10, 10]}})
    monkeypatch.setattr(_cte, "source_clearance", lambda *a: {"objects": 0, "site": "pinky"})
    monkeypatch.setattr(_cte, "measured_fold", lambda arm, p, now=None: {"folded": True, "fresh": True})

    entry = {"complete": {"stage_result": {"verification": {"placement": {"verified": True, "inside": True}},
                                           "source_clearance": {"objects": 1}},
                          "hardware_telemetry": {"stop_event": {"readback": {"folded": True}}},
                          "receipt": {"reason": "TRANSFER_CONFIRMED"}}}
    owner, comp = crm.remeasure("t-r", entry, tmp_path, now=100.0)
    assert seen_obs["before"]["camera"] == "top" and seen_obs["before"]["_reused"] is True
    assert owner["stage_result"]["source_clearance"]["objects"] == 0 and comp["phase"] == "RELEASED"

    ob = cro.Outbox(tmp_path / "outbox.json")
    t_now = 200.0
    ob.put("t-1", {"lease": "l-1", "owner_evidence": {"measured_at": t_now - cro.STALE_S - 5}, "complete": {"phase": "RELEASED"}})

    def req_409(method, path, body=None):
        if method == "GET":
            return {"tasks": [{"task_id": "t-1", "handoff_lease_id": "l-1"}]}
        if path.endswith("/owner-evidence"):
            raise HTTPError(path, 409, "Conflict", None, io.BytesIO(json.dumps({"detail": {"code": "OWNER_EVIDENCE_ALREADY_RECORDED"}}).encode()))
        pytest.fail("/complete must not run after 409 on freshly remeasured owner-evidence")

    res = cro.resend_pending(ob, req_409, remeasure=lambda tid, e: ({"measured_at": t_now}, {"phase": "RELEASED"}), now=t_now)
    assert res[0]["action"] == "kept" and "t-1" in ob.items()
    assert ob.items()["t-1"]["last_refusal"]["reason"] == "OWNER_EVIDENCE_ALREADY_RECORDED"
    # Subsequent poll (now - measured < STALE_S) keeps "remeasured" guard so persistent 409 does not drop into /complete
    res2 = cro.resend_pending(ob, req_409, remeasure=lambda tid, e: pytest.fail("should not remeasure again"), now=t_now + 2.0)
    assert res2[0]["action"] == "kept" and "t-1" in ob.items()


def test_corridor_edge_to_px_none_falls_back_or_skips():
    def to_px(p):
        if 0.005 < p[0] < 0.015:
            return None
        return (50.0 + p[0] * 1000.0, 50.0 + p[1] * 1000.0)

    mask = cc.corridor([[(0.0, 0.0), (0.04, 0.0)]], to_px, (100, 120), [0, 0, 120, 100])
    assert int(mask.sum()) > 0
    mask_skip = cc.corridor([[(0.0, 0.0), (0.04, 0.0)]], lambda p: None if abs(p[0]) > 0.005 or abs(p[1]) > 0.005 else (50.0, 50.0),
                            (100, 120), [0, 0, 120, 100])
    assert int(mask_skip.sum()) == 0


def test_auto_fold_holding_high_never_stops_and_launch_lock_retry_and_arm_filter(tmp_path, monkeypatch):
    cmds = []

    class Cell:
        def act(self, cmd):
            cmds.append(cmd)
            if cmd == "state":
                return {"ok": True, "state": [5.0, 0.0, 0.0, 0.0, 0.0, 20.0], "target": [0.0] * 6}
            return {"ok": True}

    out = caf.recover(Cell(), [0.0] * 6, 5.0, plan=lambda s: [s], look=lambda l: {"clear": True},
                      reserve=lambda l: {"ok": True}, release=lambda: None,
                      release_and_rise=lambda c: {"result": "risen"}, low=lambda s: False)
    assert out["result"] == "held" and out["reason"] == "HOLDING_HIGH"
    assert "stop now" not in cmds and "human-hold" in cmds

    # RISE_BLOCKED while holding at rest must also hold with torque ON instead of stop now
    cmds.clear()
    out_rb = caf.recover(Cell(), [0.0] * 6, 5.0, plan=lambda s: [s], look=lambda l: {"clear": False},
                         reserve=lambda l: {"ok": True}, release=lambda: None,
                         release_and_rise=lambda c: {"result": "risen"}, low=lambda s: True)
    assert out_rb["result"] == "held" and out_rb["reason"] == "RISE_BLOCKED" and "stop now" not in cmds

    import omx_incident
    import omx_incident_auto
    monkeypatch.setattr(omx_incident, "INCIDENTS", str(tmp_path / "inc"))
    monkeypatch.setattr(omx_incident_auto, "note_event", lambda *a, **k: None)
    monkeypatch.setattr(omx_incident_auto, "assessor_token_file", lambda: tmp_path / "tok")
    cwd = tmp_path / "arm_cwd"
    cwd.mkdir()
    entry = {"cwd": str(cwd), "wrapper": "sh", "config": "c.json", "library": "l.json",
             "site": "belt", "roi": [0, 0, 10, 10]}
    conf = tmp_path / "fold-conf.json"
    conf.write_text(json.dumps({"arm_a": entry, "arm_b": entry}), encoding="utf-8")
    fake_link = lambda ids: SimpleNamespace(hold=lambda: SimpleNamespace(incident_ids=ids, held=bool(ids), reason="x"))

    # 1. Session lock held across all 12 tries unlinks marker
    r_fail = caf.launch("arm_a", conf, link=fake_link(["inc-1"]),
                        run=lambda *a, **k: SimpleNamespace(stdout="session lock is held", stderr=""),
                        sleep=lambda _s: None, now=lambda: 1000.0)
    assert r_fail["result"] == "failed"
    assert not (tmp_path / "inc" / "auto-fold-inc-1.json").exists()

    # 2. Ignores foreign arm's real record_session session.json (operating_profile.instance_id) on recovery poll
    (cwd / "session.json").write_text(json.dumps({
        "config": "c.json", "operating_profile": {"instance_id": "arm_a"}, "torque_after": {"11": 0},
    }), encoding="utf-8")

    def run_ok(cmd, **kw):
        out_path = Path(cmd[cmd.index("--out") + 1])
        out_path.write_text(json.dumps({"schema": caf.SCHEMA, "result": "folded", "candidate": "park",
                                        "home": [0.0] * 6, "state": [0.0] * 6, "steps": [], "corridor": {"clear": True}}), encoding="utf-8")
        return SimpleNamespace(stdout="", stderr="")

    ticks = [0]

    def adv_sleep(_s):
        ticks[0] += 1
        if ticks[0] == 2:
            (cwd / "session.json").write_text(json.dumps({
                "config": "c.json", "operating_profile": {"instance_id": "arm_b"}, "torque_after": {"11": 0},
            }), encoding="utf-8")

    cleared = []
    res = caf.launch("arm_b", conf, link=fake_link(["inc-2"]), run=run_ok, sleep=adv_sleep, now=lambda: 1000.0,
                     clear=lambda *a, **k: cleared.append(a) or True)
    assert res["result"] == "cleared" and ticks[0] >= 2 and len(cleared) == 1

    # 3. main expands with_tiers for pallet-l1
    monkeypatch.setenv("ROSY_RECOVERY_INCIDENT", "inc-3")
    monkeypatch.setattr(caf, "recover", lambda *a, **k: {"result": "held", "reason": "TEST_STOP"})
    m_cfg = tmp_path / "cfg-fold.json"
    m_cfg.write_text(json.dumps({"io": str(tmp_path / "io"), "cameras": {"top": {}}, "calibration_path": str(tmp_path / "cal.json"),
                                 "sites": {"pallet": {"place": [0.1, 0.1], "surface_z": 0.0}}}), encoding="utf-8")
    (tmp_path / "cal.json").write_text("{}", encoding="utf-8")
    m_lib = tmp_path / "lib-fold.json"
    m_lib.write_text(json.dumps({"fps": 10, "gripper_closed": 10.0, "chunks": {"home": [[0.0] * 6]}}), encoding="utf-8")
    out_fold = tmp_path / "fold-out.json"
    rc = caf.main(["--arm", "arm_b", "--config", str(m_cfg), "--library", str(m_lib), "--site", "pallet-l1",
                   "--roi", "0", "0", "10", "10", "--out", str(out_fold)])
    assert rc == 3 and json.loads(out_fold.read_text())["reason"] == "TEST_STOP"


def test_task_runner_new_kinds_task_cli_and_no_commissioning(tmp_path, monkeypatch):
    sites = {
        "belt": {"auto_roi": [0, 0, 10, 10], "kind": "temp"},
        "temp_plate_a": {"auto_roi": [0, 0, 10, 10], "kind": "temp"},
        "pallet": {"auto_roi": [0, 0, 10, 10], "surface_z": 0.0, "kind": "ship"},
    }
    seq = ctr.plan_steps({"schema": ctr.SCHEMA, "task_id": "s-1", "kind": "sequence", "source": "vla",
                          "steps": [{"from": "belt", "to": "pallet", "to_tier": 2, "object": "box-1", "colour": "orange", "layers_below": 0}]},
                         sites)
    assert seq == [{"from": "belt", "to": "pallet-l1", "redirectable": False, "object": "box-1", "colour": "orange", "layers_below": 0}]

    for kind in ("goal_stack", "outbound", "rehandle"):
        fake_plan = {"ok": True, "why": None, "moves": [{"source": "belt", "destination": "pallet-l0", "cargo_id": "c1", "phase_label": "재취급"}]}
        import cell_stack_plan
        monkeypatch.setattr(cell_stack_plan, "plan_from_spec", lambda spec: fake_plan)
        steps = ctr.plan_steps({"schema": ctr.SCHEMA, "task_id": f"k-{kind}", "kind": kind, "source": "vla",
                                "match_cargo_object": True}, sites)
        assert steps[0]["from"] == "belt" and steps[0]["to"] == "pallet-l0" and steps[0]["object"] == "c1" and steps[0]["redirectable"] is True

    work = tmp_path / "work"
    cfg = tmp_path / "cell-c.json"
    cfg.write_text(json.dumps({"work_dir": str(work), "sites": sites}), encoding="utf-8")
    cat = tmp_path / "cat.json"
    cat.write_text("[]", encoding="utf-8")
    tf = tmp_path / "task-1.json"
    tf.write_text(json.dumps({"schema": ctr.SCHEMA, "task_id": "t-cli", "kind": "move", "source": "vla", "from": "belt", "to": "temp_plate_a"}), encoding="utf-8")
    import cell_preflight
    monkeypatch.setattr(cell_preflight, "checks", lambda *a: [("cam", True, "ok")])
    real_rt, real_rc = ctr.run_task, ctr.run_carry
    fake_proc = lambda *a, **k: SimpleNamespace(stdout='{"result": "planned"}', stderr="", returncode=0)
    monkeypatch.setattr(ctr, "run_task", lambda *a, **k: real_rt(*a, carry=lambda *ca, **ck: real_rc(*ca, run=fake_proc, **ck), **k))
    assert ctr.main(["--config", str(cfg), "--catalog", str(cat), "--task", str(tf), "--dry-run"]) == 0
    assert list((work / "task-logs").glob("*.json"))
    with pytest.raises(SystemExit):
        ctr.main(["--config", str(cfg), "--catalog", str(cat), "--task", str(tf), "--commissioning"])
    with pytest.raises(SystemExit):
        ctr.main(["--config", str(cfg), "--catalog", str(cat), "--task", str(tf), "--person-at-switch"])


def test_job_spec_client_and_job_api_unattended_extensions(tmp_path):
    for fn in ("cell-b.json", "object-catalog-orange.json", "task-run.json", "plan-stack.json"):
        (tmp_path / fn).write_text("{}", encoding="utf-8")
    (tmp_path / "cell-b.json").write_text(json.dumps({"sites": {"belt": {"alternates": ["pinky"]}}}), encoding="utf-8")
    (tmp_path / "task-run.json").write_text(json.dumps({"schema": "rosy.omx-cell-task.v1", "task_id": "t1", "kind": "move",
                                                        "from": "belt", "to": "temp_plate_a"}), encoding="utf-8")

    # 1. object-catalog-*.json + reviewed_auto without --commissioning / --person-at-switch
    argv = cjs.build_argv(cjs.JOBS["auto_pick"], {
        "arm": "arm_b", "config": "cell-b.json", "catalog": "object-catalog-orange.json",
        "roi": [0, 0, 10, 10], "source": "belt", "dest": "pallet", "reviewed_auto": True,
        "object": "orange-1", "colour": "orange", "layers_below": 1,
    }, tmp_path)
    assert "--commissioning" not in argv and "--person-at-switch" not in argv
    assert "--object" in argv and "orange-1" in argv and "--layers-below" in argv and "1" in argv

    with pytest.raises(ValueError, match="D-911"):
        cjs.build_argv(cjs.JOBS["auto_pick"], {
            "arm": "arm_b", "config": "cell-b.json", "catalog": "object-catalog-orange.json",
            "roi": [0, 0, 10, 10], "source": "belt", "dest": "pallet", "reviewed_auto": True, "person_at_switch": True,
        }, tmp_path)

    # 2. New jobs & task-JSON AMR bed refusal (including via alternates)
    assert "cell_stack_plan.py" in cjs.build_argv(cjs.JOBS["stack_plan"], {"plan": "plan-stack.json"}, tmp_path)
    assert "--dry-run" in cjs.build_argv(cjs.JOBS["task_runner_dry_run"], {
        "config": "cell-b.json", "catalog": "object-catalog-orange.json", "task": "task-run.json"}, tmp_path)
    with pytest.raises(ValueError, match="R cell-task"):
        cjs.build_argv(cjs.JOBS["task_runner"], {
            "arm": "arm_a", "config": "cell-b.json", "catalog": "object-catalog-orange.json", "task": "task-run.json"}, tmp_path)
    (tmp_path / "cell-b.json").write_text(json.dumps({"sites": {"belt": {"alternates": ["pallet"]}}}), encoding="utf-8")
    assert "--commissioning" not in cjs.build_argv(cjs.JOBS["task_runner"], {
        "arm": "arm_a", "config": "cell-b.json", "catalog": "object-catalog-orange.json", "task": "task-run.json"}, tmp_path)
    assert "cell_auto_carry.py" in cjs.build_argv(cjs.JOBS["auto_carry"], {
        "arm": "arm_b", "config": "cell-b.json", "catalog": "object-catalog-orange.json",
        "roi": [0, 0, 10, 10], "source": "belt", "dest": "pallet", "max": 4}, tmp_path)
    with pytest.raises(ValueError, match="D-911"):
        cjs.build_argv(cjs.JOBS["auto_carry"], {
            "arm": "arm_b", "config": "cell-b.json", "catalog": "object-catalog-orange.json",
            "roi": [0, 0, 10, 10], "source": "belt", "dest": "pallet", "max": 2, "person_at_switch": True}, tmp_path)
    for bad_job, bad_params in [
        ("auto_pick", {"arm": "arm_b", "config": "cell-b.json", "catalog": "object-catalog-orange.json",
                       "roi": [0, 0, 10, 10], "source": "belt", "dest": "tray-l0", "reviewed_auto": True}),
        ("auto_carry", {"arm": "arm_b", "config": "cell-b.json", "catalog": "object-catalog-orange.json",
                        "roi": [0, 0, 10, 10], "source": "belt", "dest": "vehicle_tray-l0", "max": 1}),
    ]:
        with pytest.raises(ValueError, match="R cell-task"):
            cjs.build_argv(cjs.JOBS[bad_job], bad_params, tmp_path)
    (tmp_path / "cell-b.json").write_text(json.dumps({"sites": {"belt": {}, "pinky": {}}}), encoding="utf-8")
    (tmp_path / "task-goal.json").write_text(json.dumps({
        "schema": "rosy.omx-cell-task.v1", "task_id": "tg", "kind": "goal_stack",
        "initial": {}, "goal": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="R cell-task"):
        cjs.build_argv(cjs.JOBS["task_runner"], {
            "arm": "arm_a", "config": "cell-b.json", "catalog": "object-catalog-orange.json", "task": "task-goal.json"}, tmp_path)

    # 3. Client .jobs()
    cl = cjc.CellJobClient("http://127.0.0.1:8781", token="tok")
    cl._request = lambda method, path, body=None: json.dumps({"jobs": {"auto_pick": {}}}) if (method, path) == ("GET", "/jobs") else "{}"
    assert "auto_pick" in cl.jobs()["jobs"]

    # 4. cell_job_api allows warm reuse when clean and refuses when live.json has interrupt=True
    (tmp_path / "chunk-io-a").mkdir()
    runner = cja.Runner(tmp_path, lock_dir=tmp_path, lease_dir=tmp_path)
    (tmp_path / "arm_a.json").write_text(json.dumps({"owner": runner._lease_owner}), encoding="utf-8")
    runner.runs["j1"] = {"moving": True, "arm": "arm_a", "proc": SimpleNamespace(poll=lambda: 0)}
    live_path = tmp_path / "chunk-io-a" / "live.json"
    live_path.write_text(json.dumps({"chunk": None, "human_hold_latched": False, "fault": False, "t": time.time()}), encoding="utf-8")
    assert runner._can_reuse_arm_session_locked("arm_a") is True
    live_path.write_text(json.dumps({"chunk": None, "human_hold_latched": False, "fault": False, "interrupt": True, "t": time.time()}), encoding="utf-8")
    assert runner._can_reuse_arm_session_locked("arm_a") is False


def test_verify_placed_two_tier_feel_pinch_offset_and_place_fit_top3(tmp_path, monkeypatch):
    import cell_pivot

    raw_jpg = b"\xff\xd8\xff\xd9"

    class Cell:
        def frame_receipt(self, cam, previous=None):
            return {"image": np.zeros((20, 20, 3), np.uint8), "source_stamp": time.time(), "source_seq": 2,
                    "jpeg_bytes": raw_jpg, "jpeg_sha256": hashlib.sha256(raw_jpg).hexdigest()}

    monkeypatch.setattr(cell_pivot, "map_record", lambda cal, site: {"homography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]})
    monkeypatch.setattr(cell_pivot, "bias_at", lambda *a, **k: {"bias_mm": [0.0, 0.0]})
    before = {"image": np.zeros((20, 20, 3), np.uint8)}
    src_xy, dst_xy = (0.1, 0.0), (0.3, 0.0)

    def obs(cell, cfg, cal, site, roi, cat, *, image=None):
        if image is before["image"]:
            return image, None, [], None
        return image, None, [{"object": "box-1", "raw_m": list(src_xy if site.startswith("pallet") else dst_xy)}], None

    monkeypatch.setattr(cap, "observe", obs)
    monkeypatch.setattr(cap, "_parent_attr", lambda _name, default: default)
    base_cfg = {"sites": {"belt": {}, "pallet-l0": {"layer": 0}, "pallet-l1": {"layer": 1}}}
    v1 = cap.verify_placed(Cell(), base_cfg, {}, "belt", dst_xy, [0, 0, 10, 10], [], {}, "box-1", before,
                           tmp_path / "a1.jpg", "pallet-l0", src_xy, [0, 0, 10, 10])
    assert v1["verified"] is False and v1["basis"] == "unverified: source still occupied"
    v2 = cap.verify_placed(Cell(), base_cfg, {}, "belt", dst_xy, [0, 0, 10, 10], [], {}, "box-1", before,
                           tmp_path / "a2.jpg", "pallet-l1", src_xy, [0, 0, 10, 10])
    assert v2["verified"] is True and v2["inside"] is True

    # cell_feel respects target["offset"] == 0.0 and falls back to closing_theory_deg on None
    seen_picks = []
    cfg_feel = {"work_dir": str(tmp_path), "params": {"feel.enabled": True, "reach.enabled": False, "feel.tries": 1,
                                                       "feel.step_mm": 10.0, "feel.z_step_mm": 0.0, "auto.closing_theory_deg": 90.0}, "sites": {}}
    write_lib = lambda cfg, pick, place, p: (seen_picks.append(dict(pick)) or str(p))
    for off, exp_x, exp_y in [(0.0, 0.11, 0.0), (None, 0.1, 0.01)]:
        seen_picks.clear()
        search = cell_feel.feel_hook(cfg_feel, None, {"pick": {"x": 0.1, "y": 0.0, "z": 0.05, "yaw_deg": 0.0},
                                                      "place": {"x": 0.2, "y": 0.0, "z": 0.05, "yaw_deg": 0.0}, "offset": off},
                                     write_lib)
        search(lambda _cmd: {"ok": True, "holding": True})
        assert seen_picks[0]["x"] == pytest.approx(exp_x, abs=1e-4) and seen_picks[0]["y"] == pytest.approx(exp_y, abs=1e-4)

    # cell_pinch respects target["offset"] == 0.0 vs None
    seen_closing = []
    monkeypatch.setattr(cell_pinch, "check", lambda cell, cam, hsv, closing, *a, **k: seen_closing.append(closing) or {
        "verdict": "pass", "iterations": [{"pads": [[0, 0], [1, 1]]}]})
    cfg_pinch = {"work_dir": str(tmp_path), "arm_id": "arm_b",
                 "wrist": {"hsv_min": [0, 0, 0], "hsv_max": [10, 10, 10]},
                 "params": {"pinch.enabled": True, "pinch.finger_color": "dark", "auto.closing_theory_deg": 90.0}}
    for off, expected in [(0.0, 0.0), (None, 90.0)]:
        seen_closing.clear()
        cell_pinch.hook(cfg_pinch, None, {"pick": {"x": 0.1, "y": 0.0, "z": 0.05, "yaw_deg": 0.0},
                                          "place": {}, "offset": off}, lambda *a: "x", 40.0, 30.0)()
        assert seen_closing == [pytest.approx(expected)]

    # cell_place_fit keeps up to 3 distinct valid placements per yaw spaced >= 0.012 m
    cfg_pf = {"sites": {"belt": {"surface_px": [[0, 0], [300, 0], [300, 300], [0, 300]], "yaw_deg": 0.0}},
              "params": {"place.margin_mm": 0.0, "place.search_mm": 30.0, "place.step_mm": 6.0}}
    opts, why = cpf.options(cfg_pf, "belt", (0.1, 0.1), 0.0, {"length_mm": 20.0, "width_mm": 20.0},
                            lambda q: (150.0 + (q[0] - 0.1) * 1000.0, 150.0 + (q[1] - 0.1) * 1000.0))
    assert why is None
    yaw0_pts = [xy for xy, y in opts if y == pytest.approx(0.0)]
    assert len(yaw0_pts) >= 3 and all(
        ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 >= 0.0119
        for i, a in enumerate(yaw0_pts) for b in yaw0_pts[i + 1:])
