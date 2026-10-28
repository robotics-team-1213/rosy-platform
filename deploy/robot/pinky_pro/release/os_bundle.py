#!/usr/bin/env python3
"""Offline-only CMS/Ed25519 publisher for authenticated native OS image inputs."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import lzma
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "image"))
sys.path.insert(0, str(BASE / "native"))
import ab_image_layout as ab
from os_cms_trust import _validate as validate_certificate, verify as verify_cms, CERTIFICATE
from os_rauc import _spki, verify_bundle
from os_state_layout import _pairs, _path, _read
from os_update_manifest import COMPATIBLE, _digest, _fields, _integer, release_id, validate_metadata, verify_metadata
from os_update_rollout import _shape as validate_rollout, verify as verify_rollout
from signing import parse_sha256sums, sha256_file, sign_checksums, verify_release_checksums, verify_signature

INPUT_FIELDS = {"schema_version", "kind", "board", "arch", "release_id", "source_revision", "boot_abi",
                "state_schema", "layout", "native_factory", "images"}
CHUNK = 2 * 1024**2


def read_inputs(dist: Path, public: Path) -> dict:
    dist = ab._offline_directory(dist)
    owner = dist.stat().st_uid
    _read(_path(dist, "SHA256SUMS"), 16 * 1024**2, owner)
    _read(_path(dist, "SHA256SUMS.sig"), 512, owner)
    entries, errors = verify_release_checksums(dist, public)
    if errors:
        raise ValueError("untrusted image distribution: " + str(errors[0]))
    def record(name, limit=65536):
        raw = _read(_path(dist, name), limit, owner)
        if entries.get(name) != hashlib.sha256(raw).hexdigest():
            raise ValueError("OS input metadata differs from authenticated checksum: " + name)
        return json.loads(raw, object_pairs_hook=_pairs)
    value = record("os-bundle-inputs/inputs.json")
    _fields(value, INPUT_FIELDS)
    _integer(value["schema_version"], 1, 1)
    _integer(value["boot_abi"], 2, 2)
    if (value["kind"] != "os-bundle-inputs" or value["board"] != "pinky_pro" or value["arch"] != "arm64"):
        raise ValueError("unsupported OS bundle inputs")
    identity = release_id(value["release_id"])
    _fields(value["state_schema"], {"read_min", "read_max", "write"})
    for version in value["state_schema"].values():
        _integer(version, 1, 1)
    layout = ab.validate_layout(value["layout"])
    manifest, provenance = record("manifest.json"), record("build-provenance.json")
    if (type(manifest["schema_version"]) is not int or manifest["schema_version"] != 2
            or manifest["release_id"] != identity or manifest["layout"] != layout
            or manifest.get("product") != "rosy-os" or manifest.get("board") != "pinky_pro"
            or manifest.get("architecture") != "arm64"
            or layout["provision_role"] != "bootstrap" or provenance["architecture"] != "aarch64"
            or provenance["source_revision"] != value["source_revision"]):
        raise ValueError("OS inputs differ from native image provenance")
    image = manifest["image"]
    if (image["filename"] != f"rosy-os-pinky-pro-{identity}-arm64.img.xz"
            or image["sha256"] != entries.get(image["filename"])):
        raise ValueError("OS inputs differ from authenticated image bytes")
    _fields(value["native_factory"], {"release_id", "checksums_sha256"})
    factory = "factory-release/" + identity + "/"
    native_sums = _read(_path(dist, factory + "SHA256SUMS"), 16 * 1024**2, owner)
    native_sig = _read(_path(dist, factory + "SHA256SUMS.sig"), 512, owner).decode("ascii").strip()
    if (value["native_factory"] != dict(release_id=identity, checksums_sha256=hashlib.sha256(native_sums).hexdigest())
            or verify_signature(native_sums, native_sig, public)):
        raise ValueError("untrusted native factory signature or identity")
    native_entries, errors = parse_sha256sums(native_sums)
    native_manifest = _read(_path(dist, factory + "manifest.json"), 1024**2, owner)
    if errors or native_entries.get("manifest.json") != hashlib.sha256(native_manifest).hexdigest():
        raise ValueError("native factory manifest is not checksum-bound")
    if json.loads(native_manifest, object_pairs_hook=_pairs).get("release_id") != identity:
        raise ValueError("native factory manifest belongs to another release")
    _fields(value["images"], {"rootfs.ext4", "boot.vfat"})
    for name, role in (("rootfs.ext4", "root_a"), ("boot.vfat", "boot_a")):
        item = value["images"][name]
        _fields(item, {"filename", "size_bytes", "sha256", "archive_bytes", "archive_sha256"})
        expected_size = next(p["size_lba"] * 512 for p in layout["partitions"] if p["role"] == role)
        _integer(item["size_bytes"], expected_size, expected_size)
        _integer(item["archive_bytes"], 1, 16 * 1024**3)
        _digest(item["sha256"])
        _digest(item["archive_sha256"])
        archive = "os-bundle-inputs/" + name + ".xz"
        if (item["filename"] != name + ".xz" or item["archive_sha256"] != entries.get(archive)
                or (dist / archive).stat().st_size != item["archive_bytes"]):
            raise ValueError("OS archive differs from authenticated export metadata")
    # The consumer's strict schema also validates source revision and image-size limits.
    _metadata(value, "0" * 64, dict(filename=f"rosy-os-pinky-pro-{identity}-arm64.raucb", sha256="0" * 64, size_bytes=1))
    return value


def decompress(archive: Path, expected: dict, target: Path) -> None:
    total, digest = 0, hashlib.sha256()
    with lzma.open(archive, "rb") as source, target.open("xb") as output:
        while data := source.read(min(CHUNK, expected["size_bytes"] - total + 1)):
            total += len(data)
            if total > expected["size_bytes"]:
                raise ValueError("OS image exceeds its authenticated logical size")
            digest.update(data)
            output.write(data)
        if total != expected["size_bytes"] or digest.hexdigest() != expected["sha256"]:
            raise ValueError("OS image differs from its authenticated logical digest")
        output.flush()
        os.fsync(output.fileno())


def _metadata(value, spki, bundle):
    return validate_metadata(dict(schema_version=1, kind="os-update", board="pinky_pro", arch="arm64",
        compatible=COMPATIBLE, release_id=value["release_id"], source_revision=value["source_revision"],
        bundle=bundle, rootfs_bytes=value["images"]["rootfs.ext4"]["size_bytes"],
        boot_bytes=value["images"]["boot.vfat"]["size_bytes"], native_factory=value["native_factory"],
        boot_abi=2, state_schema=value["state_schema"], cms_signer_spki_sha256=spki))


def _manifest(value):
    factory = value["native_factory"]
    return (f"[update]\ncompatible={COMPATIBLE}\nversion={value['release_id']}\nbuild={value['source_revision']}\n"
        "[bundle]\nformat=verity\n[image.rootfs]\nfilename=rootfs.ext4\n[image.boot]\nfilename=boot.vfat\n"
        "[meta.rosy]\nboot_abi=2\nstate_read_min=1\nstate_read_max=1\nstate_write=1\n"
        f"native_factory_release_id={factory['release_id']}\nnative_factory_checksums_sha256={factory['checksums_sha256']}\n")


def prepare_root(work, value, dist, public, certificate):
    from os_bundle_root import prepare
    prepare(work, value, dist, public, certificate)


def _private(key: Path, forbidden):
    key = Path(key).absolute()
    ab._offline_directory(key.parent)
    info = key.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600 or any(key.is_relative_to(p) for p in forbidden)):
        raise ValueError("private signing key must be owner-only and outside all release/work directories")
    return key


def _command(argv, *, timeout=60):
    result = subprocess.run([str(p) for p in argv], capture_output=True, timeout=timeout,
                            env=dict(os.environ, LC_ALL="C"))
    if result.returncode:
        error = result.stderr.decode("utf-8", errors="replace")[-2048:]
        if "--key" in argv:
            error = error.replace(str(argv[argv.index("--key") + 1]), "<private-key>")
        raise ValueError(f"offline RAUC command failed ({result.returncode}): {error}")
    return result.stdout


def _signed(path, value, private, public):
    raw = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    signature = sign_checksums(raw, private)
    if verify_signature(raw, signature, public):
        raise ValueError("offline Ed25519 signing key does not match distribution authority")
    ab._write_atomic(path, raw.decode("utf-8"), 0o644)
    ab._write_atomic(path.with_name(path.name + ".sig"), signature + "\n", 0o644)
    return raw, signature


def sign(dist, output, private, public, cms_private, certificate, *, canary, rauc="/usr/bin/rauc"):
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        raise ValueError("product OS signing must not run in hosted CI")
    dist, output = Path(dist).absolute(), Path(output).absolute()
    ab._offline_directory(output.parent)
    if output.exists() or output.is_symlink() or ".." in output.parts:
        raise ValueError("signed OS output must be a new directory")
    private = _private(private, (dist, output))
    cms_private = _private(cms_private, (dist, output))
    value = read_inputs(dist, public)
    certificate = Path(certificate).absolute()
    if any(c in str(certificate) for c in "\n\r\0"):
        raise ValueError("invalid CMS certificate path")
    raw_cert = _read(certificate, 32768, certificate.parent.stat().st_uid)
    validate_certificate(raw_cert)
    spki = _spki(raw_cert)
    needed = 2 * sum(item["size_bytes"] for item in value["images"].values()) + 512 * 1024**2
    if shutil.disk_usage(output.parent).free < needed:
        raise ValueError("insufficient disk for disposable OS images and CMS output")
    if _command([rauc, "--version"]).strip() != b"rauc 1.11.3":
        raise ValueError("unsupported offline RAUC version")
    work = Path(tempfile.mkdtemp(prefix=".os-sign-", dir=output.parent))
    preserve = False
    try:
        images, publish = work / "images", work / "publish"
        images.mkdir()
        publish.mkdir()
        for name, item in value["images"].items():
            decompress(dist / "os-bundle-inputs" / item["filename"], item, images / name)
        try:
            prepare_root(images, value, dist, public, raw_cert)
        except RuntimeError:
            preserve = True  # The mount owner reports failed cleanup; never delete a live mount tree.
            raise
        (images / "manifest.raucm").write_text(_manifest(value), encoding="ascii")
        trusted_cert = work / "public-cms.pem"
        trusted_cert.write_bytes(raw_cert)
        config = work / "system.conf"
        config.write_text(f"[system]\ncompatible={COMPATIBLE}\nbootloader=noop\nbundle-formats=verity\n"
            f"[keyring]\npath={trusted_cert}\ncheck-purpose=codesign\nuse-bundle-signing-time=false\nallow-partial-chain=false\n")
        name = f"rosy-os-pinky-pro-{value['release_id']}-arm64.raucb"
        bundle = publish / name
        _command([rauc, "--conf", config, "--cert", trusted_cert, "--key", cms_private,
            "--mksquashfs-args=-processors 1", "bundle", images, bundle], timeout=8 * 3600)
        bundle.chmod(0o400)
        with bundle.open("rb") as handle: os.fsync(handle.fileno())
        metadata = _metadata(value, spki, dict(filename=name, sha256=sha256_file(bundle), size_bytes=bundle.stat().st_size))
        raw, signature = _signed(publish / "os-update.json", metadata, private, public)
        authority = work / "authority"
        for relative, data in (("etc/rosy/trusted-release-keys/rosy-release-2026-01.pem", Path(public).read_bytes()),
                               ("etc/rauc/keyring.pem", raw_cert)):
            path = authority / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        stage = authority / "var/lib/rosy-device/os-update/staging" / value["release_id"]
        stage.mkdir(parents=True)
        os.rename(bundle, stage / name)
        import os_rauc
        original = os_rauc.RAUC
        try:
            os_rauc.RAUC = str(rauc)
            verify_bundle(authority, stage / name, raw, signature)
        finally:
            os_rauc.RAUC = original
        os.rename(stage / name, bundle)
        rollout = dict(schema_version=1, kind="os-update", release_id=value["release_id"], bundle=name,
            bundle_sha256=metadata["bundle"]["sha256"], published_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            canary=list(canary), canary_ok=False, withdrawn=False, wave_delay_s=600)
        validate_rollout(rollout)
        _signed(publish / "os-rollout.json", rollout, private, public)
        ab.sync_directory(publish)
        os.rename(publish, output)
        ab.sync_directory(output.parent)
        return metadata
    finally:
        if not preserve:
            shutil.rmtree(work)


def update_rollout(directory, private, public, *, promote=False, withdraw=False):
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        raise ValueError("product rollout signing must not run in hosted CI")
    if type(promote) is not bool or type(withdraw) is not bool or promote == withdraw:
        raise ValueError("select exactly one rollout operation")
    directory = ab._offline_directory(directory)
    private = _private(private, (directory,))
    def data(name, limit):
        return _read(_path(directory, name), limit, directory.stat().st_uid)
    metadata = verify_metadata(data("os-update.json", 16384), data("os-update.json.sig", 512).decode().strip(), public)
    raw, signature = data("os-rollout.json", 16384), data("os-rollout.json.sig", 512)
    value = verify_rollout(raw, signature.decode().strip(), public, metadata)
    if promote:
        if value["withdrawn"]:
            raise ValueError("a withdrawn OS release cannot be promoted again")
        value["canary_ok"] = True
    else:
        value["withdrawn"] = True
    validate_rollout(value)
    try:
        _signed(directory / "os-rollout.json", value, private, public)
    except BaseException:
        ab._write_atomic(directory / "os-rollout.json", raw.decode("utf-8"), 0o644)
        ab._write_atomic(directory / "os-rollout.json.sig", signature.decode("ascii"), 0o644)
        raise
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("sign")
    for name in ("dist", "output", "private-key", "public-key", "cms-private-key", "lock"):
        build.add_argument("--" + name, type=Path, required=True)
    build.add_argument("--source-tree", type=Path, default=BASE.parents[2])
    build.add_argument("--canary", action="append", required=True)
    policy = commands.add_parser("rollout")
    for name in ("directory", "private-key", "public-key"):
        policy.add_argument("--" + name, type=Path, required=True)
    operation = policy.add_mutually_exclusive_group(required=True)
    operation.add_argument("--promote", action="store_true")
    operation.add_argument("--withdraw", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "rollout":
        update_rollout(args.directory, args.private_key, args.public_key, promote=args.promote, withdraw=args.withdraw)
        print("OS_ROLLOUT_SIGNED")
        return 0
    import yaml
    verify_cms(yaml.safe_load(args.lock.read_bytes())["os_updates"], args.source_tree)
    sign(args.dist, args.output, args.private_key, args.public_key, args.cms_private_key,
         args.source_tree / CERTIFICATE, canary=args.canary)
    print("OS_BUNDLE_SIGNED_AND_VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
