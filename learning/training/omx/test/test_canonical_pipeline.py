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
    trap_target = tmp_path / "outside.json"
    trap_target.write_text(json.dumps({"verdict": "fake"}))
    (watch / "eval_l1").mkdir()
    (watch / "eval_l1" / "evil.json").symlink_to(trap_target)

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
    assert cp.CanonicalService(tmp_path / "no_tok", None).verify_peer_bearer("Bearer whatever") is False


def test_host_telemetry_normal_na_timeout_and_disk_thresholds(tmp_path, monkeypatch):
    import canonical_telemetry as ct

    now = [1000.0]
    calls = []

    def runner_ok(cmd, timeout=2.0):
        calls.append(cmd)
        return (0, "RTX 5080 Laptop GPU, 97, 3936, 16303, 59, [N/A]\n")

    monkeypatch.setattr(ct.shutil, "disk_usage", lambda p: SimpleNamespace(free=50 * 1024**3, total=300 * 1024**3))
    tel = ct.HostTelemetry(lambda: tmp_path, ttl_s=5.0, runner=runner_ok, clock=lambda: now[0])
    s1 = tel.snapshot()
    assert s1["stale"] is False and s1["gpu"]["available"] is True and s1["gpu"]["util_pct"] == 97
    assert s1["gpu"]["vram_used_mib"] == 3936 and s1["gpu"]["power_w"] is None
    assert s1["disk"]["state"] == "warn" and str(tmp_path) not in json.dumps(s1)

    now[0] = 1002.0
    assert tel.snapshot()["stale"] is False and len(calls) == 1  # cached within TTL

    def runner_timeout(cmd, timeout=2.0):
        calls.append("timeout")
        raise ct.subprocess.TimeoutExpired(cmd, timeout)

    tel_to = ct.HostTelemetry(lambda: tmp_path, ttl_s=0.0, runner=runner_timeout, clock=lambda: now[0])
    s2 = tel_to.snapshot()
    assert s2["gpu"]["available"] is False
    # Second call during 60s cooldown must not re-invoke runner.
    monkeypatch.setattr(ct.shutil, "disk_usage", lambda p: SimpleNamespace(free=10 * 1024**3, total=300 * 1024**3))
    now[0] = 1010.0
    tel_to.snapshot()
    import time as _time
    _time.sleep(0.05)
    assert tel_to.snapshot()["disk"]["state"] == "crit"
    assert calls.count("timeout") == 1


def test_scan_watch_dir_parses_train_eval_logs_markers_and_scrubs(tmp_path):
    watch = tmp_path / "watch_mp"
    watch.mkdir()
    (watch / "collect.done").write_text("48\n", encoding="utf-8")
    (watch / "arm_b.train.log").write_text(
        "\x1b[32mTraining:  17%|##| 1248/7500 [03:10<15:52,  6.56step/s]\x1b[0m\r"
        "INFO step:1K loss:0.099 grdn:2.309 lr:9.7e-05 /home/alice/secret Bearer tok123456\n",
        encoding="utf-8",
    )
    (watch / "arm_a.train.log").write_text(
        "Training: 100%|##| 7500/7500 [19:33<00:00,  6.39step/s]\r"
        "INFO step:8K loss:nan grdn:1.767 lr:1.4e-06\nEnd of training\n",
        encoding="utf-8",
    )
    (watch / "arm_b_ladder").mkdir()
    (watch / "arm_b_ladder" / "dev-002500.log").write_text(
        "EVAL 3101 arm_b ship-h1r1-l0 fail /home/rosy/x\nEVAL 3102 arm_b ship-h1r2-l0 pass 139.3 True\n",
        encoding="utf-8",
    )
    (watch / "arm_b_ladder" / "002500.json").write_text(json.dumps({
        "verdict": "pass", "real_evidence": True, "path": "/tmp/bad",
    }), encoding="utf-8")

    scanned = cp.scan_watch_dir(watch, {"id": "mp", "label": "Model PC", "host_id": "model"})
    raw_dump = json.dumps(scanned, allow_nan=False)
    assert "/home/alice" not in raw_dump and "tok123456" not in raw_dump and "/home/rosy" not in raw_dump
    assert scanned["markers"]["collect.done"]["present"] is True
    by_arm = {t["arm"]: t for t in scanned["training"]}
    assert by_arm["arm_b"]["step"] == 1248 and by_arm["arm_b"]["total_steps"] == 7500 and by_arm["arm_b"]["loss"] == 0.099
    assert by_arm["arm_a"]["ended"] is True and by_arm["arm_a"]["loss"] is None
    assert scanned["eval_progress"][0]["checkpoint"] == "002500" and scanned["eval_progress"][0]["successes"] == 1
    assert scanned["eval_ladder"][0]["folder"] == "arm_b_ladder" and scanned["eval_ladder"][0]["real_evidence"] is False


