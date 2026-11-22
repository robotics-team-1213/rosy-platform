"""Tests for CanonicalService: unconfigured mode, SQLite idempotency, GPU/CPU locks, watch_roots, PeerClient."""
import http.server
import json
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "learning" / "training" / "omx"))
sys.path.insert(0, str(ROOT / "contracts" / "learning" / "src"))

import canonical_pipeline as cp  # noqa: E402
from rosy.contracts.learning import omx_canonical as oc  # noqa: E402


def _make_config(tmp_path: Path) -> dict:
    for d in ("ds_real", "frames", "watch_ai"):
        (tmp_path / d).mkdir(exist_ok=True)
    lib = tmp_path / "chunks-b.json"
    lib.write_text(json.dumps({"chunks": {"home": [[0.8, -62.2, 53.1, 51.6, 45.2, 48.8]]}}), encoding="utf-8")
    return {
        "schema": cp.CONFIG_SCHEMA,
        "python": {"sim": sys.executable, "train": sys.executable, "cell": sys.executable},
        "jobs_dir": str(tmp_path / "jobs"),
        "named_sources": {
            "real_b": {"kind": "real_dataset", "arm_id": "arm_b", "label": "Real B", "path": str(tmp_path / "ds_real")},
            "real_a": {"kind": "real_dataset", "arm_id": "arm_a", "label": "Real A", "path": str(tmp_path / "ds_real")},
            "live_frames": {"kind": "frames_dir", "arm_id": "arm_b", "label": "Live", "path": str(tmp_path / "frames")},
            "slow_lib": {"kind": "chunk_library", "arm_id": "arm_b", "label": "Lib", "path": str(lib)},
        },
        "watch_roots": {
            "ai_canon": {"label": "AI PC mix-1122-canon", "host_id": "ai", "path": str(tmp_path / "watch_ai")},
        },
    }


def test_unconfigured_service_touches_nothing_and_serves_builtin_spec(tmp_path):
    root = tmp_path / "canonical"
    svc = cp.CanonicalService(root, None, host_id="model")
    assert not root.exists()
    assert svc.configured is False and svc.writable is False
    snap = svc.snapshot()
    assert snap["configured"] is False and snap["spec_sha256"] == oc.canonical_spec_sha256(oc.default_canonical_spec())
    assert snap["real_evidence"] is False and snap["policy_activation"] is False
    with pytest.raises(ValueError, match="not configured"):
        svc.start_job({"request_id": str(uuid.uuid4()), "kind": "collect_dart", "arm_id": "arm_a", "params": {}})


