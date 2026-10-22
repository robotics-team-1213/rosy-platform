"""Pilot drive reads robot state from /ws/state; the REST poll is only the fallback when the socket is quiet."""

from __future__ import annotations

import json

import pytest
from browser_harness import browser_tests_enabled

from test_pilot_browser import _enter_drive, playwright_sync


@pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")
def test_drive_skips_rest_state_poll_while_state_socket_is_live(base_url):
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
            # drive-auto.js reads /robot/state once a second on its own; only drive.js's 500 ms poll is judged.
            for _ in range(3):
                sockets[-1].send(json.dumps(frame))
                page.wait_for_timeout(100)
            before = len(polls)
            for _ in range(20):                     # 2 s of a live 10 Hz socket
                sockets[-1].send(json.dumps(frame))
                page.wait_for_timeout(100)
            live = len(polls) - before
            assert live <= 3, live                  # drive-auto's ~2; drive.js's four 500 ms ticks would make ~6
            page.wait_for_timeout(1200)             # socket silent > 1 s: the drive.js REST fallback resumes
            mark = len(polls)
            page.wait_for_timeout(2000)
            assert len(polls) - mark >= live + 2, (live, len(polls) - mark)
        finally:
            browser.close()
