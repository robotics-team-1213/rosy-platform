"""Keep ``.worktrees/`` from piling up: one gateway to create, one sweep to remove (D-761, D-790).

Usage (from the main checkout or any worktree of the repository)::

    python tools/worktrees.py status [--idle-hours N]
    python tools/worktrees.py prune [--apply] [--snapshot] [--all] [--idle-hours N]
    python tools/worktrees.py new <short-name> <type>/<topic> [--from REF] [--owner TEXT]
                                  [--prune | --no-prune] [--force-over-cap "<reason>"]

``prune`` is a dry run unless ``--apply``. Without ``--snapshot`` it removes only
what is lossless: a worktree that is clean (nothing modified, staged or
untracked), whose HEAD is an ancestor of ``main``, that is not locked, has no
rebase/merge/bisect/cherry-pick in progress, holds no ignored file outside the
cache directories, and has been idle long enough. Long enough is 1 h when its branch landed (a
commit of its own in the branch reflog, D-790), whoever made it; no wait at all for the caller's
own landed worktree (owner note equal to the caller's identity, session included); ``--idle-hours``
(default 72) for the rest, a just-created empty worktree included. Its branch is
deleted by exact sha (``git update-ref -d <ref> <sha>``) once that sha is an
ancestor of main. ``--snapshot``, which only a person or the dispatcher runs,
also takes idle worktrees that are dirty or unmerged: the working files (modified,
staged, untracked) go into a commit on top of the worktree's HEAD, built in a
temporary index and kept as ``refs/wip/<date>/<name>`` (not a tag: ``git push
--tags`` must not publish it); only a snapshot that matches the worktree lets it
be removed. An unmerged branch is always kept. ``--snapshot`` takes a dirty or unmerged one
only if the caller made it (the owner note ``new`` writes); ``--all`` also takes peers' and
unknown ones. Never removed: the main checkout, the worktree the tool runs in, a locked one,
one on ``main``, one holding ignored non-cache files, a ``stale-history`` one (D-790: its
branch is on the pre-rewrite line; a person archives it). Snapshots: ``git for-each-ref
refs/wip``; restore with ``git worktree add <path> <ref>`` or ``git checkout <ref> -- .``.

``status`` also flags ``landed-dirty`` (branch in main, uncommitted files: move the work to a
new worktree) and ``orphan`` directories git no longer lists, with what they hold; the lossless
prune removes an orphan idle 1 h, archiving files other than caches and ``.omc/state`` first
(``tools/worktree_rules.py``).

Idle is the time since the newest of: the tip commit, the worktree's ``.git``
file and ``logs/HEAD``, and the files ``git status`` lists. No ``logs/HEAD``
reads as active. The index is not used: a plain ``git status`` refreshes it.

``new`` and ``tools/land.py`` only report what the lossless prune would remove
(``--prune`` applies it, ``--no-prune`` is silent); ``new`` refuses at ``CAP``
worktrees and names each one removable now and by whom. ``rosy_harness.py lint`` warns through
``lint_note``. A bare ``git worktree add`` is not stopped by any of this. Standard library only.
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

import worktree_rules as rules

CAP = 50  # everything under .worktrees/, orphan directories included
IDLE_HOURS = 72.0
STALE_LOCK = 30 * 60  # seconds after which another run's prune lock is taken over
TYPES = ("feat", "fix", "refactor", "docs", "uiux")  # D-372
# Ignored directories that are rebuilt, not written by hand, at any depth; `*.egg-info` by suffix.
CACHES = {"__pycache__", ".pytest_cache", "node_modules", ".ruff_cache", ".mypy_cache", ".gradle", ".kotlin",
          ".cxx", ".venv", "graphify-out"}
# Caches only at the worktree root or where a marker proves it (see _generated_beside).
GENERATED = {"build", "install", "log", "dist"}
BUSY = ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG")
ZERO = "0" * 40
SNAPSHOT = ("needs snapshot", "landed-dirty")  # verdicts only --snapshot takes, and only from the owner or --all
SWEEP = "python tools/worktrees.py prune --apply"
HINT = (f"see `python tools/worktrees.py status`; `{SWEEP}` removes only clean, merged, idle ones, whoever"
        " made them; `--snapshot` is for a person or the dispatcher, not for every session")


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


def _generated_beside(parent: Path) -> bool:
    """``parent`` proves its build/install/log/dist are generated: a gradle module or a colcon workspace."""
    if any(parent.glob("build.gradle*")):
        return True
    colcon_dirs = ("build", "install", "log")
    return (all((parent / d).is_dir() for d in colcon_dirs)
            and (any((parent / d / "COLCON_IGNORE").is_file() for d in colcon_dirs)
                 or any((parent / "install").glob("setup.*"))))


def _is_cache(worktree: Path, rel: str) -> bool:
    parts = rel.rstrip("/").split("/")
    dirs = parts if rel.endswith("/") else parts[:-1]
    if dirs[:2] == [".omc", "state"]:  # hook throttles and session files; notes and handoffs elsewhere in .omc stay
        return True
    for i, name in enumerate(dirs):
        if name in CACHES or name.endswith(".egg-info"):
            return True
        if name in GENERATED and (i == 0 or _generated_beside(worktree.joinpath(*dirs[:i]))):
            return True
    return False


def _only_caches(worktree: Path, rel: str) -> bool:
    """An ignored path loses nothing when it is in a cache, or is a directory with no file outside caches.

    git reports a directory whose whole content is ignored as one entry (``ws/``), so it is walked.
    """
    if _is_cache(worktree, rel):
        return True
    if not rel.endswith("/"):
        return False
    for folder, dirs, files in os.walk(worktree / rel):
        if files:
            return False
        inside = Path(folder).relative_to(worktree).as_posix()
        dirs[:] = [d for d in dirs if not _is_cache(worktree, f"{inside}/{d}/")]
    return True


# --- inventory ------------------------------------------------------------------

def _row(path: Path, **facts) -> dict:
    return {"name": path.name, "path": path, "branch": "", "sha": "", "locked": False, "merged": False, "owner": "",
            "last": _mtime(path), "git_dir": path, "orphan": False, "changed": [], "ignored": [], **facts}


def scan(cwd: Path) -> tuple[Path, list[dict]]:
    """The main checkout and one row per directory under its ``.worktrees/``.

    Cheap facts only, four git calls for the whole set and no ``git status``:
    branch, tip, lock, merged into main, owner, and ``last`` = newest of the tip commit
    time, the ``.git`` file (creation) and ``logs/HEAD``; without ``logs/HEAD``
    it is infinite, which reads as active. A directory git does not list (a
    half-removed worktree) is an ``orphan`` row. A dot-named directory (``.omc``) and a plain
    file under ``.worktrees/`` are not worktrees and not orphans: not listed, not counted.
    ``judge`` adds the rest.
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
    owners = _owners(root)
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
        reflog = _mtime(git_dir / "logs" / "HEAD")
        branch = block.get("branch", "").removeprefix("refs/heads/")
        rows.append(_row(path, branch=branch, sha=sha, owner=owners.get(branch, ""),
                         locked="locked" in block, merged=is_merged, git_dir=git_dir,
                         last=max(tip, reflog, _mtime(path / ".git")) if reflog else float("inf")))
    listed = {row["path"].resolve() for row in rows}
    rows += [_row(path, orphan=True) for path in sorted(holder.iterdir())
             if path.is_dir() and not path.name.startswith(".") and path.resolve() not in listed]
    return root, rows


