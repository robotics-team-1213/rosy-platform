"""tools/remote/remote_pytest.py with fake ssh: host order, no local run (D-584), exit codes, bundle range."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import shlex
import threading
import time
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import remote_job as rj  # noqa: E402
import remote_pytest as rp  # noqa: E402
import xdist_plan as xp  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_headroom(monkeypatch):
    """place() fills rp.HEADROOM; no test sees another test's hosts."""
    monkeypatch.setattr(rp, "HEADROOM", {})
    monkeypatch.delenv("ROSY_TEST_WORKERS", raising=False)


def test_changed_vision_dependency_rebuilds_remote_environment(monkeypatch):
    original = rp.git
    changed = False

    def git(repo, *args):
        result = original(repo, *args)
        if changed and args[0] == "rev-parse" and args[1].endswith(":deploy/site/requirements-vision.txt"):
            return "f" * 40
        return result

    monkeypatch.setattr(rp, "git", git)
    before, dirs = rp.deps(ROOT, "HEAD")
    changed = True
    after, after_dirs = rp.deps(ROOT, "HEAD")
    assert before != after and dirs == after_dirs


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


def test_site_pc_is_last_resort_with_fleet_reserve_and_busy_flag(monkeypatch):
    site = "site@lab"
    monkeypatch.setattr(rp, "SITE_HOST", site)
    monkeypatch.setattr(rp, "SITES", {site})
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
    monkeypatch.setattr(rp, "SITES", {"site@lab"})
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
    monkeypatch.setattr(rp.remote_job, "run", lambda host, name, k, log, job, inv, *a: sent.append(job) or log.write_bytes(b""))
    rp.run_on(other, [["test/x.py"]], [tmp_path / "1.txt"], "ab" * 20, tmp_path, None)
    assert sent[0][2] == "400%"  # CPU cap


def test_unreachable_and_local_env_rejected(monkeypatch):
    monkeypatch.delenv("ROSY_TEST_LOCAL", raising=False)
    assert rp.place("pytest", ["a@1"], [None]) == ([], ["a@1: unreachable"])
    monkeypatch.setattr(rp, "probe", lambda h: host())
    assert rp.placed_hosts("pytest", ["a@1"]) == ["a@1"]
    for value in ("1", "0", ""):  # any value is an error, never a silent pass
        monkeypatch.setenv("ROSY_TEST_LOCAL", value)
        with pytest.raises(SystemExit, match="D-584"):
            rp.placed_hosts("pytest", ["a@1"])


def test_local_flag_rejected_and_require_host_is_a_noop(monkeypatch):
    monkeypatch.delenv("ROSY_TEST_LOCAL", raising=False)
    with pytest.raises(SystemExit, match="D-584"):
        rp.main(["--local", "--", "test/x.py"])
    monkeypatch.setattr(rp, "probe", lambda h: None)
    with pytest.raises(SystemExit, match="no test host reachable"):
        rp.main(["--require-host", "--wait", "0", "--", "test/x.py"])


def test_no_host_retries_until_the_deadline_then_fails_without_running_pytest(monkeypatch, tmp_path):
    monkeypatch.delenv("ROSY_TEST_LOCAL", raising=False)
    now, probes = [0.0], []
    monkeypatch.setattr(rp, "placed_hosts", lambda cls="pytest", hosts=None: probes.append(now[0]) or [])
    monkeypatch.setattr(rp, "capture", lambda *a, **kw: pytest.fail("pytest must not run on this machine"))
    with pytest.raises(SystemExit, match=r"no test host reachable \(D-584\)"):
        rp.run([["test/x.py"]], [tmp_path / "1.txt"], repo=ROOT, wait=600, poll=30,
               sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0])
    assert probes == [30.0 * i for i in range(21)]  # probe, then every 30 s until 600 s


def test_host_appearing_during_the_wait_runs_there(monkeypatch, tmp_path):
    monkeypatch.delenv("ROSY_TEST_LOCAL", raising=False)
    now, answers = [0.0], [[], [], ["a@1"]]
    monkeypatch.setattr(rp, "placed_hosts", lambda cls="pytest", hosts=None: answers.pop(0))
    monkeypatch.setattr(rp, "run_on", lambda host, inv, logs, sha, repo, label: [0] * len(inv))
    codes = rp.run([["test/x.py"]], [tmp_path / "1.txt"], repo=ROOT, wait=600, poll=30,
                   sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0])
    assert codes == [0] and now[0] == 60.0


def test_pytest_falls_back_to_full_non_site_hosts_but_sim_does_not(monkeypatch):
    monkeypatch.delenv("ROSY_TEST_LOCAL", raising=False)
    monkeypatch.setattr(rp, "SITE_HOST", "site@lab")
    monkeypatch.setattr(rp, "SITES", {"site@lab"})
    probes = {"a@1": host(avail_gb=1), "b@2": host(avail_gb=1, busy=True), "site@lab": host(avail_gb=1)}
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
    with pytest.raises(SystemExit, match="D-584"):
        rp.main(["--pick", "sim"])


def test_probe_parser_reads_only_the_rosyprobe_line():
    line = "ROSYPROBE 8 0.5 4194304 8388608 1 0 0 2 6 1"
    p = rp.parse_probe(f"Welcome to Ubuntu\nlast login: today\n{line}\nbye\n")
    assert p["nproc"] == 8 and p["avail_gb"] == 4 and p["pytest"] and not p["sim"] and p["lock_gb"] == 6 and p["site"]
    assert rp.parse_probe("8 0.5 4194304 8388608 1 0 0 2 6 0\n") is None
    assert rp.parse_probe("ROSYPROBE 8 0.5\n") is None
    assert "disk_free_gb" not in p  # an older probe: disk unknown, never a refusal
    # ~/rosy-test then /tmp: the fuller filesystem counts
    disk = rp.parse_probe(f"{line} 52428800 40 2726297 100 \n")
    assert disk["disk_free_gb"] == 2726297 / 2**20 and disk["disk_use"] == 100 and disk["nproc"] == 8


def _probe(**disk):
    return {"nproc": 8, "load1": 0.0, "avail_gb": 16.0, "total_gb": 32.0, "pytest": True, "sim": True,
            "busy": False, "lock_cores": 0, "lock_gb": 0, "site": False, **disk}


