"""land_batch: waiting landings behind a turn prepare and land as one batch, and go alone when it stops."""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import land  # noqa: E402
import land_batch  # noqa: E402
import land_queue as queue  # noqa: E402
from test_land import commit, git, repos  # noqa: E402,F401  (land.py's fixture repos)


def info(ticket: Path) -> dict:
    return json.loads(ticket.read_text(encoding="utf-8"))


def test_a_batch_leader_holds_its_members_wherever_it_stands_and_releases_them_when_cleared(tmp_path):
    leader, member, other = (queue.take(tmp_path, b, status="waiting") for b in ("feat/l", "feat/m", "feat/o"))
    queue.set_status(leader, "preparing", batch=["feat/m"])
    queue.set_status(member, "turn")  # even a member that would be first stays behind its leader
    queue.set_status(member, "waiting")
    assert [r["branch"] for r in queue.blockers(tmp_path, member)] == ["feat/l"]
    assert [r["branch"] for r in queue.blockers(tmp_path, other)] == ["feat/m"], "a preparing leader blocks no one else"
    queue.set_status(leader, "waiting", batch=[])
    assert info(leader)["batch"] == [] and info(leader)["status"] == "waiting"


def test_wait_ends_landed_once_the_branch_is_in_main_and_batch_when_it_leads_one(tmp_path):
    ahead, mine = queue.take(tmp_path, "feat/a", status="turn"), queue.take(tmp_path, "feat/b")
    naps: list[float] = []
    assert queue.wait(tmp_path, mine, 0, sleep=naps.append, done=lambda: len(naps) == 2) == "landed"
    seen = []
    assert queue.wait(tmp_path, mine, 0, sleep=naps.append, form=lambda rows: seen.append(rows) or True) == "batch"
    assert [r["branch"] for r in seen[0]] == ["feat/a"]
    ahead.unlink()
    assert queue.wait(tmp_path, mine, 0, form=lambda rows: pytest.fail("formed with no one ahead")) is None


def test_only_the_earliest_waiting_ticket_leads_and_only_with_enough_members(tmp_path, monkeypatch):
    monkeypatch.setattr(land_batch, "eligible", lambda land_, wt, row: row["branch"] != "feat/unprepared")
    monkeypatch.setattr(land_batch, "rate", lambda path: (0.25, 50))
    turn = queue.take(tmp_path, "feat/turn", status="turn")
    mine, unprepared = queue.take(tmp_path, "feat/mine", status="waiting"), queue.take(tmp_path, "feat/unprepared")
    queue.set_status(unprepared, "waiting")
    form, chosen, measured = land_batch.former(land, tmp_path, tmp_path, mine)
    assert not form([]), "the one other waiting ticket is not prepared"
    peer = queue.take(tmp_path, "feat/peer", status="waiting")
    form_peer, _, _ = land_batch.former(land, tmp_path, tmp_path, peer)
    assert not form_peer([]), "an earlier waiting ticket leads, not this one"
    assert form([]) and [r["branch"] for r in chosen] == ["feat/peer"] and measured == {"p": 0.25, "runs": 50}
    assert info(mine)["batch"] == ["feat/peer"] and info(mine)["status"] == "preparing"
    assert not form_peer([]), "one batch at a time"
    assert turn.exists()


def batch_repos(repos, tmp_path):
    main, wt = repos
    commit(wt, {"pkg/x.py": "x = 1\n"}, "leader")
    members = {}
    for name, files in (("feat/m", {"pkg/m.py": "m = 1\n"}), ("feat/c", {"pkg/a.py": "x = 3\n"})):
        path = tmp_path / name.replace("/", "-")
        git(main, "worktree", "add", "-q", str(path), "-b", name, "main")
        commit(path, files, name)
        members[name] = path
    commit(wt, {"pkg/a.py": "x = 2\n"}, "leader edits the line feat/c edits")
    rows = [{"branch": b, "worktree": str(p)} for b, p in members.items()]
    return main, wt, rows


