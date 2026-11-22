"""PR-6 tests: :8768 service_offline_job bearer tokens and canonical bundle manifest/file endpoints."""
from __future__ import annotations

import hashlib
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "learning" / "curation" / "perception"))
sys.path.insert(0, str(ROOT / "learning" / "training" / "omx"))
sys.path.insert(0, str(ROOT / "contracts" / "learning" / "src"))

import experiment_center  # noqa: E402
from learning_service_auth import ServiceTokens  # noqa: E402
from review_app import ReviewStore, make_server  # noqa: E402
from test_learning_collaboration import Accounts  # noqa: E402

RAW_TOK = "svc_offline_tok_0123456789abcdef"


def _req(url: str, *, method: str = "GET", body: dict | None = None, token: str | None = None):
    hdrs = {}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    if token is not None:
        hdrs["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_service_tokens_allow_offline_jobs_and_block_human_approval_routes(tmp_path: Path):
    tok_file = tmp_path / "svc-tokens.json"
    tok_file.write_text(json.dumps({"tokens": [{
        "id": "agy-offline", "scope": "service_offline_job",
        "token_sha256": hashlib.sha256(RAW_TOK.encode()).hexdigest(),
    }]}), encoding="utf-8")
    svc_tokens = ServiceTokens(json.loads(tok_file.read_text(encoding="utf-8")))

    ds = tmp_path / "ds"
    (ds / "meta").mkdir(parents=True)
    lib = tmp_path / "lib.json"
    lib.write_text("{}", encoding="utf-8")
    center = experiment_center.Center({
        "schema": "rosy.omx.center-config/1", "host_id": "model", "root": str(tmp_path / "center"),
        "python": {"act": sys.executable, "hilserl": sys.executable},
        "canonical": {
            "schema": "rosy.omx.canonical-config/1",
            "python": {"sim": sys.executable, "train": sys.executable, "cell": sys.executable},
            "jobs_dir": str(tmp_path / "jobs"),
            "named_sources": {"ds": {"kind": "real_dataset", "arm_id": "arm_a", "label": "ds", "path": str(ds)},
                              "lib": {"kind": "chunk_library", "arm_id": "arm_a", "label": "lib", "path": str(lib)}},
            "watch_roots": {"w": {"label": "w", "host_id": "model", "path": str(tmp_path)}},
        },
    })
    rid = "11111111-1111-1111-1111-111111111111"
    bdir = Path(center.root) / "canonical" / "runs" / rid / "output" / "bundle"
    bdir.mkdir(parents=True)
    (bdir / "model.onnx").write_bytes(b"ONNX_BYTES")
    (bdir / "model.safetensors").write_bytes(b"SAFETENSORS_BYTES")
    (bdir / "config.json").write_text('{"type":"act"}', encoding="utf-8")
    with center.canonical.connect() as db:
        doc = {"id": rid, "request_id": rid, "kind": "cell_live_check", "arm_id": "arm_a", "gpu_required": False,
               "status": "succeeded", "created_at": 1.0, "params": {}, "result": {"ok": True}}
        db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)", (rid, rid, "cell_live_check", 0, json.dumps(doc), "{}", "{}"))

    srv = make_server(ReviewStore(tmp_path / "state", empty_training=True), 0, omx_center=center, accounts=Accounts(), service_tokens=svc_tokens)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        base = f"http://127.0.0.1:{srv.server_port}"
        assert _req(base + "/api/learning/canonical", token=RAW_TOK)[0] == 200
        code_m, raw_m = _req(base + f"/api/learning/canonical/runs/{rid}/bundle-manifest", token=RAW_TOK)
        assert code_m == 200
        man = json.loads(raw_m)
        assert man["schema"] == "rosy.canonical-bundle-manifest.v1" and man["onnx_sha256"] == hashlib.sha256(b"ONNX_BYTES").hexdigest()
        code_f, raw_f = _req(base + f"/api/learning/canonical/runs/{rid}/file/model.onnx", token=RAW_TOK)
        assert code_f == 200 and raw_f == b"ONNX_BYTES"
        assert _req(base + f"/api/learning/canonical/runs/{rid}/file/../secret", token=RAW_TOK)[0] in (400, 403)

        # Invalid token & forbidden routes must return 403.
        assert _req(base + "/api/learning/canonical", token="wrong-token-123456")[0] == 403
        for path, body in (
            ("/api/learning/ladder/decision", {"round_id": "20261123T000000-abcdef01", "verdict": "replace", "note": "x"}),
            ("/api/learning/promotion-requests", {"id": "x"}),
            ("/api/learning/omx/center/hub-upload", {"bundle_id": "b1", "connection_id": "c1"}),
            ("/api/learning/omx/center/cuda-run", {"path": "/tmp"}),
            ("/api/frames/0", {"action": "approve"}),
        ):
            assert _req(base + path, method="POST", body=body, token=RAW_TOK)[0] == 403, path

        # Allowed offline job POST executes (503/400 from ladder/canonical state, NOT 403!).
        c_post, _ = _req(base + "/api/learning/storage/preflight", method="POST", body={}, token=RAW_TOK)
        assert c_post == 400

        # Regression: GET /api/learning/control is denied by _DENIED_PREFIXES (403).
        assert _req(base + "/api/learning/control", token=RAW_TOK)[0] == 403

        # Regression #1: GET /api/learning/canonical/peer-summary works with peer_token even when service_tokens & accounts are configured.
        peer_tok = "peer_tok_0123456789abcdef01234567"
        peer_tok_file = tmp_path / "peer.token"
        peer_tok_file.write_text(peer_tok + "\n", encoding="utf-8")
        peer_tok_file.chmod(0o600)
        center.canonical.peer_token_file = peer_tok_file
        assert _req(base + "/api/learning/canonical/peer-summary", token=peer_tok)[0] == 200

        # Regression #2: failed/running runs are refused by bundle-manifest & bundle file; nested subdir inside succeeded bundle works, symlink rejected.
        fid = "22222222-2222-2222-2222-222222222222"
        fbdir = Path(center.root) / "canonical" / "runs" / fid / "output" / "bundle"
        fbdir.mkdir(parents=True)
        (fbdir / "model.onnx").write_bytes(b"BAD")
        with center.canonical.connect() as db:
            fdoc = {"id": fid, "request_id": fid, "kind": "cell_live_check", "arm_id": "arm_a", "gpu_required": False,
                    "status": "failed", "created_at": 2.0, "params": {}, "result": {}}
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)", (fid, fid, "cell_live_check", 0, json.dumps(fdoc), "{}", "{}"))
        assert _req(base + f"/api/learning/canonical/runs/{fid}/bundle-manifest", token=RAW_TOK)[0] == 400
        assert _req(base + f"/api/learning/canonical/runs/{fid}/file/model.onnx", token=RAW_TOK)[0] == 400

        (bdir / "meta").mkdir()
        (bdir / "meta" / "info.json").write_text('{"ok":true}', encoding="utf-8")
        c_sub, raw_sub = _req(base + f"/api/learning/canonical/runs/{rid}/bundle-manifest", token=RAW_TOK)
        assert c_sub == 200 and any(f["path"] == "meta/info.json" for f in json.loads(raw_sub)["files"])
        c_subf, raw_subf = _req(base + f"/api/learning/canonical/runs/{rid}/file/meta/info.json", token=RAW_TOK)
        assert c_subf == 200 and raw_subf == b'{"ok":true}'

        # Running status run is refused (400), and symlinked bundle entry is refused (400).
        rnid = "33333333-3333-3333-3333-333333333333"
        (Path(center.root) / "canonical" / "runs" / rnid / "output" / "bundle").mkdir(parents=True)
        with center.canonical.connect() as db:
            rdoc = {"id": rnid, "request_id": rnid, "kind": "cell_live_check", "arm_id": "arm_a", "gpu_required": False,
                    "status": "running", "created_at": 3.0, "params": {}, "result": {}}
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)", (rnid, rnid, "cell_live_check", 0, json.dumps(rdoc), "{}", "{}"))
        assert _req(base + f"/api/learning/canonical/runs/{rnid}/bundle-manifest", token=RAW_TOK)[0] == 400
        (bdir / "meta" / "esc.json").symlink_to(tok_file)
        assert _req(base + f"/api/learning/canonical/runs/{rid}/bundle-manifest", token=RAW_TOK)[0] == 400
        assert _req(base + f"/api/learning/canonical/runs/{rid}/file/meta/esc.json", token=RAW_TOK)[0] == 400
    finally:
        srv.shutdown(); srv.server_close(); th.join(timeout=5)
