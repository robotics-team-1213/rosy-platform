from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import urllib.request
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import cell_job_api as api  # noqa: E402


@pytest.fixture(autouse=True)
def _stop_proof_passes(monkeypatch):
    """These tests are about the job API's other gates; the D-1077 proof itself is tested in test_omx_stop_proof.py."""
    monkeypatch.setattr(api, "prove_job", lambda *a, **k: ({"ok": True, "stub": True}, None))


def _make_workdir(tmp_path: Path) -> Path:
    for name in ("cell-a.json", "cell-b.json", "cell-s.json", "catalog-live.json", "chunks-s.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    (tmp_path / "tools-env-current.sh").write_text("export OMX=~/rosy-test/omx-tools-abc1234/deploy/robot/omx\n", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(("job", "arm", "expected"), [
    ("remap", "arm_a", "arm_a"), ("remap", "arm_b", "arm_b"),
    ("remap", "arm_s", None), ("calibrate_check", "arm_a", None),
])
def test_baseline_recovery_is_bound_to_supervised_ab_remap(tmp_path, monkeypatch, job, arm, expected):
    popen = Mock(return_value=Mock(poll=Mock(return_value=0)))
    monkeypatch.setattr(api.subprocess, "Popen", popen)
    monkeypatch.setenv("ROSY_BASELINE_RECOVERY_ARM", "arm_b")
    runner = api.Runner(_make_workdir(tmp_path))
    params = {"config": f"cell-{arm[-1]}.json"}
    if job == "remap":
        params.update(arm=arm, person_at_switch=True)
    assert runner.start(job, params)["code"] == 202
    assert popen.call_args.kwargs["env"].get("ROSY_BASELINE_RECOVERY_ARM") == expected
    if expected:
        launched = popen.call_args.args[0]
        wrapper = Path(launched[launched.index("--") + 1])  # remap is a camera job: cell_camera_heal runs first
        assert wrapper == Path(api.__file__).parent / "session-wrappers" / Path(api.SESSION[arm]).name
        assert wrapper.is_file()
        assert popen.call_args.kwargs["env"]["TOOLS_ROOT"] == str(wrapper.parents[4])


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
        ("cell_policy_drive", {"goal_site": "tray"}, 400),
        ("cell_policy_drive", {"goal_site": "vehicle_tray"}, 400),
        ("cell_policy_drive", {"goal_site": "not_places:vehicle_tray"}, 400),
        ("cell_policy_drive", {"goal_site": "tray", "dry_run": True}, 202),
    ],
)
def test_runner_requires_r_cell_task_for_amr_bed_motion(tmp_path, monkeypatch, job, site_params, status):
    params = {"config": "cell-s.json", **site_params}
    if job != "auto_pick_dry_run":
        params.update(arm="arm_s", person_at_switch=True)
    if job == "pivot_near":
        params.update(x=0.0, y=0.0)
    elif job == "cell_policy_drive":
        params.update(
            library="chunks-s.json",
            max_chunks=1,
            operator="human_op",
            policy_root="~/rosy-models/pinky_v1",
            policy_revision="a" * 64,
            cell_calibration="cell.json",
        )
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
    assert (Path.home() / ".local/share/rosy/omx-devices/current").resolve() == Path(drive_argv[4])
    assert "/session-wrappers/tools-env.sh" in drive_argv[2]
    assert "tools-env-current.sh" not in drive_argv[2]
    arm_b_argv = api.build_argv(api.JOBS["cell_policy_drive"], {**base_policy, "arm": "arm_b"}, wd)
    assert "tools-env-current.sh" in arm_b_argv[2]
    paced_argv = api.build_argv(api.JOBS["cell_policy_drive"], {**base_policy, "paced_chunks": True, "n_action": 8}, wd)
    assert "--paced-chunks" in paced_argv and "--n-action" in paced_argv
    with pytest.raises(ValueError, match="paced_chunks"):  # paced hybrid is admitted (ACT grasp, taught carry), taught is not
        api.build_argv(api.JOBS["cell_policy_drive"], {**base_policy, "paced_chunks": True, "mode": "taught", "goal_site": "yard:r3-s2-t1"}, wd)
    hybrid_paced = api.build_argv(api.JOBS["cell_policy_drive"], {**base_policy, "paced_chunks": True, "mode": "hybrid", "goal_site": "yard:r3-s2-t1"}, wd)
    assert "--paced-chunks" in hybrid_paced and hybrid_paced[hybrid_paced.index("--mode") + 1] == "hybrid"
    live = {**base_policy, "dry_run": False}
    assert api.build_argv(api.JOBS["cell_policy_drive"], live, wd)[0] == "./with-session-arm-s-live.sh"
    assert api.build_argv(api.JOBS["cell_policy_drive"], {**live, "person_at_switch": False}, wd)[-1] == "--person-at-switch"  # D-1077: ignored here, the runner's proof gates

    job = api.JOBS["cell_policy_drive"]
    with_goal = {**base_policy, "goal_site": "yard:r3-s2-t1"}
    del with_goal["model_calibration"]
    argv = api.build_argv(job, with_goal, wd)
    assert argv[argv.index("--goal-site") + 1] == "yard:r3-s2-t1"
    assert "--model-calibration" not in argv
    hybrid = api.build_argv(job, {**with_goal, "mode": "hybrid", "n_action": 8, "max_obs_age_s": 0.6, "source_kind": "policy"}, wd)
    assert hybrid[hybrid.index("--mode") + 1] == "hybrid"
    assert hybrid[hybrid.index("--n-action") + 1] == "8"
    assert hybrid[hybrid.index("--max-obs-age-s") + 1] == "0.6"
    assert hybrid[hybrid.index("--source-kind") + 1] == "policy"
    mixed_actor = api.build_argv(job, {**with_goal, "proposer": "Alice.Kim", "operator": "Bob.Lee"}, wd)
    assert mixed_actor[mixed_actor.index("--operator") + 1] == "Bob.Lee"
    with pytest.raises(ValueError, match="D-1024"):
        api.build_argv(job, {**with_goal, "proposer": "Alice.Kim", "operator": "alice.kim"}, wd)
    with pytest.raises(ValueError, match="source_kind"):
        api.build_argv(job, {**with_goal, "source_kind": "bogus"}, wd)
    for bad_sk in ("scripted_teacher", "sim_optimized"):
        with pytest.raises(ValueError, match="policy"):
            api.build_argv(job, {**with_goal, "mode": "act", "source_kind": bad_sk}, wd)
        with pytest.raises(ValueError, match="policy"):
            api.build_argv(job, {**with_goal, "mode": "hybrid", "source_kind": bad_sk}, wd)
    taught = {k: v for k, v in with_goal.items() if k not in {"policy_root", "policy_revision", "cell_calibration"}}
    with pytest.raises(ValueError, match="taught"):
        api.build_argv(job, {**taught, "mode": "taught", "source_kind": "policy"}, wd)
    sim_taught = api.build_argv(job, {**taught, "mode": "taught", "source_kind": "sim_optimized"}, wd)
    assert sim_taught[sim_taught.index("--source-kind") + 1] == "sim_optimized"
    fallback = api.build_argv(job, {**taught, "mode": "taught"}, wd)
    assert fallback[fallback.index("--mode") + 1] == "taught" and "--policy-root" not in fallback
    with pytest.raises(ValueError, match="goal_site"):
        api.build_argv(job, {**base_policy, "mode": "hybrid"}, wd)
    for site in ("yard:r3-s1-t1", "yard:r3-s2-t1; park", 9):
        with pytest.raises(ValueError, match="goal_site"):
            api.build_argv(job, {**base_policy, "goal_site": site}, wd)

    with pytest.raises(ValueError, match="D-1024"):
        api.build_argv(api.JOBS["cell_policy_drive"], {**base_policy, "proposer": "op_b"}, wd)
    assert api.build_argv(api.JOBS["cell_policy_drive"], {**base_policy, "max_chunks": 60}, wd)
    with pytest.raises(ValueError, match="max_chunks"):
        api.build_argv(api.JOBS["cell_policy_drive"], {**base_policy, "max_chunks": 61}, wd)
    remote_lo = api.build_argv(api.JOBS["cell_policy_drive"], {**base_policy, "arm": "arm_b", "endpoint_url": "http://127.0.0.1:8790"}, wd)
    assert "--endpoint-url" in remote_lo and remote_lo[remote_lo.index("--arm-id") + 1] == "arm_b"
    remote_tok = api.build_argv(api.JOBS["cell_policy_drive"], {**base_policy, "endpoint_url": "http://100.108.76.123:8790", "token_file": "tok", "timeout_s": 0.5}, wd)
    assert "--token-file" in remote_tok and remote_tok[remote_tok.index("--timeout-s") + 1] == "0.5"
    for bad_ep in (
        {"endpoint_url": "http://100.108.76.123:8790"},
        {"token_file": "tok"},
        {"endpoint_url": "http://127.0.0.1:8790", "mode": "taught", "goal_site": "yard:r3-s2-t1"},
    ):
        with pytest.raises(ValueError):
            api.build_argv(api.JOBS["cell_policy_drive"], {**base_policy, **bad_ep}, wd)
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