def test_place_refuses_a_host_below_the_disk_floor_and_keeps_unmeasured_ones(monkeypatch):
    """2026-10-26: a 100% full AI PC still got jobs, and a SQLite fsync stall failed a timing test."""
    monkeypatch.setattr(rp, "SITES", set())
    hosts = ["full@1", "edge@2", "pct@3", "old@4"]
    probes = [_probe(disk_free_gb=2.6, disk_use=100), _probe(disk_free_gb=19.9, disk_use=80),
              _probe(disk_free_gb=56.0, disk_use=95), _probe()]
    chosen, notes = rp.place("pytest", hosts, probes)
    assert sorted(chosen) == ["old@4", "pct@3"]  # 95% use with 56 GB free is healthy: no percent rule
    assert notes[0] == "full@1: 8.0 cores, 16.0 GB free, disk 2.6 GB free (100%) - below disk floor 20 GB"
    assert notes[1].endswith("below disk floor 20 GB") and notes[2].endswith(" - ok") and notes[3].endswith(" - ok")
    # the no-host-above-floor fallback must not send the gate to a full disk either
    monkeypatch.delenv("ROSY_TEST_LOCAL", raising=False)
    monkeypatch.setenv("ROSY_TEST_HOSTS", "full@1")
    monkeypatch.setattr(rp, "probe", lambda host: probes[0])
    assert rp.placed_hosts("pytest") == []


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
    assert len(fields) == 15 and fields[8:11] == ["4", "12", "0"]  # then df free_kb use% of ~/rosy-test, /tmp
    assert (jobs / "soon.resv").exists() and not (jobs / "old.resv").exists() and not (jobs / "junk.resv").exists()
    assert rp.parse_probe(" ".join(fields))["lock_gb"] == 12
    assert not (jobs / "dead.lock").exists() and (jobs / "live.lock").exists()
    assert not (jobs / "pwned").exists()


def test_site_pc_pytest_gets_a_cpu_quota(monkeypatch, tmp_path):
    monkeypatch.setattr(rp, "SITE_HOST", "site@lab")
    monkeypatch.setattr(rp, "SITES", {"site@lab"})
    sent = []
    monkeypatch.setattr(rp, "ship", lambda *a: None)
    monkeypatch.setattr(rp, "deps", lambda repo, sha: ("d" * 16, []))
    monkeypatch.setattr(rp, "remote", lambda *a, **kw: subprocess.CompletedProcess([], 0, b"", b""))
    monkeypatch.setattr(rp.remote_job, "run", lambda host, name, k, log, job, inv, *a: sent.append(job) or log.write_bytes(b""))
    for h in (rp.SITE_HOST, "model@1"):
        rp.run_on(h, [["test/x.py"]], [tmp_path / "1.txt"], "ab" * 20, tmp_path, None)
    assert sent[0][2] == "400%" and sent[1][2] == ""


def test_unreachable_hosts_stop_the_gate(monkeypatch, tmp_path):
    monkeypatch.delenv("ROSY_TEST_LOCAL", raising=False)
    monkeypatch.setattr(rp, "probe", lambda host: None)
    with pytest.raises(SystemExit, match="no test host reachable"):
        rp.run([["test/x.py"]], [tmp_path / "run-1.txt"], repo=ROOT, wait=0)


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
    assert 'V=$R/venvs/$DEPS' in rj.START and 'V=$R/venvs/$2' in rj.JOB
    assert '[ "$(cat "$V/.deps-sha" 2>/dev/null)" = "$DEPS" ]' in rj.START


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
    monkeypatch.setattr(rp.remote_job, "run", lambda *a, **kw: -9)
    assert rp.main(["--log-dir", str(tmp_path), "--require-host", "--", "test/x.py"]) == 1


def test_the_pytest_job_is_best_effort_lowest_io_not_idle():
    """2026-10-26: idle I/O (-c3) starved timing tests' SQLite fsync behind any other writer on the AI PC."""
    job = rj.JOB.split("systemd-run", 1)[1]
    assert "ionice -c2 -n7 " in job and "ionice -c3" not in job


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


def _fake_hosts(monkeypatch, tmp_path, hosts, job, venv_fails=()):
    """run() over fake hosts: setup succeeds (venv fails on venv_fails), job(host, inv) is one pytest."""
    seen = []
    monkeypatch.delenv("ROSY_TEST_LOCAL", raising=False)
    monkeypatch.setattr(rp, "git", lambda repo, *args: str(tmp_path) if "--show-toplevel" in args else "ab" * 20)
    monkeypatch.setattr(rp, "probe", lambda h: None if h.startswith("down") else host())
    monkeypatch.setenv("ROSY_TEST_HOSTS", " ".join(hosts))
    monkeypatch.setattr(rp, "ship", lambda *a: None)
    monkeypatch.setattr(rp, "deps", lambda repo, sha: ("d" * 16, []))
    monkeypatch.setattr(rp, "remote", lambda h, script, *a, **kw: subprocess.CompletedProcess(
        [], 1 if script == rp.VENV and h in venv_fails else 0, b"", b""))

    def run(h, name, k, log, job_args, inv, *a):
        path = next(w for w in inv if not rp.ENV_ARG.match(w))  # past xdist_plan's ROSY_JOB_* words
        seen.append((h, path))
        code = job(h, path)
        log.write_bytes(b"")
        return code
    monkeypatch.setattr(rp.remote_job, "run", run)
    return seen


def test_several_invocations_spread_over_every_reachable_host(monkeypatch, tmp_path):
    seen = _fake_hosts(monkeypatch, tmp_path, ["a@1", "b@2", "down@3"], lambda h, path: len(path))
    invocations = [["x"], ["yy"], ["zzz"]]
    codes = rp.run(invocations, [tmp_path / f"{i}.txt" for i in range(3)], repo=tmp_path)
    assert codes == [1, 2, 3], "codes come back in invocation order"
    assert sorted(p for _, p in seen) == ["x", "yy", "zzz"] and {h for h, _ in seen} <= {"a@1", "b@2"}


def test_a_host_that_fails_setup_hands_its_share_to_a_working_host(monkeypatch, tmp_path):
    seen = _fake_hosts(monkeypatch, tmp_path, ["a@1", "b@2"], lambda h, path: 0, venv_fails={"b@2"})
    assert rp.run([["x"], ["y"]], [tmp_path / "1.txt", tmp_path / "2.txt"], repo=tmp_path) == [0, 0]
    assert sorted(seen) == [("a@1", "x"), ("a@1", "y")]


