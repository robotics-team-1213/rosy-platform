from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
import urllib.request
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import cell_job_api as api  # noqa: E402


def _make_workdir(tmp_path: Path) -> Path:
    for name in ("cell-a.json", "cell-b.json", "cell-s.json", "catalog-live.json", "chunks-s.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    (tmp_path / "tools-env-current.sh").write_text("export OMX=~/rosy-test/omx-tools-abc1234/deploy/robot/omx\n", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    ("job", "site_params", "status"),
    [
        ("auto_pick", {"source": "pinky"}, 400),
        ("auto_pick", {"source": "pinky_42"}, 400),
        ("auto_pick", {"source": "bed-1"}, 400),
        ("auto_pick", {"source": "inbound"}, 202),
        ("auto_pick", {"source": "belt", "dest": "pinky"}, 400),
        ("auto_pick_dry_run", {"source": "pinky"}, 202),
        ("pivot_near", {"site": "bed-1"}, 400),
    ],
)
def test_runner_requires_r_cell_task_for_amr_bed_motion(tmp_path, monkeypatch, job, site_params, status):
    params = {"config": "cell-s.json", **site_params}
    if job != "auto_pick_dry_run":
        params.update(arm="arm_s", person_at_switch=True)
    if job == "pivot_near":
        params.update(x=0.0, y=0.0)
    else:
        params.update(catalog="catalog-live.json", roi=[0, 0, 10, 10], dest="outbound")
    params.update(site_params)

    wd = _make_workdir(tmp_path)
    popen = Mock()
    monkeypatch.setattr(api.subprocess, "Popen", popen)
    result = api.Runner(wd, lock_dir=wd).start(job, params)

    assert result["code"] == status
    if status == 400:
        assert "R cell-task -> cell_task_worker -> Gate" in result["error"]
        popen.assert_not_called()
    else:
        popen.assert_called_once()


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
    assert "--dry-run" in drive_argv and "--person-at-switch" not in drive_argv
    assert drive_argv[0] == "bash"
    assert "--commissioning" not in drive_argv
    live = {**base_policy, "dry_run": False}
    assert api.build_argv(api.JOBS["cell_policy_drive"], live, wd)[0] == "./with-session-arm-s-live.sh"
    with pytest.raises(ValueError, match="person_at_switch"):
        api.build_argv(api.JOBS["cell_policy_drive"], {**live, "person_at_switch": False}, wd)

    job = api.JOBS["cell_policy_drive"]
    with_goal = {**base_policy, "goal_site": "yard:r3-s2-t1"}
    del with_goal["model_calibration"]
    argv = api.build_argv(job, with_goal, wd)
    assert argv[argv.index("--goal-site") + 1] == "yard:r3-s2-t1"
    assert "--model-calibration" not in argv
    hybrid = api.build_argv(job, {**with_goal, "mode": "hybrid", "n_action": 8, "max_obs_age_s": 0.6}, wd)
    assert hybrid[hybrid.index("--mode") + 1] == "hybrid"
    assert hybrid[hybrid.index("--n-action") + 1] == "8"
    assert hybrid[hybrid.index("--max-obs-age-s") + 1] == "0.6"
    taught = {k: v for k, v in with_goal.items() if k not in {"policy_root", "policy_revision", "cell_calibration"}}
    fallback = api.build_argv(job, {**taught, "mode": "taught"}, wd)
    assert fallback[fallback.index("--mode") + 1] == "taught" and "--policy-root" not in fallback
    with pytest.raises(ValueError, match="goal_site"):
        api.build_argv(job, {**base_policy, "mode": "hybrid"}, wd)
    for site in ("yard:r3-s1-t1", "yard:r3-s2-t1; park", 9):
        with pytest.raises(ValueError, match="goal_site"):
            api.build_argv(job, {**base_policy, "goal_site": site}, wd)

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