def test_a_batch_lands_its_clean_members_in_one_fast_forward_and_leaves_a_conflicting_one_out(repos, tmp_path,
                                                                                               monkeypatch):
    main, wt, rows = batch_repos(repos, tmp_path)
    qdir, ticket = tmp_path / "q", queue.take(tmp_path / "q", "feat/x", status="preparing")
    calls = []
    monkeypatch.setattr(land, "select", lambda *a, **k: ([], None))
    monkeypatch.setattr(land_batch.land_prepare, "prepare", lambda land_, wt_, name, *a: calls.append(name))
    monkeypatch.setattr(land_batch.land_queue, "wait", lambda *a, **k: None)
    def rounds(args, wt_, name, main_co, *a):  # the ordinary rounds' fast-forward, without their tests
        git(main_co, "merge", "-q", "--ff-only", name)
        return 0
    monkeypatch.setattr(land, "rounds", rounds)
    code, took = land_batch.lead(land, wt, "feat/x", land.argparse.Namespace(queue_timeout=0), sys.executable, qdir,
                                 ticket, main, rows, {})
    assert code == 0 and took == ["feat/m"] and calls and calls[0].startswith("feat/x-batch")
    assert info(ticket)["batch"] == ["feat/m"], "the conflicting member was left out"
    for branch, landed in (("feat/x", True), ("feat/m", True), ("feat/c", False)):
        assert land_batch.in_main(land, wt, branch) is landed, branch
    assert git(wt, "rev-parse", "--abbrev-ref", "HEAD") == "feat/x" and git(wt, "rev-parse", "HEAD") == git(main, "rev-parse", "HEAD")
    assert not git(wt, "branch", "--list", "feat/x-batch*"), "a landed batch branch is deleted"


def test_a_stopped_batch_goes_back_to_the_untouched_leader_branch_and_clears_its_members(repos, tmp_path, monkeypatch):
    main, wt, rows = batch_repos(repos, tmp_path)
    before = git(wt, "rev-parse", "HEAD")
    qdir, ticket = tmp_path / "q", queue.take(tmp_path / "q", "feat/x", status="preparing")
    monkeypatch.setattr(land, "select", lambda *a, **k: ([], None))
    monkeypatch.setattr(land_batch.land_prepare, "prepare", lambda *a: (_ for _ in ()).throw(land.Stop("NEW failure")))
    assert land_batch.lead(land, wt, "feat/x", land.argparse.Namespace(queue_timeout=0), sys.executable, qdir,
                           ticket, main, rows, {}) == (None, ["feat/m"])
    assert git(wt, "rev-parse", "--abbrev-ref", "HEAD") == "feat/x" and git(wt, "rev-parse", "HEAD") == before
    assert git(wt, "branch", "--list", "feat/x-batch*"), "a stopped batch branch is kept for its log"
    assert not land_batch.in_main(land, wt, "feat/m")


def test_a_batch_that_selects_the_full_tier_goes_alone_before_any_pretest(repos, tmp_path, monkeypatch):
    main, wt, rows = batch_repos(repos, tmp_path)
    qdir, ticket = tmp_path / "q", queue.take(tmp_path / "q", "feat/x", status="preparing")
    monkeypatch.setattr(land, "select", lambda *a, **k: ([["test"]], "FULL tier (harness)"))
    monkeypatch.setattr(land_batch.land_prepare, "prepare", lambda *a: pytest.fail("prepared a FULL-class batch"))
    assert land_batch.lead(land, wt, "feat/x", land.argparse.Namespace(queue_timeout=0), sys.executable, qdir,
                           ticket, main, rows, {})[0] is None
    assert git(wt, "rev-parse", "--abbrev-ref", "HEAD") == "feat/x"