def test_a_slow_host_does_not_hold_back_queued_invocations(monkeypatch, tmp_path):
    # Fixed k % n gave slow@2 items 1 and 3, so fast@1 could finish only 3 and slow@2 timed out waiting.
    slow_started, released, fast_done = threading.Event(), threading.Event(), []

    def job(h, path):
        if h == "slow@2":
            slow_started.set()
            assert released.wait(10), "the fast host did not take the rest of the queue"
        else:
            assert slow_started.wait(10)
            fast_done.append(path)
            if len(fast_done) == 4:
                released.set()
        return int(path)

    seen = _fake_hosts(monkeypatch, tmp_path, ["fast@1", "slow@2"], job)
    codes = rp.run([[str(i)] for i in range(5)], [tmp_path / f"{i}.txt" for i in range(5)], repo=tmp_path)
    assert codes == [0, 1, 2, 3, 4]
    assert [h for h, _ in seen].count("slow@2") == 1 and sorted(p for _, p in seen) == list("01234")


def test_an_invocation_that_fails_mid_run_is_retried_on_another_host_and_a_lost_one_is_not(monkeypatch, tmp_path):
    failed = []

    def job(h, path):
        if path == "boom" and not failed:
            failed.append(h)
            raise SystemExit("ssh died")  # neither an exit code nor Lost: that host is out
        if path == "gone":
            raise rj.Lost("lost contact with " + h)
        return 0

    seen = _fake_hosts(monkeypatch, tmp_path, ["a@1", "b@2"], job)
    order = ["boom", "x", "y", "z"]
    codes = rp.run([[p] for p in order], [tmp_path / f"{p}.txt" for p in order], repo=tmp_path)
    assert codes == [0, 0, 0, 0]
    boom = [h for h, p in seen if p == "boom"]
    assert len(boom) == 2 and boom[0] == failed[0] != boom[1]  # retried once, on the other host
    assert sorted(p for _, p in seen if p != "boom") == ["x", "y", "z"]  # nothing dropped or run twice
    # A lost invocation keeps running on its host: 255, never rerun elsewhere (no double count).
    seen.clear()
    codes = rp.run([["gone"], ["x"]], [tmp_path / "g.txt", tmp_path / "x2.txt"], repo=tmp_path)
    assert codes == [rj.LOST_EXIT, 0] and [p for _, p in seen].count("gone") == 1


def test_largest_test_files_are_queued_first(tmp_path):
    (tmp_path / "big.py").write_text("x" * 100)
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "a.py").write_text("x" * 30)
    (tmp_path / "d" / "b.py").write_text("x" * 30)
    assert rp.cost(tmp_path, [rp.BROWSER_ENV, "big.py::test_t", "-q"]) == 100
    assert rp.cost(tmp_path, ["d"]) == 60 and rp.cost(tmp_path, ["missing.py"]) == 0


class FakeJobHost:
    """A host whose job log grows by one chunk per call (also while the link is down)."""

    def __init__(self, chunks, rc, fail=(), junk=()):
        self.chunks, self.rc, self.fail, self.junk = list(chunks), rc, set(fail), set(junk)
        self.log, self.polls, self.scripts = b"", 0, []

    def __call__(self, ssh, host, script, *args):
        self.scripts.append(script)
        if script != rj.POLL:
            return subprocess.CompletedProcess([], 0, b"", b"")
        self.polls += 1
        if self.chunks:
            self.log += self.chunks.pop(0)
        if self.polls in self.fail:
            return None
        if self.polls in self.junk:  # ssh exit 0 but cut before the marker line ended
            return subprocess.CompletedProcess([], 0, b"motd\nROSYJ", b"")
        rc = b"-" if self.chunks else str(self.rc).encode()
        return subprocess.CompletedProcess([], 0, b"Welcome\nROSYJOB " + rc + b" 1\n" + self.log[int(args[2]):], b"")


def _clock():
    now = [0.0]
    return now, (lambda s: now.__setitem__(0, now[0] + s)), (lambda: now[0])


def test_polls_that_fail_then_recover_give_the_real_code_and_the_whole_log(tmp_path):
    chunks = [b"collecting\n", b"..F", b".\xc3\xa9\r\n", b"FAILED test/x.py::t\n", b"1 failed\n"]
    fake = FakeJobHost(chunks, 1, fail={2, 3, 4}, junk={5})
    now, sleep, clock = _clock()
    log = tmp_path / "run-1.txt"
    assert rj.run("h", "r", 0, log, ["r", "d", ""], ["test/x.py"], 60, [], call=fake, sleep=sleep, clock=clock) == 1
    # Byte-identical: a stuck offset would duplicate a chunk, an early advance would drop one.
    assert log.read_bytes() == fake.log == b"".join(chunks)
    assert fake.scripts[0] == rj.START and fake.polls == 6


def test_polls_failing_past_the_budget_raise_lost_and_run_on_leaves_the_job(tmp_path, monkeypatch, capsys):
    fake = FakeJobHost([b"a", b"b", b"c"], 0, fail=set(range(2, 99)))
    now, sleep, clock = _clock()
    with pytest.raises(rj.Lost, match=r"lost contact with h for 60 s; the run continues there: h:~/rosy-test"):
        rj.run("h", "r", 0, tmp_path / "1.txt", ["r", "d", ""], [], 60, [], call=fake, sleep=sleep, clock=clock,
               budget=60)
    assert (tmp_path / "1.txt").read_bytes() == b"a" and rj.KILL not in fake.scripts
    calls = []
    monkeypatch.setattr(rp, "ship", lambda *a: None)
    monkeypatch.setattr(rp, "deps", lambda repo, sha: ("d" * 16, []))
    monkeypatch.setattr(rp, "remote", lambda host, script, *a, **kw: calls.append(script) or
                        subprocess.CompletedProcess([], 0, b"", b""))
    monkeypatch.setattr(rp.remote_job, "run", lambda *a: (_ for _ in ()).throw(rj.Lost("lost contact with h")))
    codes = rp.run_on("h", [["a"], ["b"]], [tmp_path / "1.txt", tmp_path / "2.txt"], "ab" * 20, tmp_path, None)
    assert codes == [255, 255] and rp.CLEANUP not in calls  # no cleanup under a live job
    assert "lost contact with h" in capsys.readouterr().err


