"""tools/remote/remote_sim.py (D-571): sim candidates, D-568 placement, site PC excluded, job lock."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import remote_sim as rs  # noqa: E402

rp = rs.rp
IDLE = {"nproc": 24, "load1": 1.0, "avail_gb": 12.0, "total_gb": 15.0, "pytest": True, "sim": True,
        "busy": False, "lock_cores": 0, "lock_gb": 0, "site": False}


@pytest.fixture(autouse=True)
def lab(monkeypatch):
    """No private lab file, no leftover env, a fresh site set."""
    for name in ("ROSY_SIM_HOSTS", "ROSY_TEST_HOSTS", "ROSY_TEST_LOCAL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(rp, "_LAB", {})
    monkeypatch.setattr(rp, "DEFAULT_HOSTS", "")
    monkeypatch.setattr(rp, "SITE_HOST", "site@lab")
    monkeypatch.setattr(rp, "SITES", {"site@lab"})


def probes(monkeypatch, table):
    monkeypatch.setattr(rp, "probe", lambda host: None if table[host] is None else {**IDLE, **table[host]})


def test_hosts_come_from_env_then_the_lab_file_then_the_pytest_hosts(monkeypatch):
    monkeypatch.setattr(rp, "DEFAULT_HOSTS", "m@1 a@2 site@lab")
    assert rs.candidates() == [("m@1", "ai"), ("a@2", "ai")]  # no role: the shared-PC caps
    monkeypatch.setattr(rp, "_LAB", {"sim_hosts": ["m@1=model", "a@2=ai"]})
    assert rs.candidates() == [("m@1", "model"), ("a@2", "ai")]
    monkeypatch.setenv("ROSY_SIM_HOSTS", "u@1=model v@2")
    assert rs.candidates() == [("u@1", "model"), ("v@2", "ai")]
    assert rs.candidates("model") == [("u@1", "model")] and rs.candidates("v@2") == [("v@2", "ai")]
    with pytest.raises(SystemExit, match="not a sim host"):
        rs.candidates("x@9")


def test_the_site_pc_is_production_only_and_never_a_candidate(monkeypatch):
    """User 2026-10-09: 관제 PC는 시뮬레이션에서 제외."""
    monkeypatch.setenv("ROSY_SIM_HOSTS", "u@1=model site@lab x@9=site")
    assert rs.candidates() == [("u@1", "model")]
    for want in ("site", "site@lab"):
        with pytest.raises(SystemExit, match="production only"):
            rs.candidates(want)
        with pytest.raises(SystemExit, match="production only"):
            rs.main(["--host", want, "--check"])
    # A host carrying ~/rosy-jobs/site is dropped whatever it is called, even when nothing else fits.
    probes(monkeypatch, {"u@1": {"avail_gb": 1.0}, "alias@lan": {"site": True, "nproc": 64, "total_gb": 64.0,
                                                                  "avail_gb": 60.0}})
    assert rs.ranked([("u@1", "model"), ("alias@lan", "ai")]) == []


def test_placement_is_the_d568_sim_floor_with_locks_and_busy(monkeypatch):
    hosts = [("m@1", "model"), ("a@2", "ai")]
    probes(monkeypatch, {"m@1": {"avail_gb": 9.0}, "a@2": {}})
    assert rs.ranked(hosts) == ["a@2", "m@1"]  # most headroom first
    probes(monkeypatch, {"m@1": {"avail_gb": 1.8}, "a@2": {"lock_cores": 20}})  # 2026-10-09 model PC; a running sim
    assert rs.ranked(hosts) == []
    probes(monkeypatch, {"m@1": {"sim": False}, "a@2": {"busy": True}})
    assert rs.ranked(hosts) == []
    probes(monkeypatch, {"m@1": None, "a@2": {}})
    assert rs.ranked(hosts) == ["a@2"]


def test_check_runs_nothing_and_a_run_without_a_host_fails(monkeypatch):
    monkeypatch.setenv("ROSY_SIM_HOSTS", "m@1=model")
    probes(monkeypatch, {"m@1": {"avail_gb": 1.8}})
    monkeypatch.setattr(rs, "run_sim", lambda *a, **k: pytest.fail("ran"))
    assert rs.main(["--check"]) == 0
    with pytest.raises(SystemExit, match="no host can take a sim"):
        rs.main(["swarm_bench"])


def test_runs_are_capped_on_loopback_hold_a_job_lock_and_cleanup_touches_only_this_run():
    assert "MemoryMax=" in rs.SIM and "CPUQuota=" in rs.SIM and "nice -n 10" in rs.SIM
    assert "ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST" in rs.SIM and "GZ_IP=127.0.0.1" in rs.SIM
    # D-568 2: `<pid> sim <cores> <GB>` before exec, so the pid stays the run's.
    lock = 'echo "$$ sim $CPUS ${MEM%G}" > ~/rosy-jobs/"$NAME".lock'
    assert lock in rs.SIM and rs.SIM.index(lock) < rs.SIM.index("exec timeout")
    assert '~/rosy-jobs/"$1".lock' in rp.CLEANUP
    assert "docker" not in rs.SIM and "docker" not in rs.STOP
    assert 'rosy-sim-$1.scope' in rs.STOP and "pkill" not in rs.STOP and "kill " not in rs.STOP
    assert "headless:=true" in rs.BENCHES["swarm_bench"] and "gazebo_gui:=false" in rs.BENCHES["map_v2_runner"]
    assert set(rs.PROFILES) == {"model", "ai"} and rs.PROFILES["ai"]["cpus"] < rs.PROFILES["model"]["cpus"]


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
@pytest.mark.parametrize("name", ["INNER", "SIM", "FETCH", "STOP"])
def test_remote_scripts_parse(name):
    assert subprocess.run(["bash", "-n"], input=getattr(rs, name).encode()).returncode == 0
