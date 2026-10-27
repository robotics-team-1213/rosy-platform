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
    out = capsys.readouterr().out
    assert f"would push {full}" in out and "secret scan: 1 commits' added lines clean" in out


def test_a_green_full_commit_with_an_older_pre_push_is_skipped(repo):
    local, _ = repo
    old_hook = _commit(local, "app.py", "1")
    tool.land_record.write(local, old_hook, _git(local, "rev-parse", f"{old_hook}^"), FULL, [])
    _commit(local, "tools/hooks/pre-push", "new gate")  # the installed hook would refuse old_hook
    assert tool.publish_sha(local) is None
    same_hook = _commit(local, "app.py", "2")
    tool.land_record.write(local, same_hook, _git(local, "rev-parse", f"{same_hook}^"), FULL, [])
    assert tool.publish_sha(local) == same_hook


# Assembled at runtime so no credential assignment literal sits in this source.
LEAK = "pass" + "word = " + json.dumps("unexpected-live-credential-92817")


def test_secret_scan_alone_is_what_pre_push_runs_for_a_publish_ref(repo, capsys):
    local, _ = repo
    clean = _commit(local, "app.py", "1")
    assert _run(local, "--secret-scan", clean) == 0
    _commit(local, "config/site.env", LEAK + "\n")
    assert _run(local, "--secret-scan", "HEAD") == 9
    assert "[credential]" in capsys.readouterr().err


def test_a_secret_added_and_removed_inside_the_range_still_stops_the_publish(repo, capsys):
    local, _ = repo
    added = _commit(local, "config/site.env", LEAK + "\n")
    _commit(local, "config/site.env", "# removed\n")  # gone from the tip tree, still in the history
    sha = _commit(local, "app.py", "1")
    tool.land_record.write(local, sha, _git(local, "rev-parse", f"{sha}^"), FULL, [])
    assert _run(local) == 9
    err = capsys.readouterr().err
    assert f"{added[:10]} config/site.env [credential]" in err
    assert "unexpected-live-credential" not in err  # the value is never printed


def _baseline(local: Path, *hits: tuple[str, str, str]) -> None:
    rows = [{"commit": c, "path": p, "rule": r, "verdict": "reviewed: not a secret", "reviewed": "2026-10-26"}
            for c, p, r in hits]
    path = local / tool.BASELINE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": "rosy.publish-secret-baseline/1", "reviewer": "agent review 2026-10-26", "records": rows}), encoding="utf-8")


def test_a_reviewed_baseline_hit_passes_but_the_same_path_in_a_new_commit_stops(repo, capsys):
    local, _ = repo
    reviewed = _commit(local, "config/site.env", LEAK + "\n")
    sha = _commit(local, "app.py", "1")
    tool.land_record.write(local, sha, reviewed, FULL, [])
    _baseline(local, (reviewed, "config/site.env", "credential"))
    assert _run(local) == 0
    assert "1 reviewed baseline hit(s) skipped" in capsys.readouterr().out
    again = _commit(local, "config/site.env", LEAK + " # again\n")
    tool.land_record.write(local, again, sha, FULL, [])
    assert _run(local) == 9
    err = capsys.readouterr().err
    assert f"{again[:10]} config/site.env [credential]" in err and reviewed[:10] not in err


def test_a_baseline_row_carrying_anything_but_the_triple_and_verdict_is_refused(repo, capsys):
    local, _ = repo
    sha = _commit(local, "app.py", "1")
    tool.land_record.write(local, sha, _git(local, "rev-parse", f"{sha}^"), FULL, [])
    _baseline(local, (sha, "app.py", "credential"))
    path = local / tool.BASELINE
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["records"][0]["excerpt"] = "a value must never be stored here"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert _run(local) == 1
    assert "malformed" in capsys.readouterr().err


def test_a_baseline_without_the_agent_reviewer_note_is_refused(repo, capsys):
    local, _ = repo
    sha = _commit(local, "app.py", "1")
    tool.land_record.write(local, sha, _git(local, "rev-parse", f"{sha}^"), FULL, [])
    _baseline(local, (sha, "app.py", "credential"))
    path = local / tool.BASELINE
    doc = json.loads(path.read_text(encoding="utf-8"))
    del doc["reviewer"]
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert _run(local) == 1
    assert "malformed" in capsys.readouterr().err


