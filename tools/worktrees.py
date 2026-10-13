"""Keep ``.worktrees/`` from piling up: one gateway to create, one sweep to remove (D-761).

Usage (from the main checkout or any worktree of the repository)::

    python tools/worktrees.py status [--idle-hours N]
    python tools/worktrees.py prune [--apply] [--snapshot] [--idle-hours N]
    python tools/worktrees.py new <short-name> <type>/<topic> [--force-over-cap "<reason>"]

``prune`` is a dry run unless ``--apply``. Without ``--snapshot`` it removes only
what is lossless: a worktree that is clean (nothing modified, staged or
untracked), whose HEAD is an ancestor of ``main``, that is not locked, holds no
ignored file outside the cache directories, and has been idle ``--idle-hours``
(default 12); its branch is deleted once it is re-checked as an ancestor of main.
``--snapshot`` also takes idle worktrees that are dirty or unmerged: uncommitted
and untracked content goes into a commit on top of the worktree's HEAD, built
with a temporary index and tagged ``archive/<date>/wip/<name>``, and only a
snapshot that compares equal to the worktree lets it be removed. An unmerged
branch is always kept. Never removed: the main checkout, the worktree the tool
runs in, a locked worktree, one holding ignored non-cache files.

Idle is the time since the newest of: the tip commit, the worktree's
``logs/HEAD``, and the files ``git status`` lists. The index is not used: a
plain ``git status`` refreshes it.

``new`` runs the lossless prune, refuses at ``CAP`` worktrees, then runs
``git worktree add``. ``tools/land.py`` runs the same prune at the start of a
landing and ``rosy_harness.py lint`` warns through ``lint_note``. A bare
``git worktree add`` is not stopped by any of this. Standard library only.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CAP = 40
IDLE_HOURS = 12.0
TYPES = ("feat", "fix", "refactor", "docs", "uiux")  # D-372
# Ignored directories that are rebuilt, not written by hand; `*.egg-info` is matched by suffix.
CACHES = {"__pycache__", ".pytest_cache", "node_modules", ".ruff_cache", ".mypy_cache", "build", "install",
          "log", ".gradle", ".kotlin", ".cxx", ".venv", "dist", "graphify-out", ".omc"}
CLEAR = "python tools/worktrees.py prune --snapshot --idle-hours 72 --apply"


def git(cwd: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "core.quotepath=off", "-C", str(cwd), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", env=env)


def _must(result: subprocess.CompletedProcess, what: str) -> str:
    if result.returncode != 0:
        raise RuntimeError(f"{what} failed: {(result.stderr or result.stdout).strip()}")
    return result.stdout.strip()


def _mtime(path) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _newest(path: Path) -> float:
    """mtime of a file, or of the newest file below a directory (git lists an untracked directory once)."""
    if not path.is_dir():
        return _mtime(path)
    return max((_mtime(os.path.join(d, f)) for d, _, files in os.walk(path) for f in files), default=_mtime(path))


def _is_cache(rel: str) -> bool:
    parts = rel.rstrip("/").split("/")
    dirs = parts if rel.endswith("/") else parts[:-1]
    return any(d in CACHES or d.endswith(".egg-info") for d in dirs)


# --- inventory ------------------------------------------------------------------

def scan(cwd: Path) -> tuple[Path, list[dict]]:
    """The main checkout and one row per existing worktree under its ``.worktrees/``.

    Cheap facts only, three git calls for the whole set and no ``git status``:
    branch, tip, lock, merged into main, and ``last`` = newest of the tip commit
    time and the worktree's ``logs/HEAD``. ``judge`` adds the rest.
    """
    listing = _must(git(cwd, "worktree", "list", "--porcelain"), "git worktree list")
    blocks = [dict(line.partition(" ")[::2] for line in block.splitlines())
              for block in listing.split("\n\n") if block.strip()]
    root = Path(blocks[0]["worktree"])  # git lists the main working tree first
    holder = (root / ".worktrees").resolve()
    if not holder.is_dir():
        return root, []
    times = dict(line.split() for line in git(
        root, "for-each-ref", "--format=%(objectname) %(committerdate:unix)", "refs/heads").stdout.splitlines())
    merged = set(git(root, "for-each-ref", "--merged", "main", "--format=%(objectname)", "refs/heads").stdout.split())
    rows = []
    for block in blocks[1:]:
        path = Path(block["worktree"])
        if path.resolve().parent != holder or not path.is_dir():
            continue
        sha = block.get("HEAD", "")
        if sha in times:
            is_merged, tip = sha in merged, int(times[sha])
        else:  # detached at a commit no branch points to
            is_merged = git(root, "merge-base", "--is-ancestor", sha, "main").returncode == 0
            tip = int(git(root, "show", "-s", "--format=%ct", sha).stdout.strip() or 0)
        try:  # `.git` is a file "gitdir: <absolute or relative path>"
            git_dir = path / (path / ".git").read_text(encoding="utf-8").partition("gitdir:")[2].strip()
        except OSError:
            git_dir = path
        rows.append({"name": path.name, "path": path, "branch": block.get("branch", "").removeprefix("refs/heads/"),
                     "locked": "locked" in block, "merged": is_merged,
                     "last": max(tip, _mtime(git_dir / "logs" / "HEAD")), "changed": [], "ignored": []})
    return root, rows


def _status(path: Path) -> tuple[list[str], list[str]] | None:
    """(changed or untracked paths, ignored paths outside the caches), or None when git status fails."""
    result = git(path, "status", "--porcelain", "-z", "--ignored")
    if result.returncode != 0:
        return None
    changed, ignored = [], []
    fields = result.stdout.split("\0")
    i = 0
    while i < len(fields):
        code, rel = fields[i][:2], fields[i][3:]
        i += 2 if code[:1] in ("R", "C") else 1  # a rename or copy carries its source in the next field
        if not rel:
            continue
        if code != "!!":
            changed.append(rel)
        elif not _is_cache(rel):
            ignored.append(rel)
    return changed, ignored


def judge(row: dict, now: float, idle_hours: float, here: Path, lossless: bool = False, full: bool = False) -> None:
    """Set ``idle_h`` and ``verdict``; ``git status`` runs only when the cheap facts do not decide.

    ``lossless`` stops at an unmerged branch (the lossless prune keeps it anyway);
    ``full`` always reads the status, for the uncommitted count in ``status``.
    """
    cheap = ("locked" if row["locked"] else "current" if row["path"].resolve() == here
             else "active" if now - row["last"] < idle_hours * 3600
             else "needs snapshot" if lossless and not row["merged"] else None)
    if cheap is None or full:
        status = _status(row["path"])
        if status is None:
            cheap = cheap or "unreadable"
        else:
            row["changed"], row["ignored"] = status
            row["last"] = max([row["last"], *(_newest(row["path"] / rel) for rel in row["changed"])])
    row["idle_h"] = (now - row["last"]) / 3600
    row["verdict"] = cheap or ("active" if row["idle_h"] < idle_hours
                               else "holds ignored data" if row["ignored"]
                               else "needs snapshot" if row["changed"] or not row["merged"]
                               else "removable")


def _here(cwd: Path) -> Path:
    return Path(_must(git(cwd, "rev-parse", "--show-toplevel"), "git rev-parse --show-toplevel")).resolve()


# --- removal --------------------------------------------------------------------

def _snapshot(root: Path, row: dict, day: str) -> str:
    """Tag a commit that holds the worktree's modified, staged and untracked content; return the tag.

    The commit is built in a temporary index, so the worktree's own index and
    branch are not touched. The comparison uses that index too: against the
    worktree's own index, untracked files in the snapshot would read as deleted.
    """
    path = row["path"]
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        _must(git(path, "read-tree", "HEAD", env=env), "git read-tree")
        _must(git(path, "add", "-A", env=env), "git add -A (temporary index)")
        tree = _must(git(path, "write-tree", env=env), "git write-tree")
        commit = _must(git(path, "commit-tree", tree, "-p", "HEAD", "-m",
                           f"wip snapshot of worktree {row['name']} ({row['branch'] or 'detached'})"
                           f" before removal {day}"), "git commit-tree")
        tag = base = f"archive/{day}/wip/{row['name']}"
        n = 1
        while git(root, "rev-parse", "-q", "--verify", f"refs/tags/{tag}").returncode == 0:
            n += 1
            tag = f"{base}-{n}"
        _must(git(root, "tag", tag, commit), "git tag")
        diff = git(path, "diff", "--stat", commit, env=env)
        if diff.returncode != 0 or diff.stdout.strip():
            raise RuntimeError(f"snapshot {tag} differs from the worktree; kept both")
    return tag


def _remove(root: Path, row: dict, day: str) -> str:
    """Remove one judged worktree; return a note for the report. RuntimeError leaves it in place."""
    note = ""
    force = []
    if row["changed"]:
        note = f" snapshot={_snapshot(root, row, day)}"
        force = ["--force"]  # only after the snapshot compared equal; a clean one lets git re-check
    _must(git(root, "worktree", "remove", *force, str(row["path"])), "git worktree remove")
    branch = row["branch"]
    # `branch -d` would compare with the upstream, or with whatever the main checkout has
    # checked out; the tip is re-checked against main here instead, so -D drops no commit.
    if (branch and branch != "main" and row["merged"]
            and git(root, "merge-base", "--is-ancestor", f"refs/heads/{branch}", "main").returncode == 0):
        deleted = git(root, "branch", "-D", branch)
        note += " branch deleted" if deleted.returncode == 0 else f" branch kept ({deleted.stderr.strip()})"
    return note


def prune(cwd: Path, *, idle_hours: float = IDLE_HOURS, snapshot: bool = False, apply: bool = False,
          quiet: bool = False, now: float | None = None) -> int:
    """Remove (or, without ``apply``, list) what may go; return how many. ``quiet`` drops the KEEP lines."""
    now = time.time() if now is None else now
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    root, rows = scan(cwd)
    here = _here(cwd)
    done = 0
    for row in sorted(rows, key=lambda r: r["name"]):
        judge(row, now, idle_hours, here, lossless=not snapshot)
        label = f"{row['name']} [{row['branch'] or 'detached'}]"
        if row["verdict"] != "removable" and not (snapshot and row["verdict"] == "needs snapshot"):
            if not quiet:
                print(f"KEEP    {label} {row['verdict']}")
            continue
        kind = ("dirty" if row["changed"] else "clean") + "+" + ("merged" if row["merged"] else "unmerged")
        if not apply:
            print(f"PLAN    {label} {kind} idle={row['idle_h']:.0f}h")
            done += 1
            continue
        try:
            print(f"REMOVED {label} {kind}{_remove(root, row, day)}")
            done += 1
        except (RuntimeError, OSError) as exc:
            print(f"FAIL    {label} {exc}")
    if done or not quiet:
        print(f"[worktrees] {'removed' if apply else 'would remove'} {done} of {len(rows)} under {root / '.worktrees'}")
    return done


# --- commands -------------------------------------------------------------------

def _table(rows: list[dict], file=None) -> None:
    for row in rows:
        print(f"{row['name']:<32} {row['branch'] or '(detached)':<44} {'merged' if row['merged'] else 'unmerged':<8} "
              f"{len(row['changed']):>5} {row['idle_h']:>6.0f}h {'locked' if row['locked'] else '-':<6} {row['verdict']}",
              file=file)


def cmd_status(cwd: Path, idle_hours: float, now: float) -> int:
    root, rows = scan(cwd)
    here = _here(cwd)
    for row in rows:
        judge(row, now, idle_hours, here, full=True)
    print(f"{'name':<32} {'branch':<44} {'main':<8} {'dirty':>5} {'idle':>7} {'lock':<6} verdict")
    _table(sorted(rows, key=lambda r: -r["idle_h"]))
    print(f"[worktrees] {len(rows)} under {root / '.worktrees'} (cap {CAP})")
    return 0


def cmd_new(cwd: Path, name: str, branch: str, reason: str | None, now: float) -> int:
    kind, _, topic = branch.partition("/")
    if kind not in TYPES or not topic:
        print(f"branch must be <type>/<topic> with <type> one of {', '.join(TYPES)} (D-372): {branch!r}",
              file=sys.stderr)
        return 1
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        print(f"short name must be one path component of letters, digits, '.', '_' or '-': {name!r}", file=sys.stderr)
        return 1
    root, _ = scan(cwd)
    if (root / ".worktrees" / name).exists():
        print(f"{root / '.worktrees' / name} already exists", file=sys.stderr)
        return 1
    if git(root, "rev-parse", "-q", "--verify", f"refs/heads/{branch}").returncode == 0:
        print(f"branch {branch} already exists", file=sys.stderr)
        return 1
    try:
        prune(cwd, apply=True, quiet=True, now=now)  # lossless only; never --snapshot from here
    except (RuntimeError, OSError) as exc:
        print(f"[worktrees] warning: prune failed, continuing: {exc}", file=sys.stderr)
    rows = scan(cwd)[1]
    if len(rows) >= CAP and reason is None:
        here = _here(cwd)
        oldest = sorted(rows, key=lambda r: r["last"])[:10]
        for row in oldest:
            judge(row, now, IDLE_HOURS, here)
        print(f"refused: {len(rows)} worktrees under {root / '.worktrees'}, the cap is {CAP}. Longest idle:",
              file=sys.stderr)
        _table(oldest, file=sys.stderr)
        print(f"clear idle ones (uncommitted work is kept in archive/<date>/wip/<name> tags):\n  {CLEAR}\n"
              'or, during an incident: add --force-over-cap "<reason>"', file=sys.stderr)
        return 1
    if len(rows) >= CAP:
        print(f"[worktrees] over the cap ({len(rows)} >= {CAP}), forced: {reason}")
    add = ["worktree", "add", "--relative-paths", f".worktrees/{name}", "-b", branch, "main"]
    result = git(root, *add)
    if result.returncode != 0 and "relative-paths" in result.stderr:  # git older than 2.48
        add.remove("--relative-paths")
        result = git(root, *add)
    _must(result, "git worktree add")
    print(root / ".worktrees" / name)
    return 0


def lint_note(repo: Path, now: float | None = None) -> str | None:
    """A warning line for ``rosy_harness.py lint``: at the cap, or merged worktrees sit idle.

    Count and cheap facts only (no ``git status`` per worktree). None in CI,
    outside git, and in a repository with no ``.worktrees/``.
    """
    if os.environ.get("CI"):
        return None
    try:
        rows = scan(repo)[1]
    except (RuntimeError, OSError, IndexError):
        return None
    now = time.time() if now is None else now
    idle = sum(1 for r in rows if r["merged"] and not r["locked"] and now - r["last"] >= IDLE_HOURS * 3600)
    if len(rows) < CAP and not idle:
        return None
    return (f"worktrees: {len(rows)} under .worktrees/ (cap {CAP}), {idle} merged and idle {IDLE_HOURS:.0f} h or more;"
            f" sweep with `python tools/worktrees.py prune --apply`, dirty or unmerged ones with `{CLEAR}`")


def main(argv: list[str] | None = None, now: float | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status", help="read-only table of every worktree under .worktrees/")
    pruner = sub.add_parser("prune", help="remove idle worktrees without losing work (dry run by default)")
    pruner.add_argument("--apply", action="store_true", help="act; without it the plan is printed")
    pruner.add_argument("--snapshot", action="store_true",
                        help="also take dirty or unmerged worktrees, after tagging uncommitted work")
    for command in (status, pruner):
        command.add_argument("--idle-hours", type=float, default=IDLE_HOURS)
    new = sub.add_parser("new", help="create .worktrees/<short-name> on a new branch from main")
    new.add_argument("name", metavar="short-name")
    new.add_argument("branch", metavar="type/topic")
    new.add_argument("--force-over-cap", metavar="REASON", help=f"create although {CAP} or more worktrees exist")
    args = parser.parse_args(argv)
    now = time.time() if now is None else now
    try:
        if args.command == "status":
            return cmd_status(Path.cwd(), args.idle_hours, now)
        if args.command == "new":
            return cmd_new(Path.cwd(), args.name, args.branch, args.force_over_cap, now)
        prune(Path.cwd(), idle_hours=args.idle_hours, snapshot=args.snapshot, apply=args.apply, now=now)
        return 0
    except RuntimeError as exc:
        print(f"[worktrees] STOP: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
