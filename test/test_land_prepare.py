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
