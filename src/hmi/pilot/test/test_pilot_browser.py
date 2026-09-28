"""D-323 — /pilot 접속 게이트의 브라우저 계약(dev_server 가짜 CORE).

dashboard 패널 조립 문법(ui-head + dl.ui-readout + ui-actions, 상단 e-stop)을
태블릿 뷰포트(2000×1200·1200×2000)에서 기계로 판정한다. 다른 브라우저 시험과
같은 옵트인(ROSY_RUN_BROWSER_TESTS=1).
"""

from __future__ import annotations

import os
import socket
import sys
import threading
from pathlib import Path

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api", reason="Playwright 없음")
import uvicorn  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dev_server  # noqa: E402

TABLET_VIEWPORTS = [(2000, 1200), (1200, 2000)]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def base_url():
    config = uvicorn.Config(dev_server.app, host="127.0.0.1",
                            port=_free_port(), log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        thread.join(0.05)
    yield f"http://127.0.0.1:{config.port}"
    server.should_exit = True
    thread.join(timeout=5)


def _gate_value(page) -> str:
    return page.locator('dl[data-gate-readout] dd').first.inner_text()


@pytest.fixture
def tablet_page(base_url):
    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 2000, "height": 1200})
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.set_default_timeout(10_000)
        yield base_url, page, errors
        browser.close()


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_gate_panel_follows_the_dashboard_composition(base_url):
    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for width, height in TABLET_VIEWPORTS:
                page = browser.new_page(viewport={"width": width, "height": height})
                errors: list[str] = []
                page.on("pageerror", lambda exc: errors.append(str(exc)))
                page.goto(f"{base_url}/pilot")
                page.wait_for_selector("form[data-pilot-token-form] ui-field input")
                # 패널 조립: ui-head 제목 + ui-readout 사실 + 토큰 폼.
                assert page.locator('ui-head#pilot-gate-heading').inner_text() == "접속 게이트"
                assert page.locator("dl[data-gate-readout] dt").count() >= 2
                assert _gate_value(page) == "WAIT"
                # 상단: 역할 태그 + 관제 이동 + 항상 닿는 비상 정지(irreversible).
                assert page.locator("ui-topbar ui-tag").count() == 1
                assert page.locator('ui-topbar ui-button[data-goto="/dashboard"]').count() == 1
                assert page.locator("ui-topbar ui-button[data-estop][kind='irreversible']").count() == 1
                # 토큰 단일 출처: tokens.css 가 :root 에 스텝 척도를 내려놓는다(D-130.3).
                step = page.evaluate(
                    "getComputedStyle(document.documentElement).getPropertyValue('--space-1').trim()")
                assert step, "tokens.css 가 적용되지 않았다"
                # 설치형(D-328): manifest 링크 + 서비스 워커 등록(localhost = secure context).
                manifest_href = page.evaluate(
                    "document.querySelector('link[rel=manifest]')?.href ?? ''")
                assert manifest_href.endswith("/pilot/assets/manifest.webmanifest")
                registered = page.evaluate("""(async () => {
                  for (let i = 0; i < 40; i++) {
                    const reg = await navigator.serviceWorker.getRegistration('/pilot');
                    if (reg) return true;
                    await new Promise((resolve) => setTimeout(resolve, 250));
                  }
                  return false;
                })()""")
                assert registered, "서비스 워커가 등록되지 않았다"
                overflow = page.evaluate(
                    "document.documentElement.scrollWidth - document.documentElement.clientWidth")
                assert overflow <= 0, f"가로 넘침 {overflow}px ({width}x{height})"
                assert errors == [], errors
                page.close()
        finally:
            browser.close()


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_bad_token_is_refused_with_guidance(tablet_page):
    base_url, page, errors = tablet_page
    page.goto(f"{base_url}/pilot")
    page.wait_for_selector("form[data-pilot-token-form] ui-field input")
    page.fill("form[data-pilot-token-form] ui-field input", "wrong-token")
    page.click("form[data-pilot-token-form] ui-button")
    page.wait_for_selector("text=토큰이 유효하지 않습니다")
    assert _gate_value(page) == "BLOCK"
    assert errors == [], errors


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_drive_screen_mounts_after_the_gate(tablet_page):
    base_url, page, errors = tablet_page
    page.goto(f"{base_url}/pilot")
    page.wait_for_selector("form[data-pilot-token-form] ui-field input")
    page.fill("form[data-pilot-token-form] ui-field input", "devtoken")
    page.click("form[data-pilot-token-form] ui-button")
    page.click("[data-drive-enter]")
    page.wait_for_selector("[data-drive-stage]")
    assert page.locator("[data-drive-wheel]").is_visible()
    assert page.locator("[data-drive-pedal=forward]").is_visible()
    assert page.locator("[data-drive-readout] [data-drive-fact=link]").count() == 1
    # 게이트 화면은 숨는다.
    assert not page.locator("[data-screen=connect]").is_visible()
    assert errors == [], errors
