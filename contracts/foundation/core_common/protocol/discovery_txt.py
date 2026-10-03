"""Canonical DNS-SD TXT classifier for ROSY site discovery (D-370 5.1).

The machine source is ``test/fixtures/protocol/discovery-txt.v1.json``; every
parser (this module, the ``deploy/site`` script copies, the Fleet server row
check, Android ``OverheadServiceRecord``) is tested against it. A discovery
result is an address *candidate* only. It never proves identity and never
grants authority; pairing, tokens and TLS still decide that.

Standard library only: FleetAgent, the Fleet server and the planned CORE
neighbour list all import it.
"""

from __future__ import annotations

import ipaddress
import re
import shlex
from dataclasses import dataclass, field

REASONS = (
    "wrong_type", "missing_key", "duplicate_key", "value_mismatch", "bad_host",
    "bad_address", "bad_port", "tls_host_mismatch", "ap_mode",
)

ROBOT = "_rosy._tcp"
FLEET = "_rosy-fleet._tcp"
OVERHEAD = "_rosy-overhead._tcp"

COMMON_KEYS = ("product", "role", "proto", "tls")
REQUIRED: dict[str, dict[str, str]] = {
    ROBOT: {"product": "rosy", "role": "robot", "proto": "core-v1", "tls": "none"},
    FLEET: {"product": "rosy", "role": "fleet", "proto": "site-v1", "tls": "required"},
    OVERHEAD: {"product": "rosy", "role": "overhead-camera", "proto": "rosy-overhead/1",
               "tls": "required"},
}
# Old robot images advertise stage/release/name/network only (profile, line 26).
LEGACY_ALLOWED = frozenset({ROBOT})

HOSTNAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.local$")


@dataclass(frozen=True)
class Accepted:
    service_type: str
    host: str | None
    txt: dict[str, str] = field(default_factory=dict)
    legacy: bool = False


@dataclass(frozen=True)
class Rejected:
    reason: str


def normalize_service_type(service_type: str) -> str:
    value = service_type.strip().lower().strip(".")
    return value.removesuffix(".local").strip(".")


def normalize_host(host: str) -> str:
    return host.strip().lower().rstrip(".")


def parse_txt_pairs(text: str) -> list[tuple[str, str]]:
    """Avahi's parsable ``"k=v" "k=v"`` column as ordered pairs; duplicates stay."""
    try:
        items = shlex.split(text)
    except ValueError:
        return []
    return [tuple(item.split("=", 1)) for item in items if "=" in item]


def _lan_ipv4(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except (ValueError, TypeError):
        return False
    return (ip.version == 4 and ip.is_private and not ip.is_loopback
            and not ip.is_link_local and not ip.is_multicast and not ip.is_unspecified)


def classify(service_type: str, host: str | None, address: str | None, port: object,
             txt: list[tuple[str, str]]) -> Accepted | Rejected:
    """Classify one resolved record. ``host``/``address`` may be None when unknown."""
    kind = normalize_service_type(service_type)
    if kind not in REQUIRED:
        return Rejected("wrong_type")
    name = None
    if host is not None:
        name = normalize_host(host)
        if not HOSTNAME.fullmatch(name):
            return Rejected("bad_host")
    if address is not None and not _lan_ipv4(address):
        return Rejected("bad_address")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        return Rejected("bad_port")
    keys = [key for key, _ in txt]
    if len(keys) != len(set(keys)):
        return Rejected("duplicate_key")
    values = dict(txt)
    legacy = kind in LEGACY_ALLOWED and not any(key in values for key in COMMON_KEYS)
    if not legacy:
        for key, expected in REQUIRED[kind].items():
            if key not in values:
                return Rejected("missing_key")
            if values[key] != expected:
                return Rejected("value_mismatch")
    if kind == OVERHEAD:
        if "tls_host" not in values:
            return Rejected("missing_key")
        tls_host = normalize_host(values["tls_host"])
        if not HOSTNAME.fullmatch(tls_host):
            return Rejected("bad_host")
        if name is not None and tls_host != name:
            return Rejected("tls_host_mismatch")
    if kind == ROBOT and values.get("network") == "ap":
        return Rejected("ap_mode")
    return Accepted(service_type=kind, host=name, txt=values, legacy=legacy)
