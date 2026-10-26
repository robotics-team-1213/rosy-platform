"""tools/land_browser.py: the browser tier in file-level chunks that cover every file exactly once."""

from __future__ import annotations

import random
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import land  # noqa: E402
import land_browser  # noqa: E402
import browser_scope  # noqa: E402  (test/, on sys.path through land's remote_pytest)

ENV = (land_browser.BROWSER_ENV, land_browser.ALONE_ENV)
EVERY = browser_scope.targets(["test/browser_harness.py"])  # maps to browser_scope.EVERYTHING


def files(invocations):
    return [w for inv in invocations for w in inv if w not in ENV]


def test_every_browser_file_runs_once_in_chunks_that_do_not_move_between_runs():
    assert len(EVERY) > 50  # the real tree, not an empty selection
    tier = [inv for group in land.pack(ROOT, EVERY) for inv in land_browser.chunks(ROOT, group)]
    assert sorted(files(tier)) == sorted(EVERY)  # the union is the file set: nothing lost, nothing repeated
    assert len(files(tier)) == len(set(files(tier)))  # disjoint
    assert all(inv[0] == land_browser.BROWSER_ENV and inv[-1] not in ENV for inv in tier)  # opted in, never empty
    shuffled = random.Random(7).sample(EVERY, len(EVERY))
    for group in land.pack(ROOT, EVERY):  # land_cache keys are the argv: the same tree gives the same chunks
        again = [p for p in shuffled if p in group]
        assert land_browser.chunks(ROOT, again) == land_browser.chunks(ROOT, group)
        assert len(land_browser.chunks(ROOT, group)) <= land_browser.CHUNKS + 1


def test_alone_files_share_one_chunk_marked_to_run_without_lanes(tmp_path):
    alone = sorted(land_browser.ALONE)
    paths = [*alone, "a_browser.py", "b_browser.py"]
    invs = land_browser.chunks(tmp_path, paths, 4)
    assert invs[0] == [*ENV, *alone]
    assert invs[1:] == [[land_browser.BROWSER_ENV, "a_browser.py"], [land_browser.BROWSER_ENV, "b_browser.py"]]
    assert land_browser.chunks(tmp_path, ["a_browser.py"], 4) == [[land_browser.BROWSER_ENV, "a_browser.py"]]


def test_files_split_into_size_balanced_chunks(tmp_path):
    sizes = {"a_browser.py": 900, "b_browser.py": 500, "c_browser.py": 400, "d_browser.py": 300,
             "e_browser.py": 200, "f_browser.py": 100}
    for name, size in sizes.items():
        (tmp_path / name).write_text("x" * size)
    chunks = land_browser.balanced(tmp_path, sorted(sizes), 4)
    assert sorted(p for c in chunks for p in c) == sorted(sizes) and len(chunks) == 4
    totals = sorted(sum(sizes[p] for p in c) for c in chunks)
    assert totals == [500, 500, 500, 900]  # LPT: no chunk waits behind more than the largest file
    assert land_browser.balanced(tmp_path, ["a_browser.py"], 4) == [["a_browser.py"]]  # never an empty invocation


def test_a_missing_or_repeated_chunk_stops_the_tier(monkeypatch, tmp_path):
    paths = ["a_browser.py", "b_browser.py", "c_browser.py"]
    real = land_browser.balanced
    monkeypatch.setattr(land_browser, "balanced", lambda *a: real(*a)[:-1])  # a chunk dropped
    with pytest.raises(RuntimeError, match="lost"):
        land_browser.chunks(tmp_path, paths, 3)
    monkeypatch.setattr(land_browser, "balanced", lambda *a: [*real(*a), ["a_browser.py"]])  # a file twice
    with pytest.raises(RuntimeError):
        land_browser.chunks(tmp_path, paths, 3)
    with pytest.raises(RuntimeError):
        land_browser.check(paths, [[land_browser.BROWSER_ENV, *paths], [land_browser.BROWSER_ENV]])  # an empty one


def test_no_two_browser_files_bind_the_same_fixed_port():
    """Chunks of one run share a host at once; files binding one fixed port must be listed in one chunk."""
    bind = re.compile(r"\bport\s*=\s*(\d{4,5})\b|\.bind\(\(\s*[^,]+,\s*(\d{4,5})\s*\)\)")
    owners: dict[str, set[str]] = {}
    for path in EVERY:
        for match in bind.finditer((ROOT / path).read_text(encoding="utf-8", errors="replace")):
            owners.setdefault(match.group(1) or match.group(2), set()).add(path)
    assert {port: sorted(p) for port, p in owners.items() if len(p) > 1} == {}
    assert owners.get("6000") == {"test/test_games_board_browser.py"}  # the scan sees the one fixed port today
