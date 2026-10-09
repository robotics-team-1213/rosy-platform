"""D-530 site host guard: recovery ladder, quiet window, robots probe-only, forced command (deploy/site)."""

import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "deploy" / "site" / "rosy-host-guard"
REMOTE = ROOT / "deploy" / "hosts" / "common" / "rosy-host-guard-remote"

pytestmark = pytest.mark.skipif(shutil.which("sh") is None or os.name == "nt", reason="needs a POSIX shell")

HEALTHY = "60 5 1.2 24 7200 -"
LOW_MEMORY = "2 95 3.0 24 7200 -"
UNIT_DOWN = "60 5 1.2 24 7200 pinky-nav2.service"


def _guard(tmp_path, answer, *, runs=1, exit_code=0, conf="pc1 pc op@pc1 05:50-06:20\n", now="12:00",
           action_rc=0, env_extra=None):
    """Run the guard with a stub ssh that answers ``health`` and records every remote command.

    Any other command exits ``action_rc`` (a nonzero one also writes a refusal to stderr)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    calls = tmp_path / "calls"
    (bin_dir / "ssh").write_text(
        "#!/bin/sh\n"
        f'eval "last=\\${{$#}}"; echo "$last" >> {calls}\n'
        f'[ "$last" = health ] || {{ [ {action_rc} = 0 ] || echo "refused: $last" >&2; exit {action_rc}; }}\n'
        f"echo '{answer}'; exit {exit_code}\n")
    (bin_dir / "ssh").chmod(0o755)
    (tmp_path / "hosts.conf").write_text(conf)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "GUARD_STATE": str(tmp_path / "state"),
           "GUARD_CONFIG": str(tmp_path / "hosts.conf"), "GUARD_NOW": now, **(env_extra or {})}
    for _ in range(runs):
        subprocess.run([sys.executable, str(GUARD)], env=env, check=True, capture_output=True, timeout=60)
    return calls.read_text().splitlines() if calls.exists() else []


def _actions(tmp_path):
    path = tmp_path / "state" / "actions.jsonl"
    return [json.loads(line)["action"] for line in path.read_text().splitlines()] if path.exists() else []


def test_a_healthy_pc_is_never_touched(tmp_path):
    assert _guard(tmp_path, HEALTHY, runs=5) == ["health"] * 5
    assert json.loads((tmp_path / "state/status.json").read_text())["pc1"]["state"] == "ok"


def test_three_bad_answers_without_a_down_unit_reboot_once(tmp_path):
    assert _guard(tmp_path, LOW_MEMORY, runs=3) == ["health"] * 3 + ["reboot"]
    assert _actions(tmp_path) == ["reboot"]


def test_a_down_unit_is_restarted_first_then_the_pc_is_rebooted(tmp_path):
    calls = _guard(tmp_path, UNIT_DOWN, runs=6)
    assert calls == ["health"] * 3 + ["restart pinky-nav2.service"] + ["health"] * 3 + ["reboot"]
    assert _actions(tmp_path) == ["restart pinky-nav2.service", "reboot"]


def test_a_recovered_pc_resets_the_ladder(tmp_path):
    _guard(tmp_path, LOW_MEMORY, runs=2)
    _guard(tmp_path, HEALTHY, runs=1)
    assert "reboot" not in _guard(tmp_path, LOW_MEMORY, runs=2)


def test_high_load_alone_is_reported_never_acted_on(tmp_path):
    assert _guard(tmp_path, "50 10 120.0 24 7200 -", runs=6) == ["health"] * 6
    assert json.loads((tmp_path / "state/status.json").read_text())["pc1"]["state"] == "load-high"


def test_high_load_with_a_down_unit_still_counts(tmp_path):
    assert _guard(tmp_path, "50 10 120.0 24 7200 pinky-nav2.service", runs=3)[-1] == "restart pinky-nav2.service"


def _status(tmp_path):
    return json.loads((tmp_path / "state/status.json").read_text())


def test_reboots_stop_at_the_cap_until_a_healthy_check(tmp_path):
    env = {"GUARD_REBOOT_MIN_GAP_S": "0"}
    calls = _guard(tmp_path, LOW_MEMORY, runs=12, env_extra=env)
    assert calls.count("reboot") == 2 and _status(tmp_path)["pc1"]["reboots"] == 2
    _guard(tmp_path, HEALTHY)
    assert _status(tmp_path)["pc1"]["reboots"] == 0
    assert _guard(tmp_path, LOW_MEMORY, runs=3, env_extra=env)[-1] == "reboot"


def test_two_reboots_are_never_closer_than_the_persisted_gap(tmp_path):
    calls = _guard(tmp_path, LOW_MEMORY, runs=9)  # default gap 1 h: the second round must not reboot
    assert calls.count("reboot") == 1 and _status(tmp_path)["pc1"]["last_reboot"] > 0


def test_a_refused_reboot_is_logged_truthfully_and_the_ladder_does_not_reset(tmp_path):
    calls = _guard(tmp_path, LOW_MEMORY, runs=4, action_rc=3)
    assert calls == ["health"] * 3 + ["reboot"] + ["health", "reboot"]
    assert _actions(tmp_path) == ["reboot refused", "reboot refused"]
    entry = _status(tmp_path)["pc1"]
    assert entry["bad"] == 4 and entry.get("reboots", 0) == 0
    assert "rc=3" in (tmp_path / "state/actions.jsonl").read_text()


def test_a_refused_restart_falls_through_to_a_reboot(tmp_path):
    env = {"GUARD_REBOOT_MIN_GAP_S": "0"}
    calls = _guard(tmp_path, UNIT_DOWN, runs=3, action_rc=2, env_extra=env)
    assert calls == ["health"] * 3 + ["restart pinky-nav2.service", "reboot"]
    assert _actions(tmp_path) == ["restart pinky-nav2.service refused", "reboot refused"]


@pytest.mark.parametrize("reply", ["garbage", "60 5 1.2", "x 5 1.2 24 7200 -"])
def test_a_malformed_health_reply_does_not_stop_the_other_hosts(tmp_path, reply):
    conf = "bad pc op@bad 05:50-06:20\nshort\nrobot-x robot\nok pc op@ok 05:50-06:20\n"
    status = _status(tmp_path)
    assert {status[n]["state"] for n in ("bad", "short", "robot-x", "ok")} == {"error"}
    assert calls.count("health") == 4 and _actions(tmp_path) == []


def test_a_pc_that_just_booted_is_not_rebooted(tmp_path):
    assert "reboot" not in _guard(tmp_path, "2 95 3.0 24 600 -", runs=4)


def test_an_unreachable_pc_is_only_logged(tmp_path):
    assert _guard(tmp_path, "", runs=4, exit_code=255) == ["health"] * 4
    assert _actions(tmp_path) == []


@pytest.mark.parametrize("now,window", [("06:00", "05:50-06:20"), ("23:59", "23:50-00:20"), ("00:10", "23:50-00:20")])
def test_nothing_runs_inside_the_nightly_window(tmp_path, now, window):
    assert _guard(tmp_path, LOW_MEMORY, runs=4, conf=f"pc1 pc op@pc1 {window}\n", now=now) == []
    assert json.loads((tmp_path / "state/status.json").read_text())["pc1"]["state"] == "quiet"


def test_a_reboot_whose_ten_minute_delay_lands_in_the_window_is_held(tmp_path):
    calls = _guard(tmp_path, LOW_MEMORY, runs=4, now="05:45")
    assert calls == ["health"] * 4 and _actions(tmp_path) == []


def test_robots_are_probed_and_never_recovered(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        conf = f"up robot 127.0.0.1:{port}\ndown robot 127.0.0.1:1\n"
        assert _guard(tmp_path, LOW_MEMORY, runs=4, conf=conf) == []
    status = json.loads((tmp_path / "state/status.json").read_text())
    assert status["up"]["state"] == "ok" and status["down"]["state"] == "unreachable"
    assert _actions(tmp_path) == []


def _remote(tmp_path, command, units="pinky-nav2.service\n"):
    bin_dir = tmp_path / "rbin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in {"systemctl": 'echo "$*" >> "$CALLS"; case "$*" in *is-active*) exit 3;; esac',
                       "logger": "", "sudo": 'echo "sudo $*" >> "$CALLS"'}.items():
        (bin_dir / name).write_text(f"#!/bin/sh\n{body}\nexit 0\n")
        (bin_dir / name).chmod(0o755)
    (tmp_path / "units").write_text(units)
    if role:
        (tmp_path / "role").write_text(role + "\n")
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "SSH_ORIGINAL_COMMAND": command,
           "GUARD_UNITS": str(tmp_path / "units"), "GUARD_ROLE_FILE": str(tmp_path / "role"), "CALLS": str(tmp_path / "rcalls")}
    result = subprocess.run(["sh", str(REMOTE)], env=env, capture_output=True, text=True, timeout=10)
    calls = (tmp_path / "rcalls").read_text().splitlines() if (tmp_path / "rcalls").exists() else []
    return result, calls


def test_the_forced_command_reports_down_units_in_health(tmp_path):
    result, _ = _remote(tmp_path, "health")
    fields = result.stdout.split()
    assert result.returncode == 0 and len(fields) == 6
    assert all(f.replace(".", "").isdigit() for f in fields[:5]) and fields[5] == "pinky-nav2.service"


def test_the_site_role_checks_system_units_and_others_user_units(tmp_path):
    _remote(tmp_path, "health")
    assert "--user is-active" in (tmp_path / "rcalls").read_text()
    (tmp_path / "rcalls").unlink()
    result, _ = _remote(tmp_path, "health", role="site")
    calls = (tmp_path / "rcalls").read_text()
    assert result.returncode == 0 and "--system is-active" in calls and "--user" not in calls


def test_the_forced_command_restarts_only_listed_user_units(tmp_path):
    result, calls = _remote(tmp_path, "restart pinky-nav2.service")
    assert result.returncode == 0
    assert calls == ["sudo -n /usr/local/sbin/rosy-host-control restart-unit pinky-nav2.service"]
    for i, bad in enumerate(("restart ssh.service", "restart pinky-nav2.service extra", "restart *", "rm -rf /",
                             "reboot now", "health; reboot")):
        (tmp_path / str(i)).mkdir()
        result, calls = _remote(tmp_path / str(i), bad)
        assert result.returncode == 2, bad
        assert calls == [], bad


def test_the_forced_command_reboots_only_through_the_d524_helper(tmp_path):
    result, calls = _remote(tmp_path, "reboot")
    assert result.returncode == 0 and calls == ["sudo -n /usr/local/sbin/rosy-host-control reboot"]
