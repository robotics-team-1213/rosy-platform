"""A host selected before its reboot window must refuse later jobs of the same batch."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/remote"))
import remote_job as rj
import remote_pytest as rp
from test_remote_pytest import _fake_hosts, _job_env, _sh, host

JOB_RUN = rj.run
DEFERRED = b"[remote-pytest] admission deferred: nightly reboot\n"


def defer(log):
    def call(ssh, hostname, script, *args):
        data = b"" if script == rj.START else b"ROSYJOB 253 0\n" + DEFERRED
        return subprocess.CompletedProcess([], 0, data, b"")
    return JOB_RUN("fixture", "r", 0, log, ["r", "d", ""], [], 5400, [], call=call)


@pytest.mark.skipif(os.name != "posix" or not shutil.which("flock"), reason="actual admission shell needs Linux")
@pytest.mark.parametrize("words", [[], ["ROSY_JOB_TURN=1"], ["ROSY_JOB_ALONE=1"]])
@pytest.mark.parametrize("delta,active,blocked", [(779, False, True), (780, False, False),
                                                (-60, False, False), (None, True, True), (None, False, False)])
def test_each_job_reuses_the_probe_cutoff_before_any_priority_or_resource_admission(tmp_path, words, delta, active, blocked):
    home, env = _job_env(tmp_path, 'touch "$HOME/pytest-started"\n')
    (home / "rosy-test/runs/r.jobs").mkdir()
    (home / "rosy-jobs").mkdir()
    when = "echo" if delta is None else f"/usr/bin/date -d @{10000 + delta} '+%a %Y-%m-%d %H:%M:%S %Z'"
    prefix = ('date() { if [ "$1" = +%s ]; then echo 10000; else /usr/bin/date "$@"; fi; }\n'
              # the reboot unit is a oneshot: "activating" with exit 3 through its whole warning, as it answers on the PCs
              f'systemctl() {{ case "$1" in show) {when};; is-active) echo {"activating" if active else "inactive"}; return 3;; esac; }}\n')
    result = _sh(prefix + rj.JOB, env, "r", "d", "", "0", "60", *words, "x.py")
    assert result.returncode == (253 if blocked else 0), result.stderr
    assert (home / "pytest-started").exists() is not blocked
    assert not list((home / "rosy-jobs").glob("*.lock"))
    if blocked:
        assert DEFERRED in result.stdout


@pytest.mark.skipif(os.name != "posix" or not shutil.which("flock"), reason="actual admission shell needs Linux")
@pytest.mark.parametrize("words", [[], ["ROSY_JOB_TURN=1"], ["ROSY_JOB_ALONE=1"]])
def test_waiting_for_room_rechecks_reboot_before_starting_pytest(tmp_path, words):
    home, env = _job_env(tmp_path, 'touch "$HOME/pytest-started"\n')
    (home / "rosy-test/runs/r.jobs").mkdir()
    prefix = '''clock=10000
date() { if [ "$1" = +%s ]; then echo "$clock"; else /usr/bin/date "$@"; fi; }
systemctl() { case "$1" in show) /usr/bin/date -d @10800 '+%a %Y-%m-%d %H:%M:%S %Z';; is-active) echo inactive; return 3;; esac; }
sleep() { clock=10030; }
mkdir -p "$HOME/rosy-jobs"
echo "$$ alone 2 6" > "$HOME/rosy-jobs/foreign.lock"
'''
    result = _sh(prefix + rj.JOB, env, "r", "d", "", "0", "60", *words, "x.py")
    assert result.returncode == 253, result.stderr
    assert not (home / "pytest-started").exists()
    assert (home / "rosy-jobs/foreign.lock").exists()
    assert not list((home / "rosy-jobs").glob("*.alone-wait"))


def test_later_job_of_a_single_worker_batch_moves_without_republishing_completed_results(tmp_path, monkeypatch):
    blocked, completed = [False], []

    def job(h, path, stop=None):
        if h == "a" and path == "second":
            blocked[0] = True
            return defer(tmp_path / "deferred")
        return 0

    seen = _fake_hosts(monkeypatch, tmp_path, ["a", "b"], job)
    monkeypatch.setattr(rp, "probe", lambda h: host() if (h == "a") != blocked[0] else None)
    args = [["first"], ["second"]]
    assert rp.run(args, [tmp_path / "first", tmp_path / "second"], repo=tmp_path,
                  on_done=lambda inv, log: completed.append(inv) or False) == [0, 0]
    assert seen == [("a", "first"), ("a", "second"), ("b", "second")]
    assert completed == args


@pytest.mark.parametrize("outcome", ["recover", "timeout", "stop"])
def test_all_hosts_blocked_keeps_the_original_wait_deadline_and_stop(tmp_path, monkeypatch, outcome):
    now, blocked, stop, completed = [0], [False], threading.Event(), []

    def job(h, path, stop=None):
        if not blocked[0]:
            blocked[0] = True
            return defer(tmp_path / "deferred")
        return 0

    seen = _fake_hosts(monkeypatch, tmp_path, ["a"], job)
    monkeypatch.setattr(rp, "probe", lambda h: host() if not blocked[0] or outcome == "recover" and now[0] >= 20 else None)

    def sleep(seconds):
        now[0] += seconds
        if outcome == "stop":
            stop.set()

    def run():
        return rp.run([["x"]], [tmp_path / "x"], repo=tmp_path, wait=25, poll=10,
                      clock=lambda: now[0], sleep=sleep, stop=stop,
                      on_done=lambda inv, log: completed.append(inv) or False)

    if outcome == "timeout":
        with pytest.raises(SystemExit, match="no test host"):
            run()
        assert now == [20] and completed == [] and seen == [("a", "x")]
    else:
        assert run() == ([0] if outcome == "recover" else [rp.CANCELLED])
        assert completed == ([["x"]] if outcome == "recover" else [])
        assert len(seen) == (2 if outcome == "recover" else 1)


@pytest.mark.parametrize("rerun_passes", [True, False])
def test_quarantine_deferral_moves_only_the_remaining_rerun_and_keeps_original_failure(tmp_path, monkeypatch, rerun_passes):
    blocked, calls, completed = [False], [], []
    node = "x.py::test_bad"
    original = f"FAILED {node} - original failure\n".encode()
    _fake_hosts(monkeypatch, tmp_path, ["a", "b"], lambda *a: 0)
    monkeypatch.setattr(rp, "probe", lambda h: host() if (h == "a") != blocked[0] else None)
    monkeypatch.setattr(rp, "quarantine", lambda *a: {node: "known flaky"})

    def job(h, name, k, log, job_args, inv, *args, **kw):
        is_rerun = str(k).endswith("r")
        calls.append((h, is_rerun))
        if not is_rerun:
            assert h == "a", "the original invocation must never rerun on the replacement host"
            log.write_bytes(original)
            return 1
        if h == "a":
            blocked[0] = True
            return defer(log)
        assert node in inv and "-n" not in inv
        log.write_text(f"{'PASSED' if rerun_passes else 'FAILED'} {node}\n")
        return 0 if rerun_passes else 1

    monkeypatch.setattr(rj, "run", job)
    log = tmp_path / "run.txt"
    assert rp.run([["x.py"]], [log], repo=tmp_path,
                  on_done=lambda inv, log: completed.append(inv) or False) == [0 if rerun_passes else 1]
    assert log.read_bytes().startswith(original)
    assert log.read_text().count(rp.known_failures.RERUN_MARKER) == 1
    assert calls == [("a", False), ("a", True), ("b", True)]
    assert completed == [["x.py"]]


@pytest.mark.skipif(os.name != "posix" or not shutil.which("flock"), reason="actual admission shell needs Linux")
def test_an_alone_job_behind_a_gpu_hold_never_blocks_others_and_gives_its_invocation_back(tmp_path):
    """11-09: an alone waiter behind a multi-hour training lock kept every pytest off the AI PC for ~4 h."""
    home, env = _job_env(tmp_path, 'touch "$HOME/pytest-started"\n')
    (home / "rosy-test/runs/r.jobs").mkdir()
    line = 'echo "$$ gpu 1 1" > "$HOME/rosy-jobs/train-1.lock"'  # hold_gpu.sh's lock (an Isaac .resv admits)
    prefix = '''clock=10000
date() { if [ "$1" = +%s ]; then echo "$clock"; else /usr/bin/date "$@"; fi; }
systemctl() { case "$1" in show) echo;; is-active) echo inactive; return 3;; esac; }
sleep() { [ -e "$HOME/rosy-jobs/$$.alone-wait" ] && touch "$HOME/marked"; clock=$((clock + 100)); }
mkdir -p "$HOME/rosy-jobs"
''' + line + "\n"
    result = _sh(prefix + rj.JOB, env, "r", "d", "", "0", "60", "ROSY_JOB_ALONE=1", "x.py")
    assert result.returncode == 253, result.stderr
    assert rj.HOLD_DEFERRED + b"\n" in result.stdout
    assert not (home / "pytest-started").exists() and not (home / "marked").exists()
    assert not list((home / "rosy-jobs").glob("*.alone-wait"))
    result = _sh(prefix + rj.JOB, env, "r", "d", "", "0", "60", "x.py")
    assert result.returncode == 0, result.stderr  # an ordinary job still fits beside the hold


@pytest.mark.skipif(os.name != "posix" or not shutil.which("flock"), reason="actual admission shell needs Linux")
def test_cpu_alone_job_runs_beside_gpu_when_room_fits_and_defers_on_sim_or_full_host(tmp_path):
    """Dedicated CPU/fsync timing alone job runs beside gpu training when sim is absent and cpu/mem fit."""
    home, env = _job_env(tmp_path, 'touch "$HOME/pytest-started"\n')
    env = {**env, "ROSY_HOST_CORES": "24", "ROSY_HOST_GB": "32"}
    (home / "rosy-test/runs/r.jobs").mkdir()
    base = '''clock=10000
date() { if [ "$1" = +%s ]; then echo "$clock"; else /usr/bin/date "$@"; fi; }
systemctl() { case "$1" in show) echo;; is-active) echo inactive; return 3;; esac; }
sleep() { clock=$((clock + 100)); }
mkdir -p "$HOME/rosy-jobs"
'''
    # 1) gpu lock with ample headroom: CPU_ALONE runs (non_gpu == 0)
    p1 = base + 'echo "$$ gpu 8 16" > "$HOME/rosy-jobs/train-1.lock"\n'
    res = _sh(p1 + rj.JOB, env, "r", "d", "", "0", "60", "ROSY_JOB_ALONE=1", "ROSY_JOB_CPU_ALONE=1", "x.py")
    assert res.returncode == 0 and (home / "pytest-started").exists(), res.stderr
    (home / "pytest-started").unlink()
    # 2) gpu lock leaves too few cores: CPU_ALONE defers cleanly
    p2 = base + 'echo "$$ gpu 24 16" > "$HOME/rosy-jobs/train-1.lock"\n'
    res = _sh(p2 + rj.JOB, env, "r", "d", "", "1", "60", "ROSY_JOB_ALONE=1", "ROSY_JOB_CPU_ALONE=1", "x.py")
    assert res.returncode == 253 and rj.HOLD_DEFERRED + b"\n" in res.stdout
    # 3) sim lock (Gazebo): CPU_ALONE still defers
    p3 = base + 'echo "$$ sim 6 8" > "$HOME/rosy-jobs/gz-1.lock"\n'
    res = _sh(p3 + rj.JOB, env, "r", "d", "", "2", "60", "ROSY_JOB_ALONE=1", "ROSY_JOB_CPU_ALONE=1", "x.py")
    assert res.returncode == 253 and rj.HOLD_DEFERRED + b"\n" in res.stdout


    # 4) dedicated test/test_platform_g1_timing.py auto-enables CPU_ALONE in JOB without changing invocation words
    (home / "pytest-started").unlink(missing_ok=True)
    res = _sh(p1 + rj.JOB, env, "r", "d", "", "3", "60", "ROSY_JOB_ALONE=1", "test/test_platform_g1_timing.py", "-pno:xdist")
    assert res.returncode == 0 and (home / "pytest-started").exists(), res.stderr
    # 5) dedicated ROSY_BROWSER_ALONE=1 + ROSY_RUN_BROWSER_TESTS=1 auto-enables CPU_ALONE beside gpu
    (home / "pytest-started").unlink(missing_ok=True)
    res = _sh(p1 + rj.JOB, env, "r", "d", "", "4", "60", "ROSY_RUN_BROWSER_TESTS=1", "ROSY_BROWSER_ALONE=1",
              "ROSY_JOB_ALONE=1", "a/test/test_b_browser.py")
    assert res.returncode == 0 and (home / "pytest-started").exists(), res.stderr
    # 6) generic ROSY_JOB_ALONE=1 without dedicated CPU-only marker still defers beside gpu training
    (home / "pytest-started").unlink(missing_ok=True)
    res = _sh(p1 + rj.JOB, env, "r", "d", "", "5", "60", "ROSY_JOB_ALONE=1", "a/test/test_b_browser.py")
    assert res.returncode == 253 and rj.HOLD_DEFERRED + b"\n" in res.stdout
