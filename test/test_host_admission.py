"""Several main workers per run, held to the host's room by JOB admission across runs (2026-10-28).

94 % of queued_s was a run's own jobs waiting behind its one worker per host (pytest_s p50 10 s, queued_s p50 379 s).
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import remote_job as rj  # noqa: E402
import work_queue as wq  # noqa: E402
import xdist_plan as xp  # noqa: E402
from test_remote_pytest import _job_env, _sh  # noqa: E402

LINUX = shutil.which("setsid") and shutil.which("flock") and sys.platform != "win32"
FULL = {"cores": 20.0, "mem": 22.0, "site": False, "light": False}


def test_a_full_host_gets_up_to_max_main_workers_and_each_job_sizes_xdist_from_its_share():
    rooms = {"a": dict(FULL), "small": {**FULL, "cores": 4.0, "mem": 3.0}, "light": {**FULL, "light": True}}
    plan = wq.workers(["a", "small", "light"], [["x"]] * 10, rooms)
    assert plan.count(("a", "any")) == wq.MAX_MAIN == 4 and rooms["a"]["share"] == 4
    assert plan.count(("small", "any")) == 1 and "share" not in rooms["small"]  # 3 GB: room for one more only
    assert plan.count(("light", "any")) == 1
    assert wq.workers(["b"], [["x"]] * 2, {"b": dict(FULL)}).count(("b", "any")) == 2, "never more than the jobs"
    words, extra, note = xp.plan(["pkg/test"], rooms["a"], [])
    assert words == ["ROSY_JOB_CORES=5"] and extra[:2] == ["-n", "5"] and "1/4 of the host" in note
    assert xp.plan(["pkg/test"], FULL, [])[0] == [f"ROSY_JOB_CORES={xp.MAX_WORKERS}"], "one worker: whole host"


def test_only_gazebo_isaac_and_alone_browser_chunks_ask_the_host_for_it_alone():
    """robot-08: serial (no -n) and alone on the host are different needs; an alone job empties a host."""
    serial = ["integrations/simulation/gazebo/test", "learning/envs/isaac/test", "tools"]
    alone = lambda inv: "ROSY_JOB_ALONE=1" in xp.plan(inv, FULL, serial)[0]  # noqa: E731
    assert alone(["integrations/simulation/gazebo/test/test_x.py"]) and alone(["learning/envs/isaac/test"])
    assert alone(["integrations"]), "a parent directory runs the gazebo suites too"
    assert alone(["ROSY_RUN_BROWSER_TESTS=1", "ROSY_BROWSER_ALONE=1", "a/test/test_b_browser.py"])
    assert not alone(["ROSY_JOB_CORES=6", "tools/collect_alone.py"]), "the isolation gate: serial, admitted normally"
    assert not alone(["ROSY_RUN_BROWSER_TESTS=1", "a/test/test_b_browser.py"]), "browser lanes run beside others"
    assert not alone(["pkg/test/test_a.py::test_one"]) and not alone(["pkg/test"])


HOLD = 'touch "$HOME/started.$$"; while [ ! -e "$HOME/release" ]; do sleep 0.05; done\n'


def _start(env, home, run, k, *words):
    (home / "rosy-test" / "runs" / run).mkdir(parents=True, exist_ok=True)
    started = _sh(rj.START, env, run, "d", "", str(k), "60", rj.JOB, *words, "x.py")
    assert started.returncode == 0, started.stderr


def _settled(home, expect, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and len(list(home.glob("started.*"))) < expect:
        time.sleep(0.1)
    time.sleep(6)  # more than one admission poll (5 s): nobody else gets in
    return len(list(home.glob("started.*")))


@pytest.mark.skipif(not LINUX, reason="Linux setsid/flock are required")
def test_two_runs_asking_four_each_start_only_the_five_the_host_has_room_for(tmp_path):
    """robot-08's condition: n_main is the most a run asks for; every job still passes the host's budget."""
    home, env = _job_env(tmp_path, HOLD)
    env = {**env, "ROSY_HOST_CORES": "5", "ROSY_HOST_GB": "64"}
    words = ("ROSY_JOB_RESERVE_CORES=1", "ROSY_JOB_RESERVE_GB=1")
    for run in ("r1", "r2"):
        for k in range(4):
            _start(env, home, run, k, *words)
    try:
        assert _settled(home, 5) == 5
        assert len(list((home / "rosy-jobs").glob("*.lock"))) == 5
    finally:
        (home / "release").touch()
    assert _settled(home, 8) == 8, "the waiting three start as room frees"


@pytest.mark.skipif(not LINUX, reason="Linux setsid/flock are required")
def test_an_alone_job_waits_for_the_host_to_empty_and_nothing_starts_beside_it(tmp_path):
    body = 'n=${@: -1}; touch "$HOME/started.$n.$$"; while [ ! -e "$HOME/release.$n" ]; do sleep 0.05; done\n'
    home, env = _job_env(tmp_path, body)  # the last pytest argument names the job
    for name in ("first", "alone", "later"):
        (home / "rosy-test" / "runs" / name).mkdir(parents=True)
    _sh(rj.START, env, "first", "d", "", "0", "60", rj.JOB, "first")
    deadline = time.monotonic() + 20
    while not list(home.glob("started.first.*")) and time.monotonic() < deadline:
        time.sleep(0.1)
    _sh(rj.START, env, "alone", "d", "", "0", "60", rj.JOB, "ROSY_JOB_ALONE=1", "alone")
    time.sleep(1)
    _sh(rj.START, env, "later", "d", "", "0", "60", rj.JOB, "later")  # would fit the budget, but alone waits
    try:
        time.sleep(7)
        assert not list(home.glob("started.alone.*")), "an alone job never starts beside another job"
        assert not list(home.glob("started.later.*")), "nothing starts while an alone job waits for the host"
        (home / "release.first").touch()
        time.sleep(7)
        assert list(home.glob("started.alone.*")) and not list(home.glob("started.later.*"))
        lock = (home / "rosy-jobs" / "alone.0.lock").read_text().split()
        assert lock[1] == "alone"
        (home / "release.alone").touch()
        time.sleep(7)
        assert list(home.glob("started.later.*"))
    finally:
        for name in ("first", "alone", "later"):
            (home / f"release.{name}").touch()
