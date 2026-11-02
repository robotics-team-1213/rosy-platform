"""land.py --tests: a real landing always runs its selection (2026-10-27: a hand-picked --tests left main red)."""

from __future__ import annotations

import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import land  # noqa: E402
from test_land import commit, git, repos  # noqa: E402,F401  (land.py's fixture repos)
from test_land_selection import assert_full_plan, body_calls, full_case  # noqa: E402,F401


@pytest.mark.parametrize("first", [0, 1])
@pytest.mark.parametrize("urgent", [True, False])
def test_parallel_rounds_keep_priority_until_the_last_priority_scope_exits(tmp_path, monkeypatch, first, urgent):
    monkeypatch.delenv(land.TURN_ENV, raising=False)
    entered = [threading.Event(), threading.Event()]
    finish = [threading.Event(), threading.Event()]
    rounds = ["gpre", "pre"] if urgent else ["1", "pre"]
    observations = {}

    def checks(module, wt, args, inv, logs, round_no):
        i = rounds.index(round_no)
        observations[i] = land.os.environ.get(land.TURN_ENV)
        entered[i].set()
        assert finish[i].wait(10), "test did not release this round"
        return []

    monkeypatch.setattr(land.land_checks, "run_tests", checks)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = []
        try:
            for i, round_no in enumerate(rounds):
                futures.append(pool.submit(land.run_tests, tmp_path, SimpleNamespace(urgent="user" if urgent else ""),
                                           [], tmp_path, round_no))
                assert entered[i].wait(10)
            assert all(event.wait(10) for event in entered)
            assert observations == {0: "1", 1: "1"}
            finish[first].set()
            assert futures[first].result(timeout=10) == []
            assert land.os.environ.get(land.TURN_ENV) == ("1" if urgent or first == 1 else "")
        finally:
            for event in finish:
                event.set()
            for future in futures:
                future.result(timeout=10)
    assert land.os.environ.get(land.TURN_ENV) == ""


def test_nested_normal_prepare_and_exception_leave_the_outer_priority_intact(tmp_path, monkeypatch):
    monkeypatch.delenv(land.TURN_ENV, raising=False)

    def checks(module, wt, args, inv, logs, round_no):
        assert land.os.environ.get(land.TURN_ENV) == "1"
        if round_no == 1:
            with pytest.raises(land.Stop, match="inner"):
                land.run_tests(wt, SimpleNamespace(urgent=""), [], logs, "pre")
            assert land.os.environ.get(land.TURN_ENV) == "1"
            raise land.Stop("outer")
        raise land.Stop("inner")

    monkeypatch.setattr(land.land_checks, "run_tests", checks)
    with pytest.raises(land.Stop, match="outer"):
        land.run_tests(tmp_path, SimpleNamespace(urgent=""), [], tmp_path, 1)
    assert land.os.environ.get(land.TURN_ENV) == ""
    monkeypatch.setattr(land.land_checks, "run_tests", lambda *a: [land.os.environ.get(land.TURN_ENV)])
    assert land.run_tests(tmp_path, SimpleNamespace(urgent=""), [], tmp_path, "pre") == [""]


def test_literal_full_is_a_mode_without_the_fixture_override(full_case, monkeypatch):
    case = full_case
    monkeypatch.delenv(land.FIXTURE_ENV)
    assert land.main(["--tests", "full"]) == 0
    assert_full_plan(body_calls(case))
    record = land.land_record.read(case.main, git(case.main, "rev-parse", "HEAD"))
    assert record and record["tier"] == "full"


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
