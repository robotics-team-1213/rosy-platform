"""Tests for D-1072 PR-3: :8781 readiness/failure HTTP, frame headers, always-on Ring, bundle emission, and media/staging jobs."""
from __future__ import annotations

import hashlib
import http.server
import json
from pathlib import Path
import sys
import threading
import time
import urllib.error
import urllib.request
from unittest.mock import Mock

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

REPO = Path(__file__).resolve().parents[1]
OMX = REPO / "deploy" / "robot" / "omx"
if str(OMX) not in sys.path:
    sys.path.insert(0, str(OMX))
if str(REPO / "contracts" / "foundation") not in sys.path:
    sys.path.insert(0, str(REPO / "contracts" / "foundation"))

import cell_evidence as ev  # noqa: E402
import cell_failure_context as cfc  # noqa: E402
import cell_hooks  # noqa: E402
import cell_job_api as api  # noqa: E402
import cell_job_client as client_mod  # noqa: E402
import cell_media_jobs as media_jobs  # noqa: E402
import cell_policy_drive as policy_drive  # noqa: E402
import omx_incident as oi  # noqa: E402
import omx_incident_fleet as oif  # noqa: E402
from core_common.protocol.cell_failure_context import CellFailureContext, CellReadiness  # noqa: E402


def _make_workdir(tmp_path: Path) -> Path:
    for name in ("cell-s.json", "catalog-live.json", "chunks-s.json", "upkeep-arms.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    (tmp_path / "tools-env-current.sh").write_text("export OMX=~/rosy-test/omx-tools-abc1234/deploy/robot/omx\n", encoding="utf-8")
    return tmp_path


def _sample_jpg() -> bytes:
    ok, enc = cv2.imencode(".jpg", np.full((32, 32, 3), 120, np.uint8))
    assert ok
    return enc.tobytes()


def _write_sample_bundle(root: Path, *, arm: str = "arm_s", kind: str = "stop", gen: int = 0) -> tuple[dict, bytes]:
    jpg = _sample_jpg()
    bundle = cfc.build_bundle(
        kind=kind, arm_id=arm, cell_id=("cell_s" if arm == "arm_s" else "cell_ab"),
        executor_mode="ik_auto_pick",
        correlation={"source": "belt", "dest": "outbound"},
        generation={"cell_state_gen": gen},
        measurement={"outcome": {"result": "stopped: empty", "attempt_cause": "empty"}},
        spatial={"sites": {"source": "belt", "dest": "outbound", "is_amr_bed": False}},
        visual={
            "camera_manifest": {"top": {"status": "ok", "required_for_mode": True, "source_seq": 7}},
            "frames": [{"id": "f0", "file": "arm_s_wrist-00.jpg", "camera": "arm_s_wrist", "kind": "at", "t_rel_s": -0.5, "bytes": 1, "sha256": "0" * 64}],
            "gaps": [],
        },
    )
    cfc.write_bundle(root, bundle, {"arm_s_wrist-00.jpg": jpg})
    loaded = cfc.load_bundle(root, bundle["bundle_id"])
    return loaded, jpg


def test_http_readiness_failures_frame_headers_structured_result_and_client(tmp_path, monkeypatch):
    wd = _make_workdir(tmp_path)
    bundle_root = tmp_path / "bundles"
    jpg = _sample_jpg()

    class ViewerHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("X-Frame-Seq", "123")
            self.send_header("X-Source-Stamp", "1000.5")
            self.send_header("ETag", '"seq-123"')
            self.send_header("Content-Length", str(len(jpg)))
            self.end_headers()
            self.wfile.write(jpg)

    viewer = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ViewerHandler)
    threading.Thread(target=viewer.serve_forever, daemon=True).start()

    monkeypatch.setattr(api, "_check_arm_incident", lambda _arm: None)
    monkeypatch.setattr(api, "_session_lock_held", lambda _arm, _ld=None: False)
    monkeypatch.setattr(api, "_whole_cell_lock_held", lambda _ld=None: False)
    monkeypatch.setattr(api, "_check_depth_lock_held", lambda _ld=None: False)

    runner = api.Runner(wd, lock_dir=wd, bundle_root=bundle_root, incident_check_fn=lambda _a: None, fleet_safety_check_fn=lambda _a: {"online": False, "blocked": False, "reason": None})
    bundle, asset_bytes = _write_sample_bundle(bundle_root, gen=runner.state_gen())

    class FakeProc:
        def poll(self):
            return 1

    big_log = wd / "cell-job-api" / "20261123-000001-abcdef.log"
    big_log.write_text(("noise line\n" * 600) + json.dumps({"result": "stopped: empty", "failure_bundle_id": bundle["bundle_id"]}) + "\n", encoding="utf-8")
    runner.runs["20261123-000001-abcdef"] = {
        "job": "auto_pick", "params": {}, "argv": ["python"], "proc": FakeProc(), "log": big_log,
        "moving": False, "camera": False, "arm": "arm_s", "purpose": "p", "holder": "arm_s",
        "start": time.time(), "expires_at": time.time() + 60, "audited": False,
    }

    token, mtok = "h" * 32, "m" * 32
    server = api.make_server("127.0.0.1", 0, token, runner, viewer=f"http://127.0.0.1:{viewer.server_port}", machine_token=mtok)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        cli = client_mod.CellJobClient(base, mtok)

        r = cli.readiness()
        CellReadiness.model_validate(r)
        assert r["schema"] == "rosy.cell-readiness.v1" and set(r["arms"]) == {"arm_s", "arm_a", "arm_b"}

        listed = cli.failures(arm="arm_s")
        assert len(listed["bundles"]) == 1 and listed["bundles"][0]["bundle_id"] == bundle["bundle_id"]
        latest = cli.latest_failure(arm="arm_s")
        assert latest["bundle_id"] == bundle["bundle_id"]
        got_b = cli.failure(bundle["bundle_id"])
        assert got_b["context_sha256"] == bundle["context_sha256"]
        assert cli.failure_asset(bundle["bundle_id"], "arm_s_wrist-00.jpg") == asset_bytes

        # Tampered asset & traversal must fail closed with 400
        (bundle_root / bundle["bundle_id"] / "arm_s_wrist-00.jpg").write_bytes(b"tampered")
        with pytest.raises(client_mod.CellJobError) as exc_tamper:
            cli.failure_asset(bundle["bundle_id"], "arm_s_wrist-00.jpg")
        assert exc_tamper.value.status_code == 400
        with pytest.raises(client_mod.CellJobError) as exc_trav:
            cli._request("GET", "/failures/%2e%2e/secret")
        assert exc_trav.value.status_code == 400

        # Frame headers preserved
        frame_bytes, fhdrs = cli.frame_with_headers("top")
        assert frame_bytes == jpg
        lower = {k.lower(): v for k, v in fhdrs.items()}
        assert lower["x-frame-seq"] == "123" and lower["x-source-stamp"] == "1000.5" and lower["etag"] == '"seq-123"'

        # Job get extracts structured result beyond 4000-byte log tail; non-moving exit must not bump cell_state_gen.
        jinfo = cli.get("20261123-000001-abcdef")
        assert jinfo["structured_result"]["result"] == "stopped: empty"
        assert jinfo["failure_bundle_id"] == bundle["bundle_id"]
        assert cli.readiness()["cell_state_gen"] == r["cell_state_gen"]
    finally:
        server.shutdown()
        server.server_close()
        viewer.shutdown()
        viewer.server_close()


