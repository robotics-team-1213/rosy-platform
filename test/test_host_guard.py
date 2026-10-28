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
UNIT_DOWN = "60 5 1.2 24 7200 pinky-backend.service"
# D-883: then ~/rosy-test free_kb use%, / free_kb use%, GPU used total MiB
GIB = 2**20  # KiB per GiB
RAM = f"{32 * GIB} {16 * GIB} 12 48"  # MemTotal MemAvailable kB, CPU busy%, CPU temp C
NO_GPU = "- - - -"
DISK_OK = f"{HEALTHY} {200 * GIB} 40 {100 * GIB} 50 2048 24576 37 61 {RAM}"
DISK_FULL = f"{HEALTHY} {int(2.6 * GIB)} 100 {100 * GIB} 50 {NO_GPU} {RAM}"


def _recovery(role):
    return {"role": role, "time": 123, "state": "ok", "resources": {}, "issues": [],
            **{name: {"state": "ok"} for name in ("watchdog", "kernel", "ssh", "swap")}}


def _recovery(role):
    return {"role": role, "time": 123, "state": "ok", "resources": {}, "issues": [],
            **{name: {"state": "ok"} for name in ("watchdog", "kernel", "ssh", "swap")}}


def _guard(tmp_path, answer, *, runs=1, exit_code=0, conf="pc1 pc op@pc1 05:50-06:20\n", now="12:00",
           action_rc=0, env_extra=None, recovery_answer="null", updates_answer="null"):
    """Run the guard with a stub ssh that answers ``health`` and records every remote command.

    Any other command exits ``action_rc`` (a nonzero one also writes a refusal to stderr)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    calls = tmp_path / "calls"
    (bin_dir / "ssh").write_text(
        "#!/bin/sh\n"
        f'eval "last=\\${{$#}}"; echo "$last" >> {calls}\n'
        f"[ \"$last\" != recovery ] || {{ echo '{recovery_answer}'; exit 0; }}\n"
        f"[ \"$last\" != updates ] || {{ echo '{updates_answer}'; exit 0; }}\n"
        f'[ "$last" = health ] || {{ [ {action_rc} = 0 ] || echo "refused: $last" >&2; exit {action_rc}; }}\n'
        f"echo '{answer}'; exit {exit_code}\n")
    (bin_dir / "ssh").chmod(0o755)
    (tmp_path / "hosts.conf").write_text(conf)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "GUARD_STATE": str(tmp_path / "state"),
           "GUARD_CONFIG": str(tmp_path / "hosts.conf"), "GUARD_NOW": now,
           "GUARD_LOCAL_STATUS": str(tmp_path / "local-status.json"),
           # a test PC has the real forced command installed; never read its own headroom by accident
           "GUARD_LOCAL_HEALTH": str(tmp_path / "no-local-health"), **(env_extra or {})}
    for _ in range(runs):
        subprocess.run([sys.executable, str(GUARD)], env=env, check=True, capture_output=True, timeout=60)
    return [line for line in calls.read_text().splitlines() if line not in ("recovery", "updates")] if calls.exists() else []


def _actions(tmp_path):
    path = tmp_path / "state" / "actions.jsonl"
    return [json.loads(line)["action"] for line in path.read_text().splitlines()] if path.exists() else []


def test_a_healthy_pc_is_never_touched(tmp_path):
    assert _guard(tmp_path, HEALTHY, runs=5) == ["health"] * 5
    row = json.loads((tmp_path / "state/status.json").read_text())["pc1"]
    assert row["state"] == "ok"
    assert row["resources"] == {
        "avail_pct": 60, "swap_pct": 5, "load": 1.2, "cores": 24, "uptime_s": 7200, "down": [],
        # a six-field reply: disk and RAM size unknown, not healthy; the RAM warning still uses avail_pct
        "disk": None, "disk_low": None, "gpu": None, "memory": None, "memory_low": False, "cpu": None,
    }


def test_disk_and_gpu_headroom_are_recorded(tmp_path):
    assert _guard(tmp_path, DISK_OK) == ["health"]
    row = json.loads((tmp_path / "state/status.json").read_text())["pc1"]
    assert row["state"] == "ok" and row["resources"]["disk_low"] is False
    assert row["resources"]["disk"] == {"test_free_gb": 200.0, "test_use_pct": 40,
                                        "root_free_gb": 100.0, "root_use_pct": 50}
    assert row["resources"]["gpu"] == {"used_mib": 2048, "total_mib": 24576, "util_pct": 37, "temp_c": 61}
    assert row["resources"]["cpu"] == {"busy_pct": 12, "temp_c": 48}
    assert row["resources"]["memory"] == {"total_gb": 32.0, "avail_gb": 16.0}
    assert row["resources"]["memory_low"] is False


def test_low_ram_is_a_report_only_warning_before_the_memory_ladder(tmp_path):
    answer = f"8 10 1.2 24 7200 - {200 * GIB} 40 {100 * GIB} 50 {NO_GPU} {32 * GIB} {int(2.5 * GIB)} - -"
    assert _guard(tmp_path, answer, runs=7) == ["health"] * 7
    row = json.loads((tmp_path / "state/status.json").read_text())["pc1"]
    assert row["state"] == "memory-low" and row["bad"] == 0 and _actions(tmp_path) == []
    assert row["resources"]["memory"] == {"total_gb": 32.0, "avail_gb": 2.5}
    assert row["resources"]["cpu"] == {"busy_pct": None, "temp_c": None}  # unreadable, not zero


@pytest.mark.parametrize("answer", [DISK_FULL, f"{HEALTHY} {200 * GIB} 95 {100 * GIB} 50 {NO_GPU} {RAM}"])
def test_a_low_disk_never_restarts_or_reboots(tmp_path, answer):
    """2026-10-26: a 100% full AI PC; a reboot frees nothing. A PC outside the lab gets no cleaning."""
    assert _guard(tmp_path, answer, runs=7) == ["health"] * 7
    row = json.loads((tmp_path / "state/status.json").read_text())["pc1"]
    assert row["state"] == "disk-low" and row["bad"] == 0 and row["resources"]["disk_low"] is True
    assert row["resources"]["gpu"] is None and _actions(tmp_path) == []


@pytest.mark.parametrize("name", ["ai", "model"])
def test_a_low_lab_disk_gets_one_clean_request_per_gap(tmp_path, name):
    """D-885: ask the lab PC's rosy-ops storage service once, then wait GUARD_CLEAN_GAP_S."""
    conf = f"{name} pc op@{name} 05:50-06:20\n"
    assert _guard(tmp_path, DISK_FULL, runs=4, conf=conf) == ["health", "clean-storage"] + ["health"] * 3
    row = json.loads((tmp_path / "state/status.json").read_text())[name]
    assert row["state"] == "disk-low" and row["bad"] == 0 and row["last_clean_request"] > 0
    assert _actions(tmp_path) == ["clean-storage"]
    again = _guard(tmp_path, DISK_FULL, conf=conf, env_extra={"GUARD_CLEAN_GAP_S": "0"})
    assert again.count("clean-storage") == 2  # the stub's call log accumulates across runs


