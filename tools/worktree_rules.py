"""Rules ``tools/worktrees.py`` and ``tools/land.py`` share (D-790, amends D-761).

- A landed worktree (merged into main, a commit of its own in its branch reflog) that is clean
  has no wait (``wait_h = 0.0``) in ``tools/worktrees.py``, whoever made it; ``LANDED_IDLE_HOURS``
  (1 h) still applies to orphan directories and unused merged branches (``sweep_branches``).
- ``stale_history``: a branch on the pre-rewrite line (more than ``STALE_COMMITS`` commits not in
  main, or forked from main at or before ``REWRITE_BASE``) would re-import the old history; ``new``
  does not base on it and ``land.py`` does not land it.
- Orphan directories (under ``.worktrees/``, not registered with git): ``orphan_content`` sums them
  up; ``clear_orphan`` removes empty ones and ones holding only caches or ``.omc/state``, and
  archives the rest to ``$ROSY_SCRATCH/worktree-orphans/<name>-<date>.zip`` (Python ``zipfile``,
  re-opened and counted) before the directory goes.
- A removed worktree's folder that cannot be deleted (Windows: a process holds it as its cwd) is
  ``rmdir``-ed when empty, else gets a tombstone ``.git`` file (``leave_tombstone``) pointing at a
  gitdir that cannot exist, so git inside it fails instead of walking up to the main checkout's
  ``.git`` and acting on main. The tombstone counts as a cache: the next prune deletes the folder.
- D-886: ``new`` takes a topic of lowercase words joined by ``-`` (``topic_ok``), and every prune ends
  with ``sweep_branches``: local branches already in main that no worktree has checked out go, by exact
  sha, once their reflog is ``LANDED_IDLE_HOURS`` old; ``main`` and ``archive/*`` (a person's, D-790) stay.
  Lossless: the commits are on main (D-372 decision 2).

Standard library only.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path

LANDED_IDLE_HOURS = 1.0
CLEAN_IDLE_HOURS = 6.0  # D-1070: a clean worktree on a branch, merged or not, whoever made it
NOTE_IDLE_HOURS = 24.0  # D-1070 revision 11-22: owner-note guard for a clean adoptable worktree (72 h for other names)
SPLIT_SOON = 10  # D-1067 warning at half the 20 own-commit PR cap
SPLIT_NEEDED = 20  # matches step_back.size_violations own-commit cap
NO_PR_HOURS = 24.0  # hours since first own non-merge commit without an open PR
REMOTE_PRUNE_DAYS = 14  # days since last commit on an unopened non-reserved origin branch
RESERVED_PREFIXES = ("publish/main-", "bot/", "gh-readonly-queue/", "archive/",
                     "release/", "build/", "payload-reserved-")
STALE_COMMITS = 2_000
ABANDON_DAYS = 4  # an unlanded branch with no worktree and no commit this long is archived (archive_abandoned); 14 until 11-21 (840 local branches)
# main was rewritten after this commit (2026-09-22 09:55:14 +0900); branches cut before the rewrite share
# only it with main and carry ~13,800 commits of the old line (feat/integrated-learning-pipeline, 2026-10-17).
REWRITE_BASE = "ad86fca808"
REWRITE_TIME = 1790038514  # its committer time: a merge-base this old or older is on the old line
TOPIC = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
TOPIC_MAX = 48
TOPIC_RULE = f"<topic> lowercase letters and digits joined by '-', at most {TOPIC_MAX} characters (D-886)"
# Ignored directories that are rebuilt, not written by hand, at any depth; `*.egg-info` by suffix.
CACHES = {"__pycache__", ".pytest_cache", "node_modules", ".ruff_cache", ".mypy_cache", ".gradle", ".kotlin",
          ".cxx", ".venv", "graphify-out"}
# Caches only at the worktree root or where a marker proves it (see _generated_beside).
GENERATED = {"build", "install", "log", "dist"}


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


# --- caches (what tools/worktrees.py may drop) ----------------------------------------

def _generated_beside(parent: Path) -> bool:
    """``parent`` proves its build/install/log/dist are generated: a gradle module or a colcon workspace."""
    if any(parent.glob("build.gradle*")):
        return True
    colcon_dirs = ("build", "install", "log")
    return (all((parent / d).is_dir() for d in colcon_dirs)
            and (any((parent / d / "COLCON_IGNORE").is_file() for d in colcon_dirs)
                 or any((parent / "install").glob("setup.*"))))


def is_cache(worktree: Path, rel: str) -> bool:
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


def only_caches(worktree: Path, rel: str) -> bool:
    """An ignored path loses nothing when it is in a cache, or is a directory with no file outside caches.

    git reports a directory whose whole content is ignored as one entry (``ws/``), so it is walked.
    """
    if is_cache(worktree, rel):
        return True
    if not rel.endswith("/"):
        return False
    for folder, dirs, files in os.walk(worktree / rel):
        if files:
            return False
        inside = Path(folder).relative_to(worktree).as_posix()
        dirs[:] = [d for d in dirs if not is_cache(worktree, f"{inside}/{d}/")]
    return True


# --- orphan directories -------------------------------------------------------------

def unlanded(cwd: Path, tip: str, base: str = "main") -> str | None:
    """Why a new branch must not start at ``tip``, or None: work stacked on an unlanded branch grows with it
    (11-14: v2/v3 chains held 178-189 commits not in main). Land that branch first. ``origin/main`` is published,
    never unlanded work: the D-1038 urgent lane starts there."""
    if tip == "origin/main":
        return None
    if _git(cwd, "merge-base", "--is-ancestor", tip, base).returncode == 1:
        return f"not in {base} yet (land it first; a branch stacked on unlanded work grows with it)"
    return None


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
    tomb = is_tombstone(path)  # its .git loses nothing: the worktree was removed already
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
            rel = name if inside == "." else f"{inside}/{name}"
            if not droppable(rel) and not (tomb and rel == ".git"):
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


TOMBSTONE = "removed-worktree-"


def is_tombstone(path: Path) -> bool:
    """``path/.git`` is a tombstone ``leave_tombstone`` wrote."""
    try:
        return TOMBSTONE in (path / ".git").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False


def leave_tombstone(path: Path) -> str:
    """A worktree folder left after removal: rmdir it if empty, else make git inside it fail; a note.

    The gitdir sits under ``.git``, which is then a file, so it cannot exist; git stops there
    ("gitfile does not point to a valid repository") and never reaches the parent repository.
    """
    try:
        path.rmdir()
        return " empty folder removed"
    except FileNotFoundError:
        return ""
    except OSError:
        pass
    marker = path / ".git"
    if marker.is_dir():  # a nested repository, not a worktree's gitfile: leave it
        return " folder left (it holds a .git directory)"
    try:
        if marker.exists():
            os.chmod(marker, 0o666)
        marker.write_text(f"gitdir: .git/{TOMBSTONE}{path.name}-delete-this-folder\n", encoding="utf-8")
    except OSError as exc:
        return f" folder left, tombstone failed: {exc}"
    return f" tombstone {marker} written: git inside fails until the next prune deletes the folder"


def clear_tombstone(holder: Path, name: str) -> str:
    """Delete ``holder/name`` when it holds only a tombstone; "" or why it is still there."""
    path = holder / name
    if Path(name).name != name or name in (".", "..") or not is_tombstone(path):
        return ""
    try:
        clear_orphan(path, [], lambda rel: False, time.strftime("%Y-%m-%d"))
        return ""
    except (RuntimeError, OSError):
        return (": a removed worktree's folder (tombstone) that could not be cleared; close any shell or editor"
                " inside it and retry")


def clear_orphan(path: Path, keep: list[Path], droppable, day: str) -> str:
    """Remove one judged orphan, archiving its kept files first; a note for the report.

    The directory is read again: anything added or removed since the scan keeps it.
    """
    _, now_keep, _ = orphan_content(path, droppable)
    if now_keep != keep:
        raise RuntimeError("changed since the scan; kept")
    note = f" archived to {_archive(path, keep, day)}," if keep else ""
    handler = {"onexc" if sys.version_info >= (3, 12) else "onerror": _writable_and_retry}
    try:
        shutil.rmtree(path, **handler)
    except OSError as exc:  # an open handle (WinError 32): what is left must not act on main
        raise OSError(f"{exc};{note}{leave_tombstone(path) if path.exists() else ''}") from exc
    return note + (" orphan directory removed" if keep else " orphan directory without content removed")


def reflog_time(path: Path) -> float:
    """Time of the newest entry in a reflog file, 0 when there is none.

    Not the file's mtime: ``git reflog expire --all`` (run by gc) rewrites every reflog file, worktrees'
    ``logs/HEAD`` included, and leaves the entries as they were (2026-10-26, D-886).
    """
    try:
        return float(path.read_text(encoding="utf-8").splitlines()[-1].split("\t")[0].split()[-2])
    except (OSError, UnicodeError, IndexError, ValueError):
        return 0.0


WRONG_HEAD_FIX = ("do not merge or fast-forward there; its owner moves that work to a worktree"
                  " (python tools/worktrees.py adopt) and switches the checkout back to main")


def wrong_head(root: Path) -> str | None:
    """D-1055: the shared main checkout stays on main. Its HEAD when it is anything else (``wrong-head``)."""
    head = _git(root, "symbolic-ref", "-q", "--short", "HEAD").stdout.strip() or "a detached HEAD"
    return None if head == "main" else head


TOOL_TREES = ("rosy-land-wt", "rosy-publish", "rosy-land-spec")  # <git-common-dir>/<holder>/: their tools own them
FOREIGN_FIX = ("not removed or counted here; after its session ends its owner re-attaches the branch"
               " (python tools/worktrees.py adopt) and runs git worktree remove on this one")


def foreign_worktrees(root: Path) -> list[str]:
    """Worktrees outside <root>/.worktrees/ and the tools' hidden holders (opencode's, a bare git worktree add)."""
    listed = _git(root, "worktree", "list", "--porcelain").stdout.splitlines()
    common = Path(_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()).resolve()
    inside = [(root / ".worktrees").resolve(), *(common / holder for holder in TOOL_TREES)]
    paths = [Path(line[len("worktree "):]) for line in listed if line.startswith("worktree ")][1:]  # [0] is main
    return [str(p) for p in paths if not any(p.resolve().is_relative_to(d) for d in inside)]


def shared_warnings(root: Path) -> list[str]:
    """status lines about the shared checkout itself: wrong-head, then each worktree outside .worktrees/."""
    head = wrong_head(root)
    return ([f"WARN    wrong-head: the shared main checkout {root} is on {head}, not main; {WRONG_HEAD_FIX}"] if head else []
            ) + [f"WARN    worktree outside .worktrees/: {path}; {FOREIGN_FIX}" for path in foreign_worktrees(root)]


def _gh(root: Path, *args: str) -> str | None:
    try:
        res = subprocess.run(["gh", *args], cwd=root, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return res.stdout if res.returncode == 0 else None


def open_pr_heads(root: Path) -> set[str] | None:
    """Open PR head branch names, or None when origin is absent or gh fails/truncates."""
    if _git(root, "remote", "get-url", "origin").returncode != 0:
        return None
    out = _gh(root, "pr", "list", "--state", "open", "--limit", "500", "--json", "headRefName")
    if out is None:
        return None
    try:
        items = json.loads(out)
    except ValueError:
        return None
    if not isinstance(items, list) or len(items) >= 500:
        return None
    return {item["headRefName"] for item in items if isinstance(item, dict) and item.get("headRefName")}


def _own_commit_times(root: Path, base: str, sha: str) -> list[int]:
    res = _git(root, "log", "--no-merges", "--format=%ct", f"{base}..{sha}")
    if res.returncode != 0:
        return []
    try:
        return [int(tok) for tok in res.stdout.split()]
    except ValueError:
        return []


def status_notes(root: Path, rows: list[dict], now: float) -> list[str]:
    """Shared-checkout warnings plus P1 branch-size and 24h no-PR summary lines."""
    lines = shared_warnings(root)
    base = ("refs/remotes/origin/main" if _git(root, "rev-parse", "-q", "--verify", "refs/remotes/origin/main").returncode == 0
            else "refs/heads/main")
    needed, soon, stale_no_pr = [], [], []
    for row in sorted(rows, key=lambda r: r["name"]):
        if row.get("orphan") or row.get("merged") or not row.get("sha") or row.get("branch") == "main" or row.get("verdict") == "stale-history":
            continue
        times = _own_commit_times(root, base, row["sha"])
        if len(times) >= SPLIT_NEEDED:
            needed.append(f"{row['name']}({len(times)})")
        elif len(times) >= SPLIT_SOON:
            soon.append(f"{row['name']}({len(times)})")
        if row.get("branch") and times and now - min(times) >= NO_PR_HOURS * 3600:
            stale_no_pr.append((row["name"], row["branch"]))
    if needed or soon:
        parts = ([f"split-needed (>={SPLIT_NEEDED}): {', '.join(needed)}"] if needed else []
                 ) + ([f"split-soon (>={SPLIT_SOON}): {', '.join(soon)}"] if soon else [])
        lines.append(f"WARN    branch size: {'; '.join(parts)} — split finished work from origin/main (D-1067)")
    if stale_no_pr:
        open_prs = open_pr_heads(root)
        if open_prs is not None:
            missing = [name for name, br in stale_no_pr if br not in open_prs]
            if missing:
                lines.append(f"WARN    no-pr (>{NO_PR_HOURS:.0f}h since first own commit, no open PR): {len(missing)} worktree(s): {', '.join(missing)}")
    return lines


def topic_ok(topic: str) -> bool:
    return len(topic) <= TOPIC_MAX and TOPIC.fullmatch(topic) is not None


def merge_targets(root: Path) -> list[str]:
    """Both local main and origin/main when present (D-1055 PR merges advance origin/main first)."""
    targets = [ref for ref in ("refs/heads/main", "refs/remotes/origin/main")
               if _git(root, "rev-parse", "--verify", "-q", ref).returncode == 0]
    return targets or ["refs/heads/main"]


def is_merged(root: Path, sha: str) -> bool:
    return any(_git(root, "merge-base", "--is-ancestor", sha, t).returncode == 0 for t in merge_targets(root))


def _merged_rows(root: Path, fmt: str) -> list[str]:
    seen, out = set(), []
    for target in merge_targets(root):
        listed = _git(root, "for-each-ref", "--merged", target, "refs/heads", f"--format={fmt}")
        if listed.returncode != 0:
            raise RuntimeError(f"git for-each-ref failed: {listed.stderr.strip()}")
        for line in listed.stdout.splitlines():
            if line not in seen:
                seen.add(line)
                out.append(line)
    return out


def sweep_branches(root: Path, now: float, apply: bool, say=print, quiet: bool = False, keep=frozenset()) -> int:
    """Delete (or, without ``apply``, count) local branches in main that no worktree has checked out."""
    common = root / _git(root, "rev-parse", "--git-common-dir").stdout.strip()
    done = 0
    for line in _merged_rows(root, "%(refname:short)\t%(objectname)\t%(worktreepath)"):
        branch, sha, checked_out = line.split("\t")
        # A reflog entry within the landed wait: just made, maybe about to be checked out. No reflog: not new.
        fresh = now - reflog_time(common / "logs" / "refs" / "heads" / branch) < LANDED_IDLE_HOURS * 3600
        if checked_out or fresh or branch in keep or branch == "main" or branch.startswith(RESERVED_PREFIXES):
            continue
        if apply and _git(root, "update-ref", "-d", f"refs/heads/{branch}", sha).returncode != 0:
            say(f"FAIL    branch {branch} moved; kept")  # exact sha: a commit not on main is never dropped
            continue
        if apply:
            _git(root, "config", "--remove-section", f"branch.{branch}")
        done += 1
    if done or not quiet:
        say(f"[worktrees] {'deleted' if apply else 'would delete'} {done} merged branch(es) no worktree uses")
    archive_abandoned(root, now, apply, say, quiet, keep)
    return done


def restore_archived(root: Path, branch: str) -> bool:
    """Put back the newest ``refs/archive/<branch>@<sha10>`` as the branch (create-only); False when there is none."""
    refs = _git(root, "for-each-ref", "--sort=-creatordate", "--format=%(objectname)", f"refs/archive/{branch}@*").stdout.split()
    return bool(refs) and _git(root, "update-ref", f"refs/heads/{branch}", refs[0], "").returncode == 0


def archive_abandoned(root: Path, now: float, apply: bool, say=print, quiet: bool = False, keep=frozenset()) -> int:
    """Move unlanded branches no worktree has and nobody committed to for ABANDON_DAYS to
    ``refs/archive/<branch>@<sha10>`` (11-14: 270 branches not in main, 219 without a worktree, 95 idle > 7 days).
    Nothing is lost: restore with ``git branch <branch> refs/archive/<branch>@<sha10>``."""
    merged_shas = set(_merged_rows(root, "%(objectname)"))
    listed = _git(root, "for-each-ref", "refs/heads",
                  "--format=%(refname:short)\t%(objectname)\t%(worktreepath)\t%(committerdate:unix)")
    if listed.returncode != 0:
        raise RuntimeError(f"git for-each-ref failed: {listed.stderr.strip()}")
    common = root / _git(root, "rev-parse", "--git-common-dir").stdout.strip()
    done = 0
    for line in listed.stdout.splitlines():
        branch, sha, checked_out, when = line.split("\t")
        if sha in merged_shas:
            continue
        # the reflog too: a branch just restored from refs/archive has an old tip but was touched now
        touched = max(int(when or now), reflog_time(common / "logs" / "refs" / "heads" / branch))
        # land/ leftovers too (11-22): D-1055 retired their resume path; a hidden tree's branch is checked out
        if (checked_out or branch in keep or branch.startswith(RESERVED_PREFIXES)
                or now - touched < ABANDON_DAYS * 86400):
            continue
        if apply:
            ref = f"refs/archive/{branch}@{sha[:10]}"
            # create-only with reflog (records archival timestamp), then drop the branch only at that exact sha
            if (_git(root, "update-ref", "--create-reflog", ref, sha, "").returncode != 0
                    and _git(root, "rev-parse", "--verify", "-q", ref).stdout.strip() != sha):
                say(f"FAIL    branch {branch}: could not write {ref}; kept")
                continue
            if _git(root, "update-ref", "-d", f"refs/heads/{branch}", sha).returncode != 0:
                say(f"FAIL    branch {branch} moved; kept (its archive ref stays)")
                continue
        done += 1  # branch.<name>.description (the owner) stays for a restore
    if done or not quiet:
        say(f"[worktrees] {'archived' if apply else 'would archive'} {done} unlanded branch(es) idle over"
            f" {ABANDON_DAYS} days with no worktree (refs/archive/<branch>@<sha>)")
    return done


def prune_remote(root: Path, now: float, apply: bool = False, days: float = REMOTE_PRUNE_DAYS, say=print) -> int:
    """Report (or with ``apply``, archive+delete own-only) stale unopened origin branches older than ``days``."""
    if _git(root, "rev-parse", "-q", "--verify", "refs/remotes/origin/main").returncode != 0:
        raise RuntimeError("refs/remotes/origin/main is missing; run 'git fetch origin' first")
    open_prs = open_pr_heads(root)
    if open_prs is None:
        say("[worktrees] remote prune skipped: could not read open PRs via gh (nothing deleted)")
        return 0
    me_email = _git(root, "config", "user.email").stdout.strip().lower()
    listed = _git(root, "for-each-ref", "refs/remotes/origin", "--format=%(refname:short)\t%(objectname)\t%(committerdate:unix)")
    if listed.returncode != 0:
        raise RuntimeError(f"git for-each-ref failed: {listed.stderr.strip()}")
    done, reported = 0, 0
    for line in listed.stdout.splitlines():
        short, sha, when = line.split("\t")
        if short == "origin" or not short.startswith("origin/"):
            continue
        branch = short.removeprefix("origin/")
        age_d = (now - int(when or now)) / 86400
        if branch in ("HEAD", "main") or branch in open_prs or branch.startswith(RESERVED_PREFIXES) or age_d < days:
            continue
        raw = _git(root, "log", "--format=%an\t%ae", f"refs/remotes/origin/main..refs/remotes/origin/{branch}").stdout.splitlines()
        if not raw:
            raw = _git(root, "log", "-1", "--format=%an\t%ae", f"refs/remotes/origin/{branch}").stdout.splitlines()
        pairs = [(n.strip(), e.strip()) for n, e in (r.split("\t", 1) for r in raw if "\t" in r)]
        authors = sorted({f"{n} <{e}>" for n, e in pairs}) or ["unknown"]
        if not (me_email and pairs and all(e.lower() == me_email for _, e in pairs)):
            reported += 1
            say(f"REPORT  origin/{branch} ({age_d:.0f}d, authors={', '.join(authors)}): teammate/other commits; report only")
            continue
        ref = f"refs/archive/origin/{branch}@{sha[:10]}"
        if not apply:
            say(f"PLAN    origin/{branch} ({age_d:.0f}d, sha={sha[:10]}, authors={', '.join(authors)}) -> {ref}")
            done += 1
            continue
        if (_git(root, "update-ref", "--create-reflog", ref, sha, "").returncode != 0
                and _git(root, "rev-parse", "--verify", "-q", ref).stdout.strip() != sha):
            say(f"FAIL    origin/{branch}: could not write {ref}; kept")
            continue
        res = subprocess.run(["git", "-c", "core.quotepath=off", "-C", str(root), "push", "origin",
                              f"--force-with-lease=refs/heads/{branch}:{sha}", f":refs/heads/{branch}"],
                             env={**os.environ, "ROSY_STATIC_PRE_PUSH": "1"}, capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
        if res.returncode != 0:
            say(f"FAIL    origin/{branch}: delete failed (archive ref stays): {(res.stderr or res.stdout).strip()}")
            continue
        say(f"DELETED origin/{branch} ({age_d:.0f}d, archived {ref})")
        done += 1
    say(f"[worktrees] {'deleted' if apply else 'would delete'} {done} remote branch(es) idle over {days:.0f} days"
        f" with no open PR (own commits only; {reported} teammate/other reported)")
    return done


def _safe_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def newest_file(path: Path, is_cache) -> float:
    """Newest mtime of any file outside ``.git`` and the caches: a used worktree that git sees as unchanged is active.
    shortcut: a full walk per judged worktree, run only when the cheap facts did not decide."""
    newest = 0.0
    for folder, dirs, files in os.walk(path):
        inside = Path(folder).relative_to(path).as_posix()
        dirs[:] = [d for d in dirs if d != ".git" and not is_cache(f"{'' if inside == '.' else inside + '/'}{d}/")]
        newest = max([newest, *(_safe_mtime(os.path.join(folder, n)) for n in files if n != ".git")])
    return newest


def owner_notes(root: Path, git) -> tuple[dict[str, str], dict[str, float]]:
    """(branch -> identity, branch -> epoch) from the note ``new`` wrote in ``branch.<name>.description``:
    "owner: <identity>[; at <epoch>][; over cap ...]". A note without a stamp has no epoch; no identity is no owner."""
    lines = git(root, "config", "--get-regexp", r"^branch\..*\.description$").stdout.splitlines()
    owners, stamps = {}, {}
    for key, _, value in (line.partition(" ") for line in lines):
        if not value.startswith("owner: "):
            continue
        branch = key[len("branch."):-len(".description")]
        who = value.removeprefix("owner: ").split("; over cap")[0]
        stamp = re.search(r"; at (\d+)", who)
        who = who.split("; at ")[0]
        if who.strip(" <>;"):  # " <>": no git identity was set
            owners[branch] = who
        if stamp:
            stamps[branch] = float(stamp.group(1))
    return owners, stamps
