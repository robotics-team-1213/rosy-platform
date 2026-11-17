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
                             resumer=lambda m: [m["branch"]], bisect=True)
    assert seen == groups


def test_ready_landings_roll_up_only_when_their_suites_do_not_overlap(repo):
    """D-889 23, 11-02: two or more landings sat ready 75 % of the time while each turn landed one."""
    main, snapshot = repo
    rows = [{**snapshot("fix/a", {"pkg/a.py": "x = 2\n"}), "status": "waiting"},
            {**snapshot("fix/b", {"pkg/b.py": "y = 2\n"}), "status": "waiting"},
            snapshot("fix/c", {"pkg/c.py": "z = 2\n"})]
    assert land_rollup.candidates(rows, main, host="h") == rows, "waiting tickets without a prepare record are members"
    reach = {"land/fix/a": [["pkg/test/test_a.py"]], "land/fix/b": [["pkg/test"]], "land/fix/c": [["other/test"]]}
    plan = land_rollup.plan(main, rows, lambda r, b: "affected", lambda r, b: reach[b], mixed=True)
    assert [r["branch"] for r in plan] == ["land/fix/a", "land/fix/c"], "b's suites contain a's: b lands alone"


def test_a_prepared_waiting_ticket_is_not_rolled_up(repo):
    """D-889 38, 11-17: a waiting ticket that carries `tested` or tier full_done lands on its own evidence."""
    main, snapshot = repo
    plain = snapshot("fix/a", {"pkg/a.py": "x = 2\n"})
    tested = {**snapshot("fix/b", {"pkg/b.py": "y = 2\n"}), "status": "waiting", "tested": "abc123"}
    done = {**snapshot("fix/c", {"pkg/c.py": "z = 2\n"}), "status": "waiting", "tier": "full_done"}
    assert land_rollup.candidates([plain, tested, done], main, host="h") == [plain]


def test_a_pending_ticket_tested_on_the_current_main_is_not_rolled_up(repo):
    """11-18: pending + tested == main kept its pass; tested on an older main may still re-roll."""
    main, snapshot = repo
    head = land_rollup.git(main, "rev-parse", "main").stdout.strip()
    fresh = {**snapshot("fix/a", {"pkg/a.py": "x = 2\n"}), "status": "pending", "tested": head}
    stale = {**snapshot("fix/b", {"pkg/b.py": "y = 2\n"}), "status": "pending", "tested": "0" * 40}
    assert land_rollup.candidates([fresh, stale], main, host="h") == [stale]


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


def test_a_stop_without_a_new_failure_requeues_members_instead_of_halves(tmp_path, monkeypatch):
    holder = tmp_path / "rosy-land-wt"
    holder.mkdir()
    (holder / "land-r.members").write_text(json.dumps([{"branch": n, "worktree": n} for n in "abc"]))
    (holder / "land-r.log").write_text("[remote-pytest] serial: browser job")  # killed: no verdict
    monkeypatch.setattr(land_rollup.land_async, "holder", lambda repo: holder)
    kw = dict(builder=lambda repo, half, now: pytest.fail("no halves"), resumer=lambda m: m["branch"])
    assert land_rollup.split(tmp_path, "land-r", NOW, **kw) == ["a", "b", "c"]


