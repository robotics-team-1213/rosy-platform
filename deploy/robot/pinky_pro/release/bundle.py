"""Signed bundle ingestion. Never executes code, loads images, or changes activation."""
from __future__ import annotations

import contextlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile

from layout import Layout
from manifest import ManifestRejected, load_manifest
from signing import sha256_file, verify_release_files
from storage import HEADROOM_MARGIN_BYTES, check_update_headroom, free_bytes

MAX_BYTES = 8 * 1024**3
MAX_MEMBERS = 10000
RELEASE_ID = re.compile(r"[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}\Z")
REQUIRED_PAYLOAD = {"runtime/compose.yaml", "images/rosy-core.oci.tar", "images/rosy-io.oci.tar"}


class BundleError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


def release_id(value: str) -> str:
    if not isinstance(value, str) or not RELEASE_ID.fullmatch(value):
        raise BundleError("RELEASE_ID_INVALID", "expected YYYY.MM.DD-NNN")
    return value


def safe_name(name: str) -> str:
    parts = name.rstrip("/").split("/")
    if (not name or any(c in name for c in "\\:\x00\r\n") or len(parts) > 32
            or any(p in {"", ".", ".."} or p.endswith((" ", ".")) for p in parts)):
        raise BundleError("ARCHIVE_PATH", "archive member is not a portable relative path")
    return "/".join(parts)


@contextlib.contextmanager
def decoded_archive(path: Path):
    """Python 3.14 supports zstd; Pi Python 3.11/3.12 uses the host zstd tool."""
    with path.open("rb") as probe:
        zstd = probe.read(4) == b"\x28\xb5\x2f\xfd"
    if not zstd:
        with path.open("rb") as handle:
            yield handle
        return
    try:
        from compression import zstd as compression
    except ImportError:
        executable = shutil.which("zstd")
        if not executable:
            raise BundleError("ZSTD_UNAVAILABLE", "install the host zstd package")
        process = subprocess.Popen([executable, "-d", "-q", "-c", "--", str(path)],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            yield process.stdout
        finally:
            process.stdout.close()
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=10)
    else:
        with compression.open(path, "rb") as handle:
            yield handle


def verify_tree(root: Path, key: Path, *, device_target=None) -> dict:
    if root.is_symlink() or key.is_symlink():
        raise BundleError("BUNDLE_SYMLINK", "release and trust key must not be symlinks")
    for name in ("manifest.json", "SHA256SUMS", "SHA256SUMS.sig"):
        p = root / name
        if p.is_file() and p.stat().st_size > 4 * 1024**2:
            raise BundleError("BUNDLE_METADATA_SIZE", "release metadata exceeds 4 MiB")
    rejected = verify_release_files(root, key)
    if rejected:
        raise BundleError(rejected[0].code, rejected[0].detail)
    try:
        manifest = load_manifest(root / "manifest.json", device_target=device_target,
                                 trusted_key_ids={key.stem})
    except ManifestRejected as exc:
        raise BundleError(exc.rejections[0].code, exc.rejections[0].detail) from exc
    declared = {safe_name(e["path"]): e["sha256"] for e in manifest["files"]}
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    payload = actual - {"manifest.json", "SHA256SUMS", "SHA256SUMS.sig"}
    if set(declared) != payload or not REQUIRED_PAYLOAD <= payload:
        raise BundleError("MANIFEST_PAYLOAD", "manifest must enumerate exactly the runtime and image payload")
    for name, digest in declared.items():
        if sha256_file(root / name) != digest:
            raise BundleError("MANIFEST_PAYLOAD", f"manifest digest differs for {name}")
    if manifest["runtime"]["minimum_bootloader"] is not None:
        raise BundleError("BOOTLOADER_UNVERIFIED", "this runtime updater cannot verify a bootloader requirement")
    return manifest


def stage_archive(path: Path, layout: Layout, key: Path, *, device_target=None,
                  max_bytes: int = MAX_BYTES) -> Path:
    if path.stat().st_size > max_bytes:
        raise BundleError("ARCHIVE_SIZE", "compressed bundle exceeds the configured bound")
    rejected = check_update_headroom(max(1, path.stat().st_size), staging=layout.staging)
    if rejected:
        raise BundleError(rejected[0].code, rejected[0].detail)
    layout.staging.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ingest-", dir=layout.staging) as work:
        private = Path(work)
        tree = private / "tree"
        tree.mkdir(mode=0o700)
        seen, total = set(), 0
        try:
            with decoded_archive(path) as decoded:
                # Spool a bounded uncompressed tar so member validation completes before extraction.
                spool = private / "archive.tar"
                with spool.open("wb") as out:
                    expanded = 0
                    while chunk := decoded.read(1024 * 1024):
                        expanded += len(chunk)
                        if expanded > max_bytes + MAX_MEMBERS * 4096:
                            raise BundleError("ARCHIVE_SIZE", "expanded archive exceeds the configured bound")
                        if free_bytes(private) < HEADROOM_MARGIN_BYTES + len(chunk):
                            raise BundleError("UPDATE_INSUFFICIENT_SPACE",
                                              "decompression would consume the disk reserve")
                        out.write(chunk)
                with tarfile.open(spool, "r:") as tar:
                    members = []
                    for member in tar:
                        name = safe_name(member.name)
                        if name.casefold() in seen:
                            raise BundleError("ARCHIVE_DUPLICATE", "archive contains duplicate paths")
                        seen.add(name.casefold())
                        if not (member.isfile() or member.isdir()) or member.issparse():
                            raise BundleError("ARCHIVE_TYPE", "only regular files and directories are allowed")
                        total += member.size
                        if total > max_bytes or len(seen) > MAX_MEMBERS:
                            raise BundleError("ARCHIVE_SIZE", "archive exceeds file or byte limits")
                        members.append((member, name))
                    rejected = check_update_headroom(max(1, total + spool.stat().st_size), staging=tree)
                    if rejected:
                        raise BundleError(rejected[0].code, rejected[0].detail)
                    for member, name in members:
                        destination = tree / name
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        if member.isdir():
                            destination.mkdir(exist_ok=True)
                        else:
                            with tar.extractfile(member) as source, destination.open("xb") as out:
                                shutil.copyfileobj(source, out, 1024 * 1024)
                            destination.chmod(0o600)
        except (tarfile.TarError, EOFError) as exc:
            raise BundleError("ARCHIVE_UNREADABLE", "invalid or truncated tar archive") from exc
        manifest = verify_tree(tree, key, device_target=device_target)
        target = layout.staging / release_id(manifest["release_id"])
        if target.exists() or target.is_symlink():
            verify_tree(target, key, device_target=device_target)
            if (target / "SHA256SUMS").read_bytes() != (tree / "SHA256SUMS").read_bytes():
                raise BundleError("RELEASE_ID_REUSED", "same release id names different content")
            return target
        os.replace(tree, target)
        return target
