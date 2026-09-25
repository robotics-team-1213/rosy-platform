#!/usr/bin/env python3
"""Assemble and pack a native payload-only release (D-225 Decision 2.1).

``build`` turns the tree ``deploy/image/build-native-payload.sh`` produced into
an unsigned release directory in exactly the shape
``deploy/robot/native/native_release.py verify()`` accepts once
``SHA256SUMS.sig`` is added: the switchable payload files, ``manifest.json``
listing each of them, and ``SHA256SUMS`` over manifest plus payload.
``image-overlay/`` is image-layer content (customize-rootfs.sh copies it into
the rootfs and drops it from the release), so it never enters a payload.

Signing stays offline (``sign_image_release.py``); ``pack`` then writes the
deterministic ``.tar.gz`` that ``rosy-release-push.ps1 -Tarball`` sends and
``rosy-release-unpack.sh`` accepts: sorted members, regular files and
directories only, uid/gid 0, fixed mtime, no gzip timestamp or name.

This tool never reads a private key.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tarfile

from signing import (
    CHECKSUM_FILENAME,
    SIGNATURE_FILENAME,
    build_sha256sums,
    sha256_file,
    verify_release_files,
)


RELEASE_ID = re.compile(r"^[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")
RUNTIME_ID = re.compile(r"^[0-9a-f]{64}$")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
DEFAULT_SIGNING_KEY_ID = "rosy-release-2026-01"
MANIFEST_FILENAME = "manifest.json"
METADATA = {MANIFEST_FILENAME, CHECKSUM_FILENAME, SIGNATURE_FILENAME}
IMAGE_ONLY = {"image-overlay"}
# Mirrors native_release.py: REQUIRED_PAYLOAD, PYTHON_RUNTIME_RELEASE_FILE,
# and the target/runtime it requires. The tests run verify() on the output,
# so a drift between the two fails there.
REQUIRED_PAYLOAD = {
    "install/.rosy-release",
    "deploy/robot/native/rosy-runtime.target",
    "rosy-packages.txt",
    "source-revision.txt",
    "python-runtime.sha256",
}
TARGET = {
    "board": "pinky_pro",
    "host": "raspberry-pi-5",
    "architecture": "arm64",
    "os_family": "ubuntu-server",
    "os_release": "24.04",
}
RUNTIME = {"model": "native-systemd", "default_mode": "core"}
# 2000-01-01T00:00:00Z. Any constant works; 0 trips some tar readers' warnings.
FIXED_MTIME = 946684800
# A Windows file system has no POSIX exec bits to read back (D-225 review).
_WINDOWS = os.name == "nt"


def _payload_files(payload_root: Path) -> list[str]:
    """Relative POSIX paths of every payload file, refusing anything else."""
    files: list[str] = []
    for path in sorted(payload_root.rglob("*"), key=lambda p: p.relative_to(payload_root).as_posix()):
        relative = path.relative_to(payload_root).as_posix()
        if relative.split("/", 1)[0] in IMAGE_ONLY:
            continue
        if CONTROL.search(relative):
            raise ValueError(f"PAYLOAD_PATH_UNSAFE: control character in {relative!r}")
        if path.is_symlink():
            raise ValueError(
                f"PAYLOAD_SYMLINK: {relative}; a release must not contain symlinks "
                "(native_release.py and rosy-release-unpack.sh refuse them)")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"PAYLOAD_ENTRY_TYPE: {relative} is not a regular file")
        # At any depth: a nested manifest.json or SHA256SUMS(.sig) reads as release
        # metadata to anything that walks the unpacked tree (D-225 review).
        if path.name in METADATA:
            raise ValueError(f"PAYLOAD_METADATA_PRESENT: {relative} must not be in the build tree")
        files.append(relative)
    return files


def _read_line(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def build_release(
    payload_root: Path,
    release_id: str,
    out_dir: Path,
    *,
    signing_key_id: str = DEFAULT_SIGNING_KEY_ID,
) -> dict[str, object]:
    """Copy the payload into ``out_dir`` and write manifest.json + SHA256SUMS."""
    payload_root = Path(payload_root).resolve(strict=True)
    out_dir = Path(out_dir)
    if not RELEASE_ID.fullmatch(release_id):
        raise ValueError("RELEASE_ID_INVALID: expected YYYY.MM.DD-NNN")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", signing_key_id):
        raise ValueError("SIGNING_KEY_ID_INVALID: expected the public key file stem")
    if not payload_root.is_dir():
        raise ValueError("PAYLOAD_ROOT: payload root must be a directory")
    if out_dir.exists() or out_dir.is_symlink():
        raise ValueError(f"RELEASE_DIR_EXISTS: refusing to reuse {out_dir}")

    files = _payload_files(payload_root)
    missing = sorted(REQUIRED_PAYLOAD - set(files))
    if missing:
        raise ValueError(f"PAYLOAD_INCOMPLETE: missing {', '.join(missing)}")
    marker = _read_line(payload_root / "install" / ".rosy-release")
    if marker != release_id:
        raise ValueError(f"PAYLOAD_RELEASE_ID: install/.rosy-release is {marker!r}, not {release_id}")
    revision = _read_line(payload_root / "source-revision.txt")
    if not REVISION.fullmatch(revision):
        raise ValueError("PAYLOAD_REVISION: source-revision.txt is not a full Git commit")
    if not RUNTIME_ID.fullmatch(_read_line(payload_root / "python-runtime.sha256")):
        raise ValueError("PAYLOAD_PYTHON_RUNTIME: python-runtime.sha256 is not a sha256")

    out_dir.mkdir(parents=True)
    try:
        for relative in files:
            source = payload_root / relative
            target = out_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            executable = source.stat().st_mode & 0o111
            os.chmod(target, 0o755 if executable else 0o644)
        manifest = {
            "schema_version": 1,
            "release_id": release_id,
            "git_revision": revision,
            "target": dict(TARGET),
            "runtime": dict(RUNTIME),
            "signing_key_id": signing_key_id,
            "files": [
                {"path": relative, "sha256": sha256_file(out_dir / relative)}
                for relative in files
            ],
        }
        (out_dir / MANIFEST_FILENAME).write_bytes(
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        (out_dir / CHECKSUM_FILENAME).write_bytes(
            build_sha256sums(out_dir, [MANIFEST_FILENAME, *files]))
    except BaseException:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise
    return {
        "ok": True,
        "release_dir": str(out_dir),
        "release_id": release_id,
        "git_revision": revision,
        "files": len(files),
        "signed": False,
    }


def _tar_members(release_dir: Path) -> list[tuple[str, Path]]:
    members: list[tuple[str, Path]] = []
    for path in sorted(release_dir.rglob("*"), key=lambda p: p.relative_to(release_dir).as_posix()):
        relative = path.relative_to(release_dir).as_posix()
        if CONTROL.search(relative):
            raise ValueError(f"PACK_PATH_UNSAFE: control character in {relative!r}")
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise ValueError(f"PACK_ENTRY_TYPE: {relative} is not a regular file or directory")
        members.append((relative, path))
    return members


def _modes_from(unsigned: Path, members: list[tuple[str, Path]]) -> dict[str, int]:
    """File modes from the unsigned Linux tarball, keyed by member name."""
    recorded: dict[str, tuple[bool, int]] = {}
    with tarfile.open(unsigned, "r:gz") as tar:
        for member in tar.getmembers():
            if not (member.isreg() or member.isdir()):
                raise ValueError(f"PACK_MODES_SOURCE: {member.name} is not a regular file or directory")
            recorded[member.name] = (member.isdir(), 0o755 if member.mode & 0o111 else 0o644)
    local = {relative: path.is_dir() for relative, path in members}
    expected = set(local) - {SIGNATURE_FILENAME}
    if set(recorded) != expected:
        differing = sorted(set(recorded) ^ expected)
        raise ValueError(f"PACK_MODES_MISMATCH: unsigned tarball members differ: {differing[:5]}")
    modes = {SIGNATURE_FILENAME: 0o644}
    for relative, (is_dir, mode) in recorded.items():
        if is_dir != local[relative]:
            raise ValueError(f"PACK_MODES_MISMATCH: {relative} changed type since the build")
        modes[relative] = mode
    return modes


def pack_release(
    release_dir: Path,
    tarball: Path,
    *,
    public_key: Path | None = None,
    allow_unsigned: bool = False,
    modes_from: Path | None = None,
) -> dict[str, object]:
    """Write a byte-reproducible ``.tar.gz`` of ``release_dir``'s contents.

    ``modes_from`` is the unsigned tarball the Linux build packed. A GitHub
    artifact download (zip) or a Windows checkout loses POSIX exec bits, so a
    re-pack after offline signing takes each member's mode from that tarball
    instead of the local file system; the member set must match exactly,
    except the added ``SHA256SUMS.sig``.
    """
    release_dir = Path(release_dir).resolve(strict=True)
    tarball = Path(tarball)
    if not release_dir.is_dir():
        raise ValueError("RELEASE_DIR: release directory is unavailable")
    if tarball.resolve() == release_dir or release_dir in tarball.resolve().parents:
        raise ValueError("PACK_OUTPUT_LOCATION: tarball must be written outside the release")
    manifest = json.loads((release_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    release_id = str(manifest.get("release_id"))
    if not RELEASE_ID.fullmatch(release_id):
        raise ValueError("RELEASE_ID_INVALID: manifest release_id is not YYYY.MM.DD-NNN")
    if not (release_dir / CHECKSUM_FILENAME).is_file():
        raise ValueError("SHA256SUMS_MISSING: build the release first")
    signed = (release_dir / SIGNATURE_FILENAME).is_file()
    if not signed and not allow_unsigned:
        raise ValueError("SIGNATURE_MISSING: sign the release (sign_image_release.py) before packing")
    if public_key is not None:
        rejections = verify_release_files(release_dir, Path(public_key))
        if rejections:
            raise ValueError(str(rejections[0]))
    if signed and modes_from is None and _WINDOWS:
        raise ValueError(
            "PACK_MODES_REQUIRED: on Windows the local files carry no exec bits; pass "
            "--modes-from <the unsigned Linux tarball> to re-pack a signed release")

    members = _tar_members(release_dir)
    modes = _modes_from(modes_from, members) if modes_from is not None else None
    tarball.parent.mkdir(parents=True, exist_ok=True)
    temporary = tarball.with_name(f".{tarball.name}.tmp")
    try:
        with temporary.open("wb") as raw, \
                gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9) as gz, \
                tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
            for relative, path in members:
                info = tarfile.TarInfo(relative)
                info.mtime = FIXED_MTIME
                info.uid = info.gid = 0
                info.uname = info.gname = "root"
                if path.is_dir():
                    info.type = tarfile.DIRTYPE
                    info.mode = 0o755
                    tar.addfile(info)
                    continue
                info.type = tarfile.REGTYPE
                if modes is not None:
                    info.mode = modes[relative]
                else:
                    info.mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
                info.size = path.stat().st_size
                with path.open("rb") as handle:
                    tar.addfile(info, handle)
            raw.flush()
        os.replace(temporary, tarball)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return {
        "ok": True,
        "tarball": str(tarball),
        "release_id": release_id,
        "signed": signed,
        "members": len(members),
        "sha256": sha256_file(tarball),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="payload tree -> unsigned release directory")
    build.add_argument("--payload-root", type=Path, required=True)
    build.add_argument("--release-id", required=True)
    build.add_argument("--out", type=Path, required=True, help="release directory to create")
    build.add_argument("--signing-key-id", default=DEFAULT_SIGNING_KEY_ID)
    pack = sub.add_parser("pack", help="release directory -> deterministic .tar.gz")
    pack.add_argument("--release-dir", type=Path, required=True)
    pack.add_argument("--out", type=Path, required=True, help="tarball path to write")
    pack.add_argument("--public-key", type=Path, help="verify the signature before packing")
    pack.add_argument("--allow-unsigned", action="store_true",
                      help="pack a release without SHA256SUMS.sig (never pushable)")
    pack.add_argument("--modes-from", type=Path,
                      help="unsigned Linux tarball whose file modes (exec bits) to keep")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            report = build_release(args.payload_root, args.release_id, args.out,
                                   signing_key_id=args.signing_key_id)
        else:
            report = pack_release(args.release_dir, args.out, public_key=args.public_key,
                                  allow_unsigned=args.allow_unsigned,
                                  modes_from=args.modes_from)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