def test_peer_server_fail_closed_and_single_route(tmp_path):
    import urllib.error
    import urllib.request
    import canonical_telemetry as ct

    tok_file = tmp_path / "peer.token"
    tok_file.write_text("0123456789abcdef0123456789abcdef\n", encoding="utf-8")
    if os.name == "posix":
        tok_file.chmod(0o600)
    watch = tmp_path / "watch_ai"
    watch.mkdir()
    cfg = ct.PeerServerConfig(
        host="127.0.0.1", port=0, host_id="ai",
        token=ct._load_peer_token(tok_file), jobs_dir=tmp_path / "jobs",
        watch_roots={"ai_canon": {"id": "ai_canon", "label": "AI", "host_id": "ai", "path": watch}},
    )
    srv = ct.create_peer_server(cfg, telemetry=ct.HostTelemetry(lambda: watch, runner=lambda *a, **k: (1, "")))
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    base = f"http://127.0.0.1:{srv.server_port}"
    tok = "0123456789abcdef0123456789abcdef"
    try:
        for path, method, hdrs, want in (
            ("/api/learning/canonical/peer-summary", "GET", {}, 403),
            ("/api/learning/canonical/peer-summary", "GET", {"Authorization": "Bearer wrong"}, 403),
            ("/api/learning/canonical/peer-summary?a=1", "GET", {"Authorization": f"Bearer {tok}"}, 400),
            ("/api/learning/canonical", "GET", {"Authorization": f"Bearer {tok}"}, 404),
            ("/api/learning/canonical/peer-summary", "POST", {"Authorization": f"Bearer {tok}"}, 405),
        ):
            req = urllib.request.Request(base + path, data=b"{}" if method == "POST" else None, headers=hdrs, method=method)
            with pytest.raises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(req, timeout=5)
            assert exc.value.code == want

        with urllib.request.urlopen(urllib.request.Request(
            base + "/api/learning/canonical/peer-summary", headers={"Authorization": f"Bearer {tok}"}
        ), timeout=5) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
        assert resp.status == 200 and doc["host_id"] == "ai" and doc["real_evidence"] is False
        assert "host_telemetry" in doc and str(tmp_path) not in json.dumps(doc)
    finally:
        srv.shutdown(); srv.server_close(); th.join(timeout=5)


