"""land_prepare: the pretest beside its guard round, and the size ratchet previewed while waiting."""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import land  # noqa: E402
from test_land import commit, git, repos  # noqa: E402,F401  (land.py's fixture repos)


# Fails only when the commit under test holds both growths, as when main and the branch grow one unit.
SIZE_BOTH = ("import subprocess, sys\n"
             "both = all(subprocess.run(['git', 'cat-file', '-e', f'{sys.argv[2]}:{p}']).returncode == 0\n"
             "           for p in ('mine.txt', 'peer.txt'))\n"
             "print('tools/x.py 601 > 600' if both else 'ok', file=sys.stderr)\nsys.exit(1 if both else 0)\n")


def test_pretest_guards_run_beside_the_selection_and_their_stop_still_stops(repos, monkeypatch):
    """2026-10-27: the guard round (with the isolation gate) took 150-870 s before every pretest could start."""
    main, wt = repos
    started = threading.Event()

    def guards(*args, **kwargs):
        assert started.wait(10), "the selection waited for the guard round"
        raise land.Stop("NEW failure in test/architecture")

    monkeypatch.setattr(land.land_guards, "first", guards)
    monkeypatch.setattr(land, "run_tests", lambda *a, **k: started.set() or [])
    monkeypatch.setattr(land.land_full, "save", lambda *a: pytest.fail("recorded a pretest whose guards failed"))
    with pytest.raises(land.Stop, match="test/architecture"):
        land.land_prepare.prepare(land, wt, "feat/x", land.argparse.Namespace(tests="auto"), sys.executable,
                                  None, None, [["pkg/test"]], "FULL tier (test)")


def test_waiting_landing_previews_the_size_ratchet_of_mains_merge(repos):
    """2026-10-26: main grew the unit during the wait; two landings stopped on size at their turns, 392 min in."""
    main, wt = repos
    commit(wt, {land.SIZE_RANGE: SIZE_BOTH, "mine.txt": "x\n"}, "branch grows the unit")
    check = land.land_prepare.watch(land, wt)
    assert check() is None
    commit(main, {"peer.txt": "y\n"}, "main grows it too")
    reason = check()
    assert reason and "fails the size ratchet" in reason and git(main, "rev-parse", "HEAD")[:10] in reason
    assert check() is None, "once per main"


def test_behavior_ownership_failure_is_checked_before_the_selected_tests(repos, monkeypatch, tmp_path):
    _, wt = repos
    guard = "test/test_behavior_test_ownership.py"
    commit(wt, {guard: "def test_ownership():\n    assert False\n"}, "invalid behavior test ownership")
    real, calls = land.remote_pytest.run, []
    monkeypatch.setattr(land.remote_pytest, "run", lambda inv, *a, **k: calls.append(inv) or real(inv, *a, **k))
    args = land.argparse.Namespace(tests="auto", node=False, no_cache=True)
    with pytest.raises(land.Stop, match="NEW failure"):
        land.land_guards.first(wt, args, [["pkg/test"]], tmp_path / "logs", "pre", land.run_tests)
    assert calls[0] == [[guard]]
    assert all("pkg/test" not in inv for batch in calls for inv in batch)


def test_a_landing_whose_test_hosts_give_up_leaves_a_stop(repos, monkeypatch):
    """2026-10-27: a venv-setup ssh timeout ended a landing with no stop event, invisible to land_stats."""
    main, wt = repos
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch")

    def gone(*a, **k):
        raise SystemExit("[remote-pytest] venv setup on h failed")
    monkeypatch.setattr(land, "run_tests", gone)
    with pytest.raises(SystemExit):
        land.main(["--tests", "auto"])
    events = [json.loads(line) for line in (main / ".git" / land.land_events.EVENTS).read_text(encoding="utf-8").splitlines()]
    assert [e["reason"] for e in events if e["event"] == "stop"] == ["[remote-pytest] venv setup on h failed"]


