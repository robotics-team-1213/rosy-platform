"""Own disposable image mounts and native signature injection for offline CMS bundling."""
from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "image"))
sys.path.insert(0, str(BASE / "native"))
from os_factory_release import DESCRIPTOR, PUBLIC_KEY
from os_installed_factory import _verify
from os_state_io import _write_atomic
from os_state_layout import _object, _path, _read
from os_slot_metadata import FILES, rebase_files
from signing import verify_signature


def inject(root, factory, public, certificate, metadata):
    owner = root.stat().st_uid
    expected = metadata["native_factory"]
    descriptor = _object(_read(_path(root, DESCRIPTOR), 8192, owner),
                         {"schema_version", "release_id", "checksums_sha256"})
    if descriptor != dict(schema_version=1, **expected):
        raise ValueError("offline root belongs to another factory")
    prefix = "opt/rosy/releases/" + expected["release_id"]
    release = _path(root, prefix)
    sums = _read(release / "SHA256SUMS", 16 * 1024**2, owner)
    raw_sig = _read(factory / "SHA256SUMS.sig", 512, factory.stat().st_uid)
    signature = raw_sig.decode("ascii").strip()
    if (hashlib.sha256(sums).hexdigest() != expected["checksums_sha256"]
            or sums != _read(factory / "SHA256SUMS", 16 * 1024**2, factory.stat().st_uid)
            or verify_signature(sums, signature, public)):
        raise ValueError("offline native signature does not authorize this root")
    if (_read(_path(root, PUBLIC_KEY), 8192, owner) != Path(public).read_bytes()
            or _read(_path(root, "etc/rauc/keyring.pem"), 32768, owner) != certificate):
        raise ValueError("offline root trust differs from approved signing authority")
    if _read(release / "source-revision.txt", 128, owner).decode("ascii").strip() != metadata["source_revision"]:
        raise ValueError("native factory source differs from the OS image")
    target = _path(root, prefix + "/SHA256SUMS.sig")
    if target.exists():
        if target.stat().st_nlink != 1 or _read(target, 512, owner) != raw_sig:
            raise ValueError("existing factory signature differs")
    else:
        _write_atomic(target, raw_sig.decode("ascii"), 0o644)
    # Read-only native/Python/SDK validation; never enroll or execute incoming SDK code.
    _verify(root, root, metadata)


def prepare(images, value, dist, public, certificate):
    if os.geteuid() != 0:
        raise ValueError("offline root signature preparation requires an isolated privileged signing environment")
    spec = importlib.util.spec_from_file_location("rosy_owned_image_resources", BASE / "image/assemble-ab-image.py")
    assembler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(assembler)
    resources = assembler.ImageResources()
    root_image, boot_image = images / "rootfs.ext4", images / "boot.vfat"
    root, boot = images.parent / "root-mount", images.parent / "boot-mount"
    metadata = dict(schema_version=1, kind="os-update", board="pinky_pro", arch="arm64", compatible="rosy-pinky-pro-ab-v2",
        release_id=value["release_id"], source_revision=value["source_revision"],
        bundle=dict(filename=f"rosy-os-pinky-pro-{value['release_id']}-arm64.raucb", sha256="0" * 64, size_bytes=1),
        rootfs_bytes=value["images"]["rootfs.ext4"]["size_bytes"], boot_bytes=value["images"]["boot.vfat"]["size_bytes"],
        native_factory=value["native_factory"], boot_abi=2, state_schema=value["state_schema"], cms_signer_spki_sha256="0" * 64)
    try:
        assembler._run(["e2fsck", "-fn", str(root_image)], timeout=600)
        assembler._run(["fsck.vfat", "-n", str(boot_image)], timeout=600)
        root_loop = resources.loop(root_image)
        boot_loop = resources.loop(boot_image, readonly=True)
        resources.mount(root_loop, root)
        resources.mount(boot_loop, boot, readonly=True, filesystem="vfat")
        source = {name: _read(_path(boot if name == "cmdline.txt" else root, name), 32768,
                  (boot if name == "cmdline.txt" else root).stat().st_uid).decode("utf-8") for name in FILES}
        rebase_files(source, value["layout"], value["layout"], "a")  # Validate the factory-A inputs without rebasing.
        inject(root, dist / "factory-release" / value["native_factory"]["release_id"], public, certificate, metadata)
        resources.close()
        assembler._run(["e2fsck", "-fn", str(root_image)], timeout=600)
        root.rmdir()
        root_loop = resources.loop(root_image, readonly=True)
        resources.mount(root_loop, root, readonly=True)
        _verify(root, root, metadata)
        resources.unmount_all()
        assembler._run(["e2fsck", "-fn", str(root_image)], timeout=600)
    finally:
        try:
            resources.close()
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(f"OS_SIGN_CLEANUP_HOLD preserve {images.parent}") from exc
