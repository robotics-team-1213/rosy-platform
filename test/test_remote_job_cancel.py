"""remote_job: cancel_all, the atexit KILL and the host lease; land_prepare cancels the pre run when a guard fails."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import land  # noqa: E402
import remote_job as rj  # noqa: E402
from test_land import repos  # noqa: E402,F401  (land.py's fixture repos)


class Host:
    """START ok, POLL always 'running'; every KILL recorded."""

    def __init__(self):
        self.kills, self.polls = [], threading.Semaphore(0)

    def __call__(self, ssh, host, script, *args):
        if script == rj.KILL:
            self.kills.append(args)
        elif script == rj.POLL:
            self.polls.release()
            return SimpleNamespace(returncode=0, stdout=b"ROSYJOB - 1\n")
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")


@pytest.fixture(autouse=True)
def rearmed():
    rj.cancel_all(False)
    yield
    rj.cancel_all(False)
    rj._LIVE.clear()


def _start(host, tmp_path, n):
    out = [None] * n

    def one(k):
        out[k] = rj.run("h", "r", k, tmp_path / f"{k}.txt", ["r", "d", ""], [], 600, [], call=host,
                        sleep=lambda s: time.sleep(0.01))
    threads = [threading.Thread(target=one, args=(k,), daemon=True) for k in range(n)]
    for t in threads:
        t.start()
    for _ in range(n):
        assert host.polls.acquire(timeout=10)
    return threads, out


def test_cancel_all_kills_every_live_job_and_new_runs_start_nothing(tmp_path):
    host = Host()
    threads, out = _start(host, tmp_path, 3)
    assert len(rj._LIVE) == 3
    rj.cancel_all()
    for t in threads:
        t.join(10)
    assert out == [rj.CANCELLED] * 3 and sorted(k for _, k in host.kills) == ["0", "1", "2"] and not rj._LIVE
    assert rj.run("h", "r", 9, tmp_path / "9.txt", ["r", "d", ""], [], 60, [], call=host) == rj.CANCELLED
    assert len(host.kills) == 3, "a run after cancel_all never started a host job"


def test_atexit_kills_the_jobs_still_live_and_none_finished(tmp_path):
    host = Host()
    threads, out = _start(host, tmp_path, 2)
    done = Host()
    rj._LIVE["h", "r", 7] = ([], done)  # a job this process still follows when it exits
    rj._kill_live()
    assert sorted(k for _, k in host.kills) == ["0", "1"] and done.kills == [("r", "7")]
    rj.cancel_all()
    for t in threads:
        t.join(10)
    rj.cancel_all(False)  # a finished run leaves the registry: nothing is killed for it
    quick = Host()
    quick.__class__ = type("Q", (Host,), {"__call__": lambda s, ssh, h, script, *a: SimpleNamespace(
        returncode=0, stdout=b"ROSYJOB 0 0\nok\n" if script == rj.POLL else b"", stderr=b"")})
    assert rj.run("h", "q", 0, tmp_path / "q.txt", ["r", "d", ""], [], 60, [], call=quick, sleep=lambda s: None) == 0
    assert ("h", "q", 0) not in rj._LIVE


def _lease(tmp_path, seen_age, rc=False, now=10_000):
    """Run the host's lease_check with kill stubbed; returns (exit code, kill words)."""
    (tmp_path / "0.seen").touch()
    if rc:
        (tmp_path / "0.rc").write_text("0")
    script = (f'D={tmp_path}; K=0; {rj.LEASE}\nkill() {{ echo kill "$@"; }}\n'
              f'touch -d @{now - seen_age} "$D/0.seen"; NOW={now}; lease_check 1200 4242; echo "rc=$?"')
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True).stdout
    return out.split("rc=")[1].strip(), out.split("rc=")[0].strip()


def test_lease_fresh_job_lives_stale_job_gets_term_finished_job_is_skipped(tmp_path):
    assert _lease(tmp_path, 100) == ("0", "")
    assert _lease(tmp_path, 1201) == ("1", "kill -TERM -- -4242")
    assert _lease(tmp_path, 5000, rc=True) == ("1", ""), "a finished job (.rc) is never signalled"


def test_guard_failure_cancels_the_pre_run_and_its_stop_is_the_verdict(repos, monkeypatch):
    _, wt = repos

    def guards(*a, **k):
        raise land.Stop("NEW failure in test/architecture")

    def pre(*a, **k):  # a pre run that only ends when its jobs are cancelled
        end = time.monotonic() + 10
        while not rj._CANCEL.is_set() and time.monotonic() < end:
            time.sleep(0.01)
        raise land.Overtime("cancelled")

    monkeypatch.setattr(land.land_guards, "first", guards)
    monkeypatch.setattr(land, "run_tests", pre)
    monkeypatch.setattr(land.land_full, "save", lambda *a, **k: pytest.fail("recorded a cancelled pretest"))
    with pytest.raises(land.Stop, match="test/architecture") as raised:
        land.land_prepare.prepare(land, wt, "feat/x", land.argparse.Namespace(tests="auto"), sys.executable,
                                  None, None, [["pkg/test"]], "FULL tier (test)")
    assert not isinstance(raised.value, land.Overtime) and not rj._CANCEL.is_set()
