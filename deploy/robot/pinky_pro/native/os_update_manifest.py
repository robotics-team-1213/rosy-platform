"""Exact signed OS distribution metadata; independent of native payload ordering."""
from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import re

from os_state_layout import _pairs
from signing import verify_signature

COMPATIBLE = "rosy-pinky-pro-ab-v2"
FIELDS = {"schema_version", "kind", "board", "arch", "compatible", "release_id", "source_revision",
          "bundle", "rootfs_bytes", "boot_bytes", "native_factory", "boot_abi", "state_schema", "cms_signer_spki_sha256"}
MAX_METADATA = 16384
GIB = 1024**3


def _fields(value, expected):
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("unexpected fields")


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("invalid integer")


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("invalid SHA256 digest")


def release_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}", value):
        raise ValueError("invalid release identity")
    date.fromisoformat(value[:10].replace(".", "-"))
    return value


def validate_metadata(value: dict) -> dict:
    try:
        _fields(value, FIELDS)
        _integer(value["schema_version"], 1, 1)
        for key, expected in (("kind", "os-update"), ("board", "pinky_pro"), ("arch", "arm64"),
                              ("compatible", COMPATIBLE)):
            if value[key] != expected:
                raise ValueError("unsupported " + key)
        identity = release_id(value["release_id"])
        if not isinstance(value["source_revision"], str) or not re.fullmatch(r"[0-9a-f]{40}", value["source_revision"]):
            raise ValueError("source revision is not an exact commit")
        bundle = value["bundle"]
        _fields(bundle, {"filename", "sha256", "size_bytes"})
        if bundle["filename"] != f"rosy-os-pinky-pro-{identity}-arm64.raucb":
            raise ValueError("bundle name differs from OS release")
        _digest(bundle["sha256"])
        _integer(bundle["size_bytes"], 1, 16 * GIB)
        for key, maximum in (("rootfs_bytes", 16 * GIB), ("boot_bytes", 512 * 1024**2)):
            _integer(value[key], 512, maximum)
            if value[key] % 512:
                raise ValueError("OS image size is not sector aligned")
        factory = value["native_factory"]
        _fields(factory, {"release_id", "checksums_sha256"})
        release_id(factory["release_id"])
        _digest(factory["checksums_sha256"])
        _integer(value["boot_abi"], 2, 2)
        schema = value["state_schema"]
        _fields(schema, {"read_min", "read_max", "write"})
        for version in schema.values():
            _integer(version, 1, 1)
        _digest(value["cms_signer_spki_sha256"])
        return value
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError(f"OS_UPDATE_METADATA: {exc}") from exc


def verify_metadata(raw: bytes, signature: str, public_key: Path) -> dict:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_METADATA:
        raise ValueError("OS_UPDATE_METADATA: invalid raw metadata size")
    if (not isinstance(signature, str) or len(signature) > 256
            or verify_signature(raw, signature, public_key)):
        raise ValueError("OS_UPDATE_SIGNATURE: untrusted OS metadata")
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("OS_UPDATE_METADATA: invalid JSON") from exc
    return validate_metadata(value)
