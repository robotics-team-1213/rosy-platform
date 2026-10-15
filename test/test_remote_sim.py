"""tools/remote/remote_sim.py (D-571): sim candidates, D-568 placement, site PC excluded, job lock, cleanup order."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tarfile
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


def test_runs_are_capped_on_loopback_hold_a_job_lock_and_clean_up_only_this_run():
    assert "MemoryMax=" in rs.SIM and "CPUQuota=" in rs.SIM and "nice -n 10" in rs.SIM
    assert "ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST" in rs.SIM and "GZ_IP=127.0.0.1" in rs.SIM
    assert "ROS_DOMAIN_ID=$((1 + RANDOM % 19))" in rs.SIM  # Linux-safe 0-101, clear of robots and other sims
    # D-568 2: `<pid> sim <cores> <GB>`. The shell stays (no exec), so $$ is the lock's pid and its
    # trap cleans up on the host even when the laptop is gone.
    lock = 'echo "$$ sim $CPUS ${MEM%G}" > ~/rosy-jobs/"$NAME".lock'
    assert lock in rs.SIM and "exec " not in rs.SIM and rs.SIM.rstrip().endswith("wait $!")
    assert rs.SIM.index("trap cleanup EXIT") < rs.SIM.index(lock)
    assert 'systemctl --user stop "rosy-sim-$NAME.scope"' in rs.SIM and 'rm -f ~/rosy-jobs/"$NAME".lock' in rs.SIM
    assert 'rosy-sim-$1.scope' in rs.STOP and '~/rosy-jobs/"$1".lock' in rp.CLEANUP
    for script in (rs.SIM, rs.STOP, rs.DROP):
        assert "docker" not in script and "pkill" not in script and "kill " not in script
    # The pip deps and the build run inside the scope, the build with as many workers as the quota.
    assert rs.DEPS in rs.INNER and "pip install" not in rs.SIM and '--parallel-workers "$CPUS"' in rs.INNER
    assert "headless:=true" in rs.BENCHES["swarm_bench"] and "gazebo_gui:=false" in rs.BENCHES["map_v2_runner"]
    assert set(rs.PROFILES) == {"model", "ai"} and rs.PROFILES["ai"]["cpus"] < rs.PROFILES["model"]["cpus"]


def _fake_host(monkeypatch, fetch):
    """run_sim against no host: records ship, the run and every remote script, in order."""
    calls = []

    def remote(host, script, *args, **kw):
        calls.append(script)
        return subprocess.CompletedProcess([], *(fetch if script is rs.FETCH else (0, b"", b"")))

    monkeypatch.setattr(rp, "ship", lambda *a: calls.append("ship"))
    monkeypatch.setattr(rp, "remote", remote)
    monkeypatch.setattr(rs.subprocess, "run", lambda *a, **k: calls.append("run") or subprocess.CompletedProcess(
        [], 7, "bench \U0001F600\n".encode()))
    return calls


def test_the_scope_stops_before_the_fetch_and_outputs_go_only_after_a_good_fetch(monkeypatch, tmp_path, capsys):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo("./launch.txt")
        info.size = 2
        tar.addfile(info, io.BytesIO(b"ok"))
    calls = _fake_host(monkeypatch, (0, buf.getvalue(), b""))
    assert rs.run_sim("m@1", "model", "true", [], "a" * 40, tmp_path, tmp_path / "log", 1) == 7
    # No pick reservation: ship's reservation covers the window until the job lock (D-568 2).
    assert calls == ["ship", "run", rs.STOP, rs.FETCH, rs.DROP, rp.CLEANUP]
    assert (tmp_path / "log/out/launch.txt").read_text() == "ok"

    calls = _fake_host(monkeypatch, (1, b"partial", b"tar: ./launch.txt: file changed as we read it"))
    # A console that cannot encode the bench output must not stop the fetch.
    real, sys.stdout = sys.stdout, io.TextIOWrapper(io.BytesIO(), encoding="cp949")
    try:
        assert rs.run_sim("m@1", "model", "true", [], "a" * 40, tmp_path, tmp_path / "log2", 1) == 7
    finally:
        sys.stdout = real
    assert calls == ["ship", "run", rs.STOP, rs.FETCH, rp.CLEANUP]  # the outputs stay on the host
    err = capsys.readouterr().err
    assert "fetching outputs failed (exit 1)" in err and "file changed" in err and "kept on m@1" in err
    assert not (tmp_path / "log2/out").exists()


BASH = pytest.mark.skipif(shutil.which("bash") is None or shutil.which("flock") is None, reason="needs bash, flock")


def _bash(script, **env):
    return subprocess.run(["bash", "-c", script], env={**os.environ, **env}, capture_output=True, text=True,
                          timeout=60)


@BASH
@pytest.mark.parametrize("installer_rc", [0, 7])
def test_inner_installs_contracts_before_the_bench_and_stops_on_failure(tmp_path, installer_rc):
    installer = tmp_path / "deploy/robot/pinky_pro/image/install-motion-contracts.sh"
    installer.parent.mkdir(parents=True)
    installer.write_text('set -e\nexit_code=${INSTALLER_RC}\n[ "$exit_code" = 0 ] || exit "$exit_code"\n'
                         'site="$2/lib/python$(python3 -c \'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")\')/site-packages"\n'
                         'mkdir -p "$site"\necho "READY = True" > "$site/installed_contract_probe.py"\n')
    roots = tmp_path / "tools/harness/colcon_roots.py"
    roots.parent.mkdir(parents=True)
    roots.write_text('print(".")\n')
    out = tmp_path / "out"
    out.mkdir()
    # Substitute only external ROS/build/cache prerequisites; execute the install and bench wiring.
    profile = tmp_path / "contracts/foundation/core_common/profile.py"
    profile.parent.mkdir(parents=True)
    profile.write_text('DEFAULT_ROBOT = "test_profile"\n')
    script = ('source() { :; }\ncolcon() {\n  echo "$*" > "$OUT/build-args.txt"\n}\ncd "$WORKSPACE"\n'
              + rs.INNER.replace(rs.DEPS, "")
              + '\n')
    result = _bash(script, WORKSPACE=str(tmp_path), OUT=str(out), PYDEPS=str(tmp_path / "deps"),
                   CPUS="1", INSTALLER_RC=str(installer_rc),
                   BENCH_CMD="python3 -c 'import installed_contract_probe as p; assert p.READY; print(\"BENCH_READY\")'")
    assert result.returncode == installer_rc, result.stderr
    assert ("BENCH_READY" in result.stdout) == (installer_rc == 0)
    assert "--packages-up-to gz_sim test_profile" in (out / "build-args.txt").read_text()


@BASH
def test_swarm_bench_waits_for_robots_yaml_instead_of_dying_on_the_first_look(tmp_path):
    """INNER runs benches under `set -eo pipefail`; a failed `ls | head` must not end the wait loop."""
    script = ('set -eo pipefail\nros2() { echo "ros2 $*"; }; sleep() { :; }; seq() { echo 1 2 3; }\n'
              + rs.BENCHES["swarm_bench"])
    made = tmp_path / "tmp" / "rosy_gz_multi_x"
    made.parent.mkdir()
    env = {"OUT": str(tmp_path), "TMPDIR": str(made.parent)}
    missing = _bash(script, **env)
    assert missing.returncode == 1 and "no robots.yaml after 180 s" in missing.stdout
    made.mkdir()
    (made / "robots.yaml").write_text("")
    found = _bash(script, **env)
    assert found.returncode == 0 and f"swarm_bench.py --robots {made / 'robots.yaml'} " in found.stdout


@BASH
def test_a_failed_pip_install_is_never_stamped_ok(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text('#!/bin/sh\nwhile [ $# -gt 1 ]; do [ "$1" = --target ] && mkdir -p "$2"; shift; done\n'
                  'exit "${UV_RC:-0}"\n')
    uv.chmod(0o755)
    deps = tmp_path / "deps" / "abc"
    deps.parent.mkdir()
    env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "PYDEPS": str(deps), "REQ": "req.txt"}
    script = "set -eo pipefail\n" + rs.DEPS + "echo built\n"
    failed = _bash(script, UV_RC="1", **env)
    assert failed.returncode == 1 and "CORE pip deps failed" in failed.stdout and "built" not in failed.stdout
    assert not deps.exists()
    assert _bash(script, **env).stdout == "built\n" and (deps / ".ok").is_file()


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
@pytest.mark.parametrize("name", ["DEPS", "INNER", "SIM", "FETCH", "STOP", "DROP"])
def test_remote_scripts_parse(name):
    assert subprocess.run(["bash", "-n"], input=getattr(rs, name).encode()).returncode == 0