def test_a_lost_queue_ticket_leaves_a_stop_without_recreating_its_place(repos, monkeypatch):
    main, wt = repos
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch")
    before = git(main, "rev-parse", "HEAD")
    enter = land.land_queue.enter

    def lost(*args, **kwargs):
        qdir, ticket = enter(*args, **kwargs)
        ticket.unlink()
        return qdir, ticket

    monkeypatch.setattr(land.land_queue, "enter", lost)
    assert land.main(["--tests", "auto"]) == 1
    events = [json.loads(line) for line in (main / ".git" / land.land_events.EVENTS).read_text().splitlines()]
    assert any(e["event"] == "stop" and "ticket disappeared" in e["reason"] for e in events)
    assert git(main, "rev-parse", "HEAD") == before
    assert not list((main / ".git" / land.land_queue.QUEUE).glob("*.json"))


@pytest.fixture
def full_anchor(repos, monkeypatch):
    main, wt = repos
    base = git(main, "rev-parse", "HEAD")
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch before FULL")
    candidate = git(wt, "rev-parse", "HEAD")
    land.land_full.save(wt, "feat/x", candidate, base, "full", [["pkg/test"]])
    path = main / ".git" / land.land_full.RECORDS / "feat-x.json"
    original = path.read_bytes()
    commit(main, {"lib/peer.py": "peer = 1\n"}, "peer after FULL")
    git(wt, "merge", "--no-edit", "main")
    monkeypatch.setattr(land.land_mainred, "CARRIED", [])
    monkeypatch.setattr(land.land_guards, "first", lambda *a, **k: [])
    monkeypatch.setattr(land, "run_tests", lambda *a, **k: [])
    return main, wt, base, candidate, path, original


def test_affected_overtime_preserves_full_origin_without_minting_execution_proof(full_anchor, monkeypatch):
    """Preserve provenance, but mocked empty checks cannot establish canonical browser execution."""
    main, wt, base, candidate, path, original = full_anchor
    args = land.argparse.Namespace(tests="auto", no_cache=False)
    land.land_prepare.prepare(land, wt, "feat/x", args, sys.executable, None, None, [["pkg/test"]], "")
    assert path.read_bytes() == original
    assert land.land_full.restore(wt, "feat/x") == base

    selected = []

    def select(wt_, base_, python, head=None, landed=False):
        selected.append((base_, head))
        return [["pkg/test"]], None

    monkeypatch.setattr(land, "select", select)
    assert land.main(["--tests", "auto"]) == 0
    landed = git(main, "rev-parse", "HEAD")
    record = land.land_record.read(main, landed)
    assert record["tier"] == "full"
    assert record["prepared_candidate"] == candidate and record["prepared_on"] == base
    assert selected and all(start == base for start, _ in selected)
    from publish_main import green_full
    assert not green_full(main, landed)


def test_guard_overtime_prepares_outside_and_keeps_full_origin(full_anchor, monkeypatch):
    main, wt, base, candidate, _, _ = full_anchor
    guard_calls, prepared = [], []
    real_prepare = land.land_prepare.prepare

    def guard(wt_, args, invocations, logdir, round_no, run_tests, **kw):
        guard_calls.append(round_no)
        if len(guard_calls) == 1:
            raise land.Overtime("guard consumed the turn budget")
        return []

    def outside(*args, **kw):
        prepared.append(args[-2])
        return real_prepare(*args, **kw)

    monkeypatch.setattr(land.land_guards, "first", guard)
    monkeypatch.setattr(land.land_prepare, "prepare", outside)
    monkeypatch.setattr(land, "select", lambda *a, **k: ([["pkg/test"]], None))
    assert land.main(["--tests", "auto"]) == 0
    assert prepared == [[["pkg/test"]]] and "pre" in guard_calls
    record = land.land_record.read(main, git(main, "rev-parse", "HEAD"))
    assert record["tier"] == "full" and record["prepared_candidate"] == candidate and record["prepared_on"] == base


