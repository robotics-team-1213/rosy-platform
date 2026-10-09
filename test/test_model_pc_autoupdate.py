"""D-446 executable candidate, refusal, rollback and work-lock scenarios."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import io
import re
import shutil

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy/site/rosy_model_code.py"


def module():
    assert SCRIPT.is_file(), "D-446 updater is not implemented"
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("model_code", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def keys(tmp_path):
    sys.path.insert(0, str(SCRIPT.parent))
    from candidate_signing import _openssl
    private, public = tmp_path / "key", tmp_path / "key.pub"
    subprocess.run([_openssl(), "genpkey", "-algorithm", "ED25519", "-out", str(private)], check=True)
    subprocess.run([_openssl(), "pkey", "-in", str(private), "-pubout", "-out", str(public)], check=True)
    return private, public


def candidate(m, root, keys, seq=1, env="e" * 64, *, bad_source=False, extra_files=None):
    dest = root / "inbox" / str(seq)
    dest.mkdir(parents=True)
    with tarfile.open(dest / "code.tar", "w") as tar:
        for name in ("learning/training/perception/model/watch.py", "learning/training/perception/rosy_ml.py",
                     "middleware/perception/control/__init__.py", "contracts/foundation/core_common/__init__.py"):
            data = b"broken python !" if bad_source else b"print('ok')\n"
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for name, data in (extra_files or {}).items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    obj = {"schema": "rosy-model-code/1", "source_commit": f"{seq:040x}",
           "sequence": seq, "environment_sha256": env, "archive_sha256": m.digest(dest / "code.tar")}
    raw = json.dumps(obj).encode()
    (dest / "release.json").write_bytes(raw)
    (dest / "release.json.sig").write_bytes(m.sign_manifest_bytes(raw, key_id="test", private_key=keys[0], public_key=keys[1]))
    (dest / "READY").write_text(m.digest(dest / "release.json"))
    return dest


def updater(m, root, keys, **kwargs):
    return m.Updater(root, "test", keys[1], sys.executable,
                     environment=lambda: "e" * 64, busy=lambda: None,
                     health=lambda p: None, **kwargs)


def test_module_is_available():
    assert hasattr(module(), "Updater")


def test_camera_map_dependencies_are_signed_and_imported_from_the_release(tmp_path, keys):
    m = module()
    repo = SCRIPT.parents[2]
    files = {"operations/vision/rosy_vision/" + name:
             (repo / "operations/vision/rosy_vision" / name).read_bytes()
             for name in ("__init__.py", "lane_map.py", "map_register.py")}
    files[m.PREFIX + "probe.py"] = b"import pathlib,rosy_vision; print(pathlib.Path(rosy_vision.__file__).resolve())\n"
    folder = candidate(m, tmp_path, keys, extra_files=files)
    assert updater(m, tmp_path, keys).read_candidate(folder)["source_commit"] == f"{1:040x}"
    release = tmp_path / "release"
    m.unpack(folder / "code.tar", release)
    for name, data in files.items():
        assert (release / name).read_bytes() == data
    result = subprocess.run(m.bootstrap_command(sys.executable, release, release / m.PREFIX / "probe.py", []),
                            capture_output=True, text=True, check=True)
    assert Path(result.stdout.strip()) == (release / "operations/vision/rosy_vision/__init__.py").resolve()


def test_camera_map_job_refuses_a_missing_dependency(tmp_path, keys):
    m = module()
    folder = candidate(m, tmp_path, keys, extra_files={m.CAMERA_MAP_ENTRY: b"pass\n"})
    with pytest.raises(ValueError, match="missing camera-map dependency"):
        m.unpack(folder / "code.tar", tmp_path / "release")


def test_job_entry_maps_only_the_exact_camera_map_name(tmp_path):
    m = module()
    source = tmp_path / "release"
    for name in (m.CAMERA_MAP_ENTRY, m.PREFIX + "rosy_ml.py", "outside.py"):
        (source / name).parent.mkdir(parents=True, exist_ok=True)
        (source / name).write_text("pass\n")
    file, base, name, mapped = m.job_entry(source, "camera_lane_map.py")
    assert file == (source / m.CAMERA_MAP_ENTRY).resolve() and mapped == m.CAMERA_MAP_ENTRY
    assert (base, name) == (source.resolve(), m.CAMERA_MAP_ENTRY)
    file, base, name, mapped = m.job_entry(source, "rosy_ml.py")
    assert file == (source / m.PREFIX / "rosy_ml.py").resolve() and mapped is None
    assert m.JOB_ENTRY_POINTS == {"camera_lane_map.py": m.CAMERA_MAP_ENTRY}
    # Other names resolve only under PREFIX: no other source path, no escape.
    for bad in ("../../../outside.py", str((source / "outside.py").resolve()), m.CAMERA_MAP_ENTRY,
                "./camera_lane_map.py", "lane_map.py"):
        with pytest.raises((ValueError, OSError)):
            m.job_entry(source, bad)


@pytest.mark.skipif(os.name == "nt", reason="Linux symlink/flock updater")
@pytest.mark.parametrize("kind", ["signature", "archive", "ready", "environment", "schema"])
def test_untrusted_or_incompatible_candidate_never_changes_source(tmp_path, keys, kind):
    m = module()
    c = candidate(m, tmp_path, keys, env="f" * 64 if kind == "environment" else "e" * 64)
    if kind == "signature":
        (c / "release.json.sig").write_text("{}")
    if kind == "archive":
        with (c / "code.tar").open("ab") as f: f.write(b"tampered")
    if kind == "ready": (c / "READY").write_text("not-ready")
    if kind == "schema":
        obj = json.loads((c / "release.json").read_text())
        obj["schema"] = "rosy-site/1"
        raw = json.dumps(obj).encode()
        (c / "release.json").write_bytes(raw)
        (c / "release.json.sig").write_bytes(m.sign_manifest_bytes(raw, key_id="test", private_key=keys[0], public_key=keys[1]))
        (c / "READY").write_text(m.digest(c / "release.json"))
    u = updater(m, tmp_path, keys)
    result = u.run()
    assert result["result"] in {"rejected", "idle", "held"}
    assert not (tmp_path / "current").exists()


@pytest.mark.skipif(os.name == "nt", reason="Linux symlink/flock updater")
def test_atomic_update_preserves_legacy_data_and_does_not_downgrade(tmp_path, keys):
    m = module()
    sentinel = tmp_path / "datasets/checkpoint"
    sentinel.parent.mkdir()
    sentinel.write_bytes(b"precious")
    candidate(m, tmp_path, keys, seq=2)
    u = updater(m, tmp_path, keys)
    assert u.run()["result"] == "applied"
    assert (tmp_path / "current/learning/training/perception/rosy_ml.py").read_text() == "print('ok')\n"
    assert sentinel.read_bytes() == b"precious"
    candidate(m, tmp_path, keys, seq=1)
    assert u.run()["result"] == "idle"
    assert u.state()["sequence"] == 2


@pytest.mark.skipif(os.name == "nt", reason="Linux symlink/flock updater")
def test_busy_and_hold_defer_without_consuming_candidate(tmp_path, keys):
    m = module()
    candidate(m, tmp_path, keys)
    u = updater(m, tmp_path, keys)
    u.busy = lambda: "training"
    assert u.run()["result"] == "held"
    assert not (tmp_path / "current").exists()
    u.busy = lambda: None
    (tmp_path / "HOLD").touch()
    assert u.run()["result"] == "held"
    (tmp_path / "HOLD").unlink()
    assert u.run()["result"] == "applied"


@pytest.mark.skipif(os.name == "nt", reason="Linux symlink/flock updater")
def test_job_shared_lock_blocks_switch(tmp_path, keys):
    m = module()
    candidate(m, tmp_path, keys)
    u = updater(m, tmp_path, keys)
    with m.work_lock(tmp_path, exclusive=False):
        assert u.run()["result"] == "held"
    assert u.run()["result"] == "applied"


@pytest.mark.skipif(os.name == "nt", reason="Linux symlink/flock updater")
def test_post_switch_failure_restores_previous_and_is_not_retried(tmp_path, keys):
    m = module()
    candidate(m, tmp_path, keys)
    u = updater(m, tmp_path, keys)
    assert u.run()["result"] == "applied"
    before = (tmp_path / "current").resolve()
    candidate(m, tmp_path, keys, seq=2)
    calls = []
    def health(p):
        calls.append(p)
        if len(calls) == 2: raise RuntimeError("post-switch failure")
    u.health = health
    assert u.run()["result"] == "rolled-back"
    assert (tmp_path / "current").resolve() == before
    assert 2 in u.state()["failed"]
    assert u.run()["result"] == "idle"


@pytest.mark.skipif(os.name == "nt", reason="Linux symlink/flock updater")
def test_restart_recovers_pending_before_observing_new_candidates(tmp_path, keys):
    m = module()
    candidate(m, tmp_path, keys)
    u = updater(m, tmp_path, keys)
    u.run()
    before = (tmp_path / "current").resolve()
    candidate(m, tmp_path, keys, seq=2)
    def crash(p):
        if (tmp_path / "current").resolve() != before: raise KeyboardInterrupt()
    u.health = crash
    with pytest.raises(KeyboardInterrupt): u.run()
    assert u.state()["pending"]["sequence"] == 2
    assert u.run()["result"] == "recovered"
    assert (tmp_path / "current").resolve() == before


@pytest.mark.parametrize("name,link", [("../escape", False), ("learning/training/perception/x", True),
                                      ("private/key", False), ("learning/training/perception/data/key", False),
                                      ("middleware/apps/device/pinky/profile/config/camera_nominal.yaml.extra", False),
                                      ("operations/vision/rosy_vision/cli.py", False),
                                      ("operations/vision/rosy_vision/lane_map.py.extra", False)])
def test_archive_rejects_traversal_links_and_non_code_payload(tmp_path, name, link):
    m = module()
    p = tmp_path / "bad.tar"
    with tarfile.open(p, "w") as tar:
        for valid in ["learning/training/perception/model/watch.py", "learning/training/perception/rosy_ml.py",
                      "middleware/perception/control/__init__.py", "contracts/foundation/core_common/__init__.py"]:
            data = b"print('ok')\n"
            baseline = tarfile.TarInfo(valid)
            baseline.size = len(data)
            tar.addfile(baseline, io.BytesIO(data))
        info = tarfile.TarInfo(name)
        if link:
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
        tar.addfile(info)
    with pytest.raises(ValueError): m.unpack(p, tmp_path / "out")


def test_unknown_busy_probe_fails_closed():
    m = module()
    def fail(*a, **kw): raise OSError("GPU unavailable")
    assert m.gpu_busy(runner=fail)


def test_fingerprint_is_stable_and_detects_dependency_change():
    m = module()
    assert m.fingerprint({"python": "3.12", "packages": [["torch", "2"]]}) == m.fingerprint({"packages": [["torch", "2"]], "python": "3.12"})
    assert m.fingerprint({"python": "3.12"}) != m.fingerprint({"python": "3.11"})


@pytest.mark.skipif(os.name == "nt", reason="Linux job runner")
def test_job_refuses_a_changed_environment(tmp_path, keys, monkeypatch):
    m = module()
    candidate(m, tmp_path, keys)
    updater(m, tmp_path, keys).run()
    config = {"root": str(tmp_path), "key_id": "test", "public_key": str(keys[1]),
              "python": sys.executable, "work_dir": str(tmp_path), "legacy_roots": []}
    monkeypatch.setattr(m, "gpu_busy", lambda: None)
    monkeypatch.setattr(m, "legacy_busy", lambda roots: None)
    with pytest.raises(ValueError, match="environment"):
        m.execute(config, "rosy_ml.py", [])


@pytest.mark.parametrize("camera_map", [False, True])
def test_build_only_uses_committed_source(tmp_path, keys, camera_map):
    m = module()
    repo = tmp_path / "repo"
    repo.mkdir()
    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()
    git("init")
    code = repo / "learning/training/perception"
    (code / "model").mkdir(parents=True)
    (code / "model/watch.py").write_text("print('committed')\n")
    (code / "rosy_ml.py").write_text("print('committed')\n")
    profile = "middleware/apps/device/pinky/profile/config/camera_nominal.yaml"
    dependencies = ["middleware/perception/control/__init__.py", "contracts/foundation/core_common/__init__.py",
                    "shared/web/shared-assets.json", profile]
    if camera_map:
        dependencies += [*m.CAMERA_MAP_FILES]
    for name in dependencies:
        dep = repo / name
        dep.parent.mkdir(parents=True, exist_ok=True)
        dep.write_text("PINNED = True\n")
    git("add", "learning/training/perception/model/watch.py", "learning/training/perception/rosy_ml.py",
        *dependencies)
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture")
    sha = git("rev-parse", "HEAD")
    (code / "rosy_ml.py").write_text("print('dirty')\n")
    (code / "secret").write_text("never ship")
    if camera_map:
        (repo / m.CAMERA_MAP_FILES[1]).write_text("DIRTY = True\n")
    out = tmp_path / "candidate"
    m.build(repo, sha, 1, "e" * 64, out, "test", keys[0], keys[1])
    m.unpack(out / "code.tar", tmp_path / "result")
    assert (tmp_path / "result/learning/training/perception/rosy_ml.py").read_text() == "print('committed')\n"
    assert not (tmp_path / "result/learning/training/perception/secret").exists()
    assert (tmp_path / "result/middleware/perception/control/__init__.py").read_text() == "PINNED = True\n"
    assert (tmp_path / "result/contracts/foundation/core_common/__init__.py").read_text() == "PINNED = True\n"
    assert (tmp_path / "result/shared/web/shared-assets.json").read_text() == "PINNED = True\n"
    assert (tmp_path / "result" / profile).read_text() == "PINNED = True\n"
    for name in m.CAMERA_MAP_FILES:
        if camera_map:
            assert (tmp_path / "result" / name).read_text() == "PINNED = True\n"
        else:
            assert not (tmp_path / "result" / name).exists()


def test_uncommitted_perception_edits_are_kept(tmp_path):
    m = module()
    repo = tmp_path / "repo"
    repo.mkdir()
    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()
    git("init")
    edited = repo / "learning/training/perception/rosy_ml.py"
    edited.parent.mkdir(parents=True)
    edited.write_text("print('committed')\n", encoding="utf-8")
    git("add", "learning/training/perception/rosy_ml.py")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture")
    edited.write_text("print('local edit')\n", encoding="utf-8")
    assert m.perception_edits([repo]) == "uncommitted perception edits"
    assert edited.read_text(encoding="utf-8") == "print('local edit')\n"
    (repo / "notes.txt").write_text("outside the code payload", encoding="utf-8")
    git("checkout", "--", "learning/training/perception/rosy_ml.py")
    assert m.perception_edits([repo]) is None
    assert m.perception_edits([tmp_path / "not-a-checkout"]) is None


def test_a_local_script_that_differs_from_the_signed_release_is_refused(tmp_path):
    m = module()
    signed = tmp_path / "signed"
    local = tmp_path / "work" / "learning/training/perception"
    signed.mkdir()
    local.mkdir(parents=True)
    (signed / "rosy_ml.py").write_bytes(b"print('signed')\n")
    (local / "rosy_ml.py").write_bytes(b"print('local edit')\n")
    assert "differs" in m.checkout_script_conflict(signed, local, "rosy_ml.py")
    (local / "rosy_ml.py").write_bytes(b"print('signed')\n")
    assert m.checkout_script_conflict(signed, local, "rosy_ml.py") is None
    assert m.checkout_script_conflict(signed, tmp_path / "absent", "rosy_ml.py") is None


@pytest.mark.skipif(os.name == "nt", reason="Linux symlink/flock updater")
@pytest.mark.parametrize("code_path", [
    "learning/training/perception/rosy_ml.py", "tools/perception/rosy_ml.py",
    "middleware/perception/control/model.py", "src/runtime/sensing/control/model.py",
    "contracts/foundation/core_common/model.py", "src/contracts/foundation/core_common/model.py",
])
def test_dirty_checkout_holds_the_switch_and_keeps_the_edit(tmp_path, keys, code_path):
    m = module()
    repo = tmp_path / "checkout"
    repo.mkdir()
    def git(*args):
        return subprocess.check_call(["git", "-C", str(repo), *args])
    git("init")
    edited = repo / code_path
    edited.parent.mkdir(parents=True)
    edited.write_text("print('committed')\n", encoding="utf-8")
    git("add", "--", code_path)
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture")
    edited.write_text("print('local edit')\n", encoding="utf-8")
    root = tmp_path / "state"
    candidate(m, root, keys)
    result = updater(m, root, keys, legacy_roots=(repo,)).run()
    assert result["result"] == "held" and result["reason"] == "uncommitted perception edits"
    assert edited.read_text(encoding="utf-8") == "print('local edit')\n"
    assert not (root / "current").exists()


def test_config_requires_absolute_legacy_roots(tmp_path):
    m = module()
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"root": str(tmp_path), "key_id": "test", "public_key": str(tmp_path / "pub"),
                            "python": sys.executable, "work_dir": str(tmp_path), "legacy_roots": []}))
    with pytest.raises(ValueError): m.load_config(p)


@pytest.mark.skipif(os.name == "nt", reason="Linux proc owner")
def test_unrelated_sandboxed_process_does_not_block_updates(tmp_path, monkeypatch):
    m = module()
    proc = tmp_path / "proc"
    entry = proc / "999999"
    entry.mkdir(parents=True)
    (entry / "comm").write_text("firefox")
    (entry / "cmdline").write_bytes(b"firefox\x00")
    original = Path.resolve
    def resolve(path, *a, **kw):
        if path == entry / "cwd": raise PermissionError("sandbox")
        return original(path, *a, **kw)
    monkeypatch.setattr(Path, "resolve", resolve)
    assert m.legacy_busy([str(tmp_path)], proc=proc) is None


def test_review_ui_does_not_block_code_update_but_training_does(tmp_path, monkeypatch):
    m = module()
    proc = tmp_path / "proc"
    entry = proc / "999999"
    entry.mkdir(parents=True)
    (entry / "comm").write_text("python", encoding="utf-8")
    (entry / "cmdline").write_bytes(b"python\x00/app/learning/training/perception/dataset/review_app.py\x00")
    monkeypatch.setattr(m.os, "getuid", lambda: entry.stat().st_uid, raising=False)
    original = Path.resolve
    monkeypatch.setattr(Path, "resolve", lambda path, *a, **kw:
                        tmp_path if path == entry / "cwd" else original(path, *a, **kw))
    assert m.legacy_busy([str(tmp_path)], proc=proc) is None
    (entry / "cmdline").write_bytes(b"python\x00/app/learning/training/perception/training/train_job.py\x00")
    assert m.legacy_busy([str(tmp_path)], proc=proc) == "legacy work pid 999999"


@pytest.mark.skipif(os.name == "nt", reason="Linux job receipt and flock")
def test_real_job_records_pinned_source_and_redacts_arguments(tmp_path, keys, monkeypatch):
    m = module()
    env = m.Updater(tmp_path, "test", keys[1], sys.executable).probe_environment()
    candidate(m, tmp_path, keys, env=env)
    u = m.Updater(tmp_path, "test", keys[1], sys.executable,
                  environment=lambda: env, busy=lambda: None, health=lambda p: None)
    u.run()
    config = {"root": str(tmp_path), "key_id": "test", "public_key": str(keys[1]),
              "python": sys.executable, "work_dir": str(tmp_path), "legacy_roots": []}
    monkeypatch.setattr(m, "gpu_busy", lambda: None)
    monkeypatch.setattr(m, "legacy_busy", lambda roots: None)
    assert m.execute(config, "rosy_ml.py", ["secret-argument-value"]) == 0
    receipts = list((tmp_path / "jobs").glob("*.json"))
    assert len(receipts) == 1
    text = receipts[0].read_text()
    assert "secret-argument-value" not in text
    obj = json.loads(text)
    assert obj["source_commit"] == f"{1:040x}"
    assert obj["environment_sha256"] == env and obj["exit_code"] == 0


@pytest.mark.skipif(os.name == "nt", reason="Linux unmanaged work admission")
@pytest.mark.parametrize("kind", ["gpu", "legacy"])
def test_job_does_not_start_while_unmanaged_work_is_running(tmp_path, keys, monkeypatch, kind):
    m = module()
    env = m.Updater(tmp_path, "test", keys[1], sys.executable).probe_environment()
    candidate(m, tmp_path, keys, env=env)
    m.Updater(tmp_path, "test", keys[1], sys.executable,
              environment=lambda: env, busy=lambda: None, health=lambda p: None).run()
    config = {"root": str(tmp_path), "key_id": "test", "public_key": str(keys[1]),
              "python": sys.executable, "work_dir": str(tmp_path), "legacy_roots": [str(tmp_path)]}
    monkeypatch.setattr(m, "gpu_busy", lambda: "GPU compute job" if kind == "gpu" else None)
    monkeypatch.setattr(m, "legacy_busy", lambda roots: "legacy work" if kind == "legacy" else None)
    with pytest.raises(ValueError, match="busy"):
        m.execute(config, "rosy_ml.py", [])
    assert not (tmp_path / "jobs").exists()


@pytest.mark.skipif(os.name == "nt", reason="Linux inherited flock")
def test_child_keeps_work_lock_after_parent_context_exits(tmp_path, keys):
    m = module()
    candidate(m, tmp_path, keys)
    u = updater(m, tmp_path, keys)
    with m.work_lock(tmp_path, exclusive=True) as fd:
        child = subprocess.Popen([sys.executable, "-c", "import time; print('ready', flush=True); time.sleep(.5)"],
                                 pass_fds=(fd,), stdout=subprocess.PIPE, text=True)
        assert child.stdout.readline().strip() == "ready"
    try:
        assert u.run()["result"] == "held"
    finally:
        child.wait(timeout=5)
        child.stdout.close()
    assert u.run()["result"] == "applied"


@pytest.mark.skipif(os.name == "nt", reason="Linux systemd and bash")
def test_installer_and_documented_shell_commands_parse():
    site = SCRIPT.parent
    subprocess.run(["bash", "-n", str(site / "install-model-code.sh")], check=True)
    text = (site / "model-code-update.md").read_text()
    for block in re.findall(r"```bash\n(.*?)```", text, re.S):
        subprocess.run(["bash", "-n"], input=block, text=True, check=True)


@pytest.mark.skipif(os.name == "nt" or not shutil.which("systemd-analyze"), reason="Linux systemd unit verifier")
def test_user_service_and_timer_units_validate(tmp_path):
    paths = [SCRIPT.parent / name for name in [
        "rosy-model-code-update.service", "rosy-model-code-update.timer",
        "rosy-model-code-watch.service", "rosy-model-code-watch.timer"]]
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    subprocess.run(["systemd-analyze", "--user", "verify", *map(str, paths)], check=True, timeout=30,
                   env={**os.environ, "XDG_RUNTIME_DIR": str(runtime)})


def test_isolated_bootstrap_uses_pinned_sibling_and_dependency_paths(tmp_path):
    m = module()
    root = tmp_path / "release"
    model = root / "learning/training/perception/model"
    model.mkdir(parents=True)
    (model / "helper.py").write_text("VALUE = 'pinned'\n")
    (model / "tool.py").write_text("import sys,helper,control,core_common; print(helper.VALUE,control.VALUE,core_common.VALUE,sys.flags.isolated)\n")
    for name in ["middleware/perception/control", "contracts/foundation/core_common"]:
        path = root / name
        path.mkdir(parents=True)
        (path / "__init__.py").write_text("VALUE = 'pinned'\n")
    ambient = tmp_path / "ambient"
    ambient.mkdir()
    (ambient / "helper.py").write_text("VALUE = 'ambient'\n")
    result = subprocess.run(m.bootstrap_command(sys.executable, root, model / "tool.py", []),
                            capture_output=True, text=True, check=True,
                            env={**os.environ, "PYTHONPATH": str(ambient)})
    assert result.stdout.strip() == "pinned pinned pinned 1"


@pytest.mark.skipif(os.name == "nt", reason="Linux external data link")
def test_candidate_default_data_path_preserves_external_data(tmp_path, keys):
    m = module()
    root, data = tmp_path / "state", tmp_path / "legacy/data"
    data.mkdir(parents=True)
    (data / "checkpoint").write_text("preserved")
    candidate(m, root, keys)
    u = m.Updater(root, "test", keys[1], sys.executable, data_root=data,
                  environment=lambda: "e" * 64, busy=lambda: None, health=lambda p: None)
    assert u.run()["result"] == "applied"
    assert (root / "current/data").resolve() == data
    (root / "current/data/new-result").write_text("outside payload")
    assert (data / "checkpoint").read_text() == "preserved"
    assert (data / "new-result").is_file()


@pytest.mark.skipif(os.name == "nt", reason="Linux updater state")
def test_idle_clears_the_previous_hold_reason(tmp_path, keys):
    m = module()
    u = updater(m, tmp_path, keys)
    u.busy = lambda: "GPU utilization"
    assert u.run()["reason"] == "GPU utilization"
    u.busy = lambda: None
    result = u.run()
    assert result["result"] == "idle" and result["reason"] is None


def test_bootstrap_can_run_previous_layout_after_rollback(tmp_path):
    m = module()
    root = tmp_path / "previous"
    for folder, package in [("src/runtime/sensing", "control"), ("src/contracts/foundation", "core_common")]:
        path = root / folder / package
        path.mkdir(parents=True)
        (path / "__init__.py").write_text("PINNED = True\n")
    script = root / "job.py"
    script.write_text("import control,core_common; assert control.PINNED and core_common.PINNED\n")
    result = subprocess.run(m.bootstrap_command(sys.executable, root, script, []), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_clean_older_checkout_does_not_block_signed_script(tmp_path):
    m = module()
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    subprocess.run(["git", "init", str(checkout)], check=True, capture_output=True)
    (checkout / "job.py").write_text("OLD = True\n")
    subprocess.run(["git", "-C", str(checkout), "add", "job.py"], check=True)
    subprocess.run(["git", "-C", str(checkout), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                    "commit", "-m", "clean old source"], check=True, capture_output=True)
    signed = tmp_path / "signed"
    signed.mkdir()
    (signed / "job.py").write_text("NEW = True\n")
    assert m.checkout_script_conflict(signed, checkout, "job.py") is None
    (checkout / "job.py").write_text("LOCAL = True\n")
    assert m.checkout_script_conflict(signed, checkout, "job.py") is not None


def test_environment_retains_incomplete_distribution_records(tmp_path, monkeypatch):
    from types import SimpleNamespace

    m = module()
    valid = SimpleNamespace(metadata={"Name": "Known_Package"}, version="1.2")
    assert m.distribution_fingerprint(valid) == ("known-package", "1.2")
    records = [valid]
    for name in ["unnamed.egg-info", "other.dist-info"]:
        entry = tmp_path / name
        entry.mkdir()
        (entry / "RECORD").write_text("installed-file,hash,1\n")
        records.append(SimpleNamespace(metadata={}, version=None, _path=entry))
    monkeypatch.setattr(m.importlib.metadata, "distributions", lambda: iter(records))
    first = m.environment_info()
    assert len(first["packages"]) == 3
    assert sum(name.startswith("<invalid-metadata>:") for name, _ in first["packages"]) == 2
    assert str(tmp_path) not in json.dumps(first)
    records.reverse()
    assert m.environment_info() == first
    (tmp_path / "unnamed.egg-info" / "RECORD").write_text("changed-installed-file,hash,1\n")
    changed = m.environment_info()
    assert m.fingerprint(changed) != m.fingerprint(first)
    records.pop(0)
    assert m.fingerprint(m.environment_info()) != m.fingerprint(changed)


@pytest.mark.parametrize("kind", ["unidentified", "missing", "unreadable"])
def test_incomplete_distribution_without_readable_provenance_fails_closed(tmp_path, monkeypatch, kind):
    from types import SimpleNamespace

    m = module()
    distribution = SimpleNamespace(metadata={}, version=None)
    if kind != "unidentified":
        distribution._path = tmp_path / "broken.dist-info"
    if kind == "unreadable":
        distribution._path.mkdir()
        (distribution._path / "RECORD").write_text("installed-file\n")

        def unreadable(_path):
            raise PermissionError("metadata is unreadable")

        monkeypatch.setattr(m, "digest", unreadable)
    with pytest.raises(ValueError, match="environment package metadata"):
        m.distribution_fingerprint(distribution)




@pytest.mark.parametrize("code_path", [
    "learning/training/perception/rosy_ml.py", "tools/perception/rosy_ml.py",
    "middleware/perception/control/model.py", "src/runtime/sensing/control/model.py",
    "contracts/foundation/core_common/model.py", "src/contracts/foundation/core_common/model.py",
])
@pytest.mark.parametrize("edit_kind", ["modified", "staged", "untracked", "deleted"])
def test_checkout_guard_protects_the_whole_current_and_legacy_code_closure(tmp_path, code_path, edit_kind):
    m = module()
    repo = tmp_path / "repo"
    repo.mkdir()
    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    git("init")
    source = repo / code_path
    source.parent.mkdir(parents=True)
    source.write_bytes(b"committed\n")
    git("add", "--", code_path)
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture")
    assert m.perception_edits([repo]) is None
    if edit_kind == "deleted":
        source.unlink()
    elif edit_kind == "untracked":
        source = source.with_name("local.py")
        source.write_bytes(b"local\n")
    else:
        source.write_bytes(b"local\n")
        if edit_kind == "staged": git("add", "--", code_path)
    before = git("status", "--porcelain").stdout
    assert m.perception_edits([repo]) == "uncommitted perception edits"
    assert git("status", "--porcelain").stdout == before
    if edit_kind != "deleted": assert source.read_bytes() == b"local\n"


@pytest.mark.parametrize("error", [OSError("unavailable"), subprocess.TimeoutExpired("git", 15)])
def test_checkout_observation_errors_hold_instead_of_crashing(tmp_path, monkeypatch, error):
    m = module()
    (tmp_path / ".git").mkdir()
    def fail(*args, **kwargs): raise error
    monkeypatch.setattr(m.subprocess, "run", fail)
    assert m.perception_edits([tmp_path]) == "checkout observation failed"


@pytest.mark.parametrize("guard", ["update", "exec"])
def test_hidden_untracked_files_still_block_signed_code(tmp_path, guard):
    m = module()
    repo = tmp_path / "repo"
    repo.mkdir()
    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    git("init")
    git("config", "status.showUntrackedFiles", "no")
    script = repo / "middleware/perception/control/local.py"
    script.parent.mkdir(parents=True)
    script.write_bytes(b"local edit\n")
    if guard == "update":
        assert m.perception_edits([repo]) == "uncommitted perception edits"
    else:
        signed = tmp_path / "signed"
        signed.mkdir()
        assert "differs" in m.checkout_script_conflict(signed, repo, script.relative_to(repo).as_posix())
    assert script.read_bytes() == b"local edit\n"
