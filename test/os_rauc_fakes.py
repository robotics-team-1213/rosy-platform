"""Pinned native RAUC extracted into pytest storage; never installs a package or service."""
import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
from urllib.request import urlopen

import pytest

RELEASE = "2026.10.26-011"
PACKAGES = {
    "x86_64": ("https://archive.ubuntu.com/ubuntu/pool/universe/r/rauc/rauc_1.11.3-2_amd64.deb",
               160646, "78770edfa1d65325e62970ff889a135b67896d1364d607996418fdbc89b7fad7"),
    "aarch64": ("https://ports.ubuntu.com/ubuntu-ports/pool/universe/r/rauc/rauc_1.11.3-2_arm64.deb",
                157612, "33fa200e0ed18efd59b699beb9a58646006953477221cfe0fe48e290227ea390"),
}


def run(argv, *, data=None):
    result = subprocess.run([str(value) for value in argv], input=data, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return result.stdout


@pytest.fixture(scope="session")
def rauc_tool(tmp_path_factory):
    if platform.system() != "Linux":
        pytest.skip("actual RAUC boundaries require native Linux")
    assert platform.machine() in PACKAGES, "no verified native RAUC test package for this architecture"
    assert shutil.which("dpkg-deb") and shutil.which("mksquashfs") and shutil.which("openssl")
    url, size, digest = PACKAGES[platform.machine()]
    with urlopen(url, timeout=30) as response:
        package = response.read(size + 1)
    assert len(package) == size and hashlib.sha256(package).hexdigest() == digest
    directory = tmp_path_factory.mktemp("isolated-rauc")
    archive = directory / "rauc.deb"
    archive.write_bytes(package)
    run(["dpkg-deb", "-x", archive, directory / "root"])
    tool = directory / "root/usr/bin/rauc"
    assert run([tool, "--version"]).decode().strip() == "rauc 1.11.3"
    return tool


def signer(directory: Path):
    directory.mkdir(parents=True)
    key, certificate = directory / "fixture.key.pem", directory / "fixture.cert.pem"
    run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256",
         "-nodes", "-sha256", "-days", "1", "-subj", "/CN=ROSY OS Test Signer",
         "-addext", "basicConstraints=critical,CA:FALSE", "-addext", "keyUsage=critical,digitalSignature",
         "-addext", "extendedKeyUsage=codeSigning", "-keyout", key, "-out", certificate])
    return key, certificate


def manifest():
    return (f"[update]\ncompatible=rosy-pinky-pro-ab-v2\nversion={RELEASE}\nbuild={'b' * 40}\n"
            "[bundle]\nformat=verity\n[image.rootfs]\nfilename=rootfs.ext4\n[image.boot]\nfilename=boot.vfat\n"
            "[meta.rosy]\nboot_abi=2\nstate_read_min=1\nstate_read_max=1\nstate_write=1\n"
            f"native_factory_release_id=2026.10.26-010\nnative_factory_checksums_sha256={'a' * 64}\n")


def make_bundle(directory, tool, key, certificate, text=None):
    source = directory / "source"
    source.mkdir(parents=True)
    (source / "rootfs.ext4").write_bytes(os.urandom(8192))
    (source / "boot.vfat").write_bytes(b"B" * 512)
    (source / "manifest.raucm").write_text(text or manifest())
    for filename in ("hook.sh", "handler.sh"):
        if text and "filename=" + filename in text:
            script = source / filename
            script.write_text("#!/bin/sh\nexit 99\n")
            script.chmod(0o755)
    config = directory / "system.conf"
    config.write_text(f"[system]\ncompatible=rosy-pinky-pro-ab-v2\nbootloader=noop\nbundle-formats=verity\ndata-directory={directory / 'state'}\n"
                      f"[keyring]\npath={certificate}\ncheck-purpose=codesign\nuse-bundle-signing-time=false\n")
    bundle = directory / f"rosy-os-pinky-pro-{RELEASE}-arm64.raucb"
    run([tool, "--conf", config, "--cert", certificate, "--key", key,
         "--mksquashfs-args=-processors 1", "bundle", source, bundle])
    return bundle, config
