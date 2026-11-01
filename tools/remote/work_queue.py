"""The shared invocation queue remote_pytest's host workers pull from, its largest-first cost, and browser lanes.

A full lab host runs up to MAX_MAIN main workers of one run (``main_workers``, each job's xdist sized from its
share) and, beside them, up to BROWSER_PER_HOST "lane" workers that take only browser invocations (serial, ~1 core
each), so the FULL tier's browser chunks stop queueing behind the xdist suites. Every job takes its own lock and
starts only when the host's JOB admission (remote_job.ADMIT) finds room across all runs.
While Gazebo holds a host (a live class-sim lock or reservation) it gets no lanes, so with one lab host left
the browser chunks mostly run behind main's queue there; the site PC never gets lanes (it is no FULL target)."""
from __future__ import annotations

import collections
from concurrent.futures import CancelledError
import contextlib
import functools
import itertools
import json
import math
import os
import re
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

from remote_job import CANCELLED
from xdist_plan import HOST_ALONE, SERIAL_FILE, load_serial, serial_reason


BROWSER_ENV = "ROSY_RUN_BROWSER_TESTS=1"
ALONE_ENV = "ROSY_BROWSER_ALONE=1"  # a timing-sensitive browser chunk: no lane job of its own run beside it
ENV_WORD = re.compile(r"^ROSY_[A-Z0-9_]*=")
# Browser jobs per host beside main. Measured 2026-10-26 on the model PC, 3 chunks, no other job: 1/2/3 at once
# = 1053/632/449 s wall, each chunk within 1% of its serial time, 0 failures, peak <= 751 MiB each. 2, not 3: main's
# xdist job and up to 3 preparing landings share the host, and load-flaky browser ids exist. 4 since 2026-10-31:
# the cap counts every run's browser jobs, so 2 per host left 4 browser slots for all preparing landings while a
# FULL round carried 60-163 min of browser chunks and the hosts ran at load ~5 of 24 cores; each PC's JOB
# admission (remote_job.ADMIT, since 10-28) now holds the cores and GB, and LOAD-FLAKY ids keep their ALONE chunk.
# ROSY_BROWSER_PER_HOST overrides it to measure.
BROWSER_PER_HOST = int(os.environ.get("ROSY_BROWSER_PER_HOST", "4"))
# 6 since 2026-11-01: FULL rounds ran their invocations at 0.4-0.7x parallelism (sum run_s / wall), the tail queued
# behind the run's own workers for 60-117 min; each PC's JOB admission still bounds cores and GB.
MAX_MAIN = 6  # main workers one run may ask of a full host (1 restores one-at-a-time)
MAIN_CORES, MAIN_GB = 2, 2  # headroom one more main worker needs
SKIP_ALONE = "!"  # workers(): a worker kind on a host other than the host_alone suites' one


def cancelled(invocations: list[list[str]], codes: list) -> list[int | str]:
    """codes with every invocation that never ran (None) marked CANCELLED, each one printed."""
    for inv, code in zip(invocations, codes):
        if code in (None, CANCELLED):
            print(f"[remote-pytest] cancelled after a failure: {' '.join(inv)}", flush=True)
    return [CANCELLED if code is None else code for code in codes]


def lane_job(inv: list[str]) -> bool:
    """A browser invocation a lane may take: opted in to Chromium and not marked to run alone."""
    env = list(itertools.takewhile(ENV_WORD.match, inv))
    return BROWSER_ENV in env and ALONE_ENV not in env


def host_alone(inv: list[str]) -> bool:
    """An invocation of a suite that takes the whole host (xdist_plan.HOST_ALONE: Gazebo, Isaac)."""
    paths = [w.replace("\\", "/") for w in inv if not ENV_WORD.match(w) and not w.startswith("-")]
    return any(p == a or p.startswith(a + "/") or a.startswith(p + "/") for p in paths for a in HOST_ALONE)


