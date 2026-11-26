"""Host unit and concurrency tests for `act_policy_http_server.py` (no torch/lerobot needed)."""
from __future__ import annotations

import ast
import base64
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import sys
import threading
import urllib.error
import urllib.request

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

LEARN_OMX = Path(__file__).resolve().parents[1]
SERVER_PATH = LEARN_OMX / "act_policy_http_server.py"
sys.path.insert(0, str(LEARN_OMX))
try:
    import act_policy_http_server as srv  # noqa: E402
finally:
    sys.path.remove(str(LEARN_OMX))


def _make_checkpoint(root: Path, arm_id: str, *, views=("top", "wrist"), hw=(24, 32), goal_size=None, n_steps=4, chunk_size=8):
    pdir = root / arm_id
    pdir.mkdir(parents=True, exist_ok=True)
    raw = f"weights-{arm_id}".encode("utf-8")
    (pdir / "model.safetensors").write_bytes(raw)
    rev = sha256(raw).hexdigest()
    in_feat = {"observation.state": {"shape": [6]}}
    for role in views:
        in_feat[f"observation.images.{role}"] = {"shape": [3, hw[0], hw[1]]}
    if goal_size is not None:
        in_feat["observation.environment_state"] = {"shape": [goal_size]}
    cfg = {
        "type": "act",
        "n_action_steps": n_steps,
        "chunk_size": chunk_size,
        "input_features": in_feat,
        "output_features": {"action": {"shape": [6]}},
    }
    (pdir / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return pdir, rev


def _encode_b64_jpeg(h: int, w: int, color=(10, 20, 30)) -> str:
    img = np.full((h, w, 3), color, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _http_json(url: str, *, method: str = "GET", body: dict | bytes | None = None, token: str | None = None):
    data = body if isinstance(body, bytes) else (json.dumps(body).encode("utf-8") if body is not None else None)
    headers = {}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_no_top_level_torch_or_lerobot_imports():
    tree = ast.parse(SERVER_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Import):
            names = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module.split(".")[0]]
        else:
            names = []
        assert not ({"torch", "lerobot"} & set(names)), f"top-level forbidden import {names}"


def test_parse_arm_spec_handles_windows_paths_and_rejects_bad_inputs():
    rev = "a" * 64
    arm, p_win, parsed_rev = srv.parse_arm_spec(rf"arm_a=D:\models\arm_a:{rev}")
    assert arm == "arm_a" and parsed_rev == rev and str(p_win).endswith("arm_a")
    arm_posix, p_posix, rev_posix = srv.parse_arm_spec(f"arm_b=/tmp/arm_b:{rev}")
    assert arm_posix == "arm_b" and rev_posix == rev and p_posix.name == "arm_b"
    for bad in ("no_equals", "arm_a=C:/tmp", "arm_a=C:/tmp:not_hex", "=C:/tmp:" + rev):
        with pytest.raises(ValueError):
            srv.parse_arm_spec(bad)


def test_registry_pins_sha256_and_validates_config(tmp_path):
    pdir_a, rev_a = _make_checkpoint(tmp_path, "arm_a", views=("top", "wrist"), goal_size=4)
    with pytest.raises(ValueError, match="sha256"):
        srv.PolicyRegistry.from_specs([f"arm_a={pdir_a}:{'0' * 64}"], loader=lambda *a: lambda obs: [[0.0] * 6])

    bad_dir, bad_rev = _make_checkpoint(tmp_path, "bad_role", views=("overhead",))
    with pytest.raises(ValueError, match="D-1065"):
        srv.PolicyRegistry.from_specs([f"arm_a={bad_dir}:{bad_rev}"], loader=lambda *a: lambda obs: [[0.0] * 6])

    reg = srv.PolicyRegistry.from_specs(
        [f"arm_a={pdir_a}:{rev_a}"],
        loader=lambda *a: lambda obs: [list(obs["state"])] * 4,
    )
    assert reg.health_payload()["arms"]["arm_a"]["goal_size"] == 4


def test_server_auth_validation_and_cli_security_guards(tmp_path):
    pdir, rev = _make_checkpoint(tmp_path, "arm_a")
    reg = srv.PolicyRegistry.from_specs([f"arm_a={pdir}:{rev}"], loader=lambda *a: lambda obs: [[0.0] * 6])
    with pytest.raises(ValueError, match="non-loopback"):
        srv.make_server("0.0.0.0", 0, reg, token=None)
    with pytest.raises(ValueError, match="non-empty"):
        srv.make_server("127.0.0.1", 0, reg, token="  ")

    tok_file = tmp_path / "empty.tok"
    tok_file.write_text("   \n", encoding="utf-8")
    with pytest.raises(SystemExit):
        srv.main(["--arm", f"arm_a={pdir}:{rev}"])
    with pytest.raises(SystemExit):
        srv.main(["--bind", "0.0.0.0", "--allow-insecure-loopback", "--arm", f"arm_a={pdir}:{rev}"])
    with pytest.raises(SystemExit):
        srv.main(["--token-file", str(tok_file), "--arm", f"arm_a={pdir}:{rev}"])


def test_http_endpoints_fail_closed_and_serve_concurrent_arms(tmp_path):
    pdir_a, rev_a = _make_checkpoint(tmp_path, "arm_a", views=("top", "wrist"), hw=(24, 32), n_steps=3, chunk_size=6)
    pdir_b, rev_b = _make_checkpoint(tmp_path, "arm_b", views=("top", "side", "wrist"), hw=(24, 32), goal_size=2, n_steps=3, chunk_size=6)

    bad_mode = {"mode": "ok"}

    def make_loader(pdir, _views, n_steps, _goal_size, _dev):
        tag = 1.0 if pdir.name == "arm_a" else 2.0

        def predict(obs):
            if bad_mode["mode"] == "nan" and pdir.name == "arm_a":
                return [[float("nan")] * 6] * n_steps
            if bad_mode["mode"] == "shape" and pdir.name == "arm_a":
                return [[1.0] * 5]
            if bad_mode["mode"] == "boom" and pdir.name == "arm_a":
                raise RuntimeError("cuda oom secret")
            return [[tag + i * 0.1 for i in range(6)] for _ in range(n_steps)]

        return predict

    reg = srv.PolicyRegistry.from_specs([f"arm_a={pdir_a}:{rev_a}", f"arm_b={pdir_b}:{rev_b}"], loader=make_loader)
    server = srv.make_server("127.0.0.1", 0, reg, token="secret-tok", max_body_bytes=65536)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    port = server.server_address[1]
    base = f"http://127.0.0.1:{port}"
    try:
        st, health = _http_json(f"{base}/health")
        assert st == 200 and health["ok"] is True
        assert set(health["arms"]) == {"arm_a", "arm_b"}

        jpg = _encode_b64_jpeg(24, 32)
        valid_a = {"arm_id": "arm_a", "revision": rev_a, "state": [0.0] * 6, "frames": {"top": jpg, "wrist": jpg}}
        valid_b = {
            "arm_id": "arm_b", "revision": rev_b, "state": [1.0] * 6,
            "frames": {"top": jpg, "side": jpg, "wrist": jpg}, "goal": [0.0, 1.0],
        }

        assert _http_json(f"{base}/infer", method="POST", body=valid_a)[0] == 401
        assert _http_json(f"{base}/infer", method="POST", body=valid_a, token="wrong")[0] == 401
        assert _http_json(f"{base}/infer", method="POST", body={**valid_a, "arm_id": "arm_s"}, token="secret-tok")[0] == 404
        assert _http_json(f"{base}/infer", method="POST", body={**valid_a, "revision": "0" * 64}, token="secret-tok")[0] == 409
        assert _http_json(f"{base}/infer", method="POST", body=b"{bad-json", token="secret-tok")[0] == 400
        assert _http_json(f"{base}/infer", method="POST", body=b"{" + b" " * 70000 + b"}", token="secret-tok")[0] == 413

        for bad_req in (
            {**valid_a, "state": [0.0] * 5},
            {**valid_a, "state": [True] + [0.0] * 5},
            {**valid_a, "frames": {"top": jpg}},
            {**valid_a, "frames": {"top": jpg, "wrist": base64.b64encode(b"not-jpeg").decode("ascii")}},
            {**valid_a, "frames": {"top": jpg, "wrist": _encode_b64_jpeg(16, 16)}},
            {**valid_a, "goal": [1.0]},
            {**valid_b, "goal": [1.0]},
        ):
            assert _http_json(f"{base}/infer", method="POST", body=bad_req, token="secret-tok")[0] == 400

        for fail_mode in ("nan", "shape", "boom"):
            bad_mode["mode"] = fail_mode
            code, err = _http_json(f"{base}/infer", method="POST", body=valid_a, token="secret-tok")
            assert code == 500 and err["ok"] is False and "cuda oom secret" not in json.dumps(err)

        bad_mode["mode"] = "ok"

        def call(req):
            return _http_json(f"{base}/infer", method="POST", body=req, token="secret-tok")

        with ThreadPoolExecutor(max_workers=4) as pool:
            futs = [pool.submit(call, valid_a if i % 2 == 0 else valid_b) for i in range(8)]
            results = [f.result() for f in futs]
        for i, (code, reply) in enumerate(results):
            assert code == 200 and reply["ok"] is True
            assert len(reply["chunk"]) == 3 and len(reply["chunk"][0]) == 6
            expected_first = 1.0 if i % 2 == 0 else 2.0
            assert reply["chunk"][0][0] == pytest.approx(expected_first)
    finally:
        server.shutdown()
        server.server_close()


def test_read_policy_spec_rejects_bool_dims_and_lerobot_loader_passes_device_overrides(tmp_path, monkeypatch):
    bad_hw = tmp_path / "bad_hw"
    bad_hw.mkdir()
    (bad_hw / "config.json").write_text(json.dumps({
        "type": "act", "n_action_steps": 2, "chunk_size": 4,
        "input_features": {"observation.state": {"shape": [6]}, "observation.images.top": {"shape": [3, True, 32]}},
        "output_features": {"action": {"shape": [6]}},
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="shape"):
        srv.read_policy_spec(bad_hw)

    bad_goal = tmp_path / "bad_goal"
    bad_goal.mkdir()
    (bad_goal / "config.json").write_text(json.dumps({
        "type": "act", "n_action_steps": 2, "chunk_size": 4,
        "input_features": {
            "observation.state": {"shape": [6]},
            "observation.images.top": {"shape": [3, 24, 32]},
            "observation.environment_state": {"shape": [True]},
        },
        "output_features": {"action": {"shape": [6]}},
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="goal"):
        srv.read_policy_spec(bad_goal)

    # Verify _load_lerobot_arm wires preprocessor/postprocessor device overrides and cpu detach.
    import contextlib
    import types

    seen = {}

    class FakeTensor:
        def __init__(self, arr):
            self.arr = np.asarray(arr, dtype=np.float32)

        def to(self, arg):
            return FakeTensor(self.arr.astype(np.float32) if arg == np.float32 else self.arr)

        def permute(self, *dims):
            return FakeTensor(np.transpose(self.arr, dims))

        def float(self):
            return FakeTensor(self.arr.astype(np.float32))

        def unsqueeze(self, dim):
            return FakeTensor(np.expand_dims(self.arr, axis=dim))

        def div_(self, other):
            self.arr = self.arr / other
            return self

        def __truediv__(self, other):
            return FakeTensor(self.arr / other)

        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return self.arr

    class FakePolicy:
        config = types.SimpleNamespace(device="cuda")

        def to(self, dev):
            seen["to_device"] = str(dev)
            return self

        def eval(self):
            seen["eval"] = True
            return self

        def predict_action_chunk(self, batch):
            seen["pred_keys"] = sorted(batch)
            return FakeTensor(np.zeros((1, 4, 6), dtype=np.float32))

    fake_torch = types.ModuleType("torch")
    fake_torch.float32 = np.float32
    fake_torch.device = lambda d: d
    fake_torch.tensor = lambda x, dtype=None, device=None: FakeTensor(x)
    fake_torch.from_numpy = lambda x: FakeTensor(x)
    fake_torch.inference_mode = contextlib.nullcontext

    fake_act_mod = types.ModuleType("lerobot.policies.act.modeling_act")
    fake_act_mod.ACTPolicy = types.SimpleNamespace(from_pretrained=lambda *_a, **_kw: FakePolicy())

    def fake_processors(cfg, *, pretrained_path, preprocessor_overrides=None, postprocessor_overrides=None):
        seen["cfg_device"] = cfg.device
        seen["pre_over"] = preprocessor_overrides
        seen["post_over"] = postprocessor_overrides
        return (lambda b: b), (lambda c: c)

    fake_factory_mod = types.ModuleType("lerobot.policies.factory")
    fake_factory_mod.make_pre_post_processors = fake_processors

    for name, mod in (
        ("torch", fake_torch),
        ("lerobot", types.ModuleType("lerobot")),
        ("lerobot.policies", types.ModuleType("lerobot.policies")),
        ("lerobot.policies.act", types.ModuleType("lerobot.policies.act")),
        ("lerobot.policies.act.modeling_act", fake_act_mod),
        ("lerobot.policies.factory", fake_factory_mod),
    ):
        monkeypatch.setitem(sys.modules, name, mod)

    pred = srv._load_lerobot_arm(tmp_path, {"top": (24, 32)}, 2, None, "cpu")
    out = pred({"state": [0.0] * 6, "frames_rgb": {"top": np.zeros((24, 32, 3), dtype=np.uint8)}, "goal": None})
    assert len(out) == 4 and len(out[0]) == 6  # the whole chunk; PolicyRegistry.infer trims unless full_chunk
    assert seen["cfg_device"] == "cpu" and seen["to_device"] == "cpu" and seen["eval"] is True
    assert seen["pre_over"] == {"device_processor": {"device": "cpu"}}
    assert seen["post_over"] == {"device_processor": {"device": "cpu"}}


def test_http11_keepalive_request_id_and_oversized_close(tmp_path):
    import http.client
    import socket

    pdir, rev = _make_checkpoint(tmp_path, "arm_a", views=("top", "wrist"), hw=(24, 32), n_steps=2, chunk_size=4)
    accepted = [0]
    reg = srv.PolicyRegistry.from_specs([f"arm_a={pdir}:{rev}"], loader=lambda *a: lambda obs: [[0.5] * 6] * 2)
    server = srv.make_server("127.0.0.1", 0, reg, token="ka-tok", max_body_bytes=4096)
    orig_get_request = server.get_request

    def _counting_accept():
        accepted[0] += 1
        return orig_get_request()

    server.get_request = _counting_accept
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2.0)
    conn2 = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2.0)
    try:
        conn.request("GET", "/health", headers={"Connection": "keep-alive"})
        r_health = conn.getresponse()
        r_health.read()
        assert r_health.status == 200 and r_health.version == 11 and not r_health.will_close

        jpg = _encode_b64_jpeg(24, 32)
        base_body = {"arm_id": "arm_a", "revision": rev, "state": [0.0] * 6, "frames": {"top": jpg, "wrist": jpg}}
        for idx in range(2):
            req_id = f"req-{idx}"
            conn.request(
                "POST",
                "/infer",
                body=json.dumps({**base_body, "request_id": req_id}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Authorization": "Bearer ka-tok", "Connection": "keep-alive"},
            )
            r_inf = conn.getresponse()
            data = json.loads(r_inf.read().decode("utf-8"))
            assert r_inf.status == 200 and not r_inf.will_close and data["request_id"] == req_id
        assert accepted[0] == 1

        for bad_id in ("   ", 123, "x" * 129):
            conn.request(
                "POST",
                "/infer",
                body=json.dumps({**base_body, "request_id": bad_id}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Authorization": "Bearer ka-tok"},
            )
            r_bad = conn.getresponse()
            r_bad.read()
            assert r_bad.status == 400

        conn.request(
            "POST",
            "/infer",
            body=b"{bad-json",
            headers={"Content-Type": "application/json", "Authorization": "Bearer ka-tok"},
        )
        r_json = conn.getresponse()
        r_json.read()
        assert r_json.status == 400 and r_json.will_close and (r_json.getheader("Connection") or "").lower() == "close"

        raw_ok_body = json.dumps({**base_body, "request_id": "early-check"}).encode("utf-8")
        for method, route, body_bytes, hdrs, expected_status in (
            ("POST", "/unknown", raw_ok_body, {"Content-Type": "application/json", "Authorization": "Bearer ka-tok", "Connection": "keep-alive"}, 404),
            ("POST", "/infer", raw_ok_body, {"Content-Type": "application/json", "Connection": "keep-alive"}, 401),
            ("POST", "/infer", raw_ok_body, {"Content-Type": "application/json", "Authorization": "Bearer wrong", "Connection": "keep-alive"}, 401),
            ("GET", "/health", b"abcd", {"Connection": "keep-alive"}, 200),
            ("GET", "/unknown", b"abcd", {"Connection": "keep-alive"}, 404),
            ("POST", "/infer", b"0\r\n\r\n", {"Content-Type": "application/json", "Authorization": "Bearer ka-tok", "Transfer-Encoding": "chunked", "Connection": "keep-alive"}, 400),
            ("GET", "/health", None, {"Content-Length": "", "Connection": "keep-alive"}, 200),
            ("GET", "/health", None, {"Transfer-Encoding": "", "Connection": "keep-alive"}, 200),
            ("POST", "/infer", raw_ok_body, {"Content-Type": "application/json", "Authorization": "Bearer ka-tok", "Transfer-Encoding": "", "Connection": "keep-alive"}, 400),
        ):
            early_conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=2.0)
            try:
                early_conn.request(method, route, body=body_bytes, headers=hdrs)
                r_early = early_conn.getresponse()
                r_early.read()
                assert r_early.status == expected_status and r_early.will_close
                assert (r_early.getheader("Connection") or "").lower() == "close"
            finally:
                early_conn.close()

        conn2.request(
            "POST",
            "/infer",
            body=json.dumps({**base_body, "request_id": "post-early-ok"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer ka-tok", "Connection": "keep-alive"},
        )
        r_after = conn2.getresponse()
        d_after = json.loads(r_after.read().decode("utf-8"))
        assert r_after.status == 200 and not r_after.will_close and d_after["request_id"] == "post-early-ok"

        conn2.request(
            "POST",
            "/infer",
            body=b"{" + b" " * 5000 + b"}",
            headers={"Content-Type": "application/json", "Authorization": "Bearer ka-tok"},
        )
        r_big = conn2.getresponse()
        r_big.read()
        assert r_big.status == 413 and r_big.will_close and (r_big.getheader("Connection") or "").lower() == "close"

        for wire_req, expected_line in (
            (b"POST /infer HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer ka-tok\r\nConnection: keep-alive\r\nContent-Length: " + b"9" * 4301 + b"\r\n\r\n", b"HTTP/1.1 413 "),
            (b"POST /infer HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer ka-tok\r\nConnection: keep-alive\r\nContent-Length: 4\xa0\r\n\r\n{}", b"HTTP/1.1 400 "),
        ):
            with socket.create_connection(("127.0.0.1", server.server_address[1]), timeout=2.0) as raw_sock:
                raw_sock.sendall(wire_req)
                buf = b""
                while b"\r\n\r\n" not in buf:
                    chunk = raw_sock.recv(4096)
                    assert chunk
                    buf += chunk
                assert buf.startswith(expected_line) and b"\r\nconnection: close\r\n" in buf.lower()
    finally:
        conn.close()
        conn2.close()
        server.shutdown()
        server.server_close()

    class _StubSock:
        def __init__(self):
            self.events = []

        def shutdown(self, how):
            self.events.append(("shutdown", how))

        def close(self):
            self.events.append("close")

    fake_sock = _StubSock()
    server.process_request(fake_sock, ("127.0.0.1", 12345))
    assert server._closed is True
    assert not server._active_socks
    assert "close" in fake_sock.events


def test_gpu_training_busy_health_and_503_fail_closed(tmp_path):
    import os
    import subprocess
    import time

    pdir, rev = _make_checkpoint(tmp_path, "arm_a", views=("top", "wrist"), hw=(24, 32))
    lock_file = tmp_path / "gpu.lock"
    lock_file.write_text("", encoding="utf-8")
    jobs_dir = tmp_path / "rosy-jobs"
    jobs_dir.mkdir()

    reg = srv.PolicyRegistry.from_specs(
        [f"arm_a={pdir}:{rev}"],
        loader=lambda *a: lambda obs: [[0.25] * 6] * 4,
        gpu_lock_file=lock_file,
        jobs_dir=jobs_dir,
        reject_when_training_busy=True,
    )
    server = srv.make_server("127.0.0.1", 0, reg, token="tok-lock")
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    jpg = _encode_b64_jpeg(24, 32)
    infer_body = {"arm_id": "arm_a", "revision": rev, "request_id": "req-busy-1", "state": [0.0] * 6, "frames": {"top": jpg, "wrist": jpg}}

    try:
        # 1. Idle: /health reports free, /infer returns 200
        code, h_idle = _http_json(f"{base_url}/health")
        assert code == 200 and h_idle["gpu_training_busy"] is False and h_idle["gpu_training_reason"] is None
        code, r_idle = _http_json(f"{base_url}/infer", method="POST", body=infer_body, token="tok-lock")
        assert code == 200 and r_idle["ok"] is True

        # 2. Live train-*.lock with current PID marks GPU busy -> /health true, /infer 503 with request_id
        train_lock = jobs_dir / "train-999999.lock"
        train_lock.write_text(f"{os.getpid()} gpu 8 12\n", encoding="utf-8")
        code, h_train = _http_json(f"{base_url}/health")
        assert code == 200 and h_train["gpu_training_busy"] is True and "train-999999.lock" in h_train["gpu_training_reason"]
        code, r_busy = _http_json(f"{base_url}/infer", method="POST", body=infer_body, token="tok-lock")
        assert code == 503 and r_busy["error"] == "gpu_training_busy" and r_busy["request_id"] == "req-busy-1"
        train_lock.unlink()

        # 3. Exclusive flock in another process (on POSIX) marks GPU busy, then frees cleanly; server never holds flock
        fcntl = pytest.importorskip("fcntl")
        holder = subprocess.Popen(
            [
                sys.executable, "-c",
                "import fcntl, sys, time; fh = open(sys.argv[1], 'r+'); "
                "fcntl.flock(fh.fileno(), fcntl.LOCK_EX); print('LOCKED', flush=True); time.sleep(5)",
                str(lock_file),
            ],
            stdout=subprocess.PIPE, text=True,
        )
        try:
            assert holder.stdout.readline().strip() == "LOCKED"
            code, h_flock = _http_json(f"{base_url}/health")
            assert code == 200 and h_flock["gpu_training_busy"] is True and h_flock["gpu_training_reason"] == "gpu_lock_held"
            code, r_flock = _http_json(f"{base_url}/infer", method="POST", body=infer_body, token="tok-lock")
            assert code == 503 and r_flock["error"] == "gpu_training_busy"
        finally:
            holder.terminate()
            holder.wait(timeout=5)

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            code, h_free = _http_json(f"{base_url}/health")
            if h_free["gpu_training_busy"] is False:
                break
            time.sleep(0.05)
        assert h_free["gpu_training_busy"] is False
        code, r_ok = _http_json(f"{base_url}/infer", method="POST", body=infer_body, token="tok-lock")
        assert code == 200
        with lock_file.open("r+") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    finally:
        server.shutdown()
        server.server_close()


def test_load_lerobot_arm_moves_uint8_to_device_before_float_scale(tmp_path, monkeypatch):
    import contextlib, types

    recorded, state_devs, target_dev = [], [], "device:cuda:0"

    class _FakeTensor:
        def __init__(self, arr, *, dtype="float32", device="cpu"):
            self.arr, self.dtype, self.device, self.ops = arr, dtype, device, []

        def _rec(self, tag):
            self.ops.append(tag)
            return self

        def to(self, arg):
            is_f = arg == "dtype:float32"
            tag = ("to_float", self.dtype, self.device) if is_f else ("to_device", arg, self.dtype)
            setattr(self, "dtype" if is_f else "device", "float32" if is_f else arg)
            return self._rec(tag)

        def div_(self, scale):
            self.arr = self.arr.astype(np.float64) / scale
            return self._rec(("div_", scale, self.dtype, self.device))

        permute = lambda self, *d: self._rec(("permute", d))
        unsqueeze = lambda self, d: self._rec(("unsqueeze", d))
        detach = cpu = lambda self: self
        numpy = lambda self: self.arr

    class _FakePolicy:
        config = types.SimpleNamespace(device="cpu")
        to = eval = lambda self, *_a: self
        predict_action_chunk = lambda self, b: _FakeTensor(np.full((6, 6), float(b["observation.images.top"].arr.mean()), dtype=np.float32))

    fake_torch = types.ModuleType("torch")
    fake_torch.float32, fake_torch.device, fake_torch.inference_mode = "dtype:float32", (lambda d: f"device:{d}"), contextlib.nullcontext
    fake_torch.tensor = lambda data, *, dtype=None, device=None: (state_devs.append(device) or _FakeTensor(np.asarray(data), dtype=dtype, device=device))
    fake_torch.from_numpy = lambda arr: (recorded.append(_FakeTensor(arr, dtype=str(arr.dtype))) or recorded[-1])
    for name in ("lerobot", "lerobot.policies", "lerobot.policies.act", "lerobot.policies.act.modeling_act", "lerobot.policies.factory"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    sys.modules["lerobot.policies.act.modeling_act"].ACTPolicy = types.SimpleNamespace(from_pretrained=lambda *_a, **_k: _FakePolicy())
    sys.modules["lerobot.policies.factory"].make_pre_post_processors = lambda *_a, **_k: (lambda b: b, lambda c: c)

    predict = srv._load_lerobot_arm(tmp_path, {"top": (4, 6)}, n_action_steps=4, goal_size=2, device="cuda:0")
    out = predict({"state": [0.1] * 6, "goal": [1.0, 0.0], "frames_rgb": {"top": np.full((4, 6, 3), 255, dtype=np.uint8)}})
    assert state_devs == [target_dev, target_dev]
    ops = recorded[0].ops
    assert ops.index(("to_device", target_dev, "uint8")) < ops.index(("to_float", "uint8", target_dev)) < ops.index(("div_", 255.0, "float32", target_dev))
    assert len(out) == 6 and all(len(row) == 6 and all(v == pytest.approx(1.0) for v in row) for row in out)  # whole chunk


def test_infer_trims_to_n_action_steps_unless_full_chunk_requested(tmp_path):
    pdir, rev = _make_checkpoint(tmp_path, "arm_b", views=("top",), hw=(24, 32), n_steps=3, chunk_size=6)
    reg = srv.PolicyRegistry.from_specs([f"arm_b={pdir}:{rev}"], loader=lambda *_a: (lambda _obs: [[0.1 * i] * 6 for i in range(6)]))
    req = {"arm_id": "arm_b", "revision": rev, "state": [0.0] * 6, "frames": {"top": _encode_b64_jpeg(24, 32)}}
    code, body = reg.infer(req)
    assert code == 200 and len(body["chunk"]) == 3
    code, body = reg.infer({**req, "full_chunk": True})
    assert code == 200 and len(body["chunk"]) == 6 and body["chunk"][5][0] == pytest.approx(0.5)
    assert len(reg.infer({**req, "full_chunk": "yes"})[1]["chunk"]) == 3  # anything but true keeps the trimmed chunk
