"""OS-owned motion gate reconstructed from durable state before runtime starts."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from os_bootloader import _snapshot
from os_state_io import _write_atomic
from os_state_layout import _path, _read

ENVIRONMENT = "run/rosy-os-update/motion.env"
INHIBITED = b"ROSY_IO_DRIVE_ENABLED=false\n"


def _environment(root: Path) -> Path:
    directory = _path(root, "run/rosy-os-update")
    if stat.S_IMODE(directory.stat().st_mode) != 0o700:
        raise ValueError("OS_MOTION_HOLD: runtime directory is not private")
    path = _path(root, ENVIRONMENT)
    if path.exists():
        info = path.stat()
        if (info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600
                or _read(path, 128, root.stat().st_uid) != INHIBITED):
            raise ValueError("OS_MOTION_HOLD: runtime environment differs")
    return path


def reconcile(root: Path) -> bool:
    """Return whether inhibited; unknown boot/state leaves false and raises."""
    _path(root, "run/rosy-os-update").mkdir(parents=True, exist_ok=True, mode=0o700)
    path = _environment(root)
    _write_atomic(path, INHIBITED, 0o600)
    _, state, _ = _snapshot(root)
    if state["pending"] is not None:
        return True
    path.unlink()
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return False


def allow_navigation(root: Path) -> None:
    _, state, _ = _snapshot(root)
    if state["pending"] is not None:
        raise ValueError("OS_MOTION_HOLD: OS update is pending")


def require_inhibited(root: Path) -> None:
    """RAUC's restricted namespace may read this gate but cannot publish it."""
    _, state, _ = _snapshot(root)
    if state["pending"] is None or _read(_environment(root), 128, root.stat().st_uid) != INHIBITED:
        raise ValueError("OS_MOTION_HOLD: pending transaction and drive inhibition are required")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("reconcile", "navigation", "inhibited"))
    args = parser.parse_args(argv)
    try:
        if args.command == "reconcile":
            reconcile(Path("/"))
        elif args.command == "inhibited":
            require_inhibited(Path("/"))
        else:
            allow_navigation(Path("/"))
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