def test_exit_code_counts_only_when_complete_and_chatter_is_ignored():
    assert rj.parse_poll(b"motd\nROSYJOB - 1\nlog") == (None, True, b"log")
    assert rj.parse_poll(b"ROSYJOB 3 0\n") == (3, False, b"")
    assert rj.parse_poll(b"ROSYJOB 1 0") is None and rj.parse_poll(b"partial") is None
    assert rj.parse_poll(b"ROSYJOB 1\n") is None  # no liveness field: cut off or an old script
    assert rj.parse_poll(b"ROSYJOB x 1\nlog") == (None, True, b"log")
    # The job writes the code beside the file and renames it; POLL reads only the final name.
    assert 'mv -f "$D/$K.rc.tmp" "$D/$K.rc"' in rj.JOB
    assert '[ -f "$D/$2.rc" ]' in rj.POLL and rj.POLL.index(".rc") < rj.POLL.index("tail")
    assert 'rm -f "$L"' in rj.JOB.split("trap '", 1)[1].split("' EXIT", 1)[0]
    assert 'echo "$$ pytest 2 6" > "$L"' in rj.JOB  # the lock pid is the detached job's own


def test_ship_is_retried_from_scratch_after_a_dropped_link(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "0")
    head, answers, sent = _git(repo, "rev-parse", "HEAD"), [255, 255, 0], []
    monkeypatch.setattr(rp.time, "sleep", lambda s: None)
    monkeypatch.setattr(rp, "remote", lambda host, script, *a, input=None, **kw: sent.append(input) or
                        subprocess.CompletedProcess([], answers.pop(0), b"", b""))
    rp.ship(repo, "h", head, "run1")
    assert len(sent) == 3 and sent[0] == sent[2]  # the whole bundle again each time
    answers[:] = [255, 255, 255]
    with pytest.raises(SystemExit, match="exit 255"):
        rp.ship(repo, "h", head, "run2")
    # A second attempt can add it again, even over a half-made (locked "initializing") worktree.
    assert 'git worktree remove -f -f "$R/runs/$NAME"' in rp.SHIP and rp.remote_job.SWEEP in rp.SHIP


def _job_env(tmp_path, python_body):
    """A fake host home: run dir, venv whose python runs python_body, systemd-run that just execs."""
    home = tmp_path / "home"
    (home / "rosy-test" / "runs" / "r").mkdir(parents=True)
    venv = home / "rosy-test" / "venvs" / "d"
    (venv / "bin").mkdir(parents=True)
    (venv / ".deps-sha").write_text("d\n")
    (venv / "bin" / "python").write_text("#!/bin/bash\n" + python_body)
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    (fakebin / "systemd-run").write_text('#!/bin/bash\nwhile [ "$1" != -- ]; do shift; done; shift; exec "$@"\n')
    for f in (venv / "bin" / "python", fakebin / "systemd-run"):
        f.chmod(0o755)
    return home, {"HOME": str(home), "PATH": f"{fakebin}:/usr/bin:/bin"}


def _sh(script, env, *args):
    return subprocess.run(["bash", "-c", script, "remote", *args], env=env, capture_output=True, timeout=20)


def _wait_for_lock(lock):
    for _ in range(50):  # START has returned; the job runs on without it
        if lock.exists() and lock.read_text().strip():
            return int(lock.read_text().split()[0])
        time.sleep(0.1)
    pytest.fail("job never wrote its lock")


def _skip_unreaped(pid):
    # A CI container's PID 1 (`tail -f /dev/null`) never reaps orphans, so the ended job stays a
    # zombie that `kill -0` reports alive. Lab hosts run systemd, which reaps it.
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except OSError:
        return
    if state == "Z":
        pytest.skip("PID 1 does not reap orphaned jobs here (CI container); covered on the lab hosts")


def _poll_until_done(env, k="0"):
    for _ in range(100):
        code, _, _ = rj.parse_poll(_sh(rj.POLL, env, "r", k, "0").stdout)
        if code is not None:
            return code
        time.sleep(0.1)
    pytest.fail("job never wrote its exit code")


def test_detached_job_holds_its_own_lock_and_writes_the_code_atomically(tmp_path):
    if not shutil.which("setsid") or sys.platform == "win32":
        pytest.skip("Linux setsid/timeout/ionice are required")
    # $4 is the basetemp: leave a read-only dir in it, as release/rollback tests do
    home, env = _job_env(tmp_path, 'echo out; echo err >&2; mkdir "$4/ro"; touch "$4/ro/f"; chmod 555 "$4/ro"\n'
                                   'sleep 2; echo "args $* mode $(stat -c %a "$4")"; exit 3\n')
    start = _sh(rj.START, env, "r", "d", "", "0", "60", rj.JOB, "test/x.py", "-q")
    assert start.returncode == 0, start.stderr
    lock, jobs = home / "rosy-jobs" / "r.lock", home / "rosy-test" / "runs" / "r.jobs"
    pid = _wait_for_lock(lock)
    assert lock.read_text().split()[1:] == ["pytest", "2", "6"]
    assert os.getpgid(pid) == pid  # KILL's process-group target
    assert _sh(rj.START, env, "r", "d", "", "0", "60", rj.JOB).returncode == 0  # a retried start: no second job
    assert _poll_until_done(env) == 3
    assert not lock.exists() and not (jobs / "0.rc.tmp").exists() and (jobs / "0.rc").read_text() == "3\n"
    out = (jobs / "0.log").read_bytes()
    # a short private tmp_path root per job (not /tmp/pytest-of-<user>), gone with the job despite read-only dirs
    base = re.search(rb"args -m pytest --basetemp (/tmp/rosy-pytest-\w{6})/p test/x.py -q mode 700$", out, re.M)  # leak lines may follow
    env_line, rest = out.split(b"\n", 1)
    assert re.fullmatch(rb"\[remote-pytest\] env d freeze [0-9a-f]{16}", env_line) and rest.startswith(b"out\nerr\n")
    assert base and not Path(base.group(1).decode()).exists()
    _skip_unreaped(pid)
    n = out.index(b"err")  # an offset just after "out\n"
    assert rj.parse_poll(_sh(rj.POLL, env, "r", "0", str(n)).stdout) == (3, False, out[n:])


