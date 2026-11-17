"""tools/urgent_lane.py (D-1038): evidence, publish dry run/apply and the merge-when-green evidence swap, with fakes."""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import urgent_lane  # noqa: E402
from test_publish_main import _commit, _git, _merge_gh, _run, _view, repo, tool  # noqa: E402,F401

NOW = datetime(2026, 11, 17, 3, tzinfo=timezone.utc)


def _runner(text="1 passed in 0.1s", code=0):
    def run(invocations, logs, sha, repo, label):
        for log in logs:
            log.write_text(text + "\n", encoding="utf-8")
        return [code] * len(invocations)
    return run


def _evidence(local, tmp_path, monkeypatch, **runner):
    monkeypatch.setattr(urgent_lane, "plan", lambda *a: [["pkg/test"]])
    return urgent_lane.collect(local, tmp_path, runner=_runner(**runner))


def test_green_evidence_is_kept_and_verified_only_while_intact(repo, tmp_path, monkeypatch):
    local, _ = repo
    sha = _commit(local, "app.py", "fix")
    path = _evidence(local, tmp_path, monkeypatch)
    assert path.name == f"{sha}.json" and urgent_lane.verified(local, sha)
    (tmp_path / "urgent-0.txt").write_text("1 passed in 0.1s\nedited\n", encoding="utf-8")
    assert not urgent_lane.verified(local, sha)


def test_red_or_empty_evidence_is_refused_and_writes_nothing(repo, tmp_path, monkeypatch):
    local, _ = repo
    sha = _commit(local, "app.py", "fix")
    with pytest.raises(urgent_lane.Stop, match="red or incomplete"):
        _evidence(local, tmp_path, monkeypatch, text="FAILED test/test_x.py::test_new - boom\n1 failed in 0.1s", code=1)
    with pytest.raises(urgent_lane.Stop, match="red or incomplete"):
        _evidence(local, tmp_path, monkeypatch, text="", code=0)
    assert not urgent_lane.verified(local, sha)


def test_a_branch_stacked_on_main_work_is_refused(repo, tmp_path, monkeypatch):
    local, _ = repo
    _commit(local, "app.py", "1")
    _commit(local, "app.py", "2")
    monkeypatch.setattr(urgent_lane, "MAX_COMMITS", 1)
    with pytest.raises(urgent_lane.Stop, match="fix only"):
        _evidence(local, tmp_path, monkeypatch)


def test_publish_is_a_dry_run_until_apply_and_pushes_the_evidence_commit(repo, tmp_path, monkeypatch):
    local, _ = repo
    sha = _commit(local, "app.py", "fix")
    _evidence(local, tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(urgent_lane, "run_gh", lambda repo_, *a: calls.append(a) or "https://example/pr/9\n")
    assert "dry run" in urgent_lane.publish(local, sha, "login-fix", False, NOW) and calls == []
    assert urgent_lane.publish(local, sha, "login-fix", True, NOW).startswith("pushed")
    remote = _git(local, "ls-remote", "origin", "refs/heads/urgent/login-fix-20261117")
    assert remote.split()[0] == sha
    assert calls[0][:2] == ("pr", "create") and "--base" in calls[0] and "main" in calls[0]


def test_publish_without_evidence_for_that_commit_is_refused(repo):
    local, _ = repo
    sha = _commit(local, "app.py", "fix")
    with pytest.raises(urgent_lane.Stop, match="no clean urgent evidence"):
        urgent_lane.publish(local, sha, "login-fix", True, NOW)


@pytest.mark.parametrize("with_evidence,code", [(True, 0), (False, 1)])
def test_merge_when_green_takes_urgent_evidence_in_place_of_the_full_record(repo, tmp_path, monkeypatch, with_evidence, code):
    local, _ = repo
    sha = _commit(local, "app.py", "fix")
    if with_evidence:
        _evidence(local, tmp_path, monkeypatch)
    calls = []
    gh = _merge_gh(local, sha, calls)

    def urgent_gh(r, *a):
        out = gh(r, *a)
        return json.dumps({**json.loads(out), "headRefName": "urgent/login-fix-20261117"}) if a[:2] == ("pr", "view") else out
    monkeypatch.setattr(tool, "run_gh", urgent_gh)
    assert _run(local, "--merge-when-green", "9", "--apply") == code
    merges = [c for c in calls if c[:2] == ("pr", "merge")]
    assert merges == ([("pr", "merge", "9", "--merge", "--match-head-commit", sha)] if code == 0 else [])
