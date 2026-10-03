"""D-359 §2.4·§2.5 — theme.js가 실제 표면 HTML에서 첫 그림 전에 테마를 정하고,
선택 UI가 살아 있는 페이지의 테마를 바꾸는지 Chromium으로 확인한다.

표면 파일은 가짜 호스트(`http://rosy.test`)로 그대로 서빙한다 — 서버 없이
`<head>` 순서(tokens.css → theme.js)와 CSP와 같은 외부 스크립트 경로를 그대로 탄다.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import token_themes

pytestmark = pytest.mark.skipif(
    os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
    reason="set ROSY_RUN_BROWSER_TESTS=1 to run the optional Chromium regression",
)

SRC = Path(__file__).resolve().parents[3]
COMMON = SRC / "hmi" / "web_common"
DASHBOARD = SRC / "hmi" / "dashboard"
FLEET = SRC.parent / "operations" / "fleet" / "fleet" / "server" / "web"
HOST = "http://rosy.test"
PALETTES = token_themes.palettes(token_themes.read())
TYPES = {".css": "text/css", ".js": "application/javascript", ".html": "text/html"}
PANEL_PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<link rel="stylesheet" href="/common/tokens.css">
<script src="/common/theme.js"></script>
<link rel="stylesheet" href="/common/components.css">
<link rel="stylesheet" href="/assets/shell/shell.css">
<script type="module" src="/common/ui.js"></script></head>
<body data-surface="device"><main><ui-section id="panel"></ui-section></main></body></html>"""
PINNED_PAGE = """<!doctype html><html lang="ko" data-theme="dark" data-theme-pin="dark"><head>
<link rel="stylesheet" href="/common/tokens.css">
<script src="/common/theme.js"></script></head><body></body></html>"""


def _rgb(hex_colour: str) -> str:
    raw = hex_colour.lstrip("#")
    return "rgb({}, {}, {})".format(*(int(raw[i:i + 2], 16) for i in (0, 2, 4)))


def _serve(route):
    path = route.request.url.removeprefix(HOST).split("?", 1)[0]
    if path.startswith("/common/"):
        target = COMMON / path.removeprefix("/common/")
    elif path.startswith("/console/assets/"):
        target = FLEET / path.removeprefix("/console/assets/")
    elif path.startswith("/assets/"):
        target = DASHBOARD / path.removeprefix("/assets/")
    elif path == "/console":
        target = FLEET / "index.html"
    elif path == "/surface":
        target = DASHBOARD / "surface.html"
    elif path == "/panel":
        return route.fulfill(status=200, content_type="text/html", body=PANEL_PAGE)
    elif path == "/pinned":
        return route.fulfill(status=200, content_type="text/html", body=PINNED_PAGE)
    else:
        return route.fulfill(status=404, body="")
    if not target.is_file():
        return route.fulfill(status=404, body="")
    return route.fulfill(status=200, content_type=TYPES.get(target.suffix, "text/plain"),
                         body=target.read_text(encoding="utf-8"))


@pytest.fixture()
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as playwright:
        try:
            launched = playwright.chromium.launch(headless=True)
        except Exception as error:  # pragma: no cover - host without Chromium
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        yield launched
        launched.close()


def _open(browser, path: str, *, stored: str | None = None, scheme: str = "dark", broken_storage=False):
    context = browser.new_context(viewport={"width": 1366, "height": 768}, color_scheme=scheme)
    if stored is not None:
        context.add_init_script(f"try {{ localStorage.setItem('rosy.theme', {stored!r}); }} catch (e) {{}}")
    if broken_storage:
        context.add_init_script(
            "Object.defineProperty(window, 'localStorage', {get() { throw new Error('denied'); }});")
    context.add_init_script(
        "window.__themeEvents = [];"
        "document.addEventListener('rosy:theme', (e) => window.__themeEvents.push(e.detail));")
    page = context.new_page()
    page.route(f"{HOST}/**", _serve)
    page.goto(f"{HOST}{path}", wait_until="domcontentloaded")
    return page


def _state(page) -> dict:
    return page.evaluate("""() => ({
      theme: document.documentElement.dataset.theme,
      meta: document.querySelector('meta[name="theme-color"]')?.content || null,
      metas: document.querySelectorAll('meta[name="theme-color"]').length,
      body: getComputedStyle(document.body).backgroundColor,
      scheme: getComputedStyle(document.documentElement).colorScheme,
      preference: window.RosyTheme && window.RosyTheme.get(),
      resolved: window.RosyTheme && window.RosyTheme.resolved(),
      events: window.__themeEvents,
    })""")


