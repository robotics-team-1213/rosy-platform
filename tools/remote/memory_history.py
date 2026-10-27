"""Measured pytest memory and cpu per invocation, and the lock budget they earn (remote_job.JOB
``ROSY_JOB_RESERVE_GB`` / ``ROSY_JOB_RESERVE_CORES``; a job's average cores, cpu.stat over wall time, likewise
gets ``MARGIN``, never more than its ``-n`` workers: 2026-10-27 locks held all 24 AI PC cores at load 10).

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
CPU = re.compile(r"^\[remote-pytest\] cpu (\d+) ms over (\d+) ms\r?$", re.M)


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


def cpu_cores(log_text: str) -> float | None:
    """Average cores the job's scope used (its cpu line: cpu.stat usage over wall time), or None."""
    found = CPU.findall(log_text)
    return round(int(found[-1][0]) / int(found[-1][1]), 2) if found and int(found[-1][1]) else None


def record(history: Path | None, inv: list[str], host: str, peak: int, sha: str, cores: float | None = None) -> None:
    if history is None:
        return
    row = {"key": key(inv), "host": host, "peak_mib": peak, "sha": sha,
           "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **({"cores": cores} if cores is not None else {})}
    with history.open("a", encoding="utf-8") as out:
        out.write(json.dumps(row) + "\n")


def _rows(history: Path | None, inv: list[str]) -> list[dict]:
    want, rows = key(inv), []
    try:
        lines = history.read_text(encoding="utf-8").splitlines() if history else []
    except OSError:
        lines = []
    for line in lines:
        try:
            row = json.loads(line)
            if row["key"] == want:
                rows.append(row)
        except (ValueError, KeyError, TypeError):
            continue  # a torn or foreign line
    return rows


def reserve_gb(history: Path | None, inv: list[str]) -> int:
    """MARGIN x inv's highest recorded peak, rounded up to whole GB within 1..FULL_GB; FULL_GB with no record."""
    peaks = [r["peak_mib"] for r in _rows(history, inv) if isinstance(r.get("peak_mib"), int)]
    return min(FULL_GB, max(1, math.ceil(max(peaks) * MARGIN / 1024))) if peaks else FULL_GB


def reserve_cores(history: Path | None, inv: list[str], workers: int) -> int:
    """MARGIN x inv's highest recorded average cores, rounded up within 1..workers; workers with no record."""
    used = [r["cores"] for r in _rows(history, inv) if isinstance(r.get("cores"), (int, float))]
    return min(workers, max(1, math.ceil(max(used) * MARGIN))) if used else workers


def reserve(history: Path | None, inv: list[str], words: list[str], note: str) -> tuple[list[str], str]:
    """Job words and note with the lock budget inv's history earns (remote_pytest.one): GB, unless a light host
    already capped MemoryMax, and cores under the job's ``ROSY_JOB_CORES`` (JOB's default 2; ``-n`` keeps it)."""
    gb = reserve_gb(history, inv)
    if gb < FULL_GB and not any(w.startswith("ROSY_JOB_MEM_GB=") for w in words):
        words, note = [*words, f"ROSY_JOB_RESERVE_GB={gb}"], note + f", reserve {gb} GB (memory history)"
    workers = next((int(w[15:]) for w in words if w.startswith("ROSY_JOB_CORES=") and w[15:].isdigit()), 2)
    if (cores := reserve_cores(history, inv, workers)) < workers:
        words, note = [*words, f"ROSY_JOB_RESERVE_CORES={cores}"], note + f", {cores} of {workers} cores (cpu history)"
    return words, note
