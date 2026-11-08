"""tools/land_gc.py: leftovers of stopped or landed land_async landings go only when nothing is lost (2026-11-01)."""

import json
from contextlib import contextmanager
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


@pytest.fixture(autouse=True)
def scratch_root(tmp_path, monkeypatch):
    """plan() also sweeps landing scratch folders: never the test host's real one."""
    monkeypatch.setenv("ROSY_LAND_TMP", str(tmp_path / "rosy-land"))


@contextmanager
def supervisor_lease(tree):
    """A real process owns the pre-ticket lease without refreshing the landing's old log."""
    code = ("import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import land_async;\n"
            "with land_async.locked(Path(sys.argv[2])):\n print('ready',flush=True);sys.stdin.readline()")
    process = subprocess.Popen([sys.executable, "-c", code, str(ROOT / "tools"),
                                str(tree.parent / (tree.name + ".supervisor.lock"))],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == "ready"
        yield
    finally:
        process.stdin.close()
        process.wait(timeout=10)


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


def test_sidecars_without_tree_or_branch_are_removed(landing):
    repo, common, _, _ = landing
    marker = common / land_gc.HOLDER / "land-feat-gone-20261102000009.stopped"
    marker.write_text("STOP")
    rows = land_gc.plan(repo, time.time(), 7)
    assert land_gc.apply(repo, rows) == []
    assert not marker.exists()


def test_pre_ticket_supervisor_keeps_landed_old_tree(landing):
    repo, common, tree, branch = landing
    assert not (common / land_gc.QUEUE).exists()
    assert time.time() - (tree.parent / (tree.name + ".log")).stat().st_mtime > land_gc.QUIET_S
    assert git(repo, "rev-parse", branch) == git(repo, "rev-parse", "main")
    with supervisor_lease(tree):
        lease = tree.parent / (tree.name + ".supervisor.lock")
        inode = lease.stat().st_ino
        rows = land_gc.plan(repo, time.time(), 7)
        assert next(row[0] for row in rows if row[2] == tree) == "keep"
        assert land_gc.apply(repo, rows) == []
        assert tree.exists() and git(repo, "rev-parse", branch)
        assert lease.stat().st_ino == inode, "a live lease must never be unlinked"
    assert land_gc.apply(repo, land_gc.plan(repo, time.time(), 7)) == []
    assert not tree.exists() and lease.stat().st_ino == inode


@pytest.mark.parametrize("after_revalidation", [False, True])
def test_apply_keeps_supervisor_starting_after_plan(landing, monkeypatch, after_revalidation):
    repo, _, tree, branch = landing
    rows = land_gc.plan(repo, time.time(), 7)
    assert next(row[0] for row in rows if row[2] == tree) == "remove"
    lease = supervisor_lease(tree)
    if after_revalidation:
        original = land_gc.plan

        def refresh(*args, **kwargs):
            fresh = original(*args, **kwargs)
            lease.__enter__()
            return fresh

        monkeypatch.setattr(land_gc, "plan", refresh)
    else:
        lease.__enter__()
    try:
        assert land_gc.apply(repo, rows), "new ownership must prevent removal and report the changed state"
        assert tree.exists() and git(repo, "rev-parse", branch)
        assert (tree.parent / (tree.name + ".stopped")).exists()
    finally:
        lease.__exit__(None, None, None)


def test_superseded_snapshots_go_once_a_newer_snapshot_or_the_live_branch_holds_them(landing):
    repo, common, old, branch = landing
    holder = common / land_gc.HOLDER
    (old / "a.txt").write_text("a\n")
    git(old, "add", "a.txt")
    git(old, "commit", "-q", "-m", "A")
    newer_branch = "land/feat/protected-20261102000002"
    newer = holder / newer_branch.replace("/", "-")
    git(repo, "worktree", "add", "-q", "-b", newer_branch, str(newer), branch)  # A, then B on top
    (newer / "b.txt").write_text("b\n")
    git(newer, "add", "b.txt")
    git(newer, "commit", "-q", "-m", "B")
    for suffix in (".log", ".stopped"):
        (holder / f"{newer.name}{suffix}").write_text("x\n")
        os.utime(holder / f"{newer.name}{suffix}", (OLD, OLD))
    rows = land_gc.plan(repo, time.time(), 7)
    verdict = {t.name: (action, why) for action, why, t, _ in rows if t}
    assert verdict[old.name][0] == "remove"
    assert verdict[newer.name] == ("keep", "unlanded work (2 commit(s) not in main)")
    assert land_gc.apply(repo, rows) == []
    assert not old.exists() and (holder / f"{old.name}.log").exists()
    git(repo, "branch", "feat/protected", newer_branch)  # the live branch now carries A and B
    assert next(a for a, _, t, _ in land_gc.plan(repo, time.time(), 7) if t == newer) == "remove"


def test_a_merge_git_reproduces_is_not_unique_but_a_hand_resolved_one_is(landing):
    repo, common, tree, branch = landing
    git(repo, "commit", "-q", "--allow-empty", "-m", "main moves")
    git(tree, "merge", "-q", "--no-ff", "--no-edit", "main")
    assert land_gc.reproducible(repo, git(tree, "rev-parse", "HEAD"))
    assert next(a for a, _, t, _ in land_gc.plan(repo, time.time(), 7) if t == tree) == "remove"
    git(repo, "commit", "-q", "--allow-empty", "-m", "main again")
    git(tree, "merge", "-q", "--no-ff", "--no-commit", "main")
    (tree / "hand.txt").write_text("hand\n")
    git(tree, "add", "hand.txt")
    git(tree, "commit", "-q", "--no-edit")
    assert not land_gc.reproducible(repo, git(tree, "rev-parse", "HEAD"))
    assert next(a for a, _, t, _ in land_gc.plan(repo, time.time(), 7) if t == tree) == "keep"


def test_old_landing_scratch_goes_but_a_live_or_recent_one_stays(landing, tmp_path, monkeypatch):
    repo, common, _, _ = landing
    scratch = tmp_path / "rosy-land"
    # feat-protected: the fixture's kept snapshot, whose scratch explains its STOP
    old, recent, live, kept = (scratch / n for n in ("fix-old", "fix-recent", "feat-alive", "feat-protected"))
    for folder, age in ((old, OLD), (recent, time.time()), (live, OLD), (kept, OLD)):
        folder.mkdir(parents=True)
        (folder / "run-1.txt").write_text("x\n")
        os.utime(folder / "run-1.txt", (age, age))
    (common / "rosy-land-queue").mkdir()
    (common / "rosy-land-queue" / "01-1.json").write_text(json.dumps(
        {"pid": os.getpid(), "branch": "feat/alive", "worktree": str(tmp_path), "status": "pending"}))
    rows = land_gc.plan(repo, time.time(), 7)
    assert [items for action, _, _, items in rows if action == "tmp"] == [[str(old)]]
    assert land_gc.apply(repo, rows) == []
    assert not old.exists() and recent.exists() and live.exists() and kept.exists()
    monkeypatch.setenv("ROSY_LAND_TMP", str(scratch.parent))  # a root not named rosy-land is never swept
    assert not [row for row in land_gc.plan(repo, time.time(), 7) if row[0] == "tmp"]
