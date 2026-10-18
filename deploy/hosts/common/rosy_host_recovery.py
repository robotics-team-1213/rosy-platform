"""Read-only PC recovery evidence for the approved host-state copy (D-530).

Never open /dev/watchdog: opening it can arm hardware. File existence and PID 1's
runtime timeout are checked independently of the installed configuration files.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path


def snapshot(root: str, run) -> dict:
    def read(path):
        try:
            return Path(root + path).read_text().strip()
        except OSError:
            return None

    def number(path):
        try:
            return int(read(path))
        except (TypeError, ValueError):
            return None

    def command(*args):
        try:
            result = run(*args)
            return result.stdout.strip() if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None

    def unit(name):
        return (command("systemctl", "is-enabled", name) == "enabled"
                and command("systemctl", "is-active", name) == "active")

    raw = command("systemctl", "show", "--property=RuntimeWatchdogUSec", "--value")
    timeout_s = None
    if raw == "0":
        timeout_s = 0
    elif raw:
        parts = re.findall(r"(\d+(?:\.\d+)?)(us|µs|ms|s|min|h|d)", raw)
        if parts and not re.sub(r"\d+(?:\.\d+)?(?:us|µs|ms|s|min|h|d)|\s", "", raw):
            scale = {"us": 1e-6, "µs": 1e-6, "ms": .001, "s": 1, "min": 60, "h": 3600, "d": 86400}
            timeout_s = sum(float(value) * scale[suffix] for value, suffix in parts)
    device = Path(root + "/dev/watchdog0").exists()
    watchdog = {"state": "unsupported" if not device else "degraded", "timeout_s": timeout_s,
                "device": device, "loader_active": unit("rosy-watchdog-load.service")}
    if device and timeout_s == 30 and watchdog["loader_active"]:
        watchdog["state"] = "ok"

    panic = number("/proc/sys/kernel/panic")
    softlockup = number("/proc/sys/kernel/softlockup_panic")
    kernel = {"state": "ok" if panic == 10 and softlockup == 1 else "degraded",
              "panic_s": panic, "softlockup_panic": softlockup}
    try:
        uptime = float(read("/proc/uptime").split()[0])
        load = float(read("/proc/loadavg").split()[0])
    except (AttributeError, ValueError, IndexError):
        uptime, load = None, None
    service = dict(line.split("=", 1) for line in (
        command("systemctl", "show", "rosy-ssh-watchdog.service",
                "--property=Result,ExecMainStatus,ExecMainExitTimestampMonotonic") or "").splitlines() if "=" in line)
    try:
        stamp = int(service.get("ExecMainExitTimestampMonotonic", "0"))
        age = int(uptime - stamp / 1e6) if uptime is not None and stamp > 0 else None
    except ValueError:
        age = None
    counters = {name: number("/var/lib/rosy-ssh-watchdog/" + name) for name in (
        "ssh_failures", "tailscale_failures", "gateway_failures", "reboots")}
    ssh_ok = (unit("rosy-ssh-watchdog.timer") and service.get("Result") == "success"
              and service.get("ExecMainStatus") == "0" and age is not None and 0 <= age <= 360
              and all(value is not None and value >= 0 for value in counters.values())
              and not any(counters[name] for name in ("ssh_failures", "tailscale_failures", "gateway_failures")))
    ssh = {"state": "ok" if ssh_ok else "degraded", "last_check_age_s": age, **counters}

    memory = {}
    for line in (read("/proc/meminfo") or "").splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1].isdigit():
            memory[fields[0].rstrip(":")] = int(fields[1]) * 1024
    total, free = memory.get("SwapTotal"), memory.get("SwapFree")
    used = total - free if total is not None and free is not None and 0 <= free <= total else None
    swap = {"state": "unknown" if used is None else "ok" if total > 0 else "missing",
            "total_bytes": total, "used_bytes": used}
    mem_total, available = memory.get("MemTotal"), memory.get("MemAvailable")
    resources = {
        "avail_pct": int(100 * available / mem_total) if mem_total and available is not None else None,
        "swap_pct": int(100 * used / total) if total and used is not None else None,
        "load": load, "cores": os.cpu_count(), "uptime_s": int(uptime) if uptime is not None else None,
        "mem_total_bytes": mem_total, "mem_available_bytes": available,
    }
    checks = {"watchdog": watchdog, "kernel": kernel, "ssh": ssh, "swap": swap}
    issues = [name for name, value in checks.items() if value["state"] != "ok"]
    return {"time": int(time.time()), "role": read("/usr/local/lib/rosy-host-state/role-name"),
            "state": "degraded" if issues else "ok", "issues": issues, "resources": resources, **checks}
