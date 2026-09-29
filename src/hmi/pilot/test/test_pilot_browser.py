"""D-323 — /pilot 브라우저 계약 (dev_server 가짜 CORE).

게이트 플로우 + 주행 화면 마운트 + 카메라 프레임 + 속도 프리셋을 태블릿 뷰포트에서
기계로 판정한다. ROSY_RUN_BROWSER_TESTS=1 옵트인.
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
def test_gate_panel_at_tablet_viewports(base_url):
    """게이트가 모든 태블릿 뷰포트에서 올바른 조립을 갖는다."""
    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for width, height in TABLET_VIEWPORTS:
                page = browser.new_page(viewport={"width": width, "height": height})
                errors: list[str] = []
                page.on("pageerror", lambda exc: errors.append(str(exc)))
                page.goto(f"{base_url}/pilot")
                page.wait_for_selector("form[data-pilot-token-form] ui-field input")
                assert page.locator('ui-head#pilot-gate-heading').inner_text() == "접속 게이트"
                assert page.locator("dl[data-gate-readout] dt").count() >= 2
                assert _gate_value(page) == "WAIT"
                assert page.locator("ui-topbar ui-tag").count() == 1
                assert page.locator('ui-topbar ui-button[data-estop][kind="irreversible"]').count() == 1
                manifest_href = page.evaluate(
                    "document.querySelector('link[rel=manifest]')?.href ?? ''")
                assert manifest_href.endswith("/pilot/assets/manifest.webmanifest")
                step = page.evaluate(
                    "getComputedStyle(document.documentElement).getPropertyValue('--space-1').trim()")
                assert step, "tokens.css 가 적용되지 않았다"
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
def test_drive_screen_fullscreen_with_camera_and_presets(tablet_page):
    """주행 화면이 풀스크린 카메라 + 휠 + 페달 + 프리셋을 갖는다."""
    base_url, page, errors = tablet_page
    page.goto(f"{base_url}/pilot")
    page.wait_for_selector("form[data-pilot-token-form] ui-field input")
    page.fill("form[data-pilot-token-form] ui-field input", "devtoken")
    page.click("form[data-pilot-token-form] ui-button")
    page.wait_for_selector("[data-drive-enter]")
    page.click("[data-drive-enter]")
    page.wait_for_selector("[data-drive-wheel]")
    page.wait_for_timeout(500)   # CSS 적용 대기

    # 풀스크린: drive가 뷰포트를 채운다
    layout = page.evaluate("""(() => {
      const stage = document.querySelector('[data-drive-stage]')?.getBoundingClientRect();
      const drive = document.querySelector('.pilot-drive')?.getBoundingClientRect();
      const wheel = document.querySelector('[data-drive-wheel]')?.getBoundingClientRect();
      const pedals = document.querySelector('[data-drive-pedals]')?.getBoundingClientRect();
      const body = document.body.dataset.pilotScreen;
      return {
        viewport: {w: window.innerWidth, h: window.innerHeight},
        body: body,
        drive: drive ? {w: Math.round(drive.width), h: Math.round(drive.height)} : null,
        stage: stage ? {w: Math.round(stage.width), h: Math.round(stage.height)} : null,
        wheel: wheel ? {w: Math.round(wheel.width)} : null,
        pedals: pedals ? {w: Math.round(pedals.width)} : null,
      };
    })()""")
    viewport = layout["viewport"]
    assert layout["body"] == "drive", f"body flag: {layout['body']}"
    assert layout["drive"] is not None, "drive 요소 없음"
    assert layout["drive"]["w"] >= viewport["w"] * 0.9, \
        f"드라이브 폭 {layout['drive']['w']}px < 뷰포트 {viewport['w']}px의 90%"

    # 휠이 존재하고 페달이 있다
    assert layout["wheel"]["w"] > 50, "휠이 너무 작다"
    assert layout["pedals"] and layout["pedals"]["w"] > 50, "페달이 너무 작다"

    # 휠이 존재하고 페달이 있다
    assert layout["wheel"]["w"] > 50, "휠이 너무 작다"
    assert layout["pedals"]["w"] > 50, "페달이 너무 작다"

    # 프리셋이 있다
    presets = page.locator("[data-drive-preset-row] ui-button").count()
    assert presets == 3, f"프리셋 버튼 {presets}개 (low/mid/high 3개여야)"

    # 카메라 프레임이 로드됨 (canned JPEG)
    page.wait_for_selector("[data-drive-frame][src]", timeout=10_000)
    cam_w = page.evaluate("document.querySelector('[data-drive-frame]')?.naturalWidth ?? 0")
    assert cam_w > 0, f"카메라 naturalWidth={cam_w}"

    assert errors == [], errors


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
                    reason="ROSY_RUN_BROWSER_TESTS=1 옵트인")
def test_speed_preset_changes_command_scale(tablet_page):
    """고속 프리셋이 실제로 명령 스케일을 바꾼다."""
    base_url, page, errors = tablet_page
    page.goto(f"{base_url}/pilot")
    page.wait_for_selector("form[data-pilot-token-form] ui-field input")
    page.fill("form[data-pilot-token-form] ui-field input", "devtoken")
    page.click("form[data-pilot-token-form] ui-button")
    page.wait_for_selector("[data-drive-enter]")
    page.click("[data-drive-enter]")
    page.wait_for_selector("[data-drive-wheel]")

    # 기본(저속) 상태에서 localStorage 확인
    config_low = page.evaluate("JSON.parse(localStorage.getItem('rosy.pilot.input') ?? '{}')")
    assert config_low.get("preset", "low") == "low"

    # 고속 클릭
    page.evaluate("""
      const row = document.querySelector('[data-drive-preset-row]');
      const high = [...row.querySelectorAll('ui-button')].find(b => b.textContent.includes('high'));
      if (high) high.click();
    """)
    page.wait_for_timeout(300)
    config_high = page.evaluate("JSON.parse(localStorage.getItem('rosy.pilot.input') ?? '{}')")
    assert config_high.get("preset") == "high"

    # 스틱 매핑 확인 — 고속은 저속보다 크다
    scale = page.evaluate("""(() => {
      const config = JSON.parse(localStorage.getItem('rosy.pilot.input') ?? '{}');
      return config.preset;
    })()""")
    assert scale == "high"
    assert errors == [], errors