def _identity(root: Path) -> str:
    """Who is calling: the git identity, plus the agent session when the environment names one."""
    who = f"{git(root, 'config', 'user.name').stdout.strip()} <{git(root, 'config', 'user.email').stdout.strip()}>"
    session = os.environ.get("CLAUDE_CODE_SESSION_ID")
    return who + (f"; session {session}" if session else "")


def _owners(root: Path) -> dict[str, str]:
    """branch -> the identity ``new`` recorded in ``branch.<name>.description`` ("owner: <identity>[; over cap ...]")."""
    lines = git(root, "config", "--get-regexp", r"^branch\..*\.description$").stdout.splitlines()
    found = {key[len("branch."):-len(".description")]: value.removeprefix("owner: ").split("; over cap")[0]
             for key, _, value in (line.partition(" ") for line in lines) if value.startswith("owner: ")}
    return {branch: who for branch, who in found.items() if who.strip(" <>;")}  # " <>": no git identity was set


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
        elif not _only_caches(path, rel):
            ignored.append(rel)
    return changed, ignored


def _landed(row: dict) -> bool:
    """Work landed from this branch: its reflog records a commit made on it. No reflog reads as no."""
    log = git(row["path"], "reflog", "show", "--format=%gs", f"refs/heads/{row['branch']}")
    return log.returncode == 0 and any(line.startswith("commit") for line in log.stdout.splitlines())