def workers(hosts: list[str], invocations: list[list[str]], headroom: dict,
            order: list[str] = ()) -> list[tuple[str, str]]:
    """(host, kind) per worker thread. "any" takes everything one at a time (light, site, sim-holding or unmeasured
    hosts, no lane jobs, or the host already runs BROWSER_PER_HOST browser jobs of any run); otherwise "main" takes
    all but lane jobs and each "lane" only lane jobs. A kind ending in SKIP_ALONE never takes a host_alone one.

    host_alone suites go to the first host of ``order`` (the configured list: the model PC) when it was placed:
    each one waits for its host to empty, and on 2026-10-30 70 of them (34-40 min each, 10 s-3.5 min of tests)
    kept the AI PC from new jobs, so 44 of 143 placements found no host. Without that host they run as before."""
    pin = next((h for h in order if h in hosts and not (headroom.get(h) or {}).get("site")), None)
    if (headroom.get(pin) or {}).get("sim_held"):  # Gazebo/Isaac hold it: they would wait there behind the sim
        pin = None
    if pin and any(map(host_alone, invocations)):
        hosts = [pin] if all(map(host_alone, invocations)) else [pin, *(h for h in hosts if h != pin)]
    else:
        pin = None
    hosts = hosts[:len(invocations)]
    lanes = sum(map(lane_job, invocations))
    rest = len(invocations) - lanes
    plan = []
    for host in hosts:
        room = headroom.get(host)
        free = BROWSER_PER_HOST - room.get("browser_jobs", 0) if room else 0  # other runs' browser jobs count
        full = room and not (room["light"] or room["site"] or room.get("sim_held"))
        n = max(0, min(free, lanes)) if full else 0
        mains = main_workers(room, rest) if full else 1
        if room is not None and mains > 1:
            room["share"] = mains  # xdist_plan sizes each job's -n from its share, never the whole host
        plan += [(host, "any")] * mains if n == 0 else [(host, "main")] * (mains if rest else 0) + [(host, "lane")] * n
    return [(h, k if pin in (None, h) or k == "lane" else k + SKIP_ALONE) for h, k in plan]


