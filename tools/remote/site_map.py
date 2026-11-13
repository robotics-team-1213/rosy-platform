"""One private site map: which PC runs what, with which arm boards, and how it is managed.

The map lives in ``private/site-map.yaml`` on the main checkout (``ROSY_SITE_MAP`` overrides), beside
``lab-hosts.json``, because it holds real addresses and board serials (D-226). Tools read it here instead of
rediscovering the site. ``check`` compares each host's OpenRB boards with the map, read-only:

    python tools/remote/site_map.py show
    python tools/remote/site_map.py check            # exit 1 on a missing or unmapped board
    python tools/remote/site_map.py apply-time [--host X] [--execute] [--robot-maintenance --robot-idle-confirmed R]   # dry run unless --execute

``time_source:`` (D-1021) is the one place a host's chrony `server` names are decided: top level ``{client: <name>,
site: [<upstream>, ...]}``, or ``time_source:`` on one host. ``update_status`` compares it with each host's chrony;
``apply-time`` installs it with deploy/hosts/common/rosy_time_sync.py.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lab_hosts import main_checkout  # noqa: E402

SCHEMA = "rosy.site-map/1"
TIME_TOOL = Path(__file__).resolve().parents[2] / "deploy" / "hosts" / "common" / "rosy_time_sync.py"
# rosy_time_sync.install refuses while any of these runs; a robot gets them stopped only with --robot-maintenance
WORKLOADS = ("rosy-core", "rosy-io", "rosy-navigation")
CHRONY_NAMES = ("cat /etc/chrony/chrony.conf /etc/chrony/conf.d/*.conf /etc/chrony/sources.d/*.sources /etc/chrony.conf "
                "2>/dev/null </dev/null | awk '$1==\"server\"{print tolower($2)}'")
OPENRB = re.compile(r"usb-ROBOTIS_OpenRB-150_([0-9A-F]{32})-if00")


def map_file() -> Path:
    override = os.environ.get("ROSY_SITE_MAP", "").strip()
    return Path(override) if override else main_checkout() / "private" / "site-map.yaml"


def load(path: Path | None = None) -> dict:
    path = path or map_file()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("hosts"), dict):
        raise SystemExit(f"{path}: expected schema {SCHEMA} with a hosts mapping")
    return data


def boards(host: dict) -> dict[str, str]:
    """Board serial -> '<arm>.<role>' for one host's arms."""
    found = {}
    for arm, roles in (host.get("arms") or {}).items():
        for role in ("follower", "leader"):
            serial = ((roles or {}).get(role) or {}).get("board")
            if serial:
                if serial in found:
                    raise SystemExit(f"board {serial} is mapped twice: {found[serial]} and {arm}.{role}")
                found[serial] = f"{arm}.{role}"
    return found


def time_source(site: dict, host: dict) -> set[str] | None:
    """Expected chrony `server` names of one host: its own ``time_source:``, else the map's for its role; None if unset."""
    value = host.get("time_source")
    if value is None:
        by_role = site.get("time_source")
        value = by_role.get("site" if "site" in (host.get("roles") or []) else "client") if isinstance(by_role, dict) else None
    if value is None:
        return None
    names = [value] if isinstance(value, str) else value
    if not isinstance(names, list) or not names or not all(isinstance(n, str) and n.strip() for n in names):
        raise SystemExit("time_source must be a hostname or a non-empty list of hostnames")
    return {n.strip().lower().rstrip(".") for n in names}


def time_mismatch(configured: set[str], expected: set[str]) -> str | None:
    configured = {n.rstrip(".") for n in configured}
    if configured == expected:
        return None
    return f"chrony servers {', '.join(sorted(configured)) or 'none'}; site map time_source {', '.join(sorted(expected))}"


def host_for(site: dict, target: str):
    """(map name, host) whose ``ssh:`` text contains this ssh target, else None."""
    for name, host in site["hosts"].items():
        if target in re.split(r"[\s(),]+", str(host.get("ssh", ""))):
            return name, host
    return None


