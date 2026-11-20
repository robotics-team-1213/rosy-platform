import json
import subprocess
from pathlib import Path

import pytest

from tools import cutover_watch as cw


def g(cwd, *a):
    return subprocess.run(["git", "-C", str(cwd), *a], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    work = tmp_path / "work"
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True, capture_output=True)
    g(work, "config", "user.email", "a@b.c")
    g(work, "config", "user.name", "t")
    (work / "f").write_text("1")
    g(work, "add", "f")
    g(work, "commit", "-qm", "one")
    g(work, "push", "-q", "origin", "HEAD:main")
    return work


def cfg(work, **kw):
    d = {"phase": "drain", "owner": "robot-d4", "allow": []}
    d.update(kw)
    (Path(g(work, "rev-parse", "--absolute-git-dir")) / "rosy-cutover.json").write_text(json.dumps(d))


def tree(work, name, sha, stopped=False):
    holder = Path(g(work, "rev-parse", "--absolute-git-dir")) / "rosy-land-wt"
    g(work, "worktree", "add", "-q", "--detach", str(holder / name), sha)
    if stopped:
        (holder / (name + ".stopped")).write_text("x")


def test_no_file_is_phase_none(repo):
    assert cw.collect(repo)["phase"] == "none"


def test_bad_file_is_invalid(repo):
    (Path(g(repo, "rev-parse", "--absolute-git-dir")) / "rosy-cutover.json").write_text("{")
    assert cw.collect(repo)["phase"] == "invalid"


def test_ancestor_and_trees(repo):
    head = g(repo, "rev-parse", "HEAD")
    g(repo, "checkout", "-q", "-b", "work")  # off main: landed commits are excluded by ancestry
    (repo / "f").write_text("2")
    g(repo, "commit", "-qam", "two")  # local only, not on origin/main
    local = g(repo, "rev-parse", "HEAD")
    cfg(repo, allow=[head, local])
    tree(repo, "live-ok", head)
    tree(repo, "live-out", local[:0] + g(repo, "rev-parse", "HEAD~0"))  # allowed sha too
    g(repo, "commit", "-q", "--allow-empty", "-m", "three")
    other = g(repo, "rev-parse", "HEAD")
    tree(repo, "live-bad", other)
    tree(repo, "dead-bad", other, stopped=True)
    s = cw.collect(repo)
    assert s["not_in_main"] == [local]
    assert s["outside_allow"] == ["live-bad"]


def test_record_dedupes(tmp_path):
    st = {"phase": "drain", "owner": "o", "allow": [], "not_in_main": [], "outside_allow": [], "unknown": [], "error": ""}
    status, board = tmp_path / "s" / "status.json", tmp_path / "b" / "board.md"
    assert cw.record(st, status, board, now="t1") is True
    assert cw.record(st, status, board, now="t2") is False
    assert len(board.read_text().splitlines()) == 1
    assert cw.record({**st, "outside_allow": ["x"]}, status, board, now="t3") is True
    assert len(board.read_text().splitlines()) == 2
    assert json.loads(status.read_text())["checked"] == "t3"


def test_landed_tree_after_branch_deleted_not_outside(repo):
    g(repo, "checkout", "-q", "-b", "feat")
    (repo / "f").write_text("2")
    g(repo, "commit", "-qam", "feat")
    sha = g(repo, "rev-parse", "HEAD")
    g(repo, "push", "-q", "origin", "HEAD:main")  # landed upstream, not in allow
    g(repo, "checkout", "-q", "main")
    g(repo, "branch", "-q", "-D", "feat")  # owner deleted the branch
    g(repo, "fetch", "-q", "origin")
    cfg(repo, allow=[])
    tree(repo, "live-landed", sha)
    s = cw.collect(repo)
    assert s["outside_allow"] == [] and s["unknown"] == []


def test_head_lookup_error_is_unknown(repo):
    cfg(repo, allow=[])
    holder = Path(g(repo, "rev-parse", "--absolute-git-dir")) / "rosy-land-wt"
    (holder / "broken").mkdir(parents=True)  # not a git tree: rev-parse fails
    s = cw.collect(repo)
    assert s["unknown"] == ["broken"] and s["outside_allow"] == []
