"""tools/worktrees.py and tools/worktree_rules.py against throwaway git repos: a main checkout and worktrees under .worktrees/."""

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
    monkeypatch.setattr(worktrees.rules, "scratch", lambda: None)  # no orphan archive unless a test gives one
    return main


ME = "t <t@t>"  # the fixture's git identity; no agent session in the environment
PEER = "p <p@p>"  # another session's worktree: only the 72 h rule applies to it


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


def test_hook_state_under_omc_state_is_a_cache(main):
    wt = add(main, "hooks", commit=True, merge=True)
    (wt / ".omc" / "state" / "sessions" / "s1").mkdir(parents=True)
    (wt / ".omc" / "state" / "sessions" / "s1" / "throttle.json").write_text("{}", encoding="utf-8")
    assert worktrees.prune(main, apply=True, now=LATER) == 1
    assert not wt.exists()


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
    wt = add(main, "fresh", owner=PEER)  # merged-looking, but no commit of its own landed: the 72 h rule
    landed = add(main, "landed", commit=True, merge=True, owner=PEER)
    now = time.time()
    assert worktrees.prune(main, apply=True, snapshot=True, now=now) == 0
    assert worktrees.prune(main, apply=True, snapshot=True, now=now + 0.9 * HOUR) == 0
    assert landed.is_dir()
    assert worktrees.prune(main, apply=True, now=now + 1.1 * HOUR) == 1  # D-790: landed and clean, anyone's, 1 h
    assert not landed.exists() and wt.is_dir()
    assert worktrees.prune(main, apply=True, snapshot=True, now=now + 71 * HOUR) == 0
    assert wt.is_dir()


def test_idle_counts_uncommitted_files_and_the_given_threshold(main):
    wt = add(main, "fresh", owner=PEER)
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
    stuck = [line for line in capsys.readouterr().out.splitlines() if line.startswith("stuck ")][0]
    assert " orphan  [" in stuck and "files" in stuck and "to archive]" in stuck
    monkeypatch.setattr(worktrees, "CAP", 1)  # the orphan counts toward the cap
    assert worktrees.main(["new", "more", "feat/more"]) == 1
    assert worktrees.prune(main, apply=True, snapshot=True, everyone=True, now=LATER) == 0  # files, no archive folder
    assert (wt / "a.txt").is_file()
    shutil.rmtree(wt)
    wt.mkdir()
    assert worktrees.prune(main, apply=True, now=LATER) == 1  # an empty orphan: anyone may remove it
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
    add(main, "done", commit=True, merge=True, owner=PEER)
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


def test_default_cap_is_the_fifteen_slot_budget_counts_orphans_and_preserves_explicit_exception(main, capsys):
    assert worktrees.CAP == 14  # D-886: 14 under .worktrees/ plus main
    for index in range(13):
        (main / ".worktrees" / f"orphan-{index}").mkdir(parents=True)

    assert worktrees.main(["new", "fourteenth", "docs/fourteenth", "--no-prune"]) == 0
    capsys.readouterr()
    assert worktrees.main(["new", "overflow", "docs/overflow", "--no-prune"]) == 1
    assert "the cap is 14" in capsys.readouterr().err
    assert not (main / ".worktrees" / "overflow").exists()
    assert "refs/heads/docs/overflow" not in refs(main, "refs/heads")
    assert len(list((main / ".worktrees").iterdir())) == 14

    assert worktrees.main(["new", "overflow", "docs/overflow", "--no-prune",
                           "--force-over-cap", "user-approved ADR exception"]) == 0
    description = git(main, "config", "branch.docs/overflow.description")
    assert "over cap (14 >= 14): user-approved ADR exception" in description
    assert all((main / ".worktrees" / f"orphan-{index}").is_dir() for index in range(13))


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


