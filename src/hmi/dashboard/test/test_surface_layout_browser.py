"""Browser contract for the current role-aware console shell layout."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
WEB_COMMON = ROOT.parent / "web"

pytestmark = pytest.mark.skipif(
    os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
    reason="set ROSY_RUN_BROWSER_TESTS=1 to run the optional Chromium regression",
)


def _page(browser, width: int, height: int):
    page = browser.new_page(viewport={"width": width, "height": height})
    styles = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            WEB_COMMON / "tokens.css",
            WEB_COMMON / "components.css",
            ROOT / "shell" / "shell.css",
        )
    )
    page.set_content(
        f"""<!doctype html><html lang="ko"><head><meta name="viewport" content="width=device-width, initial-scale=1"><style>{styles}</style></head>
        <body data-surface="console"><ui-shell grammar="spatial">
          <ui-topbar><ui-brand><b>ROSY</b><small>운용</small></ui-brand>
            <nav id="surface-switch" class="surface-switch"><a aria-current="page">운용</a><a>작업 준비</a><a>설치·정비</a></nav>
            <span data-spacer></span><ui-text id="shell-notice" scale="label"></ui-text>
            <ui-tag id="shell-role">administrator</ui-tag><ui-button kind="irreversible" id="shell-estop">비상 정지</ui-button>
          </ui-topbar>
          <main class="surface-main" id="surface-main">
            <ui-empty id="surface-status" hidden></ui-empty>
            <div class="surface-slot" data-slot="banner"></div>
            <div class="surface-slot" data-slot="sense"><ui-section style="min-height: 24rem">Sense</ui-section></div>
            <div class="surface-slot" data-slot="observe"><ui-section style="min-height: 30rem">Observe</ui-section></div>
            <div class="surface-slot" data-slot="act"><ui-section style="min-height: 32rem">Act</ui-section></div>
          </main></ui-shell></body></html>""",
        wait_until="load",
    )
    return page


def test_mobile_topbar_wraps_without_overlapping_brand_navigation_or_stop():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = _page(browser, 390, 844)
        result = page.evaluate("""() => {
          const rect = (selector) => {
            const {x, y, right, bottom} = document.querySelector(selector).getBoundingClientRect();
            return {x, y, right, bottom};
          };
          return {
            overflow: document.documentElement.scrollWidth - innerWidth,
            brand: rect('ui-brand'), nav: rect('#surface-switch'), role: rect('#shell-role'),
            estop: rect('#shell-estop'),
          };
        }""")
        browser.close()

    assert result["overflow"] == 0
    assert result["estop"]["y"] <= result["brand"]["y"]
    assert result["brand"]["bottom"] <= result["estop"]["bottom"]
    assert result["brand"]["bottom"] <= result["nav"]["y"]
    assert result["nav"]["right"] <= 390
    assert result["nav"]["bottom"] <= result["role"]["y"]
    assert result["estop"]["right"] <= 390
