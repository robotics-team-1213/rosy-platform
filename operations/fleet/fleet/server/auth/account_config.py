"""Explicit protected Account authority configuration; no inferred identity or signing key."""
import json
import os
import re
import stat
from pathlib import Path


def _protected(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Account configuration requires a protected regular file")
    mode = path.stat()
    if os.name == "posix" and (mode.st_uid != os.getuid() or stat.S_IMODE(mode.st_mode) & 0o077):
        raise ValueError("Account configuration requires an owner-only protected file")
    return path


def load_account_config(path):
    path = _protected(path)
    if path.stat().st_size > 65536:
        raise ValueError("Account configuration too large")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate Account configuration field")
            result[key] = value
        return result

    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    required = {"issuer", "site_id", "key_id", "private_key_file", "clients"}
    if (not isinstance(data, dict) or not required <= set(data)
            or set(data) - required - {"bootstrap_admin_login"}
            or any(not isinstance(data[key], str) or not data[key] for key in required - {"clients"})
            or not re.fullmatch(r"[A-Za-z0-9._-]{1,96}", data["site_id"])
            or not isinstance(data["clients"], dict) or not data["clients"]
            or ("bootstrap_admin_login" in data and not isinstance(data["bootstrap_admin_login"], str))):
        raise ValueError("invalid Account configuration fields")
    key = _protected(path.parent / data.pop("private_key_file"))
    if key.stat().st_size > 8192:
        raise ValueError("Account signing key too large")
    data["private_key"] = key.read_bytes()
    return data
