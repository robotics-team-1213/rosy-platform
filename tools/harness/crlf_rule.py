"""A commit may not turn an LF text blob into CRLF (2026-11-17: a ``hash-object --no-filters`` commit stored whole-file CRLF).

``problems(commit, git)`` lists the paths a non-merge commit committed since ``RULE_SINCE`` added or changed with CRLF
that its parent version did not have. ``.gitattributes`` ``eol=crlf`` / ``binary`` paths and blobs with a NUL are exempt.
Enforced by tools/harness/size_range.py.
"""

from __future__ import annotations

import datetime as dt
import subprocess

RULE_SINCE = dt.datetime.fromisoformat("2026-11-17T20:00:00+09:00")


def _blob(sha: str) -> bytes:
    return subprocess.run(["git", "cat-file", "blob", sha], capture_output=True, check=True).stdout


def _crlf(data: bytes) -> bool:
    return b"\r\n" in data and b"\0" not in data


def problems(commit: str, git) -> list[str]:
    """``git`` is size_range._git (text output); the caller has already skipped merges."""
    if dt.datetime.fromisoformat(git("log", "-1", "--format=%cI", commit).strip()) < RULE_SINCE:
        return []
    raw = git("diff-tree", "-r", "-z", "--no-commit-id", "--no-renames", "--diff-filter=AM", commit).split("\0")
    found = []
    for meta, path in zip(raw[0::2], raw[1::2]):
        _, _, old, new, _ = meta.split()
        if not _crlf(_blob(new)) or (set(old) != {"0"} and _crlf(_blob(old))):
            continue
        attrs = git("check-attr", "--source", commit, "eol", "binary", "text", "--", path)
        if not any(w in attrs for w in ("eol: crlf", "binary: set", "text: unset")):
            found.append(f"{path}: CRLF line endings added (the repo stores LF; use git add so .gitattributes normalises)")
    return found
