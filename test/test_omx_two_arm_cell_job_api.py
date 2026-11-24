"""Regression tests for D-1073 two-arm remote policy integration in `cell_job_api`."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
from unittest.mock import Mock

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
OMX = ROOT / "deploy" / "robot" / "omx"
if str(OMX) not in sys.path:
    sys.path.insert(0, str(OMX))

import cell_job_api as api  # noqa: E402
import cell_job_client as client_mod  # noqa: E402


def _make_workdir(tmp_path: Path) -> Path:
    for name in (
        "cell-a.json",
        "cell-b.json",
        "cell-s.json",
        "chunks-a.json",
        "chunks-b.json",
        "catalog-live.json",
    ):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    (tmp_path / "tools-env-current.sh").write_text(
        "export OMX=~/rosy-test/omx-tools-abc1234/deploy/robot/omx\n",
        encoding="utf-8",
    )
    return tmp_path


def _base_two_arm_params(**overrides) -> dict:
    params = {
        "config_a": "cell-a.json",
        "config_b": "cell-b.json",
        "endpoint_url": "http://127.0.0.1:8790",
        "revision_a": "a" * 64,
        "revision_b": "b" * 64,
        "library_a": "chunks-a.json",
        "library_b": "chunks-b.json",
        "task_a": "belt->temp_a:r1-s1-t1",
        "task_b": "belt->temp_b:r1-s1-t1",
        "proposer": "planner_bot",
        "operator": "human_op",
    }
    params.update(overrides)
    return params


def test_platform_parts_registers_all_d1073_safety_review_paths():
    manifest = yaml.safe_load((ROOT / "tools/harness/platform_parts.yaml").read_text(encoding="utf-8"))
    review = set(manifest["safety_review_paths"])
    expected = {
        "deploy/robot/omx/cell_remote_policy.py",
        "deploy/robot/omx/cell_two_arm_guard.py",
        "deploy/robot/omx/cell_two_arm_policy.py",
        "deploy/robot/omx/cell_two_arm_policy_cli.py",
    }
    assert expected <= review


def test_cell_two_arm_policy_argv_and_fail_closed_validation(tmp_path):
    wd = _make_workdir(tmp_path)
    job = api.JOBS["cell_two_arm_policy"]

    dry_params = _base_two_arm_params(dry_run=True, model_site_a="pallet", model_site_b="pallet")
    assert api.moves_arm(job, dry_params) is False
    dry_argv = api.build_argv(job, dry_params, wd)
    assert dry_argv[0] == "bash" and "cell_two_arm_policy_cli.py" in dry_argv
    assert "--dry-run" in dry_argv
    assert "--commissioning" not in dry_argv and "--person-at-switch" not in dry_argv
    assert dry_argv[dry_argv.index("--model-site-a") + 1] == "pallet"
    assert dry_argv[dry_argv.index("--model-site-b") + 1] == "pallet"

    live_params = _base_two_arm_params(
        endpoint_url="http://ai.local:8790",
        token_file="~/.config/rosy/omx-remote-policy.token",
        person_at_switch=True,
        max_chunks=4,
        model_site_a="pallet",
        model_site_b="pallet",
    )
    assert api.moves_arm(job, live_params) is True
    live_argv = api.build_argv(job, live_params, wd)
    assert live_argv[:3] == ["./with-session-arm-a-par.sh", "./with-session-arm-b-par.sh", "bash"]
    assert "cell_two_arm_policy_cli.py" in live_argv
    assert "--dry-run" not in live_argv
    assert live_argv[-2:] == ["--commissioning", "--person-at-switch"]

    with pytest.raises(ValueError, match="person_at_switch"):
        api.build_argv(job, _base_two_arm_params(), wd)

    with pytest.raises(ValueError, match="D-1024"):
        api.build_argv(job, _base_two_arm_params(proposer="Alice", operator="alice", dry_run=True), wd)

    with pytest.raises(ValueError, match="token_file"):
        api.build_argv(job, _base_two_arm_params(endpoint_url="http://ai.local:8790", dry_run=True), wd)

    for bad_url in ("ftp://127.0.0.1:8790", "http://user@127.0.0.1:8790", "http://127.0.0.1:8790?x=1"):
        with pytest.raises(ValueError, match="http\\(s\\) URL"):
            api.build_argv(job, _base_two_arm_params(endpoint_url=bad_url, dry_run=True), wd)

    for bad_tasks in (
        {"task_a": "belt->yard:r1-s1-t1", "task_b": "not_places:belt->yard:r1-s1-t1"},
        {"task_a": "temp_a:r1-s1-t1->yard:r1-s1-t1", "task_b": "temp_a:r1-s1-t1->yard:r1-s2-t1"},
        {"task_a": "belt->yard:r1-s1-t1", "task_b": "yard:r1-s1-t1->temp_b:r1-s1-t1"},
    ):
        with pytest.raises(ValueError, match="overlap"):
            api.build_argv(job, _base_two_arm_params(**bad_tasks, dry_run=True), wd)

    for amr_tasks in (
        {"task_a": "pinky->temp_a:r1-s1-t1"},
        {"task_b": "temp_b:r1-s1-t1->bed-1"},
        {"task_a": "vehicle_tray->temp_a:r1-s1-t1"},
    ):
        with pytest.raises(ValueError, match="R cell-task -> cell_task_worker -> Gate"):
            api.build_argv(job, _base_two_arm_params(**amr_tasks, person_at_switch=True), wd)
        assert api.build_argv(job, _base_two_arm_params(**amr_tasks, dry_run=True), wd)[0] == "bash"


def test_cell_two_arm_policy_machine_token_ban_and_dry_run_over_http(tmp_path, monkeypatch):
    wd = _make_workdir(tmp_path)
    monkeypatch.setattr(api, "_check_arm_incident", lambda _arm: None)
    monkeypatch.setattr(api, "_check_depth_lock_held", lambda _ld=None: False)
    procs = []
    monkeypatch.setattr(
        api.subprocess,
        "Popen",
        lambda argv, **kw: procs.append(Mock(argv=argv, poll=Mock(return_value=0))) or procs[-1],
    )
    runner = api.Runner(wd, lock_dir=wd, lease_dir=tmp_path / "leases")
    srv = api.make_server("127.0.0.1", 0, "h" * 32, runner, machine_token="m" * 32)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        mclient = client_mod.CellJobClient(f"http://127.0.0.1:{srv.server_port}", "m" * 32)
        with pytest.raises(client_mod.CellJobError) as exc_live:
            mclient.start("cell_two_arm_policy", _base_two_arm_params(person_at_switch=True))
        assert exc_live.value.status_code == 403

        with pytest.raises(client_mod.CellJobError) as exc_spoof:
            mclient.start("cell_two_arm_policy", _base_two_arm_params(dry_run=True, proposer="other_bot"))
        assert exc_spoof.value.status_code == 403

        res = mclient.start(
            "cell_two_arm_policy",
            _base_two_arm_params(dry_run=True, proposer="cell-job-machine", operator="human_op"),
        )
        assert "id" in res
        assert len(procs) == 1
    finally:
        srv.shutdown()
        srv.server_close()


def test_cell_two_arm_policy_dual_locks_readiness_gates_and_dirty_markers(tmp_path, monkeypatch):
    wd = _make_workdir(tmp_path)
    lease_dir = tmp_path / "leases"
    lease_dir.mkdir()
    (wd / "chunk-io-a").mkdir()
    (wd / "chunk-io-b").mkdir()
    monkeypatch.setattr(api, "_check_depth_lock_held", lambda _ld=None: False)
    monkeypatch.setattr(api, "_whole_cell_lock_held", lambda _ld=None: False)
    monkeypatch.setattr(api, "_session_lock_held", lambda _arm, _ld=None: False)
    held_arms: set[str] = set()
    monkeypatch.setattr(api, "_check_arm_incident", lambda arm: "held" if arm in held_arms else None)

    procs = []

    def fake_popen(argv, **kw):
        p = Mock()
        p.argv = argv
        p._code = None
        p.poll.side_effect = lambda: p._code
        procs.append(p)
        return p

    monkeypatch.setattr(api.subprocess, "Popen", fake_popen)
    runner = api.Runner(wd, lock_dir=wd, lease_dir=lease_dir)

    # 1. Incident on arm_b blocks two-arm start
    held_arms.add("arm_b")
    res_inc = runner.start("cell_two_arm_policy", _base_two_arm_params(person_at_switch=True))
    assert res_inc["code"] == 409 and res_inc["error_code"] == "ARM_INCIDENT_HELD"
    held_arms.clear()

    # 2. Latched human hold on arm_a blocks two-arm start with TWO_ARM_NOT_READY
    (wd / "chunk-io-a" / "live.json").write_text(
        json.dumps({"chunk": None, "human_hold_latched": True, "fault": False}),
        encoding="utf-8",
    )
    res_unready = runner.start("cell_two_arm_policy", _base_two_arm_params(person_at_switch=True))
    assert res_unready["code"] == 409 and res_unready["error_code"] == "TWO_ARM_NOT_READY"
    (wd / "chunk-io-a" / "live.json").unlink()

    # 3. Single-arm moving job on arm_b blocks two-arm start
    res_b = runner.start("remap", {"arm": "arm_b", "config": "cell-b.json", "person_at_switch": True})
    assert res_b["code"] == 202
    res_blocked = runner.start("cell_two_arm_policy", _base_two_arm_params(person_at_switch=True))
    assert res_blocked["code"] == 409 and "already runs on arm_b" in res_blocked["error"]
    procs[0]._code = 0
    runner.get(res_b["id"])

    # 4. Clean start succeeds, locks both arm_a & arm_b, and writes dirty markers for both arms
    started = runner.start("cell_two_arm_policy", _base_two_arm_params(person_at_switch=True))
    assert started["code"] == 202
    for arm_name in ("arm_a", "arm_b"):
        conflict = runner.start("remap", {"arm": arm_name, "config": f"cell-{arm_name[-1]}.json", "person_at_switch": True})
        assert conflict["code"] == 409 and f"already runs on {arm_name}" in conflict["error"]
        dirty = json.loads((wd / f"cell-state-dirty-{arm_name}.json").read_text(encoding="utf-8"))
        assert dirty["job_id"] == started["id"] and dirty["ended_at"] is None

    procs[1]._code = 0
    done = runner.get(started["id"])
    assert done["running"] is False and done["exit"] == 0
    for arm_name in ("arm_a", "arm_b"):
        dirty = json.loads((wd / f"cell-state-dirty-{arm_name}.json").read_text(encoding="utf-8"))
        assert dirty["job_id"] == started["id"] and dirty["exit_code"] == 0 and dirty["ended_at"] is not None


def test_cell_two_arm_policy_jpeg_quality_forwarding_and_validation(tmp_path):
    wd = _make_workdir(tmp_path)
    job = api.JOBS["cell_two_arm_policy"]

    argv = api.build_argv(job, _base_two_arm_params(dry_run=True, jpeg_quality=90), wd)
    idx = argv.index("--jpeg-quality")
    assert argv[idx + 1] == "90"

    for bad_q in (49, 101, True, False, 85.5, "90"):
        with pytest.raises(ValueError, match="jpeg_quality"):
            api.build_argv(job, _base_two_arm_params(dry_run=True, jpeg_quality=bad_q), wd)
