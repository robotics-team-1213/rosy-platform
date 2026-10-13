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
            or set(data) - required - {"bootstrap_admin_login", "public_key_files"}
            or any(not isinstance(data[key], str) or not data[key] for key in required - {"clients"})
            or not re.fullmatch(r"[A-Za-z0-9._-]{1,96}", data["site_id"])
            or not isinstance(data["clients"], dict) or not data["clients"]
            or ("bootstrap_admin_login" in data and not isinstance(data["bootstrap_admin_login"], str))):
        raise ValueError("invalid Account configuration fields")
    key = _protected(path.parent / data.pop("private_key_file"))
    if key.stat().st_size > 8192:
        raise ValueError("Account signing key too large")
    data["private_key"] = key.read_bytes()
    from joserfc.jwk import OKPKey
    signing = OKPKey.import_key(data["private_key"])
    if not signing.is_private or signing.curve_name != "Ed25519":
        raise ValueError("Account signing requires an Ed25519 private key")
    public_files = data.pop('public_key_files', {})
    if not isinstance(public_files, dict) or len(public_files) > 8:
        raise ValueError('Invalid Account verification key ring')
    data['trusted_public_keys'] = {}
    for kid, filename in public_files.items():
        if not isinstance(kid, str) or not re.fullmatch('[A-Za-z0-9._-]{1,96}', kid) or not isinstance(filename, str):
            raise ValueError('Invalid Account verification key')
        public = _protected(path.parent / filename)
        if public.stat().st_size > 8192:
            raise ValueError('Account verification key too large')
        pem = public.read_bytes()
        key = OKPKey.import_key(pem)
        if key.is_private or key.curve_name != 'Ed25519':
            raise ValueError('Account verification requires public Ed25519 keys')
        data['trusted_public_keys'][kid] = pem
    return data