def test_a_refused_clean_request_waits_the_gap_and_never_reboots(tmp_path):
    calls = _guard(tmp_path, DISK_FULL, runs=5, conf="ai pc op@ai 05:50-06:20\n", action_rc=2)
    assert calls == ["health", "clean-storage"] + ["health"] * 4
    assert _actions(tmp_path) == ["clean-storage refused"]


def test_a_healthy_lab_disk_is_never_cleaned(tmp_path):
    assert _guard(tmp_path, DISK_OK, runs=3, conf="ai pc op@ai 05:50-06:20\n") == ["health"] * 3


def test_a_low_disk_with_low_memory_keeps_the_memory_ladder(tmp_path):
    assert _guard(tmp_path, f"{LOW_MEMORY} {GIB} 99 {GIB} 99 {NO_GPU} {RAM}", runs=3) == ["health"] * 3 + ["reboot"]
    assert json.loads((tmp_path / "state/status.json").read_text())["pc1"]["resources"]["disk_low"] is True


@pytest.mark.parametrize("junk", ["", "{not json", "[1, 2]"])
def test_a_corrupt_state_file_does_not_stop_the_guard(tmp_path, junk):
    (tmp_path / "state").mkdir()
    (tmp_path / "state/status.json").write_text(junk)
    assert _guard(tmp_path, HEALTHY) == ["health"]
    assert json.loads((tmp_path / "state/status.json").read_text())["pc1"]["state"] == "ok"


def test_three_bad_answers_without_a_down_unit_reboot_once(tmp_path):
    assert _guard(tmp_path, LOW_MEMORY, runs=3) == ["health"] * 3 + ["reboot"]
    assert _actions(tmp_path) == ["reboot"]


