#!/usr/bin/env python3
"""Quarantine an old Pi identity, then apply a new verified provisioning bundle.

This is an operator-only recovery path for a moved SD. CORE and hardware
services must be stopped. The site Wi-Fi profile remains in place. The old
device's CORE data and host identity records stay under a root-only archive.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

try:
    from deploy.sd.personalization import DeviceIdentity, validate_device_identity, validate_provision_bundle
except ModuleNotFoundError:
    sys.path.insert(0, "/opt/rosy")
    from deploy.sd.personalization import DeviceIdentity, validate_device_identity, validate_provision_bundle


SERIAL = re.compile(r"^[0-9a-f]{8,32}$")
ARCHIVE_ROOT = "var/lib/rosy/previous-devices"
SOURCES = (
    "var/lib/rosy/core",
    "var/log/rosy-core",
    "etc/rosy/device-identity.json",
    "etc/rosy/runtime.env",
    "etc/rosy/fleet-bootstrap.json",
    "etc/rosy/ap-credentials.json",
    "var/lib/rosy/provisioning",
)


def _read(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"required regular file is unavailable: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"record is not an object: {path}")
    return data


def _atomic_json(path: Path, value: dict) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _archive_for(root: Path, fresh_uid: str, serial: str) -> Path | None:
    base = root / ARCHIVE_ROOT
    if base.is_symlink() or not base.is_dir():
        return None
    matches = []
    for candidate in base.iterdir():
        manifest = candidate / "rebind.json"
        if candidate.is_symlink() or not manifest.is_file():
            continue
        record = _read(manifest)
        if record.get("new_device_uid") == fresh_uid and record.get("hardware_serial") == serial:
            matches.append(candidate)
    if len(matches) > 1:
        raise ValueError("more than one previous-device archive matches this registration")
    return matches[0] if matches else None


def quarantine_previous(root: Path, bundle: Path, hardware_serial: str) -> Path:
    """Move old identity and CORE data aside; safe to retry after a partial move."""
    root = Path(root)
    serial = hardware_serial.strip().lower()
    if not SERIAL.fullmatch(serial):
        raise ValueError("new board hardware serial is invalid")
    fresh = _read(bundle)
    validate_provision_bundle(fresh)
    new_identity = validate_device_identity(DeviceIdentity(**fresh["device_identity"]))
    completion_path = root / "var/lib/rosy/provisioning/complete.json"
    existing_archive = _archive_for(root, new_identity.device_uid, serial)
    if existing_archive is not None:
        manifest = _read(existing_archive / "rebind.json")
        archive = existing_archive
    else:
        previous = _read(completion_path)
        binding = _read(root / "var/lib/rosy/provisioning/hardware-binding.json")
        old_identity = validate_device_identity(DeviceIdentity(**_read(root / "etc/rosy/device-identity.json")))
        if (previous.get("hardware_serial") == serial
                or binding != {"hardware_serial": previous.get("hardware_serial"),
                               "device_uid": previous.get("device_uid")}
                or old_identity.device_uid != previous.get("device_uid")
                or old_identity.device_name != previous.get("device_name")
                or new_identity.device_uid == old_identity.device_uid
                or new_identity.device_name == old_identity.device_name
                or fresh["dds"]["robot_number"] == previous.get("dds", {}).get("robot_number")):
            raise ValueError("old and new device identities are not safely distinct")
        if fresh["network"]["ssid"] != previous.get("network", {}).get("ssid"):
            raise ValueError("new registration must keep the existing site Wi-Fi")
        wifi = root / "etc/NetworkManager/system-connections/rosy-site-sta.nmconnection"
        if wifi.is_symlink() or not wifi.is_file():
            raise ValueError("existing site Wi-Fi profile is unavailable")
        pending = root / "var/lib/rosy/provisioning/new-device-setup.json"
        if pending.exists():
            candidate = _read(pending)
            if (candidate.get("hardware_serial") != serial
                    or candidate.get("prior_device_uid") != old_identity.device_uid
                    or candidate.get("device_identity") != fresh["device_identity"]):
                raise ValueError("new registration differs from the staged identity")
        base = root / ARCHIVE_ROOT
        if base.is_symlink():
            raise ValueError("previous-device archive root is a symlink")
        base.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(base, 0o700)
        archive = base / old_identity.device_uid
        if archive.exists() or archive.is_symlink():
            raise ValueError("previous-device archive path already exists")
        archive.mkdir(mode=0o700)
        manifest = {
            "schema_version": 1,
            "previous_device_uid": old_identity.device_uid,
            "previous_hardware_serial": previous["hardware_serial"],
            "new_device_uid": new_identity.device_uid,
            "hardware_serial": serial,
        }
        _atomic_json(archive / "rebind.json", manifest)

    if manifest.get("schema_version") != 1 or manifest.get("new_device_uid") != new_identity.device_uid:
        raise ValueError("previous-device archive does not match this registration")
    current_binding_path = root / "var/lib/rosy/provisioning/hardware-binding.json"
    new_install_started = current_binding_path.is_file() and _read(current_binding_path) == {
        "hardware_serial": serial, "device_uid": new_identity.device_uid,
    }
    current_identity_path = root / "etc/rosy/device-identity.json"
    if new_install_started and current_identity_path.is_file():
        if _read(current_identity_path) != fresh["device_identity"]:
            raise ValueError("new device identity differs from the registration bundle")
    for relative in SOURCES:
        source = root / relative
        destination = archive / relative
        if source.is_symlink() or destination.is_symlink():
            raise ValueError(f"device state path is a symlink: {relative}")
        if destination.exists():
            if source.exists():
                if not new_install_started:
                    raise ValueError(f"both old and new state exist: {relative}")
                # First boot may have created fresh state before Wi-Fi came up.
                # The old state is already safely inside the archive; retain
                # the new state so the one-time applicator can finish.
            continue
        if not source.exists():
            if relative.endswith(("/core", "/rosy-core", "/ap-credentials.json")):
                continue
            raise ValueError(f"old device state is missing: {relative}")
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.replace(source, destination)
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--first-boot-script", type=Path,
                        default=Path("/opt/rosy/first-boot/rosy-first-boot.py"))
    args = parser.parse_args()
    for unit in ("rosy-core.service", "rosy-io.service", "rosy-navigation.service"):
        state = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True, check=False)
        if state.stdout.strip() == "active":
            print(f"rebind refused: {unit} is active", file=sys.stderr)
            return 1
    serial_path = Path("/sys/firmware/devicetree/base/serial-number")
    serial = serial_path.read_bytes().replace(b"\0", b"").decode("ascii").strip()
    try:
        archive = quarantine_previous(Path("/"), args.bundle, serial)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"rebind refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    result = subprocess.run([sys.executable, "-B", str(args.first_boot_script),
                             "--bundle", str(args.bundle), "--network", "check"], check=False)
    if result.returncode:
        print(f"previous device archived at {archive}; new provisioning remains incomplete", file=sys.stderr)
        return result.returncode
    print(f"new device provisioned; previous device archived at {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
