"""A run placed on small hosts only moves to a lab PC once one has room (2026-11-04: 253 of 256 pretest jobs ran
serially on the site PC for 131 min while the AI PC sat idle)."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import remote_pytest as rp  # noqa: E402
import work_queue as wq  # noqa: E402

ROOM = {"site": {"site": True}, "light": {"light": True}, "ai": {"cores": 20, "mem": 20}}


def test_small_hosts_retire_once_a_lab_pc_is_placed():
    work, deferred, placements = wq.Work([0, 1, 2]), set(), [["site"], ["site", "ai"]]
    done = wq.upgrade_watch(work, [("site", "any")], ROOM, lambda: placements.pop(0) if placements else ["ai"],
                            deferred, every=0.01)
    deadline = time.monotonic() + 5
    while not deferred and time.monotonic() < deadline:
        time.sleep(0.01)
    done.set()
    assert deferred == {"site"}
    assert work.take(None, "site") is None and work.take_small(None, "site") is None
    assert work.take(None, "ai") == 0, "the rest stays queued for the lab PC"


def test_only_runs_on_small_hosts_watch():
    assert wq.small_only([("site", "any"), ("light", "any")], ROOM)
    assert not wq.small_only([("site", "any"), ("ai", "main")], ROOM)
    assert not wq.small_only([("unmeasured", "any")], ROOM), "no headroom entry: keep the one-host fast path"
    work = wq.Work([0])
    wq.upgrade_watch(work, [("ai", "main")], ROOM, lambda: pytest.fail("placed again"), set(), every=0.01)
    time.sleep(0.05)
    work.retired.add("old")
    wq.upgrade_watch(work, [("light", "any")], ROOM, lambda: ["light"], set(), every=0.01).set()
    assert work.retired == set(), "a new placement round starts with no retired host"


def test_site_wanted_rejects_lab_only_and_host_alone(monkeypatch):
    monkeypatch.setattr(wq, "HOST_ALONE", ("integrations/simulation/gazebo/test",))
    invs = [
        ["test/learning/perception/test_learning_workflow_pipeline_browser.py"],
        ["ROSY_JOB_ALONE=1", "test/test_g1_timing.py"],
        [wq.BROWSER_ENV, wq.ALONE_ENV, "test/test_b_browser.py"],
        ["integrations/simulation/gazebo/test"],
        ["test/test_normal.py"],
    ]
    site_pick = wq.wanted("any", invs, site=True)
    assert [site_pick(i) for i in range(len(invs))] == [False, False, False, False, True]
    lab_pick = wq.wanted("any", invs, site=False)
    assert lab_pick is None


def test_stranded_handles_mixed_lab_only_and_host_alone_on_site_only(capsys):
    invs = [
        ["test/learning/perception/test_learning_workflow_pipeline_browser.py"],
        ["ROSY_JOB_ALONE=1", "test/test_g1_timing.py"],
        [wq.BROWSER_ENV, wq.ALONE_ENV, "test/test_b_browser.py"],
        ["test/test_normal.py"],
    ]
    work = wq.Work([0, 1, 2])
    assert wq.stranded(work, invs, ["ai"], ROOM) is False
    assert list(work.todo) == [0, 1, 2]

    work_with_normal = wq.Work([0, 1, 3])
    assert wq.stranded(work_with_normal, invs, ["site"], ROOM) is False
    assert list(work_with_normal.todo) == [0, 1, 3]

    assert wq.stranded(work, invs, [], ROOM) is False
    assert wq.stranded(wq.Work([]), invs, ["site"], ROOM) is False

    assert wq.stranded(work, invs, ["site"], ROOM) is True
    assert list(work.todo) == []
    assert work.codes == {0: wq.LOST_EXIT, 1: wq.LOST_EXIT, 2: wq.LOST_EXIT}
    err = capsys.readouterr().err
    assert err.count("needs a lab PC") == 3


def test_small_first_and_site_run_on_pulls_smallest_first(monkeypatch, tmp_path):
    assert wq.small_first({"light": True}) is True
    assert wq.small_first({"site": True}) is True
    assert wq.small_first({"cores": 20, "mem": 20}) is False
    assert wq.small_first({}) is False
    assert wq.small_first(None) is False

    seen = []
    monkeypatch.setattr(rp, "HEADROOM", {"site@lab": {"cores": 4, "mem": 8, "site": True, "light": False}})
    monkeypatch.setattr(rp, "SITES", {"site@lab"})
    monkeypatch.setattr(rp, "ship", lambda *a, **kw: None)
    monkeypatch.setattr(rp, "deps", lambda repo, sha: ("d" * 16, []))
    monkeypatch.setattr(rp, "remote", lambda *a, **kw: subprocess.CompletedProcess([], 0, b"", b""))
    monkeypatch.setattr(rp.remote_job, "run", lambda h, name, k, log, job, inv, *a:
                        seen.append(inv) or log.write_bytes(b"") and 0)
    work = wq.Work([0, 1, 2])  # largest first: 0=big, 1=small, 2=host_alone
    invs = [["test/big.py"], ["test/small.py"], ["ROSY_JOB_ALONE=1", "test/alone.py"]]
    rp.run_on("site@lab", invs, [tmp_path / f"{i}.txt" for i in range(3)], "ab" * 20, tmp_path, None, work)
    assert [next(w for w in inv if w.startswith("test/")) for inv in seen] == ["test/small.py", "test/big.py"]
    assert list(work.todo) == [2]
