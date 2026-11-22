"""HTTP & collaboration auth tests for /api/learning/canonical/* routes."""
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import threading
import urllib.error
import urllib.request
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "learning" / "training" / "omx"))
sys.path.insert(0, str(ROOT / "learning" / "curation" / "perception"))
sys.path.insert(0, str(ROOT / "contracts" / "learning" / "src"))

import experiment_center  # noqa: E402
from review_app import ReviewStore, make_server  # noqa: E402
from test_learning_collaboration import Accounts, request as collab_req  # noqa: E402
from test_omx_center_http import request as raw_req  # noqa: E402

PREFIX = "/api/learning/canonical"


def _canon_cfg(tmp_path: Path) -> dict:
    for name in ("ds_b", "frames_b", "watch_mp"):
        (tmp_path / name).mkdir(exist_ok=True)
    (tmp_path / "ds_b" / "meta").mkdir(exist_ok=True)
    lib = tmp_path / "chunks-b.json"
    lib.write_text(json.dumps({"chunks": {"home": [[0.8, -62.2, 53.1, 51.6, 45.2, 48.8]]}}), encoding="utf-8")
    return {
        "schema": "rosy.omx.canonical-config/1",
        "python": {"sim": sys.executable, "train": sys.executable, "cell": sys.executable},
        "jobs_dir": str(tmp_path / "jobs"),
        "named_sources": {
            "real_b": {"kind": "real_dataset", "arm_id": "arm_b", "label": "Real B", "path": str(tmp_path / "ds_b")},
            "frames_b": {"kind": "frames_dir", "arm_id": "arm_b", "label": "Frames B", "path": str(tmp_path / "frames_b")},
            "lib_b": {"kind": "chunk_library", "arm_id": "arm_b", "label": "Lib B", "path": str(lib)},
        },
        "watch_roots": {"mp": {"label": "Model PC", "host_id": "model", "path": str(tmp_path / "watch_mp")}},
    }


@contextmanager
def _serve(tmp_path: Path, *, with_canonical: bool = False, accounts=None, monkeypatch=None):
    if monkeypatch is not None:
        monkeypatch.setattr(experiment_center.os, "name", "posix")
        monkeypatch.setattr(
            experiment_center.subprocess, "run",
            lambda *a, **k: type("R", (), {"returncode": 0, "stdout": b"True\n"})(),
        )
    center = None
    if with_canonical:
        center = experiment_center.Center({
            "schema": "rosy.omx.center-config/1",
            "host_id": "model",
            "root": str(tmp_path / "center"),
            "python": {"act": sys.executable, "hilserl": sys.executable},
            "canonical": _canon_cfg(tmp_path),
        })
    srv = make_server(ReviewStore(tmp_path / "state", empty_training=True), 0, omx_center=center, accounts=accounts)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        yield f"http://127.0.0.1:{srv.server_port}", center
    finally:
        srv.shutdown(); srv.server_close(); th.join(timeout=5)


def test_zero_config_serves_readonly_builtin_spec_and_blocks_writes(tmp_path):
    with _serve(tmp_path, with_canonical=False) as (base, _):
        for route, mime_prefix in (("/learning/canonical", "text/html"), ("/canonical.js", "text/javascript"), ("/canonical.css", "text/css")):
            with urllib.request.urlopen(base + route, timeout=5) as resp:
                assert resp.status == 200 and resp.headers.get("Content-Type", "").startswith(mime_prefix)
        code, snap = raw_req(base, PREFIX)
        assert code == 200 and snap["configured"] is False and snap["writable"] is False
        assert snap["spec"]["design"] == "design2_idle_home_active_canonical"
        assert snap["real_evidence"] is False and snap["policy_activation"] is False

        code2, spec = raw_req(base, PREFIX + "/spec")
        assert code2 == 200 and spec["spec_sha256"] == snap["spec_sha256"]

        _, learning = raw_req(base, "/api/learning")
        code3, err = raw_req(base, PREFIX + "/jobs", {"kind": "collect_dart"}, token=learning["token"])
        assert code3 == 503 and "설정되지 않았습니다" in err["error"]


