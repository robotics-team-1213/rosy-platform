"""tools/land_async.py: a landing runs from a hidden snapshot worktree, so the branch's worktree is free at once."""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("land_async", ROOT / "tools" / "land_async.py")
tool = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(tool)
NOW = datetime(2026, 10, 28, 4, 40, 0, tzinfo=timezone.utc)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    _git(main, "config", "user.email", "t@example.invalid")
    _git(main, "config", "user.name", "t")
    (main / "a.txt").write_text("1\n")
    _git(main, "add", "a.txt")
    _git(main, "commit", "-q", "-m", "base")
    dev = tmp_path / "dev"
    _git(main, "worktree", "add", "-q", "-b", "feat/x", str(dev))
    (dev / "a.txt").write_text("2\n")
    _git(dev, "commit", "-qam", "change")
    return main, dev


def test_start_snapshots_head_into_a_hidden_worktree_and_frees_the_branch(repo):
    main, dev = repo
    launched = []
    snap, log = tool.start(dev, ["--tests", "auto"], NOW, lambda argv, log: launched.append((argv, log)))
    assert snap == "land/feat/x-20261028044000"
    tree = log.parent / log.name.removesuffix(".log")
    assert tree.parent.name == tool.HOLDER and tree.parent.parent.name == ".git"  # not under .worktrees
    assert _git(tree, "rev-parse", "HEAD") == _git(dev, "rev-parse", "HEAD")
    assert _git(dev, "rev-parse", "--abbrev-ref", "HEAD") == "feat/x"  # the owner's worktree is untouched
    (argv, _), = launched
    assert argv[-4:] == [str(tree), snap, "--tests", "auto"] and "--supervise" in argv


@pytest.mark.parametrize("dirty", [True, False])
def test_uncommitted_changes_are_refused_never_carried(repo, dirty):
    _, dev = repo
    if dirty:
        (dev / "a.txt").write_text("3\n")
        with pytest.raises(SystemExit, match="uncommitted"):
            tool.start(dev, [], NOW, lambda *a: None)
    else:
        assert tool.start(dev, [], NOW, lambda *a: None)[0].startswith("land/feat/x-")


def test_main_and_snapshot_branches_are_refused(repo):
    main, _ = repo
    with pytest.raises(SystemExit, match="topic branch"):
        tool.start(main, [], NOW, lambda *a: None)


@pytest.mark.parametrize("lands", [True, False])
def test_supervise_cleans_up_only_a_landed_snapshot(repo, lands):
    main, dev = repo
    snap, log = tool.start(dev, [], NOW, lambda *a: None)
    tree = log.parent / log.name.removesuffix(".log")

    def fake_land(argv, cwd):
        if lands:
            _git(main, "merge", "-q", "--ff-only", snap)
        return 0 if lands else 1
    code = tool.supervise(tree, snap, [], run=fake_land)
    assert code == (0 if lands else 1)
    assert tree.exists() is not lands
    assert bool(_git(main, "branch", "--list", snap)) is not lands
    assert (tree.parent / (tree.name + ".stopped")).exists() is not lands
