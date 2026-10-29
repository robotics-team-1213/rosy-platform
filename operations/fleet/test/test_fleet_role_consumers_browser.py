"""Measure shared role styles on the actual Fleet consumers; no device writes."""

from urllib.parse import urlparse
import re

import pytest
from browser_harness import browser_tests_enabled
from fleet.server.development_session import DevelopmentSessions
from test_fleet_header_browser import _api, _fleet

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in Chromium acceptance")
SIZES = [(1920, 1080), (1366, 768), (390, 844), (320, 568)]


def _assert_control(control):
    from playwright.sync_api import expect
    # Roster refresh replaces controls; locator assertions re-resolve the live element.
    expect(control).to_have_css("height", re.compile(r"^(?:4[89]|[5-9]\d|[1-9]\d{2,})(?:\.\d+)?px$"))
    expect(control).to_have_css("font-size", "14px")
    expect(control).to_have_css("padding-left", "12px")
    expect(control).to_have_css("padding-right", "12px")


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_fleet_role_styles_reach_fields_disclosures_and_headings(tmp_path, theme):
    from playwright.sync_api import expect

    api = _api()
    api["/api/fleet/state"]["robots"][2]["link"] = "tls-refused"
    api["/api/fleet/enrollment/robots"] = {"available": True, "robots": [], "static_robot_ids": [], "alarms": []}
    writes = []
    with _fleet(tmp_path, console_token="registry-only", development_sessions=DevelopmentSessions()) as (browser, origin):
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def serve(route):
            path = urlparse(route.request.url).path
            if route.request.method == "GET" and path in api:
                route.fulfill(json=api[path])
            elif route.request.method != "GET" and "/auth/" not in path:
                writes.append(path)
                route.fulfill(status=409, json={"detail": "consumer test: no writes"})
            else:
                route.continue_()

        page.route("**/api/**", serve)
        for path in ["/console", "/console/install", "/console/site-map", "/console/cell"]:
            page.goto(origin + path)
            expect(page.locator("#user-role")).to_have_text("운영자", timeout=15000)
            page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
            if path == "/console":
                page.locator("#robot-choice").select_option("rosy_03")
            for width, height in SIZES:
                page.set_viewport_size({"width": width, "height": height})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (path, width)
                _assert_control(page.locator("#topbar-more"))
                if path == "/console":
                    _assert_control(page.locator(".queue-row").first)
                    # Current roster opens one selected robot's controls in its workspace.
                    page.locator('[data-select-robot-id="rosy_03"]').click()
                    _assert_control(page.locator("[data-auth-focus]"))
                    page.locator("[data-auth-focus]").click()
                    expect(page.locator("#console-token")).to_be_focused()
                    if page.locator("#topbar-more").is_visible():
                        page.locator("#topbar-more").click()
                    page.locator("#context-inbox-tab").click()
                    summary = page.locator("#log-panel > summary")
                    for opened in [False, True]:
                        page.locator("#log-panel").evaluate("(node, open) => node.open = open", opened)
                        _assert_control(summary)
                    page.locator("#context-status-tab").click()
                elif path == "/console/install":
                    chooser = page.locator(".ui-task-compact select")
                    if chooser.is_visible():
                        chooser.select_option("robots")
                    else:
                        page.get_by_role("tab", name="로봇 등록", exact=True).click()
                    # Only reveal the existing form to measure its paint; no enrollment request.
                    expect(page.locator("#enroll-controls")).to_be_visible()
                    page.locator("#enroll-dialog").evaluate("node => node.showModal()")
                    expect(page.locator("#enroll-code")).to_be_visible()
                    field = page.locator("#enroll-code")
                    assert field.evaluate("node => getComputedStyle(node).paddingLeft") == "12px"
                    assert field.evaluate("node => getComputedStyle(node).borderRadius") == "6px"
                    page.locator("#enroll-dialog").evaluate("node => node.close()")
                    if chooser.is_visible():
                        chooser.select_option("calibration")
                    else:
                        page.get_by_role("tab", name="카메라 설치·보정", exact=True).click()
                    page.locator("#field-options").evaluate("node => node.open = true")
                    for field_id in ["#field-width", "#field-height"]:
                        field = page.locator(field_id)
                        expect(field).to_be_visible()
                        assert field.evaluate("node => getComputedStyle(node).paddingLeft") == "12px"
                        assert field.evaluate("node => getComputedStyle(node).borderRadius") == "6px"
                else:
                    expect(page.get_by_role("heading", level=1)).to_have_count(1)
                    assert page.get_by_role("heading", level=1).evaluate("node => getComputedStyle(node).fontSize") == "20px"
                    assert page.locator("h2.ui-section-heading").evaluate_all(
                        "nodes => nodes.length > 0 && nodes.every(node => getComputedStyle(node).fontSize === '16px')")
                    if path == "/console/site-map":
                        expect(page.get_by_role("heading", name="지도 설정", exact=True)).to_have_count(1)
                        page.evaluate("location.hash = '#profile-heading'")  # D-926 3: one sub-nav screen at a time
                        _assert_control(page.locator("#profile-file").locator("xpath=ancestor::details/summary"))
                    summary = page.locator("main summary.ui-disclosure-row").first
                    for opened in [False, True]:
                        summary.evaluate("(node, open) => node.parentElement.open = open", opened)
                        _assert_control(summary)
        assert not errors, errors
        assert not writes, writes
        page.close()
