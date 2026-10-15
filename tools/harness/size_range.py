"""D-766 2: every commit in BASE..HEAD passes the size rule on its own, so bisect never meets a size red.

Usage: python tools/harness/size_range.py BASE HEAD

Each commit's tree is measured through git (``ls-tree`` + ``cat-file``, nothing is checked out
and no test runs) with the architecture guard's own rule (``size_limits.py``) against that
commit's ``size_ratchet.txt`` and ``size_units.txt``, and the rows at its first parent as the
base. Only what the commit touched is reported: its changed files, the units and packages that
hold them, and its changed ratchet rows (every key when it changed ``size_units.txt``). A commit
whose tree has no ``size_ratchet.txt`` (before D-766) is skipped. So "grow past the limit, split
in a later commit" is red on the growing commit even when the branch tip is green.
"""

from __future__ import annotations

import datetime as dt
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import PurePosixPath

import size_limits
from colcon_roots import colcon_roots

TRAILER = re.compile(r"^Safety-Review:[ \t]*\S", re.MULTILINE)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", check=True).stdout


def _show(commit: str, path: str) -> str | None:
    done = subprocess.run(["git", "show", f"{commit}:{path}"], capture_output=True, text=True, encoding="utf-8")
    return done.stdout if done.returncode == 0 else None


def _blobs(commit: str, paths: list[str]) -> dict[str, bytes]:
    """Contents of ``paths`` at ``commit`` in one ``git cat-file --batch``."""
    feed = "".join(f"{commit}:{path}\n" for path in paths).encode()
    out = subprocess.run(["git", "cat-file", "--batch"], input=feed, capture_output=True, check=True).stdout
    blobs, at = {}, 0
    for path in paths:
        header_end = out.index(b"\n", at)
        size = int(out[at:header_end].split()[2])
        blobs[path] = out[header_end + 1:header_end + 1 + size]
        at = header_end + 2 + size
    return blobs


def measure_commit(commit: str, units: list[str]) -> tuple[dict, dict, dict]:
    roots = colcon_roots()
    paths = _git("ls-tree", "-r", "--name-only", "-z", commit).split("\0")
    code = [p for p in paths if PurePosixPath(p).suffix in size_limits.CODE_SUFFIXES | size_limits.WEB_SUFFIXES]
    blobs = _blobs(commit, code)
    files = {path: blob.count(b"\n") + (not blob.endswith(b"\n") and bool(blob)) for path, blob in blobs.items()}
    xmls = [p for p in paths if p.endswith("/package.xml") and any(
        p.startswith(root + "/") and size_limits.is_prod(PurePosixPath(p[len(root) + 1:]).parts) for root in roots)]
    packages = {ET.fromstring(blob).findtext("name"): str(PurePosixPath(path).parent)
                for path, blob in _blobs(commit, xmls).items()}
    return size_limits.measure(files, packages, roots, units)


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
    ratchet = _show(commit, size_limits.RATCHET)
    if ratchet is None:
        return []
    rows, safety = size_limits.parse_ratchet(ratchet)
    units, small = size_limits.parse_units(_show(commit, size_limits.UNITS) or "")
    parents = _git("rev-list", "--parents", "-n", "1", commit).split()[1:]
    parent = parents[0] if parents else None
    # A merge of history from before D-766 (a parent without the ratchet) is the transition: its
    # rows are the new rows, measured on the merged tree, like the landing commit itself.
    transition = len(parents) > 1 and any(_show(p, size_limits.RATCHET) is None for p in parents)
    base_text = _show(parent, size_limits.RATCHET) if parent and not transition else None
    base_rows, base_safety = size_limits.parse_ratchet(base_text) if base_text is not None else (None, {})
    counts, over, owner = measure_commit(commit, units)
    listing = (_git("diff-tree", "-z", "--no-commit-id", "--name-only", "--no-renames", "-r", parent, commit)
               if parent else _git("ls-tree", "-z", "-r", "--name-only", commit))
    changed = [path for path in listing.split("\0") if path]
    keys = None
    if size_limits.UNITS not in changed and not transition:
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
    bad = size_limits.ratchet_problems(over, rows, safety, base_rows, date,
                                       lambda key: safety_commit(commit, key, safety), keys, base_safety)
    base_units_text = _show(parent, size_limits.UNITS) if parent and not transition else None
    base_units = size_limits.parse_units(base_units_text)[1] if base_units_text is not None else small
    if keys is None:
        bad += size_limits.unit_problems(counts, owner, units, small, base_units)
    return bad


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    base, head = argv
    commits = _git("rev-list", "--reverse", head, "^" + base).split()
    red = []
    for commit in commits:
        bad = check(commit)
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
