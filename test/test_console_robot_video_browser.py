"""D-801 console robot video tile lifecycle in real Chromium (mocked Fleet, media site and peer).

The page loads the real shared/robot-video.js and shared/web/webrtc.js. RTCPeerConnection is
stubbed (no media server here); real WHEP playback is test/test_webrtc_loopback.py.
"""

from __future__ import annotations

import json
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
import threading

import pytest
from browser_harness import browser_tests_enabled

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="set ROSY_RUN_BROWSER_TESTS=1")

from browser_harness import launch_options, safe_http_server  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FILES = {"/common/webrtc.js": ROOT / "shared/web/webrtc.js",
         "/common/fleet-client.js": ROOT / "shared/web/fleet-client.js",
         "/common/request.js": ROOT / "shared/web/request.js",
         "/console/assets/robot-video.js": ROOT / "applications/fleet/web/shared/robot-video.js",
         "/console/assets/robot-video.css": ROOT / "applications/fleet/web/shared/robot-video.css"}
PAGE = b"""<!doctype html><html><head><meta charset="utf-8"></head><body>
<section class="panel vision-preview"></section>
<script type="module" src="/console/assets/robot-video.js"></script></body></html>"""
PEER = """
window.__peers = [];
window.RTCPeerConnection = class {
  constructor() { this.iceGatheringState = 'complete'; window.__peers.push(this); this.closed = false; }
  addTransceiver() {} addEventListener() {}
  async createOffer() { return {type: 'offer', sdp: 'v=0 offer'}; }
  async setLocalDescription(d) { this.localDescription = d; }
  async setRemoteDescription(d) { this.remote = d; }
  close() { this.closed = true; }
};
let hidden = false;
Object.defineProperty(document, 'visibilityState', {get: () => hidden ? 'hidden' : 'visible'});
window.__setHidden = (value) => { hidden = value; document.dispatchEvent(new Event('visibilitychange')); };
"""


def _serve():
    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?")[0]
            body, kind = (PAGE, "text/html") if path == "/" else (
                (FILES[path].read_bytes(), "text/css" if path.endswith(".css") else "text/javascript")
                if path in FILES else (None, None))
            if body is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = safe_http_server(Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def console():
    server = _serve()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _run(origin, robots, *, grant_status=201, steps):
    from playwright.sync_api import sync_playwright
    calls = []

    def fleet(route):
        request, url = route.request, route.request.url
        calls.append((request.method, url.split("127.0.0.1")[-1], request.headers.get("authorization")))
        if url.endswith("/api/fleet/state"):
            return route.fulfill(json={"robots": [{"robot_id": robot} for robot in robots]})
        robot = url.split("/robots/")[1].split("/")[0]
        if request.method == "DELETE":
            return route.fulfill(status=204, body="")
        if grant_status != 201:
            return route.fulfill(status=grant_status, json={"detail": {"code": "FORBIDDEN"}})
        return route.fulfill(status=201, json={
            "grant_id": "a" * 32, "token": f"grant-{robot}", "expires_at": 0, "audience": "site:lab",
            "robot_id": robot, "path": f"robots/{robot}/front", "action": "read",
            "site_url": "https://media.site.example"})

    def media(route):
        request, url = route.request, route.request.url
        calls.append((request.method, url, request.headers.get("authorization")))
        if request.method == "OPTIONS":
            return route.fulfill(status=204, headers={"Access-Control-Allow-Origin": "*",
                                                      "Access-Control-Allow-Headers": "Authorization, Content-Type",
                                                      "Access-Control-Allow-Methods": "POST, DELETE"})
        cors = {"Access-Control-Allow-Origin": "*", "Access-Control-Expose-Headers": "Location"}
        if url.endswith("/whep"):
            return route.fulfill(status=201, body="v=0 answer", content_type="application/sdp",
                                 headers={**cors, "Location": url + "/session-1"})
        return route.fulfill(status=201 if request.method == "POST" else 204, json={}, headers=cors)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**launch_options())
        try:
            page = browser.new_page()
            page.add_init_script(PEER)
            page.route("**/api/fleet/**", fleet)
            page.route("https://media.site.example/**", media)
            page.goto(origin + "/")
            page.wait_for_selector("#robot-video")
            assert not any(url.endswith("/api/fleet/state") for _, url, _ in calls)  # collapsed: no request
            page.click("#robot-video-heading")
            page.wait_for_selector("[data-robot-video-choice]")
            result = steps(page, calls)
        finally:
            browser.close()
    return result, calls


def test_tile_opens_with_header_only_token_and_closes_when_the_tab_hides(console):
    def steps(page, calls):
        page.check("[data-robot-video-choice=rosy_01]")
        page.click("[data-robot-video-start]")
        page.wait_for_function("window.__peers.length === 1 && window.__peers[0].remote")
        opened = list(calls)
        page.evaluate("window.__setHidden(true)")
        page.wait_for_function("window.__peers[0].closed")
        page.wait_for_function("!document.querySelector('[data-robot-video-tile]')")
        closed = list(calls[len(opened):])
        page.evaluate("window.__setHidden(false)")
        page.wait_for_function("window.__peers.length === 2")
        return opened, closed

    (opened, closed), calls = _run(console, ["rosy_01", "rosy_02"], steps=steps)
    assert any(m == "POST" and u.endswith("/api/fleet/robots/rosy_01/media-grant") for m, u, _ in opened)
    whep = [(m, u, a) for m, u, a in opened if u.endswith("/robots/rosy_01/front/whep")]
    assert whep and whep[0][2] == "Bearer grant-rosy_01"
    assert all("grant-rosy_01" not in url for _, url, _ in calls)
    assert any(m == "DELETE" and u.endswith("/whep/session-1") for m, u, _ in closed)
    assert any(m == "DELETE" and u.endswith("/media-grant/" + "a" * 32) for m, u, _ in closed)


def test_grid_is_capped_at_six_tiles(console):
    robots = [f"rosy_0{index}" for index in range(1, 8)]

    def steps(page, calls):
        for robot in robots[:6]:
            page.check(f"[data-robot-video-choice={robot}]")
        disabled = page.is_disabled(f"[data-robot-video-choice={robots[6]}]")
        page.click("[data-robot-video-start]")
        page.wait_for_function("window.__peers.length === 6")
        return disabled, page.locator("[data-robot-video-tile]").count()

    (disabled, tiles), _ = _run(console, robots, steps=steps)
    assert disabled is True and tiles == 6


def test_refused_grant_shows_no_video_and_opens_no_session(console):
    def steps(page, calls):
        page.check("[data-robot-video-choice=rosy_01]")
        page.click("[data-robot-video-start]")
        page.wait_for_function("document.querySelector('[data-robot-video-tile]')?.dataset.state === 'lost'")
        return page.text_content("[data-robot-video-tile] figcaption")

    label, calls = _run(console, ["rosy_01"], grant_status=403, steps=steps)
    assert "영상 권한 없음" in label
    assert not any("media.site.example" in url for _, url, _ in calls)