def test_lossless_prune_takes_any_owners_finished_worktree(main, capsys):
    peer = add(main, "peer", commit=True, merge=True, owner="t <t@t>; session other")
    bare = add(main, "bare", commit=True, merge=True, owner=None)  # a bare `git worktree add`
    assert worktrees.main(["status"], now=LATER) == 0
    line = {text.split()[0]: text for text in capsys.readouterr().out.splitlines()}
    assert "yes   removable" in line["peer"] and "[t <t@t>; session other]" in line["peer"]
    assert "yes   removable" in line["bare"]
    assert worktrees.main(["prune", "--apply"], now=LATER) == 0  # nothing left to lose, idle three days
    assert not peer.exists() and not bare.exists()
    assert refs(main, "refs/heads/feat") == []


def test_snapshot_takes_only_the_callers_worktrees_unless_all(main, capsys):
    mine = add(main, "mine", commit=True)
    peer = add(main, "peer", commit=True, owner="t <t@t>; session other")
    bare = add(main, "bare", owner=None)  # a bare `git worktree add`, with uncommitted work
    (bare / "wip.txt").write_text("wip", encoding="utf-8")
    assert worktrees.main(["status"], now=LATER) == 0
    line = {text.split()[0]: text for text in capsys.readouterr().out.splitlines()}
    assert "yes   needs snapshot" in line["mine"]
    assert "--all needs snapshot" in line["peer"] and "--all needs snapshot" in line["bare"]
    assert worktrees.main(["prune", "--snapshot", "--apply"], now=LATER) == 0
    out = capsys.readouterr().out
    assert "owner unknown: only with --all" in out and "owner t <t@t>; session other: only with --all" in out
    assert not mine.exists() and peer.is_dir() and (bare / "wip.txt").is_file()
    assert refs(main, "refs/wip") == []
    assert worktrees.main(["prune", "--snapshot", "--apply", "--all"], now=LATER) == 0
    assert not peer.exists() and not bare.exists()
    assert git(main, "show", f"refs/wip/{DAY}/bare:wip.txt") == "wip"


def test_cap_refusal_counts_removable_worktrees_per_owner(main, monkeypatch, capsys):
    monkeypatch.setattr(worktrees, "CAP", 3)
    add(main, "mine", commit=True, merge=True)
    add(main, "bare", commit=True, merge=True, owner=None)
    add(main, "open", commit=True, owner=None)  # unmerged: not removable, not counted
    assert worktrees.main(["new", "x", "feat/x", "--no-prune"], now=LATER) == 1
    err = capsys.readouterr().err
    assert "removable now by anyone: bare (removable; owner unknown)" in err
    assert "removable now by anyone: mine (removable; owner t <t@t>)" in err
    assert f"you may remove all 2: {worktrees.SWEEP}" in err
    assert "removable by its owner (unknown) through prune --snapshot" in err and "open (needs snapshot)" in err


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
    ("x", "feat/Upper"), ("x", "feat/snake_case"), ("x", "feat/a/b"), ("x", "feat/-x"), ("x", "feat/" + "a" * 49),
    ("taken", "feat/y"), ("y", "feat/taken")])
def test_new_rejects_bad_type_name_and_existing_path_or_branch(main, name, branch):
    add(main, "taken")
    assert worktrees.main(["new", name, branch]) == 1
    assert sorted(p.name for p in (main / ".worktrees").iterdir()) == ["taken"]
    assert refs(main, "refs/heads") == ["refs/heads/feat/taken", "refs/heads/main"]


