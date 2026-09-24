"""Checksums and Ed25519 signatures for ROSY release artifacts.

Both the image distribution directory and the release bundle carry the same
two files:

``SHA256SUMS``
    Every payload file listed once, in ascending path order, in the usual
    ``<64-hex>  <path>`` form.
``SHA256SUMS.sig``
    A detached Ed25519 signature over the **exact bytes** of ``SHA256SUMS``,
    stored base64-encoded.

Verification order matters and is enforced by :func:`verify_release_files`:
the signature over the checksum list is checked first, and only then are
individual files hashed. Reversed, an attacker who can rewrite ``SHA256SUMS``
gets every file's checksum to agree with a payload they chose.

Signing and verification shell out to OpenSSL 3 rather than adding a Python
crypto dependency. The design already requires the signature to be one
OpenSSL can process, the device has ``openssl`` in the base OS, and an update
path that depends on a pip install is an update path that can fail for a new
reason. The signing private key never touches this code: it lives in a
separate signing environment, and only :func:`sign_checksums` — which is run
there, not on the robot — reads it.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

CHECKSUM_FILENAME = "SHA256SUMS"
SIGNATURE_FILENAME = "SHA256SUMS.sig"

#: Ed25519 signatures are exactly 64 bytes (RFC 8032).
SIGNATURE_LENGTH = 64

_SUMS_LINE = re.compile(r"^(?P<sha256>[0-9a-f]{64})  (?P<path>.+)$")

_READ_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class Rejection:
    """One reason a release is not trustworthy. Mirrors manifest.Rejection."""

    code: str
    field: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.code}] {self.field}: {self.detail}"


class SigningToolMissing(RuntimeError):
    """OpenSSL is unavailable, so nothing can be signed or verified.

    Raised rather than reported as a rejection: an absent verifier is not the
    same as a bad signature, and must never be mistaken for one.
    """


# Windows operator PCs often carry OpenSSL only inside Git for Windows, which a
# plain PowerShell PATH does not include. 2026-09-24: the card writer's release
# check failed with "openssl not found" while pytest passed, because only
# test/conftest.py knew these folders.
_WINDOWS_OPENSSL_DIRS = (
    r"C:\Program Files\Git\usr\bin",
    r"C:\Program Files\Git\mingw64\bin",
)


def _openssl() -> str:
    path = shutil.which("openssl")
    if path is None and os.name == "nt":
        for folder in _WINDOWS_OPENSSL_DIRS:
            candidate = os.path.join(folder, "openssl.exe")
            if os.path.isfile(candidate):
                path = candidate
                break
    if path is None:
        raise SigningToolMissing(
            "openssl not found; release signatures cannot be verified without it"
        )
    return path


def sha256_file(path: Path) -> str:
    """Hex digest of a file, read in chunks so a 2 GB image does not go in RAM."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_READ_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def build_sha256sums(root: Path, relative_paths: list[str]) -> bytes:
    """Render the checksum list for ``relative_paths``, ascending by path.

    Returns bytes, not str: the signature covers exact bytes, so the caller
    must write back precisely what was signed. Newlines are LF regardless of
    the build host.
    """
    lines = []
    for relative in sorted(relative_paths):
        digest = sha256_file(root / relative)
        lines.append(f"{digest}  {relative}\n")
    return "".join(lines).encode("utf-8")


def parse_sha256sums(data: bytes) -> tuple[dict[str, str], list[Rejection]]:
    """Parse a checksum list into ``{path: sha256}`` plus any rejections."""
    entries: dict[str, str] = {}
    rejections: list[Rejection] = []

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        return {}, [Rejection("SHA256SUMS_MALFORMED", CHECKSUM_FILENAME, f"not UTF-8: {exc}")]

    previous: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        match = _SUMS_LINE.match(line)
        if match is None:
            rejections.append(
                Rejection(
                    "SHA256SUMS_MALFORMED",
                    f"{CHECKSUM_FILENAME}:{number}",
                    f"expected '<64-hex>  <path>', got {line!r}",
                )
            )
            continue

        path = match.group("path")
        if _escapes_root(path):
            rejections.append(
                Rejection(
                    "SHA256SUMS_PATH_UNSAFE",
                    f"{CHECKSUM_FILENAME}:{number}",
                    f"{path!r} leaves the release root; verify_checksums would hash "
                    "a file outside it",
                )
            )
            continue
        if path in entries:
            rejections.append(
                Rejection(
                    "SHA256SUMS_DUPLICATE",
                    f"{CHECKSUM_FILENAME}:{number}",
                    f"{path!r} listed twice; one entry would shadow the other",
                )
            )
            continue
        if previous is not None and path < previous:
            rejections.append(
                Rejection(
                    "SHA256SUMS_UNORDERED",
                    f"{CHECKSUM_FILENAME}:{number}",
                    f"{path!r} sorts before {previous!r}; the list must be in ascending path order",
                )
            )
        previous = path
        entries[path] = match.group("sha256")

    if not entries and not rejections:
        rejections.append(
            Rejection("SHA256SUMS_EMPTY", CHECKSUM_FILENAME, "checksum list has no entries")
        )

    return entries, rejections


def _escapes_root(path: str) -> bool:
    """Whether a checksum-list path points outside the release directory.

    manifest.py already refuses these for payload entries. The checksum list
    is signed, so a bad path here is not directly exploitable — but the two
    validators should apply the same discipline, and verify_checksums joins
    these straight onto the release root.
    """
    normalised = path.replace("\\", "/")
    if normalised.startswith("/") or re.match(r"^[A-Za-z]:", path):
        return True
    return any(part == ".." for part in normalised.split("/"))