def test_cell_state_gen_invariants_and_nested_recent_attempts(tmp_path, monkeypatch):
    import cell_bundle_emit as emit

    wd = _make_workdir(tmp_path)
    bundle_root = tmp_path / "bundles"
    monkeypatch.setattr(api, "_check_arm_incident", lambda _arm: None)
    monkeypatch.setattr(api, "_session_lock_held", lambda _arm, _ld=None: False)
    monkeypatch.setattr(api, "_whole_cell_lock_held", lambda _ld=None: False)
    monkeypatch.setattr(api, "_check_depth_lock_held", lambda _ld=None: False)
    runner = api.Runner(wd, lock_dir=wd, bundle_root=bundle_root, incident_check_fn=lambda _a: None, fleet_safety_check_fn=lambda _a: {"online": False, "blocked": False, "reason": None})

    gen0 = runner.state_gen()
    # 1. Non-moving job start + exit keeps cell_state_gen unchanged.
    runner.runs["nm-1"] = {
        "job": "upkeep_check", "params": {}, "argv": ["python"], "proc": type("P", (), {"poll": lambda _s: 0})(), "log": wd / "nm.log",
        "moving": False, "camera": False, "arm": None, "purpose": "p", "holder": "h", "start": time.time(), "expires_at": time.time() + 60, "audited": False,
    }
    assert runner.queue()["active"] == []
    assert runner.state_gen() == gen0

    # 2. Moving job start bumps +1; failed exit (code != 0) leaves cell_state_gen unchanged so its failure bundle passes fence.
    pick_params = {
        "arm": "arm_s", "config": "cell-s.json", "catalog": "catalog-live.json",
        "roi": [0, 0, 10, 10], "source": "inbound", "dest": "outbound", "person_at_switch": True,
    }
    procs = []
    monkeypatch.setattr(api.subprocess, "Popen", lambda argv, **kw: procs.append(argv) or type("P", (), {"poll": lambda _s: None})())
    res_fail = runner.start("auto_pick", pick_params)
    assert res_fail["code"] == 202, res_fail
    gen_during_fail = runner.state_gen()
    assert gen_during_fail == gen0 + 1
    b_fail, _ = _write_sample_bundle(bundle_root, arm="arm_s", kind="stop", gen=gen_during_fail)
    runner.runs[res_fail["id"]]["proc"] = type("P", (), {"poll": lambda _s: 1})()
    assert runner.queue()["active"] == []
    assert runner.state_gen() == gen_during_fail
    reloaded = cfc.load_bundle(bundle_root, b_fail["bundle_id"], current_cell_state_gen=runner.state_gen())
    assert reloaded["freshness"]["gen_matches"] is True
    assert cfc.check_fence(reloaded, expected_context_sha256=reloaded["context_sha256"], expected_cell_state_gen=gen_during_fail, current_cell_state_gen=runner.state_gen())[0] is True

    # 3. Succeeded moving job (code == 0) bumps +1 on exit.
    res_ok = runner.start("auto_pick", pick_params)
    assert res_ok["code"] == 202, res_ok
    assert runner.state_gen() == gen_during_fail + 1
    runner.runs[res_ok["id"]]["proc"] = type("P", (), {"poll": lambda _s: 0})()
    assert runner.queue()["active"] == []
    assert runner.state_gen() == gen_during_fail + 2

    # 4. cell_bundle_emit preserves nested dicts in recent_attempts (e.g. auto.object) while respecting MAX_DEPTH <= 6.
    (wd / "attempts.jsonl").write_text(
        json.dumps({"attempt": 0, "auto": {"object": "container-3", "colour": "red", "bias_region": {"side": "left"}}}) + "\n",
        encoding="utf-8",
    )
    cfg = {"arm_id": "arm_s", "work_dir": str(wd), "failure_bundle_root": str(bundle_root), "cameras": {}}
    bid = emit._emit_common(cell=None, config=cfg, work=wd, kind="stop", executor_mode="ik_auto_pick", attempt_cause="empty", stage="pick", result_text="stopped: empty")
    assert bid
    emitted = cfc.load_bundle(bundle_root, bid)
    CellFailureContext.model_validate(emitted)
    rec = emitted["history_and_constraints"]["recent_attempts"]
    assert isinstance(rec[0]["auto"], dict) and rec[0]["auto"]["object"] == "container-3"