def test_prune_deletes_merged_branches_no_worktree_uses_and_keeps_the_rest(main, capsys):
    landed = main / "landed.txt"
    git(main, "branch", "fix/landed")
    git(main, "branch", "archive/kept")
    git(main, "config", "branch.fix/landed.description", "owner: p <p@p>")
    wt = add(main, "open")  # checked out (locked, so the worktree stays): kept even though it is in main
    git(main, "worktree", "lock", str(wt))
    git(main, "branch", "feat/ahead", "main")
    landed.write_text("x", encoding="utf-8")
    git(main, "add", "landed.txt")
    git(main, "commit", "-q", "-m", "landed")
    git(main, "switch", "-q", "feat/ahead")
    (main / "ahead.txt").write_text("y", encoding="utf-8")
    git(main, "add", "ahead.txt")
    git(main, "commit", "-q", "-m", "ahead")
    git(main, "switch", "-q", "main")

    assert worktrees.prune(main, now=time.time()) == 0  # created just now: inside the 1 h wait
    assert "would delete 0 merged branch(es)" in capsys.readouterr().out
    for reflog in (main / ".git" / "logs" / "refs" / "heads").rglob("*"):
        os.utime(reflog, (LATER, LATER))  # gc / reflog expire rewrote every file; their entries are old
    worktrees.prune(main, now=LATER)
    assert "would delete 1 merged branch(es)" in capsys.readouterr().out  # dry run touches nothing
    assert "refs/heads/fix/landed" in refs(main, "refs/heads")

    worktrees.prune(main, apply=True, now=LATER)
    assert "deleted 1 merged branch(es)" in capsys.readouterr().out
    assert refs(main, "refs/heads") == ["refs/heads/archive/kept", "refs/heads/feat/ahead", "refs/heads/feat/open",
                                        "refs/heads/main"]
    assert "fix/landed" not in git(main, "config", "--list")
    assert wt.is_dir()


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
    assert f"\n  {worktrees.SWEEP}" in out and "git worktree remove" not in out  # one command, not two


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


# --- owner fast path and non-worktree entries under .worktrees/ ---------------------

def test_owner_fast_path_takes_only_the_callers_landed_clean_worktree(main, capsys):
    now = time.time()  # everything was made seconds ago
    mine = add(main, "mine", commit=True, merge=True)
    peer = add(main, "peer", commit=True, merge=True, owner=PEER)
    empty = add(main, "empty")  # never committed: its tip is main's, so "merged" without any work landed
    other = add(main, "sess", commit=True, merge=True, owner=f"{ME}; session other")
    blind = add(main, "blind", commit=True, merge=True)
    (main / ".git" / "logs" / "refs" / "heads" / "feat" / "blind").unlink()  # no reflog: no evidence
    assert worktrees.main(["status"], now=now) == 0
    line = {text.split()[0]: text for text in capsys.readouterr().out.splitlines()}
    assert "yes   removable" in line["mine"]
    assert all("-     active" in line[name] for name in ("peer", "empty", "sess", "blind"))
    assert worktrees.prune(main, now=now) == 1  # dry run
    assert mine.is_dir()
    assert worktrees.prune(main, apply=True, now=now) == 1
    assert not mine.exists() and "refs/heads/feat/mine" not in refs(main, "refs/heads/feat")
    assert all(wt.is_dir() for wt in (peer, empty, other, blind))
    assert worktrees.prune(main, apply=True, now=now + 0.5 * HOUR) == 0
    assert worktrees.prune(main, apply=True, now=now + 2 * HOUR) == 2  # D-790: anyone's landed one after 1 h
    assert not peer.exists() and not other.exists() and empty.is_dir() and blind.is_dir()
    assert worktrees.prune(main, apply=True, now=now + 71 * HOUR) == 0
    assert worktrees.prune(main, apply=True, now=now + 73 * HOUR) == 2  # no landing evidence: the 72 h rule
    assert not any(wt.exists() for wt in (peer, empty, other, blind))


def test_owner_fast_path_waits_for_a_dirty_worktree_and_the_current_one(main, monkeypatch):
    now = time.time()
    dirty = add(main, "dirty", commit=True, merge=True)
    (dirty / "note.txt").write_text("wip", encoding="utf-8")
    here = add(main, "here", commit=True, merge=True)
    monkeypatch.chdir(here)
    assert worktrees.main(["prune", "--snapshot", "--apply"], now=now) == 0
    assert dirty.is_dir() and here.is_dir()


