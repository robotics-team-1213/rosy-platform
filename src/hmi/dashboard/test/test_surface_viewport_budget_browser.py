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
from playwright.sync_api import sync_playwright

from test_role_g2_browser import TOKENS, _core_client, _response

pytestmark = pytest.mark.skipif(
    os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
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
    sticky: getComputedStyle(document.querySelector('ui-topbar')).position,
    estop: box('#shell-estop'),
  };
}"""


def _inside(rect: dict, width: int, height: int) -> bool:
    return rect["top"] >= 0 and rect["left"] >= 0 and rect["bottom"] <= height and rect["right"] <= width


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
        assert first["topbar"]["height"] <= 0.2 * height, (
            f"{surface} {width}×{height}: 머리 {first['topbar']['height']}px > 창 높이의 20%")
        assert _inside(first["estop"], width, height), (surface, first["estop"])
        assert first["sticky"] == "sticky", (surface, first["sticky"])
        assert _inside(scrolled["estop"], width, height), (
            f"{surface}: 끝까지 스크롤하면 비상 정지가 화면 밖이다", scrolled["estop"])
