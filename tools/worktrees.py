"""Keep ``.worktrees/`` from piling up: one gateway to create, one sweep to remove (D-761, D-790).

Usage (from the main checkout or any worktree of the repository)::

    python tools/worktrees.py status [--idle-hours N]
    python tools/worktrees.py prune [--apply] [--snapshot] [--all] [--idle-hours N]
    python tools/worktrees.py new <short-name> <type>/<topic> [--from REF] [--owner TEXT]
                                  [--prune | --no-prune] [--force-over-cap "<reason>"]
    python tools/worktrees.py adopt <short-name> <type>/<topic> [--owner TEXT] [--prune | --no-prune]
                                  [--force-over-cap "<reason>"]

``prune`` is a dry run unless ``--apply``. Without ``--snapshot`` it removes only
what is lossless: a worktree that is clean (nothing modified, staged or
untracked), whose HEAD is an ancestor of ``main``, that is not locked, has no
rebase/merge/bisect/cherry-pick in progress, holds no ignored file outside the
cache directories, and has been idle long enough. No wait at all when its branch landed (a
commit of its own in the branch reflog, D-790) and the worktree is clean, whoever made it;
``--idle-hours`` (default 72) for the rest, a just-created empty worktree or a dirty landed one
included. D-1070: a clean worktree (nothing modified, staged, untracked or ignored outside caches)
on a branch waits only ``CLEAN_IDLE_HOURS`` (6 h, or ``--idle-hours`` when smaller), merged or not, whoever made
it: its branch holds everything, an unmerged branch is kept and ``adopt`` re-attaches it. Its branch is
deleted by exact sha (``git update-ref -d <ref> <sha>``) once that sha is an
ancestor of main, as are landed branches no worktree uses (D-886). ``--snapshot``, for a person or dispatcher,
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
file, the newest ``logs/HEAD`` entry, the index file and every non-cache file, changed or not (11-20: used
worktrees were removed). No ``logs/HEAD`` reads as active. An owner note (``new`` stamps "; at <epoch>") younger
than ``--idle-hours`` keeps the worktree unless it is clean and landed a commit of its own. Only a person runs
``--snapshot``; ``land_tick`` and ``land_bottlenecks`` run the lossless prune only.

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

CAP = 14  # everything under .worktrees/, orphan directories included; with main, the 15-slot budget (D-886)
IDLE_HOURS = 72.0
STALE_LOCK = 30 * 60  # seconds after which another run's prune lock is taken over
TYPES = ("feat", "fix", "refactor", "docs", "uiux")  # D-372
BUSY = ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG")
ZERO = "0" * 40
SNAPSHOT = ("needs snapshot", "landed-dirty")  # verdicts only --snapshot takes, and only from the owner or --all
SWEEP = "python tools/worktrees.py prune --apply"
HINT = (f"see `python tools/worktrees.py status`; `{SWEEP}` removes only clean idle ones, whoever made them"
        " (an unmerged branch stays: `adopt` re-attaches it); `--snapshot` is for a person or the dispatcher, not for every session")


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


_is_cache, _only_caches = rules.is_cache, rules.only_caches  # moved to worktree_rules (600-line cap)


# --- inventory ------------------------------------------------------------------

def _row(path: Path, **facts) -> dict:
    return {"name": path.name, "path": path, "branch": "", "sha": "", "locked": False, "merged": False, "owner": "",
            "last": _mtime(path), "noted": 0.0, "git_dir": path, "orphan": False, "changed": [], "ignored": [], **facts}


def scan(cwd: Path) -> tuple[Path, list[dict]]:
    """The main checkout and one row per directory under its ``.worktrees/``.

    Cheap facts only, four git calls for the whole set and no ``git status``:
    branch, tip, lock, merged into main, owner, and ``last`` = newest of the tip commit
    time, the ``.git`` file (creation) and the newest ``logs/HEAD`` entry; without one
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
    times = dict(line.split() for line in git(root, "for-each-ref", "--format=%(objectname) %(committerdate:unix)", "refs/heads").stdout.splitlines())
    merged = {s for t in rules.merge_targets(root) for s in git(root, "for-each-ref", "--merged", t, "--format=%(objectname)", "refs/heads").stdout.split()}
    owners, noted = rules.owner_notes(root, git)
    rows = []
    for block in blocks[1:]:
        path = Path(block["worktree"])
        if path.resolve().parent != holder or not path.is_dir():
            continue
        sha = block.get("HEAD", "")
        if sha in times:
            is_merged, tip = sha in merged, int(times[sha])
        else:  # detached at a commit no branch points to
            is_merged = rules.is_merged(root, sha)
            tip = int(git(root, "show", "-s", "--format=%ct", sha).stdout.strip() or 0)
        try:  # `.git` is a file "gitdir: <absolute or relative path>"
            git_dir = path / (path / ".git").read_text(encoding="utf-8").partition("gitdir:")[2].strip()
        except OSError:
            git_dir = path
        reflog = rules.reflog_time(git_dir / "logs" / "HEAD")  # entry time: gc rewrites the file (D-886)
        branch = block.get("branch", "").removeprefix("refs/heads/")
        rows.append(_row(path, branch=branch, sha=sha, owner=owners.get(branch, ""), noted=noted.get(branch, 0.0),
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
    with a commit of its own (``_landed``) has no wait while the worktree is clean (``row["fast"]``,
    whoever made it), and waits ``idle_hours`` when dirty (``landed-dirty``). An orphan
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
    row["fast"] = landed
    # D-1070: a clean worktree on a branch loses nothing; status below puts a dirty one back on idle_hours.
    # Only a branch `adopt` takes back: other names wait idle_hours (stale-history is never removed).
    kind, _, topic = row["branch"].partition("/")
    adoptable = kind in TYPES and rules.topic_ok(topic)
    row["wait_h"] = 0.0 if landed else min(idle_hours, rules.CLEAN_IDLE_HOURS) if adoptable else idle_hours
    stale = None if row["merged"] or not row["sha"] else rules.stale_history(row["path"], row["sha"])
    if stale:
        row["note"] = stale
    # A young owner note (11-20: its session may be about to use it); a landed clean worktree has nothing to lose.
    noted = not landed and now - row["noted"] < idle_hours * 3600
    cheap = ("locked" if row["locked"]
             else "current" if row["path"].resolve() == here
             else "on main" if row["branch"] == "main"
             else "stale-history" if stale
             else "active" if noted
             else "active" if row["wait_h"] and now - row["last"] < row["wait_h"] * 3600
             else "in-progress operation" if any((row["git_dir"] / name).exists() for name in BUSY)
             else "needs snapshot" if lossless and not row["merged"] and not adoptable else None)
    if cheap is None or full:
        index_t = _mtime(row["git_dir"] / "index")  # before status, which may refresh the index
        status = _status(row["path"])
        if status is None:
            cheap = cheap or "unreadable"
        else:
            row["changed"], row["ignored"] = status
            if status[0]:  # uncommitted files: back to the full idle wait
                row["fast"], row["wait_h"] = False, idle_hours
            row["last"] = max([row["last"], *(_newest(row["path"] / rel) for rel in row["changed"])])
            if row["wait_h"]:
                row["last"] = max(row["last"], index_t, rules.newest_file(row["path"], lambda r: _is_cache(row["path"], r)))
    row["idle_h"] = max(0.0, (now - row["last"]) / 3600)
    row["landed_dirty"] = landed and bool(row["changed"])  # D-790: work continued after the branch landed
    row["verdict"] = ("landed-dirty" if row["landed_dirty"] and cheap in (None, "active")
                      else cheap or ("active" if row["idle_h"] < row["wait_h"]
                                     else "holds ignored data" if row["ignored"]
                                     else "needs snapshot" if row["changed"] or not (row["merged"] or adoptable)
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
    if branch and row["merged"] and rules.is_merged(root, row["sha"]):
        deleted = git(root, "update-ref", "-d", f"refs/heads/{branch}", row["sha"])
        if deleted.returncode == 0:
            git(root, "config", "--remove-section", f"branch.{branch}")
        note += " branch deleted" if deleted.returncode == 0 else f" branch kept ({deleted.stderr.strip()})"
    elif branch:
        note += f" branch kept; re-attach: python tools/worktrees.py adopt {row['name']} {branch}"
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
    A lossless removal needs no owner; a row needing a snapshot (dirty or unmerged) is taken only from its
    owner unless ``everyone`` (``--all``), no owner note reading as unowned. Landed branches follow."""
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
    done, failed = 0, set()
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
                failed.add(row["branch"])  # its "branch kept" holds for this run
        git(root, "worktree", "prune", *([] if apply else ["--dry-run"]))
        rules.sweep_branches(root, now, apply, say, quiet, keep=failed)
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
        if any(rules.is_merged(root, p) for p in parents):
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


def _form_problem(root: Path, name: str, branch: str, reason: str | None, owner: str | None) -> str | None:
    """What ``new`` and ``adopt`` both refuse: branch and short-name format, an empty reason or owner, a taken path."""
    kind, _, topic = branch.partition("/")
    held = rules.clear_tombstone(root / ".worktrees", name)  # a removed worktree's folder left by an open handle
    return (
        f"branch must be <type>/<topic>, <type> one of {', '.join(TYPES)}, {rules.TOPIC_RULE} (D-372): {branch!r}"
        if kind not in TYPES or not rules.topic_ok(topic) or git(root, "check-ref-format", "--branch", branch).returncode != 0
        else f"short name must be one path component of letters, digits, '.', '_', '-', not ending in '.': {name!r}"
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9_-])?", name)
        else '--force-over-cap needs a reason: --force-over-cap "<reason>"' if reason is not None and not reason.strip()
        else f"{root / '.worktrees' / name} already exists{held}" if (root / ".worktrees" / name).exists()
        else '--owner needs a name: --owner "<who>"' if owner is not None and not owner.strip()
        else None)


def _has_branch(root: Path, branch: str) -> bool:
    return git(root, "rev-parse", "-q", "--verify", f"refs/heads/{branch}").returncode == 0 or rules.restore_archived(root, branch)


def cmd_new(cwd: Path, name: str, branch: str, reason: str | None, now: float, mode: str = "report",
            base: str = "main", owner: str | None = None) -> int:
    root, _ = scan(cwd)
    known = git(root, "rev-parse", "-q", "--verify", f"{base}^{{commit}}").returncode == 0
    problem = (_form_problem(root, name, branch, reason, owner)
               or (f"branch {branch} already exists (re-attach it: adopt)" if _has_branch(root, branch) else None)
               or (f"--from {base}: not a commit" if not known else None))
    stale = None if problem or base == "main" else rules.stale_history(root, base) or rules.unlanded(root, base)
    if stale:  # D-790: a worktree on the pre-rewrite line would carry it into main
        problem = f"refused: --from {base} is {stale}; rebuild on a new branch from main (D-172)"
    return _attach(cwd, root, name, branch, ["-b", branch, base], problem, reason, now, mode, owner)


def cmd_adopt(cwd: Path, name: str, branch: str, reason: str | None, now: float, mode: str = "report",
              owner: str | None = None) -> int:
    """D-1070: put an existing local branch (one a clean prune left) back at ``.worktrees/<name>``."""
    root, _ = scan(cwd)
    problem = (_form_problem(root, name, branch, reason, owner)
               or (f"branch {branch} does not exist" if not _has_branch(root, branch) else None))
    stale = None if problem else rules.stale_history(root, branch)
    if stale:  # D-790: the pre-rewrite line is archived by a person, never re-attached
        problem = f"refused: {branch} is {stale}; rebuild on a new branch from main (D-172)"
    return _attach(cwd, root, name, branch, [branch], problem, reason, now, mode, owner)


def _attach(cwd: Path, root: Path, name: str, branch: str, target: list[str], problem: str | None,
            reason: str | None, now: float, mode: str, owner: str | None) -> int:
    """The rest of ``new`` and ``adopt``: refuse, report or sweep, check the cap, add, write the owner note."""
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
    add = ["worktree", "add", "--relative-paths", f".worktrees/{name}", *target]
    result = git(root, *add)
    if result.returncode != 0 and "relative-paths" in result.stderr:  # git older than 2.48
        add.remove("--relative-paths")
        result = git(root, *add)
    _must(result, "git worktree add")
    # Who made it: `prune --snapshot` takes only the caller's own; people read it in `status` (D-790: --owner).
    note = f"owner: {owner.strip() if owner else _identity(root)}; at {int(now)}"
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
    new.add_argument("--from", dest="base", default="main", help="start point (default main); refused when stale")
    adopt = sub.add_parser("adopt", help="re-attach an existing local branch at .worktrees/<short-name> (D-1070)")
    for command in (new, adopt):
        command.add_argument("name", metavar="short-name")
        command.add_argument("branch", metavar="type/topic")
        command.add_argument("--force-over-cap", metavar="REASON", help=f"create although {CAP} or more worktrees exist")
        command.add_argument("--owner", help="owner note instead of the git identity and session")
        sweeping = command.add_mutually_exclusive_group()
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
        if args.command == "adopt":
            return cmd_adopt(Path.cwd(), args.name, args.branch, args.force_over_cap, now, args.mode, args.owner)
        prune(Path.cwd(), idle_hours=args.idle_hours, snapshot=args.snapshot, apply=args.apply,
              everyone=args.everyone, now=now)
        return 0
    except RuntimeError as exc:
        print(f"[worktrees] STOP: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Korean owner notes on a cp1252 console
    sys.exit(main())
