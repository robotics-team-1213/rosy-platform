"""Storage admission placement and temporary-disk profiling tests (split from test_remote_pytest.py for D-766)."""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import remote_job as rj  # noqa: E402
import remote_pytest as rp  # noqa: E402
from test_remote_pytest import _job_env, _poll_until_done, _probe, _sh  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_headroom(monkeypatch):
    """place() fills rp.HEADROOM; no test sees another test's hosts."""
    monkeypatch.setattr(rp, "HEADROOM", {})


def test_place_refuses_low_storage_and_keeps_healthy_and_unmeasured_hosts(monkeypatch):
    monkeypatch.setattr(rp, "SITES", set())
    monkeypatch.setattr(rp, "BLOCKED", set())
    hosts = ["ai@1", "edge@2", "model@3", "old@4", "healthy@5"]
    probes = [_probe(disk_free_gb=21.92, disk_use=96), _probe(disk_free_gb=29.99, disk_use=80),
              _probe(disk_free_gb=41.85, disk_use=91, pytest_blocked=True),
              _probe(), _probe(disk_free_gb=30, disk_use=89)]
    chosen, notes = rp.place("pytest", hosts, probes)
    assert sorted(chosen) == ["healthy@5", "old@4"]
    assert all("storage maintenance required" in note for note in notes[:3])
    assert "model@3" not in rp.BLOCKED  # the host-alone queue can reuse BLOCKED hosts
    assert rp.disk_full(_probe(disk_free_gb=50, disk_use=90))
    # the no-host-above-floor fallback must not send the gate to a full disk either
    monkeypatch.delenv("ROSY_TEST_LOCAL", raising=False)
    monkeypatch.setenv("ROSY_TEST_HOSTS", "ai@1 model@3")
    monkeypatch.setattr(rp, "probe", dict(zip(hosts, probes)).get)
    assert rp.placed_hosts("pytest") == []


@pytest.mark.parametrize("code", [0, 5])
def test_job_disk_profile_reports_transient_and_retained_temp_bytes(tmp_path, code):
    if not shutil.which("setsid") or sys.platform == "win32":
        pytest.skip("Linux setsid/timeout/ionice are required")
    home, env = _job_env(tmp_path,
                         'truncate -s 2M "$TMPDIR/transient"\n'
                         'peak="$HOME/rosy-test/runs/r.jobs/0.disk-peak"\n'
                         'for _ in $(seq 40); do '
                         '[[ -s "$peak" && $(cat "$peak") -ge 2097152 ]] && break; sleep 0.1; done\n'
                         '[[ -s "$peak" && $(cat "$peak") -ge 2097152 ]] || exit 42\n'
                         'rm "$TMPDIR/transient"; printf x > "$4/leftover"\n'
                         f'exit {code}\n')
    assert _sh(rj.START, env, "r", "d", "", "0", "60", rj.JOB,
               "ROSY_TEST_DISK_PROFILE=1", "x.py").returncode == 0
    assert _poll_until_done(env) == code
    out = (home / "rosy-test" / "runs" / "r.jobs" / "0.log").read_text()
    match = re.search(r"disk temp sampled_peak_bytes=(\d+) before_cleanup_bytes=(\d+) after_cleanup_bytes=(\d+)", out)
    assert match, out
    peak, before, after = map(int, match.groups())
    assert peak >= 2 * 2**20 and 0 < before < peak and after == 0