def test_five_non_motion_jobs_machine_authorized_and_argv(tmp_path, monkeypatch):
    wd = _make_workdir(tmp_path)
    monkeypatch.setattr(api, "_check_depth_lock_held", lambda _ld=None: True)
    procs = []
    monkeypatch.setattr(api.subprocess, "Popen", lambda argv, **kw: procs.append(argv) or Mock(poll=lambda: None))
    runner = api.Runner(wd, lock_dir=wd, incident_check_fn=lambda _a: "held", fleet_safety_check_fn=lambda _a: {"online": True, "blocked": True, "reason": "estop"})
    machine = api.Principal(api.ROLE_MACHINE, "agy-agent")

    cases = [
        ("upkeep_check", {"manifest": "upkeep-arms.json"}, ["--mode", "autonomous"]),
        ("capture_clip", {"view": "top", "duration_s": 2, "fps": 5}, ["capture-clip", "--view", "top", "--duration-s", "2"]),
        ("convert_episodes", {"episodes": "ep-raw", "out": "ds-out", "repo_id": "robotteam/omx_s3"}, ["convert-episodes", "--repo-id", "robotteam/omx_s3"]),
        ("transfer_dataset", {"collection": "col_001"}, ["transfer-dataset", "--collection", "col_001"]),
        ("stage_policy_bundle", {"run_id": "run_001", "target_dir": "models/staged"}, ["stage-policy-bundle", "--run-id", "run_001"]),
    ]
    for jname, params, expected in cases:
        res = runner.start(jname, params, principal=machine)
        assert res["code"] == 202, f"{jname} blocked: {res}"
        argv_line = " ".join(procs[-1])
        for piece in expected:
            assert piece in argv_line
    assert "DO_NOT_TRAIN" not in " ".join(procs[-1])


