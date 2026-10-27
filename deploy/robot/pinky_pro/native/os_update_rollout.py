"""Exact-byte Ed25519 OS rollout policy; separate from native tarball rollout state."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import re

from auto_update_host import parse_z
from os_state_layout import _pairs
from os_update_manifest import _digest, _fields, _integer, release_id, validate_metadata
from signing import verify_signature

FIELDS = {"schema_version", "kind", "release_id", "bundle", "bundle_sha256", "published_at",
          "canary", "canary_ok", "withdrawn", "wave_delay_s"}


def _hostname(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 253
            or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in value.split("."))):
        raise ValueError("invalid canary/client hostname")


def _shape(value):
    _fields(value, FIELDS)
    _integer(value["schema_version"], 1, 1)
    if value["kind"] != "os-update":
        raise ValueError("OS rollout kind differs")
    identity = release_id(value["release_id"])
    if value["bundle"] != f"rosy-os-pinky-pro-{identity}-arm64.raucb":
        raise ValueError("OS rollout bundle differs")
    _digest(value["bundle_sha256"])
    if parse_z(value["published_at"]) is None:
        raise ValueError("OS rollout publication time is invalid")
    if type(value["canary_ok"]) is not bool or type(value["withdrawn"]) is not bool:
        raise ValueError("OS rollout promotion/withdrawal must be booleans")
    _integer(value["wave_delay_s"], 600, 2**31 - 1)
    names = value["canary"]
    if not isinstance(names, list) or len(names) > 128:
        raise ValueError("OS canary inventory is invalid")
    for name in names:
        _hostname(name)
    if len(set(names)) != len(names):
        raise ValueError("duplicate OS canary hostname")
    return value


def verify(raw: bytes, signature: str, public_key: Path, metadata: dict) -> dict:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 16384:
        raise ValueError("OS_ROLLOUT: invalid raw metadata size")
    if not isinstance(signature, str) or len(signature) > 256 or verify_signature(raw, signature, public_key):
        raise ValueError("OS_ROLLOUT_SIGNATURE: untrusted OS rollout")
    try:
        value = _shape(json.loads(raw, object_pairs_hook=_pairs))
        validate_metadata(metadata)
        if (value["release_id"] != metadata["release_id"] or value["bundle"] != metadata["bundle"]["filename"]
                or value["bundle_sha256"] != metadata["bundle"]["sha256"]):
            raise ValueError("rollout and authenticated OS metadata differ")
        return value
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise ValueError(f"OS_ROLLOUT: {exc}") from exc


def authorize(value: dict, hostname: str, now: dt.datetime) -> None:
    try:
        _shape(value)
        _hostname(hostname)
        if not isinstance(now, dt.datetime) or now.tzinfo is None:
            raise ValueError("OS rollout clock is unknown")
        published = parse_z(value["published_at"])
        if value["withdrawn"] or now < published:
            raise ValueError("OS rollout withdrawn or not yet published")
        if hostname not in value["canary"] and (
                not value["canary_ok"] or now < published + dt.timedelta(seconds=value["wave_delay_s"])):
            raise ValueError("OS rollout awaits signed canary promotion and wave delay")
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise ValueError(f"OS_ROLLOUT_DEFERRED: {exc}") from exc
