"""land_speculate: the turn's main-delta selection run before the turn on the predicted tree (D-889 addendum 3)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import land  # noqa: E402
import land_speculate as spec  # noqa: E402
from test_land import commit, git, repos  # noqa: E402,F401  (land.py's fixture repos)

SELECTED = [["pkg/test/test_a.py"], ["test/test_harness_contracts.py"]]


@pytest.fixture
def queued(repos, monkeypatch):
    """feat/x prepared FULL over base; feat/peer, ahead of it in the queue, waits with its own candidate."""
    main, wt = repos
    base = git(main, "rev-parse", "HEAD")
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch")
    land.land_full.save(wt, "feat/x", git(wt, "rev-parse", "HEAD"), base, "full", [["pkg/test"]])
    git(main, "checkout", "-q", "-b", "feat/peer")
    commit(main, {"lib/peer.py": "peer = 1\n"}, "peer")
    peer = git(main, "rev-parse", "HEAD")
    git(main, "checkout", "-q", "main")
    land.land_full.save(wt, "feat/peer", peer, base, "full", [["lib/test"]])
    qdir = land.land_queue.queue_dir(wt)
    land.land_queue.take(qdir, "feat/peer", "", "waiting")
    ticket = land.land_queue.take(qdir, "feat/x", "", "preparing")
    ran, escalations = [], []
    monkeypatch.setattr(spec, "_affected", lambda *a: {"escalations": list(escalations)})
    monkeypatch.setattr(land, "select", lambda wt_, base_, python, head=None, landed=False: (SELECTED, None))
    monkeypatch.setattr(land, "run_tests", lambda wt_, args, invs, logdir, round_no: ran.append(
        (round_no, git(wt_, "rev-parse", "HEAD^{tree}"))) or [])
    monkeypatch.setattr(land.land_guards, "first", lambda *a, **k: [])
    monkeypatch.setattr(land.land_mainred, "CARRIED", [])
    land.land_events.bind(wt, "feat/x")  # land.main binds; the direct calls below need it too
    return main, wt, base, peer, qdir, ticket, ran, escalations


def _prepare(wt, qdir, ticket):
    spec.prepare(land, wt, "feat/x", land.argparse.Namespace(tests="auto"), sys.executable, qdir, ticket)
    return json.loads(land.land_full._path(wt, "feat/x").read_text(encoding="utf-8")).get(spec.KEY)


def test_prepare_tests_the_predicted_tree_and_leaves_the_branch_as_it_was(queued):
    main, wt, base, peer, qdir, ticket, ran, _ = queued
    head = git(wt, "rev-parse", "HEAD")
    kept = _prepare(wt, qdir, ticket)
    assert kept["chain"] == [peer] and kept["base"] == base and kept["invocations"] == SELECTED
    assert ran == [("spec", kept["tree"])]
    assert git(wt, "rev-parse", "HEAD") == head and git(wt, "rev-parse", "--abbrev-ref", "HEAD") == "feat/x"
    assert not git(wt, "status", "--porcelain")


def test_the_branch_worktree_is_never_touched_even_when_the_speculative_run_raises(queued, monkeypatch):
    """2026-10-28: land.py trees were stopped with taskkill /F; a branch worktree must never be left detached."""
    main, wt, base, peer, qdir, ticket, ran, _ = queued
    head, holder = git(wt, "rev-parse", "HEAD"), main / ".git" / spec.HOLDER
    git(main, "worktree", "add", "-q", "--detach", str(holder / "feat-x"), base)  # a killed run's leftover

    def killed(wt_, *a):
        assert Path(wt_) != wt and git(wt, "rev-parse", "--abbrev-ref", "HEAD") == "feat/x"
        raise RuntimeError("killed mid-run")
    monkeypatch.setattr(land, "run_tests", killed)
    with pytest.raises(RuntimeError):
        _prepare(wt, qdir, ticket)
    assert git(wt, "rev-parse", "HEAD") == head and git(wt, "rev-parse", "--abbrev-ref", "HEAD") == "feat/x"
    assert not git(wt, "status", "--porcelain") and not (holder / "feat-x").exists()
    assert str(holder) not in git(main, "worktree", "list")


def test_a_held_turn_runs_the_root_part_and_lands_a_green_full_record(queued, monkeypatch):
    """Robot-45's rule 3: the record's base is the turn's main, an ancestor of the landed commit."""
    main, wt, base, peer, qdir, ticket, ran, _ = queued
    kept = _prepare(wt, qdir, ticket)
    for path in qdir.glob("*.json"):
        path.unlink()  # both tickets leave: the peer landed, this run takes its own
    git(main, "merge", "-q", "--ff-only", peer)
    commit(main, {"docs/logs.md": "## entry\n"}, "records only")  # a record difference still holds
    ran.clear()
    turn = []
    monkeypatch.setattr(land, "run_tests", lambda wt_, args, invs, logdir, round_no: turn.append(invs) or [])
    assert land.main(["--tests", "auto"]) == 0
    assert turn == [[["test/test_harness_contracts.py"]]], "only the root test/ part runs at a held turn"
    landed = git(main, "rev-parse", "HEAD")
    record = land.land_record.read(main, landed)
    assert record["tier"] == "full" and git(main, "merge-base", "--is-ancestor", record["base"], landed) == ""
    assert record["base"] == git(main, "rev-parse", "HEAD^2") and SELECTED[0] in record["invocations"]
    from publish_main import green_full
    assert green_full(main, landed)
    events = [json.loads(line) for line in (main / ".git" / land.land_events.EVENTS).read_text().splitlines()]
    assert [e["held"] for e in events if e["event"] == "speculation" and e["stage"] == "turn"] == [True]
    assert kept["chain"] == [peer]


