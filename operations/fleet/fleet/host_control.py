"""Allowlisted service control for the site, AI, and model Ubuntu hosts.

The control system accepts reboot, reboot-over-jobs, cancel-reboot, restart-unit, and on
the lab PCs clean-storage (D-883: start the rosy-ops storage service once). Whether a PC is free
to reboot is the helper's answer, not a guess made here.
A process name, a signal, and a shell command are not actions. Fleet reaches
every host, its own included, through one forced-command SSH key; the host's
`rosy-host-control-remote` runs `sudo -n /usr/local/sbin/rosy-host-control`.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path

RESTART_ONLY = frozenset({"restart-unit"})

# Restart only (D-991): stopping one drops the firewall, stops Fleet itself or leaves a service down
# with nobody watching. A user unit here carries `operator_restart` in deploy/hosts/services.yaml.
HOSTS: dict[str, dict[str, frozenset[str]]] = {
    "site": {
        unit: RESTART_ONLY for unit in (
            "docker.service",
            "rosy-site-stack.service",
            "rosy-site-firewall.service",
            # The helper refuses these while an arm session runs.
            "rosy-omx-camera-readiness.service",
            "rosy-omx-camera-view.service",
            "rosy-omx-camera@arm_a_wrist.service",
            "rosy-omx-camera@arm_b_wrist.service",
            "rosy-omx-camera@arm_s_top.service",
            "rosy-omx-camera@arm_s_wrist.service",
            "rosy-omx-camera@side.service",
            "rosy-omx-camera@top.service",
        )
    },
    "ai": {"rosy-situation.service": RESTART_ONLY},
    "model": {
        unit: RESTART_ONLY for unit in (
            "rosy-dataset-review-account.service",
            "rosy-dataset-review.service",
            "rosy-edge-review.service",
            "rosy-ollama.service",
            "rosy-review-v12.service",
            "rosy-review-v13-eval.service",
            "rosy-review-v13.service",
            "rosy-tensorboard.service",
        )
    },
    "cell": {},
}

# Host-wide actions besides reboot; the site keeps product data, so clean-storage stays off on site.
HOST_ACTIONS: dict[str, frozenset[str]] = {
    "site": frozenset({"root-maintenance"}),
    "ai": frozenset({"clean-storage", "root-maintenance"}),
    "model": frozenset({"clean-storage", "root-maintenance"}),
    "cell": frozenset({"clean-storage", "root-maintenance"}),
}
ACTIONS = frozenset({"reboot", "reboot-over-jobs", "cancel-reboot", "restart-unit",
                     "clean-storage", "root-maintenance"})
# A person's reboot stops at running jobs; going past them is a second, named request. No action goes
# past an arm session: the helper refuses both words then.
REBOOT_WORD = {"reboot": "reboot-if-free", "reboot-over-jobs": "reboot"}
UNIT_ACTIONS = RESTART_ONLY
REBOOT_DELAY_MIN = 10
CONFIG_DIR = Path("/run/rosy-fleet-host-control")  # host /etc/rosy/fleet-host-control, Fleet only
SSH = "/usr/bin/ssh"
_LOG = logging.getLogger(__name__)
_TARGET = re.compile(r"^[a-z_][a-z0-9_-]{0,31}@[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")
# Exit codes of deploy/site/rosy-host-control; anything else is HOST_HELPER_FAILED.
_HELPER_EXIT = {3: "REBOOT_ALREADY_SCHEDULED", 4: "NO_HOST_CONTROL_REBOOT", 5: "NO_STORAGE_SERVICE",
                6: "ARM_SESSION_ACTIVE", 7: "HOST_JOBS_ACTIVE"}


class HostControlError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def read_json_object(path: Path) -> dict | None:
    """Read one status object. Missing, unreadable, or non-object is absence, not health."""
    try:
        body = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return body if isinstance(body, dict) else None


STUCK_AFTER_S = 6 * 3600  # the same bound as tools/remote/update_status.py
_WORD = re.compile(r"^[A-Za-z0-9_.:@-]{1,80}$")


def _word(value):
    return value if isinstance(value, str) and _WORD.fullmatch(value) else None


def _number(value):
    return value if type(value) in (int, float) and value == value and abs(value) != float("inf") else None


# Update channels whose stall becomes one row in the console queue (the D-632 alert surface). 3600 s is six
# missed 10-minute runs, so a single transient or rate_limited run never alerts.
ALERT_UNITS = frozenset({"rosy-omx-devices-autoupdate.service"})
ALERT_AFTER_ENV = "ROSY_FLEET_UPDATE_ALERT_AFTER_S"
ALERT_AFTER_S = 3600.0


def _alert_after_s() -> float:
    try:
        value = float(os.environ.get(ALERT_AFTER_ENV) or ALERT_AFTER_S)
    except ValueError:
        value = 0.0
    if 0 < value < float("inf"):
        return value
    _LOG.warning("%s is not a positive number; using %s", ALERT_AFTER_ENV, ALERT_AFTER_S)
    return ALERT_AFTER_S


def _update_alert(last: dict, healthy: float | None, at: float, after_s: float) -> dict | None:
    """No healthy step (switched / up_to_date) for after_s, whatever the reason, including an updater that
    logs nothing. A stale green-main pointer alerts at once: the cell already waited platform_max_age_s.
    shortcut: healthy_at comes from the report's last 400 journal lines (about 8 h), then reads as unknown."""
    age = None if healthy is None else max(0, int(at - healthy))
    pointer_stale = last.get("step") == "transient" and last.get("reason") == "stale"
    if age is not None and age < after_s and not pointer_stale:
        return None
    return {"age_s": age}


