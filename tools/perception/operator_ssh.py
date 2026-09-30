"""Operator SSH options for deliver.py and harvest.py (D-373 decision 6).

Key-only, pinned host keys, never a prompt: the rosy-device-access rules. On the
Windows operator PC the key and known_hosts default to %LOCALAPPDATA%\\Rosy; on a
Linux site PC they come from --identity/--known-hosts or ROSY_OPERATOR_KEY /
ROSY_KNOWN_HOSTS (no guessed default)."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

USER = "rosy"
KEY_ENV, KH_ENV = "ROSY_OPERATOR_KEY", "ROSY_KNOWN_HOSTS"
_SAFE_NAME = re.compile(r"[A-Za-z0-9._][A-Za-z0-9._-]*")


def safe_name(value) -> bool:
    """A host or user that ssh cannot read as an option or a shell word."""
    return isinstance(value, str) and _SAFE_NAME.fullmatch(value) is not None


class SshConfigError(ValueError):
    pass


def add_arguments(parser) -> None:
    parser.add_argument("--identity", help=f"operator private key (env {KEY_ENV})")
    parser.add_argument("--known-hosts", help=f"pinned known_hosts file (env {KH_ENV})")


def resolve(identity, known_hosts, *, env=None, platform=None) -> tuple[str, str]:
    """(identity, known_hosts): flag, then env, then the Windows default; else refuse."""
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    base = None
    if platform == "win32" and env.get("LOCALAPPDATA"):
        base = Path(env["LOCALAPPDATA"]) / "Rosy"
    identity = identity or env.get(KEY_ENV) or (
        str(base / "ssh" / "rosy-operator-ed25519") if base else None)
    known_hosts = known_hosts or env.get(KH_ENV) or (
        str(base / "known_hosts") if base else None)
    if not identity:
        raise SshConfigError(f"no operator key: pass --identity or set {KEY_ENV}")
    if not known_hosts:
        raise SshConfigError(f"no known_hosts: pass --known-hosts or set {KH_ENV}")
    if any(c.isspace() for c in known_hosts):
        raise SshConfigError(f"known_hosts path must not contain a space: {known_hosts!r}")
    return identity, known_hosts


def options(identity: str, known_hosts: str) -> list[str]:
    """Arguments shared by ssh and scp, placed before '--'."""
    return ["-i", identity, "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
            "-o", f"UserKnownHostsFile={known_hosts}", "-o", "StrictHostKeyChecking=yes",
            # a dead link fails in bounded time instead of hanging the caller
            "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3"]
