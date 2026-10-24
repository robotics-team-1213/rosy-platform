"""Shared NTP configuration and honest readiness; no host clock is changed."""

import importlib.util
import math
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "deploy/hosts/common/rosy_time_sync.py"


@pytest.fixture
def sync():
    spec = importlib.util.spec_from_file_location("rosy_time_sync", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tracking(*, correction="0.001", delay="0.010", dispersion="0.002", stamp="1000", leap="Normal", stratum="3"):
    return f"C0000201,{stratum},{stamp},{correction},0,0,0,0,0,{delay},{dispersion},16,{leap}"


def test_client_has_only_approved_site_sources(sync):
    config = sync.configuration("client", ["site.example.invalid"], [])
    assert "server site.example.invalid iburst minpoll 4 maxpoll 6" in config
    assert "pool " not in config and "sourcedir" not in config and "include" not in config
    assert "local " not in config and "allow " not in config
    assert "port 0" in config
    assert "makestep 0.1 3" in config


def test_site_serves_only_explicit_networks(sync):
    config = sync.configuration("site", ["a.example.invalid", "b.example.invalid", "c.example.invalid"], ["192.0.2.0/24"])
    assert "allow 192.0.2.0/24\n" in config
    assert "port 0" not in config and "local " not in config


@pytest.mark.parametrize("role,sources,networks", [
    ("client", [], []), ("client", ["-x"], []),
    ("client", ["site\nlocal stratum 1"], []),
    ("client", ["site iburst"], []), ("client", ["site;reboot"], []),
    ("client", ["site"], ["192.0.2.0/24"]),
    ("site", ["a", "b", "c"], []),
    ("site", ["a", "b", "c"], ["0.0.0.0/0"]),
    ("site", ["a", "b", "c"], ["::/0"]),
    ("site", ["a"], ["192.0.2.0/24"]),
    ("site", ["a", "a", "a"], ["192.0.2.0/24"]),
])
def test_unsafe_or_incomplete_config_is_refused(sync, role, sources, networks):
    with pytest.raises(ValueError):
        sync.configuration(role, sources, networks)


def test_readiness_bounds_clock_error_and_freshness(sync):
    report = sync.assess(tracking(), now=1010)
    assert report["synchronized"] is True
    assert report["error_bound_s"] == pytest.approx(0.008)
    assert sync.assess(tracking(correction="-0.1"), now=1010)["synchronized"] is False
    assert sync.assess(tracking(dispersion="0.06"), now=1010)["synchronized"] is False


@pytest.mark.parametrize("csv", [
    "", "200 OK", tracking(leap="Not synchronised"), tracking(stratum="0"),
    tracking(stamp="100"), tracking(stamp="2000"),
    tracking(correction="nan"), tracking(delay="inf"), tracking(dispersion="-1"),
    tracking(correction="bad"),
])
def test_missing_unsynced_stale_or_invalid_tracking_fails_closed(sync, csv):
    assert sync.assess(csv, now=1010)["synchronized"] is False


def test_install_requires_maintenance_before_any_mutation():
    result = subprocess.run([sys.executable, str(TOOL), "install", "--role", "client", "--source", "site.example.invalid"], capture_output=True, text=True)
    assert result.returncode != 0
    assert "maintenance" in result.stderr.lower()


def test_native_payload_carries_standalone_tool():
    installer = (ROOT / "deploy/robot/pinky_pro/native/install-native-runtime.sh").read_text()
    assert "hosts/common/rosy_time_sync.py" in installer


def test_windows_uses_ntp_client_mode_and_preserves_domain_policy():
    source = (ROOT / "deploy/hosts/common/install-time-sync.ps1").read_text()
    assert ",0x8" in source
    assert "PartOfDomain" in source and "ShouldProcess" in source
    assert "/query" in source and "/resync" in source