def test_media_jobs_clip_convert_transfer_and_stage_policy_bundle(tmp_path, monkeypatch):
    jpg = _sample_jpg()

    class MockResp:
        status = 200

        def __init__(self, data: bytes, hdrs=None):
            self._data, self.headers = data, hdrs or {"X-Frame-Seq": "9"}

        def read(self):
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    clip_out = media_jobs.capture_clip(
        "top", 1, tmp_path / "clips", fps=2, viewer_url="http://127.0.0.1:8767",
        urlopen_fn=lambda _url, timeout=5: MockResp(jpg), sleep_fn=lambda _s: None,
    )
    assert clip_out["ok"] and Path(clip_out["file"]).is_file() and 0 < clip_out["bytes"] <= media_jobs.MAX_CLIP_BYTES

    # convert_episodes blocks DO_NOT_TRAIN.txt
    ep_dir = tmp_path / "episodes"
    (ep_dir / "ep0").mkdir(parents=True)
    (ep_dir / "ep0" / "DO_NOT_TRAIN.txt").write_text("stop", encoding="utf-8")
    with pytest.raises(ValueError, match="DO_NOT_TRAIN"):
        media_jobs.convert_episodes(ep_dir, tmp_path / "ds", "robotteam/test_ds")

    # transfer_dataset blocks open/corrupt collections and pushes sealed CLOSED hardware collection
    cols = tmp_path / "collections"
    c_bad = cols / "col_open"
    c_bad.mkdir(parents=True)
    (c_bad / "manifest.json").write_text(json.dumps({"schema": "rosy.omx-collection-session.v1", "state": "RUNNING", "mode": "hardware"}), encoding="utf-8")
    with pytest.raises(ValueError, match="CLOSED"):
        media_jobs.transfer_dataset("col_open", prep_dir=tmp_path, collections_root=cols)

    c_ok = cols / "col_ok"
    (c_ok / "dataset" / "meta").mkdir(parents=True)
    (c_ok / "dataset" / "data" / "chunk-000").mkdir(parents=True)
    pq = c_ok / "dataset" / "data" / "chunk-000" / "ep0.parquet"
    pq.write_bytes(b"parquet-bytes")
    info_f = c_ok / "dataset" / "meta" / "info.json"
    info_f.write_text(json.dumps({"total_episodes": 1}), encoding="utf-8")
    (c_ok / "manifest.json").write_text(json.dumps({
        "schema": "rosy.omx-collection-session.v1", "state": "CLOSED", "mode": "hardware",
        "source_mode": "leader_native", "total_episodes": 1, "arm_id": "arm_s",
        "files": {
            "dataset/data/chunk-000/ep0.parquet": hashlib.sha256(b"parquet-bytes").hexdigest(),
            "dataset/meta/info.json": hashlib.sha256(info_f.read_bytes()).hexdigest(),
        },
    }), encoding="utf-8")
    pushed = media_jobs.transfer_dataset(
        "col_ok", prep_dir=tmp_path, collections_root=cols,
        push_fn=lambda _d, _cfg, verified=None: {"status": "done", "ok": True, "remote_path": "~/rosy-test/omx-collections/col_ok", "verification": verified},
        intake_fn=lambda _cfg, _tr: {"status": "done", "ok": True, "response": {"job_id": "intake-1"}},
    )
    assert pushed["ok"] and pushed["total_episodes"] == 1
    assert media_jobs.main(["--workdir", str(tmp_path), "transfer-dataset", "--collection", "col_ok", "--collections-root", str(cols)]) == 1

    # stage_policy_bundle: atomic promotion + SHA-256 verification & rollback on mismatch
    w_bytes = b"safetensors-weights"
    c_bytes = b'{"type":"act"}'
    manifest = {"schema": "rosy.canonical-bundle.v1", "run_id": "run_42", "files": {
        "model.safetensors": hashlib.sha256(w_bytes).hexdigest(),
        "config.json": hashlib.sha256(c_bytes).hexdigest(),
    }}
    mf_bytes = json.dumps(manifest).encode("utf-8")

    class FakeOpener:
        def __init__(self, corrupt=False):
            self.corrupt = corrupt

        def __call__(self, req, timeout=15):
            u = req.full_url
            if u.endswith("/bundle-manifest"):
                return MockResp(mf_bytes)
            if u.endswith("/model.safetensors"):
                return MockResp(b"CORRUPT" if self.corrupt else w_bytes)
            return MockResp(c_bytes)

    stage_root = tmp_path / "staged"
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        media_jobs.stage_policy_bundle("run_42", stage_root, learning_url="http://127.0.0.1:8768", opener=FakeOpener(corrupt=True))
    assert not list(stage_root.glob("*"))

    ok_stage = media_jobs.stage_policy_bundle("run_42", stage_root, learning_url="http://127.0.0.1:8768", opener=FakeOpener(corrupt=False))
    assert ok_stage["ok"] and (stage_root / "run_42" / "model.safetensors").read_bytes() == w_bytes