def test_a_different_landing_breaks_the_prediction_and_the_turn_runs_main_delta(queued, monkeypatch):
    main, wt, base, peer, qdir, ticket, ran, _ = queued
    _prepare(wt, qdir, ticket)
    commit(main, {"lib/other.py": "other = 1\n"}, "someone else landed")
    git(wt, "merge", "-q", "--no-edit", "main")
    assert spec.held(land, wt, "feat/x", base, git(wt, "rev-parse", "HEAD")) is None
    events = [json.loads(line) for line in (main / ".git" / land.land_events.EVENTS).read_text().splitlines()]
    broke = [e for e in events if e["event"] == "speculation" and e["stage"] == "turn"]
    assert [(e["why"], e["missing"], e["outside"]) for e in broke] == [("tree", [peer], 1)]


@pytest.mark.parametrize("guard", [True, False])
def test_a_held_records_only_turn_without_root_tests_still_runs_the_guards(queued, monkeypatch, guard):
    """The root test/ guards read the records that differ: an empty set would land them untested."""
    main, wt, base, peer, qdir, ticket, ran, _ = queued
    if guard:
        commit(wt, {"test/test_harness_contracts.py": "def test_g():\n    pass\n"}, "a guard file")
        land.land_full.save(wt, "feat/x", git(wt, "rev-parse", "HEAD"), base, "full", [["pkg/test"]])
    monkeypatch.setattr(land, "select", lambda *a, **k: ([["pkg/test/test_a.py"]], None))
    _prepare(wt, qdir, ticket)
    git(main, "merge", "-q", "--ff-only", peer)
    commit(main, {"docs/logs.md": "## entry\n"}, "records only")
    git(wt, "merge", "-q", "--no-edit", "main")
    assert spec.held(land, wt, "feat/x", base, git(wt, "rev-parse", "HEAD")) == (
        [["test/test_harness_contracts.py"]] if guard else [])


@pytest.mark.parametrize("status, escalation, chained", [
    ("waiting", "", True),
    ("preparing", "", False),  # still preparing: it most likely lands after this one
    ("waiting", "pkg/x.py" + spec.SAFETY_TRIGGER, False),  # nobody stacks on a safety-path ticket
])
def test_the_chain_skips_preparing_tickets_and_stops_at_safety(queued, status, escalation, chained):
    main, wt, base, peer, qdir, ticket, ran, escalations = queued
    peer_ticket = sorted(qdir.glob("*.json"))[0]
    land.land_queue.set_status(peer_ticket, status)
    escalations.extend([escalation] if escalation else [])
    assert spec.chain(land, wt, sys.executable, qdir, ticket) == ([peer] if chained else [])
