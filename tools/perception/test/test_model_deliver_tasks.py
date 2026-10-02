"""D-423 §3.2: per-task delivery, promote (shadow -> active) and active rollback."""
import subprocess

import pytest

from test_model_deliver import FLOCK_SHIM, SSH, FakeRunner, _bash_env, _model, deliver

OBJ_ROOT = "/var/lib/rosy/models/object_det"


def test_task_root_for_push_and_lane_keeps_the_flat_root(tmp_path):
    rev = _model(tmp_path, "pass")
    runner = FakeRunner()
    assert deliver.main(["push", "robot", rev, "--models", str(tmp_path), *SSH], runner=runner) == 0
    assert "/var/lib/rosy/models/shadow" in runner.calls[-1][-1]
    assert OBJ_ROOT not in runner.calls[-1][-1]


def test_push_refuses_a_model_of_another_task(tmp_path):
    rev = _model(tmp_path, "pass")          # a lane_seg model
    runner = FakeRunner()
    rc = deliver.main(["push", "robot", rev, "--task", "object_det", "--models", str(tmp_path), *SSH],
                      runner=runner)
    assert rc == 2 and runner.calls == []


def test_promote_and_active_rollback_run_on_the_task_root():
    runner = FakeRunner()
    assert deliver.main(["promote", "robot", "--task", "object_det", *SSH], runner=runner) == 0
    script = runner.calls[0][-1]
    assert f"{OBJ_ROOT}/active" in script and f"{OBJ_ROOT}/shadow" in script
    runner = FakeRunner()
    assert deliver.main(["rollback", "robot", "--task", "object_det", "--slot", "active", *SSH],
                        runner=runner) == 0
    assert f"{OBJ_ROOT}/previous" in runner.calls[0][-1]


def test_unknown_task_is_refused():
    with pytest.raises(SystemExit):
        deliver.main(["promote", "robot", "--task", "nope", *SSH], runner=FakeRunner())


def test_status_names_active_and_previous():
    script = deliver.remote_script("status", None, OBJ_ROOT)
    assert "active:" in script and "previous:" in script


@pytest.fixture
def bash_root(tmp_path):
    env = _bash_env()
    if env is None:
        pytest.skip("needs bash with sha256sum and install (and cygpath on Windows)")
    bash, to_posix = env
    root = tmp_path / "object_det"
    root.mkdir()

    def run(action, **kw):
        script = deliver.remote_script(action, None, to_posix(root), privileged=False,
                                       audit={"operator": "op"}, **kw)
        return subprocess.run([bash, "-c", FLOCK_SHIM + script], capture_output=True, text=True)
    return root, run


def test_promote_moves_shadow_to_active_and_keeps_the_old_active(bash_root):
    root, run = bash_root
    (root / "shadow").write_text("/m/object_det/r2")
    (root / "active").write_text("/m/object_det/r1")
    r = run("promote")
    assert r.returncode == 0, r.stderr
    assert (root / "active").read_text() == "/m/object_det/r2"
    assert (root / "previous").read_text() == "/m/object_det/r1"
    assert (root / "shadow").read_text() == "/m/object_det/r2"      # shadow unchanged
    assert '"action":"promote"' in (root / "history.jsonl").read_text()
    assert (root / "hold").exists()                                   # manual: holds the robot


def test_promote_without_a_shadow_changes_nothing(bash_root):
    root, run = bash_root
    (root / "active").write_text("/m/object_det/r1")
    r = run("promote")
    assert r.returncode != 0 and (root / "active").read_text() == "/m/object_det/r1"
    assert not (root / "previous").exists()


def test_active_rollback_restores_previous(bash_root):
    root, run = bash_root
    (root / "active").write_text("/m/object_det/r2")
    (root / "previous").write_text("/m/object_det/r1")
    r = run("rollback-active")
    assert r.returncode == 0, r.stderr
    assert (root / "active").read_text() == "/m/object_det/r1"
    assert not (root / "previous").exists()
    assert '"action":"rollback-active"' in (root / "history.jsonl").read_text()


def test_active_rollback_without_previous_refuses(bash_root):
    root, run = bash_root
    (root / "active").write_text("/m/object_det/r2")
    r = run("rollback-active")
    assert r.returncode != 0 and (root / "active").read_text() == "/m/object_det/r2"