def test_a_down_unit_is_restarted_first_then_the_pc_is_rebooted(tmp_path):
    calls = _guard(tmp_path, UNIT_DOWN, runs=6)
    assert calls == ["health"] * 3 + ["restart pinky-backend.service"] + ["health"] * 3 + ["reboot"]
    assert _actions(tmp_path) == ["restart pinky-backend.service", "reboot"]


def test_a_recovered_pc_resets_the_ladder(tmp_path):
    _guard(tmp_path, LOW_MEMORY, runs=2)
    _guard(tmp_path, HEALTHY, runs=1)
    assert "reboot" not in _guard(tmp_path, LOW_MEMORY, runs=2)


def test_high_load_alone_is_reported_never_acted_on(tmp_path):
    assert _guard(tmp_path, "50 10 120.0 24 7200 -", runs=6) == ["health"] * 6
    assert json.loads((tmp_path / "state/status.json").read_text())["pc1"]["state"] == "load-high"


def test_high_load_with_a_down_unit_still_counts(tmp_path):
    assert _guard(tmp_path, "50 10 120.0 24 7200 pinky-backend.service", runs=3)[-1] == "restart pinky-backend.service"


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
    assert calls == ["health"] * 3 + ["restart pinky-backend.service", "reboot"]
    assert _actions(tmp_path) == ["restart pinky-backend.service refused", "reboot refused"]


@pytest.mark.parametrize("reply", ["garbage", "60 5 1.2", "x 5 1.2 24 7200 -"])
def test_a_malformed_health_reply_does_not_stop_the_other_hosts(tmp_path, reply):
    conf = "bad pc op@bad 05:50-06:20\nshort\nrobot-x robot\nok pc op@ok 05:50-06:20\n"
    calls = _guard(tmp_path, reply, runs=2, conf=conf)
    status = _status(tmp_path)
    assert {status[n]["state"] for n in ("bad", "short", "robot-x", "ok")} == {"error"}
    assert calls.count("health") == 4 and _actions(tmp_path) == []


def test_a_pc_that_just_booted_is_not_rebooted(tmp_path):
    assert "reboot" not in _guard(tmp_path, "2 95 3.0 24 600 -", runs=4)


def test_an_unreachable_pc_is_only_logged(tmp_path):
    assert _guard(tmp_path, "", runs=4, exit_code=255) == ["health"] * 4
    assert _actions(tmp_path) == []
    assert _status(tmp_path)["pc1"]["resources"] is None


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


def _remote(tmp_path, command, units="pinky-backend.service\n", role=None):
    bin_dir = tmp_path / "rbin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in {"systemctl": 'echo "$*" >> "$CALLS"; case "$*" in *is-active*) exit 3;; esac',
                       "logger": "", "sudo": 'echo "sudo $*" >> "$CALLS"'}.items():
        (bin_dir / name).write_text(f"#!/bin/sh\n{body}\nexit 0\n")
        (bin_dir / name).chmod(0o755)
    if not (bin_dir / "nvidia-smi").exists():  # a GPU test PC must not put its real GPU in the reply
        (bin_dir / "nvidia-smi").write_text("#!/bin/sh\nexit 127\n")
        (bin_dir / "nvidia-smi").chmod(0o755)
    (tmp_path / "units").write_text(units)
    if role:
        (tmp_path / "role").write_text(role + "\n")
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "SSH_ORIGINAL_COMMAND": command,
           "GUARD_UNITS": str(tmp_path / "units"), "GUARD_ROLE_FILE": str(tmp_path / "role"),
           "GUARD_RECOVERY_STATUS": str(tmp_path / "recovery-status.json"), "CALLS": str(tmp_path / "rcalls")}
    result = subprocess.run(["sh", str(REMOTE)], env=env, capture_output=True, text=True, timeout=10)
    calls = (tmp_path / "rcalls").read_text().splitlines() if (tmp_path / "rcalls").exists() else []
    return result, calls