def test_fast_forward_requires_the_same_turn_ownership_after_all_checks(full_anchor, monkeypatch):
    main, _, _, _, _, _ = full_anchor
    before = git(main, "rev-parse", "HEAD")

    def lost_turn(*args, **kwargs):
        for ticket in land.land_queue._held:
            land.land_queue.set_status(ticket, "preparing")
        return []

    monkeypatch.setattr(land, "run_tests", lost_turn)
    monkeypatch.setattr(land, "select", lambda *a, **k: ([["pkg/test"]], None))
    assert land.main(["--tests", "auto"]) == 1
    assert git(main, "rev-parse", "HEAD") == before


@pytest.mark.parametrize("change", ["pid", "epoch", "missing_epoch"])
def test_overtime_does_not_reprepare_or_rewrite_another_turn(full_anchor, monkeypatch, change):
    main, _, _, _, _, _ = full_anchor
    before, prepared = git(main, "rev-parse", "HEAD"), []
    saved = {}

    def adopted(*args, **kwargs):
        ticket = land.land_queue._held[0]
        info = json.loads(ticket.read_text())
        fields = {"pid": os.getpid() + 1} if change == "pid" else {
            "turn_started": info["turn_started"] + 100 if change == "epoch" else None}
        land.land_queue.set_status(ticket, "turn", **fields)
        saved.update(ticket=ticket, contents=ticket.read_bytes())
        raise land.Overtime("an old check completed after ownership changed")

    def refuse_prepare(*args, **kwargs):
        prepared.append(args)
        raise land.Stop("must not prepare another owner's ticket")

    monkeypatch.setattr(land.land_guards, "first", adopted)
    monkeypatch.setattr(land.land_prepare, "again", refuse_prepare)
    monkeypatch.setattr(land, "select", lambda *a, **k: ([["pkg/test"]], None))
    assert land.main(["--tests", "auto"]) == 1
    assert not prepared, "the old owner entered preparation after losing its turn"
    # leave() preserves a ticket adopted by another PID; its complete record must remain untouched.
    if change == "pid":
        assert saved["ticket"].read_bytes() == saved["contents"]
    assert git(main, "rev-parse", "HEAD") == before


def test_again_retains_original_full_base_when_main_moves_during_preparation(full_anchor, monkeypatch):
    main, wt, base, candidate, path, original = full_anchor
    args = land.argparse.Namespace(tests="auto", no_cache=False, queue_timeout=0)

    def check(*a, **k):
        commit(main, {"lib/later.py": "later = 2\n"}, "main moves during affected checks")
        return []

    monkeypatch.setattr(land, "run_tests", check)
    monkeypatch.setattr(land.land_queue, "wait", lambda *a, **k: None)
    emitted = []
    monkeypatch.setattr(land.land_events, "emit", lambda event, **f: emitted.append(event))
    restored = land.land_prepare.again(land, wt, "feat/x", args, sys.executable, None, None,
                                       [["pkg/test"]], "")
    assert emitted[0] == "released", "the turn's lock ends where the work moves outside"
    assert restored == base and path.read_bytes() == original
    assert set(git(main, "diff", "--name-only", restored, "main").splitlines()) == {"lib/peer.py", "lib/later.py"}


@pytest.mark.parametrize("invalid", ["own_commit", "edited_merge", "carried", "no_cache",
                                   "prior_affected", "missing_invocations", "empty_invocations",
                                   "malformed_invocations"])