def test_canonical_workers_wiring_contracts(tmp_path, monkeypatch):
    import types
    import canonical_workers as cw

    spec = oc.default_canonical_spec()
    calls = {"pose_random_passed": False, "tasks_called": [], "cmds": [], "eval_results": []}

    class _FakeDs:
        @classmethod
        def create(cls, *a, **k):
            return cls()
        def add_frame(self, f):
            calls.setdefault("frames", 0)
            calls["frames"] += 1
        def save_episode(self):
            calls.setdefault("eps", 0)
            calls["eps"] += 1
        def finalize(self):
            pass

    monkeypatch.setitem(sys.modules, "lerobot", types.ModuleType("lerobot"))
    monkeypatch.setitem(sys.modules, "lerobot.datasets", types.ModuleType("lerobot.datasets"))
    ld_mod = types.ModuleType("lerobot.datasets.lerobot_dataset")
    ld_mod.LeRobotDataset = _FakeDs
    monkeypatch.setitem(sys.modules, "lerobot.datasets.lerobot_dataset", ld_mod)

    dg_mod = types.ModuleType("data_gate")
    dg_mod.gate = lambda dst, **k: {"counts": {"pass": 2, "review": 0, "reject": 0}}
    dg_mod.check_receipt = lambda dst: [0, 2]
    monkeypatch.setitem(sys.modules, "data_gate", dg_mod)

    class _FakeArm:
        def __init__(self):
            self.wait = [0.0] * 6

    class _FakeLayout:
        def __init__(self, **k):
            self.arms = {"arm_a": _FakeArm(), "arm_b": _FakeArm()}
            self.sim_arms = {"arm_a": _FakeArm(), "arm_b": _FakeArm()}
        def containers(self):
            return []

    class _FakeWorld:
        def __init__(self, layout, **k):
            import numpy as np
            self.q = {"arm_a": slice(0, 6), "arm_b": slice(0, 6)}
            self.act = {"arm_a": slice(0, 6), "arm_b": slice(0, 6)}
            self.renderers = {}
        def render(self, d, view):
            import numpy as np
            return np.zeros((4, 4, 3), dtype=np.uint8)
        def pose(self, d, c):
            return ([0.0, 0.0, 0.02], 0.0)

    class _FakeTeacher:
        def __init__(self, world, seed=0, **extra):
            if "pose_random" in extra:
                calls["pose_random_passed"] = True
            calls.setdefault("teacher_seeds", []).append(seed)
            self.world = world
            self.hook = lambda d, lbl: None
            self.contacts = dict(arm_arm=set(), arm_other=set(), pad_neighbour=set())
            self.carried = None
        def fresh(self, here):
            import numpy as np
            z = np.zeros(6, dtype=np.float32)
            return SimpleNamespace(qpos=z, ctrl=z)
        def run_single(self, here, step):
            self.contacts["arm_arm"].add("leaked_from_teacher")
            d = self.fresh(here)
            self.hook(d, "settle")
            for _ in range(62):
                self.hook(d, step["id"])
            return {"result": "pass"}
        def belt_in(self, d, step, idle):
            calls["belt_in"] = calls.get("belt_in", 0) + 1
        def frame(self, d, tgt, sid):
            pass
        def verdict(self, d, step, row, before):
            return {"result": "pass", "neighbours_disturbed": ["b2"]}

    sites_m = types.ModuleType("omx_two_arm_sites"); sites_m.Layout = _FakeLayout
    world_m = types.ModuleType("omx_two_arm_world"); world_m.World = _FakeWorld; world_m.FPS = 30
    tasks_m = types.ModuleType("omx_two_arm_tasks")
    tasks_m.get_task = lambda layout, name: (calls["tasks_called"].append(name), {
        "name": name, "start": {}, "steps": [{"id": "s1", "container": "b1", "from": "belt", "to": "ship-h1r0-l0", "arm": "arm_a"}],
    })[1]
    teach_m = types.ModuleType("omx_two_arm_teacher"); teach_m.Teacher = _FakeTeacher
    for nm, md in (("omx_two_arm_sites", sites_m), ("omx_two_arm_world", world_m), ("omx_two_arm_tasks", tasks_m), ("omx_two_arm_teacher", teach_m)):
        monkeypatch.setitem(sys.modules, nm, md)

    @cp.contextmanager if hasattr(cp, "contextmanager") else cw.contextmanager
    def _no_lock(jd):
        yield
    monkeypatch.setattr(cw, "_gpu_job_lock", _no_lock)

    out_c = tmp_path / "out_c"; out_c.mkdir()
    res_c = cw.run_collect_dart({
        "arm_id": "arm_a", "spec": spec, "spec_sha256": oc.canonical_spec_sha256(spec),
        "jobs_dir": str(tmp_path / "jobs"),
        "params": {"episodes": 1, "seed": 5201, "jitter_deg": 0.0, "color_random": False, "pose_random": True},
    }, out_c)
    assert res_c["episodes"] == 2 and calls["pose_random_passed"] is False and calls["tasks_called"] == ["stack"]
    assert calls["frames"] == 62  # settle frame ignored

    # train_stage passes admitted --dataset.episodes and writes immutable out/train on resume
    ds_root = tmp_path / "ds"; ds_root.mkdir()
    prev_dir = tmp_path / "prev_run" / "train"
    ckpt = prev_dir / "checkpoints" / "last" / "pretrained_model"
    ckpt.mkdir(parents=True)
    (ckpt / "model.safetensors").write_bytes(b"weights")
    out_t = tmp_path / "new_run"; out_t.mkdir()

    def _fake_run(cmd, env=None, check=False):
        calls["cmds"].append(cmd)
        new_ckpt = out_t / "train" / "checkpoints" / "last" / "pretrained_model"
        new_ckpt.mkdir(parents=True, exist_ok=True)
        (new_ckpt / "model.safetensors").write_bytes(b"new-weights")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cw.subprocess, "run", _fake_run)
    res_t = cw.run_train_stage({
        "arm_id": "arm_a", "spec_sha256": "abc", "jobs_dir": str(tmp_path / "jobs"),
        "params": {"dataset_root": str(ds_root), "resume_train_dir": str(prev_dir), "steps": 100, "batch_size": 4,
                   "save_freq": 50, "seed": 42, "chunk_size": 16, "n_action_steps": 4, "use_vae": False, "kl_weight": 10.0, "lr": 1e-4},
    }, out_t)
    assert res_t["admitted_episodes"] == 2
    cmd_str = " ".join(calls["cmds"][0])
    assert "--dataset.episodes=[0, 2]" in cmd_str and f"--output_dir={out_t / 'train'}" in cmd_str
    assert f"--policy.pretrained_path={ckpt}" in cmd_str and "--resume=true" not in cmd_str

    import contextlib
    import numpy as np
    class _FakeTensor:
        def __init__(self, arr):
            self.arr = arr
        def __getitem__(self, idx):
            return self
        def permute(self, *a):
            return self
        def float(self):
            return self
        def __truediv__(self, other):
            return self
    torch_m = types.ModuleType("torch")
    torch_m.from_numpy = lambda arr: _FakeTensor(arr)
    torch_m.inference_mode = lambda: contextlib.nullcontext()
    monkeypatch.setitem(sys.modules, "torch", torch_m)
    seen_obs_keys = []
    fake_policy = SimpleNamespace(
        config=SimpleNamespace(n_action_steps=4, input_features={"observation.images.top": {}}),
        reset=lambda: None,
        select_action=lambda b: (seen_obs_keys.append(set(b)), SimpleNamespace(cpu=lambda: SimpleNamespace(numpy=lambda: [np.zeros(6, dtype=np.float32)])))[1],
    )
    prof, _ = cw._eval_sim_profile(fake_policy, lambda b: b, lambda x: x, spec, "arm_a", task_name="ship-h1", episodes=1, delay_frames=0, seed_base=700)
    assert prof["arm_link_contacts"] == 0 and prof["neighbour_disturbed"] == 1
    assert prof["policy_successes"] == 1 and calls["teacher_seeds"] == [5201, 700, 700]
    assert "observation.images.top" in seen_obs_keys[0]


