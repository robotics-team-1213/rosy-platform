"""Per-invocation memory peak (remote_job.JOB) and the history-based lock reservation (memory_history)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import memory_history as mh  # noqa: E402
import remote_job as rj  # noqa: E402
import remote_pytest as rp  # noqa: E402
from test_remote_pytest import _job_env, _poll_until_done, _sh  # noqa: E402

LINUX_JOB = not shutil.which("setsid") or sys.platform == "win32"


def test_peak_line_is_parsed_from_the_invocation_log():
    assert mh.peak_mib("x\r\n[remote-pytest] memory peak 512 MiB\r\n1 passed\n") == 512
    assert mh.peak_mib("[remote-pytest] memory peak 1 MiB\n[remote-pytest] memory peak 7 MiB\n") == 7
    assert mh.peak_mib("1 passed\nsay [remote-pytest] memory peak 9 MiB\n") is None
    assert mh.peak_mib("") is None


def test_history_appends_rows_and_chooses_the_reservation(tmp_path):
    history, small, heavy = tmp_path / mh.FILE, ["test/a.py", "-q"], ["test/b.py"]
    assert mh.reserve_gb(history, small) == 6 and mh.reserve_gb(None, small) == 6  # no history
    mh.record(history, small, "ai@1", 900, "ab" * 20)
    mh.record(history, small, "omen", 300, "cd" * 20)
    mh.record(None, small, "omen", 9999, "cd" * 20)  # outside a git repo: nothing written
    rows = history.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 2 and '"key": "test/a.py -q"' in rows[0] and '"host": "ai@1"' in rows[0]
    assert '"peak_mib": 900' in rows[0] and '"sha": "' + "ab" * 20 + '"' in rows[0] and '"time": "20' in rows[0]
    with history.open("a", encoding="utf-8") as out:
        out.write('{"key": "test/a.py -q", "peak_mib"\n[]\n')  # torn and foreign lines are skipped
    assert mh.reserve_gb(history, small) == 2  # 1.25 x the highest peak (900 MiB), rounded up
    assert mh.reserve_gb(history, heavy) == 6  # another argv has no history
    mh.record(history, heavy, "ai@1", 100, "ef" * 20)
    assert mh.reserve_gb(history, heavy) == 1  # never below 1 GB
    mh.record(history, small, "ai@1", 9000, "ef" * 20)
    assert mh.reserve_gb(history, small) == 6  # never above the 6 GB MemoryMax


def test_cpu_history_lowers_the_lock_cores_but_never_the_workers(tmp_path):
    """2026-10-27: xdist locks held all 24 AI PC cores while its load was 10."""
    assert mh.cpu_cores("[remote-pytest] cpu 90000 ms over 60000 ms\r\n") == 1.5
    assert mh.cpu_cores("[remote-pytest] cpu 5 ms over 0 ms\n") is None and mh.cpu_cores("") is None
    history, inv = tmp_path / mh.FILE, ["test/a.py"]
    assert mh.reserve(history, inv, ["ROSY_JOB_CORES=6"], "xdist: 6 workers") == (["ROSY_JOB_CORES=6"], "xdist: 6 workers")
    mh.record(history, inv, "h", 300, "ab" * 20, 1.5)
    mh.record(history, inv, "h", 300, "ab" * 20)  # an older host script: no cpu line
    assert mh.reserve_cores(history, inv, 6) == 2  # ceil(1.25 x 1.5)
    words, note = mh.reserve(history, inv, ["ROSY_JOB_CORES=6"], "xdist: 6 workers")
    assert words == ["ROSY_JOB_CORES=6", "ROSY_JOB_RESERVE_GB=1", "ROSY_JOB_RESERVE_CORES=2"]
    assert note.endswith(", 2 of 6 cores (cpu history)")
    mh.record(history, inv, "h", 300, "ab" * 20, 7.9)
    assert mh.reserve(history, inv, ["ROSY_JOB_CORES=6"], "")[0] == ["ROSY_JOB_CORES=6", "ROSY_JOB_RESERVE_GB=1"]
    assert mh.reserve_cores(history, ["test/b.py"], 2) == 2  # no record: the workers


def _run_on(tmp_path, monkeypatch, headroom, peak=b"[remote-pytest] memory peak 300 MiB\n"):
    monkeypatch.setattr(rp, "HEADROOM", {"h": headroom})
    monkeypatch.delenv("ROSY_TEST_WORKERS", raising=False)
    monkeypatch.setattr(rp, "ship", lambda *a, **kw: None)
    monkeypatch.setattr(rp, "deps", lambda repo, sha: ("d" * 16, []))
    monkeypatch.setattr(rp, "remote", lambda *a, **kw: subprocess.CompletedProcess([], 0, b"", b""))
    monkeypatch.setattr(mh, "path", lambda repo: tmp_path / mh.FILE)
    calls = []
    monkeypatch.setattr(rp.remote_job, "run", lambda h, name, k, log, job, inv, *a:
                        calls.append(inv) or log.write_bytes(peak + b"1 passed\n") and 0)
    assert rp.run_on("h", [["test/x.py"]], [tmp_path / "run-1.txt"], "ab" * 20, tmp_path, None) == [0]
    return calls[0]


def test_dispatch_reserves_from_history_but_keeps_the_cap(tmp_path, monkeypatch):
    full = {"cores": 1.0, "mem": 10.0, "site": False, "light": False}
    first = _run_on(tmp_path, monkeypatch, full)
    assert not [w for w in first if w.startswith("ROSY_JOB_")]  # no history: JOB's defaults, 6 and 6
    assert '"peak_mib": 300' in (tmp_path / mh.FILE).read_text(encoding="utf-8")
    second = _run_on(tmp_path, monkeypatch, full)
    assert second[0] == "ROSY_JOB_RESERVE_GB=1" and not [w for w in second if w.startswith("ROSY_JOB_MEM_GB=")]
    light = _run_on(tmp_path, monkeypatch, {**full, "light": True, "mem": 4.5})
    assert [w for w in light if w.startswith("ROSY_JOB_")] == ["ROSY_JOB_MEM_GB=4"]  # its cap is its reservation
    mh.record(tmp_path / mh.FILE, ["test/x.py"], "h", 5000, "ab" * 20)
    assert not [w for w in _run_on(tmp_path, monkeypatch, full, b"") if w.startswith("ROSY_JOB_")]


@pytest.mark.skipif(LINUX_JOB, reason="Linux setsid/timeout/ionice are required")
@pytest.mark.parametrize("peak_bytes, line", [(b"3221225472\n", "[remote-pytest] memory peak 3072 MiB"), (None, None)])
def test_job_prints_the_scope_memory_peak_and_keeps_the_exit_code(tmp_path, peak_bytes, line):
    home, env = _job_env(tmp_path, "echo ran; exit 3\n")
    cgroup = Path("/proc/self/cgroup").read_text().split(":", 2)[2].strip()  # the fake scope is this test's cgroup
    fs = tmp_path / "cgfs"
    (fs / cgroup.lstrip("/")).mkdir(parents=True)
    if peak_bytes:
        (fs / cgroup.lstrip("/") / "memory.peak").write_bytes(peak_bytes)
        (fs / cgroup.lstrip("/") / "cpu.stat").write_text("usage_usec 4000000\nuser_usec 3000000\n")
    assert _sh(rj.START, {**env, "ROSY_CGROUP_FS": str(fs)}, "r", "d", "", "0", "60", rj.JOB, "x.py").returncode == 0
    assert _poll_until_done(env) == 3
    out = (home / "rosy-test" / "runs" / "r.jobs" / "0.log").read_text()
    peaks = [row for row in out.splitlines() if "memory peak" in row]
    assert peaks == ([line] if line else []) and out.index("ran") < (out.index(line) if line else len(out))
    assert mh.peak_mib(out) == (3072 if line else None)
    cpu = [row for row in out.splitlines() if row.startswith("[remote-pytest] cpu ")]
    assert len(cpu) == (1 if line else 0) and (not line or cpu[0].startswith("[remote-pytest] cpu 4000 ms over "))
    assert (mh.cpu_cores(out) is not None) == bool(line)


@pytest.mark.skipif(LINUX_JOB, reason="Linux setsid/timeout/ionice are required")
@pytest.mark.parametrize("words, lock, mem", [(["ROSY_JOB_RESERVE_GB=3"], "2 3", "6G"),
                                              (["ROSY_JOB_MEM_GB=4"], "2 4", "4G"),
                                              (["ROSY_JOB_CORES=6", "ROSY_JOB_RESERVE_GB=3"], "6 3", "6G"),
                                              (["ROSY_JOB_CORES=6", "ROSY_JOB_RESERVE_CORES=2"], "2 6", "6G")])
def test_job_lock_takes_the_reservation_and_memory_max_the_cap(tmp_path, words, lock, mem):
    home, env = _job_env(tmp_path, 'cat "$HOME/rosy-jobs/r.lock"\n')
    (tmp_path / "bin" / "systemd-run").write_text(
        '#!/bin/bash\necho "$*" > "$HOME/scope"\nwhile [ "$1" != -- ]; do shift; done; shift; exec "$@"\n')
    assert _sh(rj.START, env, "r", "d", "", "0", "60", rj.JOB, *words, "x.py").returncode == 0
    assert _poll_until_done(env) == 0
    out = (home / "rosy-test" / "runs" / "r.jobs" / "0.log").read_text()
    assert out.splitlines()[1].split()[1:] == ["pytest", *lock.split()]
    assert f"MemoryMax={mem} " in (home / "scope").read_text()
    bad = _sh(rj.START, env, "r", "d", "", "1", "60", rj.JOB, "ROSY_JOB_RESERVE_GB=3.5", "x.py")
    assert bad.returncode == 0 and _poll_until_done(env, "1") == 2
