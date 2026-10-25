"""Standalone early-boot dispatcher; A/B admission belongs to this OS image."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys

BOOTSTRAP_FILES = ("os_state_storage.py", "os_state_firstboot.py", "os_state_layout.py", "first_boot_runtime.py",
                   "os_state_accounts.py", "os_state_files.py", "os_state_config.py")


def marked(root: Path) -> bool:
    descriptor = root / "etc/rosy/os-slot.json"
    if descriptor.exists() or descriptor.is_symlink():
        return True
    try:
        descriptor = os.open(root / "proc/cmdline", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return False
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("kernel command line is not regular")
        raw = stream.read(16385)
    if len(raw) > 16384:
        raise ValueError("kernel command line exceeds limit")
    return any(word.startswith("rosy.os_layout=") for word in raw.decode("ascii").split())


def bootstrap_entry() -> Path:
    prefix = Path(__file__).absolute().parent.parent
    directory = prefix / "os-bootstrap"
    owner = prefix.stat().st_uid
    for path in (directory, *(directory / name for name in BOOTSTRAP_FILES)):
        info = path.lstat()
        valid = stat.S_ISDIR(info.st_mode) if path == directory else stat.S_ISREG(info.st_mode)
        if not valid or info.st_uid != owner or info.st_mode & 0o022:
            raise ValueError("OS bootstrap owner/type/permissions differ")
    return directory / "os_state_storage.py"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/"))
    parser.add_argument("--no-pending-maintenance", action="store_true")
    parser.add_argument("--tailnet", action="store_true")
    args = parser.parse_args(argv)
    try:
        if marked(args.root):
            entry = bootstrap_entry()
            command = [sys.executable, "-I", "-B", str(entry), "--root", str(args.root)]
            if args.no_pending_maintenance:
                command.append("--no-pending-maintenance")
            if args.tailnet:
                command.append("--tailnet")
            os.execv(sys.executable, command)
        print(json.dumps({"schema_version": 1, "phase": "LEGACY"}, sort_keys=True))
        return 0
    except (OSError, ValueError):
        print(json.dumps({"schema_version": 1, "phase": "HOLD", "reason": "OS_STATE_HOLD"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
