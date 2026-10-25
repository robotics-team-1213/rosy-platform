#!/usr/bin/env python3
"""Stage the image-owned firstboot closure before the root filesystem is sealed."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "native"))
from os_storage_dispatch import FIRST_BOOT_FILES, trusted_files


def stage(prefix: Path) -> None:
    prefix = Path(prefix).absolute()
    owner = prefix.stat().st_uid
    trusted_files(prefix, FIRST_BOOT_FILES, owner)
    destination = prefix / "os-bootstrap"
    if destination.is_symlink():
        raise ValueError("OS bootstrap directory is a symlink")
    if destination.exists():
        trusted_files(destination, (), owner)
    for name in FIRST_BOOT_FILES:
        target = destination / name
        if target.exists() or target.is_symlink():
            raise ValueError("firstboot staging destination already exists")
        for parent in target.parents:
            if parent == prefix:
                break
            if parent.is_symlink() or parent.exists() and (
                    not parent.is_dir() or parent.stat().st_uid != owner or parent.stat().st_mode & 0o022):
                raise ValueError("firstboot staging parent is unsafe")
    for name in FIRST_BOOT_FILES:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        shutil.copyfile(prefix / name, target)
        target.chmod(0o755 if name.endswith(".sh") else 0o644)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    args = parser.parse_args(argv)
    stage(args.prefix)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
