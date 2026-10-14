"""tools/worktrees.py against throwaway git repos: a main checkout and worktrees under .worktrees/."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import land  # noqa: E402
import worktrees  # noqa: E402

HOUR = 3600
LATER = time.time() + 75 * HOUR  # past the 72 h default: every worktree made in a test is idle by then
DAY = time.strftime("%Y-%m-%d", time.localtime(LATER))


def git(cwd: Path, *args: str, **env: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True,
                          env={**os.environ, **env}).stdout.strip()


def refs(main: Path, pattern: str) -> list[str]:
    return git(main, "for-each-ref", "--format=%(refname)", pattern).split()


@pytest.fixture
def main(tmp_path, monkeypatch):
    main = tmp_path / "main"
    main.mkdir()
    git(main, "init", "-q", "-b", "main")
    for key, value in (("user.name", "t"), ("user.email", "t@t"), ("core.autocrlf", "false")):
        git(main, "config", key, value)
    (main / ".gitignore").write_text(".worktrees/\nbuild/\ninstall/\nlog/\n.omc/\nsecret.env\n", encoding="utf-8")
    (main / "a.txt").write_text("base\n", encoding="utf-8")
    git(main, "add", ".gitignore", "a.txt")
    git(main, "commit", "-q", "-m", "init")
    monkeypatch.chdir(main)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    return main


ME = "t <t@t>"  # the fixture's git identity; no agent session in the environment


def add(main: Path, name: str, commit: bool = False, merge: bool = False, owner: str | None = ME) -> Path:
    """A worktree on feat/<name>, owned by the caller unless told otherwise; optionally committed and landed."""
    wt = main / ".worktrees" / name
    git(main, "worktree", "add", "-q", str(wt), "-b", f"feat/{name}", "main")
    if owner:
        git(main, "config", f"branch.feat/{name}.description", f"owner: {owner}")
    if commit:
        (wt / f"{name}.txt").write_text(name, encoding="utf-8")
        git(wt, "add", f"{name}.txt")
        git(wt, "commit", "-q", "-m", name)
    if merge:
        git(main, "merge", "-q", "--ff-only", f"feat/{name}")
    return wt


def wrap_git(monkeypatch, hook):
    """Route worktrees.git through hook(real, cwd, args); hook returns a result or None for the real call."""
    real = worktrees.git

    def patched(cwd, *args, env=None):
        result = hook(real, cwd, args)
        return real(cwd, *args, env=env) if result is None else result

    monkeypatch.setattr(worktrees, "git", patched)


def test_clean_merged_worktree_is_pruned_with_its_branch(main):
    wt = add(main, "done", commit=True, merge=True)
    assert worktrees.prune(main, now=LATER) == 1  # dry run: counted, nothing touched
    assert wt.is_dir() and refs(main, "refs/heads/feat") == ["refs/heads/feat/done"]
    assert worktrees.prune(main, apply=True, now=LATER) == 1
    assert not wt.exists()
    assert refs(main, "refs/heads/feat") == []
    assert "feat/done" not in git(main, "config", "--list")
    assert (main / "done.txt").read_text(encoding="utf-8") == "done"


def test_clean_unmerged_worktree_needs_snapshot_and_keeps_its_branch(main):
    wt = add(main, "open", commit=True)
    tip = git(wt, "rev-parse", "HEAD")
    assert worktrees.prune(main, apply=True, now=LATER) == 0
    assert wt.is_dir()
    assert worktrees.prune(main, apply=True, snapshot=True, now=LATER) == 1
    assert not wt.exists()
    assert git(main, "rev-parse", "feat/open") == tip
    assert refs(main, "refs/wip") == []  # nothing uncommitted and a branch holds the commits


def _dirty(wt: Path) -> None:
    (wt / "a.txt").write_text("modified\n", encoding="utf-8")
    (wt / "staged.txt").write_text("staged\n", encoding="utf-8")
    (wt / "both.txt").write_text("index\n", encoding="utf-8")
    git(wt, "add", "staged.txt", "both.txt")
    (wt / "both.txt").write_text("disk\n", encoding="utf-8")  # staged, then edited again
    (wt / "notes").mkdir()
    (wt / "notes" / "untracked.txt").write_text("untracked\n", encoding="utf-8")


def test_dirty_worktree_is_kept_without_snapshot_and_kept_under_refs_wip_with_it(main):
    wt = add(main, "dirty")
    head = git(wt, "rev-parse", "HEAD")
    _dirty(wt)
    assert worktrees.prune(main, apply=True, now=LATER) == 0
    assert wt.is_dir() and refs(main, "refs/wip") == []

    assert worktrees.prune(main, apply=True, snapshot=True, now=LATER) == 1
    ref = f"refs/wip/{DAY}/dirty"
    assert refs(main, "refs/wip") == [ref]
    assert refs(main, "refs/tags") == []  # `git push --tags` must not publish uncommitted work
    assert git(main, "show", f"{ref}:a.txt") == "modified"
    assert git(main, "show", f"{ref}:staged.txt") == "staged"
    assert git(main, "show", f"{ref}:both.txt") == "disk"
    assert git(main, "show", f"{ref}:notes/untracked.txt") == "untracked"
    assert git(main, "rev-parse", f"{ref}^") == head
    assert not wt.exists()
    assert (main / "a.txt").read_text(encoding="utf-8") == "base\n"


def test_snapshot_ref_collision_gets_a_suffix(main):
    git(main, "update-ref", f"refs/wip/{DAY}/dirty", "main")
    _dirty(add(main, "dirty"))
    assert worktrees.prune(main, apply=True, snapshot=True, now=LATER) == 1
    assert git(main, "show", f"refs/wip/{DAY}/dirty-2:notes/untracked.txt") == "untracked"
    assert git(main, "rev-parse", f"refs/wip/{DAY}/dirty") == git(main, "rev-parse", "main")


def test_nested_git_repository_blocks_the_snapshot(main, capsys):
    wt = add(main, "nest")
    nested = wt / "vendor"
    nested.mkdir()
    git(nested, "init", "-q", "-b", "main")
    (nested / "x.txt").write_text("history lives here", encoding="utf-8")
    git(nested, "add", "x.txt")
    git(nested, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "nested")
    assert worktrees.prune(main, apply=True, snapshot=True, now=LATER) == 0
    assert "nested git repository" in capsys.readouterr().out
    assert (nested / ".git").is_dir() and refs(main, "refs/wip") == []


def test_detached_unmerged_head_is_kept_under_refs_wip(main):
    wt = add(main, "loose", commit=True)
    tip = git(wt, "rev-parse", "HEAD")
    git(wt, "checkout", "-q", "--detach")
    git(main, "branch", "-q", "-D", "feat/loose")  # now only the detached HEAD reaches the commit
    assert worktrees.prune(main, apply=True, everyone=True, now=LATER) == 0
    assert worktrees.prune(main, apply=True, snapshot=True, now=LATER) == 0  # no branch, so no owner
    assert worktrees.prune(main, apply=True, snapshot=True, everyone=True, now=LATER) == 1
    assert not wt.exists()
    assert git(main, "rev-parse", f"refs/wip/{DAY}/loose") == tip


def test_rebase_in_progress_blocks_removal(main):
    wt = add(main, "mid")
    (wt / "a.txt").write_text("branch\n", encoding="utf-8")
    git(wt, "commit", "-q", "-am", "branch side")
    (main / "a.txt").write_text("main\n", encoding="utf-8")
    git(main, "commit", "-q", "-am", "main side")
    stopped = subprocess.run(["git", "-C", str(wt), "rebase", "main"], capture_output=True, text=True)
    assert stopped.returncode != 0
    assert worktrees.prune(main, apply=True, snapshot=True, now=LATER) == 0
    assert wt.is_dir() and refs(main, "refs/wip") == []
    git(wt, "rebase", "--abort")
    assert worktrees.prune(main, apply=True, snapshot=True, now=LATER) == 1


def test_ignored_non_cache_file_blocks_removal_and_a_cache_does_not(main):
    wt = add(main, "data", commit=True, merge=True)
    (wt / "build").mkdir()
    (wt / "build" / "x.o").write_text("cache", encoding="utf-8")
    (wt / "secret.env").write_text("KEY=1", encoding="utf-8")
    assert git(wt, "status", "--porcelain") == ""  # both are ignored: git calls this worktree clean
    assert worktrees.prune(main, apply=True, snapshot=True, now=LATER) == 0
    assert (wt / "secret.env").read_text(encoding="utf-8") == "KEY=1"
    (wt / "secret.env").unlink()
    assert worktrees.prune(main, apply=True, now=LATER) == 1
    assert not wt.exists()


def test_agent_state_under_omc_blocks_removal(main):
    wt = add(main, "state", commit=True, merge=True)
    (wt / ".omc").mkdir()
    (wt / ".omc" / "notes.md").write_text("handoff", encoding="utf-8")
    assert worktrees.prune(main, apply=True, snapshot=True, now=LATER) == 0
    assert (wt / ".omc" / "notes.md").is_file()


def test_log_dir_is_a_cache_only_at_the_root_or_beside_a_marker(main):
    wt = add(main, "bags", commit=True, merge=True)
    for rel in ("build/a", "install/b", "log/c",                      # worktree root
                "ws/build/a", "ws/install/setup.bash", "ws/log/c",   # colcon workspace: install/setup.*
                "data/log/run.bag"):                                  # recorded data in a directory named log
        (wt / rel).parent.mkdir(parents=True, exist_ok=True)
        (wt / rel).write_text("x", encoding="utf-8")
    assert git(wt, "status", "--porcelain") == ""
    assert worktrees.prune(main, apply=True, now=LATER) == 0
    assert (wt / "data" / "log" / "run.bag").is_file()
    shutil.rmtree(wt / "data")
    assert worktrees.prune(main, apply=True, now=LATER) == 1
    assert not wt.exists()


def test_locked_worktree_is_never_removed(main):
    wt = add(main, "held", commit=True, merge=True)
    git(main, "worktree", "lock", str(wt))
    assert worktrees.prune(main, apply=True, snapshot=True, now=LATER) == 0
    assert wt.is_dir() and refs(main, "refs/heads/feat") == ["refs/heads/feat/held"]


def test_idle_threshold_is_respected(main):
    wt = add(main, "fresh", commit=True, merge=True)
    now = time.time()
    assert worktrees.prune(main, apply=True, snapshot=True, now=now) == 0
    assert worktrees.prune(main, apply=True, snapshot=True, now=now + 71 * HOUR) == 0
    assert wt.is_dir()


def test_idle_counts_uncommitted_files_and_the_given_threshold(main):
    wt = add(main, "fresh", commit=True, merge=True)
    now = time.time()
    assert worktrees.prune(main, apply=True, now=now + 100 * HOUR, idle_hours=200) == 0
    # An uncommitted file written an hour before the clock keeps the worktree active.
    note = wt / "note.txt"
    note.write_text("wip", encoding="utf-8")
    os.utime(note, (LATER - HOUR, LATER - HOUR))
    assert worktrees.prune(main, apply=True, snapshot=True, now=LATER) == 0
    assert note.is_file()
    note.unlink()
    assert worktrees.prune(main, apply=True, now=now + 73 * HOUR) == 1
    assert not wt.exists()


def test_fresh_worktree_on_an_old_main_tip_is_active_and_so_is_one_without_a_reflog(main):
    old = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 100 * HOUR))
    git(main, "commit", "-q", "--allow-empty", "-m", "old tip", GIT_COMMITTER_DATE=old, GIT_AUTHOR_DATE=old)
    fresh = add(main, "fresh")  # no commit of its own: only .git and logs/HEAD say it is new
    assert worktrees.prune(main, apply=True, now=time.time()) == 0
    assert fresh.is_dir()
    blind = add(main, "blind")
    (Path(git(blind, "rev-parse", "--absolute-git-dir")) / "logs" / "HEAD").unlink()
    assert worktrees.prune(main, apply=True, snapshot=True, now=LATER) == 1  # `fresh` is idle by then
    assert blind.is_dir() and not fresh.exists()


def test_commit_between_scan_and_removal_keeps_the_worktree(main, monkeypatch, capsys):
    wt = add(main, "racy", commit=True, merge=True)
    real = worktrees._status

    def commit_then_status(path):
        (path / "late.txt").write_text("late", encoding="utf-8")
        git(path, "add", "late.txt")
        git(path, "commit", "-q", "-m", "landed after the scan")
        return real(path)

    monkeypatch.setattr(worktrees, "_status", commit_then_status)
    assert worktrees.prune(main, apply=True, now=LATER) == 0
    assert "changed since the scan" in capsys.readouterr().out
    assert (wt / "late.txt").is_file()
    assert git(main, "rev-parse", "feat/racy") == git(wt, "rev-parse", "HEAD")


def test_branch_that_moved_before_its_deletion_is_kept(main, monkeypatch):
    wt = add(main, "done", commit=True, merge=True)
    elsewhere = git(add(main, "open", commit=True), "rev-parse", "HEAD")
    git(main, "worktree", "lock", str(main / ".worktrees" / "open"))

    def move_after_remove(real, cwd, args):
        if args[:2] != ("worktree", "remove"):
            return None
        result = real(cwd, *args)
        git(main, "update-ref", "refs/heads/feat/done", elsewhere)
        return result

    wrap_git(monkeypatch, move_after_remove)
    assert worktrees.prune(main, apply=True, now=LATER) == 1
    assert not wt.exists()
    assert git(main, "rev-parse", "feat/done") == elsewhere


def test_failed_remove_keeps_the_branch_and_reports_an_orphan(main, monkeypatch, capsys):
    wt = add(main, "stuck", commit=True, merge=True)

    def half_remove(real, cwd, args):
        if args[:2] != ("worktree", "remove"):
            return None
        (wt / ".git").unlink()  # what an open handle leaves on Windows: git forgets it, the files stay
        real(cwd, "worktree", "prune")
        return subprocess.CompletedProcess(args, 1, "", "error: failed to delete: Permission denied")

    wrap_git(monkeypatch, half_remove)
    assert worktrees.main(["prune", "--apply"], now=LATER) == 0
    out = capsys.readouterr().out
    assert "ORPHAN  " in out and "FAIL    stuck" in out
    assert refs(main, "refs/heads/feat") == ["refs/heads/feat/stuck"]

    assert worktrees.main(["status"], now=LATER) == 0
    assert [line for line in capsys.readouterr().out.splitlines() if line.startswith("stuck ")][0].endswith("orphan")
    monkeypatch.setattr(worktrees, "CAP", 1)  # the orphan counts toward the cap
    assert worktrees.main(["new", "more", "feat/more"]) == 1
    assert worktrees.prune(main, apply=True, snapshot=True, everyone=True, now=LATER) == 0  # not empty
    assert (wt / "a.txt").is_file()
    shutil.rmtree(wt)
    wt.mkdir()
    assert worktrees.prune(main, apply=True, now=LATER) == 0  # an orphan has no owner
    assert worktrees.prune(main, apply=True, everyone=True, now=LATER) == 1
    assert not wt.exists()


def test_second_applying_prune_is_refused_until_the_lock_is_stale(main):
    wt = add(main, "done", commit=True, merge=True)
    lock = main / ".git" / "worktrees-prune.lock"
    lock.write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError, match="another prune is running"):
        worktrees.prune(main, apply=True, now=LATER)
    assert wt.is_dir() and lock.is_file()
    assert worktrees.prune(main, now=LATER) == 1  # a dry run needs no lock
    os.utime(lock, (time.time() - 31 * 60, time.time() - 31 * 60))
    assert worktrees.prune(main, apply=True, now=LATER) == 1
    assert not wt.exists() and not lock.exists()


def test_the_worktree_the_tool_runs_in_is_never_removed(main, monkeypatch):
    mine = add(main, "mine", commit=True, merge=True)
    other = add(main, "other")
    monkeypatch.chdir(mine)
    assert worktrees.main(["prune", "--snapshot", "--apply"], now=LATER) == 0
    assert mine.is_dir() and not other.exists()
    assert refs(main, "refs/heads/feat") == ["refs/heads/feat/mine"]


def test_status_names_a_verdict_per_worktree(main, capsys):
    add(main, "done", commit=True, merge=True)
    add(main, "open", commit=True)
    git(main, "worktree", "lock", str(add(main, "held")))
    assert worktrees.main(["status"], now=LATER) == 0
    verdict = {line.split()[0]: line for line in capsys.readouterr().out.splitlines()}
    assert "yes   removable" in verdict["done"]
    assert "yes   needs snapshot" in verdict["open"]
    assert "-     locked" in verdict["held"]
    assert worktrees.main(["status"]) == 0
    assert all("-     active" in line for line in capsys.readouterr().out.splitlines()
               if line.split()[0] in ("done", "open"))


def test_new_creates_below_the_cap_and_refuses_at_it(main, monkeypatch, capsys):
    monkeypatch.setattr(worktrees, "CAP", 2)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-7")
    assert worktrees.main(["new", "one", "fix/one"]) == 0
    assert Path(capsys.readouterr().out.strip()).resolve() == (main / ".worktrees" / "one").resolve()
    assert worktrees.main(["new", "two", "docs/two"]) == 0
    assert refs(main, "refs/heads") == ["refs/heads/docs/two", "refs/heads/fix/one", "refs/heads/main"]

    assert worktrees.main(["new", "three", "feat/three"]) == 1
    err = capsys.readouterr().err
    assert "the cap is 2" in err and "one" in err
    assert "python tools/worktrees.py status" in err and worktrees.SWEEP in err
    assert "--snapshot --" not in err and "person or the dispatcher" in err  # no blanket snapshot command
    assert not (main / ".worktrees" / "three").exists() and "refs/heads/feat/three" not in refs(main, "refs/heads")

    assert worktrees.main(["new", "three", "feat/three", "--force-over-cap", "  "]) == 1
    assert worktrees.main(["new", "three", "feat/three", "--force-over-cap", "incident 42"]) == 0
    assert "incident 42" in capsys.readouterr().out
    assert (main / ".worktrees" / "three" / "a.txt").is_file()
    assert git(main / ".worktrees" / "three", "rev-parse", "--abbrev-ref", "HEAD") == "feat/three"
    # Who made it and why it went over the cap are recorded and shown.
    assert git(main, "config", "branch.fix/one.description") == "owner: t <t@t>; session sess-7"
    assert "incident 42" in git(main, "config", "branch.feat/three.description")
    assert worktrees.main(["status"]) == 0
    assert "[t <t@t>; session sess-7]" in capsys.readouterr().out


def test_new_reports_finished_worktrees_and_removes_them_only_with_prune(main, monkeypatch, capsys):
    monkeypatch.setattr(worktrees, "CAP", 2)
    done = add(main, "done", commit=True, merge=True)
    kept = add(main, "open", commit=True)
    assert worktrees.main(["new", "next", "refactor/next"], now=LATER) == 1  # at the cap: nothing was swept
    assert f"1 finished worktree(s) can be removed: {worktrees.SWEEP}" in capsys.readouterr().out
    assert done.is_dir()
    assert worktrees.main(["new", "next", "refactor/next", "--no-prune"], now=LATER) == 1
    assert "can be removed" not in capsys.readouterr().out
    assert worktrees.main(["new", "next", "refactor/next", "--prune"], now=LATER) == 0
    assert not done.exists()
    assert kept.is_dir()  # unmerged: `new` never snapshots


def test_prune_takes_only_the_callers_worktrees_unless_all(main, capsys):
    mine = add(main, "mine", commit=True, merge=True)
    peer = add(main, "peer", commit=True, merge=True, owner="t <t@t>; session other")
    bare = add(main, "bare", commit=True, merge=True, owner=None)  # a bare `git worktree add`
    assert worktrees.main(["status"], now=LATER) == 0
    line = {text.split()[0]: text for text in capsys.readouterr().out.splitlines()}
    assert "yes   removable" in line["mine"]
    assert "--all removable" in line["peer"] and "[t <t@t>; session other]" in line["peer"]
    assert "--all removable" in line["bare"]
    assert worktrees.main(["prune", "--snapshot", "--apply"], now=LATER) == 0
    out = capsys.readouterr().out
    assert "owner unowned: only with --all" in out and "owner t <t@t>; session other: only with --all" in out
    assert not mine.exists() and peer.is_dir() and bare.is_dir()
    assert worktrees.main(["prune", "--apply", "--all"], now=LATER) == 0
    assert not peer.exists() and not bare.exists()


def test_cap_refusal_counts_removable_worktrees_per_owner(main, monkeypatch, capsys):
    monkeypatch.setattr(worktrees, "CAP", 3)
    add(main, "mine", commit=True, merge=True)
    add(main, "bare", commit=True, merge=True, owner=None)
    add(main, "open", commit=True, owner=None)  # unmerged: not removable, not counted
    assert worktrees.main(["new", "x", "feat/x", "--no-prune"], now=LATER) == 1
    err = capsys.readouterr().err
    assert "removable, owner t <t@t>: 1" in err and "removable, owner unowned: 1" in err


def test_status_explains_a_tip_that_is_a_merge_of_main(main, capsys):
    half = add(main, "half", commit=True)
    add(main, "open", commit=True)
    (main / "m.txt").write_text("m", encoding="utf-8")
    git(main, "add", "m.txt")
    git(main, "commit", "-q", "-m", "main moved")
    git(half, "merge", "-q", "--no-edit", "main")  # what tools/land.py leaves when the landing stops
    assert worktrees.main(["status"], now=LATER) == 0
    line = {text.split()[0]: text for text in capsys.readouterr().out.splitlines()}
    assert " unmerged " in line["half"] and "tip is a merge of main" in line["half"]
    assert "tip is a merge of main" not in line["open"]
    assert worktrees.prune(main, apply=True, now=LATER) == 0  # unmerged stays unmerged: kept


@pytest.mark.parametrize("name, branch", [
    ("x", "wip/x"), ("x", "feat"), ("x", "feat/"), ("x", "feat/a..b"), ("../x", "feat/x"), ("x.", "feat/x"),
    ("taken", "feat/y"), ("y", "feat/taken")])
def test_new_rejects_bad_type_name_and_existing_path_or_branch(main, name, branch):
    add(main, "taken")
    assert worktrees.main(["new", name, branch]) == 1
    assert sorted(p.name for p in (main / ".worktrees").iterdir()) == ["taken"]
    assert refs(main, "refs/heads") == ["refs/heads/feat/taken", "refs/heads/main"]


def test_lint_note_is_silent_in_ci_and_without_worktrees_and_never_raises(main, monkeypatch):
    assert worktrees.lint_note(main, now=LATER) is None  # no .worktrees/
    add(main, "open", commit=True)
    assert worktrees.lint_note(main, now=LATER) is None  # below the cap, nothing merged
    monkeypatch.setattr(worktrees, "CAP", 1)
    assert "cap 1" in worktrees.lint_note(main)
    monkeypatch.setattr(worktrees, "CAP", 40)
    add(main, "done", commit=True, merge=True)
    assert worktrees.lint_note(main) is None  # merged but not idle yet
    note = worktrees.lint_note(main, now=LATER)
    assert worktrees.SWEEP in note and "python tools/worktrees.py status" in note and "--snapshot --" not in note
    monkeypatch.setenv("CI", "true")
    assert worktrees.lint_note(main, now=LATER) is None
    monkeypatch.delenv("CI")
    monkeypatch.setattr(worktrees, "scan", lambda repo: 1 / 0)
    assert worktrees.lint_note(main, now=LATER) is None


# --- tools/land.py hook ------------------------------------------------------------

@pytest.fixture
def landing(main, tmp_path, monkeypatch):
    done = add(main, "done", commit=True, merge=True)
    topic = add(main, "topic", commit=True)
    monkeypatch.chdir(topic)
    monkeypatch.setenv("ROSY_LAND_TMP", str(tmp_path / "logs"))
    monkeypatch.setattr(land.remote_pytest, "run", lambda invocations, logs, *a, **kw: [])  # --tests none
    clock = types.SimpleNamespace(time=lambda: LATER, strftime=time.strftime, localtime=time.localtime)
    monkeypatch.setattr(worktrees, "time", clock)
    return done, topic


def test_land_reports_finished_worktrees_and_removes_nothing(main, landing, capsys):
    done, topic = landing
    assert land.main(["--tests", "none"]) == 0
    assert done.is_dir() and topic.is_dir()
    assert git(main, "rev-parse", "main") == git(topic, "rev-parse", "HEAD")
    out = capsys.readouterr().out
    assert f"1 finished worktree(s) can be removed: {worktrees.SWEEP}" in out
    assert "this worktree is now removable" in out and "&&" not in out  # PowerShell 5.1 has no &&
    assert "\n  git worktree remove " in out and "\n  git branch -d feat/topic" in out


def test_land_prune_sweeps_finished_worktrees_but_not_the_one_landing(main, landing):
    done, topic = landing
    assert land.main(["--tests", "none", "--prune"]) == 0
    assert not done.exists() and topic.is_dir()


def test_land_no_prune_and_dry_run_say_nothing_about_worktrees(main, landing, capsys):
    done, _ = landing
    assert land.main(["--dry-run"]) == 0
    assert land.main(["--tests", "none", "--no-prune"]) == 0
    assert done.is_dir() and "can be removed" not in capsys.readouterr().out


def test_land_continues_when_the_prune_fails(main, landing, monkeypatch, capsys):
    done, topic = landing

    def broken(*args, **kwargs):
        raise OSError("disk went away")

    monkeypatch.setattr(worktrees, "sweep", broken)
    assert land.main(["--tests", "none"]) == 0
    assert "worktree prune failed" in capsys.readouterr().out
    assert done.is_dir() and git(main, "rev-parse", "main") == git(topic, "rev-parse", "HEAD")