def test_dot_directories_and_plain_files_under_worktrees_are_not_worktrees(main, monkeypatch, capsys):
    monkeypatch.setattr(worktrees, "CAP", 2)
    holder = main / ".worktrees"
    wt = add(main, "a", commit=True)
    (holder / ".omc").mkdir()
    (holder / ".omc" / "state.json").write_text("{}", encoding="utf-8")
    (holder / ".empty").mkdir()
    (holder / "README.md").write_text("stray", encoding="utf-8")
    assert len(worktrees.scan(main)[1]) == 1  # the cap counts worktrees only
    assert worktrees.main(["status"], now=LATER) == 0
    out = capsys.readouterr().out
    assert ".omc" not in out and ".empty" not in out and "README" not in out and "1 under" in out
    assert worktrees.main(["new", "b", "fix/b"]) == 0  # 1 < cap 2: the junk is not counted
    assert worktrees.prune(main, apply=True, snapshot=True, everyone=True, now=LATER + 100 * HOUR) >= 1
    assert (holder / ".omc" / "state.json").is_file() and (holder / ".empty").is_dir()
    assert (holder / "README.md").is_file() and not wt.exists()


# --- D-790: landed-dirty, orphans, stale history, owner ------------------------------

def test_landed_worktree_with_uncommitted_files_is_flagged_and_kept(main, capsys):
    late = add(main, "late", commit=True, merge=True, owner=PEER)
    (late / "more.txt").write_text("work after landing", encoding="utf-8")
    fresh = add(main, "fresh")  # no commit yet: uncommitted work in a new worktree is not "landed"
    (fresh / "wip.txt").write_text("wip", encoding="utf-8")
    assert worktrees.main(["status"], now=LATER) == 0
    out = capsys.readouterr().out
    line = {text.split()[0]: text for text in out.splitlines()}
    assert line["late"].rstrip().endswith("landed-dirty  [p <p@p>]") and "landed-dirty" not in line["fresh"]
    assert "WARN    late: feat/late is already in main and 1 file(s) are uncommitted here (owner p <p@p>)" in out
    assert "start a new one" in out and "WARN    fresh" not in out
    assert worktrees.prune(main, apply=True, now=LATER) == 0  # lossless never takes it
    assert worktrees.prune(main, apply=True, snapshot=True, everyone=True, now=LATER) == 2  # kept under refs/wip
    assert git(main, "show", f"refs/wip/{DAY}/late:more.txt") == "work after landing"


def _orphans(main: Path) -> dict[str, Path]:
    holder = main / ".worktrees"
    found = {name: holder / name for name in ("empty", "state", "files")}
    for path in found.values():
        path.mkdir(parents=True)
    (found["empty"] / "sub").mkdir()
    for rel in (".omc/state/session.json", "pkg/__pycache__/m.pyc"):
        (found["state"] / rel).parent.mkdir(parents=True)
        (found["state"] / rel).write_text("{}", encoding="utf-8")
    for rel, text in (("notes/plan.md", "plan"), (".omc/handoff.md", "handoff"), ("__pycache__/x.pyc", "c")):
        (found["files"] / rel).parent.mkdir(parents=True, exist_ok=True)
        (found["files"] / rel).write_text(text, encoding="utf-8")
    return found


def test_orphans_are_summed_up_and_removed_or_archived_first(main, tmp_path, monkeypatch, capsys):
    import zipfile
    found = _orphans(main)
    assert worktrees.main(["status"], now=LATER) == 0
    line = {text.split()[0]: text for text in capsys.readouterr().out.splitlines()}
    assert "[empty]" in line["empty"] and "[only caches and .omc/state (2 files)]" in line["state"]
    assert "[2 files" in line["files"] and "to archive]" in line["files"] and "-     orphan" in line["files"]
    assert worktrees.prune(main, apply=True, now=time.time()) == 0  # touched seconds ago: not idle 1 h
    assert worktrees.prune(main, apply=True, now=LATER) == 2  # no archive folder: the one with files stays
    assert not found["empty"].exists() and not found["state"].exists() and found["files"].is_dir()
    monkeypatch.setattr(worktrees.rules, "scratch", lambda: tmp_path / "scratch" / "worktree-orphans")
    assert worktrees.main(["prune", "--apply"], now=LATER) == 0
    out = capsys.readouterr().out
    archive = tmp_path / "scratch" / "worktree-orphans" / f"files-{DAY}.zip"
    assert f"archived to {archive}" in out and not found["files"].exists()
    with zipfile.ZipFile(archive) as kept:
        assert sorted(kept.namelist()) == [".omc/handoff.md", "notes/plan.md"]  # caches are not kept
        assert kept.read("notes/plan.md") == b"plan"


