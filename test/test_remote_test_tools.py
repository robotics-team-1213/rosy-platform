"""Explicit native raw tooling: committed identity and executed shell boundaries.

These tests run on the native test PCs. Fake pip creates tiny import/metadata
fixtures; no package installation, codec execution or network is performed.
"""
from __future__ import annotations

import ast
import hashlib
import importlib
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))
import remote_pytest as rp  # noqa: E402
import remote_job as rj  # noqa: E402

BASE = "6ecf921d91"
RAW = "learning/curation/pinky/requirements-raw.txt"
PROFILE = "pinky-raw"


def tools():
    return importlib.import_module("remote_test_tools")


def base_recipe():
    tree = ast.parse(rp.git(ROOT, "show", f"{BASE}:tools/remote/remote_pytest.py"))
    return next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "VENV" for t in n.targets))


def test_default_recipe_and_hash_remain_identical(monkeypatch):
    old = base_recipe()
    assert rp.VENV == old
    assert tools().render_setup(rp.VENV, None) == old
    assert tools().render_job(rj.JOB, None) == rj.JOB
    before = rp.deps(ROOT, BASE)
    ci = rp.git(ROOT, "show", f"{BASE}:.github/workflows/ci.yml")
    dirs = re.search(r'--wheel-dir "\$wheelhouse" \\\n\s*(.+)', ci).group(1).split()
    paths = (rp.CI, rp.DEVICE_REQ, rp.CRYPTO_REQ, rp.FLEET_REQ, rp.VISION_REQ, *dirs)
    ids = [rp.git(ROOT, "rev-parse", f"{BASE}:{p}") for p in paths]
    install = old.split("UV=", 1)[1].split('echo "$DEPS"', 1)[0]
    expected = hashlib.sha256("\n".join([install, *ids]).encode()).hexdigest()[:16]
    assert before == (expected, dirs)
    monkeypatch.setattr(rp, "VENV", old)
    assert rp.deps(ROOT, BASE, test_tools=None) == before
    # Preserve the existing VENV install-recipe monkeypatch contract.
    monkeypatch.setattr(rp, "VENV", old.replace("$P check", "$P check # changed"))
    assert rp.deps(ROOT, BASE)[0] != before[0]


@pytest.mark.parametrize("entry", ["api", "cli"])
def test_unknown_profile_refuses_before_any_effect(monkeypatch, tmp_path, entry):
    def effect(*args, **kwargs):
        pytest.fail("unknown profile reached a local/remote effect")
    for name in ("git", "placed_hosts", "ship", "remote"):
        monkeypatch.setattr(rp, name, effect)
    with pytest.raises(SystemExit):
        if entry == "api":
            rp.run([["test/x.py"]], [tmp_path / "out"], test_tools="../arbitrary")
        else:
            rp.main(["--test-tools", "../arbitrary", "--", "test/x.py"])


def test_profile_identity_binds_committed_raw_blob_and_both_recipes(monkeypatch):
    plain = rp.deps(ROOT, BASE)
    selected = rp.deps(ROOT, BASE, test_tools=PROFILE)
    assert selected[0] != plain[0] and selected[1] == plain[1]
    original = rp.git
    seen = []
    def changed(repo, *args):
        seen.append(args)
        if args == ("rev-parse", f"{BASE}:{RAW}"):
            return "a" * 40
        return original(repo, *args)
    monkeypatch.setattr(rp, "git", changed)
    assert rp.deps(ROOT, BASE, test_tools=PROFILE)[0] != selected[0]
    assert ("rev-parse", f"{BASE}:{RAW}") in seen
    assert rp.deps(ROOT, BASE) == plain
    monkeypatch.setattr(rp, "git", original)
    for field in ("PROFILE_SETUP", "PROFILE_JOB"):
        with monkeypatch.context() as patch:
            patch.setattr(tools(), field, getattr(tools(), field) + "\n# identity change\n")
            assert rp.deps(ROOT, BASE, test_tools=PROFILE)[0] != selected[0]
            assert rp.deps(ROOT, BASE) == plain