def test_home_job_argv_requires_person_and_session(tmp_path):
    wd = _make_workdir(tmp_path)
    (wd / "chunks-a.json").write_text("{}", encoding="utf-8")
    argv = api.build_argv(
        api.JOBS["home"],
        {
            "arm": "arm_a",
            "config": "cell-a.json",
            "library": "chunks-a.json",
            "operating_profile": "profile-a.json",
            "operator": "human_op",
            "proposer": "vlm_orchestrator",
            "person_at_switch": True,
        },
        wd,
    )
    assert argv[0] == "./with-session-arm-a-par.sh"
    assert "cell_pipeline.py" in argv
    assert "--stage" in argv and "home" in argv
    assert "--commissioning" in argv and "--person-at-switch" in argv
    assert "--operator" not in argv and "--proposer" not in argv
    with pytest.raises(ValueError, match="D-1024"):
        api.build_argv(
            api.JOBS["home"],
            {
                "arm": "arm_a",
                "config": "cell-a.json",
                "library": "chunks-a.json",
                "operating_profile": "profile-a.json",
                "operator": "same_id",
                "proposer": "same_id",
                "person_at_switch": True,
            },
            wd,
        )
    with pytest.raises(ValueError, match="D-1024"):
        api.build_argv(
            api.JOBS["auto_pick"],
            {
                "arm": "arm_b",
                "config": "cell-b.json",
                "catalog": "catalog-live.json",
                "roi": [0, 0, 10, 10],
                "source": "belt",
                "dest": "pallet",
                "proposer": "vlm_orchestrator",
                "person_at_switch": True,
            },
            wd,
        )
    pick_argv = api.build_argv(
        api.JOBS["auto_pick"],
        {
            "arm": "arm_b",
            "config": "cell-b.json",
            "catalog": "catalog-live.json",
            "roi": [0, 0, 10, 10],
            "source": "belt",
            "dest": "pallet",
            "operator": "human_op",
            "proposer": "vlm_orchestrator",
            "person_at_switch": True,
        },
        wd,
    )
    assert "--operator" not in pick_argv and "--proposer" not in pick_argv


