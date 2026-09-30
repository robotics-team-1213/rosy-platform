"""Short-lived, untrusted LAN service observations for Fleet's read-only UI."""

from __future__ import annotations

import ipaddress
import time
from urllib.parse import urlsplit

from core_common.protocol.discovery_txt import ROBOT, Rejected, classify

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
            rows.append({"name": name, "hostname": hostname.lower(),
                         "address": str(ip), "port": port,
                         "stage": stage, "release": release})
        # One service may appear on several interfaces; identical addresses collapse.
        self._rows = list({(row["name"], row["address"], row["port"]): row
                           for row in rows}.values())
        self._seen_at = self._clock()

    def snapshot(self, registered: dict[str, str], paired: dict[str, dict]) -> dict:
        if self._seen_at is None or self._clock() - self._seen_at > self._ttl_s:
            return {"devices": [], "scanner_online": False}
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
            if counts[row["name"]] > 1 or len(matching) > 1:
                status = "conflict"
            elif robot_id is not None:
                agent = paired.get(robot_id) or {}
                if agent.get("online") and agent.get("device_uid"):
                    status = ("verified_online" if agent.get("device_name") == row["name"]
                              and row["stage"] == "CORE_READY" else "conflict")
                else:
                    status = "pairing_pending"
            devices.append({**row, "robot_id": robot_id, "status": status})
        return {"devices": sorted(devices, key=lambda item: (item["name"], item["address"])),
                "scanner_online": True}