def test_ring_uses_frame_receipt_and_stills_always_ring(tmp_path):
    jpg = _sample_jpg()
    seq = [0]

    def receipt(cam):
        seq[0] += 1
        if seq[0] % 3 == 0:
            raise ValueError("HTTP 304")
        return {"camera": cam, "source_seq": seq[0], "source_stamp": 100.0 + seq[0], "jpeg_bytes": jpg}

    ring = ev.Ring(lambda _c: np.zeros((4, 4, 3), np.uint8), ["top"], period_s=0.01, keep_s=0.5, frame_receipt=receipt)
    time.sleep(0.08)
    ring.close()
    meta_frames, gaps = ring.window_with_meta(0.0)
    assert meta_frames and all(m["source_seq"] is not None for m in meta_frames)
    assert any("304" in why for _, _, why in gaps)

    st = cell_hooks.stills(type("C", (), {"frame": lambda _s, _c: np.zeros((4, 4, 3), np.uint8), "frame_receipt": staticmethod(receipt)})(), {"arm_id": "arm_s", "cameras": {"top": {}}}, always_ring=True)
    assert st.ring is not None
    st.close()


def test_auto_pick_and_policy_drive_emit_valid_bundles_and_incident_fleet(tmp_path, monkeypatch):
    import cell_auto_pick as auto_pick
    import cell_calibration as cal
    import cell_choices

    bundle_root = tmp_path / "state" / "failure-bundles"
    monkeypatch.setenv("ROSY_OMX_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("ROSY_OMX_HOME", str(tmp_path / "arm-home"))
    monkeypatch.setattr(oi, "INCIDENTS", tmp_path / "incidents")

    # 1. auto_pick failure emits valid CellFailureContext bundle
    cfg = json.loads((OMX / "cell-pipeline.example.json").read_text(encoding="utf-8"))
    cfg["arm_id"] = "arm_s"
    cfg["failure_bundle_root"] = str(bundle_root)
    cfg["cameras"] = {"top": cfg["cameras"]["top"], "arm_s_wrist": "http://127.0.0.1:8767/frame/arm_s_wrist.jpg"}
    cfg["missing_cameras"] = ["arm_b_wrist"]
    cal_path = tmp_path / "cal.json"
    cal_path.write_text(json.dumps({"schema": "rosy.omx-cell-calibration.v1", "sites": {}, "plan": cfg.get("plan") or {}}), encoding="utf-8")

    class MinimalCell:
        def act(self, cmd):
            extra = {"human_hold_latched": True, "torque_hold_commanded": True} if cmd == "human-hold" else {}
            return {"ok": True, "command": cmd, "state": [0.0] * 6, "settled": True, **extra}

        def frame(self, _cam):
            return np.full((32, 32, 3), 100, np.uint8)

    res = auto_pick.run_auto(
        MinimalCell(), cfg, cal.load(cal_path), cal_path, [], [0, 0, 100, 100], "pinky", "belt",
        tmp_path, cell_choices.Choices(tmp_path / "choices.json"), dry_run=False, log=lambda _r: None,
    )
    assert res["result"].startswith("held:") and "failure_bundle_id" in res
    loaded = cfc.load_bundle(bundle_root, res["failure_bundle_id"])
    CellFailureContext.model_validate(loaded)
    assert loaded["visual"]["camera_manifest"]["arm_b_wrist"]["status"] == "missing_device"

    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()
    prev_cwd = Path.cwd()
    monkeypatch.chdir(other_cwd)
    ev_pick = oif.evidence_of(0.0, arm="arm_s")
    monkeypatch.chdir(prev_cwd)
    assert ev_pick is not None and any("wrist" in f for f in ev_pick["files"])

    # 2. policy_drive emits PolicyCapture failure bundle outside timed loop
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    w = b"weights"
    (model_dir / "model.safetensors").write_bytes(w)
    (model_dir / "config.json").write_text(json.dumps({
        "type": "act", "n_action_steps": 4, "chunk_size": 8,
        "input_features": {"observation.state": {"shape": [6]}, "observation.images.top": {"shape": [3, 8, 8]}},
        "output_features": {"action": {"shape": [6]}},
    }), encoding="utf-8")
    pcal = tmp_path / "mcal.json"
    pcal.write_text(json.dumps({n: {"id": i, "drive_mode": 0, "homing_offset": 0, "range_min": 0, "range_max": 4095}
                                for i, n in enumerate(("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"))}), encoding="utf-8")
    lib_p = tmp_path / "lib.json"
    lib_p.write_text(json.dumps({"fps": 30, "gripper_closed": 46.6, "chunks": {"home": [[0] * 6, [0] * 6]}}), encoding="utf-8")
    pcfg = tmp_path / "pcell.json"
    pcfg.write_text(json.dumps({
        "arm_id": "arm_s", "io": str(tmp_path), "work_dir": str(tmp_path / "pwork"),
        "calibration_path": str(cal_path), "failure_bundle_root": str(bundle_root),
        "cameras": {"top": "http://127.0.0.1:8767/frame/top.jpg"},
    }), encoding="utf-8")

    monkeypatch.setattr(policy_drive, "demonstrated_range", lambda *_a, **_kw: ([0.0] * 6, [10.0] * 6))
    monkeypatch.setattr(policy_drive.lrs, "LeRobotShadow", lambda *_a, **_kw: type("S", (), {
        "sim_rule": None, "goal_size": None, "chunk_size": 8, "n_action_steps": 4, "image_views": {"top": (8, 8)},
        "files": {}, "inputs": lambda _s, st, fr: ({"state": st}, {}), "infer": lambda _s, _o: type("R", (), {"chunk": [[999.0] * 6] * 8})(),
    })())
    import cell_pipeline as cp
    monkeypatch.setattr(cp, "FifoCell", lambda *_a, **_kw: MinimalCell())
    exit_code = policy_drive.main([
        "--config", str(pcfg), "--library", str(lib_p), "--mode", "act",
        "--policy-root", str(model_dir), "--policy-revision", hashlib.sha256(w).hexdigest(),
        "--model-calibration", str(pcal), "--cell-calibration", str(pcal),
        "--operator", "human_op", "--person-at-switch", "--max-chunks", "1",
    ])
    assert exit_code == 1
    p_rows = cfc.list_bundles(bundle_root, arm="arm_s", kind="policy_fail", limit=5)
    assert p_rows and CellFailureContext.model_validate(cfc.load_bundle(bundle_root, p_rows[0]["bundle_id"]))

    # 3. omx_incident_fleet finds failure-context evidence independent of CWD & enriches report_for
    monkeypatch.chdir(other_cwd)
    ev_latest = oif.evidence_of(0.0, arm="arm_s")
    assert ev_latest is not None and p_rows[0]["bundle_id"] in ev_latest["bundle"]
    summary = oif.latest_failure_summary("arm_s", 0.0, bundle_root=bundle_root)
    assert summary is not None and "bundle_id" in summary
    rep = oif.report_for("omx_arm_s", "6f1c2a3e-1b2d-4e5f-8a9b-0c1d2e3f4a5b", {
        "safe_end": True, "latched": {}, "windup_hits": [], "fault_records": [], "frames": [], "failure_context": summary,
    }, {"hold": False, "actions": [], "offered": [], "reason": "ok"}, None)
    assert rep.facts["failure_context"]["bundle_id"] == summary["bundle_id"]


def test_pr3_b1_path_confinement_and_b2_canonical_list_manifest(tmp_path, monkeypatch):
    wd = _make_workdir(tmp_path)
    runner = api.Runner(wd, lock_dir=wd, incident_check_fn=lambda _a: None, fleet_safety_check_fn=lambda _a: {"online": False, "blocked": False, "reason": None})
    machine = api.Principal(api.ROLE_MACHINE, "agy-agent")

    # B1: transfer_dataset rejects prep_dir param; media jobs reject abs, ~/, .. paths
    assert runner.start("transfer_dataset", {"collection": "col_001", "prep_dir": "/tmp/evil"}, principal=machine)["code"] == 400
    assert runner.start("capture_clip", {"view": "top", "duration_s": 1, "out_dir": "/tmp/evil"}, principal=machine)["code"] == 400
    assert runner.start("stage_policy_bundle", {"run_id": "run_1", "target_dir": "~/evil"}, principal=machine)["code"] == 400
    assert runner.start("convert_episodes", {"episodes": "../escape", "out": "ds", "repo_id": "a/b"}, principal=machine)["code"] == 400
    assert runner.start("convert_episodes", {"episodes": "ep", "out": "ds", "repo_id": "a..b/c"}, principal=machine)["code"] == 400

    # Nested DO_NOT_TRAIN.txt at depth 3 blocked
    deep_ep = wd / "ep_nested" / "a" / "b" / "c"
    deep_ep.mkdir(parents=True)
    (deep_ep / "DO_NOT_TRAIN.txt").write_text("hold", encoding="utf-8")
    with pytest.raises(ValueError, match="DO_NOT_TRAIN"):
        media_jobs.convert_episodes("ep_nested", "ds_out", "org/repo", workdir=wd)

    # B2: canonical :8768 list-shaped manifest + bytes check + bundle-manifest.json ban + on-disk re-verify
    w_bytes = b"weights-v2"
    c_bytes = b'{"type":"act"}'
    canon_mf = {
        "schema": "rosy.canonical-bundle-manifest.v1",
        "run_id": "run_list",
        "files": [
            {"path": "model.safetensors", "bytes": len(w_bytes), "sha256": hashlib.sha256(w_bytes).hexdigest()},
            {"path": "config.json", "bytes": len(c_bytes), "sha256": hashlib.sha256(c_bytes).hexdigest()},
        ],
    }
    canon_bytes = json.dumps(canon_mf).encode("utf-8")

    class Resp:
        status = 200
        headers = {}

        def __init__(self, d): self._d = d
        def read(self, _n=None): return self._d
        def __enter__(self): return self
        def __exit__(self, *_): return False

    def opener_canon(req, timeout=15):
        u = req.full_url
        if u.endswith("/bundle-manifest"):
            return Resp(canon_bytes)
        if u.endswith("/model.safetensors"):
            return Resp(w_bytes)
        return Resp(c_bytes)

    res1 = media_jobs.stage_policy_bundle("run_list", "models", learning_url="http://127.0.0.1:8768", opener=opener_canon, workdir=wd)
    assert res1["ok"] and not res1.get("already_staged")
    res2 = media_jobs.stage_policy_bundle("run_list", "models", learning_url="http://127.0.0.1:8768", opener=opener_canon, workdir=wd)
    assert res2.get("already_staged") is True

    # Tampered staged file must NOT report already_staged=True (both byte-size & same-length SHA-256 tamper)
    (wd / "models" / "run_list" / "model.safetensors").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="byte size mismatch"):
        media_jobs.stage_policy_bundle("run_list", "models", learning_url="http://127.0.0.1:8768", opener=opener_canon, workdir=wd)
    (wd / "models" / "run_list" / "model.safetensors").write_bytes(b"X" * len(w_bytes))
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        media_jobs.stage_policy_bundle("run_list", "models", learning_url="http://127.0.0.1:8768", opener=opener_canon, workdir=wd)

    # Reserved filename bundle-manifest.json rejected
    bad_mf = json.dumps({"files": [{"path": "bundle-manifest.json", "bytes": 2, "sha256": "a" * 64}]}).encode("utf-8")
    with pytest.raises(ValueError, match="invalid manifest entry path"):
        media_jobs.stage_policy_bundle("run_bad", "models", learning_url="http://127.0.0.1:8768", opener=lambda _r, timeout=15: Resp(bad_mf), workdir=wd)