def board_findings(host: dict, present: set[str]) -> list[str]:
    mapped = boards(host)
    return ([f"missing {mapped[s]} board {s}" for s in sorted(set(mapped) - present)]
            + [f"unmapped board {s}" for s in sorted(present - set(mapped))])


def present_boards(ssh: str) -> set[str]:
    ssh_target = ssh.split()[0]
    out = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", ssh_target,
                          "ls /dev/serial/by-id 2>/dev/null"], capture_output=True, text=True, timeout=30)
    if out.returncode not in (0, 2):
        raise RuntimeError(out.stderr.strip() or f"ssh {ssh_target} failed")
    return set(OPENRB.findall(out.stdout))


def ssh_run(target: str, command: str, data: bytes | None = None) -> tuple[int, str]:
    """(exit code, stdout). stderr (host-key warnings, banners) never mixes into a successful answer."""
    try:
        done = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", target, command], input=data,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=240)
    except subprocess.TimeoutExpired:
        return 255, "timed out"
    out, err = done.stdout.decode(errors="replace"), done.stderr.decode(errors="replace")
    return done.returncode, out if done.returncode == 0 else out + err


def workloads_state(run, target: str) -> tuple[list[str] | None, str]:
    """(active workload units, "") or (None, why): exit 0 is active and 3 inactive; any other exit (ssh 255, a
    timeout) is unknown, and an unknown state is never read as inactive."""
    active = []
    for unit in WORKLOADS:
        code, _ = run(target, f"systemctl is-active --quiet {unit}.service")
        if code == 0:
            active.append(unit)
        elif code != 3:
            return None, f"cannot tell whether {unit} is active (exit {code})"
    return active, ""


def apply_host(label, target, expected, robot, run, execute, robot_maintenance, tool: bytes, site_role=False) -> bool:
    """Bring one host's chrony to ``expected`` (one client source); prints one or more lines, False on a failure."""
    if site_role:  # decided by the map's roles, never by how many sources the map lists
        print(f"{label}: skipped, a site role host serves time and never gets the client role; install it by hand (needs --allow)")
        return True
    if len(expected) != 1:
        print(f"{label}: skipped, {len(expected)} sources is not one client source; install it by hand (needs --allow)")
        return True
    (source,) = expected
    code, out = run(target, CHRONY_NAMES)
    if code:
        print(f"{label}: FAIL unreachable ({out.strip()[-80:]})")
        return False
    if {n.rstrip(".") for n in out.lower().split()} == expected:
        print(f"{label}: ok, chrony already uses {source}")
        return True
    active, why = workloads_state(run, target)
    if active is None:
        print(f"{label}: FAIL {why}; refusing to change this host")
        return False
    if active and not (robot and robot_maintenance):
        print(f"{label}: refused, {', '.join(active)} active; stop them in a maintenance window"
              + (" or pass --robot-maintenance" if robot else ""))
        return False
    tail = f"install --maintenance --role client --source {shlex.quote(source)}"
    if not execute:
        steps = [f"sudo -n systemctl stop {u}.service" for u in reversed(active)]
        steps += ["mktemp -d, copy rosy_time_sync.py into it", f"sudo -n python3 -I <dir>/rosy_time_sync.py {tail}", "rm -rf <dir>"]
        steps += [f"sudo -n systemctl start {u}.service" for u in active]
        print(f"{label}: would run on {target}: " + "; ".join(steps))
        return True
    code, out = run(target, "mktemp -d")
    workdir = out.strip()
    if code or not re.fullmatch(r"/[A-Za-z0-9._/-]+", workdir):
        print(f"{label}: FAIL could not make a private directory ({out.strip()[-80:]})")
        return False
    stopped, ok = [], True
    try:
        for unit in reversed(active):
            stopped.append(unit)  # a stop that timed out may still finish, so it is restarted too
            if run(target, f"sudo -n systemctl stop {unit}.service")[0]:
                raise RuntimeError(f"could not stop {unit}")
        if run(target, f"umask 077 && cat > {workdir}/rosy_time_sync.py", tool)[0]:
            raise RuntimeError("could not copy the tool to the private directory")
        code, out = run(target, f"sudo -n python3 -I {workdir}/rosy_time_sync.py {tail}")
        if code:
            raise RuntimeError(f"install exit {code}: {out.strip()[-200:]}")
    except RuntimeError as error:
        print(f"{label}: FAIL {error}")
        ok = False
    finally:
        run(target, f"rm -rf {workdir}")
        for unit in reversed(stopped):  # start order is the reverse of the stop order
            if run(target, f"sudo -n systemctl start {unit}.service")[0]:
                print(f"{label}: FAIL could not start {unit}; start it by hand now")
                ok = False
            else:
                print(f"{label}: started {unit} again")
    if ok:
        print(f"{label}: installed chrony source {source}")
    return ok


