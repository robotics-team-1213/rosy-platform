#!/usr/bin/env python3
"""Configure an offline A/B root after its partition identities have been assigned."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "native"))
from os_state_io import _write_atomic
from os_state_layout import LAYOUT_FIELDS, _guid, _object, _path, _read
from os_storage_dispatch import BOOTSTRAP_FILES, FIRST_BOOT_FILES, trusted_files
from os_payload_compatibility import verify_contract

OVERRIDES = {"rosy-os-firstboot.conf": "rosy-first-boot.service.d/10-rosy-os.conf",
             "rosy-os-recover.conf": "rosy-release-recover.service.d/10-rosy-os.conf",
             "rosy-os-storage.conf": "rosy-os-storage.service.d/10-rosy-os.conf",
             "rosy-os-projection.conf": "rosy-sd-provision.service.d/10-rosy-os.conf",
             "rosy-os-tailnet.conf": "rosy-os-tailnet.service.d/10-rosy-os.conf"}


def configure(root: Path, release_id: str) -> None:
    root = Path(root).absolute()
    if root.is_symlink() or root == Path(root.anchor):
        raise ValueError("an offline image root is required")
    owner = root.stat().st_uid
    slot = _object(_read(_path(root, "etc/rosy/os-slot.json"), 8192, owner), LAYOUT_FIELDS)
    guids = [_guid(slot[name]) for name in ("root_partuuid", "data_partuuid", "provision_partuuid")]
    if slot["slot"] not in ("a", "b") or len(set(guids)) != 3:
        raise ValueError("invalid offline A/B partition identity")
    if not isinstance(release_id, str) or not re.fullmatch(r"[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}", release_id):
        raise ValueError("invalid factory release identity")
    prefix = root / "opt/rosy/os-bootstrap"
    trusted_files(prefix, BOOTSTRAP_FILES, owner)
    trusted_files(prefix, FIRST_BOOT_FILES, owner)
    verify_contract(_path(root, "opt/rosy/releases/" + release_id + "/deploy/robot/native"),
                    state_schema=slot["state_schema"])
    sums = _read(_path(root, "opt/rosy/releases/" + release_id + "/SHA256SUMS"), 16 * 1024 * 1024, owner)
    record = dict(schema_version=1, release_id=release_id, checksums_sha256=hashlib.sha256(sums).hexdigest())
    changes = {"etc/rosy/os-factory-release.json": (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")}
    for source, destination in OVERRIDES.items():
        changes["etc/systemd/system/" + destination] = _read(prefix / "native-runtime" / source, 8192, owner)
    targets = {}
    for relative, data in changes.items():
        target = _path(root, relative)
        if target.exists():
            if target.stat().st_nlink != 1:
                raise ValueError("OS boot configuration is hard-linked")
            if _read(target, 8192, owner) != data:
                # Descriptor serialization is not significant; the pinned fields are.
                if (relative != "etc/rosy/os-factory-release.json"
                        or _object(_read(target, 8192, owner), set(record)) != record):
                    raise ValueError("existing OS boot configuration differs")
        targets[relative] = target
    for relative, target in targets.items():
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        _write_atomic(target, changes[relative].decode("utf-8"), 0o644)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    args = parser.parse_args(argv)
    configure(args.root, args.release_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