def test_one_rollup_lane_blocks_a_new_build_until_it_is_stuck_or_not_yet_checking(repo, monkeypatch):
    main, snapshot = repo
    qdir = land_rollup.land_async.holder(main).parent / "q"
    name = "land/fix/land-rollup-20261117000000-20261117000000"
    plain = {**snapshot("fix/a", {"pkg/a.py": "x = 2\n"}), "ticket": "t1"}
    monkeypatch.setattr(land_rollup.socket, "gethostname", lambda: "h")
    monkeypatch.setattr(land_rollup, "build", lambda *a, **k: pytest.fail("a rollup is in flight"))
    monkeypatch.setattr(land_rollup, "plan", lambda r, rows, tier_of=None: rows)
    for status, extra, age in (("turn", {}, 60), ("waiting", {}, 60), ("preparing", {}, 60)):
        row = dict(branch=name, status=status, host="h", ticket="t0", age=age, **extra)
        monkeypatch.setattr(land_rollup.land_queue, "ahead", lambda q, t, row=row: [row, plain])
        assert land_rollup.roll(main, qdir, NOW, ["apply"]) == 0
    live = [dict(branch=name, status="preparing", host="h", full_wait=True, age=60),
            dict(branch=name, status="pending", host="h", age=60),
            dict(branch=name, status="turn", host="other", age=60),
            dict(branch=name, status="turn", host="h", age=land_rollup.ROLLUP_LANE_S + 1)]
    assert land_rollup.in_flight(live, "h") == []
    assert len(land_rollup.in_flight([{**live[3], "age": 60}], "h")) == 1


def test_the_halves_of_a_split_get_distinct_build_stamps(tmp_path, monkeypatch):
    """11-14 04:50: both halves got the same stamp; the second build found its branch taken and five members waited."""
    holder = tmp_path / "rosy-land-wt"
    holder.mkdir()
    (holder / "land-r.members").write_text(json.dumps([{"branch": n, "worktree": n} for n in "abcd"]))
    (holder / "land-r.log").write_text("[land] STOP: NEW failure in pkg/test")
    monkeypatch.setattr(land_rollup.land_async, "holder", lambda repo: holder)
    stamps = land_rollup.split(tmp_path, "land-r", NOW, builder=lambda repo, half, now: f"{now:%Y%m%d%H%M%S}",
                               resumer=lambda m: None, bisect=True)
    assert len(stamps) == 2 and stamps[0] != stamps[1]


def test_remote_runs_extracts_and_deduplicates_from_log_and_resume_log(tmp_path):
    holder = tmp_path / "rosy-land-wt"
    holder.mkdir()
    (holder / "land-fix-a.log").write_text(
        "[remote-pytest] deadbeef12 on model-pc (~/rosy-test/runs/land-1-aaa111)\n"
        "[remote-pytest] bad line without path\n"
        "[remote-pytest] deadbeef12 on ai-pc (~/rosy-test/runs/land-1-bbb222)\n",
        encoding="utf-8",
    )
    (holder / "land-fix-a.resume.log").write_text(
        "[remote-pytest] deadbeef12 on model-pc (~/rosy-test/runs/land-1-aaa111)\n"
        "[remote-pytest] cafe567890 on model-pc (~/rosy-test/runs/land-2-ccc333)\n",
        encoding="utf-8",
    )
    rollup_name = "land/fix/land-rollup-20261109000000-20261109000000"
    (holder / (rollup_name.replace("/", "-") + ".log")).write_text(
        "[remote-pytest] 0123456789 on rosy@ai-pc (~/rosy-test/runs/land-1-ddd444)\n"
        "[remote-pytest] 0123456789 on rosy@ai-pc (~/rosy-test/runs/land-1-ddd444)\n",
        encoding="utf-8",
    )
    rows = [
        {"branch": "land/fix/a", "worktree": str(holder / "land-fix-a")},
        {"branch": "land/fix/b", "worktree": str(holder / "land-fix-b"), "rollup": rollup_name},
        {"branch": "land/fix/c", "worktree": str(holder / "land-fix-c"), "rollup": rollup_name},
        {"branch": "land/fix/missing", "worktree": str(holder / "land-fix-missing")},
    ]
    assert land_rollup.remote_runs(holder, rows) == [
        ("model-pc", "land-1-aaa111"),
        ("ai-pc", "land-1-bbb222"),
        ("model-pc", "land-2-ccc333"),
        ("rosy@ai-pc", "land-1-ddd444"),
    ]


