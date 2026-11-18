"""A retry inherits earlier passes: argv follows the tree, each clean pass is kept when judged, stages are logged."""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import pytest

from test_land import cached, commit, git, land, repos  # noqa: F401  (land.py's fixtures)

import land_events  # noqa: E402
import work_queue  # noqa: E402

A, B = ["pkg/test"], ["pkg/test/test_a.py"]


@pytest.fixture
def events(monkeypatch):
    seen = []
    monkeypatch.setattr(land_events, "emit", lambda event, **fields: seen.append((event, fields)))
    return seen


def fake_run(monkeypatch, ran, *, die_on=None, code=0, text="1 passed in 0.1s\n"):
    def fake(invs, logs, sha="HEAD", repo=None, label=None, on_done=None, **kw):
        ran.append(invs)
        for inv, log in zip(invs, logs):
            Path(log).parent.mkdir(parents=True, exist_ok=True)
            Path(log).write_text(text, encoding="utf-8")
            if inv == die_on:
                raise RuntimeError("killed")  # a taskkill or a lost host mid-batch
            if on_done:
                on_done(inv, log, code)
        return [code] * len(invs)
    monkeypatch.setattr(land.remote_pytest, "run", fake)


def test_a_kill_keeps_the_pass_already_judged(cached, monkeypatch):
    wt, run, _ = cached
    ran = []
    fake_run(monkeypatch, ran, die_on=B)
    with pytest.raises(RuntimeError):
        run([A, B])
    assert [e["argv"] for e in land.land_cache.entries(wt)] == [A]
    git(wt, "commit", "-q", "--allow-empty", "-m", "same tree, new commit")  # the retry's re-merge
    fake_run(monkeypatch, ran)
    run([A, B])
    assert ran[-1] == [B], "same tree and env: the kept pass is reused, the killed one runs"
    monkeypatch.setattr(land.land_cache, "env_id", lambda wt_, sha: "env2")
    ran.clear()
    fake_run(monkeypatch, ran)
    run([A, B])
    assert ran == [[A, B]], "another env reuses nothing"


@pytest.mark.parametrize("code, text, verdict", [
    (None, "1 passed in 0.1s\n", None),                       # no exit code at hand: the post-loop decides
    (1, "7233 passed\n", None),                               # exit 1 without a FAILED line: needs its rerun
    (0, "1 passed in 0.1s\n", (True, False, "NEW")),          # NEW failure
    (0, "1 passed in 0.1s\n", (True, True, "LOAD-FLAKY")),    # flaky
])
def test_only_a_clean_pass_with_its_exit_code_is_kept_early(cached, monkeypatch, code, text, verdict):
    wt, run, _ = cached
    if verdict:
        monkeypatch.setattr(land.land_checks, "verdict", lambda *a, **k: verdict)
        monkeypatch.setattr(land.land_checks, "carry", lambda *a, **k: ([], ""))
    inner = []

    def fake(invs, logs, sha="HEAD", repo=None, label=None, on_done=None, **kw):
        if on_done is None:  # a rerun
            return [0]
        Path(logs[0]).parent.mkdir(parents=True, exist_ok=True)
        Path(logs[0]).write_text(text, encoding="utf-8")
        on_done(invs[0], logs[0], code)
        inner.append(land.land_cache.entries(wt))  # judged, the run not yet over
        return [code or 0]
    monkeypatch.setattr(land.remote_pytest, "run", fake)
    try:
        run([A])
    except land.Stop:
        pass
    assert inner == [[]]


def test_a_carried_failure_is_not_kept_early(cached, monkeypatch):
    wt, run, _ = cached
    monkeypatch.setattr(land.land_checks, "verdict", lambda *a, **k: (True, False, "NEW"))
    monkeypatch.setattr(land.land_checks, "carry", lambda *a, **k: (["x"], "main is red alike"))
    fake_run(monkeypatch, [])
    run([A])
    assert land.land_cache.entries(wt) == []


@pytest.mark.parametrize("same_env, same_tree, same_argv", list(itertools.product([True, False], repeat=3)))
def test_reuse_needs_the_same_env_tree_and_argv(repos, monkeypatch, same_env, same_tree, same_argv):
    main, wt = repos
    monkeypatch.setattr(land.land_cache, "env_id", lambda wt_, sha: "env1")
    head, tree = git(wt, "rev-parse", "HEAD"), git(wt, "rev-parse", "HEAD^{tree}")
    land.land_cache.record(wt, head, tree if same_tree else "0" * 40, "env1" if same_env else "env0",
                           A if same_argv else B, Path("log"))
    args = land.argparse.Namespace(tests="none", no_cache=False)
    reused, todo, _ = land.land_cache.split(wt, args, [A], head, sys.executable, None)
    assert len(reused) + len(todo) == 1
    assert bool(reused) == (same_env and same_tree and same_argv)


def test_split_without_history_ignores_what_the_last_runs_took(repos, monkeypatch):
    main, wt = repos
    invs = [A, ["pkg"]]
    cold = work_queue.split(wt, invs, seen={})
    monkeypatch.setattr(work_queue, "history", lambda repo: {tuple(i): 9e6 for i in invs})
    assert work_queue.split(wt, invs, seen={}) == cold
    assert sorted(p for inv in cold for p in inv) == sorted(p for inv in invs for p in inv)


def test_stage_events(cached, monkeypatch, events):
    wt, run, _ = cached
    land.land_cache.record(wt, "a" * 40, "b" * 40, "env0", A, Path("log"))  # an earlier row of A, other env
    fake_run(monkeypatch, [])
    run([A])
    names = [e for e, _ in events]
    assert names.index("round_start") < names.index("round_end")
    start = dict(events)["round_start"]
    assert start["todo"] == 1 and start["reused"] == 0 and start["tree"] == git(wt, "rev-parse", "HEAD^{tree}")
    assert dict(events)["reuse_miss"] == {"argv": A, "reason": "env"}


def test_admitted_is_said_once_at_the_first_preparing(tmp_path, events):
    ticket = tmp_path / "t1"
    ticket.write_text(json.dumps({"status": "pending"}), encoding="utf-8")
    for status in ("preparing", "waiting", "preparing"):
        land.land_queue.set_status(ticket, status)
    assert [e for e, _ in events] == ["admitted"]
