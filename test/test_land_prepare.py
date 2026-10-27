"""land_prepare: the pretest beside its guard round, and the size ratchet previewed while waiting."""

from __future__ import annotations

import json
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
    monkeypatch.setattr(land.land_prepare, "after_reboot", lambda ticket: None)
    monkeypatch.setattr(land.land_guards, "first", lambda *a, **k: [])
    monkeypatch.setattr(land, "run_tests", lambda *a, **k: [])
    return main, wt, base, candidate, path, original


def test_affected_overtime_preserves_full_origin_and_final_publisher_eligibility(full_anchor, monkeypatch):
    """A passing delta must not replace the FULL proof its eventual landing and publisher consume."""
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
    assert green_full(main, landed)


def test_again_retains_original_full_base_when_main_moves_during_preparation(full_anchor, monkeypatch):
    main, wt, base, candidate, path, original = full_anchor
    args = land.argparse.Namespace(tests="auto", no_cache=False, queue_timeout=0)

    def check(*a, **k):
        commit(main, {"lib/later.py": "later = 2\n"}, "main moves during affected checks")
        return []

    monkeypatch.setattr(land, "run_tests", check)
    monkeypatch.setattr(land.land_queue, "wait", lambda *a, **k: None)
    restored = land.land_prepare.again(land, wt, "feat/x", args, sys.executable, None, None,
                                       [["pkg/test"]], "")
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
