"""Native task links retain navigation semantics and the shared control floor."""
from pathlib import Path

import pytest

from browser_harness import browser_tests_enabled


pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="requires explicit Chromium browser run")
COMMON = Path(__file__).resolve().parents[1]
HOST = "http://rosy.test"
PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="/common/tokens.css">
<link rel="stylesheet" href="/common/components.css">
<link rel="stylesheet" href="/common/component-controls.css"></head>
<body><main class="ui-task-page ui-auth-page"><h1>로그인</h1>
<p>로그인 후 원래 작업으로 돌아갑니다.</p>
<a id="next" class="ui-action-link" data-kind="primary" href="/next#destination">
Rosy Account로 로그인하고 진행 중인 학습 작업으로 돌아가기</a>
</main></body></html>"""


def serve(route):
    path = route.request.url.removeprefix(HOST).split("?", 1)[0]
    assets = {f"/common/{name}": COMMON / name for name in
              ("tokens.css", "components.css", "component-controls.css")}
    if path in assets:
        return route.fulfill(content_type="text/css", body=assets[path].read_text(encoding="utf-8"))
    body = PAGE if path == "/start" else '<main id="destination"><h1>원래 작업</h1></main>'
    return route.fulfill(content_type="text/html", body=body)


@pytest.mark.parametrize("width", [320, 1366])
@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("text_scale", [1, 2])
def test_native_task_link_size_focus_reflow_and_keyboard_navigation(width, theme, text_scale):
    api = pytest.importorskip("playwright.sync_api")
    with api.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": width, "height": 844})
            page.route(HOST + "/**", serve)
            page.goto(HOST + "/start")
            page.evaluate("""({theme, scale}) => {
              document.documentElement.dataset.theme = theme;
              document.documentElement.style.fontSize = `${16 * scale}px`;
            }""", {"theme": theme, "scale": text_scale})
            link = page.get_by_role("link", name="Rosy Account로 로그인하고 진행 중인 학습 작업으로 돌아가기")
            bounds = link.bounding_box()
            assert bounds and bounds["height"] >= 48 and bounds["width"] >= 48
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert link.evaluate("""e => {
              const probe = document.createElement('span');
              probe.style.backgroundColor = 'var(--button-primary-bg)';
              document.body.append(probe);
              const matches = getComputedStyle(e).backgroundColor === getComputedStyle(probe).backgroundColor;
              probe.remove();
              return matches;
            }""")
            page.keyboard.press("Tab")
            api.expect(link).to_be_focused()
            assert link.evaluate("e => getComputedStyle(e).outlineStyle") == "solid"
            page.keyboard.press("Enter")
            api.expect(page).to_have_url(HOST + "/next#destination")
            api.expect(page.get_by_role("heading", name="원래 작업")).to_be_visible()
        finally:
            browser.close()
