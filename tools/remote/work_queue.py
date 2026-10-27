"""The shared invocation queue remote_pytest's host workers pull from, its largest-first cost, and browser lanes.

A full lab host runs its usual one-at-a-time worker ("main") and, beside it, up to BROWSER_PER_HOST "lane"
workers that take only browser invocations (serial, ~1 core each), so the FULL tier's browser chunks stop
queueing behind the xdist suites. Each worker is a run of its own (own run dir and lock, remote_job.JOB).
While Gazebo holds a host (a live class-sim lock or reservation) it gets no lanes, so with one lab host left
the browser chunks mostly run behind main's queue there; the site PC never gets lanes (it is no FULL target)."""
from __future__ import annotations

import collections
import contextlib
import itertools
import os
import re
import sys
import threading
import time
from pathlib import Path


BROWSER_ENV = "ROSY_RUN_BROWSER_TESTS=1"
ALONE_ENV = "ROSY_BROWSER_ALONE=1"  # a timing-sensitive browser chunk: no lane job of its own run beside it
ENV_WORD = re.compile(r"^ROSY_[A-Z0-9_]*=")
# Browser jobs per host beside main. Measured 2026-10-26 on the model PC, 3 chunks, no other job: 1/2/3 at once
# = 1053/632/449 s wall, each chunk within 1% of its serial time, 0 failures, peak <= 751 MiB each. 2, not 3: main's
# xdist job and up to 3 preparing landings share the host, and load-flaky browser ids exist.
# ROSY_BROWSER_PER_HOST overrides it to measure.
BROWSER_PER_HOST = int(os.environ.get("ROSY_BROWSER_PER_HOST", "2"))


def lane_job(inv: list[str]) -> bool:
    """A browser invocation a lane may take: opted in to Chromium and not marked to run alone."""
    env = list(itertools.takewhile(ENV_WORD.match, inv))
    return BROWSER_ENV in env and ALONE_ENV not in env


def workers(hosts: list[str], invocations: list[list[str]], headroom: dict) -> list[tuple[str, str]]:
    """(host, kind) per worker thread. "any" takes everything one at a time (light, site, sim-holding or unmeasured
    hosts, no lane jobs, or the host already runs BROWSER_PER_HOST browser jobs of any run); otherwise "main" takes
    all but lane jobs and each "lane" only lane jobs."""
    lanes = sum(map(lane_job, invocations))
    rest = len(invocations) - lanes
    plan = []
    for host in hosts:
        room = headroom.get(host)
        free = BROWSER_PER_HOST - room.get("browser_jobs", 0) if room else 0  # other runs' browser jobs count
        n = 0 if not room or room["light"] or room["site"] or room.get("sim_held") else max(0, min(free, lanes))
        plan += [(host, "any")] if n == 0 else [(host, "main")] * bool(rest) + [(host, "lane")] * n
    return plan


def wanted(kind: str, invocations: list[list[str]]):
    """The Work.take filter of a worker kind (None: anything)."""
    if kind == "any":
        return None
    return lambda i: lane_job(invocations[i]) == (kind == "lane")


def guard(gate, kind: str, inv: list[str]):
    """The context one job runs in: a lane slot, the host to itself for an alone job beside lanes, else nothing."""
    if gate is None or kind == "any":
        return contextlib.nullcontext()
    return gate.lane() if kind == "lane" else gate.alone() if ALONE_ENV in inv else contextlib.nullcontext()


class Work:
    """Invocation indices still to run and the exit code of each one run, shared by the host workers.

    A filtered take scans todo, so every take and give_back holds one lock. Once stop is set nothing more is taken."""

    def __init__(self, order, on_done=None):
        self.todo, self.codes, self.lost = collections.deque(order), {}, set()
        self.on_done, self.stop, self._asking = on_done, threading.Event(), threading.Lock()
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

    def take_small(self) -> int | None:
        """The last queued index (the smallest, largest-first order): a light host's pick."""
        if self.stop.is_set():
            return None
        with self._queue:
            return self.todo.pop() if self.todo else None

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


def cost(repo: Path, inv: list[str]) -> int:
    """Bytes of the test files an invocation names (dirs: their .py files), a cheap stand-in for run time."""
    # ponytail: size, not time; record per-invocation durations if largest-first still leaves a tail.
    total = 0
    for word in inv:
        path = repo / word.split("::", 1)[0]
        files = path.rglob("*.py") if path.is_dir() else [path]
        total += sum(f.stat().st_size for f in files if f.is_file())
    return total