def test_idempotency_concurrency_slots_job_locks_and_cancel(tmp_path, monkeypatch):
    cfg = _make_config(tmp_path)
    svc = cp.CanonicalService(tmp_path / "canon_root", cfg, host_id="model")
    procs = []
    monkeypatch.setattr(cp.os, "killpg", lambda pid, sig: procs.append(("killpg", pid, sig)))
    pid_seq = iter([41001, 41002, 41003, 41004])

    def fake_popen(cmd, **kw):
        pid = next(pid_seq)
        procs.append(("popen", cmd, pid))
        return SimpleNamespace(pid=pid, poll=lambda: None)

    monkeypatch.setattr(cp.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(cp, "process_stamp", lambda pid, req=None: {"pid": pid, "start": "1", "boot": "b"})

    req_id = str(uuid.uuid4())
    gpu_body = {
        "request_id": req_id, "kind": "collect_dart", "arm_id": "arm_b",
        "params": {"episodes": 12, "seed": 5201, "jitter_deg": 2.0, "color_random": True, "pose_random": True},
    }
    first = svc.start_job(gpu_body, check_gpu=False)
    assert first["status"] == "running" and first["gpu_required"] is True
    assert svc.start_job(gpu_body, check_gpu=False) == first  # idempotent
    with pytest.raises(ValueError, match="different inputs"):
        svc.start_job({**gpu_body, "arm_id": "arm_a"}, check_gpu=False)

    # Second GPU job hits BusyConflict; CPU jobs still fit up to 2.
    with pytest.raises(cp.BusyConflict, match="GPU"):
        svc.start_job({**gpu_body, "request_id": str(uuid.uuid4())}, check_gpu=False)

    cpu_req = {
        "request_id": str(uuid.uuid4()), "kind": "align_real", "arm_id": "arm_b",
        "params": {"source_id": "real_b", "wrist_flip": True, "trim_dead_idle": True},
    }
    cpu1 = svc.start_job(cpu_req, check_gpu=False)
    cpu2 = svc.start_job({**cpu_req, "request_id": str(uuid.uuid4()), "arm_id": "arm_a",
                          "params": {"source_id": "real_a", "wrist_flip": False, "trim_dead_idle": True}}, check_gpu=False)
    assert cpu1["gpu_required"] is False and cpu2["gpu_required"] is False
    with pytest.raises(cp.BusyConflict, match="CPU"):
        svc.start_job({**cpu_req, "request_id": str(uuid.uuid4())}, check_gpu=False)

    # Rejects wrist_flip for arm_a.
    with pytest.raises(ValueError, match="arm_b only"):
        svc.start_job({**cpu_req, "request_id": str(uuid.uuid4()), "arm_id": "arm_a",
                       "params": {"source_id": "real_a", "wrist_flip": True, "trim_dead_idle": True}}, check_gpu=False)

    # Cancel verifies process_stamp and kills process group.
    stopped = svc.cancel_job(first["id"])
    assert stopped["status"] == "stopping"
    assert ("killpg", 41001, cp.signal.SIGTERM) in procs

    # Simulate external ~/rosy-jobs/train-<pid>.lock blocking a new GPU job even after marking gpu job done.
    monkeypatch.setattr(cp, "process_stamp", lambda pid, req=None: None)
    (svc.root / "runs" / first["id"] / "output").mkdir(parents=True, exist_ok=True)
    (svc.root / "runs" / first["id"] / "output" / "result.json").write_text(json.dumps({"ok": True}))
    jobs_dir = Path(cfg["jobs_dir"])
    jobs_dir.mkdir(parents=True, exist_ok=True)
    (jobs_dir / f"train-{os.getpid()}.lock").write_text(f"{os.getpid()}\n")
    with pytest.raises(cp.BusyConflict, match="active GPU training lock"):
        svc.start_job({**gpu_body, "request_id": str(uuid.uuid4())}, check_gpu=False)


def test_watch_roots_parses_scratch_layout_refuses_symlinks_and_strips_paths(tmp_path):
    cfg = _make_config(tmp_path)
    watch = Path(cfg["watch_roots"]["ai_canon"]["path"])
    (watch / "real_aligned" / "arm_b" / "real").mkdir(parents=True)
    (watch / "real_aligned" / "align.done").write_text("RC=0\n")
    (watch / "real_aligned" / "arm_b" / "real" / "gate-receipt.json").write_text(json.dumps({
        "arm": "arm_b", "source": {"kind": "real", "layout": "random"},
        "counts": {"pass": 100, "review": 0, "reject": 0}, "dataset_reject": [], "goals_passing": ["ship-h1r0-l0"],
    }))
    (watch / "collect" / "dart-5201" / "arm_a" / "meta").mkdir(parents=True)
    (watch / "collect" / "dart-5201" / "arm_a" / "meta" / "info.json").write_text("{}")
    (watch / "arm_b" / "train" / "checkpoints" / "007500").mkdir(parents=True)
    (watch / "arm_b_cell_live_check.json").write_text(json.dumps({
        "root": "/secret/path",
        "checkpoints": {"007500": {"states": {"canonical_start_open": {
            "goal_3": {"strict_ok": True, "margin_ok": True, "wrist_roll_warning": "frame 0 wrist_roll=13.0"},
        }}}},
    }))
    # Symlink trap inside watch root must be ignored.
    secret = tmp_path / "secret.json"
    secret.write_text(json.dumps({"verdict": "fake"}))
    (watch / "eval_l1").mkdir()
    (watch / "eval_l1" / "evil.json").symlink_to(secret)

    svc = cp.CanonicalService(tmp_path / "canon_root", cfg)
    watched = svc.get_watched("ai_canon")
    assert watched["align_done"] == "RC=0"
    assert watched["collect_seeds"] == {"arm_a": 1, "arm_b": 0}
    assert watched["checkpoints"] == {"arm_b": {"train": ["007500"]}}
    assert watched["eval_ladder"] == []  # symlink rejected!
    assert watched["cell_live_checks"][0]["name"] == "arm_b_cell_live_check.json"
    assert "root" not in watched["cell_live_checks"][0]
    assert "wrist_roll=13.0" in watched["cell_live_checks"][0]["checkpoints"]["007500"]["states"]["canonical_start_open"]["goal_3"]["wrist_roll_warning"]
    assert watched["real_evidence"] is False and watched["policy_activation"] is False


def test_peer_client_rejects_bad_origins_and_handles_timeout_and_ok(tmp_path):
    with pytest.raises(ValueError, match="Tailscale"):
        cp._validate_peer_url("http://8.8.8.8:8768")
    with pytest.raises(ValueError, match="credentials"):
        cp._validate_peer_url("http://user:pass@127.0.0.1:8768")

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            body = json.dumps({"host_id": "ai", "runs": [], "path": "/secret/p"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        client = cp.PeerClient({"ai": {"id": "ai", "label": "AI", "url": f"http://127.0.0.1:{srv.server_port}"}})
        res = client.refresh("ai")
        assert res["status"] == "ok" and res["summary"]["host_id"] == "ai"
        assert "path" not in res["summary"]
    finally:
        srv.shutdown(); srv.server_close()

    dead = cp.PeerClient({"dead": {"id": "dead", "label": "Dead", "url": "http://127.0.0.1:1"}})
    out = dead.refresh("dead")
    assert out["status"] == "unavailable" and out["summary"] is None