@pytest.mark.parametrize("path", ["/console", "/surface"])
def test_a_stored_light_preference_paints_light_before_any_script_module(browser, path):
    page = _open(browser, path, stored="light")
    state = _state(page)
    light = PALETTES["light"]["ground"]
    assert state["theme"] == "light"
    assert state["body"] == _rgb(light)
    assert state["meta"] == light and state["metas"] == 1
    assert state["scheme"] == "light"
    assert (state["preference"], state["resolved"]) == ("light", "light")
    assert state["events"] == []  # 첫 결정은 변화가 아니다


@pytest.mark.parametrize("stored, broken", [(None, False), ("sepia", False), ("light", True)])
def test_missing_invalid_or_unreadable_preference_falls_back_to_dark(browser, stored, broken):
    page = _open(browser, "/console", stored=stored, broken_storage=broken, scheme="light")
    state = _state(page)
    dark = PALETTES["dark"]["ground"]
    assert state["theme"] == "dark"
    assert state["body"] == _rgb(dark)
    assert state["meta"] == dark


def test_system_follows_the_device_and_changes_live(browser):
    page = _open(browser, "/console", stored="system", scheme="light")
    assert _state(page)["theme"] == "light"
    page.emulate_media(color_scheme="dark")
    page.wait_for_function("document.documentElement.dataset.theme === 'dark'")
    state = _state(page)
    assert state["meta"] == PALETTES["dark"]["ground"]
    assert state["events"][-1] == {"theme": "dark", "preference": "system"}


def test_a_pinned_surface_ignores_the_preference(browser):
    page = _open(browser, "/pinned", stored="light", scheme="light")
    state = _state(page)
    assert state["theme"] == "dark"
    assert state["resolved"] == "dark"
    assert state["meta"] == PALETTES["dark"]["ground"]  # theme.js가 없던 meta를 만든다


def test_the_fleet_topbar_selector_switches_the_theme_live(browser):
    page = _open(browser, "/console")
    page.wait_for_function("customElements.get('ui-button') !== undefined")
    assert page.locator('[data-theme-choice="dark"]').get_attribute("aria-pressed") == "true"
    # D-359 §6.4 — 1366px(90rem 미만)에서 테마 선택은 머리의 '설정' 뒤에 접힌다. 이 고정물은
    # 세션이 없어 잠기므로(토큰 칸이 저절로 열린다) 닫혀 있을 때만 연다.
    if page.locator("#theme-choice").is_hidden():
        page.get_by_role("button", name="설정", exact=True).click()
    page.locator("#theme-choice").get_by_text("밝게", exact=True).click()
    page.wait_for_function("document.documentElement.dataset.theme === 'light'")
    state = _state(page)
    light = PALETTES["light"]["ground"]
    assert state["body"] == _rgb(light) and state["meta"] == light
    assert state["events"] == [{"theme": "light", "preference": "light"}]
    assert page.locator('[data-theme-choice="light"]').get_attribute("aria-pressed") == "true"
    assert page.locator('[data-theme-choice="dark"]').get_attribute("aria-pressed") == "false"
    assert page.evaluate("localStorage.getItem('rosy.theme')") == "light"
    page.reload(wait_until="domcontentloaded")
    assert _state(page)["theme"] == "light"


def test_the_device_display_panel_switches_the_theme_live(browser):
    page = _open(browser, "/panel", stored="system", scheme="dark")
    page.evaluate("""async () => {
      const {mount} = await import('/assets/panels/system/display.js');
      mount(document.getElementById('panel'), {role: 'administrator'});
    }""")
    group = page.get_by_role("group", name="화면 테마")
    assert group.locator('[aria-pressed="true"]').inner_text() == "시스템"
    assert [text.strip() for text in group.locator("ui-button").all_inner_texts()] == ["어둡게", "밝게", "시스템"]
    group.get_by_text("밝게", exact=True).click()
    page.wait_for_function("document.documentElement.dataset.theme === 'light'")
    assert _state(page)["body"] == _rgb(PALETTES["light"]["ground"])
    group.get_by_text("어둡게", exact=True).click()
    page.wait_for_function("document.documentElement.dataset.theme === 'dark'")
    assert page.evaluate("localStorage.getItem('rosy.theme')") == "dark"