def test_orphan_archive_that_does_not_verify_keeps_the_directory(main, tmp_path, monkeypatch, capsys):
    found = _orphans(main)
    monkeypatch.setattr(worktrees.rules, "scratch", lambda: tmp_path / "orphans")
    monkeypatch.setattr(worktrees.rules.zipfile.ZipFile, "testzip", lambda self: "notes/plan.md")
    assert worktrees.main(["prune", "--apply"], now=LATER) == 0
    out = capsys.readouterr().out
    assert "FAIL    files [orphan]" in out and "did not verify" in out
    assert (found["files"] / "notes" / "plan.md").read_text(encoding="utf-8") == "plan"


def test_orphan_archive_folder_comes_from_rosy_scratch(monkeypatch):
    monkeypatch.setenv("ROSY_SCRATCH", "/scratch/here")
    assert worktrees.rules.scratch() == Path("/scratch/here") / "worktree-orphans"


def _old_line(main: Path, monkeypatch) -> str:
    """A branch the D-790 rules read as pre-rewrite history: forked at or before REWRITE_TIME."""
    wt = add(main, "old", commit=True)
    monkeypatch.setattr(worktrees.rules, "REWRITE_TIME", int(time.time()) + HOUR)
    return git(wt, "rev-parse", "HEAD")


def test_stale_history_is_flagged_never_pruned_and_never_a_base(main, monkeypatch, capsys):
    _old_line(main, monkeypatch)
    assert worktrees.main(["status"], now=LATER) == 0
    out = capsys.readouterr().out
    assert "stale-history" in out and "before the history rewrite" in out and "WARN    old: feat/old" in out
    assert worktrees.prune(main, apply=True, snapshot=True, everyone=True, now=LATER) == 0
    assert worktrees.main(["new", "again", "fix/again", "--from", "feat/old"]) == 1
    assert "refused: --from feat/old" in capsys.readouterr().err
    assert not (main / ".worktrees" / "again").exists()
    monkeypatch.setattr(worktrees.rules, "REWRITE_TIME", 0)
    monkeypatch.setattr(worktrees.rules, "STALE_COMMITS", 0)  # one commit not in main is "too many" now
    assert "more than 0 commits not in main" in worktrees.rules.stale_history(main, "feat/old")
    monkeypatch.setattr(worktrees.rules, "STALE_COMMITS", 2000)
    assert worktrees.rules.stale_history(main, "feat/old") is None
    assert worktrees.main(["new", "again", "fix/again", "--from", "feat/old"]) == 0
    assert (main / ".worktrees" / "again" / "old.txt").is_file()


def test_new_records_the_owner_override_and_status_names_unknown_owners(main, capsys):
    assert worktrees.main(["new", "mine", "feat/mine", "--owner", "dispatcher lane 3"]) == 0
    assert git(main, "config", "branch.feat/mine.description") == "owner: dispatcher lane 3"
    assert worktrees.main(["new", "blank", "feat/blank", "--owner", " "]) == 1
    add(main, "bare", owner=None)
    add(main, "noname", owner=" <>")  # made while git had no user.name / user.email
    assert worktrees.main(["new", "x", "feat/x", "--from", "no-such-ref"]) == 1
    capsys.readouterr()
    assert worktrees.main(["status"]) == 0
    line = {text.split()[0]: text for text in capsys.readouterr().out.splitlines()}
    assert line["mine"].endswith("[dispatcher lane 3]")
    assert line["bare"].endswith("[unknown]") and line["noname"].endswith("[unknown]")


def _git_fails_inside(folder: Path, main: Path) -> None:
    """A real git in the tombstoned folder stops there: no fall-through to the parent repository."""
    run = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=folder, capture_output=True, text=True)
    assert run.returncode == 128 and str(main) not in run.stdout, (run.stdout, run.stderr)


