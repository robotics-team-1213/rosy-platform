"""tools/worktrees.py against throwaway git repos: a main checkout and worktrees under .worktrees/."""

from __future__ import annotations

import os
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
LATER = time.time() + 13 * HOUR  # past the 12 h default: every worktree made in a test is idle by then
DAY = time.strftime("%Y-%m-%d", time.localtime(LATER))


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def refs(main: Path, pattern: str) -> list[str]:
    return git(main, "for-each-ref", "--format=%(refname:short)", pattern).split()


@pytest.fixture
def main(tmp_path, monkeypatch):
    main = tmp_path / "main"
    main.mkdir()
    git(main, "init", "-q", "-b", "main")
    for key, value in (("user.name", "t"), ("user.email", "t@t"), ("core.autocrlf", "false")):
        git(main, "config", key, value)
    (main / ".gitignore").write_text(".worktrees/\nbuild/\nsecret.env\n", encoding="utf-8")
    (main / "a.txt").write_text("base\n", encoding="utf-8")
    git(main, "add", ".gitignore", "a.txt")
    git(main, "commit", "-q", "-m", "init")
    monkeypatch.chdir(main)
    monkeypatch.delenv("CI", raising=False)
    return main


def add(main: Path, name: str, commit: bool = False, merge: bool = False) -> Path:
    """A worktree on feat/<name>; optionally with one commit, optionally landed on main."""
    wt = main / ".worktrees" / name
    git(main, "worktree", "add", "-q", str(wt), "-b", f"feat/{name}", "main")
    if commit:
        (wt / f"{name}.txt").write_text(name, encoding="utf-8")
        git(wt, "add", f"{name}.txt")
        git(wt, "commit", "-q", "-m", name)
    if merge:
        git(main, "merge", "-q", "--ff-only", f"feat/{name}")
    return wt


def test_clean_merged_worktree_is_pruned_with_its_branch(main):
    wt = add(main, "done", commit=True, merge=True)
    assert worktrees.prune(main, now=LATER) == 1  # dry run: counted, nothing touched
    assert wt.is_dir() and refs(main, "refs/heads/feat") == ["feat/done"]
    assert worktrees.prune(main, apply=True, now=LATER) == 1
    assert not wt.exists()
    assert refs(main, "refs/heads/feat") == []
    assert (main / "done.txt").read_text(encoding="utf-8") == "done"


def test_clean_unmerged_worktree_needs_snapshot_and_keeps_its_branch(main):
    wt = add(main, "open", commit=True)
    tip = git(wt, "rev-parse", "HEAD")
    assert worktrees.prune(main, apply=True, now=LATER) == 0
    assert wt.is_dir()
    assert worktrees.prune(main, apply=True, snapshot=True, now=LATER) == 1
    assert not wt.exists()
    assert git(main, "rev-parse", "feat/open") == tip
    assert refs(main, "refs/tags") == []  # nothing uncommitted, so nothing to tag


def _dirty(wt: Path) -> None:
    (wt / "a.txt").write_text("modified\n", encoding="utf-8")
    (wt / "staged.txt").write_text("staged\n", encoding="utf-8")
    git(wt, "add", "staged.txt")
    (wt / "notes").mkdir()
    (wt / "notes" / "untracked.txt").write_text("untracked\n", encoding="utf-8")


def test_dirty_worktree_is_kept_without_snapshot_and_tagged_with_it(main):
    wt = add(main, "dirty")
    head = git(wt, "rev-parse", "HEAD")
    _dirty(wt)
    assert worktrees.prune(main, apply=True, now=LATER) == 0
    assert wt.is_dir() and refs(main, "refs/tags") == []

    assert worktrees.prune(main, apply=True, snapshot=True, now=LATER) == 1
    tag = f"archive/{DAY}/wip/dirty"
    assert refs(main, "refs/tags") == [tag]
    assert git(main, "show", f"{tag}:a.txt") == "modified"
    assert git(main, "show", f"{tag}:staged.txt") == "staged"
    assert git(main, "show", f"{tag}:notes/untracked.txt") == "untracked"
    assert git(main, "rev-parse", f"{tag}^") == head
    assert not wt.exists()
    assert (main / "a.txt").read_text(encoding="utf-8") == "base\n"


def test_snapshot_tag_collision_gets_a_suffix(main):
    git(main, "tag", f"archive/{DAY}/wip/dirty")
    _dirty(add(main, "dirty"))
    assert worktrees.prune(main, apply=True, snapshot=True, now=LATER) == 1
    assert git(main, "show", f"archive/{DAY}/wip/dirty-2:notes/untracked.txt") == "untracked"
    assert git(main, "rev-parse", f"archive/{DAY}/wip/dirty") == git(main, "rev-parse", "main")


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


def test_locked_worktree_is_never_removed(main):
    wt = add(main, "held", commit=True, merge=True)
    git(main, "worktree", "lock", str(wt))
    assert worktrees.prune(main, apply=True, snapshot=True, now=LATER) == 0
    assert wt.is_dir() and refs(main, "refs/heads/feat") == ["feat/held"]


def test_idle_threshold_is_respected(main):
    wt = add(main, "fresh", commit=True, merge=True)
    now = time.time()
    assert worktrees.prune(main, apply=True, snapshot=True, now=now) == 0
    assert worktrees.prune(main, apply=True, snapshot=True, now=now + 11 * HOUR) == 0
    assert worktrees.prune(main, apply=True, now=now + 30 * HOUR, idle_hours=48) == 0
    assert wt.is_dir()
    # An uncommitted file written an hour before the clock keeps the worktree active.
    note = wt / "note.txt"
    note.write_text("wip", encoding="utf-8")
    os.utime(note, (LATER - HOUR, LATER - HOUR))
    assert worktrees.prune(main, apply=True, snapshot=True, now=LATER) == 0
    assert note.is_file()
    note.unlink()
    assert worktrees.prune(main, apply=True, now=now + 13 * HOUR) == 1
    assert not wt.exists()


