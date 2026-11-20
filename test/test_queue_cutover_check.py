"""Tests for tools/queue_cutover_check.py (D-1055 cutover reconciliation)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("queue_cutover_check", ROOT / "tools" / "queue_cutover_check.py")
qc = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = qc
SPEC.loader.exec_module(qc)


def _g(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True).stdout.strip()


def _repo(tmp_path):
    _g(tmp_path, "init", "-q", "-b", "main")
    _g(tmp_path, "config", "user.email", "t@e.com")
    _g(tmp_path, "config", "user.name", "t")
    _commit(tmp_path, "base")
    _g(tmp_path, "update-ref", "refs/remotes/origin/main", "HEAD")
    return tmp_path


def _commit(repo, name):
    (repo / name).write_text(name, encoding="utf-8")
    _g(repo, "add", name)
    _g(repo, "commit", "-qm", name)
    return _g(repo, "rev-parse", "HEAD")


def test_local_only_commit_missing_without_publish_or_carry(tmp_path):
    repo = _repo(tmp_path)
    sha = _commit(repo, "a")
    rec = qc.reconcile(repo, [])
    assert rec["missing"] == [sha] and rec["local_only"] == 1


def test_pending_publish_branch_covers_commits(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo, "a")
    _g(repo, "update-ref", "refs/remotes/origin/publish/main-20261120-01", "HEAD")
    assert qc.reconcile(repo, [])["missing"] == []


def test_merged_publish_branch_is_not_pending_and_carry_covers(tmp_path):
    repo = _repo(tmp_path)
    _g(repo, "update-ref", "refs/remotes/origin/publish/main-20261119-01", "origin/main")
    sha = _commit(repo, "a")
    assert qc.pending_publish_refs(repo) == []
    _g(repo, "branch", "carry", sha)
    assert qc.reconcile(repo, ["carry"])["missing"] == []


def test_main_exit_nonzero_when_commit_would_be_lost(tmp_path, capsys):
    repo = _repo(tmp_path)
    _commit(repo, "a")
    assert qc.main(["--no-fetch"], repo=repo) == 1
    assert "MISSING" in capsys.readouterr().out


def test_adr_status_parsed(tmp_path):
    (tmp_path / "docs/adr").mkdir(parents=True)
    (tmp_path / "docs/adr/D-1055-x.md").write_text("## D-1055 x\n\n**Status:** Proposed (2026)\n", encoding="utf-8")
    assert qc.adr_status(tmp_path) == "Proposed"
