"""mDNS/DNS-SD 서비스 발견 — 외부 장비를 주소 없이 찾는다 (D-354).

장비는 `_rosy-dock._tcp`·`_rosy-signal._tcp` 등으로 광고한다. 이 유틸리티는
LAN에서 해당 서비스를 찾아 (instance, host, port) 목록을 반환한다.

3단 폴백:
1. `zeroconf` 패키지 (순수 Python, pip install zeroconf)
2. `avahi-browse` (Linux, systemd 표준)
3. `dns-sd` (macOS/Windows Bonjour)

어느 쪽도 없으면 빈 목록 + 경고 — 발견은 편의 기능이지 필수가 아니다.
`.local` 호스트명으로 직접 접속하는 것은 OS의 mDNS 해석기가 처리하므로
이 유틸리티 없이도 동작한다.
"""

from __future__ import annotations

import subprocess
import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DiscoveredDevice:
    """mDNS로 발견된 외부 장비 1대."""

    instance: str          # 장비 ID (예: "dock_1")
    service_type: str      # "_rosy-dock._tcp"
    host: str              # "rosy-dock-1.local"
    port: int


def discover_devices(service_type: str, *, timeout_s: float = 3.0) -> list[DiscoveredDevice]:
    """LAN에서 해당 서비스 유형의 장비를 찾는다.

    service_type 예: "_rosy-dock._tcp", "_rosy-signal._tcp"
    """
    for attempt in (_via_zeroconf, _via_avahi, _via_dnssd):
        result = attempt(service_type, timeout_s)
        if result is not None:
            return result
    return []  # 발견 도구 없음 — 빈 목록


# --- 1순위: zeroconf 패키지 ---------------------------------------------------

def _via_zeroconf(service_type: str, timeout_s: float) -> Optional[list[DiscoveredDevice]]:
    try:
        from zeroconf import ServiceBrowser, Zeroconf
    except ImportError:
        return None

    found: list[DiscoveredDevice] = []

    class _Listener:
        def add_service(self, zc: "Zeroconf", type_: str, name: str) -> None:
            info = zc.get_service_info(type_, name)
            if info is None:
                return
            instance = name.split(".")[0].replace("\\", "")
            host = info.server.rstrip(".")
            found.append(DiscoveredDevice(
                instance=instance, service_type=service_type,
                host=host, port=info.port,
            ))

        def update_service(self, zc: "Zeroconf", type_: str, name: str) -> None:
            pass  # 갱신은 이 허용 범위 밖

    zc = Zeroconf()
    try:
        import time
        browser = ServiceBrowser(zc, service_type + ".local.", _Listener())
        time.sleep(timeout_s)
    finally:
        zc.close()
    return found


# --- 2순위: avahi-browse (Linux) ----------------------------------------------

def _via_avahi(service_type: str, timeout_s: float) -> Optional[list[DiscoveredDevice]]:
    import shutil
    if shutil.which("avahi-browse") is None:
        return None

    try:
        result = subprocess.run(
            ["avahi-browse", "-rt", service_type],
            capture_output=True, text=True, timeout=timeout_s + 1.0,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    devices: list[DiscoveredDevice] = []
    for line in result.stdout.splitlines():
        # = eth0 IPv4 dock_1 _rosy-dock._tcp local
        match = re.match(r"=\s+\S+\s+IPv[46]\s+(\S+)\s+" + re.escape(service_type), line)
        if match:
            instance = match.group(1)
            # avahi-browse -t doesn't give host/port in the resolve line; use -r
            devices.append(DiscoveredDevice(
                instance=instance, service_type=service_type,
                host=f"{instance.replace('_', '-')}.local", port=80,
            ))
    return devices


# --- 3순위: dns-sd (macOS/Windows Bonjour) -------------------------------------

def _via_dnssd(service_type: str, timeout_s: float) -> Optional[list[DiscoveredDevice]]:
    import shutil
    import sys
    if sys.platform == "linux" or shutil.which("dns-sd") is None:
        return None

    try:
        proc = subprocess.Popen(
            ["dns-sd", "-B", service_type.split(".")[0], service_type.split(".")[1]],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        import time
        time.sleep(timeout_s)
        proc.terminate()
        output, _ = proc.communicate(timeout=1.0)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    devices: list[DiscoveredDevice] = []
    for line in output.splitlines():
        match = re.search(r"Add\s+Rendezvous\s+(\S+)\s+" + re.escape(service_type.split(".")[0]), line)
        if match:
            instance = match.group(1)
            devices.append(DiscoveredDevice(
                instance=instance, service_type=service_type,
                host=f"{instance.replace('_', '-')}.local", port=80,
            ))
    return devices