def test_the_worktree_the_tool_runs_in_is_never_removed(main, monkeypatch):
    mine = add(main, "mine", commit=True, merge=True)
    other = add(main, "other")
    monkeypatch.chdir(mine)
    assert worktrees.main(["prune", "--snapshot", "--apply"], now=LATER) == 0
    assert mine.is_dir() and not other.exists()
    assert refs(main, "refs/heads/feat") == ["feat/mine"]


def test_status_names_a_verdict_per_worktree(main, capsys):
    add(main, "done", commit=True, merge=True)
    add(main, "open", commit=True)
    git(main, "worktree", "lock", str(add(main, "held")))
    assert worktrees.main(["status"], now=LATER) == 0
    verdict = {line.split()[0]: line for line in capsys.readouterr().out.splitlines()}
    assert verdict["done"].endswith("removable")
    assert verdict["open"].endswith("needs snapshot")
    assert verdict["held"].endswith("locked")
    assert worktrees.main(["status"]) == 0
    assert all(line.endswith("active") for line in capsys.readouterr().out.splitlines()
               if line.split()[0] in ("done", "open"))


def test_new_creates_below_the_cap_and_refuses_at_it(main, monkeypatch, capsys):
    monkeypatch.setattr(worktrees, "CAP", 2)
    assert worktrees.main(["new", "one", "fix/one"]) == 0
    assert Path(capsys.readouterr().out.strip()).resolve() == (main / ".worktrees" / "one").resolve()
    assert worktrees.main(["new", "two", "docs/two"]) == 0
    assert refs(main, "refs/heads") == ["docs/two", "fix/one", "main"]

    assert worktrees.main(["new", "three", "feat/three"]) == 1
    err = capsys.readouterr().err
    assert "the cap is 2" in err and worktrees.CLEAR in err and "one" in err
    assert not (main / ".worktrees" / "three").exists() and "feat/three" not in refs(main, "refs/heads")

    assert worktrees.main(["new", "three", "feat/three", "--force-over-cap", "incident 42"]) == 0
    assert "incident 42" in capsys.readouterr().out
    assert (main / ".worktrees" / "three" / "a.txt").is_file()
    assert git(main / ".worktrees" / "three", "rev-parse", "--abbrev-ref", "HEAD") == "feat/three"


def test_new_sweeps_finished_worktrees_before_counting(main, monkeypatch):
    monkeypatch.setattr(worktrees, "CAP", 2)
    add(main, "done", commit=True, merge=True)
    kept = add(main, "open", commit=True)
    assert worktrees.main(["new", "next", "refactor/next"], now=LATER) == 0
    assert not (main / ".worktrees" / "done").exists()
    assert kept.is_dir()  # unmerged: `new` never snapshots


@pytest.mark.parametrize("name, branch", [
    ("x", "wip/x"), ("x", "feat"), ("x", "feat/"), ("../x", "feat/x"), ("taken", "feat/y"), ("y", "feat/taken")])
def test_new_rejects_bad_type_name_and_existing_path_or_branch(main, name, branch):
    add(main, "taken")
    assert worktrees.main(["new", name, branch]) == 1
    assert sorted(p.name for p in (main / ".worktrees").iterdir()) == ["taken"]
    assert refs(main, "refs/heads") == ["feat/taken", "main"]


def test_lint_note_is_silent_in_ci_and_without_worktrees_and_names_the_command(main, monkeypatch):
    assert worktrees.lint_note(main, now=LATER) is None  # no .worktrees/
    add(main, "open", commit=True)
    assert worktrees.lint_note(main, now=LATER) is None  # below the cap, nothing merged
    monkeypatch.setattr(worktrees, "CAP", 1)
    assert "cap 1" in worktrees.lint_note(main)
    monkeypatch.setattr(worktrees, "CAP", 40)
    add(main, "done", commit=True, merge=True)
    assert worktrees.lint_note(main) is None  # merged but not idle yet
    assert "python tools/worktrees.py prune --apply" in worktrees.lint_note(main, now=LATER)
    monkeypatch.setenv("CI", "true")
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


def test_land_sweeps_finished_worktrees_but_not_the_one_landing(main, landing, capsys):
    done, topic = landing
    assert land.main(["--tests", "none"]) == 0
    assert not done.exists() and topic.is_dir()
    assert git(main, "rev-parse", "main") == git(topic, "rev-parse", "HEAD")
    assert "this worktree is now removable" in capsys.readouterr().out


def test_land_no_prune_and_dry_run_leave_worktrees_alone(main, landing):
    done, _ = landing
    assert land.main(["--dry-run"]) == 0
    assert done.is_dir()
    assert land.main(["--tests", "none", "--no-prune"]) == 0
    assert done.is_dir()


def test_land_continues_when_the_prune_fails(main, landing, monkeypatch, capsys):
    done, topic = landing

    def broken(*args, **kwargs):
        raise OSError("disk went away")

    monkeypatch.setattr(worktrees, "prune", broken)
    assert land.main(["--tests", "none"]) == 0
    assert "worktree prune failed" in capsys.readouterr().out
    assert done.is_dir() and git(main, "rev-parse", "main") == git(topic, "rev-parse", "HEAD")