def test_the_tracked_baseline_names_an_agent_review_and_loads():
    assert len(tool.load_baseline(ROOT)) >= 109


def test_a_secret_only_a_merge_commit_adds_is_caught(repo, capsys):
    local, base = repo
    _git(local, "checkout", "-q", "-b", "side", base)
    _commit(local, "side.py", "side")
    _git(local, "checkout", "-q", "main")
    _commit(local, "app.py", "1")
    _git(local, "merge", "-q", "--no-commit", "side")
    (local / "merged.env").write_text(LEAK + "\n")  # an evil merge: in neither parent
    _git(local, "add", "merged.env")
    _git(local, "commit", "-q", "-m", "merge side")
    merge = _git(local, "rev-parse", "HEAD")
    tool.land_record.write(local, merge, _git(local, "rev-parse", f"{merge}^"), FULL, [])
    assert _run(local) == 9
    assert f"{merge[:10]} merged.env [credential]" in capsys.readouterr().err


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
def test_code_or_add_add_conflict_stops_for_the_sync_owner(repo, capsys, origin_side, local_side, blocked):
    local, _ = repo
    _diverge(local, origin_side, local_side)
    main_before = _git(local, "rev-parse", "main")
    assert _run(local) == 3
    err = capsys.readouterr().err
    assert "sync needs 동기화·게시 담당:" in err and blocked in err
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


def _record(local: Path, sha: str, **fields) -> None:
    """A land record as a future or foreign land.py may write it (land_record.write fixes the fields)."""
    folder = tool.land_record.folder(local)
    folder.mkdir(parents=True, exist_ok=True)
    record = {"sha": sha, "base": _git(local, "rev-parse", f"{sha}^"), "at": "2026-10-26T01:00:00+00:00", **fields}
    (folder / f"{sha}.json").write_text(json.dumps(record), encoding="utf-8")


def test_a_tier_field_wins_over_the_invocation_fallback(repo):
    local, _ = repo
    full, affected = (_commit(local, "app.py", str(i)) for i in (1, 2))
    _record(local, full, tier="full", invocations=[["pkg/test"]])
    _record(local, affected, tier="affected", invocations=FULL)  # runs root test/ but says affected
    assert tool.publish_sha(local) == full


def test_records_of_an_unknown_format_stop_instead_of_nothing_to_publish(repo, capsys):
    local, _ = repo
    _record(local, _commit(local, "app.py", "1"), suites="test")  # neither tier nor invocations
    assert _run(local) == 8
    assert "none with a known format" in capsys.readouterr().err


def test_apply_pushes_the_chosen_sha_from_a_temporary_worktree_and_opens_a_pr(repo, tmp_path, monkeypatch):
    local, _ = repo
    _commit(local, "tools/hooks/pre-push", "#!/bin/sh\r\nexit 0\r\n")  # CRLF as Git for Windows may check it out
    sha = _commit(local, "app.py", "1")
    tool.land_record.write(local, sha, _git(local, "rev-parse", f"{sha}^"), FULL, [])
    after = _commit(local, "app.py", "2")  # main moved on past the green FULL commit: one landing of lag
    # 2026-10-27: a landing reinstalled the shared hook mid-push and bash died rereading it; the push uses its own copy
    shared = local / ".git" / "hooks" / "pre-push"
    shared.write_text("#!/bin/sh\nexit 1\n")
    shared.chmod(0o755)
    tool.land_record.write(local, after, sha, AFFECTED, [])
    calls = []

    def gh(repo_path, *args):
        calls.append(args)
        return "[]" if args[:2] == ("pr", "list") else "https://example.invalid/pull/1"
    monkeypatch.setattr(tool, "run_gh", gh)
    monkeypatch.setattr(tool, "safety_range", lambda wt, s: "1 commits checked, 0 missing")
    assert _run(local, "--apply") == 0
    assert _git(tmp_path / "origin.git", "rev-parse", "refs/heads/publish/main-20261026-12") == sha
    create = calls[-1]
    assert create[:2] == ("pr", "create") and "publish/main-20261026-12" in create
    body = create[create.index("--body") + 1]
    for fact in (sha, "`origin/main..SHA` 커밋 수: 1", "이 PR에 없는 착지 1건", "origin/main is ancestor: yes", "IP·호스트 규칙 미검사 (secret_scan에 규칙 없음)",
                 "1 commits checked, 0 missing", "D-868", f"--match-head-commit {sha}"):
        assert fact in body
    assert body.endswith(tool.GENERATED_BY)
    assert _git(local, "worktree", "list").count("\n") == 0  # the temporary worktree is gone
    assert list((local / ".git" / "rosy-publish").iterdir()) == []  # and its hook copy