def judge(row: dict, now: float, idle_hours: float, here: Path, lossless: bool = False, full: bool = False,
          me: str = "") -> None:
    """Set ``idle_h``, ``wait_h`` and ``verdict``; ``git status`` runs only when the cheap facts do not decide.

    ``lossless`` stops at an unmerged branch (the lossless prune keeps it anyway);
    ``full`` always reads the status, for the uncommitted count in ``status``. A merged branch
    with a commit of its own (``_landed``) waits ``rules.LANDED_IDLE_HOURS`` while the worktree is
    clean, none at all when ``me`` (the caller's identity) owns it (``row["fast"]``). An orphan
    gets its content summary in ``note`` and its kept files in ``keep``.
    """
    if row["orphan"]:
        row["note"], row["keep"], newest = rules.orphan_content(row["path"], lambda rel: _is_cache(row["path"], rel))
        row["changed"], row["last"] = row["keep"], max(row["last"], newest)
        row["idle_h"], row["wait_h"] = max(0.0, (now - row["last"]) / 3600), rules.LANDED_IDLE_HOURS
        if not row["keep"] and rules.is_tombstone(row["path"]):  # a hazard with nothing to lose: no wait
            row["wait_h"] = 0.0
        row["verdict"] = "orphan"
        return
    landed = bool(row["branch"] and row["merged"] and row["branch"] != "main" and _landed(row))
    row["fast"] = landed and bool(me) and row["owner"] == me
    row["wait_h"] = 0.0 if row["fast"] else min(idle_hours, rules.LANDED_IDLE_HOURS) if landed else idle_hours
    stale = None if row["merged"] or not row["sha"] else rules.stale_history(row["path"], row["sha"])
    if stale:
        row["note"] = stale
    cheap = ("locked" if row["locked"]
             else "current" if row["path"].resolve() == here
             else "on main" if row["branch"] == "main"
             else "stale-history" if stale
             else "active" if row["wait_h"] and now - row["last"] < row["wait_h"] * 3600
             else "in-progress operation" if any((row["git_dir"] / name).exists() for name in BUSY)
             else "needs snapshot" if lossless and not row["merged"] else None)
    if cheap is None or full:
        status = _status(row["path"])
        if status is None:
            cheap = cheap or "unreadable"
        else:
            row["changed"], row["ignored"] = status
            if status[0]:  # uncommitted files: back to the full idle wait
                row["fast"], row["wait_h"] = False, idle_hours
            row["last"] = max([row["last"], *(_newest(row["path"] / rel) for rel in row["changed"])])
    row["idle_h"] = max(0.0, (now - row["last"]) / 3600)
    row["landed_dirty"] = landed and bool(row["changed"])  # D-790: work continued after the branch landed
    row["verdict"] = ("landed-dirty" if row["landed_dirty"] and cheap in (None, "active")
                      else cheap or ("active" if row["idle_h"] < row["wait_h"]
                                     else "holds ignored data" if row["ignored"]
                                     else "needs snapshot" if row["changed"] or not row["merged"]
                                     else "removable"))


def _here(cwd: Path) -> Path:
    return Path(_must(git(cwd, "rev-parse", "--show-toplevel"), "git rev-parse --show-toplevel")).resolve()


# --- removal --------------------------------------------------------------------

def _keep(root: Path, day: str, name: str, commit: str) -> str:
    """Create ``refs/wip/<day>/<name>`` at ``commit`` (create-only; ``-2``, ``-3`` on a collision)."""
    ref = base = f"refs/wip/{day}/{name}"
    for n in range(2, 100):
        if git(root, "update-ref", ref, commit, ZERO).returncode == 0:
            return ref
        ref = f"{base}-{n}"
    raise RuntimeError(f"could not create {base}")


