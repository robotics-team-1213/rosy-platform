"""Fail-closed loader for per-principal Fleet API token digests and D-519 console logins.

`python -m fleet.server.site_users hash-password` reads one password from standard input
and prints the `password_scrypt` value for `site-users.yaml`.
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import re
import secrets
import sys
from pathlib import Path
from typing import Mapping

import yaml

_ROLES = {"viewer", "operator", "policy-admin", "service"}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_LOGIN = re.compile(r"[a-z0-9._-]{1,32}\Z")
_FIELDS = {"principal_id", "role", "token_sha256", "login", "password_scrypt"}

#: D-519 1: n=2^15, r=8, p=1, 16-byte salt, 32-byte result.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 15, 8, 1


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    # OpenSSL needs about 128*r*(n+p+2) bytes; the 32 MiB default refuses n=2^15, r=8.
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
                          maxmem=128 * r * (n + p + 2) + 2 ** 20, dklen=32)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return "$".join(("scrypt", str(SCRYPT_N), str(SCRYPT_R), str(SCRYPT_P),
                     base64.b64encode(salt).decode("ascii"), base64.b64encode(digest).decode("ascii")))


def _parse_password_hash(encoded: object) -> tuple[int, int, int, bytes, bytes]:
    parts = encoded.split("$") if isinstance(encoded, str) else []
    try:
        if len(parts) != 6 or parts[0] != "scrypt":
            raise ValueError
        n, r, p = (int(part) for part in parts[1:4])
        salt = base64.b64decode(parts[4], validate=True)
        digest = base64.b64decode(parts[5], validate=True)
    except ValueError:
        raise ValueError("site user password_scrypt must be scrypt$n$r$p$salt$hash") from None
    # Bounded so a bad file cannot make every login allocate gigabytes.
    if (n < 2 ** 14 or n > 2 ** 20 or n & (n - 1) or not 1 <= r <= 16 or not 1 <= p <= 4
            or len(salt) < 16 or len(digest) != 32):
        raise ValueError("site user password_scrypt parameters are out of range")
    return n, r, p, salt, digest


def verify_password(password: str, encoded: str) -> bool:
    n, r, p, salt, digest = _parse_password_hash(encoded)
    return hmac.compare_digest(_scrypt(password, salt, n, r, p), digest)


def load_site_users(path: Path | str) -> dict[str, dict[str, str]]:
    """Principal/role metadata keyed by lowercase SHA-256 token digest (token users only)."""
    return load_site_accounts(path)[0]


def load_site_accounts(path: Path | str) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    """Token users keyed by digest, and D-519 login users keyed by login.

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
    logins: dict[str, dict[str, str]] = {}
    principals: set[str] = set()
    for entry in entries:
        keys = set(entry) if isinstance(entry, Mapping) else set()
        if (not {"principal_id", "role"} <= keys or not keys <= _FIELDS
                or ("login" in keys) != ("password_scrypt" in keys)
                or not keys & {"token_sha256", "login"}):
            raise ValueError("each site user requires principal_id, role, and token_sha256 "
                             "and/or login with password_scrypt")
        principal_id = entry["principal_id"]
        role = entry["role"]
        if not isinstance(principal_id, str) or not principal_id.strip():
            raise ValueError("site principal_id must be non-empty")
        principal_id = principal_id.strip()
        if principal_id in principals:
            raise ValueError("site principal_id values must be unique")
        if role not in _ROLES:
            raise ValueError("site user role is unknown")
        if "token_sha256" in keys:
            token_digest = entry["token_sha256"]
            if not isinstance(token_digest, str) or not _SHA256.fullmatch(token_digest):
                raise ValueError("site user token_sha256 must be a lowercase SHA-256 digest")
            if token_digest in users:
                raise ValueError("site user token digests must be unique")
            users[token_digest] = {"principal_id": principal_id, "role": role}
        if "login" in keys:
            login = entry["login"]
            if role == "service":
                raise ValueError("service principals cannot have a console login")
            if not isinstance(login, str) or not _LOGIN.fullmatch(login):
                raise ValueError("site user login must match ^[a-z0-9._-]{1,32}$")
            if login in logins:
                raise ValueError("site user logins must be unique")
            _parse_password_hash(entry["password_scrypt"])
            logins[login] = {"principal_id": principal_id, "role": role,
                             "password_scrypt": entry["password_scrypt"]}
        principals.add(principal_id)
    return users, logins


def main(argv: list[str]) -> int:
    if argv != ["hash-password"]:
        print("usage: python -m fleet.server.site_users hash-password < password", file=sys.stderr)
        return 2
    password = (getpass.getpass("password: ") if sys.stdin.isatty()
                else sys.stdin.readline().rstrip("\r\n"))
    if not password:
        print("password must not be empty", file=sys.stderr)
        return 1
    print(hash_password(password))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
