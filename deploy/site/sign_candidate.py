"""Offline signer for a verified Ubuntu site candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

if __package__:
    from .candidate_signing import (
        CandidateSignatureError, SIGNATURE_FILENAME, sign_manifest_bytes,
        verify_manifest_signature,
    )
    from .verify_candidate import CandidateVerificationError, _verify_candidate_content
else:  # pragma: no cover - exercised by the packaged offline CLI
    from candidate_signing import (
        CandidateSignatureError, SIGNATURE_FILENAME, sign_manifest_bytes,
        verify_manifest_signature,
    )
    from verify_candidate import CandidateVerificationError, _verify_candidate_content

Runner = Callable[..., subprocess.CompletedProcess]
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_MANIFEST_LIMIT = 8 * 1024 * 1024


def _write_signature(signature_path: Path, envelope: bytes, manifest_bytes: bytes, *,
                     key_id: str, public_key: Path, runner: Runner) -> None:
    created = False
    try:
        descriptor = os.open(signature_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        created = True
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(envelope)
            stream.flush()
            os.fsync(stream.fileno())
        verify_manifest_signature(
            manifest_bytes, signature_path.read_bytes(), trusted_key_id=key_id,
            public_key=public_key, runner=runner,
        )
    except FileExistsError:
        raise CandidateVerificationError("signature already exists; refusing to overwrite") from None
    except (OSError, CandidateSignatureError):
        if created:
            signature_path.unlink(missing_ok=True)
        raise


def sign_candidate(
    candidate_dir: Path, *, key_id: str, private_key: Path, public_key: Path,
    runner: Runner = subprocess.run,
) -> dict[str, str]:
    """Validate candidate content and add one detached, self-verified signature."""
    root = Path(candidate_dir).resolve(strict=True)
    manifest_path = root / "release.json"
    signature_path = root / SIGNATURE_FILENAME
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise CandidateVerificationError("release.json is missing or unsafe")
    if signature_path.exists() or signature_path.is_symlink():
        raise CandidateVerificationError("signature already exists; refusing to overwrite")

    manifest_bytes = manifest_path.read_bytes()
    checked = _verify_candidate_content(root, manifest_bytes=manifest_bytes)
    envelope = sign_manifest_bytes(
        manifest_bytes, key_id=key_id, private_key=private_key,
        public_key=public_key, runner=runner,
    )
    if manifest_path.read_bytes() != manifest_bytes:
        raise CandidateVerificationError("release.json changed while the candidate was being signed")
    checked = _verify_candidate_content(root, manifest_bytes=manifest_bytes)
    _write_signature(signature_path, envelope, manifest_bytes,
                     key_id=key_id, public_key=public_key, runner=runner)

    return {
        "source_commit": checked["source_commit"],
        "signing_key_id": key_id,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
    }


def sign_manifest_only(
    manifest_path: Path, *, expected_commit: str, key_id: str, private_key: Path,
    public_key: Path, runner: Runner = subprocess.run,
) -> dict[str, str]:
    """Sign a CI-built release.json without the candidate files (D-437).

    The signature attests that the operator approved this manifest from the
    expected commit. Every listed file hash is still checked by the site host's
    independently installed verifier before docker image load (D-301 3-4).
    """
    path = Path(manifest_path)
    if path.is_symlink() or not path.is_file():
        raise CandidateVerificationError("release.json is missing or unsafe")
    signature_path = path.resolve(strict=True).parent / SIGNATURE_FILENAME
    if signature_path.exists() or signature_path.is_symlink():
        raise CandidateVerificationError("signature already exists; refusing to overwrite")
    if not isinstance(expected_commit, str) or not _COMMIT.fullmatch(expected_commit):
        raise CandidateVerificationError("expected commit must be a full 40-character hex SHA")

    manifest_bytes = path.read_bytes()
    if not manifest_bytes or len(manifest_bytes) > _MANIFEST_LIMIT:
        raise CandidateVerificationError("release.json is empty or exceeds the 8 MiB limit")
    try:
        manifest = json.loads(manifest_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise CandidateVerificationError("release.json is not valid JSON") from None
    if (not isinstance(manifest, dict) or type(manifest.get("manifest_version")) is not int
            or manifest.get("manifest_version") != 1):
        raise CandidateVerificationError("unsupported release manifest")
    commit = manifest.get("source_commit")
    if not isinstance(commit, str) or not _COMMIT.fullmatch(commit):
        raise CandidateVerificationError("release.json source commit is not a 40-character hex SHA")
    if commit != expected_commit:
        raise CandidateVerificationError("release.json source commit differs from the expected commit")
    if manifest.get("image_tag") != commit or manifest.get("platform") != "linux/amd64":
        raise CandidateVerificationError("manifest tag or platform mismatch")

    envelope = sign_manifest_bytes(
        manifest_bytes, key_id=key_id, private_key=private_key,
        public_key=public_key, runner=runner,
    )
    if path.read_bytes() != manifest_bytes:
        raise CandidateVerificationError("release.json changed while it was being signed")
    _write_signature(signature_path, envelope, manifest_bytes,
                     key_id=key_id, public_key=public_key, runner=runner)
    return {
        "source_commit": commit,
        "signing_key_id": key_id,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "scope": "manifest-only",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--candidate-dir", type=Path,
                      help="full candidate: check every listed file, then sign")
    mode.add_argument("--manifest-only", action="store_true",
                      help="sign only --manifest (CI-built candidate, D-437); the site "
                           "host verifier still checks every file before docker load")
    parser.add_argument("--manifest", type=Path,
                        help="release.json to sign with --manifest-only")
    parser.add_argument("--expected-commit",
                        help="40-hex source commit the operator approved (--manifest-only)")
    parser.add_argument("--signing-key-id", required=True)
    parser.add_argument("--private-key", required=True, type=Path,
                        help="offline Ed25519 private key; never copied into the candidate")
    parser.add_argument("--public-key", required=True, type=Path,
                        help="matching public key used to verify the new signature")
    args = parser.parse_args(argv)
    if args.manifest_only and (args.manifest is None or args.expected_commit is None):
        parser.error("--manifest-only requires --manifest and --expected-commit")
    if not args.manifest_only and (args.manifest is not None or args.expected_commit is not None):
        parser.error("--manifest and --expected-commit are only valid with --manifest-only")
    try:
        if args.manifest_only:
            result = sign_manifest_only(
                args.manifest, expected_commit=args.expected_commit,
                key_id=args.signing_key_id,
                private_key=args.private_key, public_key=args.public_key,
            )
        else:
            result = sign_candidate(
                args.candidate_dir, key_id=args.signing_key_id,
                private_key=args.private_key, public_key=args.public_key,
            )
    except (CandidateSignatureError, CandidateVerificationError, OSError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"result": "SIGNED", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