def test_canonical_watch_and_token_hardening(tmp_path):
    import canonical_telemetry as ct
    import canonical_watch as cw

    nan_json = tmp_path / "nan.json"
    nan_json.write_text('{"v": NaN}', encoding="utf-8")
    assert cw.read_bounded_json(nan_json, root=tmp_path) is None

    eval_dir = tmp_path / "eval_watch"
    (eval_dir / "arm_b_ladder").mkdir(parents=True)
    real_log = eval_dir / "arm_b_ladder" / "dev-002500.log"
    real_log.write_text("EVAL 3102 arm_b ship-h1r2-l0 pass 139.35 True\n", encoding="utf-8")
    outside = tmp_path / "secret.log"
    outside.write_text("EVAL 1 arm_b x pass 1.0 True\n", encoding="utf-8")
    link_log = eval_dir / "arm_b_ladder" / "dev-001000.log"
    try:
        link_log.symlink_to(outside)
    except OSError:
        pass
    logs = cw._scan_eval_logs(eval_dir)
    assert [row["file"] for row in logs] == ["dev-002500.log"]

    big_tok = tmp_path / "big.token"
    big_tok.write_text("a" * 5000, encoding="utf-8")
    if os.name == "posix":
        big_tok.chmod(0o600)
    with pytest.raises(ValueError, match="bounded|4096"):
        ct.load_peer_token(big_tok)
    if os.name == "posix":
        mode_tok = tmp_path / "open.token"
        mode_tok.write_text("0123456789abcdef0123456789abcdef\n", encoding="utf-8")
        mode_tok.chmod(0o644)
        with pytest.raises(ValueError, match="permissions"):
            ct.load_peer_token(mode_tok)

    # Real hold_gpu.sh lock format is "<pid> gpu 4 8" (additional tokens after PID).
    jobs_dir = tmp_path / "rosy_jobs_fmt"
    jobs_dir.mkdir()
    (jobs_dir / f"train-{os.getpid()}.lock").write_text(f"{os.getpid()} gpu 4 8\n", encoding="utf-8")
    assert ct.external_gpu_locks(jobs_dir) == [f"external:train-{os.getpid()}"]

    # Non-path keys holding host paths (e.g. replay summary.checkpoint) must scrub path values while keeping step IDs.
    replay_watch = tmp_path / "replay_watch"
    (replay_watch / "arm_b_ladder").mkdir(parents=True)
    (replay_watch / "arm_b_ladder" / "replay-s06-002500.json").write_text(json.dumps({
        "summary": {
            "checkpoint": "/home/rosy/rosy-scratch/mix-1122-canon/arm_b/train/checkpoints/002500/pretrained_model",
            "step_id": "002500",
        },
    }), encoding="utf-8")
    scanned = cw.scan_watch_dir(replay_watch, {"id": "mp_canon", "label": "MP", "host_id": "model"})
    summary = scanned["eval_ladder"][0]["summary"]
    assert "/home/" not in json.dumps(scanned)
    assert summary["checkpoint"] == "<path>" and summary["step_id"] == "002500"


