"""The shared invocation queue remote_pytest's host workers pull from, and its largest-first cost."""
from __future__ import annotations

import collections
import sys
import threading
from pathlib import Path


class Work:
    """Invocation indices still to run and the exit code of each one run, shared by the host workers.

    deque.popleft/appendleft are atomic, so the threads need no lock. Once stop is set nothing more is taken."""

    def __init__(self, order, on_done=None):
        self.todo, self.codes, self.lost = collections.deque(order), {}, set()
        self.on_done, self.stop, self._asking = on_done, threading.Event(), threading.Lock()

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

    def take(self) -> int | None:
        if self.stop.is_set():
            return None
        try:
            return self.todo.popleft()
        except IndexError:
            return None

    def take_small(self) -> int | None:
        """The last queued index (the smallest, largest-first order): a light host's pick."""
        if self.stop.is_set():
            return None
        try:
            return self.todo.pop()
        except IndexError:
            return None


def cost(repo: Path, inv: list[str]) -> int:
    """Bytes of the test files an invocation names (dirs: their .py files), a cheap stand-in for run time."""
    # ponytail: size, not time; record per-invocation durations if largest-first still leaves a tail.
    total = 0
    for word in inv:
        path = repo / word.split("::", 1)[0]
        files = path.rglob("*.py") if path.is_dir() else [path]
        total += sum(f.stat().st_size for f in files if f.is_file())
    return total

