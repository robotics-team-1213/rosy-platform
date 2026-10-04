from __future__ import annotations

from pathlib import Path
import socket
import threading

import pytest

from core.system.runtime import HostRuntimeProbe


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _host_tree(root: Path) -> None:
    _write(
        root,
        "etc/os-release",
        'PRETTY_NAME="Raspberry Pi OS 13 (trixie)"\nNAME="Raspberry Pi OS"\nVERSION_ID="13"\n',
    )
    _write(root, "etc/hostname", "rosy-pi\n")
    _write(root, "proc/uptime", "93784.25 123.0\n")
    _write(root, "proc/loadavg", "0.18 0.11 0.07 1/234 567\n")
    _write(root, "proc/stat", "cpu  100 0 100 800 0 0 0 0 0 0\n")
    _write(
        root,
        "proc/net/dev",
        "Inter-| Receive | Transmit\n"
        " face |bytes packets errs drop fifo frame compressed multicast|"
        "bytes packets errs drop fifo colls carrier compressed\n"
        "    lo: 900 0 0 0 0 0 0 0 900 0 0 0 0 0 0 0\n"
        " wlan0: 1000 0 0 0 0 0 0 0 2000 0 0 0 0 0 0 0\n",
    )
    _write(
        root,
        "proc/meminfo",
        "MemTotal:        8192000 kB\nMemAvailable:   6144000 kB\n",
    )
    _write(root, "sys/class/thermal/thermal_zone0/temp", "52250\n")


def test_snapshot_reads_raspberry_pi_host_metrics(tmp_path):
    _host_tree(tmp_path)
    data_path = tmp_path / "data"
    data_path.mkdir()
    ticks = iter((10.0, 12.0))
    probe = HostRuntimeProbe(
        host_root=tmp_path,
        data_path=data_path,
        address_resolver=lambda _hostname: ["192.168.0.42"],
        monotonic=lambda: next(ticks),
    )

    first = probe.snapshot()
    _write(tmp_path, "proc/stat", "cpu  150 0 150 900 0 0 0 0 0 0\n")
    _write(
        tmp_path,
        "proc/net/dev",
        "Inter-| Receive | Transmit\n"
        " face |bytes packets errs drop fifo frame compressed multicast|"
        "bytes packets errs drop fifo colls carrier compressed\n"
        "    lo: 5000 0 0 0 0 0 0 0 5000 0 0 0 0 0 0 0\n"
        " wlan0: 3000 0 0 0 0 0 0 0 6000 0 0 0 0 0 0 0\n",
    )
    second = probe.snapshot()

    assert first["source"] == "host"
    assert first["os"] == {
        "name": "Raspberry Pi OS",
        "version": "13",
        "pretty_name": "Raspberry Pi OS 13 (trixie)",
    }
    assert first["hostname"] == "rosy-pi"
    assert first["uptime_seconds"] == pytest.approx(93784.25)
    assert first["cpu"]["usage_percent"] is None
    assert second["cpu"]["usage_percent"] == pytest.approx(50.0)
    assert second["cpu"]["load_1"] == pytest.approx(0.18)
    assert second["memory"]["total_bytes"] == 8192000 * 1024
    assert second["memory"]["available_bytes"] == 6144000 * 1024
    assert second["memory"]["used_percent"] == pytest.approx(25.0)
    assert second["temperature_c"] == pytest.approx(52.25)
    assert second["network"]["addresses"] == ["192.168.0.42"]
    assert first["network"]["throughput"]["rx_bytes_per_second"] is None
    assert second["network"]["throughput"] == {
        "rx_bytes_per_second": 1000.0,
        "tx_bytes_per_second": 2000.0,
        "interfaces": ["wlan0"],
    }
    assert second["storage"]["path"] == str(data_path)
    assert "collected_at" in second


def test_snapshot_degrades_to_null_when_host_files_are_missing(tmp_path):
    data_path = tmp_path / "data"
    data_path.mkdir()
    probe = HostRuntimeProbe(
        host_root=tmp_path,
        data_path=data_path,
        address_resolver=lambda _hostname: [],
    )

    snapshot = probe.snapshot()

    assert snapshot["os"]["pretty_name"] is None
    assert snapshot["uptime_seconds"] is None
    assert snapshot["cpu"]["usage_percent"] is None
    assert snapshot["memory"]["used_percent"] is None
    assert snapshot["temperature_c"] is None
    assert snapshot["network"]["addresses"] == []
    assert snapshot["network"]["throughput"]["rx_bytes_per_second"] is None
    assert set(snapshot["unavailable"]) >= {
        "os_release",
        "hostname",
        "uptime",
        "load",
        "cpu",
        "memory",
        "temperature",
        "network_counters",
    }


