"""Read-only Raspberry Pi OS telemetry with graceful degradation."""

from __future__ import annotations

from datetime import datetime, timezone
import os
import platform
import shutil
import socket
import threading
import time
from pathlib import Path
from typing import Callable, Optional


AddressResolver = Callable[[Optional[str]], list[str]]
RosGraphProvider = Callable[[], dict]


class HostRuntimeProbe:
    """Collect a bounded, secret-free snapshot from a Linux host filesystem."""

    def __init__(
        self,
        host_root: str | Path = "/",
        data_path: str | Path = "/var/lib/rosy",
        address_resolver: Optional[AddressResolver] = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.host_root = Path(host_root)
        self.data_path = Path(data_path)
        self._address_resolver = address_resolver or self._resolve_addresses
        self._monotonic = monotonic
        self._last_cpu: Optional[tuple[int, int]] = None
        self._last_network: Optional[tuple[float, int, int]] = None
        self._network_lock = threading.Lock()
        self._ros_graph_provider: Optional[RosGraphProvider] = None

    def attach_ros_graph_provider(self, provider: RosGraphProvider) -> None:
        """Attach a read-only ROS graph source after the rclpy node exists."""
        if not callable(provider):
            raise TypeError("ROS graph provider must be callable")
        self._ros_graph_provider = provider

    def _read_text(self, relative: str) -> str:
        return (self.host_root / relative).read_text(encoding="utf-8").strip()

    def _os_release(self) -> dict[str, Optional[str]]:
        values: dict[str, str] = {}
        for line in self._read_text("etc/os-release").splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            key, value = line.split("=", 1)
            values[key] = value.strip().strip('"')
        return {
            "name": values.get("NAME"),
            "version": values.get("VERSION_ID"),
            "pretty_name": values.get("PRETTY_NAME"),
        }

    def _cpu_ticks(self) -> tuple[int, int]:
        fields = self._read_text("proc/stat").splitlines()[0].split()
        if not fields or fields[0] != "cpu":
            raise ValueError("aggregate cpu row unavailable")
        ticks = [int(value) for value in fields[1:]]
        total = sum(ticks)
        idle = ticks[3] + (ticks[4] if len(ticks) > 4 else 0)
        return total, idle

    def _cpu_usage(self) -> Optional[float]:
        current = self._cpu_ticks()
        previous = self._last_cpu
        self._last_cpu = current
        if previous is None:
            return None
        total_delta = current[0] - previous[0]
        idle_delta = current[1] - previous[1]
        if total_delta <= 0:
            return None
        return round(max(0.0, min(100.0, (1.0 - idle_delta / total_delta) * 100.0)), 2)

    def _load(self) -> tuple[float, float, float]:
        fields = self._read_text("proc/loadavg").split()
        return float(fields[0]), float(fields[1]), float(fields[2])

    def _memory(self) -> dict[str, Optional[float | int]]:
        values: dict[str, int] = {}
        for line in self._read_text("proc/meminfo").splitlines():
            fields = line.replace(":", "").split()
            if len(fields) >= 2:
                values[fields[0]] = int(fields[1]) * 1024
        total = values.get("MemTotal")
        available = values.get("MemAvailable", values.get("MemFree"))
        if not total or available is None:
            raise ValueError("memory totals unavailable")
        return {
            "total_bytes": total,
            "available_bytes": available,
            "used_percent": round((1.0 - available / total) * 100.0, 2),
        }

    def _temperature(self) -> float:
        thermal_roots = (
            self.host_root / "sys/class/thermal",
            self.host_root / "sys/devices/virtual/thermal",
        )
        for thermal_root in thermal_roots:
            for path in sorted(thermal_root.glob("thermal_zone*/temp")):
                value = float(path.read_text(encoding="utf-8").strip())
                return round(value / 1000.0 if abs(value) >= 1000.0 else value, 2)
        raise FileNotFoundError("thermal zone unavailable")

    def temperature(self) -> Optional[float]:
        """The SoC temperature alone, or None (D-260 summary line).

        snapshot() also advances the CPU and network deltas; a second reader
        calling it would halve the runtime card's sampling window.
        """
        try:
            return self._temperature()
        except (OSError, ValueError):
            return None

    def _storage(self) -> dict[str, Optional[float | int | str]]:
        usage = shutil.disk_usage(self.data_path)
        return {
            "path": str(self.data_path),
            "total_bytes": usage.total,
            "free_bytes": usage.free,
            "used_percent": round(usage.used / usage.total * 100.0, 2) if usage.total else None,
        }

    def _network_throughput(self) -> dict[str, Optional[float] | list[str]]:
        with self._network_lock:
            return self._network_throughput_locked()

    def _network_throughput_locked(self) -> dict[str, Optional[float] | list[str]]:
        counters: dict[str, tuple[int, int]] = {}
        for line in self._read_text("proc/net/dev").splitlines()[2:]:
            if ":" not in line:
                continue
            interface, payload = line.split(":", 1)
            name = interface.strip()
            fields = payload.split()
            if name == "lo" or len(fields) < 9:
                continue
            counters[name] = (int(fields[0]), int(fields[8]))
        if not counters:
            raise ValueError("network counters unavailable")

        now = self._monotonic()
        received = sum(values[0] for values in counters.values())
        transmitted = sum(values[1] for values in counters.values())
        previous = self._last_network
        self._last_network = (now, received, transmitted)

        rx_rate: Optional[float] = None
        tx_rate: Optional[float] = None
        if previous is not None:
            elapsed = now - previous[0]
            rx_delta = received - previous[1]
            tx_delta = transmitted - previous[2]
            if elapsed > 0 and rx_delta >= 0 and tx_delta >= 0:
                rx_rate = round(rx_delta / elapsed, 2)
                tx_rate = round(tx_delta / elapsed, 2)
        return {
            "rx_bytes_per_second": rx_rate,
            "tx_bytes_per_second": tx_rate,
            "interfaces": sorted(counters),
        }

    @staticmethod
    def _resolve_addresses(_hostname: Optional[str]) -> list[str]:
        addresses: set[str] = set()
        routes = (
            (socket.AF_INET, ("192.0.2.1", 9)),
            (socket.AF_INET6, ("2001:db8::1", 9, 0, 0)),
        )
        for family, target in routes:
            try:
                with socket.socket(family, socket.SOCK_DGRAM) as connection:
                    connection.connect(target)
                    address = connection.getsockname()[0]
                    if address not in {"127.0.0.1", "::1"}:
                        addresses.add(address)
            except OSError:
                continue
        return sorted(addresses)

    def snapshot(self) -> dict:
        """Return all available values and name every unavailable source."""
        unavailable: list[str] = []

        try:
            os_release = self._os_release()
        except (OSError, ValueError):
            os_release = {"name": None, "version": None, "pretty_name": None}
            unavailable.append("os_release")

        try:
            hostname: Optional[str] = self._read_text("etc/hostname") or None
        except OSError:
            hostname = None
            unavailable.append("hostname")

        try:
            uptime: Optional[float] = float(self._read_text("proc/uptime").split()[0])
        except (OSError, ValueError, IndexError):
            uptime = None
            unavailable.append("uptime")

        try:
            load_1, load_5, load_15 = self._load()
        except (OSError, ValueError, IndexError):
            load_1 = load_5 = load_15 = None
            unavailable.append("load")

        try:
            cpu_usage = self._cpu_usage()
        except (OSError, ValueError, IndexError):
            cpu_usage = None
            unavailable.append("cpu")

        try:
            memory = self._memory()
        except (OSError, ValueError):
            memory = {"total_bytes": None, "available_bytes": None, "used_percent": None}
            unavailable.append("memory")

        try:
            temperature: Optional[float] = self._temperature()
        except (OSError, ValueError):
            temperature = None
            unavailable.append("temperature")

        try:
            storage = self._storage()
        except OSError:
            storage = {
                "path": str(self.data_path),
                "total_bytes": None,
                "free_bytes": None,
                "used_percent": None,
            }
            unavailable.append("storage")

        try:
            network_throughput = self._network_throughput()
        except (OSError, ValueError, IndexError):
            network_throughput = {
                "rx_bytes_per_second": None,
                "tx_bytes_per_second": None,
                "interfaces": [],
            }
            unavailable.append("network_counters")

        ros_graph = None
        if self._ros_graph_provider is not None:
            try:
                ros_graph = self._ros_graph_provider()
            except Exception:
                ros_graph = {
                    "status": "UNAVAILABLE",
                    "risks": [{
                        "code": "GRAPH_UNAVAILABLE",
                        "message": "ROS graph provider failed",
                    }],
                }
                unavailable.append("ros_graph")

        return {
            "source": "host",
            "os": os_release,
            "hostname": hostname,
            "kernel": platform.release(),
            "architecture": platform.machine(),
            "uptime_seconds": uptime,
            "cpu": {
                "usage_percent": cpu_usage,
                "load_1": load_1,
                "load_5": load_5,
                "load_15": load_15,
                "logical_count": os.cpu_count(),
            },
            "memory": memory,
            "storage": storage,
            "temperature_c": temperature,
            "network": {
                "addresses": self._address_resolver(hostname),
                "throughput": network_throughput,
            },
            "ros": ros_graph,
            "unavailable": unavailable,
            "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