def test_the_forced_command_reports_down_units_in_health(tmp_path):
    result, _ = _remote(tmp_path, "health")
    fields = result.stdout.split()
    assert result.returncode == 0 and len(fields) == 18, result.stdout
    assert all(f.replace(".", "").isdigit() for f in fields[:5]) and fields[5] == "pinky-backend.service"
    assert all(f.isdigit() for f in fields[6:10]) and fields[10:14] == ["-", "-", "-", "-"]  # no GPU
    total, avail = int(fields[14]), int(fields[15])  # RAM kB from /proc/meminfo
    assert 0 < avail <= total and abs(int(fields[0]) - 100 * avail // total) <= 2  # two meminfo reads
    assert 0 <= int(fields[16]) <= 100  # CPU busy over one second of /proc/stat
    assert fields[17] == "-" or -40 <= int(fields[17]) <= 120  # a VM test PC may have no thermal zone


def test_the_forced_command_sums_gpu_memory_and_ignores_a_broken_driver(tmp_path):
    (tmp_path / "rbin").mkdir()
    gpu = tmp_path / "rbin" / "nvidia-smi"
    gpu.write_text("#!/bin/sh\nprintf '1000, 8000, 20, 71\\n500, 8000, 85, 64\\n'\n")
    gpu.chmod(0o755)
    assert _remote(tmp_path, "health")[0].stdout.split()[10:14] == ["1500", "16000", "85", "71"]
    gpu.write_text("#!/bin/sh\necho 'NVIDIA-SMI has failed'; exit 9\n")
    assert _remote(tmp_path, "health")[0].stdout.split()[10:14] == ["-", "-", "-", "-"]


def test_the_site_role_checks_system_units_and_others_user_units(tmp_path):
    _remote(tmp_path, "health")
    assert "--user is-active" in (tmp_path / "rcalls").read_text()
    (tmp_path / "rcalls").unlink()
    result, _ = _remote(tmp_path, "health", role="site")
    calls = (tmp_path / "rcalls").read_text()
    assert result.returncode == 0 and "--system is-active" in calls and "--user" not in calls


def test_the_forced_command_restarts_only_listed_user_units(tmp_path):
    result, calls = _remote(tmp_path, "restart pinky-backend.service")
    assert result.returncode == 0
    assert calls == ["sudo -n /usr/local/sbin/rosy-host-control restart-unit pinky-backend.service"]
    for i, bad in enumerate(("restart ssh.service", "restart pinky-backend.service extra", "restart *", "rm -rf /",
                             "reboot now", "health; reboot")):
        (tmp_path / str(i)).mkdir()
        result, calls = _remote(tmp_path / str(i), bad)
        assert result.returncode == 2, bad
        assert calls == [], bad


def test_the_forced_command_cleans_storage_only_through_the_d524_helper(tmp_path):
    result, calls = _remote(tmp_path, "clean-storage")
    assert result.returncode == 0 and calls == ["sudo -n /usr/local/sbin/rosy-host-control clean-storage"]
    (tmp_path / "x").mkdir()
    result, calls = _remote(tmp_path / "x", "clean-storage now")
    assert result.returncode == 2 and calls == []


def test_the_forced_command_reboots_only_through_the_d524_helper(tmp_path):
    result, calls = _remote(tmp_path, "reboot")
    assert result.returncode == 0 and calls == ["sudo -n /usr/local/sbin/rosy-host-control reboot"]


def test_recovery_is_read_only_and_does_not_expose_the_rest_of_the_report(tmp_path):
    recovery = {"time": 123, "role": "ai", "state": "degraded"}
    (tmp_path / "recovery-status.json").write_text(json.dumps({"recovery": recovery, "errors": ["private path"]}))
    result, calls = _remote(tmp_path, "recovery")
    assert result.returncode == 0 and json.loads(result.stdout) == recovery
    assert calls == []
    result, calls = _remote(tmp_path, "recovery extra")
    assert result.returncode == 2 and calls == []


@pytest.mark.parametrize("reply", ["null", "[]", "not-json", '{"role":"ai","state":"degraded"}'])
def test_recovery_collection_never_advances_the_reboot_ladder(tmp_path, reply):
    assert _guard(tmp_path, HEALTHY, recovery_answer=reply, runs=4) == ["health"] * 4
    assert _actions(tmp_path) == []
    assert _status(tmp_path)["pc1"]["state"] == "ok"


def test_unreachable_recovery_drops_previous_snapshot(tmp_path):
    report = json.dumps(_recovery("model"))
    _guard(tmp_path, HEALTHY, recovery_answer=report)
    assert _status(tmp_path)["pc1"]["recovery"]["role"] == "model"
    _guard(tmp_path, "", exit_code=255)
    assert _status(tmp_path)["pc1"]["recovery"] is None


def test_guard_collects_its_own_pc_and_removes_a_missing_local_report(tmp_path):
    report = {**_recovery("site"), "state": "degraded", "resources": {"load": 2}}
    path = tmp_path / "local-status.json"
    path.write_text(json.dumps({"recovery": report}))
    _guard(tmp_path, HEALTHY)
    assert _status(tmp_path)["site"]["recovery"] == report
    assert _status(tmp_path)["site"]["time"] == 123  # never renew the age of a cached result
    path.unlink()
    _guard(tmp_path, HEALTHY)
    assert "site" not in _status(tmp_path)


def test_the_site_pc_adds_its_own_headroom_from_the_same_forced_command(tmp_path):
    report = {**_recovery("site"), "resources": {"load": 2, "mem_total_bytes": 1}}
    (tmp_path / "local-status.json").write_text(json.dumps({"recovery": report}))
    health = tmp_path / "local-health"
    health.write_text(f'#!/bin/sh\n[ "$SSH_ORIGINAL_COMMAND" = health ] || exit 2\necho "{DISK_OK}"\n')
    health.chmod(0o755)
    _guard(tmp_path, HEALTHY, env_extra={"GUARD_LOCAL_HEALTH": str(health)})
    row = _status(tmp_path)["site"]
    assert row["resources"]["disk"]["test_free_gb"] == 200.0 and row["resources"]["cpu"]["temp_c"] == 48
    assert row["resources"]["mem_total_bytes"] == 1 and row["recovery"] == report  # recovery values kept
    health.write_text("#!/bin/sh\necho garbage\n")
    _guard(tmp_path, HEALTHY, env_extra={"GUARD_LOCAL_HEALTH": str(health)})
    assert _status(tmp_path)["site"]["resources"] == report["resources"]  # malformed: report values only


@pytest.mark.parametrize("change", [{"role": "ai"}, {"time": "now"}, {"watchdog": None}])
def test_misidentified_or_malformed_recovery_is_unavailable(tmp_path, change):
    report = json.dumps({**_recovery("model"), **change})
    _guard(tmp_path, HEALTHY, conf="model pc op@model -\n", recovery_answer=report)
    assert _status(tmp_path)["model"]["recovery"] is None


UPDATES = {"schema": "rosy.update-report/1", "time": 123, "gate": "open",
           "updaters": [{"unit": "rosy-omx-autoupdate.service", "timer": "enabled", "healthy_at": 120.0,
                         "last": {"step": "up_to_date", "release": "c47d7c3e78c9", "reason": None, "at": 120.0}}]}


def test_the_guard_keeps_each_pcs_update_report_without_touching_the_ladder(tmp_path):
    # D-871: collected beside health, never a reason to restart or reboot
    assert _guard(tmp_path, HEALTHY, updates_answer=json.dumps(UPDATES), runs=2) == ["health"] * 2
    assert _status(tmp_path)["pc1"]["updates"] == UPDATES and _actions(tmp_path) == []


@pytest.mark.parametrize("reply", ["null", "not-json", '{"schema": "other"}', '{"schema": "rosy.update-report/1"}'])
def test_a_missing_or_malformed_update_report_is_no_evidence(tmp_path, reply):
    _guard(tmp_path, HEALTHY, updates_answer=reply)
    assert _status(tmp_path)["pc1"]["updates"] is None and _status(tmp_path)["pc1"]["state"] == "ok"


def test_an_updates_line_only_reads_updates_and_is_rebuilt_every_run(tmp_path):
    calls = _guard(tmp_path, HEALTHY, conf="site updates robttt@localhost\n", updates_answer=json.dumps(UPDATES))
    assert calls == []  # no health, restart or reboot for the site PC's own user
    assert (tmp_path / "calls").read_text().splitlines() == ["updates"]
    assert _status(tmp_path)["site"] == {"source": "local", "updates": UPDATES}
    _guard(tmp_path, HEALTHY, conf="")
    assert "site" not in _status(tmp_path)


def test_the_forced_command_runs_only_the_update_report_for_updates(tmp_path, monkeypatch):
    report = tmp_path / "report.py"
    report.write_text('print(\'{"schema": "rosy.update-report/1"}\')\n')
    monkeypatch.setenv("GUARD_UPDATE_REPORT", str(report))
    result, calls = _remote(tmp_path, "updates")
    assert result.returncode == 0 and json.loads(result.stdout) == {"schema": "rosy.update-report/1"}
    assert calls == []
    result, calls = _remote(tmp_path, "updates --all")
    assert result.returncode == 2 and calls == []
