"""tools/remote/remote_pytest.py with fake ssh: host order, local fallback, exit codes, bundle range."""

from __future__ import annotations

import subprocess
import shlex
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import remote_pytest as rp  # noqa: E402


def test_first_reachable_host_wins_in_listed_order(monkeypatch):
    monkeypatch.delenv("ROSY_TEST_LOCAL", raising=False)
    monkeypatch.setenv("ROSY_TEST_HOSTS", "a@1 b@2 c@3")
    probed = []

    def probe(host):
        probed.append(host)
        return host != "a@1"

    assert rp.pick_host(probe=probe) == "b@2"
    assert probed == ["a@1", "b@2"]


def test_no_host_or_forced_local_means_local(monkeypatch):
    monkeypatch.delenv("ROSY_TEST_LOCAL", raising=False)
    assert rp.pick_host(["a@1", "b@2"], probe=lambda h: False) is None
    monkeypatch.setenv("ROSY_TEST_LOCAL", "1")
    assert rp.pick_host(["a@1"], probe=lambda h: True) is None


def test_unreachable_hosts_stop_the_gate(monkeypatch, tmp_path):
    monkeypatch.delenv("ROSY_TEST_LOCAL", raising=False)
    monkeypatch.setattr(rp, "reachable", lambda host: False)
    with pytest.raises(SystemExit, match="no test host reachable"):
        rp.run([["test/x.py"]], [tmp_path / "run-1.txt"], repo=ROOT)


def test_worst_exit_code_counts_nothing_collected_as_pass():
    assert rp.worst([]) == 0
    assert rp.worst([0, 5]) == 0
    assert rp.worst([0, 1, 5]) == 1
    assert rp.worst([1, 4, 0]) == 4
    assert rp.worst([0, -9]) == 1 and rp.worst([-9]) == 1  # killed by a signal is a failure


def test_affected_selection_uses_local_invocations_when_full_and_drops_skipped():
    sel = {"mode": "affected", "invocations": [["test/a.py", "test/b.py"], ["test/b.py"]],
           "local_invocations": [["guard.py"]]}
    assert rp.affected_invocations(sel, {"test/b.py"}) == [["test/a.py"]]
    assert rp.affected_invocations({**sel, "mode": "full"}, set()) == [["guard.py"]]


