"""Fail-closed loader for per-principal Fleet API token digests."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping

import yaml

_ROLES = {"viewer", "operator", "policy-admin"}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def load_site_users(path: Path | str) -> dict[str, dict[str, str]]:
    """Load principal/role metadata keyed by lowercase SHA-256 token digest.

    Raw credentials are provisioned out of band and never stored in this file.
    The file itself should be mounted read-only with operator-only permissions.
    """
    try:
        document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError("unable to load site user credentials") from exc
    if not isinstance(document, Mapping) or set(document) != {"users"}:
        raise ValueError("site user file must contain only a users list")
    entries = document["users"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("site user list cannot be empty")

    users: dict[str, dict[str, str]] = {}
    principals: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping) or set(entry) != {
            "principal_id", "role", "token_sha256"
        }:
            raise ValueError("each site user requires principal_id, role, and token_sha256")
        principal_id = entry["principal_id"]
        role = entry["role"]
        token_digest = entry["token_sha256"]
        if not isinstance(principal_id, str) or not principal_id.strip():
            raise ValueError("site principal_id must be non-empty")
        principal_id = principal_id.strip()
        if principal_id in principals:
            raise ValueError("site principal_id values must be unique")
        if role not in _ROLES:
            raise ValueError("site user role is unknown")
        if not isinstance(token_digest, str) or not _SHA256.fullmatch(token_digest):
            raise ValueError("site user token_sha256 must be a lowercase SHA-256 digest")
        if token_digest in users:
            raise ValueError("site user token digests must be unique")
        principals.add(principal_id)
        users[token_digest] = {"principal_id": principal_id, "role": role}
    return users
