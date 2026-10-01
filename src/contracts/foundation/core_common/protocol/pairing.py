"""``rosy-pair/1`` pure logic: confirmation code, site fingerprint, JSON shapes (D-341 3, 4, 8, 14).

The machine source is ``test/fixtures/protocol/pairing.v1.json``; Fleet, Vision and the
Rosy Cam Kotlin tests read the same file. Standard library only.

Byte encoding of the code (the plan left it open; the vector is canonical): six UTF-8
fields, each prefixed by its byte length as a 4-byte big-endian unsigned integer, in the
order ``"rosy-pair/1"``, role, request_id, leaf_cert_sha256 (lowercase hex text),
client_nonce, server_nonce. ``decimal6`` takes the first 8 digest bytes as a big-endian
unsigned integer modulo 1,000,000, zero-padded to six digits. Length prefixes make the
field boundaries unambiguous without reserving a separator character.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import ssl

from . import device_kind, discovery_txt, site_link

PROTO = "rosy-pair/1"
ROLE = device_kind.OVERHEAD_CAMERA
MAX_REQUEST_BYTES = 4096

REQUEST_REASONS = (
    "too_large", "not_object", "unknown_field", "missing_field", "proto", "role", "bad_value",
)
RESULT_REASONS = (
    "not_object", "missing_field", "proto", "role", "bad_value", "bad_tls_host", "bad_ca_pem",
    "leaf_not_ca", "bad_expires_at",
)
PAIRABLE_REASONS = discovery_txt.REASONS + ("not_overhead", "no_pair")

REQUEST_FIELDS = ("proto", "role", "device_label", "app_version", "client_commit",
                  "poll_secret_sha256")
RESULT_FIELDS = ("proto", "role", "site_name", "source_id", "tls_host", "site_ca_pem", "token",
                 "credential_id", "expires_at")

# 32 random bytes as base64url without padding: nonces, the poll secret and the token.
SECRET_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")
SHA256_HEX = re.compile(r"[0-9a-f]{64}")
CODE_PATTERN = re.compile(r"[0-9]{6}")
SOURCE_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,32}")  # rosy-overhead/1 source names
CREDENTIAL_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")
_LABEL_LIMITS = {"device_label": 64, "app_version": 32}


def new_secret() -> str:
    """32 random bytes, base64url without padding (43 characters)."""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")


def sha256_text(value: str) -> str:
    """Lowercase hex SHA-256 of ``value``'s UTF-8 bytes (commit, poll and token digests)."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def commit(client_nonce: str) -> str:
    """``client_commit`` sent before the nonce is revealed."""
    return sha256_text(client_nonce)


def confirmation_code(*, role: str, request_id: str, leaf_cert_sha256: str, client_nonce: str,
                      server_nonce: str) -> str:
    """Six-digit code both sides compute; a relayed TLS leaf changes it (D-341 3)."""
    framed = bytearray()
    for part in (PROTO, role, request_id, leaf_cert_sha256, client_nonce, server_nonce):
        encoded = part.encode("utf-8")
        framed += len(encoded).to_bytes(4, "big") + encoded
    digest = hashlib.sha256(bytes(framed)).digest()
    return f"{int.from_bytes(digest[:8], 'big') % 1_000_000:06d}"


def der_sha256(pem: str) -> str:
    """Lowercase hex SHA-256 of the first PEM certificate's DER (the served leaf, or a CA)."""
    match = re.search(r"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----", pem, re.DOTALL)
    if match is None:
        raise ValueError("no PEM certificate found")
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(match.group(0))).hexdigest()


def fingerprint_from_sha256(der_sha256_hex: str) -> str:
    """First 16 hex of a DER SHA-256, upper case, in groups of four (D-341 4)."""
    head = der_sha256_hex[:16].upper()
    return "-".join(head[index:index + 4] for index in range(0, 16, 4))


def site_fingerprint(ca_pem: str) -> str:
    return fingerprint_from_sha256(der_sha256(ca_pem))


def _load_object(raw: bytes) -> dict | None:
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return body if isinstance(body, dict) else None


def _clean_label(value: object, limit: int) -> bool:
    return (isinstance(value, str) and 0 < len(value.strip()) <= limit
            and len(value) <= limit and not any(ord(char) < 32 or ord(char) == 127 for char in value))


def validate_request_bytes(raw: bytes) -> str | None:
    """Reason a pairing request body is refused, or None. Size is checked before parsing."""
    if len(raw) > MAX_REQUEST_BYTES:
        return "too_large"
    body = _load_object(raw)
    if body is None:
        return "not_object"
    if set(body) - set(REQUEST_FIELDS):
        return "unknown_field"
    if any(name not in body for name in REQUEST_FIELDS):
        return "missing_field"
    if body["proto"] != PROTO:
        return "proto"
    if body["role"] != ROLE:
        return "role"
    for name, limit in _LABEL_LIMITS.items():
        if not _clean_label(body[name], limit):
            return "bad_value"
    for name in ("client_commit", "poll_secret_sha256"):
        if not isinstance(body[name], str) or not SHA256_HEX.fullmatch(body[name]):
            return "bad_value"
    return None


def validate_reveal_bytes(raw: bytes) -> str | None:
    """Reason a reveal body ``{"client_nonce"}`` is refused, or None."""
    if len(raw) > MAX_REQUEST_BYTES:
        return "too_large"
    body = _load_object(raw)
    if body is None:
        return "not_object"
    if set(body) - {"client_nonce"}:
        return "unknown_field"
    if "client_nonce" not in body:
        return "missing_field"
    nonce = body["client_nonce"]
    if not isinstance(nonce, str) or not SECRET_PATTERN.fullmatch(nonce):
        return "bad_value"
    return None


def validate_result(result: object) -> str | None:
    """Reason a delivered pairing result is unusable, or None. Unknown fields are ignored."""
    if not isinstance(result, dict):
        return "not_object"
    if any(result.get(name) is None for name in RESULT_FIELDS):
        return "missing_field"
    if result["proto"] != PROTO:
        return "proto"
    if result["role"] != ROLE:
        return "role"
    site_name = result["site_name"]
    if not isinstance(site_name, str) or not site_name.strip():
        return "bad_value"
    if not isinstance(result["source_id"], str) or not SOURCE_PATTERN.fullmatch(result["source_id"]):
        return "bad_value"
    if not isinstance(result["token"], str) or not SECRET_PATTERN.fullmatch(result["token"]):
        return "bad_value"
    credential_id = result["credential_id"]
    if not isinstance(credential_id, str) or not CREDENTIAL_ID_PATTERN.fullmatch(credential_id):
        return "bad_value"
    tls_host = result["tls_host"]
    if not isinstance(tls_host, str) or not discovery_txt.HOSTNAME.fullmatch(tls_host):
        return "bad_tls_host"
    ca_reason = site_link._ca_pem_reason(result["site_ca_pem"])
    if ca_reason:
        return ca_reason
    if not site_link._is_utc_timestamp(result["expires_at"]):
        return "bad_expires_at"
    return None


def pairable(service_type: str, host: str | None, address: str | None, port: object,
             txt: list[tuple[str, str]]) -> str | None:
    """None when a discovery record may receive a pairing request, else a reason (D-341 14, 17)."""
    verdict = discovery_txt.classify(service_type, host, address, port, txt)
    if isinstance(verdict, discovery_txt.Rejected):
        return verdict.reason
    if verdict.service_type != discovery_txt.OVERHEAD:
        return "not_overhead"
    if verdict.txt.get("pair") != PROTO:
        return "no_pair"
    return None
