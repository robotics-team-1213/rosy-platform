"""Why a pinned robot address may be unreachable, judged against the latest scan.

Fleet -> CORE is plain HTTP, so the address stays pinned (D-361 3, D-370 5.3). This module
only explains: it never resolves a `.local` name and never follows a new address. A scan
row carries no robot_id or device_uid, so the identity here is the row's discovery (TXT)
name, the same key the enrollment register matches on; an avahi host name is not used.
"새 주소로 옮기기" re-pairs with the robot's screen code and compares robot_id, hostname,
serial and device_uid before anything moves.

Assumption: scan rows carry no netmask, so a "scanned subnet" is the /24 around each
scanned address plus any `site_networks` the caller knows (the site host's interfaces,
not wired today). A site on a wider prefix (say a /22) can read as "outside" for a pin
that is in fact reachable, so every result is a hint for the operator, never an action.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

SCAN_PREFIX = 24


def _pinned(base_url: str) -> tuple[str, int | None]:
    parts = urlsplit(base_url)
    try:
        port = parts.port
    except ValueError:
        port = None
    if port is None:
        port = {"http": 80, "https": 443}.get(parts.scheme.lower())
    return (parts.hostname or "").lower(), port


def _ip(host: str):
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _row_names(row: dict) -> set[str]:
    name = str(row.get("name") or "").lower()
    return {name} if name else set()


def classify_addresses(pinned: dict[str, str], rows: list[dict] | None, *,
                       names: dict[str, str], movable=frozenset(),
                       site_networks=()) -> dict:
    """`pinned`: robot_id -> base_url. `rows`: current scan rows, None when the scanner is off.

    `names`: robot_id -> lowercase discovery name for robots with a known identity.
    `movable`: robot_ids the enrollment register holds at `address_changed`.
    Each robot gets one status: `in_scanned_subnet`, `outside_scanned_subnets`,
    `seen_at_other_address` or `unknown`. `all_outside` (the site-renumber hint) needs at
    least one IP pin and every IP pin outside the scanned subnets; name pins do not count
    here, and the console suppresses the hint when a name-pinned robot is online.
    """
    networks = [ipaddress.ip_network(net, strict=False) for net in site_networks]
    for row in rows or ():
        ip = _ip(str(row.get("address") or ""))
        if ip is not None and ip.version == 4:
            networks.append(ipaddress.ip_network(f"{ip}/{SCAN_PREFIX}", strict=False))
    robots = []
    for robot_id in sorted(pinned):
        host, port = _pinned(pinned[robot_id])
        ip = _ip(host)
        name = (names.get(robot_id) or "").lower()
        seen = sorted({f"{row['address']}:{row['port']}" for row in rows or ()
                       if name and name in _row_names(row) and row["address"] != host})
        at_pinned = bool(name) and any(name in _row_names(row) and row["address"] == host
                                       for row in rows or ())
        in_subnet = None if not rows or ip is None else any(ip in net for net in networks)
        if not rows:
            status = "unknown"
        elif seen:
            status = "seen_at_other_address"
        elif ip is None:
            status = "unknown"
        else:
            status = "in_scanned_subnet" if in_subnet else "outside_scanned_subnets"
        robots.append({
            "robot_id": robot_id,
            "pinned": f"{host}:{port}" if port is not None else host,
            "pinned_is_name": ip is None,
            "status": status,
            "in_subnet": in_subnet,
            "seen_addresses": seen,
            "movable": (robot_id in movable and status == "seen_at_other_address"
                        and len(seen) == 1 and not at_pinned),
        })
    ip_pins = [entry for entry in robots if not entry["pinned_is_name"]]
    return {"robots": robots,
            "all_outside": bool(ip_pins) and all(entry["in_subnet"] is False for entry in ip_pins)}