def _snapshot(root: Path, row: dict, day: str) -> str:
    """Keep a commit that holds the worktree's working files (modified, staged, untracked); return its ref.

    Built in a temporary index, so the worktree's own index and branch are not
    touched; a file staged and then edited again is kept as it is on disk. The
    checks use that index too: against the worktree's own index, untracked files
    in the snapshot would read as deleted.
    """
    path = row["path"]
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        _must(git(path, "read-tree", "HEAD", env=env), "git read-tree")
        _must(git(path, "add", "-A", env=env), "git add -A (temporary index)")
        staged = _must(git(path, "ls-files", "-s", env=env), "git ls-files")
        if any(line.startswith("160000") for line in staged.splitlines()):
            raise RuntimeError("holds a nested git repository; a snapshot would keep a pointer and lose its history")
        tree = _must(git(path, "write-tree", env=env), "git write-tree")
        commit = _must(git(path, "commit-tree", tree, "-p", "HEAD", "-m",
                           f"wip snapshot of worktree {row['name']} ({row['branch'] or 'detached'})"
                           f" before removal {day}"), "git commit-tree")
        diff = git(path, "diff", "--stat", commit, env=env)
        left = git(path, "status", "--porcelain", "--untracked-files=all", env=env)
        if (diff.returncode != 0 or diff.stdout.strip() or left.returncode != 0
                or any(line[:2] == "??" or line[1:2] != " " for line in left.stdout.splitlines())):
            raise RuntimeError("the snapshot does not match the worktree; nothing kept, nothing removed")
    return _keep(root, day, row["name"], commit)


def _remove(root: Path, row: dict, day: str, now: float, say=print) -> str:
    """Remove one judged worktree; return a note for the report. RuntimeError/OSError leaves it in place."""
    path = row["path"]
    if row["orphan"]:  # D-790: files other than caches and .omc/state are archived first
        return rules.clear_orphan(path, row["keep"], lambda rel: _is_cache(path, rel), day)
    # The scan may be minutes old: the row must still be the same commit, branch and lock, and still idle.
    fresh = next((r for r in scan(root)[1] if r["path"].resolve() == path.resolve()), None)
    if (not fresh or fresh["orphan"] or any(fresh[k] != row[k] for k in ("sha", "branch", "locked"))
            or (row["wait_h"] and now - fresh["last"] < row["wait_h"] * 3600)):
        raise RuntimeError("changed since the scan; kept")
    note, force = "", []
    if row["changed"]:
        note = f" snapshot={_snapshot(root, row, day)}"
        force = ["--force"]  # only after the snapshot matched; a clean one lets git re-check
    elif not row["branch"] and not row["merged"]:
        note = f" head={_keep(root, day, row['name'], row['sha'])}"  # detached: no branch would hold the commits
    result = git(root, "worktree", "remove", *force, str(path))
    if result.returncode != 0:
        if path.exists() and all(r["orphan"] for r in scan(root)[1] if r["path"].resolve() == path.resolve()):
            say(f"ORPHAN  {path}{rules.leave_tombstone(path)}")  # git dropped it; the folder stays (open handle)
        raise RuntimeError(f"git worktree remove failed, branch kept: {result.stderr.strip()}")
    note += rules.leave_tombstone(path) if path.exists() else ""
    branch = row["branch"]
    # Exact sha: `update-ref -d` fails if the branch moved, so no commit that is not on main is dropped.
    if (branch and row["merged"]
            and git(root, "merge-base", "--is-ancestor", row["sha"], "refs/heads/main").returncode == 0):
        deleted = git(root, "update-ref", "-d", f"refs/heads/{branch}", row["sha"])
        if deleted.returncode == 0:
            git(root, "config", "--remove-section", f"branch.{branch}")
        note += " branch deleted" if deleted.returncode == 0 else f" branch kept ({deleted.stderr.strip()})"
    return note


def _takes(row: dict, snapshot: bool) -> bool:
    """A judged row this run would remove, owner aside."""
    if row["orphan"]:  # idle, and either nothing to keep or somewhere to archive it
        return row["idle_h"] >= row["wait_h"] and (not row["keep"] or rules.scratch() is not None)
    return row["verdict"] == "removable" or (snapshot and row["verdict"] in SNAPSHOT
                                             and row["idle_h"] >= row["wait_h"] and not row["ignored"])


