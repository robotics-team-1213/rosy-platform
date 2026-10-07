"""Atomic maintenance for the site Fleet user registry (site-users.yaml).

The file holds only per-principal SHA-256 token digests (D-276). Raw tokens are
provisioned out of band; this tool reads one from stdin only, never from argv,
so it cannot leak through ``ps`` or shell history. Writes are atomic (temp file
+ ``os.replace``) and verified by re-parsing the published bytes with the same
shape rules ``fleet.server.site_users.load_site_users`` enforces, so a file
Fleet would reject is never left in place.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

import yaml

# File-level contract mirrors fleet/server/site_users.py (D-276). `service`
# rows exist for non-operator automation (Cell workspace proposals) and are
# managed by that flow, not provisioned by hand here.
FILE_ROLES = frozenset({"viewer", "operator", "policy-admin", "service"})
CLI_ROLES = frozenset({"viewer", "operator", "policy-admin"})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")

# Fleet reads the mounted config after secret_exec.py drops to UID/GID 10001
# (Dockerfile.fleet), so the published file is root:10001 mode 0440 (README,
# "Prepare an Ubuntu host"). A 2026-10-07 incident restored the file under the
# wrong group and Fleet crash-looped on the unreadable config.
FLEET_GID = 10001
FILE_MODE = 0o440


class SiteUsersError(RuntimeError):
    """A site-users.yaml inspection or change could not be completed safely."""


def validate_users_document(document: object) -> list[dict[str, str]]:
    """Return normalized entries, or raise on the first D-276 shape violation.

    The rules mirror ``fleet.server.site_users.load_site_users`` so this tool
    never publishes a file the Fleet container would reject at startup.
    """
    if not isinstance(document, Mapping) or set(document) != {"users"}:
        raise SiteUsersError("site user file must contain only a users list")
    entries = document["users"]
    if not isinstance(entries, list) or not entries:
        raise SiteUsersError("site user list cannot be empty")
    users: list[dict[str, str]] = []
    principals: set[str] = set()
    digests: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping) or set(entry) != {
            "principal_id", "role", "token_sha256"
        }:
            raise SiteUsersError("each site user requires principal_id, role, and token_sha256")
        principal_id = entry["principal_id"]
        role = entry["role"]
        digest = entry["token_sha256"]
        if not isinstance(principal_id, str) or not principal_id.strip():
            raise SiteUsersError("site principal_id must be non-empty")
        if not isinstance(role, str):
            raise SiteUsersError("site user role must be a string")
        if role not in FILE_ROLES:
            raise SiteUsersError("site user role is unknown")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise SiteUsersError("site user token_sha256 must be a lowercase SHA-256 digest")
        principal_id = principal_id.strip()
        if principal_id in principals:
            raise SiteUsersError("site principal_id values must be unique")
        if digest in digests:
            raise SiteUsersError("site user token digests must be unique")
        principals.add(principal_id)
        digests.add(digest)
        users.append({"principal_id": principal_id, "role": role, "token_sha256": digest})
    return users


def read_valid_users(path: Path | str) -> tuple[str, list[dict[str, str]]]:
    """Parse and validate ``path``; return (source text, normalized entries)."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SiteUsersError(f"unable to read {path}: {exc}") from exc
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SiteUsersError(f"{path.name} is not valid YAML") from exc
    return text, validate_users_document(document)


def list_users(path: Path | str) -> list[dict[str, str]]:
    """Return the registered principals (digests only; no raw tokens exist here)."""
    return read_valid_users(path)[1]


def _publish(path: Path, text: str) -> None:
    """Atomically replace ``path``; the temp file never outlives an error."""
    descriptor, raw_path = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(raw_path)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == "posix":
            os.chmod(temporary, FILE_MODE)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_users(path: Path, original_text: str, document: Mapping[str, object]) -> None:
    """Publish a validated document, then re-read it before calling it done."""
    validate_users_document(document)
    _publish(path, yaml.safe_dump(document, sort_keys=False, width=4096))
    try:
        read_valid_users(path)
    except SiteUsersError:
        _publish(path, original_text)  # keep the last file Fleet accepted
        raise SiteUsersError("re-reading the written file failed; original restored")


def _apply_fleet_ownership(path: Path) -> bool:
    """Root republishes ownership directly; everyone else gets the printed hint."""
    if os.name != "posix" or not hasattr(os, "geteuid") or os.geteuid() != 0:
        return False
    try:
        os.chown(path, 0, FLEET_GID)
        os.chmod(path, FILE_MODE)
    except OSError:
        return False
    return True


def _read_token(stream) -> str:
    try:
        token = stream.read().rstrip("\r\n")
    except OSError as exc:
        raise SiteUsersError("unable to read the token from stdin") from exc
    if not token.strip():
        raise SiteUsersError("token read from stdin is empty")
    return token


