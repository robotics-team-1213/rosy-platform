"""D-868 publish automation: which SHA, when to stop for a sync, when it is due, dry run touches nothing."""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("publish_main", ROOT / "tools" / "publish_main.py")
tool = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(tool)
NOW = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)
FULL = [["learning/registry/policy/test"], ["test"]]
AFFECTED = [["test/test_harness_contracts.py", "pkg/test"]]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def _commit(repo: Path, name: str, text: str) -> str:
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(text)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", f"{name}: {text}")
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    origin, local = tmp_path / "origin.git", tmp_path / "local"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(tmp_path, "init", "-q", "-b", "main", str(local))
    for key, value in (("user.email", "t@example.com"), ("user.name", "t")):
        _git(local, "config", key, value)
    _git(local, "remote", "add", "origin", str(origin))
    base = _commit(local, "app.py", "0")
    _commit(local, "docs/logs.md", "base\n")
    _git(local, "push", "-q", "origin", "main")
    _git(local, "fetch", "-q", "origin")

    def no_gh(*args):
        raise AssertionError(f"gh called: {args}")
    monkeypatch.setattr(tool, "run_gh", no_gh)
    return local, base


def _run(local: Path, *argv: str) -> int:
    return tool.main(["--repo", str(local), *argv], now=NOW)


def test_newest_commit_with_a_green_full_record_is_published(repo, capsys):
    local, _ = repo
    full, affected, bare = (_commit(local, "app.py", str(i)) for i in (1, 2, 3))
    tool.land_record.write(local, full, _git(local, "rev-parse", f"{full}^"), FULL, [])
    tool.land_record.write(local, affected, full, AFFECTED, [])  # newer, but not FULL
    assert tool.publish_sha(local) == full
    assert _run(local) == 0
    assert f"would push {full}" in capsys.readouterr().out


def test_the_full_marker_is_what_the_lab_full_tier_runs(tmp_path):
    import affected_tests  # tools/harness, on sys.path through conftest
    empty = affected_tests.Repo(tmp_path, modules=[], owners=[], tracked=[], test_files=[])
    assert ["test"] in affected_tests.lab_full_invocations(empty)  # green_full keys on this invocation


def test_no_green_full_record_means_nothing_to_publish(repo, capsys):
    local, _ = repo
    sha = _commit(local, "app.py", "1")
    tool.land_record.write(local, sha, _git(local, "rev-parse", f"{sha}^"), AFFECTED, [])
    assert tool.publish_sha(local) is None
    assert _run(local) == 0
    assert "nothing to publish" in capsys.readouterr().out


def test_a_record_on_the_main_tip_land_py_merged_in_as_second_parent_counts(repo):
    local, base = repo
    tip = _commit(local, "app.py", "main")
    tool.land_record.write(local, tip, _git(local, "rev-parse", f"{tip}^"), FULL, [])
    _git(local, "checkout", "-q", "-b", "topic", base)
    _commit(local, "other.py", "topic")
    _git(local, "merge", "-q", "--no-edit", "main")  # land.py: merge main into the topic, then --ff-only
    _git(local, "checkout", "-q", "main")
    _git(local, "merge", "-q", "--ff-only", "topic")
    assert tool.publish_sha(local) == tip


def _diverge(local: Path, origin_side: tuple[str, str], local_side: tuple[str, str]) -> None:
    published = _git(local, "rev-parse", "main")
    _git(local, "checkout", "-q", "-b", "teammate", published)
    _commit(local, *origin_side)
    _git(local, "push", "-q", "origin", "teammate:main")
    _git(local, "checkout", "-q", "main")
    _commit(local, *local_side)


def test_records_only_conflict_is_a_clean_sync_left_to_land_py(repo, capsys):
    local, _ = repo
    _diverge(local, ("docs/logs.md", "base\norigin\n"), ("docs/logs.md", "base\nlocal\n"))
    assert _run(local) == 4
    assert "tools/land.py" in capsys.readouterr().err


