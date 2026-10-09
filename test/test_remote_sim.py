"""tools/remote/remote_sim.py (D-571): probe parsing, readiness, load-aware placement, site protection."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import remote_sim as rs  # noqa: E402

IDLE = {"cores": 24, "load": 1.0, "mem_kb": 12_000_000, "gpu": 3, "native": 1, "docker": 0, "image": 0,
        "fleet": 0, "gz": 0, "heavy": 0}


def probe(**kw):
    return {**IDLE, **kw}


def test_probe_output_is_parsed_and_a_stale_nonce_is_rejected():
    text = ("nonce=abc\ncores=24\nload=25.49\nmem_kb=1831128\ngpu=98\nnative=1\ndocker=0\nimage=0\n"
            "fleet=0\ngz=1\nheavy=4\n")
    p = rs.parse_probe(text, "abc")
    assert p["cores"] == 24 and p["load"] == 25.49 and p["gpu"] == 98 and p["gz"] == 1
    assert rs.parse_probe(text, "other") is None
    # A host without nvidia-smi prints an empty gpu value.
    assert rs.parse_probe(text.replace("gpu=98", "gpu="), "abc")["gpu"] is None


def test_readiness_needs_a_native_stack_or_the_image():
    assert rs.placement(probe(native=0), "ai")[0] is None
    assert rs.placement(probe(native=0, docker=1, image=0), "ai")[0] is None
    assert rs.placement(probe(native=0, docker=1, image=1), "ai")[0] == "docker"
    assert rs.placement(probe(native=1, docker=1, image=1), "model")[0] == "native"
    assert rs.placement(None, "model") == (None, 0.0, "unreachable or stale probe")


def test_busy_or_short_of_memory_hosts_are_refused():
    assert "busy" in rs.placement(probe(load=25.5), "model")[2]  # 2026-10-09 model PC
    assert "low memory" in rs.placement(probe(mem_kb=1_831_128), "model")[2]


def test_the_site_pc_runs_only_the_container_and_only_while_fleet_is_idle():
    site = probe(cores=8, load=0.4, mem_kb=13_800_000, native=1, docker=1, image=1, fleet=3)
    assert rs.placement(site, "site")[0] == "docker"
    assert rs.placement({**site, "image": 0}, "site")[0] is None  # native stack is never used there
    assert "busy" in rs.placement({**site, "load": 3.0}, "site")[2]
    assert "low memory" in rs.placement({**site, "mem_kb": 7_000_000}, "site")[2]
    assert rs.placement({**site, "gz": 1}, "site")[0] is None
    # A host running Fleet gets site caps even when listed under another role.
    assert rs.profile_key(site, "model") == "site"
    assert rs.placement({**site, "load": 3.0}, "model")[0] is None


def test_scores_prefer_free_capacity_and_penalise_running_sims_and_a_full_gpu():
    base = rs.placement(probe(), "model")[1]
    assert rs.placement(probe(gz=1), "model")[1] == pytest.approx(base - 1)
    assert rs.placement(probe(gpu=95), "model")[1] == pytest.approx(base - 1)
    assert rs.placement(probe(load=12.0), "model")[1] < base
    site = probe(cores=8, load=0.2, mem_kb=13_800_000, native=0, docker=1, image=1, fleet=3)
    assert rs.placement(site, "site")[1] < base  # the production PC is the last resort


def test_choose_takes_the_best_or_the_named_host_and_explains_a_refusal():
    rows = [("m@1", "model", None, (None, 0.0, "busy")),
            ("a@2", "ai", None, ("docker", 1.5, "ok")),
            ("s@3", "site", None, ("docker", 0.5, "ok"))]
    assert rs.choose(rows, None)[0] == "a@2"
    assert rs.choose(rows, "site")[0] == "s@3"
    with pytest.raises(SystemExit, match="no host can take a sim"):
        rs.choose(rows, "model")
    with pytest.raises(SystemExit, match="not in ROSY_SIM_HOSTS"):
        rs.choose(rows, "x@9")


def test_hosts_come_from_env_with_roles(monkeypatch):
    monkeypatch.setenv("ROSY_SIM_HOSTS", "u@1=model v@2")
    assert rs.hosts_from_env() == [("u@1", "model"), ("v@2", "ai")]


def test_runs_stay_on_loopback_and_cleanup_touches_only_this_run():
    docker_run = rs.SIM.split("docker run", 1)[1]
    assert "--network none" in docker_run and " -p " not in docker_run and "--publish" not in docker_run
    assert "MemoryMax=" in rs.SIM and "CPUQuota=" in rs.SIM and "nice -n 10" in rs.SIM
    assert 'rosy-sim-$1.scope' in rs.STOP and 'docker rm -f "rosy-sim-$1"' in rs.STOP
    assert "pkill" not in rs.STOP and "kill " not in rs.STOP
    assert "headless:=true" in rs.BENCHES["swarm_bench"] and "gazebo_gui:=false" in rs.BENCHES["map_v2_runner"]


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
@pytest.mark.parametrize("name", ["PROBE", "INNER", "SIM", "FETCH", "STOP"])
def test_remote_scripts_parse(name):
    assert subprocess.run(["bash", "-n"], input=getattr(rs, name).encode()).returncode == 0
