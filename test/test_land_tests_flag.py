"""land.py --tests: a real landing always runs its selection (2026-10-27: a hand-picked --tests left main red)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import land  # noqa: E402
from test_land import commit, git, repos  # noqa: E402,F401  (land.py's fixture repos)


def test_hand_picked_tests_run_on_top_of_the_selection(repos, monkeypatch):
    main, wt = repos
    monkeypatch.delenv(land.FIXTURE_ENV)
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch")
    ran = []
    monkeypatch.setattr(land, "run_tests", lambda wt_, args, inv, logdir, round_no: ran.extend(inv) or [])
    assert land.main(["--tests", "pkg/test/test_a.py -k a"]) == 0
    assert ["pkg/test"] in ran, "the selection still ran"
    assert ["pkg/test/test_a.py", "-k", "a"] in ran
    assert git(main, "rev-parse", "HEAD") == git(wt, "rev-parse", "HEAD")


def test_tests_none_needs_the_users_words_and_records_them(repos, monkeypatch, capsys):
    main, wt = repos
    monkeypatch.delenv(land.FIXTURE_ENV)
    commit(wt, {"pkg/a.py": "x = 2\n"}, "branch")
    before = git(main, "rev-parse", "HEAD")
    assert land.main(["--tests", "none"]) == 2
    assert "--skip-reason" in capsys.readouterr().err and git(main, "rev-parse", "HEAD") == before

    assert land.main(["--tests", "none", "--skip-reason", "user: merge only, test PCs are down"]) == 0
    events = [json.loads(line) for line in (main / ".git" / land.land_events.EVENTS).read_text(encoding="utf-8").splitlines()]
    assert [e["reason"] for e in events if e["event"] == "skip"] == ["user: merge only, test PCs are down"]
