"""Allowlisted service control for the site, AI, and model Ubuntu hosts.

The control system accepts reboot, cancel-reboot, restart-unit, and stop-unit.
A process name, a signal, and a shell command are not actions. Fleet reaches
every host, its own included, through one forced-command SSH key; the host's
`rosy-host-control-remote` runs `sudo -n /usr/local/sbin/rosy-host-control`.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

RESTART_ONLY = frozenset({"restart-unit"})
RESTART_OR_STOP = frozenset({"restart-unit", "stop-unit"})

# Site units are restart-only: stopping one drops the firewall or stops Fleet itself.
HOSTS: dict[str, dict[str, frozenset[str]]] = {
    "site": {
        "docker.service": RESTART_ONLY,
        "rosy-site-stack.service": RESTART_ONLY,
        "rosy-site-firewall.service": RESTART_ONLY,
    },
    "ai": {
        unit: RESTART_OR_STOP for unit in (
            "pinky-backend.service",
            "pinky-frontend.service",
            "pinky-nav2.service",
            "pinky-rosbridge-d12.service",
            "pinky-rosbridge-d13.service",
            "pinky-r2-watch.service",
        )
    },
    "model": {},
}

ACTIONS = frozenset({"reboot", "cancel-reboot", "restart-unit", "stop-unit"})
UNIT_ACTIONS = RESTART_OR_STOP
REBOOT_DELAY_MIN = 10
CONFIG_DIR = Path("/run/rosy-fleet-host-control")  # host /etc/rosy/fleet-host-control, Fleet only
SSH = "/usr/bin/ssh"
_LOG = logging.getLogger(__name__)
_TARGET = re.compile(r"^[a-z_][a-z0-9_-]{0,31}@[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")
# Exit codes of deploy/site/rosy-host-control; anything else is HOST_HELPER_FAILED.
_HELPER_EXIT = {3: "REBOOT_ALREADY_SCHEDULED", 4: "NO_HOST_CONTROL_REBOOT"}


class HostControlError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def catalogue() -> dict:
    hosts = []
    for host, units in HOSTS.items():
        unit_actions = set().union(*units.values()) if units else set()
        hosts.append({
            "host": host,
            "actions": ["reboot", "cancel-reboot", *sorted(unit_actions)],
            "units": sorted(units),
            "stoppable_units": sorted(u for u, a in units.items() if "stop-unit" in a),
            "reboot_delay_min": REBOOT_DELAY_MIN,
        })
    return {"hosts": hosts}


def decide(host: str, action: str, unit: str | None, *, confirmed: bool) -> dict:
    if confirmed is not True:
        raise HostControlError("CONFIRMATION_REQUIRED")
    if host not in HOSTS:
        raise HostControlError("UNKNOWN_HOST")
    if action not in ACTIONS:
        raise HostControlError("UNKNOWN_ACTION")
    if action in UNIT_ACTIONS:
        if action not in HOSTS[host].get(unit, ()):
            raise HostControlError("UNIT_NOT_ALLOWED")
    elif unit is not None:
        raise HostControlError("UNIT_NOT_ALLOWED")
    argv = (action,) if unit is None else (action, unit)
    return {"host": host, "action": action, "unit": unit, "argv": argv}


class UnavailableHostHelper:
    def run(self, host: str, argv: tuple[str, ...]) -> dict:
        return {"ok": False, "code": "HOST_HELPER_UNAVAILABLE"}


class SshHostHelper:
    """Call one host's forced command over SSH with an argument list. No shell."""

    def __init__(self, targets: dict[str, str], key: Path, known_hosts: Path,
                 timeout_s: float = 30):
        for host, target in targets.items():
            if host not in HOSTS or not _TARGET.fullmatch(target):
                raise HostControlError("HELPER_REFUSED")
        self.targets = dict(targets)
        self.key = key
        self.known_hosts = known_hosts
        self.timeout_s = timeout_s

    def run(self, host: str, argv: tuple[str, ...]) -> dict:
        target = self.targets.get(host)
        if target is None:
            return {"ok": False, "code": "HOST_HELPER_UNAVAILABLE"}
        try:
            completed = subprocess.run(
                [SSH, "-F", "/dev/null", "-i", str(self.key),
                 "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
                 "-o", "StrictHostKeyChecking=yes",
                 "-o", f"UserKnownHostsFile={self.known_hosts}",
                 "-o", "ConnectTimeout=10", "--", target, *argv],
                check=False, capture_output=True, text=True,
                timeout=self.timeout_s, shell=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return {"ok": False, "code": "HOST_HELPER_FAILED"}
        if completed.returncode != 0:
            return {"ok": False,
                    "code": _HELPER_EXIT.get(completed.returncode, "HOST_HELPER_FAILED"),
                    "returncode": completed.returncode}
        return {"ok": True, "code": "ACCEPTED", "output": completed.stdout.strip()[:400]}


def helper_from_config(directory: Path = CONFIG_DIR):
    """`targets` lines are `<host> <user>@<name>`; `id_ed25519` and `known_hosts` sit beside it."""
    key, known_hosts = directory / "id_ed25519", directory / "known_hosts"
    try:
        lines = (directory / "targets").read_text(encoding="utf-8").splitlines()
    except OSError:
        return UnavailableHostHelper()
    if not key.is_file() or not known_hosts.is_file():
        return UnavailableHostHelper()
    targets = {}
    for line in lines:
        fields = line.split("#", 1)[0].split()
        if not fields:
            continue
        if len(fields) != 2 or fields[0] in targets:
            _LOG.error("host control targets file is malformed; Service Control stays off")
            return UnavailableHostHelper()
        targets[fields[0]] = fields[1]
    try:
        return SshHostHelper(targets, key=key, known_hosts=known_hosts)
    except HostControlError:
        _LOG.error("host control targets name an unknown host or a bad target; Service Control stays off")
        return UnavailableHostHelper()
