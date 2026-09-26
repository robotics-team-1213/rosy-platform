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


def test_shared_role_form_layout_collapses_to_full_width_on_mobile():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        results = {}
        for width in (1440, 390):
            page = _page(browser, width, 900)
            page.locator("#surface-main").evaluate("""node => { node.innerHTML = `
              <form class='ui-form' aria-label='로봇 설정'>
                <label class='ui-field-label'>로봇 이름<input aria-label='로봇 이름'></label>
                <label class='ui-field-label'>이름표<input aria-label='이름표'></label>
                <ui-button kind='primary'>저장</ui-button>
              </form>`; }""")
            results[width] = page.locator(".ui-form").evaluate("""form => ({
              overflow: document.documentElement.scrollWidth - innerWidth,
              direction: getComputedStyle(form).flexDirection,
              firstFieldWidth: form.firstElementChild.getBoundingClientRect().width,
              formWidth: form.getBoundingClientRect().width,
              labelDisplay: getComputedStyle(form.firstElementChild).display,
              gap: getComputedStyle(form).rowGap,
            })""")
            page.close()
        browser.close()

    assert results[1440]["overflow"] == 0
    assert results[1440]["direction"] == "row"
    assert results[1440]["labelDisplay"] == "grid"
    assert results[390]["overflow"] == 0
    assert results[390]["direction"] == "column"
    assert results[390]["firstFieldWidth"] == results[390]["formWidth"]


def test_shared_role_readout_stacks_label_value_pairs_on_mobile():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        results = {}
        for width in (1440, 390):
            page = _page(browser, width, 900)
            page.locator("#surface-main").evaluate("""node => { node.innerHTML = `
              <dl class='ui-readout' aria-label='로봇 상태'>
                <dt>연결 상태</dt><dd>정상</dd>
                <dt>현재 위치</dt><dd>123.456, -78.910</dd>
                <dt>장치 식별자</dt><dd>ROSYROBOTIDENTIFIER0123456789ABCDEFGHIJKL</dd>
              </dl>`; }""")
            results[width] = page.locator(".ui-readout").evaluate("""readout => ({
              overflow: document.documentElement.scrollWidth - innerWidth,
              columns: getComputedStyle(readout).gridTemplateColumns.split(' ').length,
              numberStyle: getComputedStyle(readout.querySelector('dd')).fontVariantNumeric,
              valueOverflow: readout.lastElementChild.scrollWidth > readout.lastElementChild.clientWidth,
            })""")
            page.close()
        browser.close()

    assert results[1440]["overflow"] == 0
    assert results[1440]["columns"] == 2
    assert results[1440]["numberStyle"] == "tabular-nums"
    assert results[390]["overflow"] == 0
    assert results[390]["columns"] == 1
    assert not results[390]["valueOverflow"]


def test_shared_readback_section_preserves_heading_gap_at_mobile_width():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        results = {}
        for width in (1440, 390):
            page = _page(browser, width, 900)
            page.locator("#surface-main").evaluate("""node => { node.innerHTML = `
              <section class='ui-readback' aria-label='시스템 읽기 결과'>
                <h3>시스템 정보</h3>
                <dl class='ui-readout'><dt>상태</dt><dd>정상</dd></dl>
              </section>`; }""")
            results[width] = page.locator(".ui-readback").evaluate("""section => ({
              overflow: document.documentElement.scrollWidth - innerWidth,
              width: section.getBoundingClientRect().width,
              minWidth: getComputedStyle(section).minWidth,
              display: getComputedStyle(section).display,
              gap: getComputedStyle(section).rowGap,
              titleMargin: getComputedStyle(section.querySelector('h3')).marginBlockStart,
            })""")
            page.close()
        browser.close()

    assert results[1440]["overflow"] == 0
    assert results[1440]["display"] == "grid"
    assert results[1440]["gap"] != "normal"
    assert results[1440]["titleMargin"] == "0px"
    assert results[390]["overflow"] == 0
    assert results[390]["width"] <= 390
    assert results[390]["minWidth"] == "0px"
