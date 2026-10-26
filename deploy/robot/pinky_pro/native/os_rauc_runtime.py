"""Prepare transaction-local RAUC configuration; this grants no install or boot authority."""
from __future__ import annotations

from pathlib import Path

from os_media import capture
from os_rauc import CMS_KEY, verify_bundle
from os_state_layout import COMMON
from os_update_manifest import COMPATIBLE


def prepare(root: Path, bundle: Path, raw_metadata: bytes, signature: str) -> dict:
    """Reverify bundle and recapture media; controller must hold locks and recheck before starting RAUC."""
    root = Path(root).absolute()
    if any(char in str(root) for char in "\r\n\0%"):
        raise ValueError("OS_RAUC_RUNTIME_HOLD: unsafe runtime root")
    verified = verify_bundle(root, bundle, raw_metadata, signature)
    media = capture(root)
    target = "b" if media["slot"] == "a" else "a"
    parts = media["partitions"]
    geometry = {part["role"]: part for part in media["layout"]["partitions"]}
    for role, field in (("root_", "rootfs_bytes"), ("boot_", "boot_bytes")):
        if verified["metadata"][field] > geometry[role + target]["size_lba"] * 512:
            raise ValueError("OS_RAUC_RUNTIME_HOLD: candidate exceeds inactive partition capacity")
    runtime = root / "run/rosy-os-update/rauc"
    configuration = (f"[system]\ncompatible={COMPATIBLE}\nbootloader=custom\n"
        f"activate-installed=false\nbundle-formats=verity\nmountprefix={runtime / 'mount'}\n"
        f"data-directory={root / COMMON / 'os-update/rauc'}\n\n"
        f"[keyring]\npath={root / CMS_KEY}\ncheck-purpose=codesign\n"
        "use-bundle-signing-time=false\nallow-partial-chain=false\n\n"
        f"[handlers]\nbootloader-custom-backend={root / 'opt/rosy/os-bootstrap/native-runtime/rosy-os-bootloader'}\n")
    for index, slot in enumerate(("a", "b")):
        configuration += (f"\n[slot.rootfs.{index}]\ndevice={parts['root_' + slot]['path']}\n"
            f"type=ext4\nbootname={slot}\nallow-mounted=false\ninstall-same=true\nresize=false\n"
            f"\n[slot.boot.{index}]\ndevice={parts['boot_' + slot]['path']}\n"
            f"type=vfat\nparent=rootfs.{index}\nallow-mounted=false\ninstall-same=true\n")
    # Applied to the actual daemon, never to the D-Bus client alone. No bootstrap/data/active rw.
    devices = [("/dev/block/" + media["disk_device"], "r"),
               (parts["root_" + target]["path"], "rw"), (parts["boot_" + target]["path"], "rw"),
               ("/dev/loop-control", "rw"), ("block-loop", "rwm"),
               ("/dev/mapper/control", "rw"), ("block-device-mapper", "rwm")]
    dropin = "[Service]\nDevicePolicy=closed\nDeviceAllow=\n"
    dropin += "".join(f"DeviceAllow={device} {mode}\n" for device, mode in devices)
    return dict(verified=verified, media=media, target_slot=target,
                configuration=configuration, device_dropin=dropin)