def sign_checksums(sums: bytes, private_key: Path) -> str:
    """Sign ``sums`` with an Ed25519 private key, returning base64.

    Run in the signing environment only. The robot never has this key, and
    neither does the build host.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        message = tmp_path / "message"
        signature = tmp_path / "signature"
        message.write_bytes(sums)

        result = subprocess.run(
            [
                _openssl(), "pkeyutl", "-sign",
                "-inkey", str(private_key),
                "-rawin", "-in", str(message),
                "-out", str(signature),
            ],
            capture_output=True,
            check=False,  # the return code is inspected below, with context
        )
        if result.returncode != 0:
            raise RuntimeError(f"openssl signing failed: {result.stderr.decode('utf-8', 'replace').strip()}")

        raw = signature.read_bytes()

    if len(raw) != SIGNATURE_LENGTH:
        raise RuntimeError(f"expected a {SIGNATURE_LENGTH}-byte Ed25519 signature, got {len(raw)}")
    return base64.b64encode(raw).decode("ascii")


def verify_signature(sums: bytes, signature_b64: str, public_key: Path) -> list[Rejection]:
    """Verify a detached Ed25519 signature over the exact bytes of ``sums``."""
    if not public_key.is_file():
        return [
            Rejection(
                "SIGNATURE_KEY_UNREADABLE",
                str(public_key),
                "trusted release key not found; the device cannot establish who signed this release",
            )
        ]

    stripped = "".join(signature_b64.split())
    if not stripped:
        return [Rejection("SIGNATURE_MISSING", SIGNATURE_FILENAME, "signature file is empty")]

    try:
        raw = base64.b64decode(stripped, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        return [Rejection("SIGNATURE_MALFORMED", SIGNATURE_FILENAME, f"not valid base64: {exc}")]

    if len(raw) != SIGNATURE_LENGTH:
        return [
            Rejection(
                "SIGNATURE_MALFORMED",
                SIGNATURE_FILENAME,
                f"expected a {SIGNATURE_LENGTH}-byte Ed25519 signature, got {len(raw)}",
            )
        ]

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        message = tmp_path / "message"
        sigfile = tmp_path / "signature"
        message.write_bytes(sums)
        sigfile.write_bytes(raw)

        result = subprocess.run(
            [
                _openssl(), "pkeyutl", "-verify",
                "-pubin", "-inkey", str(public_key),
                "-rawin", "-in", str(message),
                "-sigfile", str(sigfile),
            ],
            capture_output=True,
            check=False,  # a bad signature is a rejection, not an exception
        )

    if result.returncode != 0:
        return [
            Rejection(
                "SIGNATURE_INVALID",
                SIGNATURE_FILENAME,
                "signature does not verify against the trusted release key; "
                "the checksum list was modified or signed by someone else",
            )
        ]
    return []


def verify_checksums(root: Path, entries: dict[str, str]) -> list[Rejection]:
    """Check every listed file against its recorded digest."""
    rejections: list[Rejection] = []

    for relative in sorted(entries):
        path = root / relative
        if not path.is_file():
            rejections.append(
                Rejection("CHECKSUM_FILE_MISSING", relative, "listed in the checksum list but not present")
            )
            continue
        actual = sha256_file(path)
        if actual != entries[relative]:
            rejections.append(
                Rejection(
                    "CHECKSUM_MISMATCH",
                    relative,
                    f"expected {entries[relative]}, got {actual}",
                )
            )
    return rejections


def find_unlisted_files(root: Path, entries: dict[str, str]) -> list[Rejection]:
    """Report payload files absent from the checksum list.

    An unlisted file is covered by no checksum and therefore by no signature,
    which makes it the obvious place to put something extra.
    """
    ignored = {CHECKSUM_FILENAME, SIGNATURE_FILENAME}
    rejections: list[Rejection] = []

    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if relative in ignored:
            continue

        # is_file() follows symlinks, so a dangling one reads as "not a file"
        # and vanished from this check entirely.
        if path.is_symlink():
            rejections.append(
                Rejection(
                    "CHECKSUM_SYMLINK",
                    relative,
                    "a release must not contain symlinks; what it resolves to is "
                    "not covered by the checksum list",
                )
            )
            continue

        if not path.is_file() or relative in entries:
            continue
        rejections.append(
            Rejection(
                "CHECKSUM_UNLISTED_FILE",
                relative,
                "present in the release but not covered by the signed checksum list",
            )
        )
    return rejections


def verify_release_files(root: Path, public_key: Path) -> list[Rejection]:
    """Verify a release directory: signature first, then payload checksums.

    Order is the point. If the checksums were validated before the signature
    over the list, rewriting ``SHA256SUMS`` would make every file agree with
    whatever payload the attacker supplied.
    """
    sums_path = root / CHECKSUM_FILENAME
    sig_path = root / SIGNATURE_FILENAME

    if not sums_path.is_file():
        return [Rejection("SHA256SUMS_MISSING", CHECKSUM_FILENAME, "release has no checksum list")]
    if not sig_path.is_file():
        return [Rejection("SIGNATURE_MISSING", SIGNATURE_FILENAME, "release is unsigned")]

    sums = sums_path.read_bytes()
    try:
        signature = sig_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Not valid text, so certainly not valid base64 — a rejection, not a
        # traceback out of the update path.
        return [
            Rejection("SIGNATURE_MALFORMED", SIGNATURE_FILENAME, "signature file is not UTF-8 text")
        ]
    rejections = verify_signature(sums, signature, public_key)
    if rejections:
        # Do not hash anything on an untrusted list: it would report
        # reassuring "checksum OK" lines for attacker-chosen content.
        return rejections

    entries, rejections = parse_sha256sums(sums)
    if rejections:
        return rejections

    return verify_checksums(root, entries) + find_unlisted_files(root, entries)
