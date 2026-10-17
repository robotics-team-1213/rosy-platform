"""Rules ``tools/worktrees.py`` and ``tools/land.py`` share (D-790, amends D-761).

- A landed worktree (merged into main, a commit of its own in its branch reflog) that is clean
  waits ``LANDED_IDLE_HOURS`` (1 h), not 72 h, before anyone's lossless prune takes it.
- ``stale_history``: a branch on the pre-rewrite line (more than ``STALE_COMMITS`` commits not in
  main, or forked from main at or before ``REWRITE_BASE``) would re-import the old history; ``new``
  does not base on it and ``land.py`` does not land it.
- Orphan directories (under ``.worktrees/``, not registered with git): ``orphan_content`` sums them
  up; ``clear_orphan`` removes empty ones and ones holding only caches or ``.omc/state``, and
  archives the rest to ``$ROSY_SCRATCH/worktree-orphans/<name>-<date>.zip`` (Python ``zipfile``,
  re-opened and counted) before the directory goes.

Standard library only.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path

LANDED_IDLE_HOURS = 1.0
STALE_COMMITS = 2_000
# main was rewritten after this commit (2026-09-22 09:55:14 +0900); branches cut before the rewrite share
# only it with main and carry ~13,800 commits of the old line (feat/integrated-learning-pipeline, 2026-10-17).
REWRITE_BASE = "ad86fca808"
REWRITE_TIME = 1790038514  # its committer time: a merge-base this old or older is on the old line


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "core.quotepath=off", "-C", str(cwd), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def stale_history(cwd: Path, tip: str, base: str = "main") -> str | None:
    """Why ``tip`` is on the pre-rewrite history relative to ``base``, or None (also for unknown refs)."""
    count = _git(cwd, "rev-list", "--count", f"--max-count={STALE_COMMITS + 1}", f"{base}..{tip}")
    if count.returncode != 0:
        return None
    if int(count.stdout.strip() or 0) > STALE_COMMITS:
        return f"more than {STALE_COMMITS} commits not in {base}: the pre-rewrite history"
    fork = _git(cwd, "merge-base", base, tip)
    if fork.returncode != 0 or not fork.stdout.strip():
        return f"no common history with {base}" if fork.returncode == 1 else None
    sha = fork.stdout.strip()
    when = int(_git(cwd, "show", "-s", "--format=%ct", sha).stdout.strip() or 0)
    if when <= REWRITE_TIME:
        day = time.strftime("%Y-%m-%d", time.localtime(when))
        return f"forks from {base} at {sha[:10]} ({day}), before the history rewrite after {REWRITE_BASE}"
    return None


# --- orphan directories -------------------------------------------------------------

def scratch() -> Path | None:
    """Where orphan archives go: ``$ROSY_SCRATCH``, else ``X:/DevTemp`` on a lab PC that has it."""
    base = os.environ.get("ROSY_SCRATCH") or ("X:/DevTemp" if os.name == "nt" and Path("X:/DevTemp").is_dir() else "")
    return Path(base) / "worktree-orphans" if base else None


def orphan_content(path: Path, droppable) -> tuple[str, list[Path], float]:
    """(summary, files worth keeping, newest mtime) of an orphan directory.

    ``droppable(rel)`` says a repository-relative path is a cache or ``.omc/state`` (rebuilt, not
    written by hand); such files are neither archived nor counted as content.
    """
    keep, total, newest, size = [], 0, os.path.getmtime(path), 0
    for folder, dirs, files in os.walk(path):
        inside = Path(folder).relative_to(path).as_posix()
        for name in files:
            file = Path(folder, name)
            total += 1
            try:
                info = file.lstat()
            except OSError:
                info = None
            newest = max(newest, info.st_mtime if info else newest)
            if not droppable(name if inside == "." else f"{inside}/{name}"):
                keep.append(file)
                size += info.st_size if info else 0
    if not total:
        return "empty", [], newest
    if not keep:
        return f"only caches and .omc/state ({total} files)", [], newest
    return f"{len(keep)} files, {size / 1e6:.1f} MB to archive", sorted(keep), newest


def _archive(path: Path, keep: list[Path], day: str) -> Path:
    """Zip ``keep`` under ``scratch()``, then re-open the zip and check every member; return its path."""
    folder = scratch()
    if folder is None:
        raise RuntimeError("holds files and no archive folder is set: set ROSY_SCRATCH; kept")
    folder.mkdir(parents=True, exist_ok=True)
    target = base = folder / f"{path.name}-{day}.zip"
    for n in range(2, 100):
        if not target.exists():
            break
        target = base.with_name(f"{base.stem}-{n}.zip")
    with zipfile.ZipFile(target, "x", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for file in keep:
            archive.write(file, file.relative_to(path).as_posix())
    with zipfile.ZipFile(target) as archive:
        bad, names = archive.testzip(), archive.namelist()
    want = sorted(file.relative_to(path).as_posix() for file in keep)
    if bad is not None or sorted(names) != want:
        raise RuntimeError(f"archive {target} did not verify ({bad or f'{len(names)} of {len(want)} files'}); kept")
    return target


def _writable_and_retry(func, target, *_):
    os.chmod(target, stat.S_IWRITE)  # git object files are read-only on Windows
    func(target)


def clear_orphan(path: Path, keep: list[Path], droppable, day: str) -> str:
    """Remove one judged orphan, archiving its kept files first; a note for the report.

    The directory is read again: anything added or removed since the scan keeps it.
    """
    _, now_keep, _ = orphan_content(path, droppable)
    if now_keep != keep:
        raise RuntimeError("changed since the scan; kept")
    note = f" archived to {_archive(path, keep, day)}," if keep else ""
    handler = {"onexc" if sys.version_info >= (3, 12) else "onerror": _writable_and_retry}
    shutil.rmtree(path, **handler)
    return note + (" orphan directory removed" if keep else " orphan directory without content removed")
