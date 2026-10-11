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


# Network-level ssh failures, one exit code each. They sit above deliver.py's own
# codes (3, 75, 76), intake's 4 and watch.py's 5 and 6, and below ssh's 255.
DNS_EXIT, UNREACHABLE_EXIT, HOSTKEY_EXIT = 77, 78, 79
KIND_EXIT = {"dns": DNS_EXIT, "unreachable": UNREACHABLE_EXIT, "hostkey": HOSTKEY_EXIT}
EXIT_KIND = {code: kind for kind, code in KIND_EXIT.items()}
TIMEOUT_RC = 124  # what deliver._run reports for a subprocess timeout
_KIND_PATTERNS = (  # hostkey first: its text can also mention the host name
    ("hostkey", ("host key verification failed", "remote host identification has changed",
                 "host key for", "no ed25519 host key is known", "no ecdsa host key is known",
                 "no rsa host key is known")),
    ("dns", ("could not resolve hostname", "name or service not known",
             "temporary failure in name resolution", "nodename nor servname")),
    ("unreachable", ("connection refused", "connection timed out", "operation timed out",
                     "no route to host", "network is unreachable", "connection reset",
                     "connection closed by")),
)


def classify(returncode: int, stderr: str | None, *, timeout_is_network: bool = True) -> str | None:
    """dns | unreachable | hostkey for a failed ssh/scp, else None (a remote command failure).

    Only ssh's own exit 255 and a subprocess timeout can be a network failure; a remote
    command's exit code never is."""
    if returncode == TIMEOUT_RC:  # a long transfer step that ran out is not a dead link
        return "unreachable" if timeout_is_network else None
    if returncode != 255:
        return None
    text = (stderr or "").lower()
    for kind, needles in _KIND_PATTERNS:
        if any(n in text for n in needles):
            return kind
    return None


def add_arguments(parser) -> None:
    parser.add_argument("--identity", help=f"operator private key (env {KEY_ENV})")
    parser.add_argument("--known-hosts", help=f"pinned known_hosts file (env {KH_ENV})")
    parser.add_argument("--host-key-alias", help="look up and pin the host key under this "
                        "name (the robot id) instead of the address, so a renumbered "
                        "network keeps the pin")


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


def options(identity: str, known_hosts: str, alias: str | None = None) -> list[str]:
    """Arguments shared by ssh and scp, placed before '--'.

    alias: the key is looked up (and, with StrictHostKeyChecking=yes, only ever checked)
    under this name, so the pin follows the robot and not its address."""
    keyed = ["-o", f"HostKeyAlias={alias}"] if alias else []
    return [*keyed, "-i", identity, "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
            "-o", f"UserKnownHostsFile={known_hosts}", "-o", "StrictHostKeyChecking=yes",
            # a dead link fails in bounded time instead of hanging the caller
            "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3"]