def test_job_tmpdir_is_private_and_what_it_leaks_into_tmp_is_listed_without_changing_the_code(tmp_path):
    if not shutil.which("setsid") or sys.platform == "win32":
        pytest.skip("Linux setsid/timeout/ionice are required")
    tag = f"rosy-leak-probe-{os.getpid()}-{time.monotonic_ns()}"
    home, env = _job_env(tmp_path, 'echo "tmp $TMPDIR $TEMP $TMP"; touch "$TMPDIR/inside"\n'
                                   'for i in $(seq 25); do mkdir "/tmp/$TAG-$i"; done; exit 5\n')
    try:
        assert _sh(rj.START, {**env, "TAG": tag}, "r", "d", "", "0", "60", rj.JOB, "x.py").returncode == 0
        assert _poll_until_done(env) == 5  # a warning, never the exit code
        out = (home / "rosy-test" / "runs" / "r.jobs" / "0.log").read_text()
        tmp = re.search(r"^tmp (/tmp/rosy-pytest-\w{6}/t) (\S+) (\S+)$", out, re.M)
        assert tmp and tmp.group(1) == tmp.group(2) == tmp.group(3)  # beside the basetemp $B/p, removed with it
        leaked = re.findall(r"^\[remote-pytest\] leaked into /tmp: (\S+)$", out, re.M)
        assert len(leaked) == 20 and not [p for p in leaked if "rosy-pytest-" in p]  # capped; never its own dir
        assert [p for p in leaked if p.startswith(f"/tmp/{tag}-")]  # other host users' entries may share the list
    finally:
        for p in Path("/tmp").glob(f"{tag}-*"):
            p.rmdir()


def test_job_logs_a_fingerprint_of_what_the_venv_actually_installed(tmp_path):
    if not shutil.which("setsid") or sys.platform == "win32":
        pytest.skip("Linux setsid/timeout/ionice are required")
    home, env = _job_env(tmp_path, "exit 0\n")
    site = home / "rosy-test" / "venvs" / "d" / "lib" / "python3.12" / "site-packages"
    seen = set()
    for k, version in enumerate(("1.0", "1.1")):  # same deps hash, a different unpinned pick
        dist = site / f"jsonschema-{version}.dist-info"
        dist.mkdir(parents=True)
        assert _sh(rj.START, env, "r", "d", "", str(k), "60", rj.JOB, "x.py").returncode == 0
        assert _poll_until_done(env, str(k)) == 0
        log = (home / "rosy-test" / "runs" / "r.jobs" / f"{k}.log").read_text()
        freeze = hashlib.sha256(f"lib/python3.12/site-packages/{dist.name}\n".encode()).hexdigest()[:16]
        assert f"[remote-pytest] env d freeze {freeze}\n" in log
        seen.add(freeze)
        dist.rmdir()
    assert len(seen) == 2


def test_kill_stops_the_detached_job_and_its_trap_still_runs(tmp_path):
    if not shutil.which("setsid") or sys.platform == "win32":
        pytest.skip("Linux setsid/timeout/ionice are required")
    home, env = _job_env(tmp_path, "sleep 30\n")
    # Completion must imply cleanup even while the publishing command is still returning.
    move = tmp_path / "bin" / "mv"
    move.write_text('#!/bin/bash\n/bin/mv "$@" || exit $?\n'
                    'while [ ! -e "$HOME/release" ]; do sleep 0.01; done\n')
    move.chmod(0o755)
    try:
        assert _sh(rj.START, env, "r", "d", "", "0", "60", rj.JOB).returncode == 0
        lock = home / "rosy-jobs" / "r.lock"
        _wait_for_lock(lock)
        _sh(rj.KILL, env, "r")
        assert _poll_until_done(env) == 143 and not lock.exists()
    finally:
        (home / "release").touch()


def test_ctrl_c_during_the_start_backoff_still_kills_the_job(tmp_path):
    scripts = []

    def call(ssh, host, script, *args):
        scripts.append(script)
        return None  # START's link drops; it may or may not have launched the job

    def interrupt(seconds):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        rj.run("h", "r", 0, tmp_path / "1.txt", ["r", "d", ""], [], 60, [], call=call, sleep=interrupt)
    assert scripts == [rj.START, rj.KILL]


class VanishingHost(FakeJobHost):
    """Polls answer, but the job's pid is gone and it never wrote an exit code."""

    def __init__(self, alive):
        super().__init__([b"half a log\n"] + [b""] * 9, 0)
        self.alive = list(alive)

    def __call__(self, ssh, host, script, *args):
        result = super().__call__(ssh, host, script, *args)
        if script == rj.POLL:
            flag = b"1" if self.alive.pop(0) else b"0"
            result.stdout = result.stdout.replace(b"ROSYJOB - 1", b"ROSYJOB - " + flag)
        return result


def test_a_job_that_dies_without_an_exit_code_is_reported_after_two_polls(tmp_path):
    fake = VanishingHost([True, False, True, False, False, True])  # a single miss is the launch/trap window
    now, sleep, clock = _clock()
    log = tmp_path / "1.txt"
    code = rj.run("h", "r", 0, log, ["r", "d", ""], [], 5400, [], call=fake, sleep=sleep, clock=clock)
    assert code == rj.VANISHED_EXIT and code not in (0, 1, rj.LOST_EXIT)  # land.py stops on it
    assert fake.polls == 5 and now[0] < 60  # not the 92-minute timeout
    text = log.read_bytes()
    assert text.startswith(b"half a log\n") and b"ended without an exit code" in text


def test_killed_job_shows_no_live_pid_and_no_code_and_start_does_not_rerun_a_finished_job(tmp_path):
    if not shutil.which("setsid") or sys.platform == "win32":
        pytest.skip("Linux setsid/timeout/ionice are required")
    home, env = _job_env(tmp_path, "sleep 30\n")
    assert _sh(rj.START, env, "r", "d", "", "0", "60", rj.JOB).returncode == 0
    pid = _wait_for_lock(home / "rosy-jobs" / "r.lock")
    assert rj.parse_poll(_sh(rj.POLL, env, "r", "0", "0").stdout)[:2] == (None, True)
    os.killpg(pid, 9)  # host reboot / OOM kill: no trap, no exit code
    for _ in range(50):
        if rj.parse_poll(_sh(rj.POLL, env, "r", "0", "0").stdout)[:2] == (None, False):
            break
        time.sleep(0.1)
    else:
        _skip_unreaped(pid)
        pytest.fail("POLL still reports the SIGKILLed job alive")
    jobs = home / "rosy-test" / "runs" / "r.jobs"
    (jobs / "0.rc").write_text("0\n")
    (jobs / "0.log").write_bytes(b"done\n")
    assert _sh(rj.START, env, "r", "d", "", "0", "60", rj.JOB).returncode == 0
    time.sleep(0.5)
    assert (jobs / "0.log").read_bytes() == b"done\n"  # an existing exit code: nothing started


def _read_only_tree(path):
    """A dir without u+w holding a file, as release/rollback tests leave (rm -rf alone cannot empty it)."""
    path.mkdir(parents=True)
    (path / "f").write_text("x")
    path.chmod(0o555)


