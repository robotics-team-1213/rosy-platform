"""tools/land_rollup_failed.py: a candidate that failed a rollup on a NEW failure is not rolled up again (bn-L-2)."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import land_rollup  # noqa: E402
import land_rollup_failed  # noqa: E402

NOW = datetime(2026, 11, 20, tzinfo=timezone.utc)


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A repo with branches a, b, c (one commit each) and its hidden holder."""
    main = tmp_path / "main"
    main.mkdir()
    git(main, "init", "-q", "-b", "main")
    git(main, "config", "user.name", "t")
    git(main, "config", "user.email", "t@t")
    git(main, "commit", "-q", "--allow-empty", "-m", "init")
    for b in "abc":
        git(main, "branch", b, "main")
        git(main, "commit", "-q", "--allow-empty", "-m", b)  # on main: moves main only
        git(main, "update-ref", f"refs/heads/{b}", git(main, "commit-tree", "-p", "main", "-m", b, "main^{tree}"))
    holder = land_rollup.land_async.holder(main)
    holder.mkdir(parents=True, exist_ok=True)
    return main, holder


def tip(main: Path, b: str) -> str:
    return git(main, "rev-parse", b)


def test_split_bisect_records_members_and_still_builds_its_halves(repo):
    """11-19 16:07~19:42: the same members rode about ten rollups, each stopping on the same test."""
    main, holder = repo
    members = [{"branch": b, "worktree": b, "candidate": tip(main, b)} for b in "abc"]
    (holder / "land-r.members").write_text(json.dumps(members))
    (holder / "land-r.log").write_text("[land] STOP: NEW failure in pkg/test")
    seen = land_rollup.split(main, "land-r", NOW, builder=lambda repo_, half, now: [m["branch"] for m in half],
                             resumer=lambda m: [m["branch"]], bisect=True)
    assert seen == [["a"], ["b", "c"]], "bisect keeps building halves (a half of one lands alone)"
    assert land_rollup_failed.failed(holder.parent, NOW) == {tip(main, b): "land-r" for b in "abc"}


def test_split_without_a_verdict_records_nothing(repo):
    main, holder = repo
    (holder / "land-r.members").write_text(json.dumps([{"branch": b, "worktree": b, "candidate": tip(main, b)}
                                                       for b in "ab"]))
    land_rollup.split(main, "land-r", NOW, builder=lambda *a: None, resumer=lambda m: None, bisect=False)
    assert land_rollup_failed.failed(holder.parent, NOW) == {}


def test_auto_leaves_out_failed_candidates_and_rollups_holding_one(repo, capsys):
    main, holder = repo
    land_rollup_failed.record(holder.parent, "land-r", [{"branch": "a", "candidate": tip(main, "a")}], NOW)
    rows = [{"branch": "a"}, {"branch": "b"}, {"branch": "c"},
            {"branch": "a", "rollup": "fix/land-rollup-h", "candidate": tip(main, "a")},
            {"branch": "c", "rollup": "fix/land-rollup-h", "candidate": tip(main, "c")}]
    assert land_rollup_failed.drop(main, holder.parent, rows, NOW) == [{"branch": "b"}, {"branch": "c"}]
    assert "a left out: failed in land-r" in capsys.readouterr().out


def test_a_new_candidate_or_an_old_record_rolls_up_again(repo):
    main, holder = repo
    land_rollup_failed.record(holder.parent, "land-r", [{"branch": "a", "candidate": tip(main, "a")}], NOW - timedelta(hours=25))
    land_rollup_failed.record(holder.parent, "land-s", [{"branch": "b", "candidate": "0" * 40}], NOW)  # b's old commit
    rows = [{"branch": "a"}, {"branch": "b"}]
    assert land_rollup_failed.drop(main, holder.parent, rows, NOW) == rows


@pytest.mark.parametrize("text", [None, "", "not json\n{\"t\": 1}\n[]\n{\"t\": \"2026-11-20T00:00:00\"}\n"])
def test_a_missing_or_broken_record_leaves_nothing_out(repo, text):
    main, holder = repo
    if text is not None:
        (holder.parent / land_rollup_failed.NAME).write_text(text, encoding="utf-8")
    rows = [{"branch": "a"}, {"branch": "b"}]
    assert land_rollup_failed.drop(main, holder.parent, rows, NOW) == rows
