"""D-359 §6.4·§7.8 — 역할 표면의 세로 예산과 가로 넘침 (LOCAL Chromium, FastAPI 원본).

390×844와 320×568에서 /console·/setup·/device를 실제 CORE 앱 응답으로 띄운다.
- 문서가 가로로 넘치지 않는다(scrollWidth ≤ innerWidth).
- 붙박이 머리(ui-topbar)는 창 높이의 20% 이하다.
- 비상 정지는 첫 화면 안에 있고, 끝까지 스크롤해도 화면 안에 남는다.

변이 증명: components.css `ui-topbar`에 `min-height: 300px`을 넣으면 빨갛다.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from browser_harness import browser_tests_enabled
from playwright.sync_api import sync_playwright

from test_role_g2_browser import TOKENS, _core_client, _response

pytestmark = pytest.mark.skipif(
    not browser_tests_enabled(),
    reason="set ROSY_RUN_BROWSER_TESTS=1 for the LOCAL Chromium viewport budget",
)

SURFACES = ("console", "setup", "device")
VIEWPORTS = ((390, 844), (320, 568))

MEASURE = """() => {
  const box = (selector) => document.querySelector(selector).getBoundingClientRect().toJSON();
  return {
    iw: innerWidth, ih: innerHeight,
    overflow: document.documentElement.scrollWidth - innerWidth,
    outside: [...document.querySelectorAll('body *')]
      .filter(node => node.getBoundingClientRect().right > innerWidth + 1)
      .slice(0, 6).map(node => `${node.tagName}#${node.id}.${node.className}`),
    topbar: box('ui-topbar'),
    rail: box('.ui-rail'),
    railItems: [...document.querySelectorAll('#surface-switch .ui-rail-item')].map(node => node.getBoundingClientRect().toJSON()),
    roleClipped: document.querySelector('#shell-role').scrollWidth > document.querySelector('#shell-role').clientWidth + 1,
    sticky: getComputedStyle(document.querySelector('ui-topbar')).position,
    estop: box('#shell-estop'),
    slots: ['observe', 'act', 'sense'].map(name => document.querySelector(`[data-slot="${name}"]`))
      .filter(Boolean).map(node => node.getBoundingClientRect().toJSON()),
    slotOrder: [...document.querySelectorAll('#surface-main > .surface-slot')].map(node => node.dataset.slot),
    cameraActions: [...document.querySelectorAll('#vision-expand, #vision-record-stop')]
      .map(node => node.getBoundingClientRect().toJSON()),
  };
}"""


def _inside(rect: dict, width: int, height: int) -> bool:
    return rect["top"] >= 0 and rect["left"] >= 0 and rect["bottom"] <= height and rect["right"] <= width


def test_manifest_failure_has_a_keyboard_retry_and_preserves_the_stop(tmp_path):
    client = _core_client(tmp_path)
    token = TOKENS["administrator"]
    failing = {"value": True}
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 320, "height": 568})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script(f"sessionStorage.setItem('rosy.dashboard.token', {token!r})")

        def serve(route):
            path = urlsplit(route.request.url).path
            if path == "/api/v1/ui/surfaces/setup" and failing["value"]:
                route.fulfill(status=503, json={"detail": "일시적으로 연결할 수 없습니다"})
                return
            if route.request.method != "GET":
                route.fulfill(status=501, json={"detail": "fixture blocks writes"})
                return
            response = _response(client, path, token, "normal", "setup")
            route.fulfill(status=response.status_code,
                          content_type=response.headers.get("content-type", "application/octet-stream"),
                          body=response.content if hasattr(response, "content") else response.body)

        page.route("**/*", serve)
        page.goto("http://rosy.test/setup", wait_until="domcontentloaded")
        retry = page.get_by_role("button", name="화면 구성 다시 불러오기", exact=True)
        retry.wait_for(state="visible")
        assert page.locator("#shell-estop").is_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        failing["value"] = False
        retry.focus()
        page.keyboard.press("Enter")
        page.wait_for_function("document.querySelector('#surface-status').hidden")
        assert page.locator("#surface-retry").count() == 0
        # D-741 6: 레일은 아이콘 아래에 짧은 이름을 적고 전체 이름은 접근성 이름이다.
        current = page.locator("#surface-switch [aria-current=page]")
        assert current.get_attribute("aria-label") == "작업 준비"
        assert current.inner_text().strip() == "준비"
        assert errors == [], errors
        browser.close()


@pytest.mark.parametrize("width,height", VIEWPORTS)
def test_role_surfaces_keep_the_header_budget_and_the_stop_in_view(tmp_path, width, height):
    client = _core_client(tmp_path)
    token = TOKENS["administrator"]
    records = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for surface in SURFACES:
            context = browser.new_context(viewport={"width": width, "height": height})
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script(f"sessionStorage.setItem('rosy.dashboard.token', {token!r})")

            def serve(route, surface=surface):
                request = route.request
                if request.method != "GET":
                    route.fulfill(status=501, content_type="application/json", body='{"detail":"fixture blocks writes"}')
                    return
                response = _response(client, urlsplit(request.url).path, token, "normal", surface)
                route.fulfill(status=response.status_code, headers={
                    "content-type": response.headers.get("content-type", "application/octet-stream"),
                    "cache-control": "no-store",
                }, body=response.content if hasattr(response, "content") else response.body)

            page.route("**/*", serve)
            page.goto(f"http://rosy.test/{surface}", wait_until="domcontentloaded")
            page.wait_for_function("""() => {
              const status = document.querySelector('#surface-status');
              if (!status) return false;
              if (status.hidden) return true;
              const text = (status.textContent || '').trim();
              return text !== '' && text !== '화면을 불러오는 중입니다.';
            }""")
            page.wait_for_timeout(300)
            first = page.evaluate(MEASURE)
            if shot_dir := os.environ.get("ROSY_SHOT_DIR"):
                Path(shot_dir).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(shot_dir) / f"robot-{surface}-{width}x{height}.png"))
            page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
            page.wait_for_timeout(100)
            scrolled = page.evaluate(MEASURE)
            records[surface] = {"first": first, "scrolled": scrolled, "errors": errors}
            context.close()
        browser.close()

    for surface, record in records.items():
        first, scrolled = record["first"], record["scrolled"]
        assert record["errors"] == [], (surface, record)
        assert first["overflow"] <= 0, (surface, first["outside"])
        assert first["roleClipped"] is False, (surface, first)
        assert first["topbar"]["height"] <= 0.2 * height, (
            f"{surface} {width}×{height}: 머리 {first['topbar']['height']}px > 창 높이의 20%")
        # D-741 6: 화면 전환은 머리 아래 레일 한 줄이다. 머리와 더해도 예산 안이고 세 화면이 한 줄에 선다.
        chrome = first["topbar"]["height"] + first["rail"]["height"]
        assert chrome <= 0.2 * height, f"{surface} {width}×{height}: 머리+레일 {chrome}px > 창 높이의 20%"
        assert first["topbar"]["bottom"] <= first["rail"]["top"], (surface, first["topbar"], first["rail"])
        rail_items = first["railItems"]
        assert len(rail_items) == 3 and len({round(item["top"]) for item in rail_items}) == 1, (surface, rail_items)
        assert _inside(first["estop"], width, height), (surface, first["estop"])
        assert first["sticky"] == "sticky", (surface, first["sticky"])
        if surface == "console":
            assert first["slotOrder"] == ["banner", "observe", "act", "sense"], (width, first)
            slots = first["slots"]
            assert slots[0]["top"] < slots[1]["top"] < slots[2]["top"], (width, slots)
            assert max(slot["x"] for slot in slots) - min(slot["x"] for slot in slots) <= 1, (width, slots)
            assert max(slot["width"] for slot in slots) - min(slot["width"] for slot in slots) <= 1, (width, slots)
            actions = first["cameraActions"]
            assert len(actions) == 2 and abs(actions[0]["width"] - actions[1]["width"]) <= 1, (width, actions)
        assert _inside(scrolled["estop"], width, height), (
            f"{surface}: 끝까지 스크롤하면 비상 정지가 화면 밖이다", scrolled["estop"])