def test_run_cleanup_removes_read_only_dirs_first(tmp_path):
    """2026-10-26: read-only dirs kept runs/ (37 GB) and pytest garbage-* dirs from ever being deleted."""
    ship = rp.SHIP.index('chmod -R u+rwX -- "$R/runs/$NAME"')
    assert ship < rp.SHIP.index('git worktree remove -f -f "$R/runs/$NAME"')  # a retried ship
    if not shutil.which("bash") or sys.platform == "win32" or os.geteuid() == 0:
        pytest.skip("POSIX bash as a non-root user is required")
    home = tmp_path / "home"
    runs = home / "rosy-test" / "runs"
    _read_only_tree(runs / "r" / "store")
    _read_only_tree(runs / "r.jobs" / "0.tmp" / "store")
    subprocess.run(["bash", "-c", rp.CLEANUP, "remote", "r"], env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
                   capture_output=True, timeout=30)
    assert not (runs / "r").exists() and not (runs / "r.jobs").exists()


def test_sweep_removes_only_old_finished_runs_of_this_runner(tmp_path):
    if not shutil.which("bash") or sys.platform == "win32":
        pytest.skip("POSIX bash is required")
    home = tmp_path / "home"
    root, jobs = home / "rosy-test", home / "rosy-jobs"
    repo, runs = root / "repo", root / "runs"
    jobs.mkdir(parents=True)
    runs.mkdir(parents=True)
    _git(tmp_path, "init", "-q", "-b", "main", str(repo))
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "0")
    live = subprocess.Popen(["sleep", "30"])
    old = time.time() - 3 * 3600  # past the 2 h sweep age (was 12 h: a full disk kept them)
    names = {"land-1-a1b2c3": "old", "land-2-d4e5f6": "live", "abcdef0123-0a0b0c": "fresh",
             "land-3-0f0f0f": "running", "sim-0123456789-abcdef": "sim", "other": "other"}
    try:
        for name, kind in names.items():
            _git(repo, "worktree", "add", "-q", "--detach", str(runs / name), "HEAD")
            _git(repo, "update-ref", f"refs/remote-pytest/{name}", "HEAD")
            j = runs / f"{name}.jobs"
            j.mkdir()
            if kind != "running":
                (j / "0.rc").write_text("1\n")
            (j / "0.pid").write_text(f"{live.pid if kind in ('live', 'running') else 999999999}\n")
            if kind == "old":  # read-only dirs from release tests, in the checkout and in the job dir
                _read_only_tree(runs / name / "store")
                _read_only_tree(j / "0.tmp" / "store")
            if kind != "fresh":
                os.utime(j, (old, old))
        (runs / "land-2-d4e5f6.jobs" / "0.pid").write_text("999999999\n")
        (jobs / "land-2-d4e5f6.lock").write_text(f"{live.pid} pytest 2 6\n")  # a later invocation runs
        script = (f"set -euo pipefail; R={shlex.quote(str(root))}; cd \"$R/repo\"\n" + rp.remote_job.SWEEP
                  + "git worktree prune\n")
        subprocess.run(["bash", "-c", script], env={"HOME": str(home), "PATH": "/usr/bin:/bin"}, check=True,
                       capture_output=True, timeout=30)
    finally:
        live.kill()
    gone = {n for n in names if not (runs / n).exists()}
    assert gone == {"land-1-a1b2c3"} and not (runs / "land-1-a1b2c3.jobs").exists()
    assert "land-1-a1b2c3" not in _git(repo, "worktree", "list")
    refs = _git(repo, "for-each-ref", "--format=%(refname)", "refs/remote-pytest")
    assert "land-1-a1b2c3" not in refs and "refs/remote-pytest/other" in refs


@pytest.mark.parametrize("listed,rerun_out,rerun_code,code", [
    (True, "PASSED test/q.py::test_f\n", 0, 0),                    # listed, passes once more -> green
    (True, "FAILED test/q.py::test_f - again\n", 1, 1),            # listed, fails twice -> still red
    (True, "PASSED test/q.py::test_f\nERROR test/q.py::test_f - teardown\n", 1, 1),  # teardown error
    (True, None, None, 1),                                          # rerun lost -> red, no crash
    (False, None, None, 1),                                         # unlisted -> never rerun
])
def test_run_on_reruns_only_quarantined_failures_once(tmp_path, monkeypatch, listed, rerun_out, rerun_code, code):
    """D-762 stage 1: one rerun of listed ids, appended after the marker known_failures.py reads."""
    monkeypatch.setattr(rp, "ship", lambda *a, **kw: None)
    monkeypatch.setattr(rp, "deps", lambda repo, sha: ("d" * 16, []))
    monkeypatch.setattr(rp, "remote", lambda *a, **kw: subprocess.CompletedProcess([], 0, b"", b""))
    monkeypatch.setattr(rp, "quarantine", lambda repo, sha: {"test/q.py::test_f": "r"} if listed else {})
    calls = []

    def job(host, name, k, log, job_args, inv, *a):
        calls.append((k, inv))
        if k == 0:
            log.write_bytes(b"FAILED test/q.py::test_f - boom\n1 failed\n")
            return 1
        if rerun_out is None:
            raise rj.Lost("lost contact with h")  # before the rerun log exists
        log.write_bytes(rerun_out.encode())
        return rerun_code

    monkeypatch.setattr(rp.remote_job, "run", job)
    log = tmp_path / "run-1.txt"
    assert rp.run_on("h", [["test/q.py"]], [log], "ab" * 20, tmp_path, None) == [code]
    if not listed:
        assert len(calls) == 1
        return
    assert calls[1] == ("0r", ["test/q.py::test_f", "-q", "-rA", "-p", "no:cacheprovider"])
    assert len(calls) == 2
    text = log.read_text(encoding="utf-8")
    assert rp.known_failures.RERUN_MARKER in text
    assert text.endswith(rerun_out or "rerun lost\n")


