"""The browser tier's chunks: ``land.py`` splits the real-Chromium test files into serial invocations.

remote_pytest runs browser invocations in lanes beside each host's main worker (``remote/work_queue.py``), so
smaller chunks finish sooner. Chunk membership depends only on the committed tree (file sizes, the ALONE
list), never on run timings, so ``land_cache`` keys (the argv) stay the same from run to run.

Grouping rule: a chunk is a list of whole files, and two files that bind the same fixed port must share a chunk
(chunks run at once on one host). No two browser files do today; ``test/test_land.py`` fails when two start to,
and the fix is to list them together here.
"""

from __future__ import annotations

from pathlib import Path

from remote_pytest import ALONE_ENV, BROWSER_ENV

# 2026-10-26 FULL: 4 chunks took 878/772/536/487 s (2673 s); 8 bring a chunk near 5 min.
CHUNKS = 8
# Load-sensitive: their ids failed under load and passed alone (test/flaky_quarantine.txt LOAD-FLAKY rows), so
# they run in one chunk with no lane job of the same run beside it.
ALONE = frozenset({
    "middleware/robot_ui/robot/test/test_action_groups_browser.py",
    "operations/fleet/test/test_console_card_trips_browser.py",
    "operations/fleet/test/test_site_map_browser.py",
})


def balanced(wt: Path, paths: list[str], n: int) -> list[list[str]]:
    """paths in at most n lists of near-equal total size: largest first, each into the lightest list.

    A sub-list of one pack() group keeps its basenames apart."""
    # shortcut: file size stands in for run time; commit a measured per-file table if chunks skew.
    size = {p: (wt / p).stat().st_size if (wt / p).is_file() else 0 for p in paths}
    bins: list[tuple[list[int], list[str]]] = [([0], []) for _ in range(min(n, len(paths)))]
    for path in sorted(paths, key=lambda p: (-size[p], p)):  # ties by name: the same chunks for any input order
        total, members = min(bins, key=lambda b: (b[0][0], len(b[1])))  # empty files still fill every list
        total[0] += size[path]
        members.append(path)
    return [sorted(members) for _, members in bins]


def chunks(wt: Path, paths: list[str], n: int = CHUNKS) -> list[list[str]]:
    """Browser invocations for one pack() group: the ALONE files in one chunk marked ALONE_ENV, the rest balanced.

    Raises RuntimeError unless every path is in exactly one chunk: a lost file would land untested."""
    alone = sorted(p for p in paths if p in ALONE)
    out = [[BROWSER_ENV, ALONE_ENV, *alone]] if alone else []
    out += [[BROWSER_ENV, *chunk] for chunk in balanced(wt, [p for p in paths if p not in ALONE], n)]
    check(paths, out)
    return out


def check(paths: list[str], invocations: list[list[str]]) -> None:
    """Every path in exactly one invocation, nothing else in any."""
    named = [w for inv in invocations for w in inv if w not in (BROWSER_ENV, ALONE_ENV)]
    if sorted(named) != sorted(paths) or not all(inv[-1] not in (BROWSER_ENV, ALONE_ENV) for inv in invocations):
        raise RuntimeError(f"browser chunks lost, repeated or emptied files: {sorted(paths)} -> {invocations}")
