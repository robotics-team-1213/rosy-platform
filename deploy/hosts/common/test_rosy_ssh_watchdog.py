"""rosy-ssh-watchdog ladder: restart ssh, tailscaled, NetworkManager, then reboot (guarded)."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("rosy-ssh-watchdog")
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="bash + /proc host script")


def run(tmp_path, *, ssh=False, gateway=True, uptime=7200, env=None):
    """One watchdog run with stubbed system commands; returns the action lines."""
    stubs = tmp_path / "bin"
    stubs.mkdir(exist_ok=True)
    calls = tmp_path / "calls"
    for name, body in {
        "timeout": f'shift; if [ "$1" = bash ]; then {"echo SSH-2.0-x" if ssh else "exit 1"}; else "$@"; fi',
        "tailscale": 'echo \'{"BackendState": "Running"}\'',
        "systemctl": f'echo "$@" >> {calls}; [ "$1" = is-enabled ] && exit 0; true',
        "ip": "echo 'default via 192.0.2.1 dev wlan0'",
        "ping": "exit 0" if gateway else "exit 1",
        "awk": f'if [ "$#" -ge 2 ] && [ "$2" = /proc/uptime ]; then echo {uptime}; else exec /usr/bin/awk "$@"; fi',
    }.items():
        (stubs / name).write_text("#!/usr/bin/env bash\n" + body + "\n")
        (stubs / name).chmod(0o755)
    e = dict(os.environ, PATH=f"{stubs}:{os.environ['PATH']}",
             ROSY_SSH_WATCHDOG_STATE=str(tmp_path / "state"), **(env or {}))
    out = subprocess.run(["bash", str(SCRIPT)], env=e, capture_output=True, text=True, check=True).stdout
    acted = [l for l in calls.read_text().splitlines() if not l.startswith("is-enabled")] if calls.exists() else []
    calls.unlink(missing_ok=True)
    return out, acted


def test_healthy_host_does_nothing(tmp_path):
    out, acted = run(tmp_path, ssh=True)
    assert acted == [] and "failed" not in out


def test_ladder_then_guarded_reboot(tmp_path):
    steps = [run(tmp_path)[1] for _ in range(4)]
    assert steps == [["restart ssh"], ["restart tailscaled"], ["restart NetworkManager"], ["reboot"]]
    # A second reboot within the hour is refused; ssh is restarted instead.
    run(tmp_path), run(tmp_path), run(tmp_path)
    assert run(tmp_path)[1] == ["restart ssh"]


def test_no_reboot_within_boot_grace(tmp_path):
    for _ in range(3):
        run(tmp_path, uptime=60)
    out, acted = run(tmp_path, uptime=60)
    assert acted == [] and "boot grace" in out


def test_recovery_resets_the_count(tmp_path):
    run(tmp_path)
    run(tmp_path, ssh=True)
    assert run(tmp_path)[1] == ["restart ssh"]


def test_robot_skips_gateway_and_network_manager(tmp_path):
    out, acted = run(tmp_path, ssh=True, gateway=False, env={"CHECK_GATEWAY": "0"})
    assert acted == []
    run(tmp_path, env={"CHECK_GATEWAY": "0"}), run(tmp_path, env={"CHECK_GATEWAY": "0"})
    assert run(tmp_path, env={"CHECK_GATEWAY": "0"})[1] == []  # step 3 is a no-op on robots
