"""Stored site-link record check (D-391 1).

The machine source is ``test/fixtures/protocol/site-link.v1.json``. A site
client (Rosy Cam, FleetAgent) keeps one record per site with the same field
names; ``validate`` returns None for a usable record or one reason from
``REASONS``.

Standard library only. The CA check is a minimal DER walk: it decodes each
PEM CERTIFICATE block and reads the basicConstraints extension. It does not
verify signatures, validity dates or the chain; TLS does that at connect
time. What it catches is the 2026-09-30 failure class: a leaf certificate
(or a leaf in the bundle) stored where the site CA belongs.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import re
from datetime import datetime

from . import device_kind
from .discovery_txt import HOSTNAME

REASONS = (
    "missing_field", "bad_value", "ip_as_tls_host", "bad_tls_host", "bad_ca_pem", "leaf_not_ca",
    "bad_port", "unknown_role", "bad_expires_at", "missing_credential", "credential_conflict",
    "bad_manual_host",
)

REQUIRED = ("site_name", "tls_host", "port", "ca_pem", "role", "credential_id", "expires_at")

_EXPIRES_AT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$")
_PEM_BLOCK = re.compile(
    r"-----BEGIN CERTIFICATE-----(?P<body>[A-Za-z0-9+/=\s]*?)-----END CERTIFICATE-----")
_DNS_NAME = re.compile(
    r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")
# DER encoding of OID 2.5.29.19 (id-ce-basicConstraints).
_BASIC_CONSTRAINTS_OID = bytes.fromhex("0603551d13")


class _DerError(ValueError):
    pass


def validate(record: object) -> str | None:
    """Return None when ``record`` is a valid site-link record, else a reason."""
    if not isinstance(record, dict):
        return "bad_value"
    for name in REQUIRED:
        if name not in record or record[name] is None:
            return "missing_field"
    for name in ("site_name", "credential_id"):
        if not isinstance(record[name], str) or not record[name].strip():
            return "bad_value"

    tls_host = record["tls_host"]
    if not isinstance(tls_host, str):
        return "bad_tls_host"
    if _is_ip(tls_host):
        return "ip_as_tls_host"
    if not HOSTNAME.match(tls_host.lower()):
        return "bad_tls_host"

    port = record["port"]
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        return "bad_port"
    if record["role"] not in device_kind.ALL:
        return "unknown_role"
    if not _is_utc_timestamp(record["expires_at"]):
        return "bad_expires_at"

    ca_reason = _ca_pem_reason(record["ca_pem"])
    if ca_reason:
        return ca_reason

    has_secret = record.get("credential") is not None
    has_ref = record.get("credential_ref") is not None
    if has_secret and has_ref:
        return "credential_conflict"
    if not (has_secret or has_ref):
        return "missing_credential"
    value = record["credential"] if has_secret else record["credential_ref"]
    if not isinstance(value, str) or not value:
        return "bad_value"

    manual_host = record.get("manual_host")
    if manual_host is not None and not (
            isinstance(manual_host, str) and (_is_ip(manual_host) or _DNS_NAME.match(manual_host))):
        return "bad_manual_host"
    # Unknown top-level fields are ignored on purpose (forward compatible).
    return None


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def _is_utc_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not _EXPIRES_AT.match(value):
        return False
    try:
        datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return False
    return True


def _ca_pem_reason(value: object) -> str | None:
    """bad_ca_pem unless every block parses; leaf_not_ca if any block is not a CA."""
    if not isinstance(value, str):
        return "bad_ca_pem"
    blocks = list(_PEM_BLOCK.finditer(value))
    if not blocks or _PEM_BLOCK.sub("", value).strip():
        return "bad_ca_pem"
    verdicts = []
    for block in blocks:
        try:
            der = base64.b64decode("".join(block.group("body").split()), validate=True)
            verdicts.append(_is_ca_certificate(der))
        except (binascii.Error, _DerError):
            return "bad_ca_pem"
    return None if all(verdicts) else "leaf_not_ca"


def _tlv(data: bytes, pos: int, end: int) -> tuple[int, int, int]:
    """Read one DER TLV at ``pos``; return (tag, content_start, content_end)."""
    if pos + 2 > end:
        raise _DerError("truncated")
    tag, length = data[pos], data[pos + 1]
    pos += 2
    if length & 0x80:
        count = length & 0x7F
        if count == 0 or count > 4 or pos + count > end:
            raise _DerError("bad length")
        length = int.from_bytes(data[pos:pos + count], "big")
        pos += count
    if pos + length > end:
        raise _DerError("truncated")
    return tag, pos, pos + length


def _children(data: bytes, start: int, end: int) -> list[tuple[int, int, int]]:
    items, pos = [], start
    while pos < end:
        item = _tlv(data, pos, end)
        items.append(item)
        pos = item[2]
    return items


def _is_ca_certificate(der: bytes) -> bool:
    """True when basicConstraints says cA=TRUE; absent extension means not a CA (RFC 5280)."""
    tag, start, end = _tlv(der, 0, len(der))
    if tag != 0x30:
        raise _DerError("certificate is not a SEQUENCE")
    parts = _children(der, start, end)
    if len(parts) != 3 or parts[0][0] != 0x30:
        raise _DerError("certificate must hold tbsCertificate, algorithm, signature")
    for tag, start, end in _children(der, parts[0][1], parts[0][2]):
        if tag != 0xA3:  # [3] EXPLICIT extensions
            continue
        seq_tag, seq_start, seq_end = _tlv(der, start, end)
        if seq_tag != 0x30:
            raise _DerError("extensions are not a SEQUENCE")
        for ext_tag, ext_start, ext_end in _children(der, seq_start, seq_end):
            fields = _children(der, ext_start, ext_end)
            if ext_tag != 0x30 or not fields:
                raise _DerError("bad extension")
            oid = der[ext_start:fields[0][2]]
            if oid != _BASIC_CONSTRAINTS_OID:
                continue
            value_tag, value_start, value_end = fields[-1]
            if value_tag != 0x04:
                raise _DerError("extnValue is not an OCTET STRING")
            bc_tag, bc_start, bc_end = _tlv(der, value_start, value_end)
            if bc_tag != 0x30:
                raise _DerError("basicConstraints is not a SEQUENCE")
            inner = _children(der, bc_start, bc_end)
            # cA BOOLEAN DEFAULT FALSE: present and non-zero means CA.
            return bool(inner) and inner[0][0] == 0x01 and der[inner[0][1]:inner[0][2]] != b"\x00"
    return False