def test_affected_preparation_does_not_upgrade_unusable_full_evidence(full_anchor, invalid):
    main, wt, base, candidate, path, original = full_anchor
    if invalid == "own_commit":
        commit(wt, {"pkg/a.py": "x = 3\n"}, "implementation after FULL")
    elif invalid == "edited_merge":
        commit(main, {"lib/third.py": "third = 3\n"}, "another peer")
        git(wt, "merge", "--no-commit", "--no-ff", "main")
        commit(wt, {"pkg/a.py": "x = 4\n"}, "merge with an unsupported own edit")
    elif invalid == "carried":
        land.land_mainred.CARRIED.append(("pkg/test/test_a.py::test_a", base, "red", ("pkg/test",)))
    elif invalid in ("prior_affected", "missing_invocations", "empty_invocations", "malformed_invocations"):
        invocations = {"prior_affected": [["pkg/test"]], "missing_invocations": None,
                       "empty_invocations": [], "malformed_invocations": ["pkg/test"]}[invalid]
        land.land_full.save(wt, "feat/x", candidate, base,
                            "affected" if invalid == "prior_affected" else "full",
                            invocations)
    args = land.argparse.Namespace(tests="auto", no_cache=invalid == "no_cache")
    land.land_prepare.prepare(land, wt, "feat/x", args, sys.executable, None, None, [["pkg/test"]], "")
    record = json.loads(path.read_text())
    assert record["tier"] == ("carried" if invalid == "carried" else "affected")
    assert record["candidate"] == git(wt, "rev-parse", "HEAD")
    assert record["main"] == git(main, "rev-parse", "HEAD")


@pytest.mark.parametrize("failure", ["selection", "guard", "head_move"])
def test_failed_affected_reprepare_cannot_create_a_publishable_landing(full_anchor, monkeypatch, failure):
    main, wt, base, candidate, path, original = full_anchor
    args = land.argparse.Namespace(tests="auto", no_cache=False)

    def check(*a, **k):
        if failure == "head_move":
            commit(wt, {"pkg/a.py": "x = 5\n"}, "branch changed during checks")
        else:
            raise land.Stop("NEW affected failure")
        return []

    monkeypatch.setattr(land.land_guards if failure == "guard" else land,
                        "first" if failure == "guard" else "run_tests", check)
    with pytest.raises(land.Stop, match="NEW affected failure|HEAD changed"):
        land.land_prepare.prepare(land, wt, "feat/x", args, sys.executable, None, None, [["pkg/test"]], "")
    assert path.read_bytes() == original
    assert land.land_record.read(main, git(wt, "rev-parse", "HEAD")) is None
    if failure == "head_move":
        assert land.land_full.restore(wt, "feat/x") is None


@pytest.mark.parametrize("batch_size", [2, 4])
@pytest.mark.parametrize("busy_count", [0, 2])
def test_batch_leader_counts_own_carried_members_before_reserving_capacity(tmp_path, batch_size, busy_count):
    queue = land.land_queue
    for n in range(busy_count):
        queue.take(tmp_path, f"feat/busy-{n}", status="preparing")
    members = [f"feat/member-{n}" for n in range(batch_size - 1)]
    for branch in members:
        queue.take(tmp_path, branch, status="pending")
    leader = queue.take(tmp_path, "feat/leader", status="pending")
    queue.set_status(leader, "pending", batch=members)

    land.land_prepare.slot(tmp_path, leader,
                           sleep=lambda _: pytest.fail("own carried members reserved preparation slots"))

    assert json.loads(leader.read_text())["status"] == "preparing"
    assert json.loads(leader.read_text())["batch"] == members


@pytest.mark.parametrize("batch_size", [2, 4])
@pytest.mark.parametrize("older_status", ["pending", "preparing"])
def test_batch_leader_preserves_other_preparing_and_older_pending_claims(tmp_path, batch_size, older_status):
    queue = land.land_queue
    for n in range(land.land_prepare.MAX_PREPARING - 1):
        queue.take(tmp_path, f"feat/busy-{n}", status="preparing")
    older = queue.take(tmp_path, "feat/older", status=older_status)
    members = [f"feat/member-{n}" for n in range(batch_size - 1)]
    for branch in members:
        queue.take(tmp_path, branch, status="pending")
    leader = queue.take(tmp_path, "feat/leader", status="pending")
    queue.set_status(leader, "pending", batch=members)
    later = queue.take(tmp_path, "feat/later", status="pending")
    naps = []

    def release_older(seconds):
        naps.append(seconds)
        assert len(naps) == 1, "own carried members still consume capacity after a peer releases it"
        assert json.loads(leader.read_text())["status"] == "pending"
        older.unlink()

    land.land_prepare.slot(tmp_path, leader, sleep=release_older)

    assert len(naps) == 1
    assert json.loads(leader.read_text())["status"] == "preparing"
    assert json.loads(later.read_text())["status"] == "pending"


