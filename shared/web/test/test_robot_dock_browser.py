"""Chromium behavior tests for shared C23 robot-dock & C18 selection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from browser_harness import browser_tests_enabled

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in Chromium scenario")
WEB = Path(__file__).resolve().parents[1]
HOST = "http://rosy.test"


@pytest.fixture
def dock_gallery():
    from playwright.sync_api import sync_playwright, expect

    assets = json.loads((WEB / "shared-assets.json").read_text(encoding="utf-8"))["shared_assets"]

    def serve(route):
        name = route.request.url.split("/common/", 1)[-1].split("?", 1)[0]
        if name not in assets:
            return route.fulfill(status=404, body="not registered")
        route.fulfill(path=str(WEB / name), content_type=assets[name])

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1366, "height": 768})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route(HOST + "/**", serve)
        response = page.goto(HOST + "/common/component-gallery.html")
        assert response.status == 200
        expect(page.locator("#kit-ready")).to_have_text("견본 준비 완료")
        page.evaluate("""async () => {
          for (const href of ['/common/choice-controls.css', '/common/robot-dock.css']) {
            if (!document.querySelector(`link[href="${href}"]`)) {
              const link = document.createElement('link');
              link.rel = 'stylesheet';
              link.href = href;
              document.head.append(link);
              await new Promise((resolve) => { link.onload = resolve; link.onerror = resolve; });
            }
          }
          const host = document.createElement('section');
          host.id = 'dock-test-stage';
          host.className = 'robot-stage';
          document.querySelector('main').prepend(host);
          const { createSelection } = await import('/common/selection.js');
          const { createRobotDock } = await import('/common/robot-dock.js');
          const { createRobotPanel } = await import('/common/robot-panel.js');
          const { robotProfile } = await import('/common/robot-profile.js');
          const profiles = [
            robotProfile({ id: 'rosy_01', name: '1호기', kind: 'mobile', online: true, evidence: 'fresh', battery: { percent: 82 }, alarm: { level: 'caution', text: '주의' } }),
            robotProfile({ id: 'rosy_02', name: '2호기', kind: 'mobile', online: true, evidence: 'fresh', battery: { percent: 65 } }),
            robotProfile({ id: 'arm_a', name: 'OMX A', kind: 'arm', online: true, evidence: 'fresh' }),
            robotProfile({ id: 'arm_b', name: 'OMX B', kind: 'arm', online: false, evidence: 'disconnected' }),
          ];
          const byId = new Map(profiles.map((p) => [p.id, p]));
          const selection = createSelection(null);
          let openId = null;
          let panel = null;
          const dock = createRobotDock({
            selection,
            profiles,
            onToggle: (id) => {
              openId = id;
              selection.set(id, { source: 'dock' });
              dock.setOpen(id);
              panel.setRobot(id ? byId.get(id) : null);
            },
          });
          panel = createRobotPanel({
            selection,
            onClose: () => {
              openId = null;
              dock.setOpen(null);
            },
            sections: {
              status: (p) => {
                const el = document.createElement('p');
                el.textContent = `${p.name} (${p.kindLabel})`;
                return el;
              },
              manual: (p) => (p.kind === 'mobile' ? Object.assign(document.createElement('p'), { textContent: '수동 조종' }) : null),
              commands: (p) => (p.kind === 'arm' ? Object.assign(document.createElement('p'), { textContent: '팔 명령' }) : null),
            },
          });
          const mainCol = document.createElement('div');
          mainCol.className = 'robot-stage-main';
          host.append(panel.root, mainCol, dock.root);
          window.__dockDemo = { selection, dock, panel, profiles };
        }""")
        yield page
        assert not errors, errors
        browser.close()


def test_robot_dock_desktop_rail_keyboard_and_toggle(dock_gallery):
    from playwright.sync_api import expect

    page = dock_gallery
    dock = page.locator("#dock-test-stage .robot-dock")
    panel = page.locator("#dock-test-stage .robot-panel")
    buttons = dock.locator(".robot-dock-btn")
    assert buttons.count() >= 4

    # Desktop rail sits as a vertical 56px strip with >=48px button width.
    boxes = buttons.evaluate_all("nodes => nodes.map(n => n.getBoundingClientRect().toJSON())")
    assert all(b["width"] >= 48 and b["height"] >= 44 for b in boxes)

    # First click opens the panel and reflects both selected + open states.
    first = buttons.nth(0)
    first_id = first.get_attribute("data-robot-id")
    first.click()
    expect(panel).to_be_visible()
    expect(panel).to_have_attribute("data-robot-id", first_id)
    expect(first).to_have_attribute("aria-pressed", "true")
    expect(first).to_have_attribute("data-selected", "")

    # ArrowDown / End / Home move roving focus without accidental toggle, Enter/click switches robot.
    first.focus()
    page.keyboard.press("ArrowDown")
    second = buttons.nth(1)
    expect(second).to_be_focused()
    second_id = second.get_attribute("data-robot-id")
    page.keyboard.press("End")
    expect(buttons.last).to_be_focused()
    page.keyboard.press("Home")
    expect(first).to_be_focused()

    # Clicking a second robot switches the panel while clearing open on the first.
    second.click()
    expect(panel).to_have_attribute("data-robot-id", second_id)
    expect(second).to_have_attribute("aria-pressed", "true")
    expect(first).to_have_attribute("aria-pressed", "false")

    # Clicking the already open dock button closes the panel cleanly.
    second.click()
    expect(panel).to_be_hidden()
    expect(second).to_have_attribute("aria-pressed", "false")


@pytest.mark.parametrize("width", [390, 320])
def test_robot_dock_mobile_horizontal_bar_and_no_overflow(dock_gallery, width):
    from playwright.sync_api import expect

    page = dock_gallery
    page.set_viewport_size({"width": width, "height": 844})
    dock = page.locator("#dock-test-stage .robot-dock")
    panel = page.locator("#dock-test-stage .robot-panel")
    buttons = dock.locator(".robot-dock-btn")

    boxes = buttons.evaluate_all("nodes => nodes.map(n => n.getBoundingClientRect().toJSON())")
    assert all(b["height"] >= 44 and b["width"] >= 44 for b in boxes)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")

    buttons.first.click()
    expect(panel).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    assert page.evaluate("() => { const t = document.getElementById('rosy-shared-tooltip'); return !t || t.hidden || getComputedStyle(t).display === 'none' || !t.textContent.trim(); }")
    dock_box = dock.bounding_box()
    panel_box = panel.bounding_box()
    assert dock_box and panel_box
    assert dock_box["y"] + dock_box["height"] <= panel_box["y"] + 1

    # Arm profile shows OMX commands and hides mobile manual section.
    arm_btn = dock.locator('.robot-dock-btn[data-kind="arm"]').first
    if arm_btn.count() > 0:
        arm_btn.click()
        expect(panel).to_have_attribute("data-kind", "arm")
        assert panel.locator('details[data-section="manual"]').count() == 0
