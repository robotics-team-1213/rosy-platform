"""Landing gate speed (D-1037): a full pool and a draining queue are waited for, quick contract run, fail-fast order."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import host_probe  # noqa: E402
import remote_pytest as rp  # noqa: E402
from test_land import cached, commit, git, land, repos  # noqa: E402,F401
from test_land_async import NOW, _git, repo, tool  # noqa: E402,F401
import land_quick  # noqa: E402
import work_queue  # noqa: E402


@pytest.fixture(autouse=True)
def _full_flag_never_leaks(monkeypatch):
    """host_probe.FULL is module state: a leaked True makes other tests' empty placement wait 12 h on a real clock."""
    monkeypatch.setattr(host_probe, "FULL", False)


def test_a_full_but_reachable_pool_keeps_waiting_and_never_runs_locally(monkeypatch, tmp_path):
    monkeypatch.delenv("ROSY_TEST_LOCAL", raising=False)
    now, answers = [0.0], [[]] * 5 + [["a@1"]]

    def placed(cls="pytest", hosts=None, cores=0):
        monkeypatch.setattr(host_probe, "FULL", answers[0] == [])  # restored after the test: never leaks
        return answers.pop(0)

    monkeypatch.setattr(rp, "placed_hosts", placed)
    monkeypatch.setattr(rp, "capture", lambda *a, **kw: pytest.fail("pytest must not run on this machine"))
    monkeypatch.setattr(rp, "run_on", lambda host, inv, logs, sha, repo, label: [0] * len(inv))
    codes = rp.run([["test/x.py"]], [tmp_path / "1.txt"], repo=ROOT, wait=60, poll=30,
                   sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0])
    assert codes == [0] and now[0] > 60  # waited past the unreachable budget


def test_an_unreachable_pool_still_fails_after_the_wait(monkeypatch, tmp_path):
    monkeypatch.delenv("ROSY_TEST_LOCAL", raising=False)
    now = [0.0]

    def placed(cls="pytest", hosts=None, cores=0):
        monkeypatch.setattr(host_probe, "FULL", False)
        return []

    monkeypatch.setattr(rp, "placed_hosts", placed)
    with pytest.raises(SystemExit, match=r"no test host reachable \(D-584\)"):
        rp.run([["test/x.py"]], [tmp_path / "1.txt"], repo=ROOT, wait=60, poll=30,
               sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0])


@pytest.mark.parametrize("drains", [True, False])
def test_a_queue_that_keeps_draining_keeps_the_landing_waiting(repo, monkeypatch, drains):
    main, dev = repo
    snap, log = tool.start(dev, [], NOW, lambda *a: None)
    tree = log.parent / log.name.removesuffix(".log")
    now, runs = [0], []
    monkeypatch.setattr(tool.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(tool, "ROOM_WAIT_S", 10)
    sigs = iter([("1",), ("1",) if not drains else ("2",)] + [("2",)] * 5)
    monkeypatch.setattr(tool._queue(), "signature", lambda t: next(sigs))
    answers = iter([False, True])
    calls = []

    def fake_land(argv, cwd, stdout, stderr, **kw):
        runs.append(argv)
        if len(runs) == 1:
            stdout.write(f"[land] STOP: {tool.QUEUE_FULL} (12/12 tickets)\n")
            return 1
        _git(main, "merge", "-q", "--ff-only", snap)
        return 0

    def room(*args):
        calls.append(1)
        now[0] = 11  # the first wait window ran out; the renewed one sees room
        return next(answers)

    code = tool.supervise(tree, snap, [], run=fake_land, room=room)
    assert (code, len(runs)) == ((0, 2) if drains else (1, 1))


def test_after_a_fix_commit_only_the_failed_invocation_and_the_delta_rerun(cached):
    """land_cache ancestor reuse: the passed invocation stays reused, the failed one (never recorded) reruns."""
    wt, _, _ = cached
    commit(wt, {"tools/harness/affected_tests.py": ""}, "harness")
    ancestor = git(wt, "rev-parse", "HEAD")
    land.land_cache.record(wt, ancestor, git(wt, "rev-parse", "HEAD^{tree}"), "env1", ["pkg/test/test_a.py"], Path("log"))
    commit(wt, {"pkg/b.py": "y = 1\n"}, "the fix")
    args = land.argparse.Namespace(tests="auto", no_cache=False)
    done, todo, _ = land.land_cache.split(wt, args, [["pkg/test/test_a.py"], ["pkg/test/test_b.py"]],
                                          git(wt, "rev-parse", "HEAD"), sys.executable,
                                          lambda *a, **k: ([["pkg/test/test_b.py"]], None))
    assert todo == [["pkg/test/test_b.py"]] and len(done) == 1 and "test_a.py" in done[0]


def test_short_likely_failers_start_before_long_suites(tmp_path):
    rates = {("test/a.py",): 0.5, ("test/b.py",): 0.0}
    seen = {("test/a.py",): 20.0, ("test/b.py",): 20.0, ("test/long",): 900.0}
    key = lambda inv: work_queue.order(tmp_path, inv, seen)  # noqa: E731
    work_queue._fail_rates.cache_clear()
    events = tmp_path / ".git" / "rosy-land-events.jsonl"
    events.parent.mkdir()
    import json
    events.write_text("".join(json.dumps({"event": "tests", "argv": list(a), "verdict": v}) + "\n"
                              for a, r in rates.items() for v in (["new"] * int(r * 2) + ["pass"] * int((1 - r) * 2))),
                      encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    order = sorted([["test/long"], ["test/b.py"], ["test/a.py"]], key=key)
    assert order == [["test/a.py"], ["test/b.py"], ["test/long"]]


class _Land:
    class Stop(Exception):
        pass

    TURN_ENV = "X_TURN"
    os = __import__("os")

    def __init__(self, codes, verdict=(0, [], "")):
        self.codes, self._verdict, self.remote_pytest = codes, verdict, self
        self.land_checks = self
        self.CANCELLED = "CANCELLED"

    def out(self, wt, *a):
        return "HEAD"

    def tmp_dir(self, branch):
        return Path(self.tmp)

    def run(self, inv, logs, head, **kw):
        if isinstance(self.codes, BaseException):
            raise self.codes
        return self.codes

    def verdict(self, *a):
        return self._verdict


@pytest.mark.parametrize("codes, verdict, stops", [
    ([0], (0, [], ""), False),
    ([1], (1, [], "boom"), True),                   # a confirmed NEW failure stops before the ticket
    ([1], (1, ["flaky"], "load"), False),           # load-flaky is not a confirmed failure
    (SystemExit("no test host reachable"), None, False),  # no verdict: the real rounds wait for hosts
    (["CANCELLED"], None, False),
])
def test_quick_contract_stops_only_on_a_confirmed_new_failure(tmp_path, codes, verdict, stops):
    (tmp_path / "t.py").write_text("", encoding="utf-8")
    fake = _Land(codes, verdict)
    fake.tmp = str(tmp_path)
    if stops:
        with pytest.raises(_Land.Stop, match="quick contract"):
            land_quick.run(fake, tmp_path, "python", ("t.py",))
    else:
        land_quick.run(fake, tmp_path, "python", ("t.py",))
