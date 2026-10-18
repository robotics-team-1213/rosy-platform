"""Pilot drive reads robot state from /ws/state; the REST poll is only the fallback when the socket is quiet."""

from __future__ import annotations

import json

import pytest
from browser_harness import browser_tests_enabled

from test_pilot_browser import _enter_drive, base_url, playwright_sync  # noqa: F401  (module fixture)


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
def test_drive_skips_rest_state_poll_while_state_socket_is_live(base_url):  # noqa: F811
    stamp = "2026-10-07T06:00:00Z"
    frame = {"type": "state", "mode": "MANUAL", "timestamp": stamp, "velocity": {"linear": 0.12, "angular": 0.1},
             "evidence": {"velocity": {"evidence": "fresh", "received_at": stamp}}}
    polls, sockets = [], []
    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.route("**/api/v1/robot/state", lambda route: (polls.append(1), route.fulfill(json=frame)))

            def status_socket(route):
                sockets.append(route)
                route.on_message(lambda raw: route.send(json.dumps(frame))
                                 if json.loads(raw).get("type") == "auth" else None)

            page.route_web_socket("**/ws/state", status_socket)
            _enter_drive(page, base_url)
            page.wait_for_function("document.querySelector('[data-drive-fact=link]').dataset.state === 'OPEN'")
            for _ in range(3):
                sockets[-1].send(json.dumps(frame))
                page.wait_for_timeout(100)
            before = len(polls)
            for _ in range(20):                     # 2 s of a live 10 Hz socket: four 500 ms poll ticks
                sockets[-1].send(json.dumps(frame))
                page.wait_for_timeout(100)
            assert len(polls) == before
            page.wait_for_timeout(1600)             # socket silent > 1 s: the REST fallback resumes
            assert len(polls) > before
        finally:
            browser.close()