def test_working_tree_raw_pins_are_ignored(tmp_path):
    repo = tmp_path / "repo"
    subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", str(ROOT), str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "--detach", BASE], check=True)
    before = rp.deps(repo, BASE, test_tools=PROFILE)
    default_before = rp.deps(repo, BASE)
    (repo / RAW).write_text("uncommitted-and-invalid\n")
    assert rp.deps(repo, BASE, test_tools=PROFILE) == before
    assert rp.deps(repo, BASE) == default_before
    # A real committed blob change must affect only the selected closure.
    # This oracle fails independently if profile identity drops the raw object.
    subprocess.run(["git", "-C", str(repo), "add", RAW], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Codex", "-c",
                    "user.email=codex@openai.com", "commit", "-q", "-m", "test raw identity"], check=True)
    changed = rp.git(repo, "rev-parse", "HEAD")
    assert rp.deps(repo, changed, test_tools=PROFILE)[0] != before[0]
    assert rp.deps(repo, changed) == default_before


def shell(script, root, *args, env=None):
    # Replace only the runner's known root. Never overwrite HOME/CODEX_HOME.
    script = script.replace("~/rosy-test", shlex.quote(str(root)))
    script = script.replace("~/rosy-jobs", shlex.quote(str(root / "jobs")))
    return subprocess.run(["bash", "-c", script, "remote", *args], capture_output=True,
                          env=env, timeout=25)


def executable(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)


