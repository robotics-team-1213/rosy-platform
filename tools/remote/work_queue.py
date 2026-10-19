"""The shared invocation queue remote_pytest's host workers pull from, and its largest-first cost."""
from __future__ import annotations

import collections
from pathlib import Path


class Work:
    """Invocation indices still to run and the exit code of each one run, shared by the host workers.

    deque.popleft/appendleft are atomic, so the threads need no lock."""

    def __init__(self, order):
        self.todo, self.codes, self.lost = collections.deque(order), {}, set()

    def take(self) -> int | None:
        try:
            return self.todo.popleft()
        except IndexError:
            return None

    def take_small(self) -> int | None:
        """The last queued index (the smallest, largest-first order): a light host's pick."""
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

