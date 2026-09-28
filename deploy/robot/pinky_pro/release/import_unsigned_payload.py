#!/usr/bin/env python3
"""Verify and import a native ARM64 unsigned handoff before offline signing."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Callable

from manifest import validate_manifest


Decompressor = Callable[[Path, Path], None]
MAX_ARCHIVE_MEMBERS = 4096
MAX_EXPANDED_BYTES = 12 * 1024 * 1024 * 1024
MAX_DECOMPRESSED_TAR_BYTES = MAX_EXPANDED_BYTES + 64 * 1024 * 1024
MAX_IMAGE_METADATA_BYTES = 1024 * 1024
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_CHECKSUM_BYTES = 1024
BUILDER_FIELDS = {"ok", "output", "release_id", "git_revision", "signed"}
PROVENANCE_FIELDS = {
    "schema_version",
    "release_id",
    "source_revision",
    "created_at",
    "build_architecture",
    "docker_version",
    "ros_base_image",
    "images",
}
PINNED_IMAGE_RE = re.compile(r"^.+@sha256:[0-9a-f]{64}$")


class HandoffError(RuntimeError):
    """A fail-closed unsigned-handoff rejection with a stable code."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, code: str) -> dict:
    try:
        if path.stat().st_size > MAX_JSON_BYTES:
            raise HandoffError(
                "JSON_LIMIT", f"{path.name} exceeds the JSON size limit"
            )
        value = json.loads(path.read_text(encoding="utf-8"))
    except HandoffError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandoffError(code, f"cannot read {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise HandoffError(code, f"{path.name} must contain a JSON object")
    return value


def _zstd_decompress(source: Path, destination: Path) -> None:
    executable = shutil.which("zstd")
    if executable is None:
        raise HandoffError("ZSTD_UNAVAILABLE", "zstd executable is required")
    try:
        process = subprocess.Popen(
            [executable, "-q", "-d", "-c", str(source)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise HandoffError("ARCHIVE_DECOMPRESS", str(exc)) from exc
    try:
        if process.stdout is None or process.stderr is None:
            raise HandoffError(
                "ARCHIVE_DECOMPRESS", "zstd pipes are unavailable"
            )
        total = 0
        with destination.open("xb") as output:
            while True:
                block = process.stdout.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > MAX_DECOMPRESSED_TAR_BYTES:
                    raise HandoffError(
                        "ARCHIVE_LIMIT",
                        "decompressed tar exceeds the handoff limit",
                    )
                output.write(block)
        stderr = process.stderr.read().decode("utf-8", errors="replace")
        returncode = process.wait()
        if returncode:
            detail = (stderr.strip() or "zstd failed")[-500:]
            raise HandoffError("ARCHIVE_DECOMPRESS", detail)
    except BaseException:
        if process.poll() is None:
            process.kill()
        process.wait()
        destination.unlink(missing_ok=True)
        raise
    finally:
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()


def _verify_outer_checksum(archive: Path, checksum: Path) -> None:
    try:
        if checksum.stat().st_size > MAX_CHECKSUM_BYTES:
            raise HandoffError(
                "CHECKSUM_LIMIT", "checksum file exceeds the size limit"
            )
        line = checksum.read_text(encoding="ascii").strip()
    except HandoffError:
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise HandoffError("CHECKSUM_READ", str(exc)) from exc
    fields = line.split()
    if (
        len(fields) != 2
        or len(fields[0]) != 64
        or fields[1].lstrip("*") != archive.name
    ):
        raise HandoffError(
            "CHECKSUM_FORMAT",
            "checksum must name the selected archive exactly",
        )
    try:
        int(fields[0], 16)
    except ValueError as exc:
        raise HandoffError(
            "CHECKSUM_FORMAT", "checksum digest is not hexadecimal"
        ) from exc
    if _sha256(archive) != fields[0].lower():
        raise HandoffError(
            "CHECKSUM_MISMATCH",
            "archive SHA-256 does not match its handoff checksum",
        )


def _validate_archive_members(members: list[tarfile.TarInfo]) -> None:
    if len(members) > MAX_ARCHIVE_MEMBERS:
        raise HandoffError(
            "ARCHIVE_LIMIT", "archive contains too many members"
        )
    expanded = sum(member.size for member in members if member.isfile())
    if expanded > MAX_EXPANDED_BYTES:
        raise HandoffError(
            "ARCHIVE_LIMIT", "archive expanded size exceeds the handoff limit"
        )

    seen: set[str] = set()
    for member in members:
        name = member.name
        path = PurePosixPath(name)
        if (
            not name
            or name.startswith("/")
            or "\\" in name
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
            or (path.parts and ":" in path.parts[0])
        ):
            raise HandoffError(
                "ARCHIVE_PATH", f"unsafe archive member path: {name!r}"
            )
        if name in seen:
            raise HandoffError(
                "ARCHIVE_DUPLICATE", f"duplicate archive member: {name}"
            )
        seen.add(name)
        if not (member.isfile() or member.isdir()):
            raise HandoffError(
                "ARCHIVE_TYPE", f"unsupported archive member type: {name}"
            )
        if name == "arm64-builder.json":
            if not member.isfile():
                raise HandoffError(
                    "ARCHIVE_LAYOUT", "arm64-builder.json must be a file"
                )
        elif path.parts[0] != "rosy-unsigned-payload":
            raise HandoffError(
                "ARCHIVE_LAYOUT", f"unexpected handoff root: {path.parts[0]}"
            )

    if "arm64-builder.json" not in seen:
        raise HandoffError("ARCHIVE_LAYOUT", "arm64-builder.json is missing")
    if not any(
        PurePosixPath(name).parts[0] == "rosy-unsigned-payload"
        for name in seen
    ):
        raise HandoffError(
            "ARCHIVE_LAYOUT", "rosy-unsigned-payload is missing"
        )


def _inspect_image(path: Path, expected_id: str) -> str:
    try:
        with tarfile.open(path, "r:") as archive:
            manifest_member = archive.getmember("manifest.json")
            if (
                not manifest_member.isfile()
                or manifest_member.size > MAX_IMAGE_METADATA_BYTES
            ):
                raise HandoffError(
                    "IMAGE_LIMIT",
                    f"{path.name} manifest metadata is invalid",
                )
            manifest_stream = archive.extractfile(manifest_member)
            if manifest_stream is None:
                raise KeyError("manifest.json")
            image_manifest = json.loads(manifest_stream.read().decode("utf-8"))
            if (
                not isinstance(image_manifest, list)
                or len(image_manifest) != 1
            ):
                raise ValueError(
                    "Docker archive must describe exactly one image"
                )
            config_name = image_manifest[0]["Config"]
            config_member = archive.getmember(config_name)
            if (
                not config_member.isfile()
                or config_member.size > MAX_IMAGE_METADATA_BYTES
            ):
                raise HandoffError(
                    "IMAGE_LIMIT", f"{path.name} config metadata is invalid"
                )
            config_stream = archive.extractfile(config_member)
            if config_stream is None:
                raise KeyError(config_name)
            config_bytes = config_stream.read()
            config = json.loads(config_bytes.decode("utf-8"))
    except (
        OSError,
        tarfile.TarError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise HandoffError(
            "IMAGE_ARCHIVE", f"cannot inspect {path.name}: {exc}"
        ) from exc
    actual_id = "sha256:" + hashlib.sha256(config_bytes).hexdigest()
    if actual_id != expected_id:
        raise HandoffError(
            "IMAGE_ID", f"{path.name} config digest differs from the manifest"
        )
    platform = f"{config.get('os')}/{config.get('architecture')}"
    if platform != "linux/arm64":
        raise HandoffError(
            "IMAGE_PLATFORM",
            f"{path.name} is {platform}, expected linux/arm64",
        )
    return platform


def _verify_payload(
    root: Path,
    *,
    expected_release_id: str,
    expected_revision: str,
    expected_signing_key_id: str,
) -> dict:
    payload = root / "rosy-unsigned-payload"
    builder_path = root / "arm64-builder.json"
    manifest_path = payload / "manifest.json"
    if (
        not payload.is_dir()
        or not builder_path.is_file()
        or not manifest_path.is_file()
    ):
        raise HandoffError(
            "HANDOFF_LAYOUT", "payload, builder report, or manifest is missing"
        )

    builder = _read_json(builder_path, "BUILDER_JSON")
    manifest = _read_json(manifest_path, "MANIFEST_JSON")
    rejections = validate_manifest(manifest)
    if rejections:
        detail = "; ".join(f"{item.code}:{item.field}" for item in rejections)
        raise HandoffError("MANIFEST_REJECTED", detail)

    if set(builder) != BUILDER_FIELDS:
        raise HandoffError(
            "BUILDER_SCHEMA", "builder report fields do not match schema 1"
        )
    builder_output = builder.get("output")
    if (
        not isinstance(builder_output, str)
        or not PurePosixPath(builder_output).is_absolute()
    ):
        raise HandoffError(
            "BUILDER_SCHEMA", "builder output must be an absolute POSIX path"
        )
    expected_builder = {
        "ok": True,
        "release_id": expected_release_id,
        "git_revision": expected_revision,
        "signed": False,
    }
    for field, expected in expected_builder.items():
        if builder.get(field) != expected:
            raise HandoffError(
                "BUILDER_IDENTITY", f"builder {field} does not match"
            )
    for field, expected in (
        ("release_id", expected_release_id),
        ("git_revision", expected_revision),
        ("signing_key_id", expected_signing_key_id),
    ):
        if manifest.get(field) != expected:
            raise HandoffError(
                "MANIFEST_IDENTITY", f"manifest {field} does not match"
            )
    if (payload / "SHA256SUMS").exists() or (
        payload / "SHA256SUMS.sig"
    ).exists():
        raise HandoffError(
            "UNEXPECTED_SIGNATURE",
            "unsigned handoff already contains signing files",
        )

    declared = {entry["path"]: entry["sha256"] for entry in manifest["files"]}
    actual = {
        path.relative_to(payload).as_posix()
        for path in payload.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    if set(declared) != actual:
        raise HandoffError(
            "MANIFEST_PAYLOAD",
            "manifest must enumerate every payload file exactly",
        )
    for name, expected in declared.items():
        if _sha256(payload / Path(name)) != expected:
            raise HandoffError(
                "PAYLOAD_HASH", f"payload digest mismatch: {name}"
            )

    provenance = _read_json(
        payload / "build-provenance.json", "PROVENANCE_JSON"
    )
    if (
        set(provenance) != PROVENANCE_FIELDS
        or provenance.get("schema_version") != 1
    ):
        raise HandoffError(
            "PROVENANCE_SCHEMA",
            "provenance fields or schema version do not match",
        )
    for field, expected in (
        ("release_id", expected_release_id),
        ("source_revision", expected_revision),
        ("build_architecture", "arm64"),
        ("created_at", manifest["created_at"]),
    ):
        if provenance.get(field) != expected:
            raise HandoffError(
                "PROVENANCE_IDENTITY", f"provenance {field} does not match"
            )
    if (
        not isinstance(provenance.get("docker_version"), str)
        or not provenance["docker_version"]
    ):
        raise HandoffError(
            "PROVENANCE_SCHEMA", "Docker version must be a non-empty string"
        )
    ros_base = provenance.get("ros_base_image", "")
    if (
        not isinstance(ros_base, str)
        or PINNED_IMAGE_RE.fullmatch(ros_base) is None
    ):
        raise HandoffError(
            "PROVENANCE_BASE", "ROS base image is not digest-pinned"
        )
    if (
        not isinstance(provenance.get("images"), dict)
        or set(provenance["images"]) != {"rosy_core", "rosy_io"}
    ):
        raise HandoffError(
            "PROVENANCE_SCHEMA",
            "provenance must describe CORE and IO exactly",
        )
    for role, record in provenance["images"].items():
        if (
            not isinstance(record, dict)
            or set(record) != {"tag", "image_id"}
            or not isinstance(record["tag"], str)
            or not record["tag"]
            or not isinstance(record["image_id"], str)
        ):
            raise HandoffError(
                "PROVENANCE_SCHEMA",
                f"invalid provenance image record: {role}",
            )

    images = {}
    for role, filename in (
        ("rosy_core", "rosy-core.oci.tar"),
        ("rosy_io", "rosy-io.oci.tar"),
    ):
        image_id = manifest["containers"][role]
        provenance_id = provenance["images"][role]["image_id"]
        if provenance_id != image_id:
            raise HandoffError(
                "PROVENANCE_IMAGE", f"{role} image ID does not match"
            )
        images[role] = _inspect_image(payload / "images" / filename, image_id)
    if (
        manifest["containers"]["rosy_core"]
        == manifest["containers"]["rosy_io"]
    ):
        raise HandoffError(
            "IMAGE_COLLISION", "CORE and IO must be distinct images"
        )

    return {
        "ok": True,
        "release_id": expected_release_id,
        "git_revision": expected_revision,
        "signing_key_id": expected_signing_key_id,
        "signed": False,
        "files_verified": len(declared),
        "images": images,
    }


def import_handoff(
    archive: Path,
    checksum: Path,
    output: Path,
    *,
    expected_release_id: str,
    expected_revision: str,
    expected_signing_key_id: str,
    decompressor: Decompressor = _zstd_decompress,
) -> dict:
    try:
        archive = archive.resolve(strict=True)
        checksum = checksum.resolve(strict=True)
    except OSError as exc:
        raise HandoffError(
            "INPUT_IO", f"archive or checksum is unavailable: {exc}"
        ) from exc
    output = output.resolve()
    expected_archive_name = (
        f"rosy-unsigned-{expected_release_id}-{expected_revision}.tar.zst"
    )
    if archive.name != expected_archive_name:
        raise HandoffError(
            "ARCHIVE_IDENTITY",
            "archive filename does not match expected release",
        )
    if output.exists():
        raise HandoffError(
            "OUTPUT_EXISTS", "verified handoff output already exists"
        )
    if not output.parent.is_dir():
        raise HandoffError(
            "OUTPUT_PARENT", "output parent directory does not exist"
        )

    _verify_outer_checksum(archive, checksum)
    with tempfile.TemporaryDirectory(
        prefix=f".{output.name}.", dir=output.parent
    ) as work:
        work_path = Path(work)
        raw_tar = work_path / "handoff.tar"
        extracted = work_path / "verified"
        extracted.mkdir()
        decompressor(archive, raw_tar)
        try:
            with tarfile.open(raw_tar, "r:") as handoff:
                _validate_archive_members(handoff.getmembers())
                handoff.extractall(extracted, filter="data")
        except (OSError, tarfile.TarError) as exc:
            raise HandoffError("ARCHIVE_EXTRACT", str(exc)) from exc
        report = _verify_payload(
            extracted,
            expected_release_id=expected_release_id,
            expected_revision=expected_revision,
            expected_signing_key_id=expected_signing_key_id,
        )
        try:
            os.replace(extracted, output)
        except OSError as exc:
            raise HandoffError(
                "OUTPUT_COMMIT",
                f"cannot publish verified handoff: {exc}",
            ) from exc
    report["output"] = str(output)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "archive", type=Path, help="downloaded unsigned .tar.zst"
    )
    parser.add_argument(
        "--checksum", required=True, type=Path, help="sibling .sha256 file"
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="new verified handoff directory",
    )
    parser.add_argument(
        "--release-id",
        required=True,
        help="expected YYYY.MM.DD-NNN release ID",
    )
    parser.add_argument(
        "--git-revision",
        required=True,
        help="expected full 40-hex source revision",
    )
    parser.add_argument(
        "--signing-key-id",
        required=True,
        help="expected offline signing key ID",
    )
    return parser


def main(argv=None, *, decompressor: Decompressor = _zstd_decompress) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = import_handoff(
            args.archive,
            args.checksum,
            args.output,
            expected_release_id=args.release_id,
            expected_revision=args.git_revision,
            expected_signing_key_id=args.signing_key_id,
            decompressor=decompressor,
        )
    except HandoffError as exc:
        print(
            json.dumps({"ok": False, "code": exc.code, "detail": exc.detail}),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
