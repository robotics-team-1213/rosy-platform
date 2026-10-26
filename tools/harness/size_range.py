"""D-766 2: every commit in BASE..HEAD passes the size rule on its own, so bisect never meets a size red.

Usage: python tools/harness/size_range.py BASE HEAD

Each commit's tree is measured through git (``ls-tree`` + ``cat-file``, nothing is checked out
and no test runs) with that commit's own ``size_limits.py`` (the architecture guard's rule) against that
commit's ``size_ratchet.txt`` and ``size_units.txt``, and the rows at its first parent as the
base. Only what the commit touched is reported: its changed files, the units and packages that
hold them, and its changed ratchet rows (every key when it changed ``size_units.txt``). A commit
whose tree has no ``size_ratchet.txt`` (before D-766) is skipped. So "grow past the limit, split
in a later commit" is red on the growing commit even when the branch tip is green.
"""

from __future__ import annotations

import datetime as dt
import functools
import os
import re
import subprocess
import sys
import types
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor
from pathlib import PurePosixPath

import size_limits
from colcon_roots import colcon_roots

TRAILER = re.compile(r"^Safety-Review:[ \t]*\S", re.MULTILINE)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", check=True).stdout


# Keyed by blob oid: commits of one range share almost every blob, so each is read once per run
# instead of once per commit (3,235 commits ran for hours in pre-push on 2026-10-27).
_TEXT: dict[str, str] = {}
_LINES: dict[str, int] = {}
_SCRIPTS: dict[tuple, int] = {}
_NAMES: dict[str, str | None] = {}
_RULES: dict[str, types.ModuleType] = {}
_path = functools.lru_cache(maxsize=None)(PurePosixPath)  # immutable, so a shared instance is the same value


@functools.lru_cache(maxsize=8)
def _tree(commit: str) -> dict[str, str]:
    """``path -> blob oid`` of ``commit``'s tree."""
    tree = {}
    for entry in _git("ls-tree", "-r", "-z", commit).split("\0"):
        if entry:
            meta, path = entry.split("\t", 1)
            _, kind, oid = meta.split()
            if kind == "blob":
                tree[path] = oid
    return tree


def _read(oids) -> dict[str, bytes]:
    """Contents of the blobs ``oids`` in one ``git cat-file --batch``."""
    oids = list(dict.fromkeys(oids))
    if not oids:
        return {}
    feed = "".join(f"{oid}\n" for oid in oids).encode()
    out = subprocess.run(["git", "cat-file", "--batch"], input=feed, capture_output=True, check=True).stdout
    blobs, at = {}, 0
    for oid in oids:
        header_end = out.index(b"\n", at)
        size = int(out[at:header_end].split()[2])
        blobs[oid] = out[header_end + 1:header_end + 1 + size]
        at = header_end + 2 + size
    return blobs


def _show(commit: str, path: str) -> str | None:
    oid = _tree(commit).get(path)
    if oid is None:
        return None
    if oid not in _TEXT:  # newlines as the former ``git show`` read with text=True gave them
        _TEXT[oid] = _read([oid])[oid].decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return _TEXT[oid]


def rule_at(commit: str):
    """The commit's own ``size_limits.py``, so a later rule change never reddens an earlier commit."""
    oid = _tree(commit).get("tools/harness/size_limits.py")
    if oid is None:
        return size_limits
    if oid not in _RULES:
        module = types.ModuleType("size_limits_at_commit")
        exec(compile(_show(commit, "tools/harness/size_limits.py"), "size_limits.py", "exec"), module.__dict__)
        module.PurePosixPath = _path  # measure() parses every path once per package; the paths repeat
        _RULES[oid] = module
    return _RULES[oid]


def measure_commit(commit: str, units: list[str], limits=size_limits) -> tuple[dict, dict, dict]:
    roots = colcon_roots()
    tree = _tree(commit)
    code = [p for p in tree if PurePosixPath(p).suffix in limits.CODE_SUFFIXES | limits.WEB_SUFFIXES]
    script_rule = getattr(limits, "inline_script_lines", None)  # absent before revision 2
    html = [p for p in code if p.endswith(".html")] if script_rule else []
    missing = [tree[p] for p in code if tree[p] not in _LINES]
    missing += [tree[p] for p in html if (script_rule, tree[p]) not in _SCRIPTS]
    for oid, blob in _read(missing).items():
        _LINES[oid] = blob.count(b"\n") + (not blob.endswith(b"\n") and bool(blob))
        if script_rule:
            _SCRIPTS[script_rule, oid] = script_rule(blob.decode("utf-8", "replace"))
    files = {path: _LINES[tree[path]] for path in code}
    xmls = [p for p in tree if p.endswith("/package.xml") and any(
        p.startswith(root + "/") and limits.is_prod(PurePosixPath(p[len(root) + 1:]).parts) for root in roots)]
    for oid, blob in _read(tree[p] for p in xmls if tree[p] not in _NAMES).items():
        _NAMES[oid] = ET.fromstring(blob).findtext("name")
    packages = {_NAMES[tree[path]]: str(PurePosixPath(path).parent) for path in xmls}
    packages.update(getattr(limits, "STANDALONE", {}))
    if not script_rule:
        return limits.measure(files, packages, roots, units)
    scripts = {path: _SCRIPTS[script_rule, tree[path]] for path in html}
    return limits.measure(files, packages, roots, units, scripts)


