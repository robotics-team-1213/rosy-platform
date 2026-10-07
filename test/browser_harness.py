"""Shared helpers for the optional Chromium regressions (D-153 G2 캡처 훅).

렌더는 표면마다 다르지만 실행기·오류 수집·confirm 스텁·스크린샷 저장의 배관은
그렇지 않다. `robot_contracts.py` 의 공유 헬퍼 관례를 따른다 — D-92 는 제품
표면의 컴포넌트 공유를 금지할 뿐, 시험 도구의 공유는 다른 문제다.
"""

from __future__ import annotations

import os
from pathlib import Path
import socket
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

# Chromium net/base/port_util.cc kRestrictedPorts: page loads to these fail with
# net::ERR_UNSAFE_PORT. Windows hosts whose dynamic port range starts at 1024
# (`netsh int ipv4 show dynamicport tcp`) hand them out for port 0 (2049 seen 2026-10-07).
CHROMIUM_RESTRICTED_PORTS = frozenset({
    1, 7, 9, 11, 13, 15, 17, 19, 20, 21, 22, 23, 25, 37, 42, 43, 53, 69, 77, 79, 87, 95,
    101, 102, 103, 104, 109, 110, 111, 113, 115, 117, 119, 123, 135, 137, 139, 143, 161,
    179, 389, 427, 465, 512, 513, 514, 515, 526, 530, 531, 532, 540, 548, 554, 556, 563,
    587, 601, 636, 989, 990, 993, 995, 1719, 1720, 1723, 2049, 3659, 4045, 4190, 5060,
    5061, 6000, 6566, 6665, 6666, 6667, 6668, 6669, 6679, 6697, 10080,
})


def browser_tests_enabled() -> bool:
    """Opt-in for real-Chromium tests. `ROSY_RUN_BROWSER_TESTS=1` is canonical;
    `ROSY_BROWSER_TESTS=1` (the older Fleet name) is accepted too."""
    return "1" in (os.environ.get("ROSY_RUN_BROWSER_TESTS"), os.environ.get("ROSY_BROWSER_TESTS"))


def safe_listener(host: str = "127.0.0.1") -> socket.socket:
    """A socket bound to a free port Chromium will load (never a restricted one)."""
    for _ in range(64):
        listener = socket.socket()
        listener.bind((host, 0))
        if listener.getsockname()[1] not in CHROMIUM_RESTRICTED_PORTS:
            return listener
        listener.close()
    raise RuntimeError("could not allocate a browser-safe local port")


def safe_http_server(handler_cls, *, server_cls=ThreadingHTTPServer, host: str = "127.0.0.1"):
    """`server_cls` serving on an already-bound `safe_listener()` socket (no bind race)."""
    listener = safe_listener(host)
    server = server_cls(listener.getsockname(), handler_cls, bind_and_activate=False)
    server.socket.close()
    server.socket = listener
    # What HTTPServer.server_bind() would have set (handlers read server_port).
    server.server_address = listener.getsockname()
    server.server_name, server.server_port = host, server.server_address[1]
    server.server_activate()
    return server


def free_port(host: str = "127.0.0.1") -> int:
    """A browser-safe free port, closed before return, so another bind can take it first.
    Use only for a server API that accepts nothing but a port number."""
    with safe_listener(host) as listener:
        return listener.getsockname()[1]


def launch_options() -> dict:
    options = {"headless": True, "timeout": 10_000}
    if channel := os.environ.get("ROSY_BROWSER_CHANNEL"):
        options["channel"] = channel
    return options


def open_page(playwright, width: int, height: int, *, url: str | None = None):
    """Chromium 실행 + 페이지 오류 수집. 호출자이 browser.close() 한다."""
    options = launch_options()
    if url and (port := urlsplit(url).port):
        options["args"] = [f"--explicitly-allowed-ports={port}"]
    browser = playwright.chromium.launch(**options)
    page = browser.new_page(viewport={"width": width, "height": height})
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    # 기본 대기 예산은 15초다(2026-09-25). 5초는 경합 중인 호스트에서
    # goto(networkidle)·wait_for_function 을 계약과 무관하게 쓰러뜨렸다 —
    # 플레이크 사후 처리 3건이 같은 원인이었다. 계약 자체의 타임아웃은
    # 호출처에서 이미 명시적으로 지정한다.
    page.set_default_timeout(15_000)
    return browser, page, errors


DECLINE_CONFIRM = """
    window.__confirms = [];
    window.confirm = (message) => { window.__confirms.push(String(message)); return false; };
"""


def accept_confirm(page) -> None:
    """이후 confirm 을 수락한다. 표현식을 `; null` 로 닫는다 — Playwright
    evaluate 의 완료값이 함수면 그 함수를 무인자 호출하기 때문이다(D-153 회차 3
    발견)."""
    page.evaluate(
        "window.confirm = (message) => { window.__confirms.push(String(message));"
        " return true; }; null"
    )


def save_temp_screenshot(page, name: str) -> Path:
    shot = Path(os.environ.get("TEMP", "/tmp")) / name
    page.screenshot(path=str(shot))
    print(f"\nscreenshot: {shot}")
    return shot
