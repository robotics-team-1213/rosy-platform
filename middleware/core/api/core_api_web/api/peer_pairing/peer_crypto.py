"""Dedicated application identity proof; never a release or SSH signing key."""
import base64
import hashlib
import json
import os
import stat
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


class ProofDenied(ValueError):
    pass


def public_key(key):
    raw = key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return base64.b64encode(raw).decode("ascii")


def fingerprint(encoded):
    return hashlib.sha256(_public(encoded).public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()


def _public(encoded):
    try:
        if not isinstance(encoded, str) or not 1 <= len(encoded) <= 256:
            raise ProofDenied("invalid public key")
        raw = base64.b64decode(encoded, validate=True)
        key = serialization.load_der_public_key(raw)
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
            raise ProofDenied("P-256 public key required")
        if public_key(key) != encoded:
            raise ProofDenied("noncanonical public key")
        return key
    except (ValueError, TypeError) as exc:
        raise ProofDenied("invalid public key") from exc


def transcript(context, fields):
    if context not in {"request", "receiver-challenge", "session-request"}:
        raise ProofDenied("unknown proof context")
    raw = json.dumps({"version": "rosy.peer-proof/1", "context": context, "fields": fields},
                     sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
    if len(raw) > 4096:
        raise ProofDenied("proof transcript too large")
    return raw


def verify(encoded_key, signature, context, fields):
    try:
        if not isinstance(signature, str) or not 1 <= len(signature) <= 128:
            raise ProofDenied("invalid signature")
        raw = base64.b64decode(signature, validate=True)
        if base64.b64encode(raw).decode('ascii') != signature:
            raise ProofDenied('noncanonical signature encoding')
        _public(encoded_key).verify(raw, transcript(context, fields), ec.ECDSA(hashes.SHA256()))
    except (ValueError, TypeError, InvalidSignature) as exc:
        raise ProofDenied("proof rejected") from exc


class PeerIdentity:
    def __init__(self, path, approved_fingerprints):
        path = Path(path).absolute()
        approved = tuple(approved_fingerprints)
        for parent in reversed(path.parents):
            if parent.is_symlink():
                raise ProofDenied("identity ancestor symlink rejected")
            if parent.exists() and os.name == "posix":
                info = parent.stat()
                writable = stat.S_IMODE(info.st_mode) & 0o022
                protected_temporary_root = info.st_uid == 0 and info.st_mode & stat.S_ISVTX
                if info.st_uid not in {0, os.geteuid()} or (writable and not protected_temporary_root):
                    raise ProofDenied("unsafe identity ancestor permissions")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except FileNotFoundError:
            if approved:
                raise ProofDenied("identity key missing for existing relationships")
            generated = ec.generate_private_key(ec.SECP256R1())
            raw = generated.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption())
            try:
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            except FileExistsError:
                descriptor = None
            if descriptor is not None:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise ProofDenied("identity path unavailable") from exc
        try:
            info = os.fstat(descriptor)
            if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
                raise ProofDenied("unsafe identity path")
            if os.name == "posix" and (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077):
                raise ProofDenied("unsafe identity permissions")
            raw = os.read(descriptor, 4097)
        finally:
            os.close(descriptor)
        try:
            self._key = serialization.load_pem_private_key(raw, password=None)
        except (ValueError, TypeError) as exc:
            raise ProofDenied("identity key invalid") from exc
        if not isinstance(self._key, ec.EllipticCurvePrivateKey) or not isinstance(self._key.curve, ec.SECP256R1):
            raise ProofDenied("P-256 identity required")
        self.public_key = public_key(self._key.public_key())
        self.fingerprint = fingerprint(self.public_key)
        if any(value != self.fingerprint for value in approved):
            raise ProofDenied("receiver identity changed")

    def sign(self, context, fields):
        return base64.b64encode(self._key.sign(transcript(context, fields), ec.ECDSA(hashes.SHA256()))).decode("ascii")