@pytest.mark.parametrize("origin_side,local_side,blocked", [
    (("app.py", "origin"), ("app.py", "local"), "app.py"),
    (("docs/index.md", "origin"), ("docs/index.md", "local"), "add/add"),  # a records path, but add/add
])
def test_code_or_add_add_conflict_stops_for_robot_4d(repo, capsys, origin_side, local_side, blocked):
    local, _ = repo
    _diverge(local, origin_side, local_side)
    main_before = _git(local, "rev-parse", "main")
    assert _run(local) == 3
    err = capsys.readouterr().err
    assert "sync needs robot-4d:" in err and blocked in err
    assert _git(local, "rev-parse", "main") == main_before  # merge-tree touched no branch or checkout
    assert _git(local, "status", "--porcelain") == ""


def test_publish_waits_min_hours_unless_a_blocked_teammate_forces_it(repo, capsys):
    local, _ = repo
    sha = _commit(local, "app.py", "1")
    tool.land_record.write(local, sha, _git(local, "rev-parse", f"{sha}^"), FULL, [])
    _git(local, "push", "-q", "origin", "HEAD~1:refs/heads/publish/main-20261026-10")  # 2 h before NOW
    assert _run(local) == 0
    assert "not due" in capsys.readouterr().out
    assert _run(local, "--min-hours", "1") == 0
    assert "would push" in capsys.readouterr().out
    assert _run(local, "--force-blocked", "PR 212 waits") == 0
    assert "forced: PR 212 waits" in capsys.readouterr().out


def _refs(path: Path) -> str:
    return _git(path, "for-each-ref", "--format=%(refname) %(objectname)")


def test_dry_run_changes_no_ref_worktree_or_origin(repo, tmp_path):
    local, _ = repo
    sha = _commit(local, "app.py", "1")
    tool.land_record.write(local, sha, _git(local, "rev-parse", f"{sha}^"), FULL, [])
    before = (_refs(local), _refs(tmp_path / "origin.git"), _git(local, "worktree", "list"))
    assert _run(local) == 0
    assert (_refs(local), _refs(tmp_path / "origin.git"), _git(local, "worktree", "list")) == before


def test_apply_pushes_the_chosen_sha_from_a_temporary_worktree_and_opens_a_pr(repo, tmp_path, monkeypatch):
    local, _ = repo
    sha = _commit(local, "app.py", "1")
    tool.land_record.write(local, sha, _git(local, "rev-parse", f"{sha}^"), FULL, [])
    _commit(local, "app.py", "2")  # main moved on past the green FULL commit
    calls = []

    def gh(repo_path, *args):
        calls.append(args)
        return "[]" if args[:2] == ("pr", "list") else "https://example.invalid/pull/1"
    monkeypatch.setattr(tool, "run_gh", gh)
    assert _run(local, "--apply") == 0
    assert _git(tmp_path / "origin.git", "rev-parse", "refs/heads/publish/main-20261026-12") == sha
    assert ("pr", "create") == calls[-1][:2] and "publish/main-20261026-12" in calls[-1]
    assert _git(local, "worktree", "list").count("\n") == 0  # the temporary worktree is gone


def _view(local: Path, sha: str, **over) -> str:
    view = {"state": "OPEN", "headRefName": "publish/main-20261026-12", "headRefOid": sha,
            "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN",
            "statusCheckRollup": [{"name": "ci-result", "status": "COMPLETED", "conclusion": "SUCCESS"}]}
    return json.dumps({**view, **over})


@pytest.mark.parametrize("over,code", [
    ({}, 0),
    ({"mergeable": "CONFLICTING", "mergeStateStatus": "DIRTY"}, 6),
    ({"statusCheckRollup": [{"name": "ci-result", "status": "IN_PROGRESS", "conclusion": ""}]}, 5),
    ({"statusCheckRollup": [{"name": "ci-result", "status": "COMPLETED", "conclusion": "FAILURE"}]}, 1),
])
def test_merge_when_green_merges_only_a_mergeable_green_pr_at_its_head(repo, monkeypatch, over, code):
    local, _ = repo
    sha = _commit(local, "app.py", "1")
    tool.land_record.write(local, sha, _git(local, "rev-parse", f"{sha}^"), FULL, [])
    calls = []

    def gh(repo_path, *args):
        calls.append(args)
        return _view(local, sha, **over) if args[:2] == ("pr", "view") else ""
    monkeypatch.setattr(tool, "run_gh", gh)
    assert _run(local, "--merge-when-green", "7", "--apply") == code
    merges = [c for c in calls if c[:2] == ("pr", "merge")]
    assert merges == ([("pr", "merge", "7", "--merge", "--match-head-commit", sha)] if code == 0 else [])