def test_canonical_intake_normalizes_bench_data_and_enqueues_idempotent_align(tmp_path):
    import numpy as np
    import canonical_intake as ci
    import data_gate

    spec = oc.default_canonical_spec()
    card_txt = "Take the container from the belt pickup end and place it on ship hold h1, A side row (r0), tier 1 (floor) (l0)."
    norm_txt = ci.normalize_bench_task(card_txt)
    assert norm_txt == "Pick container from belt to ship-h1r0-l0."
    assert data_gate.GOAL_RE.search(norm_txt)
    assert ci.normalize_bench_task("Move ship-h1r1-l0 to tray") == "Move container from ship-h1r1-l0 to tray."
    assert ci.normalize_bench_task("Take the container ... (ship-h1r0-l0 -> belt)") == "Move container from ship-h1r0-l0 to belt."
    assert ci.normalize_bench_task("Take the container ... (ship-h1r0-l0 -> tray)") == "Move container from ship-h1r0-l0 to tray."

    # 12-DOF bi_omx_follower normalized [-100..100] at 30fps -> 6-DOF sim rad + linear gripper + 15fps.
    g0_b = spec["idle_park"]["arm_b"]["gripper_units"]
    g1_b = spec["canonical_start"]["arm_b"]["gripper_units"]
    raw_b0 = list(spec["idle_park"]["arm_b"]["norm"]) + [g0_b]
    raw_b1 = list(spec["canonical_start"]["arm_b"]["norm"]) + [g1_b]
    row0 = [0.0] * 6 + raw_b0
    row1 = [0.0] * 6 + raw_b1
    arr = np.asarray([row0, row0, row1, row1], dtype=np.float64)
    st_out, ac_out, stride, out_fps = ci.prepare_episode_arrays(
        arr, arr, spec=spec, arm_id="arm_b", robot_type="bi_omx_follower", src_fps=30, target_fps=15,
    )
    assert stride == 2 and out_fps == 15 and st_out.shape == (2, 6) and ac_out.shape == (2, 6)
    assert abs(st_out[0, 5] - spec["sim_jaw_closed"]) < 1e-4
    assert abs(st_out[1, 5] - spec["sim_jaw_open"]) < 1e-4
    assert abs(st_out[0, 1] - (spec["idle_park"]["arm_b"]["norm"][1] * 3.141592653589793 / 100.0)) < 1e-4

    # Explicit record-config.json use_degrees=True converts <= 105 deg with pi/180 (never pi/100).
    deg_col = tmp_path / "deg_col"
    (deg_col / "dataset").mkdir(parents=True)
    (deg_col / "record-config.json").write_text(json.dumps({"robot": {"arm_b": {"use_degrees": True}}}), encoding="utf-8")
    assert ci.detect_source_units(deg_col / "dataset", "arm_b", {}) == "deg"
    deg_arr = np.asarray([[45.0, -45.0, 0.0, 0.0, 0.0, g0_b]], dtype=np.float64)
    deg_out, _, _, _ = ci.prepare_episode_arrays(deg_arr, deg_arr, spec=spec, arm_id="arm_b", src_fps=15, target_fps=15, units="deg")
    assert abs(deg_out[0, 0] - (45.0 * 3.141592653589793 / 180.0)) < 1e-5

    # Collection discovery + full sha256 verification + idempotent intake enqueueing arm_a + arm_b.
    import hashlib
    cols = tmp_path / "collections"
    valid = cols / "bi-sess-01"
    (valid / "dataset" / "meta").mkdir(parents=True)
    (valid / "dataset" / "data" / "chunk-000").mkdir(parents=True)
    p_info = valid / "dataset" / "meta" / "info.json"
    p_pq = valid / "dataset" / "data" / "chunk-000" / "file-000.parquet"
    p_info.write_text(json.dumps({"codebase_version": "v3.0", "robot_type": "bi_omx_follower", "total_episodes": 2}))
    p_pq.write_bytes(b"PAR1")
    files_map = {
        "dataset/meta/info.json": hashlib.sha256(p_info.read_bytes()).hexdigest(),
        "dataset/data/chunk-000/file-000.parquet": hashlib.sha256(p_pq.read_bytes()).hexdigest(),
    }
    mf_bytes = json.dumps({
        "schema": "rosy.omx-collection-session.v1", "state": "CLOSED", "mode": "hardware",
        "source_mode": "leader_native", "robot_type": "bi_omx_follower", "arm_id": "arm_ab", "total_episodes": 2,
        "files": files_map,
    }).encode("utf-8")
    (valid / "manifest.json").write_bytes(mf_bytes)

    dnt = cols / "dnt-sess"
    (dnt / "dataset" / "meta").mkdir(parents=True)
    (dnt / "dataset" / "data" / "chunk-000").mkdir(parents=True)
    (dnt / "dataset" / "meta" / "info.json").write_text("{}")
    (dnt / "dataset" / "data" / "chunk-000" / "ep.parquet").write_bytes(b"x")
    (dnt / "manifest.json").write_bytes(mf_bytes)
    (dnt / "DO_NOT_TRAIN.txt").write_text("stop")

    cfg = _make_config(tmp_path)
    cfg["collections_dir"] = str(cols)
    svc = cp.CanonicalService(tmp_path / "canon_intake_root", cfg)
    snap = svc.snapshot()
    assert "bi-sess-01" in snap["named_sources"] and "dnt-sess" not in snap["named_sources"]

    started = []
    monkeypatch.setattr(svc, "start_job", lambda b: (started.append(b), {"id": b["request_id"], "arm_id": b["arm_id"], "kind": b["kind"]})[1])
    with pytest.raises(ValueError, match="valid collection request fields"):
        svc.intake_collection({"collection": "bi-sess-01", "extra_bad": 1})
    with pytest.raises(ValueError, match="auto_align must be bool"):
        svc.intake_collection({"collection": "bi-sess-01", "auto_align": "yes"})
    with pytest.raises(ValueError, match="disagrees with sealed manifest"):
        svc.intake_collection({"collection": "bi-sess-01", "arm_id": "arm_a"})
    res = svc.intake_collection({"collection": "bi-sess-01"})
    assert res["ok"] is True and res["arms"] == ["arm_a", "arm_b"]
    assert [s["arm_id"] for s in started] == ["arm_a", "arm_b"]
    assert started[0]["params"]["wrist_flip"] is False and started[1]["params"]["wrist_flip"] is True
    assert (svc.root / "intakes" / "bi-sess-01.json").is_file()

    # Bimanual arm feature selection filters opposing arm cameras and maps <arm>_wrist -> wrist.
    bi_feats = {
        "observation.images.top": {}, "observation.images.side": {},
        "observation.images.arm_a_wrist": {}, "observation.images.arm_b_wrist": {},
    }
    f_b, leg_b = ci.select_arm_features(bi_feats, "arm_b")
    assert "observation.images.arm_a_wrist" not in f_b and leg_b["arm_b_wrist"] == "wrist"
    assert data_gate.camera_map(f_b, leg_b) == {
        "observation.images.top": "top", "observation.images.side": "side", "observation.images.arm_b_wrist": "wrist",
    }