@pytest.mark.parametrize("words,install", [([rp.BROWSER_ENV], True), ([], False)])
def test_leading_rosy_words_are_the_job_environment_and_browser_jobs_get_chromium(tmp_path, words, install):
    if not shutil.which("setsid") or sys.platform == "win32":
        pytest.skip("Linux setsid/timeout/ionice are required")
    home, env = _job_env(tmp_path, '[ "$2" = playwright ] && echo "$*" > "$HOME/installed"\n'
                                   'echo "browser=${ROSY_RUN_BROWSER_TESTS:-} args $*"\n')
    start = _sh(rj.START, env, "r", "d", "", "0", "60", rj.JOB, *words, "test/x_browser.py", "-q")
    assert start.returncode == 0, start.stderr
    assert _poll_until_done(env) == 0
    out = (home / "rosy-test" / "runs" / "r.jobs" / "0.log").read_text()
    assert re.search(f"browser={'1' if install else ''} args -m pytest --basetemp /tmp/rosy-pytest-\\w{{6}}/p test/x_browser.py -q$",
                     out, re.M)  # leak lines may follow
    installed = home / "installed"
    assert installed.exists() == install
    assert not install or installed.read_text() == "-m playwright install chromium\n"
    assert rp.ENV_ARG.match(rp.BROWSER_ENV) and not rp.ENV_ARG.match("PATH=/x") and not rp.ENV_ARG.match("-k=x")


def test_browser_reruns_keep_the_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(rp, "ship", lambda *a, **kw: None)
    monkeypatch.setattr(rp, "deps", lambda repo, sha: ("d" * 16, []))
    monkeypatch.setattr(rp, "remote", lambda *a, **kw: subprocess.CompletedProcess([], 0, b"", b""))
    monkeypatch.setattr(rp, "quarantine", lambda repo, sha: {"test/q_browser.py::test_f": "r"})
    calls = []

    def job(host, name, k, log, job_args, inv, *a):
        calls.append(inv)
        log.write_bytes(b"FAILED test/q_browser.py::test_f - boom\n" if k == 0
                        else b"PASSED test/q_browser.py::test_f\n")
        return 1 if k == 0 else 0

    monkeypatch.setattr(rp.remote_job, "run", job)
    inv = [rp.BROWSER_ENV, "test/q_browser.py"]
    assert rp.run_on("h", [inv], [tmp_path / "1.txt"], "ab" * 20, tmp_path, None) == [0]
    assert calls[0][:2] == inv and calls[1][:2] == [rp.BROWSER_ENV, "test/q_browser.py::test_f"]


LISTING = ("ID    Tailnet                 Account\n"
           "665e  team@example.com        team@example.com*\n"
           "bc4d  other@example.com       other@example.com\n")


def test_tailscale_current_profile_is_the_starred_row():
    assert rp.current_profile(LISTING) == ["665e", "team@example.com", "team@example.com"]
    assert rp.current_profile(LISTING.replace("*", "")) == []


def test_tailscale_profile_mismatch_fails_fast_naming_both(monkeypatch):
    monkeypatch.delenv("ROSY_TEST_HOSTS", raising=False)
    listing = subprocess.CompletedProcess([], 0, LISTING, "")
    with pytest.raises(SystemExit) as error:
        rp.check_tailscale_profile("bc4d", which=lambda _: "tailscale", run=lambda *a, **k: listing)
    assert "current 665e" in str(error.value) and "tailscale switch bc4d" in str(error.value)
    rp.check_tailscale_profile("665e", which=lambda _: "tailscale", run=lambda *a, **k: listing)  # match: passes


def test_tailscale_profile_check_skipped_without_cli_or_key_or_with_explicit_hosts(monkeypatch):
    def never(*a, **k):
        raise AssertionError("tailscale must not be called")

    rp.check_tailscale_profile("bc4d", which=lambda _: None, run=never)   # no CLI
    rp.check_tailscale_profile("", which=lambda _: "tailscale", run=never)  # no lab-hosts.json key
    monkeypatch.setenv("ROSY_TEST_HOSTS", "user@host")
    rp.check_tailscale_profile("bc4d", which=lambda _: "tailscale", run=never)  # manual host override


# --- pytest-xdist on the test hosts (xdist_plan.py) and light hosts below the memory floor ---

GROUP = ["middleware/core/gateway/test", "middleware/core/events/test", "middleware/core/services/test",
         "shared/web/test", "contracts/foundation/test", "middleware/devices/pinky/profile/test",
         "middleware/devices/omx/profile/test"]  # the 7,151-test group measured at 722 s serial


def test_a_host_under_the_memory_floor_is_light_ranked_after_full_hosts_and_before_the_site_pc(monkeypatch):
    monkeypatch.setattr(rp, "SITES", {"site@lab"})
    hosts = ["ai@2", "model@1", "site@lab", "tiny@4"]
    probes = [host(nproc=18, avail_gb=5), host(), host(nproc=8, load1=0.2, avail_gb=13), host(avail_gb=3.5)]
    chosen, notes = rp.place("pytest", hosts, probes)
    assert chosen == ["model@1", "ai@2"]  # the site PC stays out while any other host fits
    assert "light" in notes[0] and notes[1].endswith("ok") and "below pytest floor 2 cores/4 GB" in notes[3]
    assert rp.HEADROOM["ai@2"]["light"] and not rp.HEADROOM["model@1"]["light"]
    assert rp.place("pytest", hosts[2:3], probes[2:3])[0] == ["site@lab"]  # alone: last resort as before
    # Sim keeps its own floor; there is no light sim host.
    assert rp.place("sim", ["ai@2"], [{**probes[0], "sim": True, "avail_gb": 7}])[0] == []


