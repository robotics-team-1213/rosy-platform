"""tools/remote/remote_pytest.py with fake ssh: host order, local fallback, exit codes, bundle range."""

from __future__ import annotations

import subprocess
import shlex
import time
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import remote_pytest as rp  # noqa: E402


def host(nproc=24, load1=1.0, avail_gb=12.0, total_gb=15.0, pytest=True, sim=False, busy=False,
         lock_cores=0, lock_gb=0, site=False):
    """A fake PROBE result."""
    return {"nproc": nproc, "load1": load1, "avail_gb": avail_gb, "total_gb": total_gb, "pytest": pytest,
            "sim": sim, "busy": busy, "lock_cores": lock_cores, "lock_gb": lock_gb, "site": site}


def test_most_headroom_first_and_floor_skips_full_hosts():
    hosts = ["model@1", "ai@2", "low@3"]
    chosen, notes = rp.place("pytest", hosts, [host(avail_gb=8), host(avail_gb=12), host(avail_gb=3)])
    assert chosen == ["ai@2", "model@1"]
    assert "below pytest floor" in notes[2] and notes[1].endswith("ok")
    # Busy cores count: load or locked budgets, whichever is larger.
    chosen, _ = rp.place("pytest", hosts[:2], [host(load1=23.5), host(nproc=8, lock_cores=7)])
    assert chosen == []


def test_lock_budget_reserves_memory_not_yet_used():
    chosen, notes = rp.place("pytest", ["a@1"], [host(avail_gb=12, total_gb=15, lock_gb=12)])
    assert chosen == [] and "3.0 GB free" in notes[0]


def test_sim_needs_capability_and_its_own_floor():
    hosts = ["model@1", "ai@2"]
    probes = [host(sim=True, nproc=8, load1=3), host(sim=False)]
    chosen, notes = rp.place("sim", hosts, probes)
    assert chosen == [] and "below sim floor" in notes[0] and "no sim capability" in notes[1]
    assert rp.place("sim", hosts, [host(sim=True), host()])[0] == ["model@1"]


def test_site_pc_is_last_resort_with_fleet_reserve_and_busy_flag():
    site = rp.SITE_HOST
    hosts = ["model@1", site]
    roomy = host(nproc=8, load1=0.2, avail_gb=13)
    assert rp.place("pytest", hosts, [host(), roomy])[0] == ["model@1"]
    assert rp.place("pytest", hosts, [host(avail_gb=2), roomy])[0] == [site]
    # Fleet reserve: 8 threads - 2 can never meet the sim floor of 6.
    assert rp.place("sim", hosts, [None, {**roomy, "sim": True}])[0] == []
    chosen, notes = rp.place("pytest", hosts, [host(avail_gb=2), {**roomy, "busy": True}])
    assert chosen == [] and "busy" in notes[1]


def test_site_pc_under_another_name_keeps_its_protections(monkeypatch, tmp_path):
    monkeypatch.delenv("ROSY_TEST_LOCAL", raising=False)
    monkeypatch.setattr(rp, "SITES", {rp.SITE_HOST})
    other = "robttt@192.168.1.230"
    roomy = host(nproc=8, load1=0.2, avail_gb=13, site=True)  # ~/rosy-jobs/site on the host
    probes = {"model@1": host(), other: roomy}
    monkeypatch.setattr(rp, "probe", probes.get)
    assert rp.placed_hosts("pytest", list(probes)) == ["model@1"]  # last
    _, notes = rp.place("pytest", [other], [roomy])
    assert "5.8 cores, 9.0 GB free (site PC)" in notes[0]  # Fleet reserve taken off
    probes["model@1"] = host(avail_gb=1)
    assert rp.placed_hosts("pytest", list(probes)) == [other]
    sent = []
    monkeypatch.setattr(rp, "ship", lambda *a, **kw: None)
    monkeypatch.setattr(rp, "deps", lambda repo, sha: ("d" * 16, []))
    monkeypatch.setattr(rp, "remote", lambda *a, **kw: subprocess.CompletedProcess([], 0, b"", b""))
    monkeypatch.setattr(rp, "capture", lambda command, log, cwd=None: sent.append(command[-1]) or 0)
    rp.run_on(other, [["test/x.py"]], [tmp_path / "1.txt"], "ab" * 20, tmp_path, None)
    assert " 400% test/x.py" in sent[0]  # CPU cap


