"""Offline signer for a verified Ubuntu site candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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

    return {
        "source_commit": checked["source_commit"],
        "signing_key_id": key_id,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-dir", required=True, type=Path)
    parser.add_argument("--signing-key-id", required=True)
    parser.add_argument("--private-key", required=True, type=Path,
                        help="offline Ed25519 private key; never copied into the candidate")
    parser.add_argument("--public-key", required=True, type=Path,
                        help="matching public key used to verify the new signature")
    args = parser.parse_args(argv)
    try:
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
