"""D-553 addendum 3: pre-push reuses land.py's green results only through an unbroken record chain."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("land_record", ROOT / "tools" / "hooks" / "land_record.py")
tool = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(tool)
FAST = ["test/fast_a.py", "test/fast_b.py"]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    commits = []
    for i in range(4):
        (tmp_path / "f.txt").write_text(str(i))
        _git(tmp_path, "add", "f.txt")
        _git(tmp_path, "commit", "-q", "-m", f"c{i}")
        commits.append(_git(tmp_path, "rev-parse", "HEAD"))
    _git(tmp_path, "update-ref", "refs/remotes/origin/main", commits[0])
    return tmp_path, commits


def test_a_full_chain_back_to_origin_reuses_results_and_owes_unran_fast_suites(repo):
    path, c = repo
    tool.write(path, c[2], c[0], [["test/fast_a.py", "pkg/test"]], [])
    tool.write(path, c[3], c[2], [["other/test"]], [])
    assert tool.owed(path, c[3], "origin/main", FAST) == ["test/fast_b.py"]


def test_a_missing_record_breaks_the_chain(repo):
    path, c = repo
    tool.write(path, c[3], c[2], [["test/fast_a.py", "test/fast_b.py"]], [])
    assert tool.owed(path, c[3], "origin/main", FAST) is None  # c[1]..c[2] were never landed by land.py


def test_a_record_whose_base_is_not_an_ancestor_is_ignored(repo):
    path, c = repo
    tool.write(path, c[1], c[3], [["x"]], [])
    assert tool.owed(path, c[1], "origin/main", FAST) is None


def test_nothing_past_origin_runs_the_gate_as_before(repo):
    path, c = repo
    assert tool.owed(path, c[0], "origin/main", FAST) is None


def test_the_hook_falls_back_when_the_helper_says_not_covered():
    hook = (ROOT / "tools" / "hooks" / "pre-push").read_text(encoding="utf-8")
    reuse = hook.index("land_record.py owed")
    assert reuse < hook.index('AFFECTED_BASE="$(git merge-base')
    assert "exit 0" in hook[reuse:hook.index('AFFECTED_BASE="$(git merge-base')]
