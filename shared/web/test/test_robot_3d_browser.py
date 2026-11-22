"""Chromium behavior tests for shared C15 robot-3d view (mobile & arm models, presets, dispose)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from browser_harness import browser_tests_enabled, launch_options

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in Chromium scenario")
WEB = Path(__file__).resolve().parents[1]
HOST = "http://rosy.test"


@pytest.fixture
def view_gallery():
    from playwright.sync_api import sync_playwright, expect

    assets = json.loads((WEB / "shared-assets.json").read_text(encoding="utf-8"))["shared_assets"]

    def serve(route):
        name = route.request.url.split("/common/", 1)[-1].split("?", 1)[0]
        if name not in assets:
            return route.fulfill(status=404, body="not registered")
        route.fulfill(path=str(WEB / name), content_type=assets[name])

    with sync_playwright() as pw:
        opts = launch_options()
        opts["args"] = [
            "--use-gl=angle",
            "--use-angle=swiftshader",
            "--enable-webgl",
            "--ignore-gpu-blocklist",
        ]
        browser = pw.chromium.launch(**opts)
        page = browser.new_page(viewport={"width": 1366, "height": 768})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route(HOST + "/**", serve)
        response = page.goto(HOST + "/common/component-gallery.html")
        assert response.status == 200
        expect(page.locator("#kit-ready")).to_have_text("견본 준비 완료")
        yield page
        assert not errors, errors
        browser.close()


def test_robot_3d_view_mounts_mobile_and_arm_updates_presets_and_disposes(view_gallery):
    from playwright.sync_api import expect

    page = view_gallery
    ready_mobile = page.evaluate("""async () => {
      const host = document.createElement('div');
      host.id = 'test-3d-host';
      document.querySelector('main').prepend(host);
      const { createRobotView } = await import('/common/robot-3d.js');
      const v = createRobotView(host, {
        kind: 'mobile',
        robotId: 'rosy_01',
        name: '1호기',
        selected: true,
        pose: { x: 0.25, y: 0.15, yaw: 0.5 },
      });
      window.__v3d = v;
      return await v.ready;
    }""")
    fig = page.locator("#test-3d-host .robot-view")
    expect(fig).to_be_visible()
    assert fig.get_attribute("data-state") in ("ready", "fallback")
    assert isinstance(ready_mobile, bool)
    page.locator('#test-3d-host [data-preset="top"]').click()
    expect(page.locator('#test-3d-host [data-preset="top"]')).to_have_attribute("aria-pressed", "true")

    ready_arm = page.evaluate("""async () => {
      window.__v3d.dispose();
      const host = document.getElementById('test-3d-host');
      const { createRobotView } = await import('/common/robot-3d.js');
      const arm = createRobotView(host, {
        kind: 'arm',
        robotId: 'arm_a',
        name: 'OMX A',
        selected: true,
      });
      window.__v3d = arm;
      return await arm.ready;
    }""")
    assert isinstance(ready_arm, bool)
    expect(fig).to_have_attribute("data-kind", "arm")
    expect(fig).to_have_attribute("data-pose", "unverified")
    expect(page.locator("#test-3d-host .robot-view-badge")).to_be_visible()
    assert "자세 미확인" in page.locator("#test-3d-host .robot-view-badge").inner_text()
    page.evaluate("() => window.__v3d.setState({ joints: { joint1: 0.5, joint2: -0.2, joint3: 0.4 } })")
    expect(fig).to_have_attribute("data-pose", "live")
    expect(page.locator("#test-3d-host .robot-view-badge")).to_be_hidden()
    assert "OMX A" in page.locator("#test-3d-host .robot-view-summary").inner_text()
    page.evaluate("() => window.__v3d.dispose()")
