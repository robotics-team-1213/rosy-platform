"""Read-only physical recovery pages; credentials never enter logs or CORE."""
import math
import os
from pathlib import Path
import re
import stat

OWNER_UID = 0
DISPLAY = "run/rosy-boot/recovery-display.txt"
FIELDS = {"DEVICE", "URL", "CODE", "SHA256", "EXPIRES_MONOTONIC", "BOOT_ID", "AP_EPOCH"}
CODE = re.compile(r"[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}-[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}\Z")
PIN = re.compile(r"(?:[0-9A-F]{2}:){31}[0-9A-F]{2}\Z")


def _read(root, relative, *, limit, private=False):
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = Path(relative).parts
        for part in parts[:-1]:
            info = os.fstat(descriptor)
            if info.st_uid != OWNER_UID or info.st_mode & 0o022:
                return ""
            following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        info = os.fstat(descriptor)
        if info.st_uid != OWNER_UID or info.st_mode & 0o022:
            return ""
        file_descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                  dir_fd=descriptor)
        with os.fdopen(file_descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != OWNER_UID or info.st_nlink != 1
                    or info.st_size > limit or (private and stat.S_IMODE(info.st_mode) != 0o640)):
                return ""
            raw = handle.read(limit + 1)
            return raw.decode("ascii") if len(raw) <= limit else ""
    finally:
        os.close(descriptor)


def read_page(root, view, now):
    """Five-second code, full fingerprint, original AP-card phases for this boot/AP."""
    try:
        network = view.get("network") or {}
        if (network.get("mode") != "ap" or not network.get("epoch")
                or str(view.get("stage", "")).split(":", 1)[0] not in {"FAILED", "BOOTING"}):
            return None
        lines = _read(root, DISPLAY, limit=1024, private=True).splitlines()
        if len(lines) != len(FIELDS):
            return None
        fields = dict(line.split("=", 1) for line in lines)
        if fields.keys() != FIELDS:
            return None
        if (not re.fullmatch(r"rosy-pinky-[a-hj-km-np-z2-9]{4}", fields["DEVICE"])
                or not re.fullmatch(r"[A-Za-z0-9-]{1,64}", fields["BOOT_ID"])):
            return None
        expires = float(fields["EXPIRES_MONOTONIC"])
        if (not math.isfinite(now) or not math.isfinite(expires) or not now < expires <= now + 600
                or fields["DEVICE"] != view.get("device_name")
                or fields["URL"] != f"https://{network.get('address')}:8443"
                or fields["AP_EPOCH"] != str(network["epoch"])
                or fields["BOOT_ID"] != _read(root, "proc/sys/kernel/random/boot_id", limit=128).strip()
                or not CODE.fullmatch(fields["CODE"]) or not PIN.fullmatch(fields["SHA256"])):
            return None
        phase = int((now - (expires - 600)) // 5) % 3
        if phase == 2:
            return None
        if phase == 1:
            fingerprint = fields["SHA256"].replace(":", "")
            return {"title": "SHA256 2/3", "lines": [fingerprint[index:index + 16] for index in range(0, 64, 16)]}
        return {"title": "Wi-Fi recovery 1/3", "lines": [fields["DEVICE"], fields["URL"],
                "Compare SHA256 first", "Trust this certificate", "Code: " + fields["CODE"]]}
    except (OSError, UnicodeError, ValueError, TypeError, KeyError):
        return None
