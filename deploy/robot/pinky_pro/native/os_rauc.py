"""Verify staged OS bundles with pinned RAUC and the image-owned CMS trust anchor."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

from os_state_layout import COMMON, _pairs, _path, _read
from os_update_manifest import COMPATIBLE, _digest, _fields, _integer, verify_metadata

RAUC = "/usr/bin/rauc"
ED_KEY = "etc/rosy/trusted-release-keys/rosy-release-2026-01.pem"
CMS_KEY = "etc/rauc/keyring.pem"
PEM_CERT = rb"-----BEGIN CERTIFICATE-----\r?\n(?:[A-Za-z0-9+/=]+\r?\n)+-----END CERTIFICATE-----"


def _run(argv, *, data=None, pass_fds=()):
    result = subprocess.run(argv, input=data, capture_output=True, timeout=60, pass_fds=pass_fds,
                            env=dict(os.environ, LC_ALL="C"))
    if result.returncode or len(result.stdout) > 1024**2 or len(result.stderr) > 65536:
        raise ValueError("RAUC/OpenSSL verification command failed")
    return result.stdout


def _certificate(raw: bytes) -> bytes:
    if not re.fullmatch(rb"\s*(?:" + PEM_CERT + rb")\s*", raw):
        raise ValueError("a single public CMS certificate is required")
    return _run(["openssl", "x509", "-outform", "DER"], data=raw)


def _spki(raw: bytes) -> str:
    public = _run(["openssl", "x509", "-pubkey", "-noout"], data=raw)
    details = _run(["openssl", "pkey", "-pubin", "-text", "-noout"], data=public)
    if b"ASN1 OID: prime256v1" not in details:
        raise ValueError("CMS signer must use ECDSA P-256")
    return hashlib.sha256(_run(["openssl", "pkey", "-pubin", "-outform", "DER"], data=public)).hexdigest()


def _inspect(bundle: Path, certificate: Path) -> dict:
    if _run([RAUC, "--version"]).strip() != b"rauc 1.11.3":
        raise ValueError("unsupported RAUC version")
    if any(char in str(certificate) for char in "\r\n\0"):
        raise ValueError("invalid CMS certificate path")
    # This sealed, slotless configuration is for info only; the install daemon has its own runtime config.
    config = (f"[system]\ncompatible={COMPATIBLE}\nbootloader=noop\nbundle-formats=verity\n"
              f"[keyring]\npath={certificate}\ncheck-purpose=codesign\nuse-bundle-signing-time=false\n"
              "allow-partial-chain=false\n").encode()
    descriptor = os.memfd_create("rosy-rauc-verify", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        os.write(descriptor, config)
        fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS,
                    fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL)
        raw = _run([RAUC, "--conf", f"/proc/self/fd/{descriptor}", "info", "--output-format=json-2", str(bundle)],
                   pass_fds=(descriptor,))
    finally:
        os.close(descriptor)
    return json.loads(raw, object_pairs_hook=_pairs)


def _inner(value: dict, metadata: dict) -> dict:
    _fields(value, {"manifest-hash", "update", "bundle", "images", "meta"})
    _digest(value["manifest-hash"])
    update = value["update"]
    if not isinstance(update, dict) or not {"compatible", "version", "build"} <= set(update) <= {"compatible", "version", "build", "description"}:
        raise ValueError("unexpected RAUC update fields")
    if (update["compatible"] != COMPATIBLE or update["version"] != metadata["release_id"]
            or update["build"] != metadata["source_revision"]):
        raise ValueError("RAUC identity differs from signed OS metadata")
    bundle = value["bundle"]
    _fields(bundle, {"format", "verity-hash", "verity-salt", "verity-size"})
    if bundle["format"] != "verity":
        raise ValueError("only verity OS bundles are supported")
    _digest(bundle["verity-hash"])
    _digest(bundle["verity-salt"])
    _integer(bundle["verity-size"], 4096, 16 * 1024**3)
    if bundle["verity-size"] % 4096:
        raise ValueError("invalid verity tree size")
    _fields(value["meta"], {"rosy"})
    expected = dict(boot_abi="2", state_read_min="1", state_read_max="1", state_write="1",
                    native_factory_release_id=metadata["native_factory"]["release_id"],
                    native_factory_checksums_sha256=metadata["native_factory"]["checksums_sha256"])
    if value["meta"]["rosy"] != expected:
        raise ValueError("RAUC factory or ABI contract differs")
    images = value["images"]
    if not isinstance(images, list) or len(images) != 2:
        raise ValueError("exactly rootfs and boot images are required")
    result = {}
    for image in images:
        required = {"slot-class", "filename", "checksum", "size", "hooks"}
        if not isinstance(image, dict) or not required <= set(image) <= required | {"adaptive"}:
            raise ValueError("unsupported image fields")
        role = image["slot-class"]
        if role not in ("rootfs", "boot") or role in result or image["hooks"] != [] or image.get("adaptive", []) != []:
            raise ValueError("unsupported class, hooks or adaptive install")
        if image["filename"] != {"rootfs": "rootfs.ext4", "boot": "boot.vfat"}[role]:
            raise ValueError("unsupported OS image filename")
        expected_size = metadata["rootfs_bytes" if role == "rootfs" else "boot_bytes"]
        _integer(image["size"], expected_size, expected_size)
        _digest(image["checksum"])
        result[role] = dict(filename=image["filename"], sha256=image["checksum"], size=image["size"])
    return result


def _identity(info) -> tuple:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
            info.st_mode, info.st_uid, info.st_nlink)


def _verify(root: Path, bundle: Path, raw_metadata: bytes, signature: str) -> dict:
    root, bundle = Path(root).absolute(), Path(bundle).absolute()
    public = _path(root, ED_KEY)
    _read(public, 8192, root.stat().st_uid)
    metadata = verify_metadata(raw_metadata, signature, public)
    expected = _path(root, COMMON + "/os-update/staging/" + metadata["release_id"] + "/" + metadata["bundle"]["filename"])
    if bundle != expected:
        raise ValueError("OS bundle is outside its private release staging directory")
    keyring = _path(root, CMS_KEY)
    certificate = _read(keyring, 32768, root.stat().st_uid)
    pinned_der = _certificate(certificate)
    if _spki(certificate) != metadata["cms_signer_spki_sha256"]:
        raise ValueError("OS metadata selects an unapproved CMS signer")
    with os.fdopen(os.open(bundle, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as handle:
        info = os.fstat(handle.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != root.stat().st_uid or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o400 or info.st_size != metadata["bundle"]["size_bytes"]):
            raise ValueError("OS bundle type, ownership, mode or size differs")
        digest = hashlib.sha256()
        while chunk := handle.read(2 * 1024**2):
            digest.update(chunk)
        if digest.hexdigest() != metadata["bundle"]["sha256"]:
            raise ValueError("OS bundle differs from its signed digest")
        handle.seek(-8, os.SEEK_END)
        size = int.from_bytes(handle.read(8), "big")
        if not 0 < size <= 65536 or size + 8 >= info.st_size:
            raise ValueError("invalid CMS footer size")
        handle.seek(-8 - size, os.SEEK_END)
        cms = handle.read(size)
        value = _inspect(bundle, keyring)
        images = _inner(value, metadata)
        pem = _run(["openssl", "pkcs7", "-inform", "DER", "-print_certs"], data=cms)
        certificates = re.findall(PEM_CERT, pem)
        if len(certificates) != 1 or _certificate(certificates[0]) != pinned_der:
            raise ValueError("CMS must contain exactly the pinned signing certificate")
        if _identity(os.fstat(handle.fileno())) != _identity(info) or _identity(bundle.stat()) != _identity(info):
            raise ValueError("OS bundle changed during verification")
    return dict(metadata=metadata, images=images, manifest_sha256=value["manifest-hash"])


def verify_bundle(root: Path, bundle: Path, raw_metadata: bytes, signature: str) -> dict:
    """No install is requested; callers must reverify and admit actual targets before writes."""
    try:
        return _verify(root, bundle, raw_metadata, signature)
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        raise ValueError(f"OS_RAUC_HOLD: {exc}") from exc
