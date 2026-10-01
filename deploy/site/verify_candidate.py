"""Verify a transferred site candidate and its already-loaded Docker images."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Callable

if __package__:
    from .candidate_signing import (
        CandidateSignatureError, SIGNATURE_FILENAME, verify_manifest_signature,
    )
else:  # pragma: no cover - exercised by the packaged host CLI
    from candidate_signing import (
        CandidateSignatureError, SIGNATURE_FILENAME, verify_manifest_signature,
    )


REQUIRED_DEPLOYMENT_FILES = (
    "compose.yaml", "Caddyfile", ".env.example", "README.md",
    "robots.yaml.example", "site-cameras.yaml.example", "site-users.yaml.example",
    "mdns-bridge.py", "rosy-mdns-bridge.service", "rosy-mdns-bridge.timer",
    "fleet-mdns.py", "rosy-fleet-advertise.service", "rosy-overhead-advertise.service",
    "rosy-site-stack.service", "site-firewall.py", "rosy-site-firewall.service",
    "discovery-token.template.txt", "site_db.py", "candidate_signing.py",
    "sign_candidate.py", "verify_candidate.py",
)
REQUIRED_DOCUMENT_FILES = ("docs/reference/site-lan-discovery-profile.md",)
SERVICES = ("fleet", "vision", "proxy")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
Runner = Callable[..., subprocess.CompletedProcess]


class CandidateVerificationError(ValueError):
    """Candidate metadata or local host image state does not match."""


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _candidate_file(root: Path, relative: str, *, label: str) -> Path:
    if (not isinstance(relative, str) or not relative or "\\" in relative
            or "\x00" in relative):
        raise CandidateVerificationError(f"invalid {label} path")
    path = PurePosixPath(relative)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise CandidateVerificationError(f"unsafe {label} path")
    candidate = (root / Path(*path.parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise CandidateVerificationError(f"unsafe {label} path") from None
    if not candidate.is_file():
        raise CandidateVerificationError(f"missing {label}")
    return candidate


def _manifest_hash(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise CandidateVerificationError(f"invalid {label} SHA-256")
    return value


def _verify_candidate_content(candidate_dir: Path, *, manifest_bytes: bytes | None = None) -> dict:
    """Verify manifest-listed files and archive before an offline signing step."""
    root = Path(candidate_dir).resolve(strict=True)
    manifest_path = root / "release.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise CandidateVerificationError("release.json is missing or unsafe")
    manifest_bytes = manifest_path.read_bytes() if manifest_bytes is None else manifest_bytes
    if not manifest_bytes or len(manifest_bytes) > 8 * 1024 * 1024:
        raise CandidateVerificationError("release.json is empty or exceeds the 8 MiB limit")
    try:
        manifest = json.loads(manifest_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise CandidateVerificationError("release.json is unreadable or invalid JSON") from None
    if (not isinstance(manifest, dict) or type(manifest.get("manifest_version")) is not int
            or manifest.get("manifest_version") != 1):
        raise CandidateVerificationError("unsupported release manifest")

    commit = manifest.get("source_commit")
    if not isinstance(commit, str) or not _COMMIT.fullmatch(commit):
        raise CandidateVerificationError("invalid source commit")
    if manifest.get("image_tag") != commit or manifest.get("platform") != "linux/amd64":
        raise CandidateVerificationError("manifest tag or platform mismatch")

    hashes = manifest.get("deployment_file_sha256")
    if not isinstance(hashes, dict):
        raise CandidateVerificationError("deployment file hashes are missing")
    required = set(REQUIRED_DEPLOYMENT_FILES) | set(REQUIRED_DOCUMENT_FILES)
    unsupported = set(hashes) - required
    if unsupported:
        raise CandidateVerificationError("unsupported deployment file path")
    missing = required - set(hashes)
    if missing:
        raise CandidateVerificationError("required deployment file hashes are missing")
    for name, expected in hashes.items():
        digest = _manifest_hash(expected, label="deployment file")
        relative = name if name.startswith("docs/") else f"deploy/site/{name}"
        file_path = _candidate_file(root, relative, label="deployment file")
        if _digest(file_path) != digest:
            raise CandidateVerificationError(f"deployment file hash mismatch: {name}")

    env_path = _candidate_file(root, "deploy/site/.env.example", label="site env template")
    expected_tag = f"ROSY_SITE_IMAGE_TAG={commit}"
    if expected_tag not in env_path.read_text(encoding="utf-8").splitlines():
        raise CandidateVerificationError("site env template image tag mismatch")

    archive_name = manifest.get("image_archive")
    if archive_name != "images.tar":
        raise CandidateVerificationError("unsupported image archive path")
    archive_path = _candidate_file(root, archive_name, label="image archive")
    archive_hash = _manifest_hash(manifest.get("image_archive_sha256"), label="image archive")
    if _digest(archive_path) != archive_hash:
        raise CandidateVerificationError("image archive hash mismatch")

    images = manifest.get("images")
    if not isinstance(images, dict) or set(images) != set(SERVICES):
        raise CandidateVerificationError("candidate must contain Fleet, Vision, and proxy images")
    image_ids: dict[str, str] = {}
    for service in SERVICES:
        row = images[service]
        if not isinstance(row, dict):
            raise CandidateVerificationError(f"invalid {service} image record")
        reference = f"rosy-site-{service}:{commit}"
        if row.get("reference") != reference or row.get("platform") != "linux/amd64":
            raise CandidateVerificationError(f"{service} manifest image reference/platform mismatch")
        expected_id = row.get("image_id")
        if not isinstance(expected_id, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_id):
            raise CandidateVerificationError(f"invalid {service} image ID")

        sbom_name = row.get("sbom")
        if sbom_name != f"sbom/{service}.spdx":
            raise CandidateVerificationError(f"unsupported {service} SBOM path")
        sbom_path = _candidate_file(root, sbom_name, label=f"{service} SBOM")
        sbom_hash = _manifest_hash(row.get("sbom_sha256"), label=f"{service} SBOM")
        if _digest(sbom_path) != sbom_hash:
            raise CandidateVerificationError(f"{service} SBOM hash mismatch")
        image_ids[service] = expected_id

    return {
        "manifest": manifest,
        "source_commit": commit,
        "platform": "linux/amd64",
        "verified_images": list(SERVICES),
        "image_ids": image_ids,
        "deployment_files": len(hashes),
        "image_archive_sha256": archive_hash,
    }


def verify_candidate(
    candidate_dir: Path, *, trusted_key_id: str, trusted_public_key: Path,
    runner: Runner = subprocess.run, inspect_loaded_images: bool = True,
) -> dict:
    """Authenticate a candidate and check contents, optionally inspect loaded images."""
    root = Path(candidate_dir).resolve(strict=True)
    manifest_path = root / "release.json"
    signature_path = root / SIGNATURE_FILENAME
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise CandidateVerificationError("release.json is missing or unsafe")
    if signature_path.is_symlink() or not signature_path.is_file():
        raise CandidateVerificationError("release signature is missing or unsafe")
    try:
        manifest_bytes = manifest_path.read_bytes()
        signature_bytes = signature_path.read_bytes()
    except OSError:
        raise CandidateVerificationError("candidate signature inputs are unreadable") from None
    try:
        verify_manifest_signature(
            manifest_bytes, signature_bytes, trusted_key_id=trusted_key_id,
            public_key=trusted_public_key, runner=runner,
        )
    except CandidateSignatureError as error:
        raise CandidateVerificationError(str(error)) from error

    summary = _verify_candidate_content(root, manifest_bytes=manifest_bytes)
    if not inspect_loaded_images:
        return {
            "source_commit": summary["source_commit"],
            "platform": summary["platform"],
            "deployment_files": summary["deployment_files"],
            "image_archive_sha256": summary["image_archive_sha256"],
            "manifest_image_ids": summary["image_ids"],
        }
    image_ids: dict[str, str] = {}
    for service in SERVICES:
        row = summary["manifest"]["images"][service]
        reference = row["reference"]
        expected_id = row["image_id"]
        try:
            result = runner(
                ["docker", "image", "inspect", "--format",
                 "{{.Id}}|{{.Os}}|{{.Architecture}}", reference],
                check=True, capture_output=True, text=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            raise CandidateVerificationError(
                f"docker image inspection failed for {service}") from None
        identity = result.stdout.strip().split("|")
        if len(identity) != 3 or identity[0] != expected_id:
            raise CandidateVerificationError(f"{service} loaded image ID mismatch")
        if identity[1:] != ["linux", "amd64"]:
            raise CandidateVerificationError(f"{service} loaded platform mismatch")
        image_ids[service] = identity[0]

    summary["image_ids"] = image_ids
    summary.pop("manifest")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-dir", type=Path,
                        default=Path(__file__).resolve().parents[2])
    parser.add_argument("--trusted-key-id", required=True,
                        help="the key ID enrolled by the host administrator")
    parser.add_argument("--trusted-public-key", required=True, type=Path,
                        help="public key installed outside the candidate bundle")
    parser.add_argument("--signature-only", action="store_true",
                        help="verify signature and package hashes before docker image load")
    args = parser.parse_args(argv)
    try:
        result = verify_candidate(
            args.candidate_dir, trusted_key_id=args.trusted_key_id,
            trusted_public_key=args.trusted_public_key,
            inspect_loaded_images=not args.signature_only,
        )
    except (CandidateVerificationError, OSError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"result": "PASS", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