def prune(cwd: Path, *, idle_hours: float = IDLE_HOURS, snapshot: bool = False, apply: bool = False,
          everyone: bool = False, quiet: bool = False, now: float | None = None, say=print) -> int:
    """Remove (or, without ``apply``, list) what may go; return how many. ``quiet`` drops the KEEP lines.

    A lossless removal needs no owner: nothing is lost and the worktree sat idle for days. A row
    that needs a snapshot (dirty or unmerged work) is taken only from its owner unless ``everyone``
    (``--all``); no owner note reads as unowned.
    """
    now = time.time() if now is None else now
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    root, rows = scan(cwd)
    here = _here(cwd)
    me = _identity(root)
    lock = (root / _must(git(root, "rev-parse", "--git-common-dir"), "git rev-parse")) / "worktrees-prune.lock"
    if apply:  # two applying runs must not interleave
        if time.time() - (_mtime(lock) or time.time()) > STALE_LOCK:
            lock.unlink(missing_ok=True)
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        except FileExistsError:
            raise RuntimeError(f"another prune is running ({lock}; taken over after 30 min)") from None
    done = 0
    try:
        for row in sorted(rows, key=lambda r: r["name"]):
            judge(row, now, idle_hours, here, lossless=not snapshot, me=me)
            label = f"{row['name']} [{row['branch'] or ('orphan' if row['orphan'] else 'detached')}]"
            if not _takes(row, snapshot):
                if not quiet:
                    say(f"KEEP    {label} {row['verdict']}")
                continue
            if row["verdict"] in SNAPSHOT and not everyone and row["owner"] != me:
                if not quiet:
                    say(f"KEEP    {label} {row['verdict']}, owner {row['owner'] or 'unknown'}: only with --all")
                continue
            kind = (row["note"] if row["orphan"] else ("dirty" if row["changed"] else "clean") + "+"
                    + ("merged" if row["merged"] else "unmerged"))
            if not apply:
                say(f"PLAN    {label} {kind} idle={row['idle_h']:.0f}h")
                done += 1
                continue
            try:
                say(f"REMOVED {label} {kind}{_remove(root, row, day, now, say)}")
                done += 1
            except (RuntimeError, OSError) as exc:
                say(f"FAIL    {label} {exc}")
    finally:
        if apply:
            lock.unlink(missing_ok=True)
    if done or not quiet:
        say(f"[worktrees] {'removed' if apply else 'would remove'} {done} of {len(rows)} under {root / '.worktrees'}")
    return done


def sweep(cwd: Path, apply: bool = False, now: float | None = None) -> None:
    """What ``new`` and ``tools/land.py`` run: one report line, or the lossless prune when asked (``--prune``)."""
    if apply:
        prune(cwd, apply=True, quiet=True, now=now)
        return
    count = prune(cwd, quiet=True, now=now, say=lambda *_: None)
    if count:
        print(f"[worktrees] {count} finished worktree(s) can be removed: {SWEEP}")


# --- commands -------------------------------------------------------------------

def _table(rows: list[dict], me: str, now: float, file=None) -> None:
    """One line per row; ``you``: may the caller remove it (yes), only with --all, or not at all (-)."""
    for row in rows:
        who = row["owner"] or ("" if row["orphan"] else "unknown")  # D-790: no owner note is said, not left blank
        owner = "; ".join(text for text in (who, row.get("note")) if text)
        branch = row["branch"] or ("(orphan)" if row["orphan"] else "(detached)")
        you = ("-" if not _takes(row, True)
               else "yes" if row["verdict"] not in SNAPSHOT or row["owner"] == me else "--all")
        print(f"{row['name']:<32} {branch:<44} {'merged' if row['merged'] else 'unmerged':<8} "
              f"{len(row['changed']):>5} {row['idle_h']:>6.0f}h {'locked' if row['locked'] else '-':<6} {you:<5} "
              f"{row['verdict']}" + (f"  [{owner}]" if owner else ""), file=file)