def test_pr3_b3_readiness_cell_ab_fleet_two_arm_and_session_lock(tmp_path, monkeypatch):
    wd = _make_workdir(tmp_path)
    bundle_root = tmp_path / "bundles"
    monkeypatch.setattr(api, "_check_arm_incident", lambda _arm: None)
    monkeypatch.setattr(api, "_whole_cell_lock_held", lambda _ld=None: False)
    monkeypatch.setattr(api, "_check_depth_lock_held", lambda _ld=None: False)
    monkeypatch.setattr(api, "_session_lock_held", lambda arm, _ld=None: arm == "arm_s")

    def fake_fleet(arm):
        if arm == "arm_a":
            return {"online": True, "blocked": True, "reason": "HUMAN_HOLD on cell_ab"}
        return {"online": True, "blocked": False, "reason": None}

    runner = api.Runner(wd, lock_dir=wd, bundle_root=bundle_root, incident_check_fn=lambda _a: None, fleet_safety_check_fn=fake_fleet)

    class RunningProc:
        def poll(self): return None

    runner.runs["job-ab"] = {
        "job": "cell_two_arm_policy", "params": {}, "argv": ["python"], "proc": RunningProc(), "log": wd / "x.log",
        "moving": True, "camera": False, "arm": "arm_ab", "arms": ("arm_a", "arm_b"),
        "purpose": "p", "holder": "h", "start": time.time(), "expires_at": time.time() + 60, "audited": False,
    }
    from cell_job_readiness import build_readiness

    r = build_readiness(runner, whole_cell_lock_fn=lambda _l: False, session_lock_fn=api._session_lock_held, depth_lock_fn=lambda _l: False)
    CellReadiness.model_validate(r)
    assert r["allowed_tiers_now"] == [0]
    assert any(ref.startswith("fleet_safety:cell_ab:") for ref in r["blocking_refusals"])
    assert "session_lock:arm_s" in r["blocking_refusals"]
    assert r["arms"]["arm_a"]["active_job_id"] == "job-ab" and r["arms"]["arm_b"]["active_job_id"] == "job-ab"
    assert r["arms"]["arm_a"]["fleet_safety"]["blocked"] is True and r["arms"]["arm_s"]["fleet_safety"]["blocked"] is False