def test_a_pending_landing_continues_on_mains_new_landing_code_with_its_own_ticket(tmp_path, monkeypatch):
    """2026-10-31: queue fixes never reached landers already waiting; they deadlocked until restarted by hand."""
    prep, queue, q = land.land_prepare, land.land_queue, tmp_path / ".git" / "rosy-land-queue"
    busy = [queue.take(q, f"feat/p{n}", status="preparing") for n in range(prep.MAX_PREPARING)]
    mine = queue.take(q, "feat/mine", status="pending")
    monkeypatch.setattr(prep, "STARTED", "old rules")
    seen = []

    def run(argv, env):
        seen.append((argv, env))
        return 7

    monkeypatch.setattr(prep, "rules", lambda: "old rules")
    assert prep.relaunch(land, q, mine, run) is None and not seen, "same rules: carry on"
    monkeypatch.setattr(prep, "rules", lambda: "new rules")
    with pytest.raises(SystemExit) as stopped:
        prep.slot(q, mine, sleep=lambda s: pytest.fail("waited instead of relaunching"),
                  changed=lambda: prep.relaunch(land, q, mine, run))
    argv, env = seen[0]
    assert stopped.value.code == 7 and argv[3] == str(tmp_path / "tools" / "land.py")
    assert env[queue.TICKET_ENV] == str(mine) and env[land.land_checks.OWN_COPY] == "1"
    busy.pop().unlink()  # a free slot: the landing prepares on its own rules, never relaunching mid-pretest
    prep.slot(q, mine, changed=lambda: pytest.fail("relaunched with a slot free"))
    assert json.loads(mine.read_text())["status"] == "preparing"


@pytest.mark.parametrize("remote_tool", [False, True])
def test_repository_without_landing_entrypoint_has_no_rules_to_relaunch(repos, monkeypatch, remote_tool):
    main, wt = repos
    if remote_tool:
        commit(main, {"tools/remote/helper.py": "# unrelated remote tooling\n"}, "remote tool without a lander")
    prep, queue = land.land_prepare, land.land_queue
    assert prep.rules() is None, "missing landing code is unknown, not a changed runnable rule set"
    qdir = main / ".git" / queue.QUEUE
    mine = queue.take(qdir, "feat/x", str(wt))
    monkeypatch.setattr(prep, "STARTED", "rules from the importing repository")
    assert prep.relaunch(land, qdir, mine, lambda *a: pytest.fail("spawned a missing lander")) is None


def test_mains_land_py_adopts_the_parents_ticket(tmp_path, monkeypatch):
    queue = land.land_queue
    ahead = queue.take(tmp_path, "feat/ahead", status="waiting")
    mine = queue.take(tmp_path, "feat/mine", status="pending")
    queue.set_status(mine, "waiting", urgent="user request", batch_auto=True, batch=[], owner_note="keep")
    original = json.loads(mine.read_text())
    monkeypatch.setattr(queue, "queue_dir", lambda wt: tmp_path)
    monkeypatch.setattr(queue, "_held", [])
    monkeypatch.setenv(queue.TICKET_ENV, str(mine))
    qdir, ticket = queue.enter(tmp_path, "feat/mine", "preparing")
    assert ticket == mine and sorted(tmp_path.glob("[0-9]*.json")) == [ahead, mine], "same place, no new ticket"
    assert json.loads(mine.read_text())["status"] == "preparing" and queue.TICKET_ENV not in os.environ
    adopted = json.loads(mine.read_text())
    assert all(adopted[key] == original[key] for key in ("start", "urgent", "batch_auto", "batch", "owner_note"))


