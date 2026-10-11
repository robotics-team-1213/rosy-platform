"""D-641: 실제 갤러리에서 의미·이름·선택·설명과 공용 누름면을 확인한다."""

from pathlib import Path

import pytest
from browser_harness import browser_tests_enabled

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="ROSY_RUN_BROWSER_TESTS=1 필요")
ROOT = Path(__file__).resolve().parents[3]
COMMON = ROOT / "shared/web"
GALLERY = ROOT / "middleware/ui/robot"
HOST = "http://rosy.test"
ICONS = ["fleet", "map", "install", "cell", "notification", "history", "tools", "refresh", "download", "connect"]
TYPES = {".html": "text/html", ".css": "text/css", ".js": "application/javascript"}


def serve(route):
    path = route.request.url.removeprefix(HOST).split("?", 1)[0]
    target = COMMON / path.removeprefix("/common/") if path.startswith("/common/") else (
        GALLERY / "styleguide.html" if path == "/styleguide" else
        GALLERY / path.removeprefix("/styleguide/assets/"))
    if not target.is_file():
        return route.fulfill(status=404, body="")
    route.fulfill(status=200, content_type=TYPES.get(target.suffix, "text/plain"), body=target.read_text(encoding="utf-8"))


@pytest.fixture
def page():
    api = pytest.importorskip("playwright.sync_api")
    with api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        context.route(f"{HOST}/**", serve)
        yield context.new_page()
        browser.close()


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("width,height", [(1920, 1080), (1366, 768), (390, 844), (320, 568)])
def test_catalog_names_geometry_states_and_keyboard_tooltip(page, theme, width, height):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{HOST}/styleguide")
    page.wait_for_function("() => document.querySelector('.icon-inventory .ui-icon')")
    page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
    inventory = page.locator(".icon-inventory [data-action-icon]")
    assert inventory.evaluate_all("nodes => nodes.map(node => node.dataset.actionIcon)") == ICONS
    metrics = inventory.evaluate_all("""nodes => nodes.map(node => ({
      height: node.getBoundingClientRect().height,
      font: getComputedStyle(node).fontSize,
      inset: getComputedStyle(node).paddingLeft,
      paths: node.querySelectorAll('.ui-icon path').length,
      hidden: node.querySelector('.ui-icon').getAttribute('aria-hidden'),
      name: node.querySelector('.ui-icon-label').textContent.trim(),
    }))""")
    assert all(item["height"] >= 48 and item["font"] == "14px" and item["inset"] == "12px"
               and item["paths"] > 0 and item["hidden"] == "true" and item["name"] for item in metrics)
    link = page.get_by_role("link", name="관제", exact=True)
    assert link.get_attribute("aria-current") == "page"
    assert page.get_by_role("tab", name="기록", exact=True).get_attribute("aria-selected") == "true"
    assert page.get_by_role("button", name="알림 보기", exact=True).get_attribute("aria-pressed") == "true"
    disabled = page.locator(".icon-states [disabled]")
    assert disabled.get_attribute("aria-disabled") == "true"
    assert disabled.locator("small[data-reason]").inner_text() == "이 견본에는 내보낼 결과가 없습니다"
    link.focus()
    tooltip = page.get_by_role("tooltip")
    tooltip.wait_for(state="visible")
    assert tooltip.inner_text() == "관제"
    assert link.get_attribute("aria-describedby") == "rosy-shared-tooltip"
    assert link.evaluate("node => node.contains(document.querySelector('.ui-tooltip'))") is False
    box = tooltip.bounding_box()
    assert 0 <= box["x"] and box["x"] + box["width"] <= width
    assert 0 <= box["y"] and box["y"] + box["height"] <= height
    page.keyboard.press("Escape")
    assert not tooltip.is_visible()
    assert link.get_attribute("aria-describedby") is None
    assert link.get_attribute("aria-current") == "page"
    page.keyboard.press("Tab")
    assert page.get_by_role("tab", name="기록", exact=True).evaluate("node => node === document.activeElement")
    assert tooltip.inner_text() == "기록"
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert not errors


def test_hover_description_is_hoverable_dismissible_and_preserves_other_evidence(page):
    page.goto(f"{HOST}/styleguide")
    page.wait_for_function("() => document.querySelector('.icon-inventory .ui-icon')")
    refresh = page.locator("#icon-focus-demo")
    refresh.evaluate("node => node.setAttribute('aria-describedby', 'other-evidence')")
    refresh.hover()
    tooltip = page.get_by_role("tooltip")
    tooltip.wait_for(state="visible")
    assert "현재 내용 다시 조회" in tooltip.inner_text()
    assert set(refresh.get_attribute("aria-describedby").split()) == {"other-evidence", "rosy-shared-tooltip"}
    tooltip.hover()
    assert tooltip.is_visible()
    page.keyboard.press("Escape")
    assert not tooltip.is_visible()
    assert refresh.get_attribute("aria-describedby") == "other-evidence"
    assert refresh.get_attribute("data-action-icon") == "refresh"
    rejected = page.evaluate("""async () => {
      const {actionIcon} = await import('/common/ui.js');
      const button = document.createElement('button'); button.dataset.iconOnly = '';
      try { actionIcon(button, 'refresh'); return false; } catch (error) { return error instanceof TypeError; }
    }""")
    assert rejected
