"""Allowlisted service control for the site, AI, and model Ubuntu hosts.

The control system accepts reboot, cancel-reboot, restart-unit, and stop-unit.
A process name, a signal, and a shell command are not actions.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import PurePath

HOSTS: dict[str, frozenset[str]] = {
    "site": frozenset({
        "docker.service",
        "rosy-site-stack.service",
        "rosy-site-firewall.service",
    }),
    "ai": frozenset({
        "pinky-backend.service",
        "pinky-frontend.service",
        "pinky-nav2.service",
        "pinky-rosbridge-d12.service",
        "pinky-rosbridge-d13.service",
        "pinky-r2-watch.service",
    }),
    "model": frozenset(),
}

ACTIONS = frozenset({"reboot", "cancel-reboot", "restart-unit", "stop-unit"})
UNIT_ACTIONS = frozenset({"restart-unit", "stop-unit"})
REBOOT_DELAY_MIN = 10
HELPER_NAME = "rosy-host-control"


class HostControlError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def catalogue() -> dict:
    hosts = []
    for host, units in HOSTS.items():
        actions = ["reboot", "cancel-reboot"]
        if units:
            actions.extend(sorted(UNIT_ACTIONS))
        hosts.append({
            "host": host,
            "actions": actions,
            "units": sorted(units),
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
        if unit not in HOSTS[host]:
            raise HostControlError("UNIT_NOT_ALLOWED")
    elif unit is not None:
        raise HostControlError("UNIT_NOT_ALLOWED")
    argv = (action,) if unit is None else (action, unit)
    return {"host": host, "action": action, "unit": unit, "argv": argv}


class UnavailableHostHelper:
    def run(self, host: str, argv: tuple[str, ...]) -> dict:
        return {"ok": False, "code": "HOST_HELPER_UNAVAILABLE"}


class SubprocessHostHelper:
    """Run the local rosy-host-control helper. No shell."""

    def __init__(self, helper: str, role: str, timeout_s: float = 20):
        if role not in HOSTS:
            raise HostControlError("UNKNOWN_HOST")
        if PurePath(helper).name != HELPER_NAME:
            raise HostControlError("HELPER_REFUSED")
        self.helper = helper
        self.role = role
        self.timeout_s = timeout_s

    def run(self, host: str, argv: tuple[str, ...]) -> dict:
        if host != self.role:
            return {"ok": False, "code": "HOST_NOT_LOCAL"}
        try:
            completed = subprocess.run(
                [self.helper, *argv],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return {"ok": False, "code": "HOST_HELPER_FAILED"}
        if completed.returncode != 0:
            return {"ok": False, "code": "HOST_HELPER_FAILED",
                    "returncode": completed.returncode}
        return {"ok": True, "code": "ACCEPTED", "output": completed.stdout.strip()}


def helper_from_environment(environ: dict | None = None):
    environ = os.environ if environ is None else environ
    path = environ.get("ROSY_HOST_CONTROL_HELPER", "")
    role = environ.get("ROSY_HOST_CONTROL_ROLE", "")
    if path == "" or role not in HOSTS or PurePath(path).name != HELPER_NAME:
        return UnavailableHostHelper()
    return SubprocessHostHelper(helper=path, role=role)
