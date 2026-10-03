"""D-354: mDNS 서비스 발견 시험.

펌웨어가 mDNS 광고를 포함하는지, discover 유틸리티가
폴백 체인을 따르는지, 서비스명이 계약과 일치하는지.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dock_firmware_advertises_mdns():
    """도크 펌웨어가 ESPmDNS를 include하고 rosy-dock 서비스를 등록한다."""
    sketch = ROOT / "operations/site_devices/dock/firmware/rosy_dock/rosy_dock.ino"
    text = sketch.read_text(encoding="utf-8")
    assert "#include <ESPmDNS.h>" in text, "dock must include ESPmDNS"
    assert 'MDNS.addService("rosy-dock", "tcp", 80)' in text, (
        "dock must advertise _rosy-dock._tcp on port 80"
    )


def test_signal_firmware_advertises_mdns():
    """신호등 펌웨어가 ESPmDNS를 include하고 rosy-signal 서비스를 등록한다."""
    sketch = ROOT / "operations/site_devices/signal/firmware/rosy_signal/rosy_signal.ino"
    text = sketch.read_text(encoding="utf-8")
    assert "#include <ESPmDNS.h>" in text, "signal must include ESPmDNS"
    assert 'MDNS.addService("rosy-signal", "tcp", 80)' in text, (
        "signal must advertise _rosy-signal._tcp on port 80"
    )


def test_discover_utility_falls_back_gracefully():
    """발견 도구가 없어도 예외 없이 빈 목록을 반환한다."""
    import sys
    sys.path.insert(0, str(ROOT / "src" / "contracts" / "foundation"))
    from core_common.discover import discover_devices, DiscoveredDevice

    # 이 테스트 환경에서는 zeroconf도 avahi도 없을 수 있다 — 빈 목록이면 족하다
    result = discover_devices("_rosy-dock._tcp", timeout_s=0.5)
    assert isinstance(result, list), "discover must return a list, never raise"
    for device in result:
        assert isinstance(device, DiscoveredDevice)
        assert device.service_type == "_rosy-dock._tcp"


def test_discovered_device_shape():
    import sys
    sys.path.insert(0, str(ROOT / "src" / "contracts" / "foundation"))
    from core_common.discover import DiscoveredDevice

    d = DiscoveredDevice(
        instance="dock_1", service_type="_rosy-dock._tcp",
        host="dock_1.local", port=80,
    )
    assert d.instance == "dock_1"
    assert d.host.endswith(".local"), "mDNS hostnames end in .local (D-354)"


def test_dock_contract_documents_mdns_service_names():
    """계약 문서가 mDNS 서비스명 표를 포함한다 (D-354)."""
    readme = ROOT / "operations" / "site_devices" / "dock" / "README.md"
    text = readme.read_text(encoding="utf-8")
    assert "_rosy-dock._tcp" in text, "dock contract must name the mDNS service"
    assert "_rosy-signal._tcp" in text, "dock contract cross-references signal (D-352)"