def test_collaboration_enforces_view_manage_csrf_no_paths_and_busy_conflict(tmp_path, monkeypatch):
    accounts = Accounts()
    with _serve(tmp_path, with_canonical=True, accounts=accounts, monkeypatch=monkeypatch) as (base, center):
        class _NoRedir(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a):
                return None
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedir())
        with pytest.raises(urllib.error.HTTPError) as exc:
            opener.open(urllib.request.Request(base + "/learning/canonical"), timeout=5)
        assert exc.value.code == 303 and exc.value.headers.get("Location") == "/accounts"
        with opener.open(urllib.request.Request(base + "/learning/canonical", headers={"Cookie": "rosy_learning_session=reader"}), timeout=5) as page:
            assert page.status == 200 and "표준 시작 자세" in page.read().decode("utf-8")
        assert collab_req(base, PREFIX)[0] == 401
        code, snap = collab_req(base, PREFIX, "reader")
        assert code == 200 and snap["configured"] is True and snap["real_evidence"] is False
        assert str(tmp_path) not in json.dumps(snap)

        token = collab_req(base, "/api/accounts/session", "reviewer")[1]["token"]
        bad_body = {
            "request_id": str(uuid.uuid4()), "kind": "align_real", "arm_id": "arm_b",
            "params": {"source_id": "/etc/passwd", "wrist_flip": True, "trim_dead_idle": True},
        }
        assert collab_req(base, PREFIX + "/jobs", "reader", bad_body, token)[0] == 403
        assert collab_req(base, PREFIX + "/jobs", "editor", bad_body, token)[0] == 403
        assert collab_req(base, PREFIX + "/jobs", "reviewer", bad_body, token)[0] == 400

        import canonical_pipeline as cp
        monkeypatch.setattr(cp.subprocess, "Popen", lambda *a, **k: type("P", (), {"pid": 51001, "poll": lambda s: None})())
        monkeypatch.setattr(cp, "process_stamp", lambda pid, req=None: {"pid": pid, "start": "1", "boot": "b"})
        monkeypatch.setattr(cp.os, "killpg", lambda pid, sig: None)

        ok_body = {
            "request_id": str(uuid.uuid4()), "kind": "align_real", "arm_id": "arm_b",
            "params": {"source_id": "real_b", "wrist_flip": True, "trim_dead_idle": True},
        }
        code_ok, run = collab_req(base, PREFIX + "/jobs", "reviewer", ok_body, token)
        assert code_ok == 200 and run["status"] == "running" and run["policy_activation"] is False
        assert str(tmp_path) not in json.dumps(run)

        c_run, detail = collab_req(base, f"{PREFIX}/runs/{run['id']}", "reader")
        assert c_run == 200 and detail["id"] == run["id"] and "log_tail" in detail

        c_watch, watched = collab_req(base, f"{PREFIX}/watched/mp", "reader")
        assert c_watch == 200 and watched["id"] == "mp" and str(tmp_path) not in json.dumps(watched)

        c_cancel, stopped = collab_req(base, f"{PREFIX}/jobs/{run['id']}/cancel", "reviewer", {}, token)
        assert c_cancel == 200 and stopped["status"] == "stopping"

        # GPU busy conflict returns 409.
        gpu_body = {
            "request_id": str(uuid.uuid4()), "kind": "collect_dart", "arm_id": "arm_b",
            "params": {"episodes": 10, "seed": 1, "jitter_deg": 2.0, "color_random": True, "pose_random": True},
        }
        monkeypatch.setattr(center.canonical, "start_job", lambda b: (_ for _ in ()).throw(cp.BusyConflict("gpu busy")))
        assert collab_req(base, PREFIX + "/jobs", "reviewer", gpu_body, token)[0] == 409