@pytest.mark.parametrize("blocked", [False, True])
@pytest.mark.parametrize("changed", [False, True])
def test_waiting_landing_refreshes_rules_before_its_turn(tmp_path, monkeypatch, blocked, changed):
    prep, queue, batch = land.land_prepare, land.land_queue, land.land_batch
    qdir = tmp_path / ".git" / queue.QUEUE
    peer = queue.take(qdir, "feat/peer", status="turn") if blocked else None
    mine = queue.take(qdir, "feat/mine", status="waiting", urgent="user request", batch_auto=True)
    original = json.loads(mine.read_text())
    monkeypatch.setattr(prep, "STARTED", "old")
    monkeypatch.setattr(prep, "rules", lambda: "new" if changed else "old")
    monkeypatch.setattr(prep, "watch", lambda *a: None)
    monkeypatch.setattr(batch, "group_of", lambda *a: None)
    monkeypatch.setattr(batch, "in_main", lambda *a: False)
    monkeypatch.setattr(land.land_full, "restore", lambda *a: "tested-main")
    calls, naps = [], []

    def child(argv, env):
        calls.append((argv, env))
        assert argv[3] == str(tmp_path / "tools" / "land.py")
        assert env[queue.TICKET_ENV] == str(mine) and env[land.land_checks.OWN_COPY] == "1"
        return land.argparse.Namespace(returncode=7)

    def release(seconds):
        naps.append(seconds)
        if peer:
            peer.unlink()

    wait = queue.wait
    monkeypatch.setattr(queue, "wait", lambda *a, **k: wait(*a, **k, sleep=release))
    monkeypatch.setattr(land.remote_pytest.remote_job, "step", child)
    args = land.argparse.Namespace(tests="full", queue_timeout=0)
    if changed:
        with pytest.raises(SystemExit) as stopped:
            batch.queue(land, tmp_path, "feat/mine", args, sys.executable, qdir, mine, tmp_path)
        assert stopped.value.code == 7 and len(calls) == 1 and not naps
        assert json.loads(mine.read_text())["status"] == "waiting", "old rules never grant the turn"
    else:
        assert batch.queue(land, tmp_path, "feat/mine", args, sys.executable, qdir, mine, tmp_path) is None
        assert not calls and len(naps) == int(blocked)
    current = json.loads(mine.read_text())
    assert all(current[key] == original[key] for key in ("start", "urgent", "batch_auto", "branch", "worktree"))
    assert sorted(qdir.glob("[0-9]*.json")) == ([peer, mine] if changed and blocked else [mine])


@pytest.mark.parametrize("leader", [False, True])
def test_rule_refresh_keeps_live_batches_on_their_loaded_rules(tmp_path, monkeypatch, leader):
    prep, queue = land.land_prepare, land.land_queue
    mine = queue.take(tmp_path, "feat/mine", status="waiting")
    if leader:
        queue.set_status(mine, "preparing", batch=["feat/member"])
    else:
        owner = queue.take(tmp_path, "feat/leader", status="preparing")
        queue.set_status(owner, "preparing", batch=["feat/mine"])
    monkeypatch.setattr(prep, "STARTED", "old")
    monkeypatch.setattr(prep, "rules", lambda: "new")
    assert prep.relaunch(land, tmp_path, mine, lambda *a: pytest.fail("a live batch was relaunched")) is None


def test_reprepare_wait_refreshes_rules_before_turn(tmp_path, monkeypatch):
    prep, queue = land.land_prepare, land.land_queue
    mine = queue.take(tmp_path, "feat/mine", status="preparing")
    monkeypatch.setattr(prep, "prepare", lambda *a: None)
    monkeypatch.setattr(prep, "watch", lambda *a: None)
    monkeypatch.setattr(prep, "relaunch", lambda *a: 9)
    monkeypatch.setattr(land.land_full, "restore", lambda *a: "tested-main")
    with pytest.raises(SystemExit) as stopped:
        prep.again(land, tmp_path, "feat/mine", land.argparse.Namespace(queue_timeout=0), sys.executable,
                   tmp_path, mine, [], "reprepare")
    assert stopped.value.code == 9


