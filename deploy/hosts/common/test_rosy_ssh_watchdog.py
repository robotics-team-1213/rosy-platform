"""rosy-ssh-watchdog: only SSH failures climb to a guarded reboot; other checks never reboot."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("rosy-ssh-watchdog")
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="bash + /proc host script")


def run(tmp_path, *, ssh=False, ts_alive=True, route=True, ping=True, neigh=None,
        uptime=7200, core_active=False, env=None):
    """One watchdog run with stubbed system commands; returns (stdout, action lines)."""
    stubs = tmp_path / "bin"
    stubs.mkdir(exist_ok=True)
    calls = tmp_path / "calls"
    route_line = route if isinstance(route, str) else ("default via 192.0.2.1 dev wlan0" if route else "")
    for name, body in {
        "timeout": ('shift; if [ "$1" = bash ]; then ' + ("echo SSH-2.0-x" if ssh else "exit 1")
                    + '; elif [ "$1" = tailscale ]; then ' + ("exit 0" if ts_alive else "exit 1")
                    + '; else "$@"; fi'),
        "tailscale": "exit 0",
        "systemctl": (f'echo "$@" >> {calls}; '
                      'case "$1" in is-enabled) [ "$2" = ssh.socket ] && exit 1; exit 0;; '
                      f'is-active) exit {0 if core_active else 3};; esac; true'),
        "ip": (f'if [ "$1" = -4 ]; then echo "{route_line}"; '
               f'else {f"echo 192.0.2.1 dev wlan0 lladdr 00:00:5e:00:53:01 {neigh}" if neigh else "true"}; fi'),
        "ping": "exit 0" if ping else "exit 1",
        "awk": f'if [ "$#" -ge 2 ] && [ "$2" = /proc/uptime ]; then echo {uptime}; else exec /usr/bin/awk "$@"; fi',
    }.items():
        (stubs / name).write_text("#!/usr/bin/env bash\n" + body + "\n")
        (stubs / name).chmod(0o755)
    e = dict(os.environ, PATH=f"{stubs}:{os.environ['PATH']}",
             ROSY_SSH_WATCHDOG_STATE=str(tmp_path / "state"), **(env or {}))
    out = subprocess.run(["bash", str(SCRIPT)], env=e, capture_output=True, text=True, check=True).stdout
    acted = ([l for l in calls.read_text().splitlines() if l.split()[0] not in ("is-enabled", "is-active")]
             if calls.exists() else [])
    calls.unlink(missing_ok=True)
    return out, acted


ROBOT = {"ROSY_ROBOT": "1"}


def test_healthy_host_does_nothing(tmp_path):
    assert run(tmp_path, ssh=True)[1] == []


def test_ssh_ladder_then_guarded_reboot(tmp_path):
    steps = [run(tmp_path)[1] for _ in range(3)]
    assert steps == [["restart ssh"], ["restart NetworkManager", "restart ssh"], ["reboot"]]
    # A second reboot within the hour is refused; ssh is restarted instead.
    assert run(tmp_path)[1] == ["restart ssh"]


def test_reboots_are_capped_until_ssh_recovers(tmp_path):
    env = {"REBOOT_MIN_GAP_S": "0"}
    reboots = sum(a == ["reboot"] for a in (run(tmp_path, env=env)[1] for _ in range(12)))
    assert reboots == 2
    run(tmp_path, ssh=True, env=env)            # a healthy run resets the cap
    assert ["reboot"] in [run(tmp_path, env=env)[1] for _ in range(3)]


def test_no_reboot_within_boot_grace(tmp_path):
    for _ in range(2):
        run(tmp_path, uptime=60)
    out, acted = run(tmp_path, uptime=60)
    assert acted == ["restart ssh"] and "boot grace" in out


def test_tailscale_and_gateway_never_reboot_and_back_off(tmp_path):
    acts = [run(tmp_path, ssh=True, ts_alive=False, ping=False)[1] for _ in range(10)]
    assert all("reboot" not in a for a in acts)
    assert [i for i, a in enumerate(acts) if "restart tailscaled" in a] == [0, 5]
    assert [i for i, a in enumerate(acts) if "restart NetworkManager" in a] == [2, 5, 8]


def test_no_default_route_link_route_or_icmp_drop_is_healthy(tmp_path):
    assert run(tmp_path, ssh=True, route=False)[1] == []
    assert run(tmp_path, ssh=True, route="default dev wg0 scope link")[1] == []
    for _ in range(3):
        assert run(tmp_path, ssh=True, ping=False, neigh="REACHABLE")[1] == []


def test_stale_neighbour_is_not_a_live_gateway(tmp_path):
    acts = [run(tmp_path, ssh=True, ping=False, neigh="STALE")[1] for _ in range(3)]
    assert acts[2] == ["restart NetworkManager"]


def test_robot_skips_network_manager_and_never_reboots_with_core_active(tmp_path):
    acts = [run(tmp_path, ping=False, core_active=True, env=ROBOT) for _ in range(5)]
    assert all("restart NetworkManager" not in a for _, a in acts)
    assert all("reboot" not in a for _, a in acts)
    assert "rosy-core active" in acts[-1][0]


def test_robot_reboots_when_core_is_down(tmp_path):
    steps = [run(tmp_path, env=ROBOT)[1] for _ in range(3)]
    assert steps[-1] == ["reboot"]


def test_dry_run_and_garbage_state_change_nothing(tmp_path):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "ssh_failures").write_text("x\n")
    run(tmp_path, env={"DRY_RUN": "1"})
    assert (tmp_path / "state" / "ssh_failures").read_text() == "x\n"
    assert run(tmp_path)[1] == ["restart ssh"]   # garbage reads as 0