def test_frame_proxy_returns_clean_json_on_viewer_http_error(tmp_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import urllib.error

    class FailingViewer(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def do_GET(self):
            self.send_response(404)
            self.end_headers()

    viewer = ThreadingHTTPServer(("127.0.0.1", 0), FailingViewer)
    threading.Thread(target=viewer.serve_forever, daemon=True).start()
    wd = _make_workdir(tmp_path)
    token = "t" * 32
    server = api.make_server("127.0.0.1", 0, token, api.Runner(wd, lock_dir=wd), viewer=f"http://127.0.0.1:{viewer.server_port}")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/frame/arm_b_wrist.jpg",
            headers={"Authorization": f"Bearer {token}"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=5)
        assert exc.value.code == 404
        body = json.loads(exc.value.read().decode("utf-8"))
        assert "404" in body["error"]
    finally:
        server.shutdown()
        server.server_close()
        viewer.shutdown()
        viewer.server_close()


def test_resolve_goal_site_supports_standalone_cell_api_layout(tmp_path):
    import shutil
    import subprocess

    repo_root = Path(__file__).resolve().parents[1]
    stage = tmp_path / "cell-job-api"
    (stage / "tools" / "sim").mkdir(parents=True)
    (stage / "shared" / "web").mkdir(parents=True)
    shutil.copy2(repo_root / "deploy" / "robot" / "omx" / "cell_policy_goals.py", stage / "cell_policy_goals.py")
    shutil.copy2(repo_root / "tools" / "sim" / "cell_site_map.py", stage / "tools" / "sim" / "cell_site_map.py")
    shutil.copy2(repo_root / "shared" / "web" / "cell-site-map.json", stage / "shared" / "web" / "cell-site-map.json")
    out = subprocess.check_output(
        [sys.executable, "-c", "import cell_policy_goals as g; print(g.resolve_goal_site('yard:r1-s2-t1'))"],
        cwd=stage,
        text=True,
    )
    assert "ship-h1r0-l0" in out


def test_check_arm_incident_hold_supports_standalone_cell_api_layout(tmp_path):
    import os
    import shutil
    import subprocess

    repo_root = Path(__file__).resolve().parents[1]
    stage = tmp_path / "cell-job-api"
    stage.mkdir()
    for name in (
        "cell_decisions.py",
        "cell_job_guards.py",
        "cell_job_peer_health.py",
        "cell_params.py",
        "joint_push.py",
        "joint_tune_lock.py",
        "omx_incident.py",
        "omx_incident_auto.py",
        "omx_incident_fleet.py",
        "omx_incident_reading.py",
        "omx_incident_reassess.py",
        "push_replay.py",
    ):
        shutil.copy2(repo_root / "deploy" / "robot" / "omx" / name, stage / name)

    omx_home = tmp_path / "omx-home"
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["ROSY_OMX_HOME"] = str(omx_home)

    script_unheld = (
        "import cell_job_guards as g; "
        "assert g.check_arm_incident_hold('arm_a') is None"
    )
    subprocess.check_call([sys.executable, "-c", script_unheld], cwd=stage, env=env)

    inc_dir = omx_home / "incidents"
    inc_dir.mkdir(parents=True)
    (inc_dir / "HOLD-arm_a.json").write_text(json.dumps({"reason": "elbow overload"}), encoding="utf-8")

    script_held = (
        "import cell_job_guards as g; "
        "res = g.check_arm_incident_hold('arm_a'); "
        "assert res and 'elbow overload' in res, res"
    )
    subprocess.check_call([sys.executable, "-c", script_held], cwd=stage, env=env)


def test_runner_whole_cell_ab_cross_lock_and_warm_reuse(tmp_path, monkeypatch):
    wd = _make_workdir(tmp_path)
    lease_dir = tmp_path / "leases"
    lease_dir.mkdir()
    (wd / "chunk-io-b").mkdir()
    procs = []

    def fake_popen(argv, **kwargs):
        p = Mock()
        p.argv = argv
        p.env = kwargs.get("env") or {}
        p._code = None
        p.poll.side_effect = lambda: p._code
        procs.append(p)
        return p

    monkeypatch.setattr(api.subprocess, "Popen", fake_popen)
    runner = api.Runner(wd, lock_dir=wd, lease_dir=lease_dir)

    # 1. Whole-cell session.lock blocks moving jobs
    monkeypatch.setattr(api, "_whole_cell_lock_held", lambda _ld=None: True)
    res_whole = runner.start("remap", {"arm": "arm_a", "config": "cell-a.json", "person_at_switch": True})
    assert res_whole["code"] == 409 and "whole-cell session.lock" in res_whole["error"]

    # 2. External arm_b lock blocks arm_a moving job (A/B cross-arm lock check)
    monkeypatch.setattr(api, "_whole_cell_lock_held", lambda _ld=None: False)
    monkeypatch.setattr(api, "_session_lock_held", lambda arm, _ld=None: arm == "arm_b")
    res_cross = runner.start("remap", {"arm": "arm_a", "config": "cell-a.json", "person_at_switch": True})
    assert res_cross["code"] == 409 and "session lock for arm_b" in res_cross["error"]

    # 3. Run arm_b cleanly, then warm-reuse arm_b when lease + exit 0 + clean live.json all hold
    monkeypatch.setattr(api, "_session_lock_held", lambda arm, _ld=None: False)
    first = runner.start("remap", {"arm": "arm_b", "config": "cell-b.json", "person_at_switch": True})
    assert first["code"] == 202
    assert procs[0].env["ROSY_ARM_LEASE_OWNER"] == runner._lease_owner
    procs[0]._code = 0

    monkeypatch.setattr(api, "_session_lock_held", lambda arm, _ld=None: arm == "arm_b")
    (lease_dir / "arm_b.json").write_text(json.dumps({"owner": runner._lease_owner}), encoding="utf-8")
    (wd / "chunk-io-b" / "live.json").write_text(
        json.dumps({"chunk": None, "human_hold_latched": False, "fault": False}),
        encoding="utf-8",
    )
    reused = runner.start("remap", {"arm": "arm_b", "config": "cell-b.json", "person_at_switch": True})
    assert reused["code"] == 202
    procs[1]._code = 0

    # 4. Warm reuse is refused if human_hold_latched, lease hold, or foreign owner
    (wd / "chunk-io-b" / "live.json").write_text(
        json.dumps({"chunk": None, "human_hold_latched": True, "fault": False}),
        encoding="utf-8",
    )
    refused_hold = runner.start("remap", {"arm": "arm_a", "config": "cell-a.json", "person_at_switch": True})
    assert refused_hold["code"] == 409

    (wd / "chunk-io-b" / "live.json").write_text(
        json.dumps({"chunk": None, "human_hold_latched": False, "fault": False}),
        encoding="utf-8",
    )
    (lease_dir / "arm_b.json").write_text(json.dumps({"owner": "other:99"}), encoding="utf-8")
    refused_owner = runner.start("remap", {"arm": "arm_b", "config": "cell-b.json", "person_at_switch": True})
    assert refused_owner["code"] == 409

    # 5. Stale live.json timestamp or dead pid refuses warm reuse
    import time

    (lease_dir / "arm_b.json").write_text(json.dumps({"owner": runner._lease_owner, "pid": 12345}), encoding="utf-8")
    (wd / "chunk-io-b" / "live.json").write_text(
        json.dumps({"chunk": None, "human_hold_latched": False, "fault": False, "t": time.time() - 60.0}),
        encoding="utf-8",
    )
    refused_stale = runner.start("remap", {"arm": "arm_b", "config": "cell-b.json", "person_at_switch": True})
    assert refused_stale["code"] == 409

    (wd / "chunk-io-b" / "live.json").write_text(
        json.dumps({"chunk": None, "human_hold_latched": False, "fault": False, "t": time.time()}),
        encoding="utf-8",
    )
    monkeypatch.setattr(api, "_pid_alive", lambda _pid: False)
    refused_dead = runner.start("remap", {"arm": "arm_b", "config": "cell-b.json", "person_at_switch": True})
    assert refused_dead["code"] == 409


def test_runner_daemon_reaper_writes_audit_without_get_poll(tmp_path, monkeypatch):
    import subprocess
    import time

    wd = _make_workdir(tmp_path)
    runner = api.Runner(wd, jobs={"noop": {"script": "noop.py", "argv": [], "params": {}}}, lock_dir=wd)
    monkeypatch.setattr(api, "build_argv", lambda job, params, workdir: [sys.executable, "-c", "pass"])
    res = runner.start("noop", {})
    assert res["code"] == 202

    audit_file = wd / "cell-job-api" / "audit.jsonl"
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if audit_file.is_file() and audit_file.read_text(encoding="utf-8").strip():
            break
        time.sleep(0.02)
    else:
        pytest.fail("audit.jsonl was not written automatically by daemon reaper")
    row = json.loads(audit_file.read_text(encoding="utf-8").splitlines()[0])
    assert row["id"] == res["id"] and row["exit"] == 0 and isinstance(subprocess.Popen, type)


def test_tools_tree_resolves_symlink_skips_comments_and_snapshots_start(tmp_path, monkeypatch):
    wd = _make_workdir(tmp_path)
    real_a = tmp_path / "omx-tools-3fff92e55d"
    real_b = tmp_path / "omx-tools-deadbeef00"
    real_a.mkdir()
    real_b.mkdir()
    link = tmp_path / "omx-tools-current"
    link.symlink_to(real_a)
    (wd / "tools-env-current.sh").write_text(
        f"# omx-tools-stale999\nFOO=1 # omx-tools-inline999\nexport OMX={link}/deploy/robot/omx\n",
        encoding="utf-8",
    )
    assert api._tools_tree(wd) == "omx-tools-3fff92e55d"

    loop_a = tmp_path / "omx-tools-loop"
    loop_b = tmp_path / "omx-tools-loop-b"
    loop_a.symlink_to(loop_b)
    loop_b.symlink_to(loop_a)
    eloop_wd = tmp_path / "eloop-wd"
    eloop_wd.mkdir()
    (eloop_wd / "tools-env-current.sh").write_text(f"export OMX={loop_a}/deploy/robot/omx\n", encoding="utf-8")
    assert api._tools_tree(eloop_wd) == "omx-tools-loop"

    procs = []

    class P:
        _code = None

        def poll(self):
            return self._code

    monkeypatch.setattr(api.subprocess, "Popen", lambda argv, **kw: (procs.append(P()) or procs[-1]))
    runner = api.Runner(wd, jobs={"noop": {"script": "noop.py", "argv": [], "params": {}}}, lock_dir=wd)
    monkeypatch.setattr(api, "build_argv", lambda job, params, workdir: ["true"])
    started = runner.start("noop", {})
    assert started["code"] == 202

    # Switch symlink BEFORE exit: audit record keeps the start-time snapshot.
    link.unlink()
    link.symlink_to(real_b)
    procs[0]._code = 0
    runner.get(started["id"])
    row = json.loads((wd / "cell-job-api" / "audit.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert row["state_changes"]["omx_tools_tree"] == "omx-tools-3fff92e55d"


def test_goal_site_import_error_returns_http_400(tmp_path, monkeypatch):
    import cell_job_spec as spec

    wd = _make_workdir(tmp_path)
    monkeypatch.setattr(spec, "resolve_goal_site", lambda _v: (_ for _ in ()).throw(ModuleNotFoundError("cell_site_map")))
    res = api.Runner(wd, lock_dir=wd).start(
        "cell_policy_drive",
        {
            "arm": "arm_a",
            "config": "cell-a.json",
            "library": "chunks-s.json",
            "max_chunks": 1,
            "mode": "taught",
            "goal_site": "yard:r3-s2-t1",
            "operator": "human_op",
            "proposer": "vlm",
            "person_at_switch": True,
        },
    )
    assert res["code"] == 400 and "cannot read Cell site map" in res["error"]


def test_cell_job_api_service_unit_preserves_detached_arm_sessions():
    unit_path = Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx" / "rosy-omx-cell-job-api.service"
    text = unit_path.read_text(encoding="utf-8")
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
    assert "KillMode=process" in lines
    assert "KillMode=control-group" not in lines
    assert "NoNewPrivileges=true" in lines
    assert "UMask=0077" in lines
    assert any(line.startswith("ExecStart=") and "exec /usr/bin/python3" in line for line in lines)


def test_surface_job_argv_requires_person_at_switch(tmp_path):
    wd = _make_workdir(tmp_path)
    (wd / "cell-b.json").write_text(json.dumps({"sites": {"pallet": {}}}), encoding="utf-8")
    argv = api.build_argv(api.JOBS["surface"], {"arm": "arm_b", "config": "cell-b.json", "person_at_switch": True}, wd)
    assert argv[0] == "./with-session-arm-b-par.sh"
    assert "cell_calibrate.py" in argv
    assert argv[argv.index("--only") + 1] == "surface"
    assert "--commissioning" in argv and "--person-at-switch" in argv
    (wd / "cell-s.json").write_text(json.dumps({"sites": {"pinky": {"place": [0.1, 0.2]}}}), encoding="utf-8")
    with pytest.raises(ValueError, match="R cell-task -> cell_task_worker -> Gate"):
        api.build_argv(api.JOBS["surface"], {"arm": "arm_s", "config": "cell-s.json", "person_at_switch": True}, wd)
    (wd / "cell-s.json").write_text("{bad json", encoding="utf-8")
    with pytest.raises(ValueError, match="surface calibration config"):
        api.build_argv(api.JOBS["surface"], {"arm": "arm_s", "config": "cell-s.json", "person_at_switch": True}, wd)
    (wd / "cell-s.json").write_text(json.dumps({"sites": {"pinky": {"surface_z": 0.031}, "belt": {}}}), encoding="utf-8")
    assert api.build_argv(api.JOBS["surface"], {"arm": "arm_s", "config": "cell-s.json", "person_at_switch": True}, wd)[0] == "./with-session-arm-s-live.sh"


def test_cell_job_api_is_managed_by_omx_devices_autoupdate():
    import yaml

    root = Path(__file__).resolve().parents[1]
    unit = (root / "deploy" / "robot" / "omx" / "rosy-omx-cell-job-api.service").read_text(encoding="utf-8")
    assert "Environment=ROSY_CELL_JOB_API_ROOT=%h/.local/share/rosy/omx-devices/current/deploy/robot/omx" in unit
    example = json.loads((root / "deploy" / "robot" / "omx" / "omx-devices-autoupdate.json.example").read_text(encoding="utf-8"))
    assert "rosy-omx-cell-job-api.service" in example["units"]
    assert "deploy/robot/omx/rosy-omx-cell-job-api.service" in example["unit_files"]
    assert "cell_job_api" in example["smoke"]
    entry = yaml.safe_load((root / "deploy" / "hosts" / "services.yaml").read_text(encoding="utf-8"))["roles"]["omx"]["rosy-omx-cell-job-api.service"]
    assert entry["channel"] == "autoupdate"
    assert entry["source"] == ".local/share/rosy/omx-devices/current"


def test_check_arm_incident_hold_syncs_stale_local_hold_only_when_fleet_confirmed_clear(monkeypatch):
    from types import SimpleNamespace
    import cell_job_guards as guards

    def _run_case(statuses, *, sync_result):
        calls = []
        seq = list(statuses)

        def _status(_arm):
            return seq.pop(0) if len(seq) > 1 else seq[0]

        def _sync(arm):
            calls.append(arm)
            return sync_result

        fake_mod = SimpleNamespace(
            status=_status,
            sync_hold_from_fleet=_sync,
            hold_file=lambda _arm: None,
        )
        monkeypatch.setitem(sys.modules, "omx_incident", fake_mod)
        return guards.check_arm_incident_hold("arm_b"), calls

    # (a) Fleet confirms clear and outbox is empty -> sync lifts stale local hold and re-check passes
    res_a, calls_a = _run_case(
        [
            {"local_held": True, "local_reason": "runner: human hold", "fleet_held": False, "unsent_outbox": 0},
            {"local_held": False, "local_reason": None, "fleet_held": False, "unsent_outbox": 0},
        ],
        sync_result=True,
    )
    assert res_a is None and calls_a == ["arm_b"]

    # (b) Sync race (Fleet became held or unreachable during sync) -> stays held fail-closed
    res_b, calls_b = _run_case(
        [{"local_held": True, "local_reason": "runner: human hold", "fleet_held": False, "unsent_outbox": 0}],
        sync_result=False,
    )
    assert res_b == "runner: human hold" and calls_b == ["arm_b"]

    # (c) Fleet unreachable (fleet_held=None) -> never calls sync, stays held fail-closed
    res_c, calls_c = _run_case(
        [{"local_held": True, "local_reason": "runner: human hold", "fleet_held": None, "unsent_outbox": 0}],
        sync_result=True,
    )
    assert res_c == "runner: human hold" and calls_c == []

    # (d) Unsent outbox pending -> never calls sync, stays held fail-closed
    res_d, calls_d = _run_case(
        [{"local_held": True, "local_reason": "runner: human hold", "fleet_held": False, "unsent_outbox": 1}],
        sync_result=True,
    )
    assert res_d == "runner: human hold" and calls_d == []

    # (e) Fleet also holds the arm -> never calls sync, stays held fail-closed
    res_e, calls_e = _run_case(
        [{"local_held": True, "local_reason": "runner: human hold", "fleet_held": True, "unsent_outbox": 0}],
        sync_result=True,
    )
    assert res_e == "runner: human hold" and calls_e == []


def test_post_eval_job_guards_amr_bed_and_requires_person_at_switch(tmp_path, monkeypatch):
    wd = _make_workdir(tmp_path)
    base = {"arm": "arm_s", "config": "cell-s.json", "site": "floor", "x": -0.06, "y": 0.15, "person_at_switch": True}
    argv = api.build_argv(api.JOBS["post_eval"], base, wd)
    assert argv[0] == "./with-session-arm-s-live.sh"
    assert "cell_post_eval.py" in argv
    assert argv[argv.index("--targets") + 1] == "floor:-0.06,0.15"
    assert "--apply" not in argv
    assert "--commissioning" in argv and "--person-at-switch" in argv

    argv_apply = api.build_argv(api.JOBS["post_eval"], {**base, "apply": True}, wd)
    assert "--apply" in argv_apply


    popen = Mock()
    monkeypatch.setattr(api.subprocess, "Popen", popen)
    for bad_site in ("pinky", "bed-1"):
        res = api.Runner(wd, lock_dir=wd).start("post_eval", {**base, "site": bad_site})
        assert res["code"] == 400 and "R cell-task -> cell_task_worker -> Gate" in res["error"]
    popen.assert_not_called()


def test_safe_home_job_admits_incident_held_blocks_fleet_stop_and_machine_token(tmp_path, monkeypatch):
    import cell_job_guards as guards

    wd = _make_workdir(tmp_path)
    for fn in ("cell-s.json", "chunks-s.json"):
        (wd / fn).write_text("{}", encoding="utf-8")
    (wd / "tools-env-current.sh").write_text("export OMX=~/rosy-test/omx-tools-abc/deploy/robot/omx\n", encoding="utf-8")
    params = {"arm": "arm_s", "config": "cell-s.json", "library": "chunks-s.json", "site": "floor", "roi": [0, 0, 10, 10]}

    monkeypatch.setattr(api, "_check_depth_lock_held", lambda _ld=None: False)
    lock_held = [False]
    monkeypatch.setattr(api, "_session_lock_held", lambda arm, _ld=None: arm == "arm_s" and lock_held[0])
    popen = Mock(return_value=Mock(poll=Mock(return_value=0)))
    monkeypatch.setattr(api.subprocess, "Popen", popen)

    runner = api.Runner(
        wd, lock_dir=wd,
        incident_check_fn=lambda arm: f"{arm}: 2 open incidents",
        fleet_safety_check_fn=lambda _arm: {"online": True, "blocked": False},
    )
    home_res = runner.start("home", {"arm": "arm_s", "config": "cell-s.json", "library": "chunks-s.json", "operating_profile": "prof.json", "person_at_switch": True})
    assert home_res["code"] == 409 and home_res["error_code"] == "ARM_INCIDENT_HELD"

    from core_common.protocol.arm_incident.home_recovery import HOME_RECOVERY_REASON
    original_check = runner._incident_check_fn
    runner._incident_check_fn = lambda _arm: HOME_RECOVERY_REASON
    pending = runner.start("home", {"arm": "arm_s", "config": "cell-s.json", "library": "chunks-s.json",
                                   "operating_profile": "prof.json", "person_at_switch": True})
    assert pending["code"] == 409 and pending["error_code"] == "HOME_RECOVERY_REQUIRED"
    popen.assert_not_called()
    runner._incident_check_fn = original_check

    mach_res = runner.start("safe_home", params, principal=guards.Principal(guards.ROLE_MACHINE, "bot"))
    assert mach_res["code"] == 403 and mach_res["error_code"] == "MACHINE_COMMISSIONING_FORBIDDEN"

    # External non-hold session lock refuses safe_home (409), while live human-hold attaches (202), and cold arm admits (202).
    lock_held[0] = True
    busy_res = runner.start("safe_home", params)
    assert busy_res["code"] == 409 and "session lock" in busy_res["error"]

    import time as _time
    (wd / "chunk-io-s").mkdir(exist_ok=True)
    (wd / "chunk-io-s" / "live.json").write_text(json.dumps({"t": _time.time(), "chunk": None, "human_hold_latched": True, "torque_hold_commanded": True}), encoding="utf-8")
    hold_res = runner.start("safe_home", params)
    assert hold_res["code"] == 202 and popen.call_count == 1

    lock_held[0] = False
    ok_res = runner.start("safe_home", params)
    assert ok_res["code"] == 202 and popen.call_count == 2

    blocked = api.Runner(
        wd, lock_dir=wd,
        incident_check_fn=lambda arm: f"{arm}: open",
        fleet_safety_check_fn=lambda _arm: {"online": True, "blocked": True, "reason": "E-stop"},
    )
    estop_res = blocked.start("safe_home", params)
    assert estop_res["code"] == 409 and estop_res["error_code"] == "FLEET_SAFETY_STOP"


def test_cell_safe_home_guards_hw_error_incident_cap_and_clears_multi(tmp_path, monkeypatch):
    import cell_safe_home as csh

    cfg_p, lib_p, out_p = tmp_path / "cell.json", tmp_path / "lib.json", tmp_path / "out.json"
    cfg_p.write_text(json.dumps({"arm_id": "arm_s", "io": str(tmp_path / "io")}), encoding="utf-8")
    lib_p.write_text("{}", encoding="utf-8")
    args = SimpleNamespace(arm="arm_s", config=cfg_p, library=lib_p, site="floor", roi=[0, 0, 10, 10],
                           out=out_p, device="/dev/null", max_incidents=3, no_clear=False)

    args_missing = SimpleNamespace(arm="arm_s", config=cfg_p, library=lib_p, site="floor", roi=[0, 0, 10, 10],
                                 out=out_p, device=None, max_incidents=3, no_clear=False)
    monkeypatch.setenv("ROSY_OMX_ARM_BOARDS", str(tmp_path / "missing-boards.json"))
    rc_unavail, res_unavail = csh.run_safe_home(args_missing, live_fn=lambda _c: False)
    assert rc_unavail == 2 and res_unavail["result"] == "refused_hw_probe_unavailable"
    (tmp_path / "boards.json").write_text(json.dumps({"00FB51A150323952582E3120FF070726": "arm_s"}), encoding="utf-8")
    monkeypatch.setenv("ROSY_OMX_ARM_BOARDS", str(tmp_path / "boards.json"))  # /dev/null is unmapped: passes the board check

    rc_alert, res_alert = csh.run_safe_home(
        args, live_fn=lambda _c: False,
        read_fn=lambda _d: (_ for _ in ()).throw(RuntimeError("Motor 11: ping failed (0, 128)")),
    )
    assert rc_alert == 2 and res_alert["result"] == "refused_hw_error"

    rc_hw, res_hw = csh.run_safe_home(
        args, live_fn=lambda _c: False, read_fn=lambda _d: [{"id": 11, "hardware_error": 32}],
    )
    assert rc_hw == 2 and res_hw["result"] == "refused_hw_error"

    rc_cap, res_cap = csh.run_safe_home(
        args, live_fn=lambda _c: False, read_fn=lambda _d: [{"id": 11, "hardware_error": 0}],
        status_fn=lambda _a: {"incident_ids": ["1", "2", "3", "4"]},
    )
    assert rc_cap == 2 and res_cap["result"] == "refused_too_many_incidents"

    cleared = []
    monkeypatch.chdir(tmp_path)
    def fake_run(cmd, env=None, timeout=None):
        assert env and env["ROSY_RECOVERY_INCIDENT"] == "inc-1,inc-2"
        out_p.write_text(json.dumps({"result": "folded", "candidate": "park", "state": [0, -58, 50, 50, -5, 46.5], "home": [0, -58, 50, 50, -5, 46.5], "corridor": {"clear": True}}))
        return SimpleNamespace(returncode=0)

    tok_p = tmp_path / "assessor.token"
    tok_p.write_text("tok", encoding="utf-8")
    rc_ok, res_ok = csh.run_safe_home(
        args, live_fn=lambda _c: False, read_fn=lambda _d: [{"id": 11, "hardware_error": 0}],
        status_fn=lambda _a: {"incident_ids": ["inc-1", "inc-2"]}, run_fn=fake_run,
        wait_sess_fn=lambda *_a: ({"torque_after": {str(i): 0 for i in range(11, 17)}, "hardware_faults": {}, "caps_restored": True}, None),
        token_fn=lambda: tok_p,
        clear_fn=lambda *a, **kw: cleared.append((kw["only"], kw["recovery"])),
    )
    assert rc_ok == 0 and res_ok["cleared_ids"] == ["inc-1", "inc-2"]
    assert [c[0] for c in cleared] == ["inc-1", "inc-2"] and cleared[0][1]["caps_restored_after"] is True


def test_job_client_wait_timeout_and_cli_get_wait_run(monkeypatch, capsys):
    import inspect
    import cell_job_client as jc

    assert inspect.signature(jc.CellJobClient.wait).parameters["timeout_s"].default == 600.0
    calls = []

    def fake_start(self, job, params, *, idempotency_key=None):
        calls.append(("start", job, params, idempotency_key))
        return {"id": "job-42", "running": True}

    def fake_get(self, job_id):
        calls.append(("get", job_id))
        return {"id": job_id, "running": False, "exit": 0}

    def fake_wait(self, job_id, *, poll_s=1.0, timeout_s=600.0):
        calls.append(("wait", job_id, timeout_s))
        return {"id": job_id, "running": False, "exit": 0 if job_id == "job-42" else 2}

    monkeypatch.setattr(jc.CellJobClient, "start", fake_start)
    monkeypatch.setattr(jc.CellJobClient, "get", fake_get)
    monkeypatch.setattr(jc.CellJobClient, "wait", fake_wait)

    assert jc.main(["--url", "http://127.0.0.1:8781", "get", "job-42"]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == "job-42"
    assert jc.main(["--url", "http://127.0.0.1:8781", "wait", "job-42", "--timeout", "30"]) == 0
    assert json.loads(capsys.readouterr().out)["exit"] == 0
    assert jc.main(["--url", "http://127.0.0.1:8781", "wait", "job-99", "--timeout", "15"]) == 1
    capsys.readouterr()
    assert jc.main(["--url", "http://127.0.0.1:8781", "run", "pivot_near", "--params-json", '{"site":"floor"}', "--timeout", "45", "--idempotency-key", "k1", "--wait"]) == 0
    capsys.readouterr()
    assert calls == [
        ("get", "job-42"),
        ("wait", "job-42", 30.0),
        ("wait", "job-99", 15.0),
        ("start", "pivot_near", {"site": "floor"}, "k1"),
        ("wait", "job-42", 45.0),
    ]


def test_calibrate_check_targets_validation_and_non_moving_argv(tmp_path, monkeypatch):
    wd = _make_workdir(tmp_path)
    no_targets = api.build_argv(api.JOBS["calibrate_check"], {"config": "cell-s.json"}, wd)
    assert "--targets" not in no_targets
    assert no_targets[:2] == ["bash", "-c"] and no_targets[3:] == ["cell_calibrate.py", "--config", "cell-s.json", "check"]
    with_targets = api.build_argv(
        api.JOBS["calibrate_check"],
        {"config": "cell-s.json", "targets": ["floor:-0.06,0.15", "belt:0.115,-0.05"]},
        wd,
    )
    idx = with_targets.index("--targets")
    assert with_targets[:idx] == no_targets  # the old argv, unchanged, then only the new option
    assert with_targets[idx + 1 :] == ["floor:-0.06,0.15", "belt:0.115,-0.05"]
    assert api.moves_arm(api.JOBS["calibrate_check"], {"config": "cell-s.json", "targets": ["floor:0,0"]}) is False
    for bad in (
        [],
        [f"s{i}:0,0" for i in range(13)],
        "floor:0,0",
        ["--only:0,0"],
        ["-x:0,0"],
        ["BAD SITE:0,0"],
        ["floor:0.9,0.0"],
        ["floor:nan,0.0"],
        ["floor:inf,0.0"],
        ["floor:0.1"],
    ):
        with pytest.raises(ValueError):
            api.build_argv(api.JOBS["calibrate_check"], {"config": "cell-s.json", "targets": bad}, wd)

    # a bad list is refused before any process starts; a good one starts
    popen = Mock()
    popen.return_value.poll.return_value = None
    monkeypatch.setattr(api.subprocess, "Popen", popen)
    runner = api.Runner(wd, lock_dir=wd)
    refused = runner.start("calibrate_check", {"config": "cell-s.json", "targets": ["floor:nan,0.0"]})
    assert refused["code"] == 400 and "targets" in refused["error"]
    popen.assert_not_called()
    started = runner.start("calibrate_check", {"config": "cell-s.json", "targets": ["floor:-0.06,0.15"]})
    assert started["code"] == 202
    popen.assert_called_once()


def test_runner_records_the_release_for_an_s_policy_dry_run(tmp_path, monkeypatch):
    wd = _make_workdir(tmp_path)
    popen = Mock()
    popen.return_value.poll.return_value = None
    monkeypatch.setattr(api.subprocess, "Popen", popen)
    runner = api.Runner(wd, lock_dir=wd)
    dry = runner.start(
        "cell_policy_drive",
        {
            "arm": "arm_s", "config": "cell-s.json", "library": "chunks-s.json",
            "policy_root": "~/rosy-models/pinky_v1", "policy_revision": "a" * 64,
            "model_calibration": "model.json", "cell_calibration": "cell.json",
            "max_chunks": 3, "operator": "op_b", "proposer": "op_a",
            "dry_run": True, "person_at_switch": True,
        },
    )
    assert dry["code"] == 202
    assert runner.runs[dry["id"]]["omx_tools_tree"] == (Path.home() / ".local/share/rosy/omx-devices/current").resolve().name


def test_runner_keeps_the_workdir_tree_for_a_short_argv(tmp_path, monkeypatch):
    wd = _make_workdir(tmp_path)
    popen = Mock()
    popen.return_value.poll.return_value = None
    monkeypatch.setattr(api.subprocess, "Popen", popen)
    monkeypatch.setattr(api, "build_argv", lambda job, params, workdir: ["true"])
    runner = api.Runner(wd, lock_dir=wd)
    res = runner.start("calibrate_check", {"config": "cell-s.json"})
    assert res["code"] == 202
    assert runner.runs[res["id"]]["omx_tools_tree"] == "omx-tools-abc1234"


def test_runner_answers_400_when_the_release_path_cannot_be_resolved(tmp_path, monkeypatch):
    wd = _make_workdir(tmp_path)
    popen = Mock()
    monkeypatch.setattr(api.subprocess, "Popen", popen)

    def cannot_resolve(job, params, workdir):  # Path.resolve() raises RuntimeError on Python 3.12 for a symlink loop
        raise RuntimeError("symlink loop")

    monkeypatch.setattr(api, "build_argv", cannot_resolve)
    res = api.Runner(wd, lock_dir=wd).start("cell_policy_drive", {"dry_run": True})
    assert res["code"] == 400 and "symlink loop" in res["error"]
    popen.assert_not_called()


def test_remap_obstacle_mm_validation_and_argv(tmp_path):
    wd = _make_workdir(tmp_path)
    argv = api.build_argv(
        api.JOBS["remap"],
        {"arm": "arm_a", "config": "cell-a.json", "obstacle_mm": 80, "person_at_switch": True},
        wd,
    )
    idx = argv.index("--obstacle-mm")
    assert argv[idx + 1] == "80"
    for bad in (0, -5, 250, True, "80"):
        with pytest.raises(ValueError):
            api.build_argv(
                api.JOBS["remap"],
                {"arm": "arm_a", "config": "cell-a.json", "obstacle_mm": bad, "person_at_switch": True},
                wd,
            )
