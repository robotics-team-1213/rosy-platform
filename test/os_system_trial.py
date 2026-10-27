"""Fixture-only boot observations; offline validation never replaces PID1 deadline evidence."""
import json
import os
from pathlib import Path
import subprocess
import uuid

UNIT = "rosy-system-trial-probe.service"
PREFIX = "ROSY_SYSTEM_TRIAL "
FIELDS = {"schema_version", "boot_id", "root_device", "root_argument", "slot", "os_layout",
          "device_tree_partition", "tryboot", "deadline_active", "deadline_timer"}


def _read(root, relative, limit):
    with (root / relative).open("rb") as stream:
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise ValueError("fixture observation exceeds its bound")
    return value


def _argument(words, name):
    values = [word.split("=", 1)[1] for word in words if word.startswith(name + "=")]
    if len(values) != 1:
        raise ValueError("fixture kernel argument is missing or ambiguous")
    return values[0]


def capture(root=Path("/"), *, run=subprocess.check_output):
    root = Path(root)
    if os.environ.get("ROSY_OS_GUEST") != "1" or os.geteuid() != 0:
        raise ValueError("trial probe requires an explicitly owned guest")
    instance = _read(root, "etc/rosy-system-guest-id", 128).decode("ascii").strip()
    if (not instance.startswith("rosy-system-")
            or str(uuid.UUID(instance.removeprefix("rosy-system-"))) != instance.removeprefix("rosy-system-")
            or _read(root, "var/lib/cloud/data/instance-id", 128).decode("ascii").strip() != instance
            or _read(root, "proc/1/comm", 128).strip() != b"systemd"
            or run(["uname", "-m"], timeout=30).strip() != b"aarch64"):
        raise ValueError("trial probe owned guest identity differs")
    words = _read(root, "proc/cmdline", 4096).decode("ascii").split()
    boot = _read(root, "proc/sys/kernel/random/boot_id", 128).decode("ascii").strip()
    if str(uuid.UUID(boot)) != boot:
        raise ValueError("trial probe boot UUID differs")
    dt = {}
    for name in ("partition", "tryboot"):
        raw = _read(root, "proc/device-tree/chosen/bootloader/" + name, 4)
        if len(raw) != 4:
            raise ValueError("trial probe DT property differs")
        dt[name] = int.from_bytes(raw, "big")
    return dict(schema_version=1, boot_id=boot,
                root_device=run(["findmnt", "-n", "-o", "SOURCE", "/"], timeout=30).decode("ascii").strip(),
                root_argument="root=" + _argument(words, "root"), slot=_argument(words, "rauc.slot"),
                os_layout=_argument(words, "rosy.os_layout"), device_tree_partition=dt["partition"], tryboot=dt["tryboot"],
                deadline_active=run(["systemctl", "is-active", "rosy-os-trial-deadline.timer"], timeout=30).strip() == b"active",
                deadline_timer=_read(root, "etc/systemd/system/rosy-os-trial-deadline.timer", 8192).decode("utf-8"))


def validate(raw, *, target_slot, root_uuid, previous_boot):
    from os_system_vm import pid1_start
    if (target_slot not in ("a", "b") or str(uuid.UUID(root_uuid)) != root_uuid
            or str(uuid.UUID(previous_boot)) != previous_boot or len(raw) > 1024**2):
        raise ValueError("invalid expected trial evidence")
    records, boots = [], set()
    for line in raw.splitlines():
        event = json.loads(line)
        if not isinstance(event, dict):
            raise ValueError("trial journal entry is not an object")
        event_boot = event.get("_BOOT_ID")
        if not isinstance(event_boot, str) or uuid.UUID(event_boot).hex != event_boot:
            raise ValueError("trial journal boot UUID differs")
        boots.add(event_boot)
        message = event.get("MESSAGE", "")
        if isinstance(message, str) and message.startswith(PREFIX):
            if event.get("_SYSTEMD_UNIT") != UNIT or event.get("_UID") != "0":
                raise ValueError("trial probe sender differs")
            facts = json.loads(message.removeprefix(PREFIX))
            if (not isinstance(facts, dict) or set(facts) != FIELDS
                    or event_boot != uuid.UUID(facts["boot_id"]).hex):
                raise ValueError("trial probe boot binding differs")
            records.append(facts)
    if len(records) != 1:
        raise ValueError("trial probe must provide exactly one observation")
    facts = records[0]
    boot = facts["boot_id"]
    expected = dict(schema_version=1, root_device="/dev/vdc4" if target_slot == "a" else "/dev/vdc5",
                    root_argument="root=PARTUUID=" + root_uuid, slot=target_slot, os_layout="ab-v2",
                    device_tree_partition=2 if target_slot == "a" else 3, tryboot=1, deadline_active=True)
    if (not isinstance(boot, str) or str(uuid.UUID(boot)) != boot or boot == previous_boot or boots != {uuid.UUID(boot).hex}
            or any(facts[key] != value or type(facts[key]) is not type(value)
                   for key, value in expected.items() if key != "tryboot")
            or not isinstance(facts["deadline_timer"], str)
            or [line.strip() for line in facts["deadline_timer"].splitlines()
                if line.strip().startswith("OnBootSec=")] != ["OnBootSec=180s"]):
        raise ValueError("trial observation differs from its expected kernel boot")
    pid1_start(raw, "rosy-os-trial-deadline.service", boot, 180_000_000)
    return facts


if __name__ == "__main__":
    print(PREFIX + json.dumps(capture(), sort_keys=True), flush=True)