def cmd_status(cwd: Path, idle_hours: float, now: float) -> int:
    root, rows = scan(cwd)
    here, me = _here(cwd), _identity(root)
    for row in rows:
        judge(row, now, idle_hours, here, full=True, me=me)
        # A tip that merged main in (tools/land.py does) and was not landed since is not an ancestor of main.
        # Still unmerged, and correctly kept; the note only explains why a "landed-looking" branch is.
        if row["merged"] or row["orphan"] or row.get("note"):
            continue
        parents = git(root, "rev-list", "--parents", "-n1", row["sha"]).stdout.split()[2:]
        if any(git(root, "merge-base", "--is-ancestor", p, "main").returncode == 0 for p in parents):
            row["note"] = "tip is a merge of main"
    print(f"{'name':<32} {'branch':<44} {'main':<8} {'dirty':>5} {'idle':>7} {'lock':<6} {'you':<5} verdict  [owner]")
    _table(sorted(rows, key=lambda r: -r["idle_h"]), me, now)
    for row in rows:  # D-790: the two states that need a person, said in words
        who = row["owner"] or "unknown"
        if row.get("landed_dirty"):
            print(f"WARN    {row['name']}: {row['branch']} is already in main and {len(row['changed'])} file(s) are"
                  f" uncommitted here (owner {who}). Do not keep working in a landed worktree: start a new one"
                  " (python tools/worktrees.py new <short-name> <type>/<topic>) and move the work there.")
        if row["verdict"] == "stale-history":
            print(f"WARN    {row['name']}: {row['branch']} {row['note']} (owner {who}). Do not merge or land it;"
                  " rebuild what is needed on a new branch from main (D-172), then archive this one.")
    print(f"[worktrees] {len(rows)} under {root / '.worktrees'} (cap {CAP})")
    return 0


def cmd_new(cwd: Path, name: str, branch: str, reason: str | None, now: float, mode: str = "report",
            base: str = "main", owner: str | None = None) -> int:
    kind, _, topic = branch.partition("/")
    root, _ = scan(cwd)
    held = rules.clear_tombstone(root / ".worktrees", name)  # a removed worktree's folder left by an open handle
    known = git(root, "rev-parse", "-q", "--verify", f"{base}^{{commit}}").returncode == 0
    problem = (
        f"branch must be <type>/<topic> with <type> one of {', '.join(TYPES)} (D-372): {branch!r}"
        if kind not in TYPES or not topic or git(root, "check-ref-format", "--branch", branch).returncode != 0
        else f"short name must be one path component of letters, digits, '.', '_', '-', not ending in '.': {name!r}"
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9_-])?", name)
        else '--force-over-cap needs a reason: --force-over-cap "<reason>"' if reason is not None and not reason.strip()
        else f"{root / '.worktrees' / name} already exists{held}" if (root / ".worktrees" / name).exists()
        else f"branch {branch} already exists"
        if git(root, "rev-parse", "-q", "--verify", f"refs/heads/{branch}").returncode == 0
        else f"--from {base}: not a commit" if not known
        else '--owner needs a name: --owner "<who>"' if owner is not None and not owner.strip()
        else None)
    stale = None if problem or base == "main" else rules.stale_history(root, base)
    if stale:  # D-790: a worktree on the pre-rewrite line would carry it into main
        problem = f"refused: --from {base} is {stale}; rebuild on a new branch from main (D-172)"
    if problem:
        print(problem, file=sys.stderr)
        return 1
    if mode != "silent":
        try:
            sweep(cwd, apply=mode == "apply", now=now)  # lossless only; never --snapshot from here
        except (RuntimeError, OSError) as exc:
            print(f"[worktrees] warning: prune failed, continuing: {exc}", file=sys.stderr)
    rows = scan(cwd)[1]
    if len(rows) >= CAP and reason is None:
        here, me = _here(cwd), _identity(root)
        for row in rows:
            judge(row, now, IDLE_HOURS, here, me=me)
        print(f"refused: {len(rows)} worktrees under {root / '.worktrees'}, the cap is {CAP}. Longest idle:",
              file=sys.stderr)
        _table(sorted(rows, key=lambda r: r["last"])[:10], me, now, file=sys.stderr)
        finished = [r for r in rows if _takes(r, False)]  # nothing left to lose: anyone may sweep them
        for row in sorted(finished, key=lambda r: r["name"]):
            print(f"removable now by anyone: {row['name']} ({row.get('note') if row['orphan'] else row['verdict']};"
                  f" owner {row['owner'] or 'unknown'})", file=sys.stderr)
        if finished:
            print(f"you may remove all {len(finished)}: {SWEEP}", file=sys.stderr)
        for row in sorted((r for r in rows if r["verdict"] in SNAPSHOT and _takes(r, True)), key=lambda r: r["name"]):
            print(f"removable by its owner ({row['owner'] or 'unknown'}) through prune --snapshot (a person or the"
                  f" dispatcher: also --all): {row['name']} ({row['verdict']})", file=sys.stderr)
        print(f'{HINT}\nor, during an incident: add --force-over-cap "<reason>"', file=sys.stderr)
        return 1
    add = ["worktree", "add", "--relative-paths", f".worktrees/{name}", "-b", branch, base]
    result = git(root, *add)
    if result.returncode != 0 and "relative-paths" in result.stderr:  # git older than 2.48
        add.remove("--relative-paths")
        result = git(root, *add)
    _must(result, "git worktree add")
    # Who made it: `prune --snapshot` takes only the caller's own; people read it in `status` (D-790: --owner).
    note = f"owner: {owner.strip() if owner else _identity(root)}"
    if len(rows) >= CAP:
        note += f"; over cap ({len(rows)} >= {CAP}): {reason}"
        print(f"[worktrees] over the cap ({len(rows)} >= {CAP}), forced: {reason}")
    git(root, "config", f"branch.{branch}.description", note)
    print(root / ".worktrees" / name)
    return 0