def raw_fixture(target, *, bad_version=False, namespace=True):
    target.mkdir(parents=True, exist_ok=True)
    distributions = [("mcap", "1.5.0", "mcap"), ("mcap-ros2-support", "0.5.7", "mcap_ros2"),
                     ("numpy", "2.2.6", "numpy"), ("opencv-python-headless", "4.12.0.88", "cv2")]
    for name, version, module in distributions:
        package = target / module
        package.mkdir(exist_ok=True)
        if module != "mcap_ros2" or not namespace:
            (package / "__init__.py").write_text("")
        metadata = target / f"{name.replace('-', '_')}-{version}.dist-info"
        metadata.mkdir(exist_ok=True)
        (metadata / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {'0.0' if bad_version else version}\n")


def snapshot(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def native_stage(tmp_path):
    if sys.platform == "win32":
        pytest.skip("native Linux shell boundary")
    root = tmp_path / "native-root"
    outside = root / "venvs" / "default-existing"
    outside.mkdir(parents=True)
    (outside / ".deps-sha").write_text("default-existing\n")
    (outside / "untouched").write_bytes(b"default environment contents")
    checkout = root / "runs" / "r"
    checkout.mkdir(parents=True)
    for path in (rp.DEVICE_REQ, rp.FLEET_REQ, rp.VISION_REQ, rp.CRYPTO_REQ, RAW):
        dest = checkout / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(rp.git(ROOT, "show", f"{BASE}:{path}") + "\n")
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    return root, outside, fakebin


def prepare_installer(root, fakebin, mode):
    # The fixture interpreter delegates actual isolated readiness to native Python.
    # Pip exits successfully with an empty target in the critical negative case.
    script = f'''#!{sys.executable}
import os, pathlib, subprocess, sys
a = sys.argv[1:]
if a[:2] == ['-m', 'pip']:
    pathlib.Path({str(root / 'installer-called')!r}).touch()
    if {mode!r} == 'install-failure': sys.exit(19)
    if '--target' in a and 'raw-tools' in a[a.index('--target') + 1]:
        target = pathlib.Path(a[a.index('--target') + 1]); target.mkdir(parents=True, exist_ok=True)
        source = pathlib.Path({str(root / 'fixture-source')!r})
        if source.exists():
            import shutil
            shutil.copytree(source, target, dirs_exist_ok=True)
    if '--wheel-dir' in a:
        p = pathlib.Path(a[a.index('--wheel-dir') + 1]); p.mkdir(exist_ok=True); (p / 'fake.whl').touch()
    sys.exit(0)
if a[:2] == ['-m', 'pytest']:
    pathlib.Path({str(root / 'pytest-called')!r}).write_text(os.environ.get('PYTHONPATH', ''))
    sys.exit(0)
os.execv({sys.executable!r}, [{sys.executable!r}, *a])
'''
    interpreter = root / "fixture-python"
    executable(interpreter, script)
    executable(fakebin / "uv", '#!/bin/bash\nN="${@: -1}"\nmkdir -p "$N/bin"\n'
               + f"cp {shlex.quote(str(interpreter))} \"$N/bin/python\"\n"
               + 'printf \'#!%s/bin/python\\nprint("fixture console")\\n\' "$N" > "$N/bin/fixture-console"\n')
    executable(fakebin / "systemd-run", '#!/bin/bash\nwhile [ "$1" != -- ]; do shift; done; shift; exec "$@"\n')
    return {**os.environ, "PATH": f"{fakebin}:/usr/bin:/bin"}


@pytest.mark.parametrize("mode", ["empty-target", "wrong-version", "broken-import", "wrong-origin",
                                  "install-failure", "valid"])
def test_executed_setup_publishes_only_after_isolated_readiness(native_stage, mode):
    root, outside, fakebin = native_stage
    before = snapshot(outside)
    if mode in ("valid", "wrong-version", "broken-import", "wrong-origin"):
        raw_fixture(root / "fixture-source", bad_version=mode == "wrong-version")
        if mode == "broken-import":
            (root / "fixture-source/mcap/__init__.py").write_text("raise ImportError('broken fixture')\n")
        if mode == "wrong-origin":
            (root / "fixture-source/mcap/__init__.py").write_text("__file__ = '/outside/mcap/__init__.py'\n")
    env = prepare_installer(root, fakebin, mode)
    recipe = tools().render_setup(rp.VENV, PROFILE)
    result = shell(recipe, root, "r", "selected-hash", env=env)
    assert (root / "installer-called").exists(), result.stderr
    published = root / "venvs" / "selected-hash"
    staged = root / "venvs" / ".new-selected-hash"
    assert snapshot(outside) == before
    assert not (root / "pytest-called").exists()
    if mode == "valid":
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert (published / ".deps-sha").read_text().strip() == "selected-hash"
        assert (published / "raw-tools" / "mcap_ros2").is_dir()
        console = (published / "bin/fixture-console").read_text()
        assert console.startswith(f"#!{published}/bin/python\n")
        assert str(staged) not in console
    else:
        assert result.returncode != 0, (result.stdout, result.stderr)
        assert not (published / ".deps-sha").exists()
        assert not (staged / ".deps-sha").exists()


@pytest.mark.parametrize("context", [None, PROFILE, "unknown"])
@pytest.mark.parametrize("ready", [False, True])
def test_executed_job_binds_context_and_exposes_only_selected_target(native_stage, context, ready):
    root, outside, fakebin = native_stage
    before = snapshot(outside)
    env = prepare_installer(root, fakebin, "valid")
    venv = root / "venvs" / "selected-hash"
    executable(venv / "bin" / "python", (root / "fixture-python").read_text())
    (venv / ".deps-sha").write_text("selected-hash\n")
    raw_fixture(venv / "raw-tools")  # incidental target must not activate default jobs
    (venv / ".raw-pins").write_text(rp.git(ROOT, "show", f"{BASE}:{RAW}") + "\n")
    if ready:
        (venv / ".test-tools").write_text(PROFILE + "\n")
    jobs = root / "runs" / "r.jobs"
    jobs.mkdir()
    (root / "jobs").mkdir()
    if context == "unknown":
        with pytest.raises(SystemExit):
            tools().render_job(rj.JOB, context)
        return
    result = shell(tools().render_job(rj.JOB, context), root,
                   "r", "selected-hash", "", "0", "10", "test/x.py", env=env)
    marker = root / "pytest-called"
    if context == PROFILE and not ready:
        assert result.returncode != 0 and not marker.exists(), result.stderr
    elif context is None and ready:
        # A selected environment cannot accidentally serve a default context.
        assert result.returncode != 0 and not marker.exists(), result.stderr
    else:
        assert result.returncode == 0 and marker.exists(), result.stderr
        visible = marker.read_text().split(":")
        assert str(venv / "receiver-crypto") in visible
        assert (str(venv / "raw-tools") in visible) == (context == PROFILE)
    assert snapshot(outside) == before


def test_all_invocations_and_quarantine_keep_profile_context(monkeypatch, tmp_path):
    monkeypatch.setattr(rp, "ship", lambda *a: None)
    monkeypatch.setattr(rp, "deps", lambda *a, **kw: ("selected-hash", []))
    setup = []
    monkeypatch.setattr(rp, "remote", lambda host, script, *a, **kw:
                        setup.append(script) or subprocess.CompletedProcess([], 0))
    calls = []
    def job(host, name, k, log, context, args, *rest):
        calls.append((k, list(context), list(args)))
        if k == 0:
            log.write_text("FAILED test/x.py::test_case - expected\n")
            return 1
        log.write_text("PASSED test/x.py::test_case\n")
        return 0
    monkeypatch.setattr(rj, "run", job)
    monkeypatch.setattr(rp, "quarantine", lambda *a: {"test/x.py::test_case": "known flake"})
    codes = rp.run_on("h", [["ROSY_RUN_BROWSER_TESTS=1", "test/x.py"], ["test/y.py"]],
                      [tmp_path / "one", tmp_path / "two"], BASE, ROOT, None, test_tools=PROFILE)
    assert codes == [0, 0]
    assert [c[0] for c in calls] == [0, "0r", 1]
    assert all(c[1] == [calls[0][1][0], "selected-hash", "", PROFILE] for c in calls)
    assert calls[1][2][0] == "ROSY_RUN_BROWSER_TESTS=1"
    assert setup[0] == tools().render_setup(rp.VENV, PROFILE)


def test_setup_failure_starts_no_job(monkeypatch, tmp_path):
    monkeypatch.setattr(rp, "ship", lambda *a: None)
    monkeypatch.setattr(rp, "deps", lambda *a, **kw: ("selected-hash", []))
    monkeypatch.setattr(rp, "remote", lambda *a, **kw: subprocess.CompletedProcess([], 23))
    monkeypatch.setattr(rj, "run", lambda *a: pytest.fail("pytest started after failed setup"))
    with pytest.raises(SystemExit, match="setup"):
        rp.run_on("h", [["test/x.py"]], [tmp_path / "log"], BASE, ROOT, None, test_tools=PROFILE)


def test_run_dispatches_selected_profile_to_every_host(monkeypatch, tmp_path):
    monkeypatch.setattr(rp, "git", lambda repo, *args: str(ROOT) if args[-1] == "--show-toplevel" else BASE)
    monkeypatch.setattr(rp, "placed_hosts", lambda *a, **k: ["a", "b"])
    monkeypatch.setattr(rp, "cost", lambda *a: 1)
    contexts = []
    def run_on(host, invocations, logs, sha, repo, label, work=None, *, test_tools=None):
        contexts.append((host, test_tools))
        while (i := work.take()) is not None:
            work.codes[i] = 0
    monkeypatch.setattr(rp, "run_on", run_on)
    assert rp.run([["x"], ["y"]], [tmp_path / "x", tmp_path / "y"],
                  repo=ROOT, test_tools=PROFILE) == [0, 0]
    assert sorted(contexts) == [("a", PROFILE), ("b", PROFILE)]


def test_cli_passes_selected_profile_to_run(monkeypatch, tmp_path):
    monkeypatch.setattr(rp, "git", lambda *a: BASE)
    observed = []
    def run(invocations, logs, sha, **kw):
        observed.append((invocations, kw.get("test_tools")))
        return [0]
    monkeypatch.setattr(rp, "run", run)
    assert rp.main(["--test-tools", PROFILE, "--log-dir", str(tmp_path), "--", "test/x.py"]) == 0
    assert observed == [([["test/x.py"]], PROFILE)]


def test_detached_start_renders_profile_locally_for_older_business_checkout(tmp_path):
    calls = []
    def call(ssh, host, script, *args):
        calls.append((script, args))
        if script == rj.START:
            return subprocess.CompletedProcess([], 0, b"", b"")
        return subprocess.CompletedProcess([], 0, b"ROSYJOB 0 0\n", b"")
    assert rj.run("h", "r", 0, tmp_path / "log", ["r", "selected-hash", "", PROFILE],
                  ["test/x.py"], 10, [], call=call) == 0
    start_args = calls[0][1]
    assert start_args[:5] == ("r", "selected-hash", "", "0", "10")
    assert start_args[5] == tools().render_job(rj.JOB, PROFILE)
    assert start_args[6:] == ("test/x.py",)
    # No profile argument can become a shell argument or a pytest path.
    with pytest.raises(SystemExit):
        rj.run("h", "r", 1, tmp_path / "bad", ["r", "selected-hash", "", "unknown"],
               ["test/x.py"], 10, [], call=lambda *a: pytest.fail("unknown context reached SSH"))