@pytest.mark.parametrize("main_moves,reds", [(True, 1), (True, 2), (False, 1)])
def test_a_main_red_stop_prepares_once_more_only_when_main_moved(repos, monkeypatch, main_moves, reds):
    """D-889 14, 11-01: a pretest on a 66 min old main stopped on a MAIN-RED test main had fixed meanwhile."""
    main, wt = repos
    merged = []
    monkeypatch.setattr(land.land_guards, "first", lambda *a, **k: [])
    monkeypatch.setattr(land.land_speculate, "prepare", lambda *a, **k: None)
    monkeypatch.setattr(land, "select", lambda *a, **k: ([["pkg/test"]], "FULL tier (test)"))

    def run(wt_, args, invocations, logdir, tag):
        merged.append(land.land_mainred.merged_main(wt_))
        if len(merged) == 1 and main_moves:
            commit(main, {"fixed.txt": "x\n"}, "main fixes its red test")
        if len(merged) <= reds:
            raise land.Stop("NEW failure in pkg/test; MAIN-RED: 1 of 1 NEW id(s) also fail on main")
        return []
    monkeypatch.setattr(land, "run_tests", run)
    args = land.argparse.Namespace(tests="auto", no_cache=True)
    if main_moves and reds == 1:
        land.land_prepare.prepare(land, wt, "feat/x", args, sys.executable, None, None)
        assert len(merged) == 2 and merged[1] == git(main, "rev-parse", "HEAD") != merged[0]
    else:
        with pytest.raises(land.Stop, match="MAIN-RED"):
            land.land_prepare.prepare(land, wt, "feat/x", args, sys.executable, None, None)
        assert len(merged) == (2 if main_moves else 1), "once more at most, and only on a moved main"


def test_a_delta_record_reports_the_tier_under_it_and_is_never_full(tmp_path, monkeypatch):
    """D-889 27: main's delta suites run before the turn extend the earlier tier; a land record must not call
    them FULL unless the tier under them was, and with no tier under them nothing qualifies."""
    record = tmp_path / "record.json"
    monkeypatch.setattr(land.land_full, "_path", lambda wt, branch: record)
    land.land_full.save(tmp_path, "b", "c" * 40, "m" * 40, "delta", [["mine/test"], ["fleet/test"]],
                        base_tier="affected")
    got = land.land_full.prepared(tmp_path, "b", "m" * 40)
    assert got["tier"] == "affected" and got["invocations"] == [["mine/test"], ["fleet/test"]]
    land.land_full.save(tmp_path, "b", "c" * 40, "m" * 40, "delta", [["fleet/test"]])
    assert land.land_full.prepared(tmp_path, "b", "m" * 40) is None
    assert json.loads(record.read_text(encoding="utf-8"))["tier"] == "delta"


def test_a_load_flaky_pretest_keeps_its_tier_and_hands_the_ids_to_the_turn(full_anchor, monkeypatch):
    """D-970 4: one LOAD-FLAKY id no longer voids the pretest; the record keeps it for the turn to rerun alone.
    An explicit FULL witness stays strict."""
    main, wt, base, candidate, path, original = full_anchor
    line = "pytest pkg/test ok (run-pre-1.txt), LOAD-FLAKY ['pkg/test/test_a.py::test_a']"
    monkeypatch.setattr(land, "run_tests", lambda *a, **k: [line])
    args = land.argparse.Namespace(tests="auto", no_cache=True)
    land.land_prepare.prepare(land, wt, "feat/x", args, sys.executable, None, None, [["pkg/test"]], "")
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["tier"] == "affected" and record["flaky"] == [["pkg/test/test_a.py::test_a"]]
    assert land.land_full.flaky(wt, "feat/x") == [["pkg/test/test_a.py::test_a"]]
