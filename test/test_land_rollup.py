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
    apart = lambda repo_, branch: [[branch + "/test"]]  # noqa: E731  (no two members share a suite)
    assert [r["branch"] for r in land_rollup.plan(main, rows, tier, apart)] == ["land/fix/a", "land/fix/b", "land/fix/c"]
    monkeypatch.setattr(land_rollup, "ROLLUP_MAX", 2)
    assert [r["branch"] for r in land_rollup.plan(main, rows, tier, apart)] == ["land/fix/a", "land/fix/b"]
    assert land_rollup.plan(main, rows[:2], tier, apart) == [], "one member is no rollup"


def test_build_merges_the_members_into_one_branch_and_records_them(repo, monkeypatch):
    main, snapshot = repo
    rows = [snapshot("fix/a", {"pkg/a.py": "x = 2\n"}), snapshot("fix/clash", {"pkg/a.py": "x = 3\n"}),
            snapshot("fix/b", {"pkg/b.py": "y = 2\n"})]
    for i, row in enumerate(rows):
        row["ticket"] = f"member-{i}"
    expected = {r["branch"]: git(main, "rev-parse", r["branch"]) for r in rows}
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
    assert [(m["candidate"], m["ticket"]) for m in members] == [
        (expected[rows[i]["branch"]], rows[i]["ticket"]) for i in (0, 2)]


def test_build_rejects_duplicate_branches_from_legacy_queue_rows(repo):
    main, snapshot = repo
    row = snapshot("fix/a", {"pkg/a.py": "x = 2\n"})
    with pytest.raises(land_rollup.land.Stop, match="duplicate"):
        land_rollup.build(main, [{**row, "ticket": "a1"}, {**row, "ticket": "a2"}], NOW,
                          start=lambda *a: pytest.fail("duplicate branch reached admission"))


def test_build_persists_nested_children_without_changing_direct_ownership(repo, monkeypatch):
    import land_events

    main, snapshot = repo
    leaves = [snapshot("fix/a", {"pkg/a.py": "x = 2\n"}), snapshot("fix/b", {"pkg/b.py": "y = 2\n"})]
    inner = snapshot("fix/land-rollup-20261101000100-20261101000100", {"pkg/inner.py": "inner = 1\n"})
    for leaf in leaves:
        git(Path(inner["worktree"]), "merge", "--no-edit", leaf["branch"])
    children = [dict(branch=r["branch"], worktree=r["worktree"], ticket=f"leaf-{i}",
                     candidate=git(main, "rev-parse", r["branch"])) for i, r in enumerate(leaves)]
    holder = land_rollup.land_async.holder(main)
    child_sidecar = holder / (inner["branch"].replace("/", "-") + ".members")
    child_sidecar.write_text(json.dumps(children), encoding="utf-8")
    sibling = snapshot("fix/c", {"pkg/c.py": "z = 2\n"})
    rows = [{**inner, "ticket": "inner"}, {**sibling, "ticket": "sibling"}]
    tip, log = [], holder / "land-fix-land-rollup-x.log"

    def start(wt, args, now, launch):
        tip.append(git(wt, "rev-parse", "HEAD"))
        return "land/fix/land-rollup-x", log

    name, _ = land_rollup.build(main, rows, NOW, start=start)
    members = json.loads(log.with_suffix(".members").read_text())
    assert [m["branch"] for m in members] == [r["branch"] for r in rows]
    assert members[0]["members"] == children
    child_sidecar.unlink()  # completion must survive later collection of the child's sidecar
    event_log = holder.parent / land_events.EVENTS
    monkeypatch.setattr(land_events, "_where", dict(path=event_log, branch=name))
    land_events.landed(tip[0])
    completed = land_events.read(event_log)
    assert len(completed) == 1 and completed[0]["members"][0]["members"] == children


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


def test_ready_landings_roll_up_only_when_their_suites_do_not_overlap(repo):
    """D-889 23, 11-02: two or more landings sat ready 75 % of the time while each turn landed one."""
    main, snapshot = repo
    rows = [{**snapshot("fix/a", {"pkg/a.py": "x = 2\n"}), "status": "waiting"},
            {**snapshot("fix/b", {"pkg/b.py": "y = 2\n"}), "status": "waiting"},
            snapshot("fix/c", {"pkg/c.py": "z = 2\n"})]
    assert land_rollup.candidates(rows, main, host="h") == rows, "waiting (ready) tickets are members too"
    reach = {"land/fix/a": [["pkg/test/test_a.py"]], "land/fix/b": [["pkg/test"]], "land/fix/c": [["other/test"]]}
    plan = land_rollup.plan(main, rows, lambda r, b: "affected", lambda r, b: reach[b])
    assert [r["branch"] for r in plan] == ["land/fix/a", "land/fix/c"], "b's suites contain a's: b lands alone"


def test_the_rollup_takes_its_first_members_place_and_the_member_leaves_it(repo, monkeypatch, tmp_path):
    main, snapshot = repo
    qdir = land_rollup.land_queue.queue_dir(main)
    first = land_rollup.land_queue.take(qdir, "land/fix/a", "w", "waiting")
    rows = [{**snapshot("fix/a", {"pkg/a.py": "x = 2\n"}), "ticket": first.name, "pid": 1},
            snapshot("fix/b", {"pkg/b.py": "y = 2\n"})]
    seen = []

    def start(wt, args, now, launch):
        seen.append(land_rollup.os.environ.get(land_rollup.land_queue.TICKET_ENV))
        return "land/fix/land-rollup-x", land_rollup.land_async.holder(wt) / "land-fix-land-rollup-x.log"
    land_rollup.build(main, rows, NOW, start=start)
    assert seen == [str(first)] and land_rollup.land_queue.TICKET_ENV not in land_rollup.os.environ
    # the rollup's land.py adopts it (pid changes); the first member's exit must not remove it
    land_rollup.land_queue.set_status(first, "preparing", pid=999999, branch="fix/land-rollup-x")
    assert land_rollup.adopted(qdir, rows[0], wait=1, sleep=lambda s: None)
    monkeypatch.setattr(land_rollup.land_queue, "_held", [first])
    land_rollup.land_queue.leave()
    assert first.exists(), "an adopted ticket stays when its old owner leaves"
