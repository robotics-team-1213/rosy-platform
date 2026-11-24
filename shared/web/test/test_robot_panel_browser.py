"""Chromium behavior tests for shared C24 robot-panel (in-place updates, disclosure, stop slot)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from browser_harness import browser_tests_enabled

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in Chromium scenario")
WEB = Path(__file__).resolve().parents[1]
FLEET_WEB = Path(__file__).resolve().parents[3] / "applications/fleet/web"
HOST = "http://rosy.test"


@pytest.fixture
def panel_gallery():
    from playwright.sync_api import sync_playwright, expect

    assets = json.loads((WEB / "shared-assets.json").read_text(encoding="utf-8"))["shared_assets"]
    fleet_assets = json.loads((FLEET_WEB / "assets.json").read_text(encoding="utf-8"))["assets"]

    def serve(route):
        url = route.request.url.split("?", 1)[0]
        if "/console/assets/" in url:
            name = url.split("/console/assets/", 1)[-1]
            if name not in fleet_assets:
                return route.fulfill(status=404, body="not registered")
            entry = fleet_assets[name]
            return route.fulfill(path=str(FLEET_WEB / entry["path"]), content_type=entry["media_type"])
        name = url.split("/common/", 1)[-1]
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
          for (const href of ['/console/assets/roster.css']) {
            if (!document.querySelector(`link[href="${href}"]`)) {
              const link = document.createElement('link');
              link.rel = 'stylesheet';
              link.href = href;
              document.head.append(link);
              await new Promise((resolve) => { link.onload = resolve; link.onerror = resolve; });
            }
          }
          const { createSelection } = await import('/console/assets/selection.js');
          const { createRobotPanel } = await import('/console/assets/robot-panel.js');
          const { robotProfile } = await import('/console/assets/robot-profile.js');
          const opener = document.createElement('button');
          opener.id = 'panel-test-opener';
          opener.type = 'button';
          opener.textContent = '패널 열기';
          const stage = document.createElement('div');
          stage.id = 'panel-test-stage';
          stage.className = 'robot-stage';
          const mainCol = document.createElement('div');
          mainCol.className = 'robot-stage-main';
          mainCol.append(opener);

          window.__panelEvents = { collapsed: 0, closed: 0, stopped: [] };
          const statusNode = document.createElement('p');
          statusNode.id = 'panel-status-node';
          const manualNode = document.createElement('div');
          manualNode.id = 'panel-manual-node';
          const manualSelect = document.createElement('select');
          manualSelect.id = 'panel-manual-select';
          manualSelect.innerHTML = '<option value="1">1단</option><option value="2">2단</option>';
          manualNode.append(manualSelect);
          const settingsNode = document.createElement('p');
          settingsNode.id = 'panel-settings-node';
          const commandsNode = document.createElement('p');
          commandsNode.id = 'panel-commands-node';
          commandsNode.textContent = '팔 명령 확인';

          const panel = createRobotPanel({
            selection: createSelection(null),
            onManualCollapse: () => { window.__panelEvents.collapsed += 1; },
            onClose: () => { window.__panelEvents.closed += 1; },
            sections: {
              status: (p) => { statusNode.textContent = `${p.id}:${p.power?.text ?? '-'}`; return statusNode; },
              manual: (p) => (p.kind === 'mobile' ? manualNode : null),
              commands: (p) => (p.kind === 'arm' ? commandsNode : null),
              settings: (p) => { settingsNode.textContent = p.link?.text || ''; return settingsNode; },
            },
            stop: (p) => (p.kind === 'arm'
              ? { note: '팔 단독 정지 없음 · 비상 정지 사용' }
              : { label: '주행 취소 · 이 로봇', onStop: (prof) => window.__panelEvents.stopped.push(prof.id) }),
          });
          panel.root.id = 'test-robot-panel';
          stage.append(panel.root, mainCol);
          document.querySelector('main').prepend(stage);
          window.__panelCtl = { panel, robotProfile };
        }""")
        yield page
        assert not errors, errors
        browser.close()


def test_robot_panel_in_place_updates_collapse_and_focus_return(panel_gallery):
    from playwright.sync_api import expect

    page = panel_gallery
    page.locator("#panel-test-opener").focus()
    page.evaluate("""() => {
      const { panel, robotProfile } = window.__panelCtl;
      panel.setRobot(robotProfile({
        id: 'rosy_01', name: '1호기', kind: 'mobile', online: true, evidence: 'fresh',
        battery: { percent: 82 },
      }));
    }""")

    panel = page.locator("#test-robot-panel")
    expect(panel).to_be_visible()
    expect(panel).to_have_attribute("data-robot-id", "rosy_01")
    manual_details = panel.locator('details[data-section="manual"]')
    settings_details = panel.locator('details[data-section="settings"]')
    assert manual_details.evaluate("node => !node.open")
    assert settings_details.evaluate("node => !node.open")
    assert panel.locator('.robot-panel-jumps button[data-jump-section="manual"]', has_text='수동').count() == 1

    # Open manual disclosure, focus child select, and push a same-ID live update.
    manual_details.locator("summary").click()
    assert manual_details.evaluate("node => node.open")
    page.locator("#panel-manual-select").focus()
    page.evaluate("""() => {
      window.__keptManual = document.getElementById('panel-manual-node');
      const { panel, robotProfile } = window.__panelCtl;
      panel.setRobot(robotProfile({
        id: 'rosy_01', name: '1호기', kind: 'mobile', online: true, evidence: 'fresh',
        battery: { percent: 81 },
      }));
    }""")
    expect(page.locator("#panel-status-node")).to_have_text("rosy_01:81%")
    assert page.evaluate("() => window.__keptManual === document.getElementById('panel-manual-node')")
    assert manual_details.evaluate("node => node.open")
    expect(page.locator("#panel-manual-select")).to_be_focused()

    # Collapsing manual fires onManualCollapse; footer stop button calls onStop.
    manual_details.locator("summary").click()
    page.wait_for_function("() => window.__panelEvents.collapsed === 1")
    panel.locator('.robot-panel-foot ui-button, .robot-panel-foot button', has_text='주행 취소 · 이 로봇').click()
    assert page.evaluate("() => window.__panelEvents.stopped").__eq__(["rosy_01"])

    # Switching to arm updates sections (no manual, has commands, displays footer note).
    page.evaluate("""() => {
      const { panel, robotProfile } = window.__panelCtl;
      panel.setRobot(robotProfile({
        id: 'arm_a', name: 'OMX A', kind: 'arm', online: true, evidence: 'fresh',
      }));
    }""")
    expect(panel).to_have_attribute("data-kind", "arm")
    assert panel.locator('details[data-section="manual"]').count() == 0
    assert panel.locator('#panel-commands-node').count() == 1
    expect(panel.locator('.robot-panel-foot')).to_contain_text('팔 단독 정지 없음')

    # Escape closes panel, calls onClose, and restores focus to opener.
    panel.locator(".robot-panel-close").focus()
    page.keyboard.press("Escape")
    expect(panel).to_be_hidden()
    assert page.evaluate("() => window.__panelEvents.closed === 1")
    expect(page.locator("#panel-test-opener")).to_be_focused()
