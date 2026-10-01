"""Short-lived, untrusted LAN service observations for Fleet's read-only UI."""

from __future__ import annotations

import ipaddress
import time
from urllib.parse import urlsplit

from core_common.protocol.discovery_txt import ROBOT, Rejected, classify

#: Robots live on RFC 1918 LANs only (the same rule as enrollment.parse_manual_address).
#: `ipaddress.is_private` also admits documentation, benchmark and shared ranges.
RFC1918 = tuple(ipaddress.ip_network(net) for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def is_rfc1918(address: object) -> bool:
    try:
        ip = ipaddress.ip_address(str(address))
    except ValueError:
        return False
    return ip.version == 4 and any(ip in net for net in RFC1918)


_ROW_ERRORS = {
    "bad_host": "invalid discovery hostname",
    "bad_address": "discovery address must be a private LAN IPv4 address",
    "bad_port": "invalid discovery port",
}


class DiscoveryStore:
    def __init__(self, *, clock=time.monotonic, ttl_s: float = 45.0) -> None:
        if ttl_s <= 0:
            raise ValueError("discovery TTL must be positive")
        self._clock = clock
        self._ttl_s = ttl_s
        self._seen_at: float | None = None
        self._rows: list[dict] = []

    def replace_scan(self, devices: list[dict]) -> None:
        if not isinstance(devices, list) or len(devices) > 64:
            raise ValueError("discovery scan must contain at most 64 devices")
        rows = []
        for device in devices:
            if not isinstance(device, dict):
                raise ValueError("discovery device must be an object")
            name = device.get("name")
            hostname = device.get("hostname", "")
            address = device.get("address")
            port = device.get("port")
            if (not isinstance(name, str) or not name or len(name) > 96
                    or any(ord(char) < 32 for char in name)):
                raise ValueError("invalid discovery name")
            if not isinstance(hostname, str) or not isinstance(address, str):
                raise ValueError("invalid discovery address")
            network = device.get("network", "sta")
            if network not in ("sta", "ap"):
                raise ValueError("invalid discovery network")
            # The bridge already classified the TXT; re-check the row with the same
            # classifier (D-370 5.1). Rows carry no common keys, so they classify as legacy.
            result = classify(ROBOT, hostname or None, address, port, [("network", network)])
            if isinstance(result, Rejected):
                if result.reason == "ap_mode":
                    continue
                raise ValueError(_ROW_ERRORS[result.reason])
            ip = ipaddress.ip_address(address)
            stage = device.get("stage", "")
            release = device.get("release", "")
            if any(not isinstance(value, str) or len(value) > 96 for value in (stage, release)):
                raise ValueError("invalid discovery metadata")
            rows.append({"name": name, "hostname": result.host or "",
                         "address": str(ip), "port": port,
                         "stage": stage, "release": release})
        # One service may appear on several interfaces; identical addresses collapse.
        self._rows = list({(row["name"], row["address"], row["port"]): row
                           for row in rows}.values())
        self._seen_at = self._clock()

    def rows(self) -> list[dict]:
        """Current unexpired scan rows (copies); empty when the scanner is offline."""
        if self._seen_at is None or self._clock() - self._seen_at > self._ttl_s:
            return []
        return [dict(row) for row in self._rows]

    def snapshot(self, registered: dict[str, str], paired: dict[str, dict],
                 enrolled: dict[str, str] | None = None) -> dict:
        """`enrolled` maps a lowercase discovery name to its enrolled robot_id (D-361 8).

        `scanner_state` is `never_seen` (no scan since Fleet started), `online`, or `expired`
        (the lease ran out: discovery and move-address stop until the scanner returns).
        """
        if self._seen_at is None:
            return {"devices": [], "scanner_online": False, "scanner_state": "never_seen",
                    "scanner_age_s": None}
        elapsed = self._clock() - self._seen_at
        age_s = int(elapsed)
        if elapsed > self._ttl_s:
            return {"devices": [], "scanner_online": False, "scanner_state": "expired",
                    "scanner_age_s": age_s}
        enrolled = enrolled or {}
        counts = {}
        for row in self._rows:
            counts[row["name"]] = counts.get(row["name"], 0) + 1
        devices = []
        for row in self._rows:
            matching = []
            for robot_id, base_url in registered.items():
                endpoint = urlsplit(base_url)
                try:
                    same = (endpoint.hostname in {row["address"], row["hostname"]}
                            and endpoint.port == row["port"])
                except ValueError:
                    same = False
                if same:
                    matching.append(robot_id)
            status = "registration_pending"
            robot_id = matching[0] if len(matching) == 1 else None
            enrolled_id = enrolled.get(row["name"].lower())
            if counts[row["name"]] > 1 or len(matching) > 1:
                status = "conflict"
            elif enrolled_id is not None:
                # Matched by name; an address difference is the register's own state.
                robot_id = enrolled_id
                agent = paired.get(robot_id) or {}
                status = ("verified_online" if agent.get("online") and agent.get("device_uid")
                          and agent.get("device_name") == row["name"] else "enrolled")
            elif robot_id is not None:
                agent = paired.get(robot_id) or {}
                if agent.get("online") and agent.get("device_uid"):
                    status = ("verified_online" if agent.get("device_name") == row["name"]
                              and row["stage"] == "CORE_READY" else "conflict")
                else:
                    status = "pairing_pending"
            devices.append({**row, "robot_id": robot_id, "status": status,
                            "enrollable": status == "registration_pending"})
        return {"devices": sorted(devices, key=lambda item: (item["name"], item["address"])),
                "scanner_online": True, "scanner_state": "online", "scanner_age_s": age_s}