def add_user(path: Path | str, principal: str, role: str, token: str,
             *, dry_run: bool = False) -> dict[str, object]:
    """Register one principal; ``token`` is the raw bearer and is hashed here."""
    principal = principal.strip()
    if not principal:
        raise SiteUsersError("principal must be a non-empty id")
    if role not in CLI_ROLES:
        raise SiteUsersError(f"role must be one of {sorted(CLI_ROLES)}")
    if not token.strip():
        raise SiteUsersError("token read from stdin is empty")
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    path = Path(path)
    original_text, users = read_valid_users(path)
    if any(user["principal_id"] == principal for user in users):
        raise SiteUsersError(f"principal {principal} already exists; remove it first")
    if any(user["token_sha256"] == digest for user in users):
        raise SiteUsersError("token already belongs to another principal; provision a fresh one")
    entry = {"principal_id": principal, "role": role, "token_sha256": digest}
    if dry_run:
        validate_users_document({"users": [*users, entry]})
        return {"dry_run": True, "action": "add", "entry": entry}
    _write_users(path, original_text, {"users": [*users, entry]})
    return {"action": "add", "entry": entry}


def remove_user(path: Path | str, principal: str, *, dry_run: bool = False) -> dict[str, object]:
    """Remove one principal's digest; the registry never becomes empty."""
    path = Path(path)
    original_text, users = read_valid_users(path)
    remaining = [user for user in users if user["principal_id"] != principal]
    if len(remaining) == len(users):
        raise SiteUsersError(f"principal {principal} is not registered")
    if not remaining:
        raise SiteUsersError("refusing to remove the last principal; Fleet rejects an empty users list")
    if dry_run:
        return {"dry_run": True, "action": "remove", "principal_id": principal}
    _write_users(path, original_text, {"users": remaining})
    return {"action": "remove", "principal_id": principal}


def validate_file(path: Path | str, *, expected_gid: int = FLEET_GID) -> dict[str, object]:
    """Restart gate for config watchers: content shape plus permission bits.

    A watcher that restarts Fleet on every file change must call this first and
    keep the running container on the last good file when it fails; publishing
    an unreadable file straight into a restart is the 2026-10-07 crash loop.
    """
    path = Path(path)
    _, users = read_valid_users(path)
    report: dict[str, object] = {"path": str(path), "principals": len(users)}
    if os.name != "posix":
        report["ownership"] = "unchecked (non-posix host)"
        return report
    status = path.stat()
    mode = status.st_mode & 0o777
    report.update({"uid": status.st_uid, "gid": status.st_gid, "mode": format(mode, "04o")})
    if mode & 0o007:
        raise SiteUsersError(
            f"mode {format(mode, '04o')} lets others read the digests; expected 0440")
    if mode & 0o020:
        raise SiteUsersError(f"mode {format(mode, '04o')} is group-writable; expected 0440")
    if status.st_gid != expected_gid:
        raise SiteUsersError(
            f"owning group is {status.st_gid}, expected {expected_gid}; Fleet reads the file "
            f"as gid {FLEET_GID} after secret_exec drops privileges")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="print the registered principals")
    listing.add_argument("file", type=Path)
    adding = commands.add_parser("add", help="register a principal with a stdin token")
    adding.add_argument("file", type=Path)
    adding.add_argument("--principal", required=True)
    adding.add_argument("--role", required=True, choices=sorted(CLI_ROLES),
                        help="human roles only; service rows belong to the Cell flow")
    adding.add_argument("--token-stdin", action="store_true", required=True,
                        help="read the raw bearer token from stdin (never argv)")
    adding.add_argument("--dry-run", action="store_true")
    removing = commands.add_parser("remove", help="remove a principal's digest")
    removing.add_argument("file", type=Path)
    removing.add_argument("--principal", required=True)
    removing.add_argument("--dry-run", action="store_true")
    checking = commands.add_parser("validate", help="restart gate: content plus ownership bits")
    checking.add_argument("file", type=Path)
    checking.add_argument("--gid", type=int, default=FLEET_GID,
                          help="owning group Fleet reads as (default %(default)s)")
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            print(json.dumps(list_users(args.file)))
            return 0
        if args.command == "validate":
            print(json.dumps(validate_file(args.file, expected_gid=args.gid)))
            return 0
        if args.command == "add":
            result = add_user(args.file, args.principal, args.role, _read_token(sys.stdin),
                              dry_run=args.dry_run)
        else:
            result = remove_user(args.file, args.principal, dry_run=args.dry_run)
    except (SiteUsersError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result))
    if not args.dry_run:
        if _apply_fleet_ownership(args.file):
            print(f"ownership applied: root:{FLEET_GID} mode 0440")
        else:
            print(f"run as root to apply, or: chown 0:{FLEET_GID} {args.file} && chmod 440 {args.file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