def test_stop_remote_invokes_ssh_and_survives_unreachable_hosts(tmp_path, monkeypatch):
    holder = tmp_path / "rosy-land-wt"
    holder.mkdir()
    (holder / "land-fix-a.log").write_text(
        "[remote-pytest] deadbeef12 on dead-host (~/rosy-test/runs/land-1-111111)\n"
        "[remote-pytest] deadbeef12 on err-host (~/rosy-test/runs/land-1-222222)\n"
        "[remote-pytest] deadbeef12 on live-host (~/rosy-test/runs/land-1-333333)\n",
        encoding="utf-8",
    )
    rows = [{"branch": "land/fix/a", "worktree": str(holder / "land-fix-a")}]
    calls = []

    def fake_run(cmd, **kw):
        calls.append((cmd, kw))
        host = cmd[-5]  # [ssh, -o..., host, bash, -s, --, run_name]
        if host == "dead-host":
            raise subprocess.TimeoutExpired(cmd, 10)
        if host == "err-host":
            raise OSError("ssh unavailable")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(land_rollup.subprocess, "run", fake_run)
    assert land_rollup.stop_remote(holder, rows) == 1
    assert [c[0][-5] for c in calls] == ["dead-host", "err-host", "live-host"]
    assert [c[0][-1] for c in calls] == ["land-1-111111", "land-1-222222", "land-1-333333"]
    cmd, kw = calls[2]
    assert cmd[:9] == ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                       "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2"]
    assert cmd[10:] == ["bash", "-s", "--", "land-1-333333"]
    assert kw["timeout"] == 10
    script = kw["input"].decode("utf-8")
    assert "\r" not in script  # Windows text=True would turn \n into \r\n and break remote bash
    assert '[ -d ~/rosy-test/runs/"$1".jobs ] || exit 0' in script
    assert 'kill -TERM -- "-$p"' in script
    for pat in ('~/rosy-jobs/"$1".lock', '~/rosy-jobs/"$1".*.lock', '~/rosy-jobs/"$1".resv'):
        assert pat in script


def test_roll_calls_stop_remote_only_for_stopped_members(repo, monkeypatch):
    main, snapshot = repo
    holder = land_rollup.land_async.holder(main)
    a, b = snapshot("fix/a", {"pkg/a.py": "x = 2\n"}), snapshot("fix/b", {"pkg/b.py": "y = 2\n"})
    old = snapshot("fix/land-rollup-20261109000000-20261109000000", {"pkg/r.py": "r = 1\n"})
    old.update(status="preparing", full_wait=True, ticket="t-old", pid=7)
    (holder / (old["branch"].replace("/", "-") + ".members")).write_text(json.dumps(
        [{"branch": m["branch"], "worktree": m["worktree"], "ticket": "gone"} for m in (a, b)]))
    (holder / (old["branch"].replace("/", "-") + ".log")).write_text(
        "[remote-pytest] deadbeef12 on model-pc (~/rosy-test/runs/land-1-old111)\n", encoding="utf-8")
    new = {**snapshot("fix/c", {"pkg/c.py": "z = 2\n"}), "status": "preparing", "full_wait": True,
           "ticket": "t-new", "pid": 8}
    (holder / (Path(new["worktree"]).name + ".log")).write_text(
        "[remote-pytest] cafe123456 on ai-pc (~/rosy-test/runs/land-1-new222)\n", encoding="utf-8")

    stopped, ssh_runs, events = [], [], []
    real_run = subprocess.run

    def fake_run(cmd, *args, **kw):
        if cmd and cmd[0] == "ssh":
            ssh_runs.append((cmd[-5], cmd[-1]))
            events.append("ssh")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real_run(cmd, *args, **kw)

    def fake_stop(pid):
        stopped.append(pid)
        events.append("stop")

    monkeypatch.setattr(land_rollup.subprocess, "run", fake_run)
    monkeypatch.setattr(land_rollup.socket, "gethostname", lambda: "h")
    monkeypatch.setattr(land_rollup, "plan", lambda repo_, rows, tier_of=None: rows)
    monkeypatch.setattr(land_rollup, "adopted", lambda qdir, first: True)
    monkeypatch.setattr(land_rollup, "stop", fake_stop)
    monkeypatch.setattr(land_rollup.land_queue, "ahead", lambda qdir, t: [old, new])

    # Partial merge: b clashed, so old keeps landing b and only new is stopped.
    monkeypatch.setattr(land_rollup, "build", lambda repo_, members, now, urgent="": (
        "land/fix/land-rollup-y", [m for m in members if m["branch"] != "land/fix/b"]))
    assert land_rollup.roll(main, holder.parent / "q", NOW, ["apply"]) == 0
    assert stopped == [8]
    assert ssh_runs == [("ai-pc", "land-1-new222")]
    assert events == ["ssh", "stop"]

    # Full merge: both old and new are stopped, and old's remote run is stopped once before stop(pid).
    stopped.clear()
    ssh_runs.clear()
    events.clear()
    monkeypatch.setattr(land_rollup, "build", lambda repo_, members, now, urgent="": (
        "land/fix/land-rollup-x", members))
    assert land_rollup.roll(main, holder.parent / "q", NOW, ["apply"]) == 0
    assert sorted(stopped) == [7, 8]
    assert ssh_runs == [("model-pc", "land-1-old111"), ("ai-pc", "land-1-new222")]
    assert events == ["ssh", "ssh", "stop", "stop"]

    # Unreachable SSH host never breaks roll().
    def failing_run(cmd, *args, **kw):
        if cmd and cmd[0] == "ssh":
            raise subprocess.TimeoutExpired(cmd, 10)
        return real_run(cmd, *args, **kw)

    monkeypatch.setattr(land_rollup.subprocess, "run", failing_run)
    assert land_rollup.roll(main, holder.parent / "q", NOW, ["apply"]) == 0


