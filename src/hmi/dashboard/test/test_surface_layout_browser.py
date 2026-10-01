"""Browser contract for the current role-aware console shell layout."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
WEB_COMMON = ROOT.parent / "web_common"

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
            ROOT / "panels" / "surface-panels.css",
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

    # D-359 §6.4 — 두 줄 머리: 이름·역할 / 화면 전환, 비상 정지는 두 줄 오른쪽에 걸친다.
    assert result["overflow"] == 0
    assert result["estop"]["y"] <= result["brand"]["y"]
    assert result["brand"]["bottom"] <= result["estop"]["bottom"]
    assert result["brand"]["bottom"] <= result["nav"]["y"]
    assert result["role"]["bottom"] <= result["nav"]["y"]
    assert result["brand"]["right"] <= result["role"]["x"]
    assert result["role"]["right"] <= result["estop"]["x"]
    assert result["nav"]["right"] <= result["estop"]["x"]
    assert result["estop"]["right"] <= 390


def test_desktop_console_keeps_three_regions_and_active_controls_inside_viewport():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = _page(browser, 1366, 768)
        page.evaluate("""() => {
          for (const slot of document.querySelectorAll('.surface-slot')) {
            for (const panel of slot.querySelectorAll('ui-section')) panel.style.minHeight = '0';
          }
          const sense = document.querySelector('[data-slot=sense] ui-section');
          sense.style.height = '60rem';
          const observe = document.querySelector('[data-slot=observe] ui-section');
          observe.style.height = '100%';
          const act = document.querySelector('[data-slot=act]');
          act.replaceChildren();
          const tabs = document.createElement('div'); tabs.className = 'action-group-tabs';
          tabs.setAttribute('role', 'tablist'); tabs.innerHTML = '<ui-button role="tab" aria-selected="true">운전</ui-button><ui-button role="tab">도킹</ui-button>';
          const panel = document.createElement('div'); panel.className = 'action-group-panel';
          panel.setAttribute('role', 'tabpanel'); panel.innerHTML = '<ui-section><h2>운전 모드</h2><ui-button>대기</ui-button></ui-section><ui-section><h2>저속 직접 제어</h2><ui-button>전진</ui-button></ui-section>';
          act.append(tabs, panel);
        }""")
        result = page.evaluate("""() => {
          const rect = (selector) => {
            const {x, y, right, bottom} = document.querySelector(selector).getBoundingClientRect();
            return {x, y, right, bottom};
          };
          return {
            documentHeight: document.documentElement.scrollHeight,
            bodyHeight: document.body.scrollHeight,
            sense: rect('[data-slot=sense]'), observe: rect('[data-slot=observe]'),
            act: rect('[data-slot=act]'), estop: rect('#shell-estop'), topbar: rect('ui-topbar'),
            senseScrollable: document.querySelector('[data-slot=sense]').scrollHeight
              > document.querySelector('[data-slot=sense]').clientHeight,
            activeBottom: document.querySelector('.action-group-panel').getBoundingClientRect().bottom,
          };
        }""")
        browser.close()

    assert result["documentHeight"] == 768
    assert result["bodyHeight"] == 768
    assert result["senseScrollable"] is True
    assert result["sense"]["y"] >= result["topbar"]["bottom"]
    assert result["sense"]["bottom"] <= 768
    assert result["sense"]["right"] <= result["observe"]["x"]
    assert result["observe"]["right"] <= result["act"]["x"]
    assert result["act"]["bottom"] <= 768
    assert result["activeBottom"] <= result["act"]["bottom"]
    assert result["estop"]["bottom"] <= result["topbar"]["bottom"]


def test_wide_but_short_console_keeps_its_columns_and_scrolls_the_page():
    """D-359 US-008: 1366x600 (wide, height < 40rem) stacked the console into one column because
    the columns rule and the fixed-frame rule shared one media condition. The frame lets go and
    the page scrolls; the three columns stay."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = _page(browser, 1366, 600)
        result = page.evaluate("""() => {
          const rect = (selector) => document.querySelector(selector).getBoundingClientRect().toJSON();
          return {
            overflow: document.documentElement.scrollWidth - innerWidth,
            documentHeight: document.documentElement.scrollHeight,
            bodyOverflow: getComputedStyle(document.body).overflowY,
            sense: rect('[data-slot=sense]'), observe: rect('[data-slot=observe]'),
            act: rect('[data-slot=act]'), estop: rect('#shell-estop'),
          };
        }""")
        browser.close()

    assert result["overflow"] <= 0, result
    assert result["sense"]["right"] <= result["observe"]["x"], result
    assert result["observe"]["right"] <= result["act"]["x"], result
    assert result["sense"]["y"] == result["observe"]["y"] == result["act"]["y"], result
    assert result["documentHeight"] > 600 and result["bodyOverflow"] != "hidden", result
    estop = result["estop"]
    assert estop["y"] >= 0 and estop["bottom"] <= 600 and estop["right"] <= 1366, result


