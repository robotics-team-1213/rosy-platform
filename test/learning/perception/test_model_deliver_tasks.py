"""D-423 §3.2: per-task delivery, promote (shadow -> active) and active rollback."""
import json
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


# --- review 2026-10-03: H2 flat lane root has no active slot, M3 unsigned push, L3 promote no-op ---

@pytest.mark.parametrize("argv", [["promote", "robot"], ["promote", "robot", "--task", "lane_seg"],
                                  ["rollback", "robot", "--slot", "active"]])
def test_flat_lane_task_has_no_active_slot(argv, capsys):
    runner = FakeRunner()
    assert deliver.main([*argv, *SSH], runner=runner) == 2 and runner.calls == []
    assert "lane_seg" in capsys.readouterr().err


def _object_model(models, signed=False):
    import hashlib
    import json
    sys_path_model = models / "object-det-20261003-00000001"
    sys_path_model.mkdir(parents=True)
    (sys_path_model / "model.onnx").write_bytes(b"onnx")
    from control.sensing.perception.learned.manifest import OBJECT_CLASSES
    doc = {"schema": "rosy.perception.model/1", "model_revision": sys_path_model.name, "task": "object_det",
           "files": [{"name": "model.onnx", "sha256": hashlib.sha256(b"onnx").hexdigest(), "precision": "fp32"}],
           "input": {"shape": [1, 3, 256, 320], "color": "rgb", "scale": 1 / 255, "mean": [0, 0, 0],
                     "std": [1, 1, 1], "layout": "nchw"},
           "output": {"layout": "yolo_cxcywh_scores", "classes": [
               {"index": i, "name": n, "role": "object"} for i, n in enumerate(OBJECT_CLASSES)]},
           "dataset": {"repo": "r", "revision": "a" * 40}, "camera_profile_revision": "c"}
    (sys_path_model / "model_manifest.json").write_text(json.dumps(doc), encoding="utf-8")
    (sys_path_model / "intake_report.json").write_text(json.dumps({
        "model_revision": sys_path_model.name, "verdict": "pass",
        "files": [{"name": "model.onnx", "sha256": hashlib.sha256(b"onnx").hexdigest()}]}), encoding="utf-8")
    if signed:
        (sys_path_model / "model_manifest.json.sig").write_text("c2ln", encoding="ascii")
    return sys_path_model.name


def test_unsigned_object_det_push_is_refused_unless_allowed(tmp_path, capsys):
    rev = _object_model(tmp_path)
    base = ["push", "robot", rev, "--task", "object_det", "--models", str(tmp_path), *SSH]
    runner = FakeRunner()
    assert deliver.main(base, runner=runner) == 2 and runner.calls == []
    assert "unsigned" in capsys.readouterr().err
    runner = FakeRunner()
    assert deliver.main([*base, "--allow-unsigned"], runner=runner) == 0


def test_signed_object_det_push_goes_through_and_check_verifies_locally(tmp_path, monkeypatch):
    rev = _object_model(tmp_path, signed=True)
    base = ["push", "robot", rev, "--task", "object_det", "--models", str(tmp_path), *SSH]
    assert deliver.main(base, runner=FakeRunner()) == 0
    seen = []
    monkeypatch.setattr(deliver, "verify_manifest_signature", lambda folder, keys: seen.append(keys) or "k")
    assert deliver.main([*base, "--check", str(tmp_path / "keys")], runner=FakeRunner()) == 0
    assert seen == [str(tmp_path / "keys")]

    def bad(folder, keys):
        raise deliver.SignatureError("no trusted key verifies")
    monkeypatch.setattr(deliver, "verify_manifest_signature", bad)
    assert deliver.main([*base, "--check", str(tmp_path / "keys")], runner=FakeRunner()) == 2


def test_promote_when_shadow_is_already_active_changes_nothing(bash_root):
    root, run = bash_root
    (root / "shadow").write_text("/m/object_det/r1")
    (root / "active").write_text("/m/object_det/r1")
    r = run("promote")
    assert r.returncode == 0, r.stderr
    assert "already active" in r.stdout
    assert not (root / "previous").exists() and not (root / "hold").exists()


def test_status_shows_the_d558_model_version_beside_the_pointer(bash_root):
    root, run = bash_root
    to_posix = _bash_env()[1]
    for name, doc in (("v13-drivable-20261010-aaaaaaaa", {"model_version": "v13.1.00"}),
                      ("lane-seg-20261001-bbbbbbbb", {})):
        (root / name).mkdir()
        (root / name / "model_manifest.json").write_text(
            json.dumps({"model_revision": name, **doc}, indent=2), encoding="utf-8")
    (root / "shadow").write_text(to_posix(root / "v13-drivable-20261010-aaaaaaaa"))
    (root / "active").write_text(to_posix(root / "lane-seg-20261001-bbbbbbbb"))
    out = run("status").stdout.splitlines()
    assert out[0] == f"shadow: {to_posix(root / 'v13-drivable-20261010-aaaaaaaa')} (v13.1.00)"
    assert out[2] == f"active: {to_posix(root / 'lane-seg-20261001-bbbbbbbb')}"