def _view(local: Path, sha: str, **over) -> str:
    view = {"state": "OPEN", "headRefName": "publish/main-20261026-12", "headRefOid": sha,
            "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN",
            "statusCheckRollup": [{"name": "ci-result", "status": "COMPLETED", "conclusion": "SUCCESS"}]}
    return json.dumps({**view, **over})


def _merge_gh(local: Path, sha: str, calls: list, **over):
    """gh whose `pr merge` makes origin/main the merge commit M(old origin/main, sha), as GitHub does."""
    def gh(repo_path, *args):
        calls.append(args)
        if args[:2] == ("pr", "merge"):
            _git(local, "checkout", "-q", "--detach", "origin/main")
            _git(local, "merge", "-q", "--no-ff", "--no-edit", sha)
            _git(local, "push", "-q", "origin", "HEAD:main")
            _git(local, "checkout", "-q", "main")
        return _view(local, sha, **over) if args[:2] == ("pr", "view") else ""
    return gh


@pytest.mark.parametrize("over,code", [
    ({}, 0),
    ({"mergeable": "CONFLICTING", "mergeStateStatus": "DIRTY"}, 6),
    ({"statusCheckRollup": [{"name": "ci-result", "status": "IN_PROGRESS", "conclusion": ""}]}, 5),
    ({"statusCheckRollup": [{"name": "ci-result", "status": "COMPLETED", "conclusion": "FAILURE"}]}, 1),
])
def test_merge_when_green_merges_only_a_mergeable_green_pr_at_its_head(repo, monkeypatch, capsys, over, code):
    local, _ = repo
    sha = _commit(local, "app.py", "1")
    tool.land_record.write(local, sha, _git(local, "rev-parse", f"{sha}^"), FULL, [])
    _commit(local, "app.py", "2")  # local main moved past the published SHA
    calls = []
    monkeypatch.setattr(tool, "run_gh", _merge_gh(local, sha, calls, **over))
    assert _run(local, "--merge-when-green", "7", "--apply") == code
    merges = [c for c in calls if c[:2] == ("pr", "merge")]
    assert merges == ([("pr", "merge", "7", "--merge", "--match-head-commit", sha)] if code == 0 else [])
    if code == 0:  # no fast-forward is possible now: sync origin/main back through a worktree and land.py
        out = capsys.readouterr().out
        assert "git merge origin/main" in out and "tools/land.py" in out and "ff-only" not in out


def test_after_the_merge_a_direct_code_push_to_origin_stops_the_sync_back(repo, monkeypatch, capsys):
    local, _ = repo
    sha = _commit(local, "app.py", "1")
    tool.land_record.write(local, sha, _git(local, "rev-parse", f"{sha}^"), FULL, [])
    published = _git(local, "rev-parse", "origin/main")
    _git(local, "checkout", "-q", "-b", "direct", published)
    _commit(local, "lib.py", "origin")  # a teammate pushed straight to origin
    _git(local, "push", "-q", "origin", "direct:main")
    _git(local, "fetch", "-q", "origin")
    _git(local, "checkout", "-q", "main")
    _commit(local, "lib.py", "local")
    calls = []
    monkeypatch.setattr(tool, "run_gh", _merge_gh(local, sha, calls))
    assert _run(local, "--merge-when-green", "7", "--apply") == 3
    assert "sync needs 동기화·게시 담당:" in capsys.readouterr().err
