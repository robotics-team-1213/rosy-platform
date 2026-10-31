"""tools/land_rollup.py: waiting landings rolled into one branch and one ticket (D-889 addendum 11)."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import land_rollup  # noqa: E402

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def commit(cwd: Path, files: dict[str, str], message: str) -> None:
    for name, data in files.items():
        path = cwd / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data, encoding="utf-8")
    git(cwd, "add", "-A")
    git(cwd, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    git(main, "init", "-q", "-b", "main")
    git(main, "config", "user.name", "t")
    git(main, "config", "user.email", "t@t")
    commit(main, {"pkg/a.py": "x = 1\n", "pkg/b.py": "y = 1\n", "pkg/c.py": "z = 1\n"}, "init")
    holder = Path(git(main, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "rosy-land-wt"

    def snapshot(name: str, files: dict[str, str]) -> dict:
        branch, tree = f"land/{name}", holder / f"land-{name}"
        git(main, "worktree", "add", "-q", "-b", branch, str(tree), "main")
        commit(tree, files, name)
        return {"branch": branch, "worktree": str(tree), "status": "pending", "host": "h", "pid": 1}
    return main, snapshot


def test_only_plain_pending_landings_at_their_snapshot_tip_roll_up(repo):
    main, snapshot = repo
    a, b = snapshot("fix/a", {"pkg/a.py": "x = 2\n"}), snapshot("fix/b", {"pkg/b.py": "y = 2\n"})
    rows = [a, b, {**snapshot("fix/u", {"pkg/c.py": "z = 2\n"}), "urgent": "the user's words"},
            {**snapshot("fix/p", {"pkg/c.py": "z = 3\n"}), "status": "preparing"},
            {**snapshot("fix/o", {"pkg/c.py": "z = 4\n"}), "host": "other"},
            {**snapshot("fix/l", {"pkg/c.py": "z = 5\n"}), "batch": ["land/fix/k"]},
            snapshot("fix/k", {"pkg/c.py": "z = 8\n"}),
            {"branch": "fix/direct", "worktree": str(main), "status": "pending", "host": "h"}]
    moved = snapshot("fix/m", {"pkg/c.py": "z = 6\n"})
    git(Path(moved["worktree"]), "checkout", "-q", "-b", "land/fix/m-batch-k2")  # land.py moved it onto a batch
    commit(Path(moved["worktree"]), {"pkg/c.py": "z = 7\n"}, "batch merge")
    assert land_rollup.candidates(rows + [moved], main, host="h") == [a, b], "leader l and carried k stay out"


def test_plan_keeps_one_tier_skips_safety_and_conflicts_and_caps_the_size(repo, monkeypatch):
    main, snapshot = repo
    rows = [snapshot("fix/a", {"pkg/a.py": "x = 2\n"}), snapshot("fix/safe", {"pkg/b.py": "y = 9\n"}),
            snapshot("fix/full", {"pkg/c.py": "z = 9\n"}), snapshot("fix/clash", {"pkg/a.py": "x = 3\n"}),
            snapshot("fix/b", {"pkg/b.py": "y = 2\n"}), snapshot("fix/c", {"pkg/c.py": "z = 2\n"})]
    tiers = {"land/fix/safe": None, "land/fix/full": "full"}
    tier = lambda repo_, branch: tiers.get(branch, "affected")  # noqa: E731
    assert [r["branch"] for r in land_rollup.plan(main, rows, tier)] == ["land/fix/a", "land/fix/b", "land/fix/c"]
    monkeypatch.setattr(land_rollup, "ROLLUP_MAX", 2)
    assert [r["branch"] for r in land_rollup.plan(main, rows, tier)] == ["land/fix/a", "land/fix/b"]
    assert land_rollup.plan(main, rows[:2], tier) == [], "one member is no rollup"


def test_build_merges_the_members_into_one_branch_and_records_them(repo, monkeypatch):
    main, snapshot = repo
    rows = [snapshot("fix/a", {"pkg/a.py": "x = 2\n"}), snapshot("fix/clash", {"pkg/a.py": "x = 3\n"}),
            snapshot("fix/b", {"pkg/b.py": "y = 2\n"})]
    started = []

    def start(wt, args, now, launch):
        started.append((git(wt, "rev-parse", "HEAD"), args))
        log = land_rollup.land_async.holder(wt) / "land-fix-land-rollup-x.log"
        return "land/fix/land-rollup-x", log
    snap, merged = land_rollup.build(main, rows, NOW, start=start)
    assert [r["branch"] for r in merged] == ["land/fix/a", "land/fix/b"], "the clashing member lands alone"
    head, args = started[0]
    assert args == ["--tests", "auto"]
    assert git(main, "show", f"{head}:pkg/a.py") == "x = 2" and git(main, "show", f"{head}:pkg/b.py") == "y = 2"
    members = json.loads((land_rollup.land_async.holder(main) / "land-fix-land-rollup-x.members").read_text())
    assert [m["branch"] for m in members] == ["land/fix/a", "land/fix/b"]


@pytest.mark.parametrize("log, groups", [("[land] STOP: NEW failure in pkg/test", [["a", "b"], ["c", "d", "e"]]),
                                         ("[land] STOP: merge aborted; resolve by hand", [["a"], ["b"], ["c"], ["d"],
                                                                                         ["e"]])])
def test_a_failed_rollup_splits_in_halves_or_sends_members_back_alone(tmp_path, monkeypatch, log, groups):
    holder = tmp_path / "rosy-land-wt"
    holder.mkdir()
    (holder / "land-r.members").write_text(json.dumps([{"branch": n, "worktree": n} for n in "abcde"]))
    (holder / "land-r.log").write_text(log)
    monkeypatch.setattr(land_rollup.land_async, "holder", lambda repo: holder)
    seen = land_rollup.split(tmp_path, "land-r", NOW, builder=lambda repo, half, now: [m["branch"] for m in half],
                             resumer=lambda m: [m["branch"]])
    assert seen == groups