def test_map_uses_remaining_desktop_observe_height_and_stays_within_mobile_width():
    with sync_playwright() as playwright:
        visible = os.environ.get("ROSY_VISIBLE_BROWSER") == "1"
        browser = playwright.chromium.launch(headless=not visible)
        desktop_results = {}
        for width, height in ((1366, 768), (1440, 900)):
            page = _page(browser, width, height)
            page.evaluate("""() => {
              for (const slot of document.querySelectorAll('.surface-slot')) {
                for (const panel of slot.querySelectorAll('ui-section')) panel.style.minHeight = '0';
              }
              const observe = document.querySelector('[data-slot=observe]');
              observe.replaceChildren();
              const map = document.createElement('ui-section');
              map.innerHTML = `<ui-head>지도 및 위치</ui-head><ui-status>100×100</ui-status>
                <ui-actions>레이어</ui-actions><p>지도 안내</p><ui-actions>지도 작업</ui-actions>
                <div class="surface-map-frame"><canvas class="surface-map-canvas"></canvas>
                  <dl class="ui-readout surface-map-readout"><dt>선택 좌표</dt><dd role="status">X 0.00 m · Y 0.00 m</dd></dl></div>
                <a>작업 준비</a><ui-status>지도 상태</ui-status><ui-status>작업 결과</ui-status>`;
              const camera = document.createElement('ui-section');
              camera.innerHTML = `<ui-head>전방 카메라</ui-head><div class="surface-camera-stage">카메라</div>`;
              observe.append(map);
              document.querySelector('[data-slot=sense]').append(camera);
              const act = document.querySelector('[data-slot=act]');
              act.replaceChildren();
              const tabs = document.createElement('div'); tabs.className = 'action-group-tabs';
              tabs.innerHTML = '<ui-button role="tab">운전</ui-button><ui-button role="tab">도킹</ui-button><ui-button role="tab">차선 추종</ui-button>';
              const panel = document.createElement('div'); panel.className = 'action-group-panel';
              panel.innerHTML = '<ui-section><ui-head>운전</ui-head><ui-button>정지</ui-button></ui-section>';
              act.append(tabs, panel);
            }""")
            desktop_results[width] = page.evaluate("""() => ({
              canvas: document.querySelector('.surface-map-canvas').getBoundingClientRect().height,
              frame: document.querySelector('.surface-map-frame').getBoundingClientRect().height,
              mapPanel: document.querySelector('[data-slot=observe] ui-section').getBoundingClientRect(),
              actPanel: document.querySelector('.action-group-panel').getBoundingClientRect(),
              overflow: document.documentElement.scrollHeight - innerHeight,
              estopBottom: document.querySelector('#shell-estop').getBoundingClientRect().bottom,
              topbarBottom: document.querySelector('ui-topbar').getBoundingClientRect().bottom,
              viewportHeight: innerHeight,
            })""")
            if visible:
                screenshot_dir = Path(os.environ.get("ROSY_SCREENSHOT_DIR", r"X:\DevTemp\rosy-uiux-followup"))
                screenshot_dir.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(screenshot_dir / f"console-map-{width}x{height}.png"), full_page=True)
                page.wait_for_timeout(1500)
            page.close()
        mobile = _page(browser, 390, 844)
        mobile_overflow = mobile.evaluate("Math.max(0, document.documentElement.scrollWidth - innerWidth)")
        browser.close()

    for result in desktop_results.values():
        assert result["canvas"] > 200, desktop_results
        assert result["frame"] > result["canvas"]
        assert result["overflow"] == 0
        assert result["actPanel"]["bottom"] <= result["viewportHeight"]
        assert result["estopBottom"] <= result["topbarBottom"]
    assert mobile_overflow == 0

def test_shared_role_form_layout_collapses_to_full_width_on_mobile():
    """D-359 §6.3 — 폼은 뷰포트가 아니라 칸(#surface-main)에 반응한다. 320px 폰의 칸은 22rem보다 좁다."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        results = {}
        for width in (1440, 320):
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
    assert results[320]["overflow"] == 0
    assert results[320]["direction"] == "column"
    assert results[320]["firstFieldWidth"] == results[320]["formWidth"]


def test_shared_role_readout_stacks_label_value_pairs_on_mobile():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        results = {}
        for width in (1440, 390, 320):
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
    # 390px 폰의 칸(약 22.9rem)은 두 열을 지키고 긴 값은 줄바꿈한다. 320px 칸은 한 열이다.
    assert results[390]["overflow"] == 0
    assert results[390]["columns"] == 2
    assert not results[390]["valueOverflow"]
    assert results[320]["overflow"] == 0
    assert results[320]["columns"] == 1
    assert not results[320]["valueOverflow"]


def test_shared_parts_follow_their_slot_width_not_the_viewport():
    """D-359 §6.3 — 넓은 창이라도 좁은 칸의 폼·읽기·조작 묶음은 한 열로 쌓이고, 넓은 칸은 그대로다."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = _page(browser, 1440, 900)
        page.locator("#surface-main").evaluate("""node => { node.innerHTML = `
          <div class='surface-slot' data-slot='narrow' style='width: 20rem'>
            <form class='ui-form'><label class='ui-field-label'>이름<input></label><ui-button>저장</ui-button></form>
            <dl class='ui-readout'><dt>상태</dt><dd>정상</dd></dl>
            <ui-actions><ui-button>하나</ui-button><ui-button>둘</ui-button></ui-actions>
          </div>
          <div class='surface-slot' data-slot='wide'>
            <form class='ui-form'><label class='ui-field-label'>이름<input></label><ui-button>저장</ui-button></form>
            <dl class='ui-readout'><dt>상태</dt><dd>정상</dd></dl>
            <ui-actions><ui-button>하나</ui-button><ui-button>둘</ui-button></ui-actions>
          </div>`; }""")
        result = page.evaluate("""() => Object.fromEntries(['narrow', 'wide'].map(slot => {
          const root = document.querySelector(`[data-slot=${slot}]`);
          return [slot, {
            form: getComputedStyle(root.querySelector('.ui-form')).flexDirection,
            readout: getComputedStyle(root.querySelector('.ui-readout')).gridTemplateColumns.split(' ').length,
            actions: getComputedStyle(root.querySelector('ui-actions')).flexDirection,
          }];
        }))""")
        browser.close()

    assert result["narrow"] == {"form": "column", "readout": 1, "actions": "column"}, result
    assert result["wide"] == {"form": "row", "readout": 2, "actions": "row"}, result


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