def main_workers(room: dict, jobs: int) -> int:
    """Main workers of one run on a full host: 2026-10-28, 94 % of queued_s was a run's own jobs waiting behind
    its one worker per host (pytest_s p50 10 s, queued_s p50 379 s). The host's JOB admission (remote_job) still
    holds every job to the free cores and GB across runs, so this is the most a run asks for."""
    by_room = min(int(room.get("cores", 0)) // MAIN_CORES, int(room.get("mem", 0)) // MAIN_GB)
    return max(1, min(MAX_MAIN, by_room, jobs))


def wanted(kind: str, invocations: list[list[str]]):
    """The Work.take filter of a worker kind (None: anything)."""
    skip, kind = kind.endswith(SKIP_ALONE), kind.removesuffix(SKIP_ALONE)
    if kind == "any":
        return (lambda i: not host_alone(invocations[i])) if skip else None
    return lambda i: lane_job(invocations[i]) == (kind == "lane") and not (skip and host_alone(invocations[i]))


def guard(gate, kind: str, inv: list[str]):
    """The context one job runs in: a lane slot, the host to itself for an alone job beside lanes, else nothing."""
    kind = kind.removesuffix(SKIP_ALONE)
    if gate is None or kind == "any":
        return contextlib.nullcontext()
    return gate.lane() if kind == "lane" else gate.alone() if ALONE_ENV in inv else contextlib.nullcontext()


class Work:
    """Invocation indices still to run and the exit code of each one run, shared by the host workers.

    A filtered take scans todo, so every take and give_back holds one lock. Once stop is set nothing more is taken."""

    def __init__(self, order, on_done=None, stop=None):
        self.todo, self.codes, self.lost = collections.deque(order), {}, set()
        self.on_done, self._asking = on_done, threading.Lock()
        self.stop = stop if stop is not None else threading.Event()
        self._queue, self.began = threading.Lock(), time.monotonic()  # began: an invocation's queue wait starts here

    def done(self, inv: list[str], log: Path) -> None:
        """Ask on_done(inv, log) whether to cancel the rest; set stop when it says so or raises (the safe side).

        One call at a time, on the host's worker thread; that host takes nothing while it runs, so the callback
        may call remote_pytest.run itself (a nested run has its own queue, threads and run dir)."""
        if self.on_done is None:
            return
        with self._asking:
            if self.stop.is_set():
                return
            try:
                cancel = bool(self.on_done(inv, log))
            except CancelledError:
                self.stop.set()
                raise
            except Exception as error:  # noqa: BLE001 - a broken callback must not hang or pass the run
                print(f"[remote-pytest] WARNING: on_done raised {error!r}; cancelling the rest", file=sys.stderr, flush=True)
                cancel = True
            if cancel:
                self.stop.set()

    def take(self, wanted=None) -> int | None:
        """The first queued index (largest first) that wanted(index) accepts; any index when wanted is None."""
        if self.stop.is_set():
            return None
        with self._queue:
            for i in self.todo:
                if wanted is None or wanted(i):
                    self.todo.remove(i)
                    return i
        return None

    def take_small(self, wanted=None) -> int | None:
        """The last queued index (the smallest, largest-first order) wanted(index) accepts: a light host's pick."""
        if self.stop.is_set():
            return None
        with self._queue:
            for i in reversed(self.todo):
                if wanted is None or wanted(i):
                    self.todo.remove(i)
                    return i
        return None

    def give_back(self, i: int) -> None:
        """i first in line again: its host failed mid-run, so another host (or run()'s fallback) runs it."""
        with self._queue:
            self.todo.appendleft(i)


class Gate:
    """One host's browser lanes and its main worker: a lane job waits while an alone job runs, and an alone
    job starts once the host's running lane jobs end (remote_pytest.ALONE_ENV, timing-sensitive files)."""

    def __init__(self):
        self._cv, self._lanes, self._alone = threading.Condition(), 0, False

    @contextlib.contextmanager
    def lane(self):
        with self._cv:
            self._cv.wait_for(lambda: not self._alone)
            self._lanes += 1
        try:
            yield
        finally:
            with self._cv:
                self._lanes -= 1
                self._cv.notify_all()

    @contextlib.contextmanager
    def alone(self):
        with self._cv:
            self._alone = True
            self._cv.wait_for(lambda: self._lanes == 0)
        try:
            yield
        finally:
            with self._cv:
                self._alone = False
                self._cv.notify_all()


SPLIT_S = 240  # an invocation whose median run exceeds this is split (2026-11-01: 30 min combined invocations)
MAX_SPLIT = 6
BYTES_PER_S = 2000  # shortcut: rough test-code bytes per run second for invocations with no history; replace if it misorders


@functools.lru_cache(maxsize=4)
def _history(events: str, mtime: float) -> dict[tuple, float]:
    runs = collections.defaultdict(list)
    with open(events, encoding="utf-8") as f:
        for line in f:
            if '"run_s"' not in line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("event") == "tests" and isinstance(row.get("run_s"), (int, float)):
                runs[tuple(row.get("argv") or ())].append(row["run_s"])
    return {argv: statistics.median(v) for argv, v in runs.items()}


def history(repo: Path) -> dict[tuple, float]:
    """Median run_s per invocation argv from the landing events log (land_checks records run_s since 2026-10-31)."""
    common = subprocess.run(["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True).stdout.strip()
    events = Path(common) / "rosy-land-events.jsonl" if common else None
    if events is None or not events.is_file():
        return {}
    return _history(str(events), events.stat().st_mtime)


def cost(repo: Path, inv: list[str], seen: dict | None = None) -> float:
    """Expected run seconds: the measured median when this argv ran before, else test-file bytes / BYTES_PER_S."""
    seen = history(repo) if seen is None else seen
    if tuple(inv) in seen:
        return seen[tuple(inv)]
    total = 0
    for word in inv:
        path = repo / word.split("::", 1)[0]
        files = path.rglob("*.py") if path.is_dir() else [path]
        total += sum(f.stat().st_size for f in files if f.is_file())
    return total / BYTES_PER_S


def split(repo: Path, invocations: list[list[str]], seen: dict | None = None) -> list[list[str]]:
    """Long invocations as smaller ones the hosts can run side by side; every test still runs exactly once.

    One measured above SPLIT_S splits into one invocation per path, and a single directory into up to MAX_SPLIT
    balanced file groups. Browser chunks (land_browser chunks them), alone/isolation runs, node ids, own -n and
    serial_suites.txt paths stay whole."""
    seen = history(repo) if seen is None else seen
    serial = load_serial(SERIAL_FILE.read_text(encoding="utf-8")) if SERIAL_FILE.is_file() else []
    out = []
    for inv in invocations:
        env = list(itertools.takewhile(ENV_WORD.match, inv))
        rest = inv[len(env):]
        paths = [w for w in rest if not w.startswith("-")]
        whole = (seen.get(tuple(inv), 0) < SPLIT_S or any(w.startswith(("ROSY_RUN_BROWSER_TESTS", "ROSY_ALONE",
                 "ROSY_JOB_ALONE", "ROSY_COLLECT")) for w in env) or len(paths) != len(rest)
                 or any("::" in p or "collect_alone" in p for p in paths) or serial_reason(inv, serial))
        if whole:
            out.append(inv)
        elif len(paths) > 1:
            out += [[*env, p] for p in paths]
        elif (repo / paths[0]).is_dir():
            files = sorted((f for f in (repo / paths[0]).rglob("*.py")
                            if f.name.startswith("test_") or f.name.endswith("_test.py")),
                           key=lambda f: -f.stat().st_size)
            n = min(MAX_SPLIT, math.ceil(seen[tuple(inv)] / SPLIT_S), len(files))
            groups, sizes = [[] for _ in range(n)], [0] * n
            for f in files:  # largest first into the lightest group
                i = sizes.index(min(sizes))
                groups[i].append(f.relative_to(repo).as_posix())
                sizes[i] += f.stat().st_size
            out += [[*env, *sorted(g)] for g in groups if g] if n > 1 else [inv]
        else:
            out.append(inv)
    return out

