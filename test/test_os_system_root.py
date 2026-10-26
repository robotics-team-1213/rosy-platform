"""Real guest-kernel offline signature preparation with synthetic native payload/layout, never DEVICE evidence."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("ROSY_OS_GUEST") != "1" or not Path("/run/rosy-system-guest").is_file(),
                                reason="only inside the owned disposable SYSTEM guest")


def run(argv):
    result = subprocess.run([str(p) for p in argv], capture_output=True, check=True, timeout=180)
    return result.stdout


def test_actual_loop_fsck_mount_signature_injection_and_error_cleanup(tmp_path):
    from test_os_installed_factory import _installed
    from test_ab_image_layout import module
    from os_rauc_fakes import signer
    ab = module()
    _, root, release, value, _, public = _installed(tmp_path)
    _, certificate = signer(tmp_path / "cms")
    raw_cert = certificate.read_bytes()
    ring = root / "etc/rauc/keyring.pem"
    ring.parent.mkdir(parents=True)
    ring.write_bytes(raw_cert)
    layout = ab.plan()
    start = 2048
    for part, mib in zip(layout["partitions"], (8, 64, 64, 128, 128, 64)):
        part.update(start_lba=start, size_lba=mib * 2048)
        start += mib * 2048
    layout["raw_size_bytes"] = 512 * 1024**2
    layout = ab.validate_layout(layout)
    from os_slot_metadata import render_files
    source_boot = tmp_path / "boot-source"
    source_boot.mkdir()
    for name, text in render_files(layout, "a", "root=LABEL=writable console=ttyS0").items():
        path = (source_boot if name == "cmdline.txt" else root) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    dist = tmp_path / "dist"
    factory = dist / "factory-release" / value["native_factory"]["release_id"]
    factory.mkdir(parents=True)
    for name in ("SHA256SUMS", "SHA256SUMS.sig", "manifest.json"):
        shutil.copyfile(release / name, factory / name)
    signature = (release / "SHA256SUMS.sig").read_bytes()
    (release / "SHA256SUMS.sig").unlink()
    images = tmp_path / "images"
    images.mkdir()
    root_image, boot_image = images / "rootfs.ext4", images / "boot.vfat"
    for path, mib in ((root_image, 128), (boot_image, 64)):
        with path.open("xb") as stream: stream.truncate(mib * 1024**2)
    run(["mkfs.ext4", "-q", "-F", "-E", "lazy_itable_init=0,lazy_journal_init=0", "-d", root, root_image])
    run(["mkfs.vfat", "-F", "32", boot_image])
    run(["mcopy", "-i", boot_image, source_boot / "cmdline.txt", "::/cmdline.txt"])
    value.update(layout=layout, source_revision=(release / "source-revision.txt").read_text().strip(),
                 images={"rootfs.ext4": {"size_bytes": root_image.stat().st_size},
                         "boot.vfat": {"size_bytes": boot_image.stat().st_size}})
    from os_bundle_root import prepare
    boot_sha = hashlib.sha256(boot_image.read_bytes()).hexdigest()
    prepare(images, value, dist, public, raw_cert)
    command = "cat /opt/rosy/releases/" + value["native_factory"]["release_id"] + "/SHA256SUMS.sig"
    assert run(["debugfs", "-R", command, root_image]) == signature
    assert not (release / "SHA256SUMS.sig").exists()
    assert hashlib.sha256(boot_image.read_bytes()).hexdigest() == boot_sha
    # Exercise rejection after the real RW mount; all owned loop/mount resources must still be released.
    # The real publisher allocates a fresh owned workspace for each signing attempt.
    bad_images = tmp_path / "bad-signature-case/images"
    bad_images.mkdir(parents=True)
    for name in ("rootfs.ext4", "boot.vfat"):
        shutil.copyfile(images / name, bad_images / name)
    (factory / "SHA256SUMS.sig").write_text("invalid supplied signature")
    with pytest.raises(ValueError, match="native signature"):
        prepare(bad_images, value, dist, public, raw_cert)
    assert run(["debugfs", "-R", command, bad_images / "rootfs.ext4"]) == signature
    loops = json.loads(run(["losetup", "--json", "--output", "NAME,BACK-FILE"]))["loopdevices"]
    assert not any(str(tmp_path) in (row.get("back-file") or "") for row in loops)
    print("SYSTEM actual fsck/owned-loop/RW-injection/RO-readback and error cleanup; payload/layout synthetic")
