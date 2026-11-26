"""POST /arms/{arm}/load: verified swap, allowed roots, auth, keep-old-on-failure, env write-back, Learning forwarder."""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import urllib.error
import urllib.request

import pytest

ROOT = Path(__file__).resolve().parents[4]
LEARN_OMX = ROOT / "learning" / "training" / "omx"
for p in (str(LEARN_OMX), str(ROOT / "contracts" / "learning" / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import act_policy_http_server as srv  # noqa: E402
import canonical_serve  # noqa: E402

TOKEN = "load-token-0123456789"


def _ckpt(root: Path, name: str, payload: bytes) -> tuple[Path, str]:
    pdir = root / name
    pdir.mkdir(parents=True)
    (pdir / "model.safetensors").write_bytes(payload)
    (pdir / "config.json").write_text(json.dumps({
        "type": "act", "n_action_steps": 4, "chunk_size": 8,
        "input_features": {"observation.state": {"shape": [6]}, "observation.images.top": {"shape": [3, 24, 32]}},
        "output_features": {"action": {"shape": [6]}},
    }), encoding="utf-8")
    return pdir.resolve(), sha256(payload).hexdigest()


def _post(url, body, token=TOKEN):
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _health(base):
    with urllib.request.urlopen(base + "/health", timeout=5) as resp:
        return json.loads(resp.read())["arms"]


@pytest.fixture()
def act(tmp_path):
    root = tmp_path / "models"
    old_dir, old_rev = _ckpt(root, "old", b"old-weights")
    env = tmp_path / "omx-act-http.env"
    env.write_text(f'ROSY_ACT_HTTP_PYTHON=/usr/bin/python3\nROSY_ACT_HTTP_ARGS="--bind 0.0.0.0 --arm arm_a={old_dir}:{old_rev}"\n',
                   encoding="utf-8")
    os.chmod(env, 0o600)
    fail = {"on": False}

    def loader(*_a):
        if fail["on"]:
            raise RuntimeError("cuda out of memory")
        return lambda obs: [[0.0] * 6]

    reg = srv.PolicyRegistry.from_specs([f"arm_a={old_dir}:{old_rev}"], loader=loader)
    server = srv.make_server("127.0.0.1", 0, reg, token=TOKEN, load_roots=[root], env_file=env)
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    try:
        yield SimpleNamespace(base=f"http://127.0.0.1:{server.server_port}", root=root, env=env, fail=fail,
                              old_dir=old_dir, old_rev=old_rev, tmp=tmp_path)
    finally:
        server.shutdown()
        server.server_close()


def test_load_success_swaps_shows_dir_sha_and_persists_env(act):
    new_dir, new_rev = _ckpt(act.root, "new", b"new-weights")
    assert _health(act.base)["arm_a"]["dir"] == str(act.old_dir)
    code, reply = _post(act.base + "/arms/arm_a/load", {"dir": str(new_dir), "sha256": new_rev})
    assert code == 200 and reply["ok"] and reply["previous_revision"] == act.old_rev and reply["persisted"] is True
    arm = _health(act.base)["arm_a"]
    assert arm["dir"] == str(new_dir) and arm["revision"] == new_rev
    code, reply = _post(act.base + "/infer", {"arm_id": "arm_a", "revision": act.old_rev})
    assert code == 409  # clients pinned to the old sha are refused, not silently served the new model
    text = act.env.read_text(encoding="utf-8")
    assert f"--arm arm_a={new_dir}:{new_rev}" in text and act.old_rev not in text
    assert text.startswith("ROSY_ACT_HTTP_PYTHON=/usr/bin/python3\n") and text.rstrip().endswith('"')
    if os.name == "posix":
        assert (act.env.stat().st_mode & 0o777) == 0o600
    assert list(act.env.parent.glob(".omx-act-http.env.*")) == []


def test_wrong_sha_outside_root_and_bad_body_keep_old_model(act):
    new_dir, new_rev = _ckpt(act.root, "new", b"new-weights")
    before = act.env.read_text(encoding="utf-8")
    code, reply = _post(act.base + "/arms/arm_a/load", {"dir": str(new_dir), "sha256": "0" * 64})
    assert code == 422 and "sha256" in reply["error"] and reply["kept_revision"] == act.old_rev
    outside, out_rev = _ckpt(act.tmp / "elsewhere", "x", b"x")
    assert _post(act.base + "/arms/arm_a/load", {"dir": str(outside), "sha256": out_rev})[0] == 403
    escape = str(act.root / ".." / "elsewhere" / "x")  # .. resolves out of the root
    assert _post(act.base + "/arms/arm_a/load", {"dir": escape, "sha256": out_rev})[0] == 403
    assert _post(act.base + "/arms/arm_a/load", {"dir": "relative/x", "sha256": new_rev})[0] == 400
    assert _post(act.base + "/arms/arm_a/load", {"dir": str(new_dir), "sha256": new_rev, "x": 1})[0] == 400
    assert _post(act.base + "/arms/arm_z/load", {"dir": str(new_dir), "sha256": new_rev})[0] == 404
    assert _health(act.base)["arm_a"]["revision"] == act.old_rev and act.env.read_text(encoding="utf-8") == before


def test_auth_missing_or_wrong_is_refused_before_any_load(act):
    new_dir, new_rev = _ckpt(act.root, "new", b"new-weights")
    assert _post(act.base + "/arms/arm_a/load", {"dir": str(new_dir), "sha256": new_rev}, token=None)[0] == 401
    assert _post(act.base + "/arms/arm_a/load", {"dir": str(new_dir), "sha256": new_rev}, token="nope")[0] == 401
    assert _health(act.base)["arm_a"]["revision"] == act.old_rev


def test_failed_load_keeps_old_model_serving(act):
    new_dir, new_rev = _ckpt(act.root, "new", b"new-weights")
    act.fail["on"] = True
    code, reply = _post(act.base + "/arms/arm_a/load", {"dir": str(new_dir), "sha256": new_rev})
    assert code == 500 and reply["error"] == "load failed: RuntimeError" and reply["kept_revision"] == act.old_rev
    assert _health(act.base)["arm_a"]["dir"] == str(act.old_dir)
    code, reply = _post(act.base + "/infer", {"arm_id": "arm_a", "revision": act.old_rev})
    assert code == 400 and "state" in reply["error"]  # old revision still accepted (fails later on missing state)


def test_load_disabled_without_roots_and_env_left_alone_without_token(tmp_path):
    pdir, rev = _ckpt(tmp_path, "a", b"a")
    reg = srv.PolicyRegistry.from_specs([f"arm_a={pdir}:{rev}"], loader=lambda *a: lambda obs: [[0.0] * 6])
    status, reply = srv.handle_load(reg, "arm_a", {"dir": str(pdir), "sha256": rev}, roots=[], env_file=None)
    assert status == 403 and "disabled" in reply["error"]
    env = tmp_path / "e.env"
    env.write_text("ROSY_ACT_HTTP_ARGS=--config /x.json\n", encoding="utf-8")
    status, reply = srv.handle_load(reg, "arm_a", {"dir": str(pdir), "sha256": rev}, roots=[tmp_path], env_file=env)
    assert status == 200 and reply["persisted"] is False and "--arm arm_a=" in reply["reason"]
    assert env.read_text(encoding="utf-8") == "ROSY_ACT_HTTP_ARGS=--config /x.json\n"


def test_learning_forwarder_sends_run_checkpoint_and_reports_inline(act, tmp_path):
    canon_root = tmp_path / "canon"
    rid = "3f1b2c4d-0000-4000-8000-000000000001"
    ckpt_parent = canon_root / "runs" / rid / "output" / "train" / "checkpoints" / "last"
    ckpt_parent.mkdir(parents=True)
    _ckpt(ckpt_parent, "pretrained_model", b"run-weights")
    token_file = tmp_path / "act.token"
    token_file.write_text(TOKEN, encoding="utf-8")
    os.chmod(token_file, 0o600)
    run = {"id": rid, "kind": "train_stage", "status": "succeeded", "arm_id": "arm_a",
           "result": {"policy_sha256": sha256(b"run-weights").hexdigest()}}
    svc = SimpleNamespace(root=canon_root, get_run=lambda _rid: run,
                          act_serve=canonical_serve.parse_config({"url": act.base, "token_file": str(token_file)}))
    out = canonical_serve.serve_run(svc, rid)
    assert out["http_status"] == 403 and out["ok"] is False  # canon root is outside the ACT server's load root
    act_root_run = act.root / "runs"
    svc.root = act_root_run
    (act_root_run / "runs" / rid / "output" / "train" / "checkpoints" / "last").mkdir(parents=True)
    _ckpt(act_root_run / "runs" / rid / "output" / "train" / "checkpoints" / "last", "pretrained_model", b"run-weights")
    out = canonical_serve.serve_run(svc, rid)
    assert out["ok"] is True and out["reply"]["revision"] == run["result"]["policy_sha256"]
    assert _health(act.base)["arm_a"]["revision"] == run["result"]["policy_sha256"]
    run["status"] = "running"
    with pytest.raises(ValueError, match="train_stage"):
        canonical_serve.serve_run(svc, rid)
    svc.act_serve = None
    with pytest.raises(ValueError, match="설정"):
        canonical_serve.serve_run(svc, rid)
