"""Short-lived, untrusted LAN service observations for Fleet's read-only UI."""

from __future__ import annotations

import ipaddress
import time
from urllib.parse import urlsplit


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
            if (not isinstance(hostname, str) or len(hostname) > 253
                    or (hostname and (not hostname.endswith(".local")
                                      or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-."
                                             for char in hostname.lower())))):
                raise ValueError("invalid discovery hostname")
            try:
                ip = ipaddress.ip_address(address)
            except (ValueError, TypeError):
                raise ValueError("invalid discovery address") from None
            if (ip.version != 4 or not ip.is_private or ip.is_loopback or ip.is_link_local
                    or ip.is_multicast or ip.is_unspecified):
                raise ValueError("discovery address must be a private LAN IPv4 address")
            if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
                raise ValueError("invalid discovery port")
            network = device.get("network", "sta")
            if network == "ap":
                continue
            if network != "sta":
                raise ValueError("invalid discovery network")
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
