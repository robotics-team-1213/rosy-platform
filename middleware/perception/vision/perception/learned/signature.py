"""Subject: a model folder is opened only when its manifest carries a trusted signature (D-423 §3.4).

model_manifest.json pins every model file by sha256 (verify_files), so one Ed25519
signature over the manifest's exact bytes covers the whole bundle. It is made on
the PC with the release signing module (release/signing.py in the robot deploy tree,
sign_checksums: base64 of the raw signature) and checked here the way release
verification does it (openssl pkeyutl -verify -rawin) against the robot's trusted
release keys. This package cannot import the deploy tree, hence the small mirror;
test_learned_signature.py signs with the release module and verifies with this one.

object_det enforces: unsigned bundles are refused unless the dev override
ROSY_ALLOW_UNSIGNED_MODELS=true is in the node's environment (read once at start,
never a ROS parameter); a present but wrong signature is refused even then.
lane_seg is warn-only for now (coordinator decision 2026-10-03): the field's 0930
lane model is unsigned, so the node opens it, logs, and reports signed: false.
Follow-up: sign the 0930 lane model, then enforce for lane_seg too."""

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
ALLOW_UNSIGNED_ENV = "ROSY_ALLOW_UNSIGNED_MODELS"
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
    try:
        with tempfile.TemporaryDirectory() as tmp:
            sig_file = Path(tmp) / "signature"
            sig_file.write_bytes(raw)
            for key in keys:
                result = subprocess.run([openssl, "pkeyutl", "-verify", "-pubin", "-inkey", str(key),
                                         "-rawin", "-in", str(folder / MANIFEST_NAME),
                                         "-sigfile", str(sig_file)],
                                        capture_output=True, check=False, timeout=30)
                if result.returncode == 0:
                    return key.stem
    except (OSError, subprocess.SubprocessError) as exc:  # review M5: a process error is not a crash
        raise SignatureError(f"openssl verification could not run: {exc}") from exc
    raise SignatureError(f"no trusted key in {keys_dir} verifies {SIGNATURE_NAME}")


def allow_unsigned_from_env(environ=os.environ) -> bool:
    """The object_det dev override: only the exact text "true" turns it on."""
    return environ.get(ALLOW_UNSIGNED_ENV) == "true"


class SignatureCheck:
    """A ModelSlot opener that checks the signature first.

    enforce=True refuses (SignatureError keeps the previous model), except an
    unsigned bundle under allow_unsigned. enforce=False opens anyway. Either way
    signed/reason describe the model that was last opened successfully."""

    def __init__(self, open_folder, *, enforce: bool, allow_unsigned: bool = False,
                 keys_dir=TRUSTED_KEYS):
        self._open, self._enforce, self._allow, self._keys = open_folder, enforce, allow_unsigned, keys_dir
        self.signed: bool | None = None
        self.reason: str | None = None

    def __call__(self, folder):
        try:
            verify_manifest_signature(folder, self._keys)
            signed, reason = True, None
        except SignatureError as exc:
            unsigned = not (Path(folder) / SIGNATURE_NAME).exists()
            if self._enforce and not (self._allow and unsigned):
                raise
            signed, reason = False, str(exc)
        model = self._open(folder)
        self.signed, self.reason = signed, reason
        return model


def checked_opener(open_folder, *, allow_unsigned: bool, keys_dir=TRUSTED_KEYS):
    """The enforcing check (object_det)."""
    return SignatureCheck(open_folder, enforce=True, allow_unsigned=allow_unsigned, keys_dir=keys_dir)