def test_unreachable_and_forced_local(monkeypatch):
    monkeypatch.delenv("ROSY_TEST_LOCAL", raising=False)
    assert rp.place("pytest", ["a@1"], [None]) == ([], ["a@1: unreachable"])
    monkeypatch.setattr(rp, "probe", lambda h: host())
    assert rp.placed_hosts("pytest", ["a@1"]) == ["a@1"]
    monkeypatch.setenv("ROSY_TEST_LOCAL", "1")
    assert rp.placed_hosts("pytest", ["a@1"]) == []


def test_pytest_falls_back_to_full_non_site_hosts_but_sim_does_not(monkeypatch):
    monkeypatch.delenv("ROSY_TEST_LOCAL", raising=False)
    probes = {"a@1": host(avail_gb=1), "b@2": host(avail_gb=1, busy=True), rp.SITE_HOST: host(avail_gb=1)}
    monkeypatch.setattr(rp, "probe", probes.get)
    assert rp.placed_hosts("pytest", list(probes)) == ["a@1"]
    assert rp.placed_hosts("sim", list(probes)) == []


def test_pick_prints_one_host_or_exits_1(monkeypatch, capsys):
    monkeypatch.delenv("ROSY_TEST_LOCAL", raising=False)
    monkeypatch.setenv("ROSY_TEST_HOSTS", "a@1 b@2")
    monkeypatch.setattr(rp, "probe", lambda h: host(sim=h == "b@2"))
    reserved = []
    monkeypatch.setattr(rp, "remote", lambda h, script, *args, **kw: reserved.append((h, script, args)))
    assert rp.main(["--pick", "sim"]) == 0
    assert capsys.readouterr().out == "b@2\n"
    assert reserved == [("b@2", rp.RESERVE, ("sim", "6", "8", "600"))]
    monkeypatch.setattr(rp, "probe", lambda h: None)
    assert rp.main(["--pick", "sim"]) == 1
    assert capsys.readouterr().out == ""
    monkeypatch.setenv("ROSY_TEST_LOCAL", "1")
    assert rp.main(["--pick", "sim"]) == 1
    assert "ROSY_TEST_LOCAL=1" in capsys.readouterr().err


def test_probe_parser_reads_only_the_rosyprobe_line():
    line = "ROSYPROBE 8 0.5 4194304 8388608 1 0 0 2 6 1"
    p = rp.parse_probe(f"Welcome to Ubuntu\nlast login: today\n{line}\nbye\n")
    assert p["nproc"] == 8 and p["avail_gb"] == 4 and p["pytest"] and not p["sim"] and p["lock_gb"] == 6 and p["site"]
    assert rp.parse_probe("8 0.5 4194304 8388608 1 0 0 2 6 0\n") is None
    assert rp.parse_probe("ROSYPROBE 8 0.5\n") is None


