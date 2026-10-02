"""Subject: a model folder is opened only when its manifest carries a trusted signature (D-423 §3.4).

model_manifest.json pins every model file by sha256 (verify_files), so one Ed25519
signature over the manifest's exact bytes covers the whole bundle. It is made on
the PC with the release signing module (deploy/robot/pinky_pro/release/signing.py,
sign_checksums: base64 of the raw signature) and checked here the way release
verification does it (openssl pkeyutl -verify -rawin) against the robot's trusted
release keys. This package cannot import the deploy tree, hence the small mirror;
test_learned_signature.py signs with the release module and verifies with this one.

Unsigned bundles are refused unless the node's allow_unsigned_models dev flag is
on. A bundle whose signature is present but wrong is refused even then."""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .manifest import MANIFEST_NAME, ManifestError

SIGNATURE_NAME = MANIFEST_NAME + ".sig"
TRUSTED_KEYS = "/etc/rosy/trusted-release-keys"
SIGNATURE_LENGTH = 64  # Ed25519, RFC 8032
_WINDOWS_OPENSSL = (r"C:\Program Files\Git\usr\bin", r"C:\Program Files\Git\mingw64\bin")


class SignatureError(ManifestError):
    """The bundle is unsigned or its signature is not from a trusted key."""


def openssl_path() -> str:
    path = shutil.which("openssl")
    if path is None and os.name == "nt":
        path = next((os.path.join(d, "openssl.exe") for d in _WINDOWS_OPENSSL
                     if os.path.isfile(os.path.join(d, "openssl.exe"))), None)
    if path is None:
        raise SignatureError("openssl not found; model signatures cannot be verified")
    return path


def verify_manifest_signature(folder, keys_dir=TRUSTED_KEYS) -> str:
    """The trusted key's name (file stem) that signed this manifest, or SignatureError."""
    folder = Path(folder)
    sig_path = folder / SIGNATURE_NAME
    if not sig_path.is_file():
        raise SignatureError(f"unsigned model: no {SIGNATURE_NAME}")
    try:
        raw = base64.b64decode("".join(sig_path.read_text(encoding="ascii").split()), validate=True)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise SignatureError(f"{SIGNATURE_NAME}: not base64 ({exc})") from exc
    if len(raw) != SIGNATURE_LENGTH:
        raise SignatureError(f"{SIGNATURE_NAME}: expected {SIGNATURE_LENGTH} bytes, got {len(raw)}")
    keys = sorted(p for p in Path(keys_dir).glob("*.pem") if p.is_file() and not p.is_symlink())
    if not keys:
        raise SignatureError(f"no trusted keys in {keys_dir}")
    openssl = openssl_path()
    with tempfile.TemporaryDirectory() as tmp:
        sig_file = Path(tmp) / "signature"
        sig_file.write_bytes(raw)
        for key in keys:
            result = subprocess.run([openssl, "pkeyutl", "-verify", "-pubin", "-inkey", str(key),
                                     "-rawin", "-in", str(folder / MANIFEST_NAME), "-sigfile", str(sig_file)],
                                    capture_output=True, check=False)
            if result.returncode == 0:
                return key.stem
    raise SignatureError(f"no trusted key in {keys_dir} verifies {SIGNATURE_NAME}")


def checked_opener(open_folder, *, allow_unsigned: bool, keys_dir=TRUSTED_KEYS):
    """A ModelSlot opener that verifies the signature first; a failure keeps the old model."""
    def opener(folder):
        if not (allow_unsigned and not (Path(folder) / SIGNATURE_NAME).exists()):
            verify_manifest_signature(folder, keys_dir)
        return open_folder(folder)
    return opener
