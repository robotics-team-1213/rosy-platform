"""Measured pytest memory per invocation, and the lock budget it earns (remote_job.JOB ``ROSY_JOB_RESERVE_GB``).

remote_job.JOB prints ``[remote-pytest] memory peak <MiB> MiB`` (the scope's cgroup ``memory.peak``).
remote_pytest.one() appends it with the invocation's argv key, host, sha and time to
``<git-common-dir>/rosy-pytest-memory.jsonl`` (beside land_cache's file) and, before the next run of the
same argv, reserves ``MARGIN`` times its highest recorded peak in whole GB (at least 1), else ``FULL_GB``.
MemoryMax stays 6 GB either way, so a wrong guess only lets one more job onto a host, it never kills one.
Measured 2026-10-26 over 140 scopes: median 0.3 GB, p90 3.1 GB, max 5.7 GB. 2026-10-27 over 763 argvs (3,077
runs) the highest peak per argv was median 292 MiB, p90 852 MiB, while 99% reserved 3 GB: the reservations, not
the hosts' memory, filled the test PCs. Standard library only.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import time
from pathlib import Path

FILE = "rosy-pytest-memory.jsonl"
FULL_GB, MARGIN = 6, 1.25
PEAK = re.compile(r"^\[remote-pytest\] memory peak (\d+) MiB\r?$", re.M)


def path(repo: Path) -> Path | None:
    """The history file of repo's common git dir; None outside a git repo."""
    result = subprocess.run(["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True)
    return Path(result.stdout.strip()) / FILE if result.returncode == 0 else None


def peak_mib(log_text: str) -> int | None:
    """The job's peak line in an invocation log, or None (old host script, no memory.peak)."""
    found = PEAK.findall(log_text)
    return int(found[-1]) if found else None


def key(inv: list[str]) -> str:
    return " ".join(inv)


def record(history: Path | None, inv: list[str], host: str, peak: int, sha: str) -> None:
    if history is None:
        return
    row = {"key": key(inv), "host": host, "peak_mib": peak, "sha": sha,
           "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    with history.open("a", encoding="utf-8") as out:
        out.write(json.dumps(row) + "\n")


def reserve_gb(history: Path | None, inv: list[str]) -> int:
    """MARGIN x inv's highest recorded peak, rounded up to whole GB within 1..FULL_GB; FULL_GB with no record."""
    want, peaks = key(inv), []
    try:
        lines = history.read_text(encoding="utf-8").splitlines() if history else []
    except OSError:
        lines = []
    for line in lines:
        try:
            row = json.loads(line)
            if row["key"] == want:
                peaks.append(int(row["peak_mib"]))
        except (ValueError, KeyError, TypeError):
            continue  # a torn or foreign line
    return min(FULL_GB, max(1, math.ceil(max(peaks) * MARGIN / 1024))) if peaks else FULL_GB
