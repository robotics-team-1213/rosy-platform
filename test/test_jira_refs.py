"""tools/jira_refs.py: key matching, the advisory check and the range report on a throwaway repo."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import jira_refs  # noqa: E402


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    for key, value in (("user.name", "t"), ("user.email", "t@t"), ("core.autocrlf", "false")):
        git(repo, "config", key, value)
    (repo / "a.txt").write_text("0\n", encoding="utf-8")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", "chore: base")
    return repo


def commit(repo: Path, message: str) -> None:
    path = repo / "a.txt"
    path.write_text(path.read_text(encoding="utf-8") + "1\n", encoding="utf-8")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", message)


def test_find_keys_matches_branch_and_commit_forms_only():
    assert jira_refs.find_keys("feat/kan-14-omx-check", "KAN") == ["KAN-14"]
    assert jira_refs.find_keys("fix(drive): turn (KAN-13) see KAN-13, KAN-7", "KAN") == ["KAN-13", "KAN-7"]
    assert jira_refs.find_keys("XKAN-1 KAN-1x D-403 kan-", "KAN") == []
    assert jira_refs.find_keys("KAN-007", "KAN") == ["KAN-7"]


def test_check_is_advisory_unless_strict(repo, tmp_path, capsys):
    message = tmp_path / "msg"
    message.write_text("docs: notes\n", encoding="utf-8")
    assert jira_refs.main(["--repo", str(repo), "check", "--branch", "docs/notes",
                           "--message-file", str(message)]) == 0
    out = capsys.readouterr().out
    assert "no KAN key" in out and "hint:" in out
    assert jira_refs.main(["--repo", str(repo), "check", "--branch", "docs/notes", "--strict"]) == 1
    assert jira_refs.main(["--repo", str(repo), "check", "--branch", "feat/kan-26-real-path", "--strict"]) == 0


def test_check_reads_the_current_branch(repo, capsys):
    git(repo, "checkout", "-q", "-b", "feat/kan-27-pinky-goal")
    assert jira_refs.main(["--repo", str(repo), "check", "--strict"]) == 0
    assert "KAN-27" in capsys.readouterr().out


def test_report_groups_commits_by_key_and_lists_unkeyed(repo, capsys):
    base = git(repo, "rev-parse", "HEAD")
    commit(repo, "feat(fleet): send waypoint goal (KAN-27)")
    commit(repo, "fix(omx): grip width | retry\n\nRefs KAN-28 and KAN-27")
    commit(repo, "docs: typo")
    assert jira_refs.main(["--repo", str(repo), "report", "--range", f"{base}..HEAD"]) == 0
    out = capsys.readouterr().out
    assert "이슈 2개 · 키 없는 커밋 1개" in out
    rows = [line for line in out.splitlines() if line.startswith("| KAN-") or line.startswith("| (없음)")]
    assert [row.split(" | ")[0] for row in rows] == ["| KAN-27", "| KAN-27", "| KAN-28", "| (없음)"]
    assert "grip width / retry" in out

    assert jira_refs.main(["--repo", str(repo), "report", "--range", f"{base}..HEAD", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert sorted(payload["issues"]) == ["KAN-27", "KAN-28"]
    assert [row["subject"] for row in payload["unkeyed"]] == ["docs: typo"]