def apply_time(site: dict, run=ssh_run, execute=False, only=None, robot_maintenance=False, tool: bytes | None = None,
               robot_idle_confirmed: str | None = None) -> bool:
    """Run apply_host for every host of the map and every Pinky; True when none failed."""
    tool = TIME_TOOL.read_bytes() if tool is None else tool
    jobs = [(name, str(host["ssh"]).split()[0], time_source(site, host), False, "site" in (host.get("roles") or []))
            for name, host in site["hosts"].items() if host.get("ssh")]
    robots_source = time_source(site, {})  # a robot has the client role
    jobs += [(f"rosy-pinky-{robot}", f"rosy-pinky-{robot}", robots_source, True, False)
             for robot in ((site.get("robots") or {}).get("pinky_active") or {})]
    jobs = [job for job in jobs if only in (None, job[0], job[1])]
    if not jobs:
        print(f"no host matches {only!r}")
        return False
    if robot_maintenance:  # one robot per run, and only one a person says is idle (no reliable idle signal over ssh)
        if only is None or len(jobs) != 1 or not jobs[0][3]:
            print("refused: --robot-maintenance needs --host naming exactly one robot")
            return False
        if robot_idle_confirmed not in jobs[0][:2]:
            print(f"{jobs[0][0]}: refused, --robot-maintenance needs --robot-idle-confirmed {jobs[0][0]}: "
                  "confirm on its dashboard that it is not moving or docking and has no goal")
            return False
    results = []
    for name, target, expected, robot, site_role in jobs:
        if expected is None:
            print(f"{name}: skipped, no time_source in the site map")
            continue
        results.append(apply_host(name, target, expected, robot, run, execute, robot_maintenance, tool, site_role))
    return all(results)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("show", "check", "apply-time"))
    parser.add_argument("--host", help="apply-time: one map host name, robot name or ssh target")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="apply-time: print only (the default)")
    mode.add_argument("--execute", action="store_true", help="apply-time: really install over ssh")
    parser.add_argument("--robot-maintenance", action="store_true",
                        help="apply-time: stop and restart a robot's rosy-core/rosy-io/rosy-navigation around the install; "
                             "needs --host with one robot and --robot-idle-confirmed")
    parser.add_argument("--robot-idle-confirmed", metavar="ROBOT",
                        help="apply-time: you checked that this robot is idle (not moving or docking, no goal); no ssh "
                             "signal says so, so --robot-maintenance refuses without it")
    args = parser.parse_args(argv)
    site = load()
    if args.command == "show":
        print(json.dumps(site, indent=1, ensure_ascii=False, default=str))
        return 0
    if args.command == "apply-time":
        return 0 if apply_time(site, execute=args.execute, only=args.host, robot_maintenance=args.robot_maintenance,
                                  robot_idle_confirmed=args.robot_idle_confirmed) else 1
    failed = False
    for name, host in site["hosts"].items():
        if not host.get("arms"):
            continue
        try:
            findings = board_findings(host, present_boards(str(host["ssh"])))
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            findings = [f"unreachable: {error}"]
        failed |= bool(findings)
        print(f"{name}: " + ("; ".join(findings) if findings else f"{len(boards(host))} boards match"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