def test_matching_venv_does_not_wait_for_active_pytest(tmp_path):
    if not shutil.which("flock") or not shutil.which("bash"):
        pytest.skip("POSIX flock is required")
    root = tmp_path / "rosy-test"
    (root / "runs" / "run1").mkdir(parents=True)
    (root / "venvs" / "same").mkdir(parents=True)
    (root / "venvs" / "same" / ".deps-sha").write_text("same\n")
    lock = root / "venv.lock"
    holder = subprocess.Popen(
        ["bash", "-c", f'exec 9>{shlex.quote(str(lock))}; flock -x 9; echo ready; sleep 5'],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "ready"
        script = rp.VENV.replace("R=~/rosy-test", f"R={shlex.quote(str(root))}")
        subprocess.run(["bash", "-c", script, "remote", "run1", "same"],
                       check=True, timeout=2)
    finally:
        holder.terminate()
        holder.wait(timeout=2)


def test_pytest_uses_the_same_dependency_environment_as_setup():
    assert 'V=$R/venvs/$DEPS' in rp.VENV
    assert 'V=$R/venvs/$DEPS' in rp.PYTEST
    assert '[ "$(cat "$V/.deps-sha" 2>/dev/null)" = "$DEPS" ]' in rp.PYTEST


def test_lock_change_does_not_rebuild_venv_but_install_change_does(monkeypatch):
    baseline = rp.deps(ROOT, "HEAD")[0]
    monkeypatch.setattr(rp, "VENV", rp.VENV.replace("flock -x -w 600 9", "flock -x -w 60 9"))
    assert rp.deps(ROOT, "HEAD")[0] == baseline
    monkeypatch.setattr(rp, "VENV", rp.VENV.replace("$P check", "$P install extra\n$P check"))
    assert rp.deps(ROOT, "HEAD")[0] != baseline


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def test_bundle_starts_at_origin_main_and_falls_back_to_full_history(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    for n in range(3):
        _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", str(n))
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD~1")
    head, pushed = _git(repo, "rev-parse", "HEAD"), _git(repo, "rev-parse", "HEAD~1")
    assert rp.bundle_base(repo, head) == pushed

    sent = []

    def fake_remote(host, script, *args, input=None, **kw):
        listing = subprocess.run(["git", "bundle", "list-heads", "-"], input=input, capture_output=True,
                                 cwd=repo)
        prereq = b"\n-" in input.split(b"\n\n", 1)[0] or input.split(b"\n", 2)[1].startswith(b"-")
        sent.append(prereq)
        assert args[1] == head and listing.returncode == 0
        return subprocess.CompletedProcess([], 3 if prereq else 0, b"", b"")  # host lacks the base

    monkeypatch.setattr(rp, "remote", fake_remote)
    rp.ship(repo, "h", head, "run1")
    assert sent == [True, False]  # origin/main..sha first, then the whole history
    assert _git(repo, "for-each-ref", "refs/remote-pytest") == ""  # temporary ref removed


def test_pushing_origin_main_itself_sends_a_full_bundle(tmp_path, monkeypatch):
    # sha == origin/main (or behind it) would give an empty bundle, which git refuses.
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    for n in range(2):
        _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", str(n))
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    head, sent = _git(repo, "rev-parse", "HEAD"), []

    def fake_remote(host, script, *args, input=None, **kw):
        sent.append(subprocess.run(["git", "bundle", "list-heads", "-"], input=input, cwd=repo,
                                   capture_output=True).returncode)
        return subprocess.CompletedProcess([], 0, b"", b"")

    monkeypatch.setattr(rp, "remote", fake_remote)
    for sha in (head, _git(repo, "rev-parse", "HEAD~1")):
        rp.ship(repo, "h", sha, "run2")
    assert sent == [0, 0]


def _fake_ssh(tmp_path, monkeypatch, fail_on):
    """A fake ssh: `true` succeeds; a script containing `fail_on` exits 1, anything else 0."""
    fake = tmp_path / "fake_ssh.py"
    fake.write_text("import sys\nc = sys.argv[-1]\nif c != 'true':\n    sys.stdin.buffer.read()\n"
                    f"sys.exit(1 if {fail_on!r} in c else 0)\n", encoding="utf-8")
    monkeypatch.setattr(rp, "SSH", [sys.executable, str(fake)])
    monkeypatch.setenv("ROSY_TEST_HOSTS", "h")
    monkeypatch.delenv("ROSY_TEST_LOCAL", raising=False)


def test_ship_failure_is_a_nonzero_exit_and_leaves_no_ref(tmp_path, monkeypatch):
    _fake_ssh(tmp_path, monkeypatch, "git bundle verify")
    monkeypatch.setattr(rp.secrets, "token_hex", lambda _: "f0f0f0")
    sha = _git(ROOT, "rev-parse", "HEAD")
    with pytest.raises(SystemExit) as exc:
        rp.main(["--log-dir", str(tmp_path), "--require-host", "--", "test/x.py"])
    assert exc.value.code != 0
    ref = f"refs/remote-pytest/{sha[:10]}-f0f0f0"
    assert subprocess.run(["git", "-C", str(ROOT), "show-ref", "--verify", "--quiet", ref]).returncode == 1


def test_venv_failure_is_a_nonzero_exit(tmp_path, monkeypatch):
    _fake_ssh(tmp_path, monkeypatch, "/.new-")
    with pytest.raises(SystemExit) as exc:
        rp.main(["--log-dir", str(tmp_path), "--require-host", "--", "test/x.py"])
    assert exc.value.code != 0


def test_remote_pytest_failure_and_signal_death_propagate(tmp_path, monkeypatch):
    _fake_ssh(tmp_path, monkeypatch, "systemd-run")
    assert rp.main(["--log-dir", str(tmp_path), "--require-host", "--", "test/x.py"]) == 1
    monkeypatch.setattr(rp, "capture", lambda command, log, cwd=None: -9)
    assert rp.main(["--log-dir", str(tmp_path), "--require-host", "--", "test/x.py"]) == 1


def test_timeout_is_a_failed_step(monkeypatch):
    def hang(*a, **kw):
        raise subprocess.TimeoutExpired("ssh", 1)
    monkeypatch.setattr(rp.subprocess, "run", hang)
    assert rp.remote("h", "true", timeout=1).returncode == 124


def test_several_invocations_spread_over_every_reachable_host(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(rp, "git", lambda repo, *args: str(tmp_path) if "--show-toplevel" in args else "ab" * 20)
    monkeypatch.setattr(rp, "reachable", lambda host: host != "down@3")
    monkeypatch.setenv("ROSY_TEST_HOSTS", "a@1 b@2 down@3")
    monkeypatch.setattr(rp, "run_on", lambda host, invs, logs, *rest: [seen.append((host, inv)) or len(inv[0])
                                                                       for inv in invs])
    invocations = [["x"], ["yy"], ["zzz"]]
    codes = rp.run(invocations, [tmp_path / f"{i}.txt" for i in range(3)], repo=tmp_path)
    assert codes == [1, 2, 3], "codes come back in invocation order"
    assert sorted(seen) == [("a@1", ["x"]), ("a@1", ["zzz"]), ("b@2", ["yy"])]


def test_a_host_that_fails_setup_hands_its_share_to_a_working_host(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(rp, "git", lambda repo, *args: str(tmp_path) if "--show-toplevel" in args else "ab" * 20)
    monkeypatch.setattr(rp, "reachable", lambda host: True)
    monkeypatch.setenv("ROSY_TEST_HOSTS", "a@1 b@2")

    def run_on(host, invs, logs, *rest):
        if host == "b@2":
            raise SystemExit("venv setup failed")
        return [seen.append((host, inv)) or 0 for inv in invs]
    monkeypatch.setattr(rp, "run_on", run_on)
    assert rp.run([["x"], ["y"]], [tmp_path / "1.txt", tmp_path / "2.txt"], repo=tmp_path) == [0, 0]
    assert sorted(seen) == [("a@1", ["x"]), ("a@1", ["y"])]
