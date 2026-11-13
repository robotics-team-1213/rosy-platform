"""D-530 site host guard: recovery ladder, quiet window, robots probe-only, forced command (deploy/site)."""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
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
        # D-1021: a `drift ...` command answers the file the test wrote, or nothing at all (ssh exit 255)
        f'case "$last" in drift*) [ -f {tmp_path}/drift-answer ] && {{ cat {tmp_path}/drift-answer; exit 0; }}; exit 255;; esac\n'
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


def _alerts(tmp_path, webhook="https://chat.example/hook/secret", curl_rc=0):
    """A stub curl records argv and stdin; returns the webhook path's env for _guard."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "curl").write_text(
        f'#!/bin/sh\necho "$*" >> {tmp_path}/curl-args\ncat >> {tmp_path}/curl-stdin\nexit {curl_rc}\n')
    (bin_dir / "curl").chmod(0o755)
    path = tmp_path / "alert-webhook"
    if webhook is not None:
        path.write_text(webhook + "\n")
    return {"GUARD_ALERT_WEBHOOK_FILE": str(path)}


def _sent(tmp_path):
    path = tmp_path / "curl-args"
    return path.read_text().splitlines() if path.exists() else []


def test_a_silent_pc_alerts_once_and_once_more_when_it_returns(tmp_path):
    """2026-11-07: the model PC sat off the LAN for six hours and nothing told anyone."""
    env = _alerts(tmp_path)
    _guard(tmp_path, "", exit_code=255, runs=1, env_extra=env)
    assert _sent(tmp_path) == []  # one missed check is not a dead PC
    _guard(tmp_path, "", exit_code=255, runs=3, env_extra=env)
    assert len(_sent(tmp_path)) == 1 and "pc1 PC가 2번 연속" in _sent(tmp_path)[0]
    _guard(tmp_path, HEALTHY, env_extra=env)
    assert len(_sent(tmp_path)) == 2 and "다시 응답합니다" in _sent(tmp_path)[1]
    assert _actions(tmp_path) == ["alert unreachable", "alert recovered"]


def test_the_webhook_never_reaches_argv_the_status_file_or_the_action_log(tmp_path):
    env = _alerts(tmp_path)
    _guard(tmp_path, "", exit_code=255, runs=2, env_extra=env)
    assert 'url = "https://chat.example/hook/secret"' in (tmp_path / "curl-stdin").read_text()
    for text in (*_sent(tmp_path), (tmp_path / "state/status.json").read_text(), (tmp_path / "state/actions.jsonl").read_text()):
        assert "secret" not in text


def test_a_failed_post_tries_again_and_never_touches_the_ladder(tmp_path):
    env = _alerts(tmp_path, curl_rc=22)
    assert set(_guard(tmp_path, "", exit_code=255, runs=4, env_extra=env)) == {"health"}
    assert len(_sent(tmp_path)) == 3
    assert _actions(tmp_path) == []


@pytest.mark.parametrize("webhook", [None, "http://chat.example/hook", 'https://x"\nurl = "https://evil'])
def test_no_alert_without_one_https_webhook(tmp_path, webhook):
    env = _alerts(tmp_path, webhook=webhook)
    _guard(tmp_path, "", exit_code=255, runs=3, env_extra=env)
    assert _sent(tmp_path) == []


def test_the_nightly_quiet_window_and_robots_do_not_alert(tmp_path):
    env = _alerts(tmp_path)
    _guard(tmp_path, "", exit_code=255, runs=3, now="06:00", env_extra=env)
    assert _sent(tmp_path) == []
    _guard(tmp_path, "", runs=3, conf="r1 robot 127.0.0.1:9\n", env_extra=env)
    assert _sent(tmp_path) == []


def test_a_healthy_pc_is_never_touched(tmp_path):
    assert _guard(tmp_path, HEALTHY, runs=5) == ["health"] * 5
    row = json.loads((tmp_path / "state/status.json").read_text())["pc1"]
    assert row["state"] == "ok"
    assert row["resources"] == {
        "avail_pct": 60, "swap_pct": 5, "load": 1.2, "cores": 24, "uptime_s": 7200, "down": [],
        # a six-field reply: disk and RAM size unknown, not healthy; the RAM warning still uses avail_pct
        "disk": None, "disk_low": None, "gpu": None, "memory": None, "memory_low": False, "cpu": None,
        "reboot_overdue": False,
    }


def test_a_pc_whose_nightly_reboots_kept_skipping_is_reported_never_rebooted(tmp_path):
    """D-991: a nightly reboot skips while work runs; after three days that is flagged, never forced."""
    answer = HEALTHY.replace(" 7200 ", f" {3 * 86400 + 1} ")
    assert _guard(tmp_path, answer, runs=4) == ["health"] * 4
    row = json.loads((tmp_path / "state/status.json").read_text())["pc1"]
    assert row["state"] == "ok" and row["resources"]["reboot_overdue"] is True and _actions(tmp_path) == []


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


@pytest.mark.parametrize("name", ["ai", "model", "cell", "arm-cell", "cell-b"])
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


def test_monitoring_health_failures_alert_once_and_recovery_once(tmp_path):
    import http.server
    import threading
    code = {"value": 503}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(code["value"])
            self.end_headers()

        def log_message(self, *args):
            pass
    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        env = _alerts(tmp_path)
        conf = f"mon monitoring http://127.0.0.1:{server.server_port}/monitoring-health\n"
        _guard(tmp_path, HEALTHY, conf=conf, env_extra=env)
        assert _sent(tmp_path) == []  # one failed check is not an outage
        _guard(tmp_path, HEALTHY, conf=conf, runs=3, env_extra=env)
        assert len(_sent(tmp_path)) == 1 and "mon 서비스가 2번 연속" in _sent(tmp_path)[0]
        code["value"] = 200
        _guard(tmp_path, HEALTHY, conf=conf, env_extra=env)
        assert len(_sent(tmp_path)) == 2 and "다시 응답합니다" in _sent(tmp_path)[1]
        assert _actions(tmp_path) == ["alert unreachable", "alert recovered"]
        assert "mon" not in json.loads((tmp_path / "state/status.json").read_text())
    finally:
        server.shutdown()


def test_monitoring_with_a_stale_or_null_last_success_counts_as_failing(tmp_path):
    import http.server
    import threading
    body = {"value": {"status": "ready", "last_success": None}}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            payload = json.dumps(body["value"]).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass
    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        env = {**_alerts(tmp_path), "GUARD_MONITORING_STALE_MIN": "15"}
        conf = f"mon monitoring http://127.0.0.1:{server.server_port}/monitoring-health\n"
        _guard(tmp_path, HEALTHY, conf=conf, env_extra=env)
        assert _sent(tmp_path) == []  # one stale check is not an outage
        body["value"] = {"status": "ready", "last_success": time.time() - 16 * 60}
        _guard(tmp_path, HEALTHY, conf=conf, runs=2, env_extra=env)
        assert len(_sent(tmp_path)) == 1 and "mon 서비스가 2번 연속" in _sent(tmp_path)[0]
        body["value"] = {"status": "ready", "last_success": time.time() - 5 * 60}
        _guard(tmp_path, HEALTHY, conf=conf, env_extra=env)
        assert len(_sent(tmp_path)) == 2 and "다시 응답합니다" in _sent(tmp_path)[1]
        body["value"] = {"status": "ready"}  # an older Monitoring without the key is judged by the status code
        _guard(tmp_path, HEALTHY, conf=conf, runs=3, env_extra=env)
        assert len(_sent(tmp_path)) == 2
    finally:
        server.shutdown()


def _monitoring_alerts(tmp_path, status_code, body):
    """Alerts sent after three guard runs against a Monitoring that always answers like this."""
    import http.server
    import threading
    tmp_path.mkdir(parents=True, exist_ok=True)

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status_code)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass
    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        conf = f"mon monitoring http://127.0.0.1:{server.server_port}/monitoring-health\n"
        _guard(tmp_path, HEALTHY, conf=conf, runs=3, env_extra=_alerts(tmp_path))
        return _sent(tmp_path)
    finally:
        server.shutdown()


@pytest.mark.parametrize("body", [b"<html><body>502 Bad Gateway</body></html>", b"[]", b"ok", b"null"])
def test_a_2xx_monitoring_answer_that_is_not_a_json_object_is_a_failed_check(tmp_path, body):
    assert len(_monitoring_alerts(tmp_path, 200, body)) == 1


@pytest.mark.parametrize("body", [b"", b'{"status":"ready"}'])
def test_an_empty_or_keyless_monitoring_answer_is_judged_by_the_status_code(tmp_path, body):
    assert _monitoring_alerts(tmp_path, 200, body) == []
    assert len(_monitoring_alerts(tmp_path / "down", 503, body)) == 1


def test_a_failed_monitoring_state_write_does_not_stop_status_json(tmp_path):
    conf = "pc1 pc op@pc1 05:50-06:20\n"
    _guard(tmp_path, HEALTHY, conf=conf)
    state = tmp_path / "state"
    (state / "monitoring-health.json").unlink()
    (state / "monitoring-health.json").mkdir()  # neither a direct write nor a replace onto it can succeed
    (state / "status.json").unlink()
    _guard(tmp_path, HEALTHY, conf=conf)
    assert "pc1" in json.loads((state / "status.json").read_text())


def test_the_monitoring_state_is_written_through_a_temporary_file_in_its_own_directory(tmp_path):
    source = GUARD.read_text(encoding="utf-8")
    assert "monitors_file.with_suffix" in source and "os.replace(monitors_tmp, monitors_file)" in source
    _guard(tmp_path, HEALTHY)
    assert sorted(p.name for p in (tmp_path / "state").glob("monitoring-health*")) == ["monitoring-health.json"]


# --- D-1021: drift and login-probe watches ----------------------------------------------------------------

CLEAN_DRIFT = "chrony 1 1 ntp.example.test,\nguard-age 300\n"


def _drift(tmp_path, answer, runs=1, env=None):
    answer_file = tmp_path / "drift-answer"
    answer_file.unlink(missing_ok=True)
    if answer is not None:
        answer_file.write_text(answer)
    return _guard(tmp_path, HEALTHY, conf="m drift op@m ntp.example.test old.example.test\n", runs=runs, env_extra=env)


@pytest.mark.parametrize("answer, word", [
    ("chrony 1 1 gone.example.test,\nguard-age 5\n", "gone.example.test"),
    ("chrony 1 2 ntp.example.test,extra.example.test,\n", "extra.example.test"),
    ("chrony 0 1 ntp.example.test,\n", "0개"),
    ("chrony 1 1 ntp.example.test,\nretired old.example.test\n", "옛 이름 old.example.test"),
    ("chrony 1 1 ntp.example.test,\nguard-age 7300\n", "멈췄"),
    ("chrony none\n", "chrony가 설치돼"),
    ("chrony x y\n", "읽지 못했습니다"),
    ("guard-age 5\n", "chrony 보고가 없"),
    ("chrony 1 1 ntp.example.test,\nguard-age missing\n", "status.json이 없거나"),
    ("chrony 1 1 ntp.example.test,\nguard-age \n", "status.json이 없거나"),
    ("chrony 1 1 ntp.example.test,\nguard-age -5\n", "status.json이 없거나"),
    ("chrony 1 1 ntp.example.test,\nguard-age nan\n", "status.json이 없거나"),
    ("chrony 1 1 ntp.example.test,\n", "상태 시각 보고가 없"),
    (None, "답이 없"),
])
def test_a_drift_problem_alerts_once_after_two_checks_and_once_on_recovery(tmp_path, answer, word):
    env = _alerts(tmp_path)
    _drift(tmp_path, answer, 1, env)
    assert _sent(tmp_path) == []  # one bad check is not a streak
    _drift(tmp_path, answer, 3, env)
    assert len(_sent(tmp_path)) == 1 and word in _sent(tmp_path)[0]
    _drift(tmp_path, CLEAN_DRIFT, 1, env)
    assert len(_sent(tmp_path)) == 2 and "다시 정상" in _sent(tmp_path)[1]
    assert _actions(tmp_path) == ["alert unreachable", "alert recovered"]


def test_a_clean_drift_answer_never_alerts_and_the_retired_names_reach_the_forced_command(tmp_path):
    env = _alerts(tmp_path)
    assert _drift(tmp_path, CLEAN_DRIFT, 4, env) == ["drift old.example.test"] * 4
    assert _sent(tmp_path) == []


def test_a_dash_skips_the_name_compare_but_not_the_other_checks(tmp_path):
    env = _alerts(tmp_path)
    (tmp_path / "drift-answer").write_text("chrony 1 1 anything.example.test,\nguard-age 5\n")
    _guard(tmp_path, HEALTHY, conf="m drift op@m -\n", runs=3, env_extra=env)
    assert _sent(tmp_path) == []


def _login(tmp_path, apps, age=0, env=None, write=True):
    path = tmp_path / "login-status.json"
    if write:
        path.write_text(json.dumps({"time": int(time.time()) - age, "apps": apps}))
    _guard(tmp_path, HEALTHY, conf=f"acct logincheck {path}\n", env_extra=env)


def test_login_failures_alert_once_per_streak_and_once_on_recovery_without_credentials(tmp_path):
    env = _alerts(tmp_path)
    bad = {"fleet": True, "learning": False}
    _login(tmp_path, bad, age=10, env=env)
    for _ in range(2):  # the same failed report read by three guard runs is still one report
        _login(tmp_path, bad, env=env, write=False)
    assert _sent(tmp_path) == []
    _login(tmp_path, bad, age=5, env=env)  # the second failing report
    assert len(_sent(tmp_path)) == 1 and "learning" in _sent(tmp_path)[0] and "fleet" not in _sent(tmp_path)[0]
    _login(tmp_path, bad, age=2, env=env)  # still the same streak
    assert len(_sent(tmp_path)) == 1
    _login(tmp_path, {"fleet": True, "learning": True}, age=0, env=env)
    assert len(_sent(tmp_path)) == 2 and "다시 정상" in _sent(tmp_path)[1]
    _login(tmp_path, bad, age=8, env=env)
    _login(tmp_path, bad, age=4, env=env)
    assert len(_sent(tmp_path)) == 3  # a new streak alerts again
    assert _actions(tmp_path) == ["alert unreachable", "alert recovered", "alert unreachable"]
    for text in (*_sent(tmp_path), (tmp_path / "state/actions.jsonl").read_text()):
        assert "secret" not in text and "password" not in text.lower()


def test_a_login_report_that_stops_being_renewed_or_is_missing_alerts(tmp_path):
    env = _alerts(tmp_path)
    _login(tmp_path, {"fleet": True}, age=4 * 3600, env=env)
    assert _sent(tmp_path) == []
    _login(tmp_path, {"fleet": True}, age=4 * 3600, env=env)
    assert len(_sent(tmp_path)) == 1 and "시간 전" in _sent(tmp_path)[0]
    _login(tmp_path, {"fleet": True}, age=0, env=env)
    assert len(_sent(tmp_path)) == 2 and "다시 정상" in _sent(tmp_path)[1]
    (tmp_path / "login-status.json").unlink()
    _login(tmp_path, {}, env=env, write=False)
    _login(tmp_path, {}, env=env, write=False)
    assert len(_sent(tmp_path)) == 3 and "읽지 못했습니다" in _sent(tmp_path)[2]


@pytest.mark.parametrize("conf", [
    "m drift op@m\n", "m drift\n", "m drift op@m ntp.example.test, old\n", "m drift op@m a,,b old.example.test\n",
    "m drift op@m ntp.example.test bad;name\n", "x logincheck\n", "x logincheck /a /b\n"])
def test_a_malformed_watch_line_is_a_loud_config_error_never_a_silent_skip(tmp_path, conf):
    env = _alerts(tmp_path)
    (tmp_path / "drift-answer").write_text(CLEAN_DRIFT)
    for _ in range(2):
        _guard(tmp_path, HEALTHY, conf=conf, env_extra=env)
    assert len(_sent(tmp_path)) == 1 and "감시 설정" in _sent(tmp_path)[0]
    result = subprocess.run([sys.executable, str(GUARD)], capture_output=True, text=True, timeout=60, env={
        **os.environ, "GUARD_STATE": str(tmp_path / "state"), "GUARD_CONFIG": str(tmp_path / "hosts.conf"),
        "GUARD_LOCAL_STATUS": str(tmp_path / "local-status.json"), "GUARD_LOCAL_HEALTH": str(tmp_path / "none")})
    assert "config error" in result.stderr and "IndexError" not in result.stdout + result.stderr


def _raw_login(tmp_path, text, env):
    (tmp_path / "login-status.json").write_text(text)
    _guard(tmp_path, HEALTHY, conf=f"acct logincheck {tmp_path / 'login-status.json'}\n", env_extra=env)


@pytest.mark.parametrize("delta, word", [(-3600, "미래"), (None, "미래")])
def test_a_future_or_nan_login_stamp_is_a_problem(tmp_path, delta, word):
    env = _alerts(tmp_path)
    stamp = "NaN" if delta is None else str(int(time.time()) - delta)
    for _ in range(2):
        _raw_login(tmp_path, '{"time": %s, "apps": {"fleet": true}}' % stamp, env)
    assert len(_sent(tmp_path)) == 1 and word in _sent(tmp_path)[0]


def test_a_partial_login_report_is_a_problem_and_only_a_full_all_pass_one_recovers(tmp_path):
    env = _alerts(tmp_path)
    _login(tmp_path, {"fleet": True, "learning": True}, age=20, env=env)  # a full report names the known apps
    for age in (10, 8):  # the probe run for one app: the failing one vanished from the file
        _login(tmp_path, {"fleet": True}, age=age, env=env)
    assert len(_sent(tmp_path)) == 1 and "빠진 앱: learning" in _sent(tmp_path)[0]
    _login(tmp_path, {"fleet": True}, age=5, env=env)
    assert len(_sent(tmp_path)) == 1  # an all-PASS partial report is no recovery
    _login(tmp_path, {"fleet": True, "learning": True}, age=0, env=env)
    assert len(_sent(tmp_path)) == 2 and "다시 정상" in _sent(tmp_path)[1]


def test_the_failing_app_set_changing_inside_a_streak_alerts_once_more(tmp_path):
    env = _alerts(tmp_path)
    for age in (8, 4):
        _login(tmp_path, {"fleet": False, "learning": True}, age=age, env=env)
    assert len(_sent(tmp_path)) == 1 and "fleet" in _sent(tmp_path)[0]
    _login(tmp_path, {"fleet": False, "learning": True}, age=2, env=env)
    assert len(_sent(tmp_path)) == 1  # the same set, no new alert
    _login(tmp_path, {"fleet": False, "learning": False}, age=1, env=env)
    assert len(_sent(tmp_path)) == 2 and "fleet, learning" in _sent(tmp_path)[1]
    _login(tmp_path, {"fleet": False, "learning": False}, age=0, env=env)
    assert len(_sent(tmp_path)) == 2


def test_the_drift_verb_is_read_only_and_refuses_odd_names(tmp_path):
    result, calls = _remote(tmp_path, "drift localhost")
    assert result.returncode == 0 and "retired localhost" in result.stdout  # /etc/hosts always names localhost
    assert result.stdout.count("chrony ") == 1 and calls == []
    assert re.search(r"^guard-age (missing|\d+)$", result.stdout, re.M)  # never an empty value
    for bad in ("drift a;b", "drift $(id)", "drift ../x"):
        result, calls = _remote(tmp_path, bad)
        assert result.returncode == 2 and calls == []
