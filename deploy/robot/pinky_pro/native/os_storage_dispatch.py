"""Standalone early-boot dispatcher; A/B admission belongs to this OS image."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys

BOOTSTRAP_FILES = ("os_state_storage.py", "os_state_firstboot.py", "os_state_layout.py", "os_state_io.py",
                   "os_state_accounts.py", "os_state_files.py", "os_state_config.py", "os_state_ready.py")
FIRST_BOOT_NATIVE = (*BOOTSTRAP_FILES, "first_boot_runtime.py", "first_boot_support.py", "network_handoff.py", "operator_keys.py",
                     "native_release.py", "signing.py", "network_transaction.py", "network.py",
                     "nm_network.py", "rosy_claim.py", "rosy-os-firstboot.conf", "os_factory_release.py",
                     "os_boot_recover.py", "image-layer-reconcile.py", "sync-image-layer.py",
                     "image_layer_boot.py", "image_layer_files.py", "rosy-os-recover.conf")
FIRST_BOOT_FILES = ("first-boot/rosy-first-boot.py", "first-boot/rosy-first-boot.sh", "deploy/sd/personalization.py",
                    *("native-runtime/" + name for name in FIRST_BOOT_NATIVE))


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


def trusted_files(directory: Path, names, owner: int) -> None:
    for name in ("", *names):
        parts = Path(name).parts
        for index in range(len(parts) + 1):
            path = directory.joinpath(*parts[:index])
            info = path.lstat()
            final_file = bool(parts) and index == len(parts)
            valid = stat.S_ISREG(info.st_mode) if final_file else stat.S_ISDIR(info.st_mode)
            if not valid or info.st_uid != owner or info.st_mode & 0o022:
                raise ValueError("OS bootstrap owner/type/permissions differ")


def bootstrap_entry() -> Path:
    prefix = Path(__file__).absolute().parent.parent
    directory = prefix / "os-bootstrap"
    trusted_files(directory, BOOTSTRAP_FILES, prefix.stat().st_uid)
    return directory / "os_state_storage.py"


def first_boot_entry() -> Path:
    prefix = Path(__file__).absolute().parent.parent
    directory = prefix / "os-bootstrap"
    trusted_files(directory, FIRST_BOOT_FILES, prefix.stat().st_uid)
    return directory / "first-boot/rosy-first-boot.sh"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/"))
    parser.add_argument("--no-pending-maintenance", action="store_true")
    parser.add_argument("--tailnet", action="store_true")
    parser.add_argument("--projected", action="store_true")
    parser.add_argument("--first-boot", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.first_boot:
            if (not marked(args.root) or args.tailnet or args.projected or args.no_pending_maintenance):
                raise ValueError("firstboot dispatch requires an unambiguous A/B identity")
            entry = first_boot_entry()
            os.environ["ROSY_ROOT"] = str(args.root)
            os.execv(str(entry), [str(entry)])
        if marked(args.root):
            entry = bootstrap_entry()
            command = [sys.executable, "-I", "-B", str(entry), "--root", str(args.root)]
            if args.no_pending_maintenance:
                command.append("--no-pending-maintenance")
            if args.tailnet:
                command.append("--tailnet")
            if args.projected:
                command.append("--projected")
            os.execv(sys.executable, command)
        print(json.dumps({"schema_version": 1, "phase": "LEGACY"}, sort_keys=True))
        return 0
    except (OSError, ValueError):
        print(json.dumps({"schema_version": 1, "phase": "HOLD", "reason": "OS_STATE_HOLD"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
