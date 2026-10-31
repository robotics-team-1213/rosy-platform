"""Whether one pytest invocation runs under pytest-xdist on its test host, and the job budget it records.

remote_pytest.one() asks ``plan(inv, headroom)`` for (job words, pytest args, note). Job words are
leading ``ROSY_JOB_*=n`` words that remote_job.JOB reads for its lock budget and ``MemoryMax``; a
quarantine rerun keeps them. An invocation runs serial when it is a browser job, names node ids
(reruns, D-790 load-flaky checks), names no path, sets ``-n``/``-p no:xdist`` itself, or names a
path under (or above) a prefix in ``serial_suites.txt``. Otherwise it gets ``-n W --dist loadfile``
(one file per worker, so in-file order and module fixtures stay as in a serial run) with W from
the host's measured free cores and memory, at most what the job's 6 GB ``MemoryMax`` holds.
``ROSY_TEST_WORKERS=n`` (laptop environment) overrides W for measurement; 0 or 1 is serial.
Standard library only.
"""

from __future__ import annotations

import itertools
import os
import re
from pathlib import Path

SERIAL_FILE = Path(__file__).with_name("serial_suites.txt")
ALONE = "ROSY_BROWSER_ALONE=1"  # work_queue.ALONE_ENV: a timing-sensitive browser chunk
# Suites that need the host to themselves (ROS_DOMAIN_ID, ports, subprocesses), not merely no -n: serial_suites.txt's
# tools line (home-directory tools, collect_alone one file per process) and browser or node-id jobs are admitted
# normally. land_isolation runs its timing files one at a time inside its own job.
HOST_ALONE = ("integrations/simulation/gazebo/test", "learning/envs/isaac/test")
# land.py sets TURN_ENV while it holds the turn; its jobs then carry TURN_JOB, which remote_job.ADMIT starts without
# waiting for room. 2026-10-31 a turn's guard job waited 75 min behind other landings' prepare jobs on the site PC,
# and the whole queue (34 tickets) waited behind the turn.
TURN_ENV, TURN_JOB = "ROSY_LAND_TURN", "ROSY_JOB_TURN=1"
JOB_MEM_GB = 6  # remote_job.JOB MemoryMax default (D-568 2)
GB_PER_WORKER = 1.0  # shortcut: a guess, not measured; lower it once the measurement plan shows per-worker RSS
MAX_WORKERS = int(JOB_MEM_GB // GB_PER_WORKER)
SITE_CPUS = 4  # remote_pytest.SITE_CPU_QUOTA 400%
ENV_WORD = re.compile(r"^ROSY_[A-Z0-9_]*=")
OWN_XDIST = re.compile(r"^(-n|-n\d+|-nauto|--numprocesses(=.*)?|--dist(=.*)?|-pno:xdist|no:xdist)$")


def load_serial(text: str) -> list[str]:
    """Path prefixes of serial_suites.txt: one per line, ``#`` starts a comment."""
    rows = (line.split("#", 1)[0].strip().replace("\\", "/").strip("/") for line in text.splitlines())
    return [row for row in rows if row]


def serial_reason(inv: list[str], serial: list[str]) -> str | None:
    """Why inv must not get ``-n``, or None when it may."""
    env = list(itertools.takewhile(ENV_WORD.match, inv))
    words = inv[len(env):]
    if any(w.startswith("ROSY_RUN_BROWSER_TESTS=") for w in env):
        return "browser job"
    if any(OWN_XDIST.match(w) for w in words):
        return "invocation sets xdist itself"
    paths = [w.replace("\\", "/") for w in words if not w.startswith("-")]
    if not paths:
        return "no path named"
    for path in paths:
        if "::" in path:
            return "node ids"
        path = path.removeprefix("./").strip("/")
        for prefix in serial:
            if path in ("", ".") or path == prefix or path.startswith(prefix + "/") or prefix.startswith(path + "/"):
                return f"{prefix} is in {SERIAL_FILE.name}"
    return None


def workers(cores: float, mem_gb: float, site: bool) -> int:
    """xdist workers for a host with this free headroom; 1 means serial."""
    override = os.environ.get("ROSY_TEST_WORKERS", "").strip()
    if override:
        if not override.isdigit():
            raise SystemExit(f"[remote-pytest] ROSY_TEST_WORKERS must be a whole number, not {override!r}")
        return max(1, int(override))
    n = min(int(cores), int(mem_gb // GB_PER_WORKER), MAX_WORKERS, SITE_CPUS if site else MAX_WORKERS)
    return n if n >= 2 else 1


def plan(inv: list[str], headroom: dict | None, serial: list[str] | None = None) -> tuple[list[str], list[str], str]:
    """(job words, extra pytest args, note) for inv on a host placed with this headroom (None: unmeasured)."""
    if serial is None:
        serial = load_serial(SERIAL_FILE.read_text(encoding="utf-8"))
    if headroom is None:
        return [], [], "serial: host below the floor (D-568 7 fallback)"
    why = serial_reason(inv, serial)
    # The host's JOB admission runs these with no other job on the host, from any run (HOST_ALONE, ALONE).
    paths = [w.replace("\\", "/") for w in inv if not ENV_WORD.match(w) and not w.startswith("-")]
    alone = ["ROSY_JOB_ALONE=1"] if ALONE in inv or any(p == a or p.startswith(a + "/") or a.startswith(p + "/")
                                                        for p in paths for a in HOST_ALONE) else []
    alone += [TURN_JOB] if os.environ.get(TURN_ENV) == "1" else []  # a turn holder's job skips the host's queue
    if headroom["light"]:  # below the pytest memory floor: cap the job at what the host has free
        mem = max(1, int(headroom["mem"]))
        return [f"ROSY_JOB_MEM_GB={mem}", *alone], [], f"serial: light host, MemoryMax {mem} GB"
    share = max(1, int(headroom.get("share", 1)))  # this run's main workers on the host (work_queue.main_workers)
    n = 1 if why else workers(headroom["cores"] / share, headroom["mem"] / share, headroom["site"])
    if n == 1:
        return alone, [], f"serial: {why or 'not enough headroom for 2 workers'}"
    note = f"xdist: {n} workers" + (f" (1/{share} of the host)" if share > 1 else "")
    return [f"ROSY_JOB_CORES={n}", *alone], ["-n", str(n), "--dist", "loadfile"], note
