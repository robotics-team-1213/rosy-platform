"""Detached Ed25519 signatures for immutable site candidate manifests."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

SIGNATURE_VERSION = 1
SIGNATURE_FILENAME = "release.json.sig"
SIGNATURE_LENGTH = 64
_DOMAIN = b"ROSY-SITE-CANDIDATE-SIGNATURE-v1\x00"
_KEY_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
Runner = Callable[..., subprocess.CompletedProcess]


class CandidateSignatureError(ValueError):
    """A site candidate has no acceptable detached signature."""


def _openssl() -> str:
    path = shutil.which("openssl")
    if path is None and os.name == "nt":
        for folder in (r"C:\Program Files\Git\usr\bin", r"C:\Program Files\Git\mingw64\bin"):
            candidate = os.path.join(folder, "openssl.exe")
            if os.path.isfile(candidate):
                path = candidate
                break
    if path is None:
        raise CandidateSignatureError("OpenSSL is required for site candidate signatures")
    return path


def _key_path(path: Path, *, label: str) -> Path:
    path = Path(path)
    if path.is_symlink():
        raise CandidateSignatureError(f"{label} must not be a symlink")
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        raise CandidateSignatureError(f"{label} is missing or unreadable") from None
    if not resolved.is_file():
        raise CandidateSignatureError(f"{label} is not a file")
    return resolved


def _validate_key_id(key_id: object) -> str:
    if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id):
        raise CandidateSignatureError("signing key ID is malformed")
    return key_id


def _signed_message(manifest: bytes, key_id: str) -> bytes:
    return _DOMAIN + key_id.encode("ascii") + b"\x00" + manifest


def _run_openssl(args: list[str], *, runner: Runner) -> subprocess.CompletedProcess:
    try:
        return runner(args, capture_output=True, check=False, timeout=30)
    except (OSError, subprocess.SubprocessError):
        raise CandidateSignatureError("OpenSSL signature operation failed") from None


def sign_manifest_bytes(
    manifest: bytes, *, key_id: str, private_key: Path, public_key: Path,
    runner: Runner = subprocess.run,
) -> bytes:
    """Sign exact manifest bytes and self-verify before returning the envelope."""
    if not isinstance(manifest, bytes) or not manifest or len(manifest) > 8 * 1024 * 1024:
        raise CandidateSignatureError("manifest bytes are empty or exceed the 8 MiB limit")
    key_id = _validate_key_id(key_id)
    private_path = _key_path(private_key, label="private signing key")
    public_path = _key_path(public_key, label="matching public key")

    with tempfile.TemporaryDirectory(prefix="rosy-site-sign-") as temporary:
        root = Path(temporary)
        message = root / "message"
        signature_path = root / "signature"
        message.write_bytes(_signed_message(manifest, key_id))
        result = _run_openssl(
            [_openssl(), "pkeyutl", "-sign", "-inkey", str(private_path),
             "-rawin", "-in", str(message), "-out", str(signature_path)],
            runner=runner,
        )
        if result.returncode != 0:
            raise CandidateSignatureError("OpenSSL could not sign the candidate manifest")
        try:
            signature = signature_path.read_bytes()
        except OSError:
            raise CandidateSignatureError("OpenSSL did not produce a signature") from None
        if len(signature) != SIGNATURE_LENGTH:
            raise CandidateSignatureError("OpenSSL produced an invalid Ed25519 signature length")

        _verify_raw(_signed_message(manifest, key_id), signature, public_path,
                    runner=runner, temporary=root)

    envelope = {
        "signature_version": SIGNATURE_VERSION,
        "signing_key_id": key_id,
        "signature": base64.b64encode(signature).decode("ascii"),
    }
    return (json.dumps(envelope, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CandidateSignatureError("signature envelope contains duplicate fields")
        result[key] = value
    return result


def _verify_raw(
    message_bytes: bytes, signature: bytes, public_key: Path, *,
    runner: Runner, temporary: Path | None = None,
) -> None:
    if len(signature) != SIGNATURE_LENGTH:
        raise CandidateSignatureError("signature has an invalid Ed25519 length")
    public_path = _key_path(public_key, label="trusted public key")

    def verify(root: Path) -> None:
        message = root / "message-verify"
        signature_path = root / "signature-verify"
        message.write_bytes(message_bytes)
        signature_path.write_bytes(signature)
        result = _run_openssl(
            [_openssl(), "pkeyutl", "-verify", "-pubin", "-inkey", str(public_path),
             "-rawin", "-in", str(message), "-sigfile", str(signature_path)],
            runner=runner,
        )
        if result.returncode != 0:
            raise CandidateSignatureError("signature verification failed")

    if temporary is not None:
        verify(temporary)
    else:
        with tempfile.TemporaryDirectory(prefix="rosy-site-verify-") as directory:
            verify(Path(directory))


def verify_manifest_signature(
    manifest: bytes, envelope_bytes: bytes, *, trusted_key_id: str,
    public_key: Path, runner: Runner = subprocess.run,
) -> None:
    """Fail closed unless the exact manifest is signed by the enrolled key."""
    if not isinstance(manifest, bytes) or not manifest or len(manifest) > 8 * 1024 * 1024:
        raise CandidateSignatureError("manifest bytes are empty or exceed the 8 MiB limit")
    trusted_key_id = _validate_key_id(trusted_key_id)
    if not isinstance(envelope_bytes, bytes) or not envelope_bytes or len(envelope_bytes) > 16 * 1024:
        raise CandidateSignatureError("signature envelope is missing or exceeds the 16 KiB limit")
    try:
        envelope = json.loads(envelope_bytes, object_pairs_hook=_strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise CandidateSignatureError("signature envelope is not valid JSON") from None
    if not isinstance(envelope, dict) or set(envelope) != {
        "signature_version", "signing_key_id", "signature",
    }:
        raise CandidateSignatureError("signature envelope fields are invalid")
    if type(envelope["signature_version"]) is not int or envelope["signature_version"] != SIGNATURE_VERSION:
        raise CandidateSignatureError("unsupported signature envelope version")
    key_id = _validate_key_id(envelope["signing_key_id"])
    if key_id != trusted_key_id:
        raise CandidateSignatureError("trusted signing key ID mismatch")
    encoded = envelope["signature"]
    if not isinstance(encoded, str):
        raise CandidateSignatureError("signature is not base64 text")
    try:
        signature = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise CandidateSignatureError("signature is not valid base64") from None
    _verify_raw(_signed_message(manifest, key_id), signature, public_key, runner=runner)
