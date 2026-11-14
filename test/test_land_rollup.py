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
            {**snapshot("fix/f", {"pkg/c.py": "z = 9\n"}), "alone": True},  # --tests full for publish evidence
            {**snapshot("fix/p", {"pkg/c.py": "z = 3\n"}), "status": "preparing"},
            {**snapshot("fix/o", {"pkg/c.py": "z = 4\n"}), "host": "other"},
            {**snapshot("fix/l", {"pkg/c.py": "z = 5\n"}), "batch": ["land/fix/k"]},
            snapshot("fix/k", {"pkg/c.py": "z = 8\n"}),
            {"branch": "fix/direct", "worktree": str(main), "status": "pending", "host": "h"}]
    moved = snapshot("fix/m", {"pkg/c.py": "z = 6\n"})
    git(Path(moved["worktree"]), "checkout", "-q", "-b", "land/fix/m-batch-k2")  # land.py moved it onto a batch
    commit(Path(moved["worktree"]), {"pkg/c.py": "z = 7\n"}, "batch merge")
    assert land_rollup.candidates(rows + [moved], main, host="h", mixed=False) == [a, b], "leader l, carried k out"


def test_plan_keeps_one_tier_skips_safety_and_conflicts_and_caps_the_size(repo, monkeypatch):
    main, snapshot = repo
    rows = [snapshot("fix/a", {"pkg/a.py": "x = 2\n"}), snapshot("fix/safe", {"pkg/b.py": "y = 9\n"}),
            snapshot("fix/full", {"pkg/c.py": "z = 9\n"}), snapshot("fix/clash", {"pkg/a.py": "x = 3\n"}),
            snapshot("fix/b", {"pkg/b.py": "y = 2\n"}), snapshot("fix/c", {"pkg/c.py": "z = 2\n"})]
    tiers = {"land/fix/safe": None, "land/fix/full": "full"}
    tier = lambda repo_, branch: tiers.get(branch, "affected")  # noqa: E731
    apart = lambda repo_, branch: [[branch + "/test"]]  # noqa: E731  (no two members share a suite)
    plan = lambda rows_: [r["branch"] for r in land_rollup.plan(main, rows_, tier, apart, mixed=False)]  # noqa: E731
    assert plan(rows) == ["land/fix/a", "land/fix/b", "land/fix/c"]
    monkeypatch.setattr(land_rollup, "ROLLUP_MAX", 2)
    assert plan(rows) == ["land/fix/a", "land/fix/b"]
    assert plan(rows[:2]) == [], "one member is no rollup"


def test_mixed_rollup_takes_full_waiters_every_tier_and_overlapping_suites(repo):
    """D-889 33, 11-09: 8 of 11 tickets were FULL waiters ('preparing'), so the half-hourly rollup merged none."""
    main, snapshot = repo
    rows = [{**snapshot("fix/a", {"pkg/a.py": "x = 2\n"}), "status": "preparing", "full_wait": True},
            {**snapshot("fix/run", {"pkg/c.py": "z = 5\n"}), "status": "preparing"},  # its pretest runs: stays
            snapshot("land-rollup-x", {"pkg/c.py": "z = 6\n"}),
            snapshot("fix/safe", {"pkg/b.py": "y = 9\n"}), snapshot("fix/clash", {"pkg/a.py": "x = 3\n"}),
            snapshot("fix/c", {"pkg/c.py": "z = 2\n"})]
    rows[2]["branch"] = "land/fix/land-rollup-20261109000000-20261109000000"  # no .members record: kept whole
    git(main, "branch", rows[2]["branch"], "land/land-rollup-x")
    got = land_rollup.candidates(rows, main, host="h", mixed=True)
    assert [r["branch"] for r in got] == ["land/fix/a", "land/fix/safe", "land/fix/clash", "land/fix/c"]
    assert land_rollup.candidates(rows, main, host="h", mixed=False) == rows[2:], "revert switch: idle only"
    tiers = {"land/fix/a": "full", "land/fix/safe": None}
    same = lambda repo_, branch: [["pkg/test"]]  # noqa: E731  (every suite overlaps)
    plan = land_rollup.plan(main, got, lambda r, b: tiers.get(b, "affected"), same, mixed=True)
    assert [r["branch"] for r in plan] == ["land/fix/a", "land/fix/safe", "land/fix/c"], "the clash stays out"
    tiers = {"land/fix/clash": "full"}  # the only FULL row clashes: an affected rollup, overlap counts again
    plan = land_rollup.plan(main, got, lambda r, b: tiers.get(b, "affected"), same, mixed=True)
    assert [r["branch"] for r in plan] == [], "every affected member overlaps the first: no rollup"


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


def test_build_merges_a_member_whose_snapshot_branch_is_gone_from_its_recorded_commit(repo):
    main, snapshot = repo
    rows = [snapshot("fix/a", {"pkg/a.py": "x = 2\n"}), snapshot("fix/b", {"pkg/b.py": "y = 2\n"}),
            snapshot("fix/c", {"pkg/c.py": "z = 2\n"})]
    rows[1]["candidate"] = git(main, "rev-parse", rows[1]["branch"])
    for row in rows[1:]:  # b keeps its recorded commit, c has none: left out, never a crash
        git(main, "worktree", "remove", "--force", row["worktree"])
        git(main, "branch", "-D", row["branch"])
    log = land_rollup.land_async.holder(main) / "land-fix-land-rollup-y.log"
    _, merged = land_rollup.build(main, rows, NOW, start=lambda *a: ("land/fix/land-rollup-y", log))
    assert [r["branch"] for r in merged] == ["land/fix/a", "land/fix/b"]


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