def test_snapshot_includes_attached_ros_graph_without_exposing_mutation(tmp_path):
    _host_tree(tmp_path)
    data_path = tmp_path / "data"
    data_path.mkdir()
    probe = HostRuntimeProbe(host_root=tmp_path, data_path=data_path)
    graph = {"status": "OK", "domain_id": 42, "node_count": 3}

    probe.attach_ros_graph_provider(lambda: graph)

    assert probe.snapshot()["ros"] == graph


def test_ros_graph_provider_failure_degrades_explicitly(tmp_path):
    _host_tree(tmp_path)
    data_path = tmp_path / "data"
    data_path.mkdir()
    probe = HostRuntimeProbe(host_root=tmp_path, data_path=data_path)

    def fail():
        raise RuntimeError("graph failed")

    probe.attach_ros_graph_provider(fail)
    snapshot = probe.snapshot()

    assert snapshot["ros"]["status"] == "UNAVAILABLE"
    assert "ros_graph" in snapshot["unavailable"]


def test_network_sampling_serializes_concurrent_counter_reads(tmp_path):
    data_path = tmp_path / "data"
    data_path.mkdir()
    release_first = threading.Event()
    second_done = threading.Event()

    def counters(received):
        return (
            "Inter-| Receive | Transmit\n"
            " face |bytes packets errs drop fifo frame compressed multicast|"
            "bytes packets errs drop fifo colls carrier compressed\n"
            f" wlan0: {received} 0 0 0 0 0 0 0 {received} 0 0 0 0 0 0 0\n"
        )

    current = {"main": 1000}

    def read_text(relative):
        assert relative == "proc/net/dev"
        name = threading.current_thread().name
        if name == "first-reader":
            assert release_first.wait(timeout=2.0)
            return counters(1500)
        if name == "second-reader":
            return counters(3000)
        return counters(current["main"])

    clock = {"MainThread": 0.0, "first-reader": 1.0, "second-reader": 2.0}
    probe = HostRuntimeProbe(
        host_root=tmp_path,
        data_path=data_path,
        monotonic=lambda: clock[threading.current_thread().name],
    )
    probe._read_text = read_text
    assert probe._network_throughput()["rx_bytes_per_second"] is None

    results = {}

    def sample(key):
        results[key] = probe._network_throughput()
        if key == "second":
            second_done.set()

    first = threading.Thread(target=sample, args=("first",), name="first-reader")
    second = threading.Thread(target=sample, args=("second",), name="second-reader")
    first.start()
    second.start()
    second_finished_while_first_blocked = second_done.wait(timeout=0.2)
    release_first.set()
    first.join(timeout=2.0)
    second.join(timeout=2.0)

    current["main"] = 4000
    clock["MainThread"] = 3.0
    following = probe._network_throughput()

    assert second_finished_while_first_blocked is False
    assert following["rx_bytes_per_second"] == pytest.approx(1000.0)


def test_temperature_reads_the_mounted_sysfs_symlink_target_tree(tmp_path):
    _write(tmp_path, "sys/devices/virtual/thermal/thermal_zone0/temp", "48750\n")
    data_path = tmp_path / "data"
    data_path.mkdir()

    probe = HostRuntimeProbe(
        host_root=tmp_path,
        data_path=data_path,
        address_resolver=lambda _hostname: [],
    )

    assert probe._temperature() == pytest.approx(48.75)


def test_snapshot_does_not_expose_process_environment(tmp_path, monkeypatch):
    _host_tree(tmp_path)
    data_path = tmp_path / "data"
    data_path.mkdir()
    monkeypatch.setenv("ROSY_ADMIN_TOKEN", "must-not-leak")
    probe = HostRuntimeProbe(host_root=tmp_path, data_path=data_path)

    snapshot_text = repr(probe.snapshot())

    assert "ROSY_ADMIN_TOKEN" not in snapshot_text
    assert "must-not-leak" not in snapshot_text


def test_default_address_lookup_uses_routes_without_hostname_dns(monkeypatch):
    class FakeSocket:
        def __init__(self, family, _kind):
            self.family = family

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def connect(self, _target):
            return None

        def getsockname(self):
            if self.family == socket.AF_INET:
                return ("192.168.0.42", 54321)
            return ("2001:db8::42", 54321, 0, 0)

    def fail_dns(*_args, **_kwargs):
        raise AssertionError("hostname DNS must not block runtime telemetry")

    monkeypatch.setattr(socket, "socket", FakeSocket)
    monkeypatch.setattr(socket, "getaddrinfo", fail_dns)

    assert HostRuntimeProbe._resolve_addresses("unresolvable-host") == [
        "192.168.0.42",
        "2001:db8::42",
    ]
