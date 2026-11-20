from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
import urllib.request

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import cell_job_api as api  # noqa: E402


def _make_workdir(tmp_path: Path) -> Path:
    for name in ("cell-a.json", "cell-b.json", "cell-s.json", "catalog-live.json", "chunks-s.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    (tmp_path / "tools-env-current.sh").write_text("export OMX=~/rosy-test/omx-tools-abc1234/deploy/robot/omx\n", encoding="utf-8")
    return tmp_path


def test_remap_and_policy_drive_argv_validation(tmp_path):
    wd = _make_workdir(tmp_path)
    remap_argv = api.build_argv(api.JOBS["remap"], {"arm": "arm_s", "config": "cell-s.json", "person_at_switch": True}, wd)
    assert remap_argv[0] == "./with-session-arm-s-live.sh"
    assert "cell_calibrate.py" in remap_argv
    assert "--only" in remap_argv and "remap" in remap_argv and "regions" in remap_argv
    assert "--commissioning" in remap_argv and "--person-at-switch" in remap_argv

    sha = "a" * 64
    base_policy = {
        "arm": "arm_s",
        "config": "cell-s.json",
        "library": "chunks-s.json",
        "policy_root": "~/rosy-models/pinky_v1",
        "policy_revision": sha,
        "model_calibration": "model.json",
        "cell_calibration": "cell.json",
        "max_chunks": 3,
        "operator": "op_b",
        "proposer": "op_a",
        "dry_run": True,
        "person_at_switch": True,
    }
    drive_argv = api.build_argv(api.JOBS["cell_policy_drive"], base_policy, wd)
    assert "cell_policy_drive.py" in drive_argv
    assert "--dry-run" in drive_argv and "--person-at-switch" in drive_argv
    assert "--commissioning" not in drive_argv

    with pytest.raises(ValueError, match="D-1024"):
        api.build_argv(api.JOBS["cell_policy_drive"], {**base_policy, "proposer": "op_b"}, wd)
    with pytest.raises(ValueError, match="max_chunks"):
        api.build_argv(api.JOBS["cell_policy_drive"], {**base_policy, "max_chunks": 7}, wd)
    with pytest.raises(ValueError, match="safe path"):
        api.build_argv(api.JOBS["cell_policy_drive"], {**base_policy, "policy_root": "../secret"}, wd)


def test_runner_serializes_arms_ab_space_camera_locks_and_http_queue(tmp_path, monkeypatch):
    wd = _make_workdir(tmp_path)

    class FakeProc:
        def __init__(self, code=None):
            self._code = code

        def poll(self):
            return self._code

    procs = []
    monkeypatch.setattr(api.subprocess, "Popen", lambda *a, **kw: procs.append(FakeProc(None)) or procs[-1])
    monkeypatch.setattr(api, "_session_lock_held", lambda arm, _ld=None: arm == "arm_s")

    runner = api.Runner(wd)
    res_lock = runner.start("remap", {"arm": "arm_s", "config": "cell-s.json", "person_at_switch": True})
    assert res_lock["code"] == 409 and "session lock" in res_lock["error"]

    res_a = runner.start("remap", {"arm": "arm_a", "config": "cell-a.json", "person_at_switch": True, "purpose": "calib_a"})
    assert res_a["code"] == 202

    # Same arm, A/B space, and camera serialization
    res_same = runner.start("remap", {"arm": "arm_a", "config": "cell-a.json", "person_at_switch": True})
    assert res_same["code"] == 409 and "already runs on arm_a" in res_same["error"]
    res_b = runner.start("remap", {"arm": "arm_b", "config": "cell-b.json", "person_at_switch": True})
    assert res_b["code"] == 409 and "A/B cell space" in res_b["error"]
    res_cam = runner.start("calibrate_check", {"config": "cell-s.json"})
    assert res_cam["code"] == 409 and "another camera job" in res_cam["error"]

    # HTTP GET /queue returns holder, purpose, started_at, expires_at
    token = "t" * 32
    server = api.make_server("127.0.0.1", 0, token, runner)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/queue", headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            q = json.loads(resp.read().decode("utf-8"))
        assert len(q["active"]) == 1
        item = q["active"][0]
        assert item["id"] == res_a["id"] and item["holder"] == "arm_a" and item["purpose"] == "calib_a"
        assert item["expires_at"] > item["started_at"]
    finally:
        server.shutdown()
        server.server_close()

    # Finish arm_a and verify audit state_changes
    procs[0]._code = 0
    info = runner.get(res_a["id"])
    assert info["running"] is False and info["exit"] == 0
    audit = json.loads((wd / "cell-job-api" / "audit.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert audit["state_changes"]["arm"] == "arm_a"
    assert audit["state_changes"]["omx_tools_tree"] == "omx-tools-abc1234"