def lint_note(repo: Path, now: float | None = None) -> str | None:
    """A warning line for ``rosy_harness.py lint``: at the cap, or merged worktrees sit idle.

    Count and cheap facts only (no ``git status`` per worktree). None in CI,
    outside git, in a repository with no ``.worktrees/``, and on any error: a
    warn-only note must never fail lint or pre-push.
    """
    try:
        if os.environ.get("CI"):
            return None
        rows = scan(repo)[1]
        now = time.time() if now is None else now
        idle = sum(1 for r in rows if r["merged"] and not r["locked"] and now - r["last"] >= IDLE_HOURS * 3600)
        if len(rows) < CAP and not idle:
            return None
        return (f"worktrees: {len(rows)} under .worktrees/ (cap {CAP}), {idle} merged and idle"
                f" {IDLE_HOURS:.0f} h or more; {HINT}")
    except Exception:
        return None


def main(argv: list[str] | None = None, now: float | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status", help="read-only table of every directory under .worktrees/")
    pruner = sub.add_parser("prune", help="remove idle worktrees without losing work (dry run by default)")
    pruner.add_argument("--apply", action="store_true", help="act; without it the plan is printed")
    pruner.add_argument("--all", dest="everyone", action="store_true",
                        help="with --snapshot: also worktrees other sessions made, and unowned ones")
    pruner.add_argument("--snapshot", action="store_true",
                        help="also take dirty or unmerged worktrees, after keeping uncommitted work under refs/wip")
    for command in (status, pruner):
        command.add_argument("--idle-hours", type=float, default=IDLE_HOURS)
    new = sub.add_parser("new", help="create .worktrees/<short-name> on a new branch from main")
    new.add_argument("name", metavar="short-name")
    new.add_argument("branch", metavar="type/topic")
    new.add_argument("--force-over-cap", metavar="REASON", help=f"create although {CAP} or more worktrees exist")
    new.add_argument("--from", dest="base", default="main", help="start point (default main); refused when stale")
    new.add_argument("--owner", help="owner note instead of the git identity and session")
    sweeping = new.add_mutually_exclusive_group()
    sweeping.add_argument("--prune", dest="mode", action="store_const", const="apply", default="report",
                          help="apply the lossless prune first (default: only report what it would remove)")
    sweeping.add_argument("--no-prune", dest="mode", action="store_const", const="silent", help="no report either")
    args = parser.parse_args(argv)
    now = time.time() if now is None else now
    try:
        if args.command == "status":
            return cmd_status(Path.cwd(), args.idle_hours, now)
        if args.command == "new":
            return cmd_new(Path.cwd(), args.name, args.branch, args.force_over_cap, now, args.mode, args.base,
                           args.owner)
        prune(Path.cwd(), idle_hours=args.idle_hours, snapshot=args.snapshot, apply=args.apply,
              everyone=args.everyone, now=now)
        return 0
    except RuntimeError as exc:
        print(f"[worktrees] STOP: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
