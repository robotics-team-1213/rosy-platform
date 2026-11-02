"""tools/land_gc.py: leftovers of stopped or landed land_async landings go only when nothing is lost (2026-11-01)."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import land_gc  # noqa: E402

OLD = time.time() - 30 * 86400


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def hidden(repo, holder, branch, extra=False, log_age=OLD):
    name = branch.replace("/", "-")
    git(repo, "worktree", "add", "-q", "-b", branch, str(holder / name), "main")
    if extra:
        (holder / name / "x.txt").write_text(f"{branch}\n")  # same content and second would share one SHA
        git(holder / name, "add", "x.txt")
        git(holder / name, "commit", "-q", "-m", "unlanded")
    for suffix in (".log", ".stopped", ".land_async.py"):
        path = holder / f"{name}{suffix}"
        path.write_text("x\n")
        os.utime(path, (log_age, log_age))
    return holder / name


def test_only_landings_with_nothing_unique_and_no_live_ticket_are_removed(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("a\n")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", "init")
    common = Path(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    holder = common / "rosy-land-wt"
    holder.mkdir()
    landed = hidden(repo, holder, "land/feat/landed-20261101000001")
    unlanded = hidden(repo, holder, "land/feat/unlanded-20261101000002", extra=True)
    alive = hidden(repo, holder, "land/feat/alive-20261101000003", extra=True)
    fresh = hidden(repo, holder, "land/feat/fresh-20261101000004", log_age=time.time())
    git(repo, "branch", "land/v2-hand-made")  # not a land_async snapshot: never touched
    (common / "rosy-land-queue").mkdir()
    (common / "rosy-land-queue" / "01-1.json").write_text(json.dumps(
        {"pid": os.getpid(), "branch": "land/feat/alive-20261101000003", "worktree": str(alive), "status": "pending"}))
    gone = holder / "land-feat-gone-1.log"
    gone.write_text("STOP\n")
    os.utime(gone, (OLD, OLD))

    rows = land_gc.plan(repo, time.time(), 7)
    verdict = {(t.name if t else items[0]): (action, reason) for action, reason, t, items in rows}
    assert verdict["land-feat-landed-20261101000001"][0] == "remove"
    assert verdict["land-feat-unlanded-20261101000002"] == ("keep", "unlanded work (1 commit(s) not in main)")
    assert verdict["land-feat-alive-20261101000003"] == ("keep", "live ticket")
    assert verdict["land-feat-fresh-20261101000004"] == ("keep", "log written in the last hour")
    assert verdict[str(gone)][0] == "log"

    assert land_gc.apply(repo, rows) == []
    assert not landed.exists() and not git(repo, "branch", "--list", "land/feat/landed-20261101000001")
    assert not (holder / "land-feat-landed-20261101000001.stopped").exists()
    assert (holder / "land-feat-landed-20261101000001.log").exists(), "the log stays for its owner"
    assert unlanded.exists() and alive.exists() and fresh.exists() and not gone.exists()
    assert git(repo, "branch", "--list", "land/v2-hand-made")
    assert "land-v2-hand-made" not in verdict


@pytest.fixture
def landing(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "user.name", "t")
    git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    git(repo, "commit", "-q", "--allow-empty", "-m", "main")
    common = Path(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    holder = common / land_gc.HOLDER
    holder.mkdir()
    branch = "land/feat/protected-20261102000001"
    return repo, common, hidden(repo, holder, branch), branch


@pytest.mark.parametrize("kind", ["untracked", "ignored", "merge", "orphan"])
def test_plan_preserves_all_unrepresented_work(landing, kind):
    repo, _, tree, branch = landing
    if kind == "ignored":
        (tree / ".gitignore").write_text("private/\n")
        git(tree, "add", ".gitignore")
        git(tree, "commit", "-q", "-m", "ignore")
        git(repo, "merge", "--ff-only", branch)
        (tree / "private").mkdir()
        (tree / "private" / "data").write_text("keep")
    elif kind == "merge":
        (tree / "resolution").write_text("merge-only resolution")
        git(tree, "add", "resolution")
        sha = git(tree, "commit-tree", git(tree, "write-tree"), "-p", "main", "-p", "main~1", "-m", "resolution")
        git(tree, "reset", "--hard", sha)
    elif kind == "orphan":
        git(repo, "worktree", "remove", str(tree))
        tree.mkdir()
        (tree / "user-data").write_text("keep")
    else:
        (tree / "user-data").write_text("keep")
    rows = land_gc.plan(repo, time.time(), 7)
    assert next(row[0] for row in rows if row[2] == tree) == "keep"
    assert land_gc.apply(repo, rows) == []
    assert tree.exists()
    assert git(repo, "rev-parse", branch)


def test_git_failure_is_not_an_empty_safe_result(tmp_path):
    with pytest.raises(subprocess.CalledProcessError):
        land_gc.plan(tmp_path, time.time(), 7)


@pytest.mark.parametrize("change", ["untracked", "head", "branch", "ticket", "fresh-log"])
def test_apply_rechecks_plan_before_removal(landing, change):
    repo, common, tree, branch = landing
    rows = land_gc.plan(repo, time.time(), 7)
    assert next(row[0] for row in rows if row[2] == tree) == "remove"
    if change == "untracked":
        (tree / "new-data").write_text("keep")
    elif change == "head":
        git(tree, "checkout", "--detach", "main~1")
    elif change == "branch":
        git(tree, "checkout", "--detach")
        git(repo, "update-ref", f"refs/heads/{branch}", "main~1")
    elif change == "ticket":
        queue = common / land_gc.QUEUE
        queue.mkdir()
        (queue / "01-1.json").write_text(json.dumps({"pid": os.getpid(), "branch": branch, "worktree": str(tree)}))
    else:
        (tree.parent / f"{tree.name}.log").touch()
    assert land_gc.apply(repo, rows), "a stale plan must report the skipped removal"
    assert tree.exists()
    assert git(repo, "rev-parse", branch)


def test_main_reports_failed_removal(landing, monkeypatch):
    repo, _, tree, _ = landing
    git(repo, "worktree", "lock", str(tree))
    monkeypatch.chdir(repo)
    assert land_gc.main(["--apply"]) != 0
    assert tree.exists()


def test_snapshot_checked_out_elsewhere_is_kept(landing, tmp_path):
    repo, _, tree, branch = landing
    moved = tmp_path / "active"
    git(repo, "worktree", "move", str(tree), str(moved))
    rows = land_gc.plan(repo, time.time(), 7)
    assert land_gc.apply(repo, rows) == []
    assert git(repo, "rev-parse", branch)
    assert moved.exists()


def test_apply_history_revalidation_is_linear(landing, monkeypatch):
    repo, common, _, _ = landing
    for i in range(3):
        hidden(repo, common / land_gc.HOLDER, f"land/feat/other-2026110200000{i + 2}")
    rows = land_gc.plan(repo, time.time(), 7)
    original, calls = land_gc.git, []

    def counted(path, *args):
        if args[0] == "rev-list":
            calls.append(args)
        return original(path, *args)

    monkeypatch.setattr(land_gc, "git", counted)
    assert land_gc.apply(repo, rows) == []
    assert len(calls) == 4, "each candidate's history is rechecked once"