def safety_commit(at: str, key: str, safety: dict) -> tuple[dt.date, bool] | None:
    """(date, has Safety-Review trailer) of the commit up to ``at`` that added ``key``'s safety row."""
    allowed, expiry = safety[key]
    row = f"safety {allowed} {key} {expiry.isoformat()}"
    sha = _git("log", "-1", "--format=%H", "-S", row, at, "--", size_limits.RATCHET).strip()
    if not sha:
        return None
    date, _, message = _git("log", "-1", "--format=%cs%n%B", sha).partition("\n")
    return dt.date.fromisoformat(date), bool(TRAILER.search(message))


def check(commit: str) -> list[str]:
    limits = rule_at(commit)
    ratchet = _show(commit, limits.RATCHET)
    if ratchet is None:
        return []
    rows, safety = limits.parse_ratchet(ratchet)
    units, small = limits.parse_units(_show(commit, limits.UNITS) or "")
    parents = _git("rev-list", "--parents", "-n", "1", commit).split()[1:]
    parent = parents[0] if parents else None
    # A merge of history from before D-766 (a parent without the ratchet) is the transition: its
    # rows are the new rows, measured on the merged tree, like the landing commit itself.
    transition = len(parents) > 1 and any(_show(p, limits.RATCHET) is None for p in parents)
    base_text = _show(parent, limits.RATCHET) if parent and not transition else None
    base_rows, base_safety = limits.parse_ratchet(base_text) if base_text is not None else (None, {})
    if base_rows is not None and len(parents) > 1:  # a merge: each side's rows were checked on that side
        for other in parents[1:]:
            for key, count in limits.parse_ratchet(_show(other, limits.RATCHET))[0].items():
                base_rows[key] = max(count, base_rows.get(key, count))
    counts, over, owner = measure_commit(commit, units, limits)
    listing = (_git("diff-tree", "-z", "--no-commit-id", "--name-only", "--no-renames", "-r", parent, commit)
               if parent else _git("ls-tree", "-z", "-r", "--name-only", commit))
    changed = [path for path in listing.split("\0") if path]
    keys = None
    if limits.UNITS not in changed and not transition:
        roots = colcon_roots()
        keys = set()
        for path in changed:
            root = next((r for r in roots if path.startswith(r + "/")), None)
            keys.add(path[len(root) + 1:] if root else path)
            key = owner.get(path)
            while key:  # the unit or package, and every enclosing unit up to the package
                keys.add(key)
                key = owner.get(key) if key in units else None
        keys |= {key for key in {*rows, *(base_rows or {})} if (base_rows or {}).get(key) != rows.get(key)}
        keys |= {key for key in {*safety, *base_safety} if safety.get(key) != base_safety.get(key)}  # whole rows
    date = dt.date.fromisoformat(_git("log", "-1", "--format=%cs", commit).strip())
    bad = limits.ratchet_problems(over, rows, safety, base_rows, date,
                                       lambda key: safety_commit(commit, key, safety), keys, base_safety)
    base_units_text = _show(parent, limits.UNITS) if parent and not transition else None
    base_units = limits.parse_units(base_units_text)[1] if base_units_text is not None else small
    if keys is None:
        bad += limits.unit_problems(counts, owner, units, small, base_units)
    return bad


CHUNK = 50  # fewer commits than this per extra process cost more to start than they save


def _check_all(commits: list[str]) -> list[list[str]]:
    return [check(commit) for commit in commits]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    base, head = argv
    commits = _git("rev-list", "--reverse", head, "^" + base).split()
    # Contiguous chunks, one per process, so neighbouring commits share a process's blob caches.
    workers = min(os.cpu_count() or 1, len(commits) // CHUNK + 1)
    size = -(-len(commits) // workers) or 1
    chunks = [commits[at:at + size] for at in range(0, len(commits), size)]
    if workers > 1:
        with ProcessPoolExecutor(workers) as pool:
            verdicts = [bad for chunk in pool.map(_check_all, chunks) for bad in chunk]
    else:
        verdicts = [check(commit) for commit in commits]
    red = []
    for commit, bad in zip(commits, verdicts):
        if bad:
            red.append(_git("log", "-1", "--format=%h %s", commit).strip() + "\n    " + "\n    ".join(bad))
    print(f"[size-range] {len(commits)} commit(s) checked")
    if red:
        print("[size-range] commits that do not pass the D-766 size rule on their own (split in the same"
              " commit or an earlier one):\n" + "\n".join(red), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