def test_pr3_b4_amr_bed_veto_and_wrist_fallback_preserved(tmp_path):
    import cell_bundle_emit as emit

    jpg = _sample_jpg()
    bundle_root = tmp_path / "bundles"

    class FakeRing:
        keep_s = 4.0

        def window_with_meta(self, _since):
            return ([{"t": 100.0, "camera": "top", "jpeg": jpg, "source_seq": 1, "source_stamp": 99.5}], [])

    class FakeCell:
        def act(self, _c): return {"ok": True, "state": [0.0] * 6, "settled": True}
        def frame(self, _cam): return np.full((16, 16, 3), 90, np.uint8)

    cfg = {"arm_id": "arm_s", "failure_bundle_root": str(bundle_root), "cameras": {"top": {}, "arm_s_wrist": {}}}
    bid = emit.emit_pick_failure(
        FakeCell(), cfg, {"sites": {}}, "tray:1", "belt", tmp_path, {"result": "stopped: empty"},
        {"transfer": {"result": "empty", "at": "run grasp_pick", "steps": []}, "fail": {"stage": "transfer", "class": "empty"}},
        stills=type("S", (), {"ring": FakeRing(), "last_tips": {}, "close": lambda _s: None})(),
    )
    assert bid
    loaded = cfc.load_bundle(bundle_root, bid)
    CellFailureContext.model_validate(loaded)
    assert loaded["spatial"]["sites"]["is_amr_bed"] is True
    assert any(v["code"] == "AMR_BED_REQUIRES_FLEET_R" for v in loaded["history_and_constraints"]["measured_vetoes"])
    cams_in_frames = {f["camera"] for f in loaded["visual"]["frames"]}
    assert "arm_s_wrist" in cams_in_frames and "top" in cams_in_frames

    # PolicyCapture propagates site/goal_site AMR bed veto
    log_p = tmp_path / "pd.jsonl"
    log_p.write_text("", encoding="utf-8")
    with emit.PolicyCapture(FakeCell(), cfg, work=tmp_path, mode="act", paced_chunks=True, dry_run=False, log_path=log_p, site="belt", goal_site="tray-l1") as cap:
        bid_p = cap.emit_if_failed({"result": "stopped", "reason": "stalled", "at": 2})
    assert bid_p
    lp = cfc.load_bundle(bundle_root, bid_p)
    assert lp["spatial"]["sites"]["is_amr_bed"] is True
    assert any(v["code"] == "AMR_BED_REQUIRES_FLEET_R" for v in lp["history_and_constraints"]["measured_vetoes"])