def test_capture_does_not_turn_invalid_noncarrier_children_into_a_valid_leaf(tmp_path):
    member = dict(branch="land/fix/a-20261101000000", ticket="a", candidate="a" * 40,
                  members=[dict(branch="land/fix/b-20261101000000", ticket="b", candidate="b" * 40)])
    captured = land_rollup.member_metadata(tmp_path, member)
    assert captured.get("members_error"), "invalid nested metadata must not be silently dropped into a valid leaf"


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
    plan = land_rollup.plan(main, rows, lambda r, b: "affected", lambda r, b: reach[b], mixed=True)
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


def test_a_rollup_whose_full_has_not_started_rerolls_with_new_waiters(repo, monkeypatch):
    """D-889 34, 11-09 22:40: two rollups and three FULL waiters each waited for one of two FULL slots."""
    main, snapshot = repo
    holder = land_rollup.land_async.holder(main)
    a, b = snapshot("fix/a", {"pkg/a.py": "x = 2\n"}), snapshot("fix/b", {"pkg/b.py": "y = 2\n"})
    old = snapshot("fix/land-rollup-20261109000000-20261109000000", {"pkg/r.py": "r = 1\n"})
    old.update(status="preparing", full_wait=True, ticket="t-old", pid=7)
    (holder / (old["branch"].replace("/", "-") + ".members")).write_text(json.dumps(
        [{"branch": m["branch"], "worktree": m["worktree"], "ticket": "gone"} for m in (a, b)]))
    new = {**snapshot("fix/c", {"pkg/c.py": "z = 2\n"}), "status": "preparing", "full_wait": True,
           "ticket": "t-new", "pid": 8}
    got = land_rollup.candidates([old, new], main, host="h", mixed=True)
    assert [(r["branch"], r["ticket"], r["pid"]) for r in got] == [
        ("land/fix/a", "t-old", 7), ("land/fix/b", "t-old", 7), ("land/fix/c", "t-new", 8)]
    passed = {**old, "status": "waiting"}
    assert land_rollup.candidates([passed, new], main, host="h", mixed=True) == [new], "its FULL passed: kept"
    assert land_rollup.whole(got[1:]) == got[2:], "a rollup with a member left out is not stopped"
    assert land_rollup.sources(got[:2]) == {old["branch"]}, "re-rolling with nothing new is no rollup"

    stopped, built = [], []
    monkeypatch.setattr(land_rollup.socket, "gethostname", lambda: "h")
    monkeypatch.setattr(land_rollup, "plan", lambda repo_, rows, tier_of=None: rows)
    monkeypatch.setattr(land_rollup, "adopted", lambda qdir, first: True)
    monkeypatch.setattr(land_rollup, "stop", stopped.append)
    monkeypatch.setattr(land_rollup.land_queue, "ahead", lambda qdir, t: [old, new])
    monkeypatch.setattr(land_rollup, "build", lambda repo_, members, now, urgent="": built.append(members) or (
        "land/fix/land-rollup-x", members))
    assert land_rollup.roll(main, holder.parent / "q", NOW, ["apply"]) == 0
    assert [m["branch"] for m in built[0]] == ["land/fix/a", "land/fix/b", "land/fix/c"]
    assert sorted(stopped) == [7, 8], "the old rollup's land.py and the waiter's, each once"
    marker = holder / (old["branch"].replace("/", "-") + ".split")
    assert "re-rolled into land/fix/land-rollup-x" in marker.read_text(), "its supervisor must not bisect it"

    stopped.clear()
    monkeypatch.setattr(land_rollup, "build", lambda repo_, members, now, urgent="": (
        "land/fix/land-rollup-y", [m for m in members if m["branch"] != "land/fix/b"]))  # b clashed in the merge
    marker.unlink()
    land_rollup.roll(main, holder.parent / "q", NOW, ["apply"])
    assert stopped == [8] and not marker.exists(), "the old rollup keeps landing b"


def test_the_halves_of_a_split_get_distinct_build_stamps(tmp_path, monkeypatch):
    """11-14 04:50: both halves got the same stamp; the second build found its branch taken and five members waited."""
    holder = tmp_path / "rosy-land-wt"
    holder.mkdir()
    (holder / "land-r.members").write_text(json.dumps([{"branch": n, "worktree": n} for n in "abcd"]))
    (holder / "land-r.log").write_text("[land] STOP: NEW failure in pkg/test")
    monkeypatch.setattr(land_rollup.land_async, "holder", lambda repo: holder)
    stamps = land_rollup.split(tmp_path, "land-r", NOW, builder=lambda repo, half, now: f"{now:%Y%m%d%H%M%S}",
                               resumer=lambda m: None)
    assert len(stamps) == 2 and stamps[0] != stamps[1]