def update_summary(guard: dict | None, now: float, *, reasons: bool = False) -> dict:
    """D-871: each PC's update channels for every signed-in role: state and release; the stalled channel's
    reason code only with reasons=True (operators).

    `ok` = a healthy step within STUCK_AFTER_S, `off` = its timer is not enabled, `stuck` = otherwise.
    A PC whose report is missing or malformed is `unknown`; nothing is inferred from silence."""
    hosts = []
    after_s = _alert_after_s()
    for name, row in sorted((guard or {}).items()):
        if not isinstance(row, dict) or "updates" not in row:
            continue  # robots and older guard rows are not update hosts
        report = row["updates"]
        if not isinstance(report, dict) or not isinstance(report.get("updaters"), list):
            hosts.append({"host": name, "state": "unknown", "gate": None, "channels": []})
            continue
        channels = []
        for item in report["updaters"]:
            if not isinstance(item, dict) or not _word(item.get("unit")):
                continue
            last = item.get("last") if isinstance(item.get("last"), dict) else {}
            healthy = _number(item.get("healthy_at"))
            fresh = healthy is not None and now - healthy <= STUCK_AFTER_S
            state = "off" if item.get("timer") != "enabled" else "ok" if fresh else "stuck"
            channel = {"unit": item["unit"], "state": state, "release": _word(last.get("release")),
                       "at": _number(last.get("at"))}
            # A frozen or missing gate is a deliberate or separately shown stop; judged at the report's own time.
            if item["unit"] in ALERT_UNITS and item.get("timer") == "enabled" and report.get("gate") == "open":
                alert = _update_alert(last, healthy, _number(report.get("time")) or now, after_s)
                if alert:
                    if reasons:
                        alert["reason"] = _word(last.get("reason")) or _word(last.get("step"))
                    channel["alert"] = alert
            channels.append(channel)
        stack = report.get("site_stack") if isinstance(report.get("site_stack"), dict) else None
        if stack:
            channels.append({"unit": "rosy-site-autoupdate", "state": "ok" if _word(stack.get("result")) else "unknown",
                             "release": _word(stack.get("current")), "at": None})
        worst = ("stuck" if any(c["state"] == "stuck" for c in channels)
                 else "frozen" if report.get("gate") == "frozen" else "ok")
        gate = report.get("gate") if report.get("gate") in ("open", "frozen", "missing") else None
        hosts.append({"host": name, "state": worst, "gate": gate, "time": _number(report.get("time")),
                      "channels": channels})
    return {"hosts": hosts}


def catalogue() -> dict:
    hosts = []
    for host, units in HOSTS.items():
        unit_actions = set().union(*units.values()) if units else set()
        hosts.append({
            "host": host,
            "actions": ["reboot", "reboot-over-jobs", "cancel-reboot", *sorted(HOST_ACTIONS.get(host, ())),
                        *sorted(unit_actions)],
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
        if action not in HOSTS[host].get(unit, ()):
            raise HostControlError("UNIT_NOT_ALLOWED")
    elif unit is not None:
        raise HostControlError("UNIT_NOT_ALLOWED")
    elif action in ("clean-storage", "root-maintenance") and action not in HOST_ACTIONS.get(host, ()):
        raise HostControlError("ACTION_NOT_ALLOWED")
    argv = (REBOOT_WORD.get(action, action),) if unit is None else (action, unit)
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