def test_a_light_host_takes_the_smallest_invocations_with_a_memory_cap(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(rp, "ship", lambda *a, **kw: None)
    monkeypatch.setattr(rp, "deps", lambda repo, sha: ("d" * 16, []))
    monkeypatch.setattr(rp, "remote", lambda *a, **kw: subprocess.CompletedProcess([], 0, b"", b""))
    monkeypatch.setattr(rp.remote_job, "run", lambda h, name, k, log, job, inv, *a:
                        seen.append(inv) or log.write_bytes(b"") and 0)
    rp.HEADROOM["ai@2"] = {"cores": 18, "mem": 5.4, "site": False, "light": True}
    work = rp.Work([0, 1, 2])  # largest first
    work.todo.popleft()  # a full host took the largest
    rp.run_on("ai@2", [["big"], ["mid"], ["small"]], [tmp_path / f"{i}.txt" for i in range(3)],
              "ab" * 20, tmp_path, None, work)
    assert [inv[1] for inv in seen] == ["small", "mid"]
    assert all(inv[0] == "ROSY_JOB_MEM_GB=5" and "-n" not in inv for inv in seen)
    assert work.take_small() is None and work.take() is None


def test_worker_count_follows_free_cores_memory_the_job_cap_and_the_site_quota(monkeypatch):
    assert xp.workers(14.5, 11.0, False) == xp.MAX_WORKERS == 6  # MemoryMax 6 GB / 1 GB a worker
    assert xp.workers(3.9, 11.0, False) == 3
    assert xp.workers(16, 2.5, False) == 2
    assert xp.workers(1.5, 11.0, False) == 1  # one worker is serial
    assert xp.workers(10, 10, True) == 4  # CPUQuota 400%
    monkeypatch.setenv("ROSY_TEST_WORKERS", "12")
    assert xp.workers(2, 2, False) == 12  # measurement override
    monkeypatch.setenv("ROSY_TEST_WORKERS", "0")
    assert xp.workers(16, 12, False) == 1
    monkeypatch.setenv("ROSY_TEST_WORKERS", "auto")
    with pytest.raises(SystemExit, match="whole number"):
        xp.workers(16, 12, False)


@pytest.mark.parametrize("inv, why", [
    (GROUP, None),
    (["shared/web/test/", ".\\contracts\\foundation\\test", "-k", "not slow"], None),
    (["test/test_land.py"], "test is in serial_suites.txt"),
    (["middleware/core/gateway/test", "middleware/perception/test"], "middleware/perception is in"),
    (["middleware"], "is in serial_suites.txt"),  # a parent of a serial suite
    (["."], "is in serial_suites.txt"),
    (["middleware/core/gateway/test/test_api.py::test_x"], "node ids"),
    ([rp.BROWSER_ENV, "shared/web/test"], "browser job"),
    (["shared/web/test", "-n", "2"], "sets xdist itself"),
    (["shared/web/test", "-pno:xdist"], "sets xdist itself"),
    (["-q"], "no path named"),
])
def test_serial_list_and_rules_keep_hazardous_invocations_serial(inv, why):
    serial = xp.load_serial(xp.SERIAL_FILE.read_text(encoding="utf-8"))
    reason = xp.serial_reason(inv, serial)
    assert reason is None if why is None else why in reason


def test_serial_list_parses_comments_and_names_real_paths():
    assert xp.load_serial("# head\n\ntest  # why\n middleware\\perception/ \n") == ["test", "middleware/perception"]
    serial = xp.load_serial(xp.SERIAL_FILE.read_text(encoding="utf-8"))
    assert "test" in serial and "operations/fleet/test" in serial
    assert all((ROOT / prefix).exists() for prefix in serial), "a stale line keeps nothing serial"


def test_plan_gives_xdist_words_and_args_only_to_safe_invocations_on_full_hosts():
    full = {"cores": 14.0, "mem": 10.0, "site": False, "light": False}
    words, extra, note = xp.plan(GROUP, full, [])
    assert (words, extra, note) == (["ROSY_JOB_CORES=6"], ["-n", "6", "--dist", "loadfile"], "xdist: 6 workers")
    assert xp.plan(["test"], full, ["test"])[:2] == ([], [])
    assert xp.plan(GROUP, None, [])[:2] == ([], [])  # D-568 7 fallback host: unmeasured, serial
    assert xp.plan(GROUP, {**full, "light": True, "mem": 4.7}, [])[:2] == (["ROSY_JOB_MEM_GB=4"], [])


def test_run_on_adds_xdist_to_the_run_but_never_to_the_quarantine_rerun(tmp_path, monkeypatch):
    monkeypatch.setattr(rp, "ship", lambda *a, **kw: None)
    monkeypatch.setattr(rp, "deps", lambda repo, sha: ("d" * 16, []))
    monkeypatch.setattr(rp, "remote", lambda *a, **kw: subprocess.CompletedProcess([], 0, b"", b""))
    monkeypatch.setattr(rp, "quarantine", lambda repo, sha: {"shared/web/test/test_q.py::test_f": "r"})
    rp.HEADROOM["h"] = {"cores": 14.0, "mem": 10.0, "site": False, "light": False}
    calls = []

    def job(host, name, k, log, job_args, inv, *a):
        calls.append(inv)
        log.write_bytes(b"[gw2] [ 50%] FAILED shared/web/test/test_q.py::test_f \n"
                        b"FAILED shared/web/test/test_q.py::test_f - boom\n" if k == 0
                        else b"PASSED shared/web/test/test_q.py::test_f\n")
        return 1 if k == 0 else 0

    monkeypatch.setattr(rp.remote_job, "run", job)
    assert rp.run_on("h", [["shared/web/test"]], [tmp_path / "1.txt"], "ab" * 20, tmp_path, None) == [0]
    assert calls[0][:6] == ["ROSY_JOB_CORES=6", "shared/web/test", "-n", "6", "--dist", "loadfile"]
    assert calls[0][6:] == rp.PYTEST_TAIL
    assert calls[1][:2] == ["ROSY_JOB_CORES=6", "shared/web/test/test_q.py::test_f"] and "-n" not in calls[1]


def test_venv_installs_pinned_xdist_so_its_hash_rebuilds_the_venv():
    assert "pytest-xdist==3.8.0" in rp.VENV.split("UV=", 1)[1].split('echo "$DEPS"', 1)[0]


@pytest.mark.parametrize("words, lock, mem", [([], "2 6", "6G"), (["ROSY_JOB_CORES=6"], "6 6", "6G"),
                                              (["ROSY_JOB_MEM_GB=4"], "2 4", "4G")])
def test_job_records_its_xdist_budget_in_the_lock_and_caps_memory(tmp_path, words, lock, mem):
    if not shutil.which("setsid") or sys.platform == "win32":
        pytest.skip("Linux setsid/timeout/ionice are required")
    home, env = _job_env(tmp_path, 'cat "$HOME/rosy-jobs/r.lock"\n')
    (tmp_path / "bin" / "systemd-run").write_text(
        '#!/bin/bash\necho "$*" > "$HOME/scope"\nwhile [ "$1" != -- ]; do shift; done; shift; exec "$@"\n')
    start = _sh(rj.START, env, "r", "d", "", "0", "60", rj.JOB, *words, "x.py")
    assert start.returncode == 0, start.stderr
    assert _poll_until_done(env) == 0
    out = (home / "rosy-test" / "runs" / "r.jobs" / "0.log").read_text()
    assert out.splitlines()[1].split()[1:] == ["pytest", *lock.split()]  # after the env line
    assert f"MemoryMax={mem}" in (home / "scope").read_text()
    bad = _sh(rj.START, env, "r", "d", "", "1", "60", rj.JOB, "ROSY_JOB_CORES=$(id)", "x.py")
    assert bad.returncode == 0 and _poll_until_done(env, "1") == 2