def test_candidates_deduplicate_topics_and_unrolled_keeps_carrier_ticket(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    holder = repo / ".git" / "rosy-land-wt"
    (holder / "r").mkdir(parents=True)
    (holder / "m1").mkdir()
    (holder / "m2").mkdir()
    (holder / "land-fix-land-rollup-20261116000000-20261116000000.members").write_text(json.dumps([
        {"branch": "land/fix/a-20261116000000", "worktree": str(holder / "m1"), "candidate": "c1", "ticket": "t-m1"},
        {"branch": "land/fix/b-20261116000000", "worktree": str(holder / "m2"), "candidate": "c2", "ticket": "t-m2"},
    ]))
    monkeypatch.setattr(land_rollup.socket, "gethostname", lambda: "h")
    monkeypatch.setattr(land_rollup.land_async, "holder", lambda r: holder)
    monkeypatch.setattr(land_rollup, "git", lambda tree, *a, **kw: subprocess.CompletedProcess(a, 0, "abc\n", ""))
    rows = [
        {"branch": "land/fix/x-20261116000000", "worktree": str(holder / "m1"), "status": "pending", "host": "h",
         "ticket": "t-old"},
        {"branch": "land/fix/x-20261116000001", "worktree": str(holder / "m2"), "status": "pending", "host": "h",
         "ticket": "t-new"},
        {"branch": "land/fix/land-rollup-20261116000000-20261116000000", "worktree": str(holder / "r"),
         "status": "pending", "host": "h", "ticket": "t-roll"},
    ]
    found = land_rollup.candidates(rows, repo, mixed=True)
    assert [r["branch"] for r in found] == [
        "land/fix/x-20261116000001", "land/fix/a-20261116000000", "land/fix/b-20261116000000"]
    assert found[1]["ticket"] == "t-roll" and found[1]["member_ticket"] == "t-m1"
    assert land_rollup.member_metadata(holder, found[1])["ticket"] == "t-m1"


def test_roll_prefers_affected_lane_and_ignores_nonpositive_pid(tmp_path, monkeypatch):
    land_rollup.stop(0)
    land_rollup.stop(-1)
    repo = tmp_path / "repo"
    holder = repo / ".git" / "rosy-land-wt"
    for name in ("a1", "a2", "f1"):
        (holder / name).mkdir(parents=True)
    rows = [
        {"branch": "land/fix/a1-20261116000001", "worktree": str(holder / "a1"), "status": "pending", "host": "h",
         "pid": 0, "ticket": "t1"},
        {"branch": "land/fix/f1-20261116000002", "worktree": str(holder / "f1"), "status": "pending", "host": "h",
         "pid": 100, "ticket": "t2"},
        {"branch": "land/fix/a2-20261116000003", "worktree": str(holder / "a2"), "status": "pending", "host": "h",
         "pid": 200, "ticket": "t3"},
    ]
    tiers = {rows[0]["branch"]: "affected", rows[1]["branch"]: "full", rows[2]["branch"]: "affected"}
    monkeypatch.setattr(land_rollup.socket, "gethostname", lambda: "h")
    monkeypatch.setattr(land_rollup.land_queue, "ahead", lambda q, t: rows)
    monkeypatch.setattr(land_rollup, "candidates", lambda r, p: r)
    seen = []

    def fake_plan(r, candidate_rows, tier_of=None):
        got = [row for row in candidate_rows if tier_of(r, row["branch"]) is not None]
        seen.append([row["branch"] for row in got])
        return got

    monkeypatch.setattr(land_rollup, "plan", fake_plan)
    monkeypatch.setattr(land_rollup, "tier", lambda r, b: tiers[b])
    monkeypatch.setattr(land_rollup, "affected", lambda r, b: "affected" if tiers[b] == "affected" else None)
    monkeypatch.setattr(land_rollup, "MIXED", True)
    assert land_rollup.roll(repo, holder.parent / "q", NOW, []) == 0
    assert seen == [[rows[0]["branch"], rows[2]["branch"]]]


def test_build_adopts_unrolled_carrier_ticket_while_preserving_member_ticket(repo, monkeypatch):
    main, snapshot = repo
    holder = land_rollup.land_async.holder(main)
    qdir = land_rollup.land_queue.queue_dir(main)
    qdir.mkdir(parents=True, exist_ok=True)
    carrier = qdir / "01794700-1.json"
    carrier.write_text(json.dumps({"pid": 1}), encoding="utf-8")
    a = snapshot("fix/a", {"pkg/a.py": "x = 2\n"})
    b = snapshot("fix/b", {"pkg/b.py": "y = 2\n"})
    old = snapshot("fix/land-rollup-20261116000000-20261116000000", {"pkg/r.py": "r = 1\n"})
    old.update(status="preparing", full_wait=True, ticket=carrier.name, pid=7)
    (holder / (old["branch"].replace("/", "-") + ".members")).write_text(json.dumps([
        {"branch": a["branch"], "worktree": a["worktree"], "ticket": "t-m1"},
        {"branch": b["branch"], "worktree": b["worktree"], "ticket": "t-m2"},
    ]))
    c = {**snapshot("fix/c", {"pkg/c.py": "z = 2\n"}), "status": "preparing", "full_wait": True,
         "ticket": "t-new", "pid": 8}
    monkeypatch.setattr(land_rollup.socket, "gethostname", lambda: "h")
    members = land_rollup.candidates([old, c], main, host="h", mixed=True)
    assert len(members) == 3 and members[0]["ticket"] == carrier.name and members[0]["member_ticket"] == "t-m1"
    monkeypatch.setattr(land_rollup.land, "safety_review", lambda *a, **kw: None)
    monkeypatch.setattr(land_rollup.land, "size_check", lambda *a, **kw: None)
    monkeypatch.setattr(land_rollup.land, "step", lambda *a, **kw: None)
    seen_env, log = [], holder / "land-rollup-test.log"

    def fake_start(wt, argv, now, detach):
        seen_env.append(land_rollup.os.environ.get(land_rollup.land_queue.TICKET_ENV))
        return "land/fix/land-rollup-next", log

    land_rollup.build(main, members, NOW, start=fake_start)
    assert seen_env == [str(carrier)]
    recorded = json.loads((log.parent / (log.name.removesuffix(".log") + ".members")).read_text(encoding="utf-8"))
    assert [m["ticket"] for m in recorded] == ["t-m1", "t-m2", "t-new"]