def test_probe_script_counts_live_locks_and_drops_dead_ones(tmp_path):
    if not shutil.which("bash") or sys.platform == "win32":
        pytest.skip("POSIX bash with /proc is required")
    jobs = tmp_path / "rosy-jobs"
    jobs.mkdir()
    live = subprocess.Popen(["sleep", "30"])
    try:
        (jobs / "live.lock").write_text(f"{live.pid} pytest 2 6\n")
        (jobs / "dead.lock").write_text("999999999 sim 6 8\n")
        (jobs / "odd.lock").write_text(f"{live.pid} sim 6 7.5\n")  # counts 0, does not abort
        (jobs / "evil.lock").write_text(f"{live.pid} sim a[$(touch {jobs}/pwned)] 1\n")
        now = int(time.time())
        (jobs / "soon.resv").write_text(f"{now + 600} pytest 2 6\n")  # reserved, not started yet
        (jobs / "old.resv").write_text(f"{now - 1} pytest 2 6\n")
        (jobs / "junk.resv").write_text("soon pytest 2 6\n")
        script = rp.PROBE.replace("J=~/rosy-jobs", f"J={shlex.quote(str(jobs))}")
        fields = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True).stdout.split()
    finally:
        live.kill()
    assert len(fields) == 11 and fields[-3:] == ["4", "12", "0"]
    assert (jobs / "soon.resv").exists() and not (jobs / "old.resv").exists() and not (jobs / "junk.resv").exists()
    assert rp.parse_probe(" ".join(fields))["lock_gb"] == 6
    assert not (jobs / "dead.lock").exists() and (jobs / "live.lock").exists()
    assert not (jobs / "pwned").exists()


def test_site_pc_pytest_gets_a_cpu_quota(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(rp, "ship", lambda *a: None)
    monkeypatch.setattr(rp, "deps", lambda repo, sha: ("d" * 16, []))
    monkeypatch.setattr(rp, "remote", lambda *a, **kw: subprocess.CompletedProcess([], 0, b"", b""))
    monkeypatch.setattr(rp, "capture", lambda command, log, cwd=None: sent.append(command[-1]) or 0)
    for h in (rp.SITE_HOST, "model@1"):
        rp.run_on(h, [["test/x.py"]], [tmp_path / "1.txt"], "ab" * 20, tmp_path, None)
    assert " 400% test/x.py" in sent[0] and "'' test/x.py" in sent[1]


def test_unreachable_hosts_stop_the_gate(monkeypatch, tmp_path):
    monkeypatch.delenv("ROSY_TEST_LOCAL", raising=False)
    monkeypatch.setattr(rp, "probe", lambda host: None)
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
    monkeypatch.setattr(rp, "probe", lambda h: host())
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


def test_setup_steps_run_at_low_priority_and_capped_on_site_hosts(monkeypatch):
    sent = []
    monkeypatch.setattr(rp.subprocess, "run", lambda cmd, **kw: sent.append(cmd[-1]) or
                        subprocess.CompletedProcess(cmd, 0))
    monkeypatch.setattr(rp, "SITES", {"site@9"})
    rp.remote("model@1", rp.VENV, "x", timeout=1)
    rp.remote("site@9", rp.SHIP, "x", timeout=1, input=b"")
    assert sent[0].startswith("nice -n 15 ionice -c3 bash -c ")
    assert sent[1].startswith("systemd-run --user --scope -q -p MemoryMax=6G -p CPUQuota=400% -- nice -n 15")


def test_timeout_is_a_failed_step(monkeypatch):
    def hang(*a, **kw):
        raise subprocess.TimeoutExpired("ssh", 1)
    monkeypatch.setattr(rp.subprocess, "run", hang)
    assert rp.remote("h", "true", timeout=1).returncode == 124


def test_several_invocations_spread_over_every_reachable_host(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(rp, "git", lambda repo, *args: str(tmp_path) if "--show-toplevel" in args else "ab" * 20)
    monkeypatch.setattr(rp, "probe", lambda h: None if h == "down@3" else host())
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
    monkeypatch.setattr(rp, "probe", lambda h: host())
    monkeypatch.setenv("ROSY_TEST_HOSTS", "a@1 b@2")

    def run_on(host, invs, logs, *rest):
        if host == "b@2":
            raise SystemExit("venv setup failed")
        return [seen.append((host, inv)) or 0 for inv in invs]
    monkeypatch.setattr(rp, "run_on", run_on)
    assert rp.run([["x"], ["y"]], [tmp_path / "1.txt", tmp_path / "2.txt"], repo=tmp_path) == [0, 0]
    assert sorted(seen) == [("a@1", ["x"]), ("a@1", ["y"])]