def test_eligible_wants_a_prepared_member_at_its_worktree_head(repos, tmp_path):
    main, wt, rows = batch_repos(repos, tmp_path)
    row = {**rows[0], "host": socket.gethostname(), "status": "waiting"}
    assert not land_batch.eligible(land, wt, row), "no prepared tier yet"
    member = Path(row["worktree"])
    land.land_full.save(member, "feat/m", git(member, "rev-parse", "HEAD"), git(main, "rev-parse", "HEAD"), "affected", [])
    assert land_batch.eligible(land, wt, row)
    land.land_full.save(member, "feat/m", git(member, "rev-parse", "HEAD"), git(main, "rev-parse", "HEAD"), "full", [])
    assert not land_batch.eligible(land, wt, row), "a FULL-class landing goes alone (D-889 6)"
    land.land_full.save(member, "feat/m", git(member, "rev-parse", "HEAD"), git(main, "rev-parse", "HEAD"), "affected", [])
    assert not land_batch.eligible(land, wt, {**row, "host": "elsewhere"})
    assert not land_batch.eligible(land, wt, {**row, "batch": ["feat/y"]}), "a leader is not a member"
    commit(main, {"tools/harness/platform_parts.yaml": "roots:\n  - path: pkg/m.py\n    concern: safety\n"}, "tag")
    assert land_batch.safety(land, wt, "feat/m") and not land_batch.safety(land, wt, "feat/x")
    assert not land_batch.eligible(land, wt, row), "a safety branch lands alone (D-889 3)"


@pytest.mark.parametrize("p, k", [(None, 2), (0.31, 2), (0.21, 2), (0.2, 3), (0.13, 3), (0.12, 4), (0.08, 4),
                                  (0.07, 6), (0.0, 6)])
def test_k_follows_the_rolling_new_rate_by_the_addendum_table(p, k):
    assert land_batch.kopt(p) == k


def test_the_rolling_new_rate_counts_runs_over_24_hours_widened_to_the_last_50(tmp_path):
    now, rows = 1_000_000.0, []
    for n in range(60):  # 60 runs, an hour apart; every third met a NEW in its pretest
        t = now - n * 3600
        rows.append({"t": t, "event": "tests", "pid": n, "branch": "b", "verdict": "new" if n % 3 == 0 else "pass"})
        rows.append({"t": t + 1, "event": "prepared" if n % 3 else "stop", "pid": n, "branch": "b"})
    rows.append({"t": now, "event": "tests", "pid": 999, "branch": "b", "verdict": "pass"})  # neither: not a run
    path = tmp_path / "events.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    p, runs = land_batch.rate(path, now=now + 2)
    assert runs == 50 and p == pytest.approx(17 / 50), "24 h hold 25 runs, so the last 50"
    assert land_batch.rate(tmp_path / "none.jsonl") == (None, 0)


def test_a_failed_batch_bisects_by_halving_until_the_leader_goes_alone(tmp_path, monkeypatch):
    qdir, ticket = tmp_path / "q", queue.take(tmp_path / "q", "feat/l", status="preparing")
    rows = [{"branch": f"feat/m{n}"} for n in range(5)]
    tries = []

    def lead(land_, wt, branch, args, python, qdir_, ticket_, main_co, members, measured):
        tries.append([r["branch"] for r in members])
        return None, [r["branch"] for r in members]
    waits = iter(["batch", None])
    monkeypatch.setattr(land_batch, "lead", lead)
    monkeypatch.setattr(land_batch, "safety", lambda *a: False)
    monkeypatch.setattr(land_batch, "affected", lambda *a: True)
    monkeypatch.setattr(land_batch.land_prepare, "watch", lambda *a: None)

    chosen: list = []

    def wait(*a, form=None, **k):  # the first wait forms a batch of six, the next one is the turn alone
        got = next(waits)
        if got == "batch":
            chosen[:] = rows
        return got
    monkeypatch.setattr(land_batch, "former", lambda *a: (lambda rows_: True, chosen, {}))
    monkeypatch.setattr(land_batch.land_queue, "wait", wait)
    args = land.argparse.Namespace(queue_timeout=0, tests="auto")
    assert land_batch.queue(land, tmp_path, "feat/l", args, sys.executable, qdir, ticket, tmp_path) is None
    assert tries == [[f"feat/m{n}" for n in range(5)], ["feat/m0", "feat/m1"], ["feat/m0"]], "6 -> 3 -> 2 -> alone"
    assert info(ticket)["batch"] == []
