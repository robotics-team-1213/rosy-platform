"""D-641: 실제 갤러리에서 의미·이름·선택·설명과 공용 누름면을 확인한다."""

from pathlib import Path
import re

import pytest
from browser_harness import browser_tests_enabled

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="ROSY_RUN_BROWSER_TESTS=1 필요")
ROOT = Path(__file__).resolve().parents[3]
COMMON = ROOT / "shared/web"
GALLERY = ROOT / "middleware/robot_ui/robot"
HOST = "http://rosy.test"
ICONS = ["fleet", "map", "install", "cell", "notification", "history", "tools", "refresh", "download", "connect",
         "login", "account", "logout"]
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
    page.mouse.move(0, 0)
    assert not tooltip.is_visible()
    page.keyboard.press("Tab")
    assert page.get_by_role("tab", name="기록", exact=True).evaluate("node => node === document.activeElement")
    assert tooltip.inner_text() == "기록"
    page.keyboard.press("ArrowRight")
    tools = page.get_by_role("tab", name="운영 도구", exact=True)
    assert tools.get_attribute("aria-selected") == "true"
    assert tools.evaluate("node => node === document.activeElement")
    assert page.locator("#icon-history-panel").is_hidden()
    assert page.locator("#icon-tools-panel").is_visible()
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
    box = tooltip.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
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


def test_focused_description_does_not_block_another_control(page):
    page.goto(f"{HOST}/styleguide")
    page.wait_for_function("() => document.querySelector('.icon-inventory .ui-icon')")
    page.locator("#icon-focus-demo").focus()
    tooltip = page.get_by_role("tooltip")
    tooltip.wait_for(state="visible")
    box = tooltip.bounding_box()
    description = tooltip.text_content()
    page.evaluate("""box => {
      const button = document.createElement('button');
      button.id = 'under-description'; button.textContent = 'Read next item';
      button.dataset.uiTooltip = 'A different underlying description';
      Object.assign(button.style, {position: 'fixed', left: `${box.x}px`, top: `${box.y}px`,
        width: `${box.width}px`, height: `${box.height}px`});
      button.addEventListener('click', () => button.dataset.clicked = 'yes');
      document.body.append(button);
    }""", box)
    control = page.locator("#under-description")
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    assert tooltip.is_visible()
    assert tooltip.text_content() == description
    control.click()
    assert control.get_attribute("data-clicked") == "yes"


@pytest.mark.parametrize("mutation", ["node.hidden = true", "node.remove()"])
def test_tooltip_closes_when_its_owner_leaves_the_visible_surface(page, mutation):
    page.goto(f"{HOST}/styleguide")
    page.wait_for_function("() => document.querySelector('.icon-inventory .ui-icon')")
    owner = page.locator(".icon-inventory [data-action-icon='connect']")
    owner.hover()
    tooltip = page.get_by_role("tooltip")
    tooltip.wait_for(state="visible")
    described = tooltip.text_content()
    owner.evaluate(f"node => {{ {mutation}; }}")
    # Removing the owner slides the next inventory button under the resting pointer, and Chromium may hover it:
    # the old description must be gone, while the neighbour may show its own.
    page.wait_for_function("""text => { const tip = document.querySelector("[role=tooltip]");
      return !tip || tip.hidden || tip.textContent !== text; }""", arg=described)


@pytest.mark.parametrize("activation", ["mouse", "Enter", "Space"])
def test_activation_dismisses_description_until_focus_moves_and_next_control_is_reachable(page, activation):
    page.goto(f"{HOST}/styleguide")
    page.wait_for_function("() => document.querySelector('.icon-inventory .ui-icon')")
    owner = page.locator("#icon-focus-demo")
    owner.focus()
    tooltip = page.get_by_role("tooltip")
    tooltip.wait_for(state="visible")
    if activation == "mouse":
        owner.click()
    else:
        page.keyboard.press(activation)
    tooltip.wait_for(state="hidden")
    assert owner.evaluate("node => node === document.activeElement")
    assert owner.get_attribute("aria-describedby") is None
    # 누른 조작에 포커스가 남아도 포인터 재진입으로 설명이 다시 떠서는 안 된다.
    page.mouse.move(0, 0)
    owner.hover()
    assert not tooltip.is_visible()
    next_control = page.locator(".icon-inventory [data-action-icon='connect']")
    next_control.evaluate("node => node.addEventListener('click', () => node.dataset.clicked = 'true')")
    next_control.click()
    assert next_control.get_attribute("data-clicked") == "true"
    owner.focus()
    tooltip.wait_for(state="visible")


def test_existing_sr_only_and_css_hidden_icons_keep_names_and_get_keyboard_descriptions(page):
    page.goto(f"{HOST}/styleguide")
    page.wait_for_function("() => document.querySelector('.icon-inventory .ui-icon')")
    source = (ROOT / "applications/fleet/web/index.html").read_text(encoding="utf-8")
    # 실제 단독 아이콘 조작의 마크업을 재사용한다. 상태 센터는 별도 구성 조작이다.
    snippets = [re.search(rf'<ui-button\b[^>]*\b{attribute}="{value}"[^>]*>.*?</ui-button>', source, re.S).group()
                for attribute, value in [("id", "fleet-theme"), ("id", "vision-refresh")]]
    page.evaluate("""async markup => {
      const {actionIcon} = await import('/common/ui.js');
      const stage = document.createElement('div'); stage.id = 'existing-icons';
      stage.innerHTML = markup.join(''); document.body.append(stage);
      for (const button of stage.querySelectorAll('ui-button')) actionIcon(button, button.dataset.actionIcon);
    }""", snippets)
    tooltip = page.get_by_role("tooltip")
    for snippet, (name, target) in zip(snippets, [
            ("테마 변경", "#fleet-theme"), ("영상 새로고침", "#vision-refresh")], strict=True):
        control = page.locator(f"#existing-icons {target}")
        assert control.get_attribute("data-ui-tooltip") == name
        assert page.get_by_role("button", name=name, exact=True).count() == 1
        control.focus()
        tooltip.wait_for(state="visible")
        assert tooltip.inner_text() == name
        assert control.get_attribute("aria-describedby") == "rosy-shared-tooltip"
        assert control.get_attribute("data-icon-only") == ("" if 'data-icon-only=""' in snippet else None)
        assert control.evaluate("node => getComputedStyle(node).minHeight") == "48px"
    assert page.locator("#existing-icons #fleet-theme").get_attribute("aria-pressed") is None
    fallback = page.evaluate("""async () => {
      const {actionIcon} = await import('/common/ui.js');
      const button = document.createElement('button'); button.setAttribute('aria-label', '접속 확인');
      actionIcon(button, 'connect');
      const automatic = button.dataset.uiTooltip;
      button.dataset.uiTooltip = '별도 접속 설명'; button.title = '기존 설명'; actionIcon(button, 'connect');
      return {automatic, explicit: button.dataset.uiTooltip, label: button.getAttribute('aria-label')};
    }""")
    assert fallback == {"automatic": "접속 확인", "explicit": "별도 접속 설명", "label": "접속 확인"}
