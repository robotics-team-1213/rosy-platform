"""Read-only, boot-bound firmware/PID1 watchdog admission; never open /dev/watchdog."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

from os_bootloader import boot_facts
from os_state_layout import _pairs, _path, _read, _sysfs_read

IDENTITY = "Broadcom BCM2835 Watchdog timer"
BOOT_CONFIG = "# ROSY A/B kernel watchdog\n[all]\nkernel_watchdog_timeout=180\n"


def render_boot_config(raw: bytes) -> str:
    if type(raw) is not bytes or len(raw) > 65536 or b"\0" in raw:
        raise ValueError("invalid watchdog boot configuration")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("invalid watchdog boot configuration") from exc
    if "# ROSY A/B kernel watchdog" in text:
        if text.endswith(BOOT_CONFIG) and text.count("# ROSY A/B kernel watchdog") == 1:
            return text
        raise ValueError("watchdog configuration already differs")
    return text.rstrip("\n") + "\n" + BOOT_CONFIG


def _run(argv, timeout=10):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def _call(run, argv, limit):
    result = run(argv, timeout=10)
    if result.returncode or len(result.stdout.encode("utf-8")) > limit or len(result.stderr) > 16384:
        raise ValueError("watchdog observation command failed or exceeded its limit")
    return result.stdout


def _journal(raw: str, boot_id: str) -> None:
    using = re.compile(r"Using hardware watchdog '" + re.escape(IDENTITY) + r"', version [0-9a-f]+, device /dev/watchdog0")
    opened = armed = False
    previous = -1
    for line in raw.splitlines():
        row = json.loads(line, object_pairs_hook=_pairs)
        if (not isinstance(row, dict) or row.get("_BOOT_ID") != boot_id.replace("-", "")
                or row.get("_PID") != "1" or row.get("_UID") != "0" or row.get("_COMM") != "systemd"):
            raise ValueError("watchdog journal is not from this boot's PID1")
        stamp, message = row.get("__MONOTONIC_TIMESTAMP"), row.get("MESSAGE")
        if not isinstance(stamp, str) or not re.fullmatch(r"[0-9]{1,20}", stamp) or int(stamp) <= previous:
            raise ValueError("watchdog journal ordering is unknown")
        previous = int(stamp)
        if not isinstance(message, str):
            raise ValueError("watchdog journal message is invalid")
        if using.fullmatch(message):
            opened, armed = True, False
        elif opened and message == "Watchdog running with a timeout of 10s.":
            armed = True
        elif opened and not armed and message == "Watchdog pretimeout is disabled.":
            pass
        else:
            opened = armed = False
    if not opened or not armed:
        raise ValueError("PID1 hardware open/enable evidence is missing or superseded")


def admit(root: Path = Path("/"), *, run=_run) -> dict:
    try:
        if root != Path("/") and run is _run:
            raise ValueError("live watchdog observations require the real root or an explicit test runner")
        facts = boot_facts(root)
        if facts["tryboot"]:
            raise ValueError("watchdog auto-arm admission requires the normal source boot")
        owner = root.stat().st_uid
        config = _read(_path(root, "boot/firmware/config.txt"), 65536, owner).decode("utf-8")
        if not config.endswith(BOOT_CONFIG) or config.count("# ROSY A/B kernel watchdog") != 1:
            raise ValueError("firmware watchdog configuration differs")
        command = _read(_path(root, "proc/cmdline"), 16384, owner).decode("ascii").split()
        saved = _read(_path(root, "boot/firmware/cmdline.txt"), 16384, owner).decode("ascii").split()
        if ([w for w in command if w.startswith("watchdog.open_timeout=")] != ["watchdog.open_timeout=180"]
                or any(w.startswith("watchdog.open_timeout=") for w in saved)):
            raise ValueError("firmware-injected watchdog handoff was not observed")
        for path, expected in (
            ("sys/module/watchdog/parameters/open_timeout", "180"),
            ("sys/class/watchdog/watchdog0/state", "active"),
            ("sys/class/watchdog/watchdog0/timeout", "10"),
            ("sys/class/watchdog/watchdog0/identity", IDENTITY),
        ):
            if _sysfs_read(root, root / path).decode("ascii").strip() != expected:
                raise ValueError("kernel watchdog observation differs")
        keys = ("RuntimeWatchdogUSec", "RebootWatchdogUSec", "WatchdogDevice", "Version")
        raw = _call(run, ["/usr/bin/systemctl", "show", *("--property=" + key for key in keys)], 4096)
        properties = _pairs([line.split("=", 1) for line in raw.splitlines()])
        if (set(properties) != set(keys) or properties["RuntimeWatchdogUSec"] != "10s"
                or properties["RebootWatchdogUSec"] != "10s" or properties["WatchdogDevice"] != "/dev/watchdog0"
                or not re.fullmatch(r"255(?:[. -].*)?", properties["Version"])):
            raise ValueError("effective PID1 watchdog configuration or supported version differs")
        journal = _call(run, ["/usr/bin/journalctl", "--boot=" + facts["boot_id"].replace("-", ""),
            "--output=json", "--no-pager", "-n", "64", "--grep=watchdog|Watchdog", "_PID=1"], 262144)
        _journal(journal, facts["boot_id"])
        return dict(schema_version=1, boot_id=facts["boot_id"], device="/dev/watchdog0",
                    identity=IDENTITY, timeout_seconds=10, kernel_open_timeout_seconds=180)
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, subprocess.SubprocessError) as exc:
        raise ValueError(f"OS_WATCHDOG_HOLD: {exc}") from exc