def _held(monkeypatch, wt: Path) -> None:
    """What a process with ``wt`` as its cwd does on Windows: the folder itself cannot be deleted."""
    real = Path.rmdir

    def rmdir(self):
        if self == wt:
            raise PermissionError(32, "The process cannot access the file", str(self))
        real(self)

    monkeypatch.setattr(Path, "rmdir", rmdir)
    monkeypatch.setattr(worktrees.rules.shutil, "rmtree",
                        lambda path, **kw: (_ for _ in ()).throw(PermissionError(32, "in use", str(path))))


def test_held_folder_after_removal_gets_a_tombstone_and_the_next_prune_deletes_it(main, monkeypatch, capsys):
    wt = add(main, "held", commit=True, merge=True)

    def half_remove(real, cwd, args):
        if args[:2] != ("worktree", "remove"):
            return None
        for item in wt.iterdir():  # git deleted the files; the open handle keeps the empty folder
            shutil.rmtree(item) if item.is_dir() else item.unlink()
        real(cwd, "worktree", "prune")
        return subprocess.CompletedProcess(args, 1, "", "error: failed to delete: Permission denied")

    wrap_git(monkeypatch, half_remove)
    with monkeypatch.context() as held:
        _held(held, wt)
        assert worktrees.main(["prune", "--apply"], now=LATER) == 0
    out = capsys.readouterr().out
    assert "ORPHAN  " in out and "tombstone" in out and "FAIL    held" in out
    assert [p.name for p in wt.iterdir()] == [".git"] and worktrees.rules.is_tombstone(wt)
    _git_fails_inside(wt, main)
    assert str(wt) not in git(main, "worktree", "list", "--porcelain")
    root, rows = worktrees.scan(main)
    assert [(r["name"], r["orphan"]) for r in rows] == [("held", True)]  # never a live worktree
    assert worktrees.main(["status"], now=LATER) == 0
    assert "only caches" in [line for line in capsys.readouterr().out.splitlines() if line.startswith("held ")][0]
    assert worktrees.prune(main, apply=True, now=time.time()) == 1  # nothing to lose: no idle wait
    assert not wt.exists()


def test_empty_leftover_folder_is_removed_not_tombstoned(main, monkeypatch, capsys):
    wt = add(main, "gone", commit=True, merge=True)

    def half_remove(real, cwd, args):
        if args[:2] != ("worktree", "remove"):
            return None
        for item in wt.iterdir():
            shutil.rmtree(item) if item.is_dir() else item.unlink()
        real(cwd, "worktree", "prune")
        return subprocess.CompletedProcess(args, 1, "", "error: failed to delete: Permission denied")

    wrap_git(monkeypatch, half_remove)
    assert worktrees.main(["prune", "--apply"], now=LATER) == 0
    assert "empty folder removed" in capsys.readouterr().out and not wt.exists()


def test_orphan_that_cannot_be_cleared_gets_a_tombstone(main, monkeypatch, capsys):
    orphan = main / ".worktrees" / "stuck" / "__pycache__"
    orphan.mkdir(parents=True)
    (orphan / "m.pyc").write_text("c", encoding="utf-8")
    with monkeypatch.context() as held:
        _held(held, orphan.parent)
        assert worktrees.main(["prune", "--apply"], now=LATER) == 0
    assert "FAIL    stuck [orphan]" in capsys.readouterr().out
    _git_fails_inside(orphan.parent, main)
    assert worktrees.prune(main, apply=True, now=LATER) == 1 and not orphan.parent.exists()


def test_new_clears_a_tombstone_folder_or_refuses_while_it_is_held(main, monkeypatch, capsys):
    folder = main / ".worktrees" / "again"
    folder.mkdir(parents=True)
    with monkeypatch.context() as held:
        _held(held, folder)
        assert "tombstone" in worktrees.rules.leave_tombstone(folder)
        assert worktrees.main(["new", "again", "feat/again"]) == 1
        assert "could not be cleared" in capsys.readouterr().err
    assert worktrees.main(["new", "again", "feat/again"]) == 0
    assert git(folder, "rev-parse", "--abbrev-ref", "HEAD") == "feat/again"
