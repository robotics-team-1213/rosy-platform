"""tools/remote/remote_sim.py (D-571): probe parsing, readiness, load-aware placement, site PC excluded."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import remote_sim as rs  # noqa: E402

IDLE = {"cores": 24, "load": 1.0, "mem_kb": 12_000_000, "gpu": 3, "native": 1, "fleet": 0, "gz": 0, "heavy": 0}


def probe(**kw):
    return {**IDLE, **kw}


def test_probe_output_is_parsed_and_a_stale_nonce_is_rejected():
    text = "nonce=abc\ncores=24\nload=25.49\nmem_kb=1831128\ngpu=98\nnative=1\nfleet=0\ngz=1\nheavy=4\n"
    p = rs.parse_probe(text, "abc")
    assert p["cores"] == 24 and p["load"] == 25.49 and p["gpu"] == 98 and p["gz"] == 1
    assert rs.parse_probe(text, "other") is None
    # A host without nvidia-smi prints an empty gpu value.
    assert rs.parse_probe(text.replace("gpu=98", "gpu="), "abc")["gpu"] is None


def test_readiness_needs_the_native_stack():
    assert rs.placement(probe(native=0), "ai")[0] is False
    assert rs.placement(probe(), "model")[0] is True
    assert rs.placement(None, "model") == (False, 0.0, "unreachable or stale probe")


def test_busy_or_short_of_memory_hosts_are_refused():
    assert "busy" in rs.placement(probe(load=25.5), "model")[2]  # 2026-10-09 model PC
    assert "low memory" in rs.placement(probe(mem_kb=1_831_128), "model")[2]


def test_the_site_pc_is_production_only_and_never_a_candidate(monkeypatch):
    """User 2026-10-09: 관제 PC는 시뮬레이션에서 제외."""
    assert all("robttt" not in h and role != "site" for h, role in rs.hosts_from_env())
    monkeypatch.setenv("ROSY_SIM_HOSTS", "u@1=model robttt@100.82.51.8=site x@9=site")
    assert rs.hosts_from_env() == [("u@1", "model")]
    for want in ("site", "robttt@100.82.51.8"):
        with pytest.raises(SystemExit, match="production only"):
            rs.choose([("u@1", "model", None, (True, 1.0, "ok"))], want)
        with pytest.raises(SystemExit, match="production only"):
            rs.main(["--host", want, "--check"])
    # A host running Fleet is refused whatever it is called.
    assert rs.placement(probe(fleet=3), "model") == (False, 0.0, rs.PRODUCTION_REFUSAL)
    assert rs.PRODUCTION_REFUSAL in rs.table([])


def test_scores_prefer_free_capacity_and_penalise_running_sims_and_a_full_gpu():
    base = rs.placement(probe(), "model")[1]
    assert rs.placement(probe(gz=1), "model")[1] == pytest.approx(base - 1)
    assert rs.placement(probe(gpu=95), "model")[1] == pytest.approx(base - 1)
    assert rs.placement(probe(load=12.0), "model")[1] < base


def test_choose_takes_the_best_or_the_named_host_and_explains_a_refusal():
    rows = [("m@1", "model", None, (False, 0.0, "busy")), ("a@2", "ai", None, (True, 1.5, "ok"))]
    assert rs.choose(rows, None)[0] == "a@2"
    assert rs.choose(rows, "ai")[0] == "a@2"
    with pytest.raises(SystemExit, match="no host can take a sim"):
        rs.choose(rows, "model")
    with pytest.raises(SystemExit, match="not in ROSY_SIM_HOSTS"):
        rs.choose(rows, "x@9")


def test_hosts_come_from_env_with_roles(monkeypatch):
    monkeypatch.setenv("ROSY_SIM_HOSTS", "u@1=model v@2")
    assert rs.hosts_from_env() == [("u@1", "model"), ("v@2", "ai")]


def test_runs_are_capped_on_loopback_and_cleanup_touches_only_this_run():
    assert "MemoryMax=" in rs.SIM and "CPUQuota=" in rs.SIM and "nice -n 10" in rs.SIM
    assert "ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST" in rs.SIM and "GZ_IP=127.0.0.1" in rs.SIM
    assert "docker" not in rs.SIM and "docker" not in rs.STOP
    assert 'rosy-sim-$1.scope' in rs.STOP and "pkill" not in rs.STOP and "kill " not in rs.STOP
    assert "headless:=true" in rs.BENCHES["swarm_bench"] and "gazebo_gui:=false" in rs.BENCHES["map_v2_runner"]


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
@pytest.mark.parametrize("name", ["PROBE", "INNER", "SIM", "FETCH", "STOP"])
def test_remote_scripts_parse(name):
    assert subprocess.run(["bash", "-n"], input=getattr(rs, name).encode()).returncode == 0
