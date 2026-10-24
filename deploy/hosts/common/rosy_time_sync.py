#!/usr/bin/env python3
"""Configure the shared site NTP hierarchy; check never changes the clock (D-859)."""

import argparse
import csv
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

CONFIG = Path("/etc/chrony/chrony.conf")
MAX_ERROR_S = 0.05
MAX_AGE_S = 180


def configuration(role, sources, networks):
    if role not in {"site", "client"} or not sources:
        raise ValueError("role and explicit NTP sources are required")
    sources = list(dict.fromkeys(source.lower().rstrip(".") for source in sources))
    for source in sources:
        try:
            ipaddress.ip_address(source)
        except ValueError:
            if len(source) > 253 or not all(
                re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                for label in source.rstrip(".").split(".")
            ):
                raise ValueError("NTP source must be a hostname or IP, without options")
    if role == "site" and (len(sources) < 3 or not networks):
        raise ValueError("site needs at least three distinct upstream sources and an allowed CIDR")
    if role == "client" and networks:
        raise ValueError("clients cannot serve NTP")
    if role == "client" and len(sources) != 1:
        raise ValueError("all clients must use the same single site NTP endpoint (D-861)")
    allowed = []
    for network in networks:
        parsed = ipaddress.ip_network(network, strict=True)
        if parsed.prefixlen == 0 or parsed.is_multicast or parsed.is_unspecified:
            raise ValueError("an explicit client network is required; never allow the entire Internet")
        allowed.append(str(parsed))
    lines = [
        "# Managed by ROSY D-859; maintain only while application workloads are stopped.",
        "driftfile /var/lib/chrony/chrony.drift",
        "rtcsync",
        "makestep 0.1 3",
        "maxdistance 0.1",
        "bindcmdaddress 127.0.0.1",
        "bindcmdaddress ::1",
    ]
    lines += [f"server {source} iburst minpoll 4 maxpoll 6" for source in sources]
    lines += [f"allow {network}" for network in allowed] if role == "site" else ["port 0"]
    return "\n".join(lines) + "\n"


def assess(tracking, *, now):
    """Bound UTC error by remaining correction + root delay/2 + dispersion."""
    refused = {"synchronized": False, "reason": "invalid_tracking"}
    try:
        fields = next(csv.reader([tracking.strip()]))
        if len(fields) != 14:
            return refused
        stratum = int(fields[2])
        stamp, correction, delay, dispersion = (float(fields[i]) for i in (3, 4, 10, 11))
        if not all(math.isfinite(v) for v in (now, stamp, correction, delay, dispersion)):
            return refused
        if delay < 0 or dispersion < 0:
            return refused
        age = now - stamp
        bound = abs(correction) + delay / 2 + dispersion
        ready = fields[13] == "Normal" and 1 <= stratum <= 15 and 0 <= age <= MAX_AGE_S and bound <= MAX_ERROR_S
        return {"synchronized": ready, "reason": "ready" if ready else "unsynchronized_or_out_of_bounds",
                "error_bound_s": bound, "sample_age_s": age, "stratum": stratum}
    except (ValueError, StopIteration, csv.Error):
        return refused


def run(*args, check=True):
    return subprocess.run(args, check=check, capture_output=True, text=True, timeout=20)


def check():
    try:
        active = run("systemctl", "is-active", "--quiet", "chrony.service", check=False).returncode == 0
        report = assess(run("chronyc", "-c", "tracking").stdout, now=time.time())
        if not active:
            report = {"synchronized": False, "reason": "chrony_inactive"}
    except (OSError, subprocess.SubprocessError):
        report = {"synchronized": False, "reason": "chrony_unavailable"}
    print(json.dumps(report, allow_nan=False))
    return 0 if report["synchronized"] else 1


def install(config, path=CONFIG):
    if sys.platform != "linux" or os.geteuid() != 0:
        raise ValueError("install requires root on a Linux host with chrony installed")
    # A restart reopens makestep's first-three-update window, including on reinstall.
    for unit in ("rosy-core", "rosy-io", "rosy-navigation", "rosy-site-stack",
                 "systemd-timesyncd", "ntp", "ntpsec"):
        if run("systemctl", "is-active", "--quiet", unit + ".service", check=False).returncode == 0:
            raise ValueError(f"stop {unit}.service in the maintenance window before installation")
    old = path.read_bytes() if path.exists() else None
    backup = None
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".rosy-time-", delete=False) as staged:
        candidate = Path(staged.name)
        staged.write(config.encode("utf-8"))
    try:
        run("chronyd", "-p", "-f", str(candidate))
        if old is not None:
            fd, name = tempfile.mkstemp(dir=path.parent, prefix="chrony.conf.rosy-backup-")
            os.close(fd)
            backup = Path(name)
            shutil.copy2(path, backup)
        candidate.chmod(0o644)
        candidate.replace(path)
        try:
            run("systemctl", "enable", "chrony.service")
            run("systemctl", "restart", "chrony.service")
        except (OSError, subprocess.SubprocessError):
            if backup is not None:
                shutil.copy2(backup, path)
            else:
                path.unlink()
            run("systemctl", "restart", "chrony.service", check=False)
            raise
    finally:
        candidate.unlink(missing_ok=True)
    print(f"installed; backup={backup or 'none'}", file=sys.stderr)
    # A timeout leaves the intended config installed and explicitly reports not ready.
    subprocess.run(["chronyc", "waitsync", "60", "0.01", "0", "1"],
                   check=False, stdout=subprocess.DEVNULL, timeout=70)
    return check()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="read-only UTC error/freshness check, JSON and nonzero when not ready")
    for command in ("render", "install"):
        options = sub.add_parser(command)
        options.add_argument("--role", required=True, choices=("site", "client"))
        options.add_argument("--source", action="append", required=True, help="upstream for site; site server for client")
        options.add_argument("--allow", action="append", default=[], help="site-only client CIDR")
        if command == "install":
            options.add_argument("--maintenance", action="store_true", help="confirm all host workloads are stopped")
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            return check()
        if args.command == "install" and not args.maintenance:
            parser.error("install requires --maintenance: stop all workloads before changing the clock")
        config = configuration(args.role, args.source, args.allow)
        if args.command == "render":
            print(config, end="")
            return 0
        return install(config)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"time-sync failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
