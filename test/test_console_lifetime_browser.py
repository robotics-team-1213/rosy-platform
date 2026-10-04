"""D-425 actual document teardown, token epochs and BFCache read recovery."""

from __future__ import annotations

import json
import os
from urllib.parse import urlparse

import pytest

from browser_harness import open_page
from test_fleet_console_browser import API, WEB, console_url  # noqa: F401
from test_fleet_console_browser import _camera_api

pytestmark = pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
                                reason="set ROSY_RUN_BROWSER_TESTS=1 for Chromium acceptance")


def _held_fetch(path, body=False):
    return """(() => {
      const send = window.fetch.bind(window);
      window.__requests = [];
      window.__pending = [];
      window.__polls = new Map();
      window.__observers = new Set();
      const Observer = window.IntersectionObserver;
      window.IntersectionObserver = class extends Observer {
        constructor(...args) { super(...args); __observers.add(this); }
        disconnect() { super.disconnect(); __observers.delete(this); }
      };
      let sequence = 0;
      window.setInterval = (fn, ms) => { const id = ++sequence; __polls.set(id, fn); return id; };
      window.clearInterval = id => __polls.delete(id);
      window.fetch = (input, options = {}) => {
        const path = new URL(String(input), location.origin).pathname;
        __requests.push({path, method: options.method || 'GET'});
        if (path === HELD_PATH && !__pending.length) {
          if (HELD_BODY) {
            const response = new Response('{}', {status: 200});
            const waiting = new Promise(resolve => __pending.push({signal: options.signal,
              release: body => resolve(path.startsWith('/api/vision/') ? new Blob(['late']) : body)}));
            response.json = response.blob = () => waiting;
            return Promise.resolve(response);
          }
          return new Promise(resolve => __pending.push({signal: options.signal,
            release: (body, status = 200) => resolve(new Response(JSON.stringify(body), {status}))}));
        }
        return send(input, options);
      };
      sessionStorage.setItem('rosy-console-token', 'fleet-lifetime-a');
    })();""".replace("HELD_PATH", json.dumps(path)).replace("HELD_BODY", json.dumps(body))


def _serve_api(route):
    body = {
        **API,
        "/api/fleet/session": {"principal_id": "fresh-role", "role": "operator"},
        "/api/fleet/discovery": {"scanner_online": True, "devices": []},
        "/api/fleet/enrollment/robots": {"available": False, "robots": [], "alarms": []},
        "/api/fleet/vision/sources": {"sources": []},
    }.get(urlparse(route.request.url).path)
    route.fulfill(status=200 if body is not None else 404,
                  json=body if body is not None else {"detail": "Not Found"})


@pytest.mark.parametrize("document,held", [("index.html", "/api/fleet/state"),
                                            ("index.html", "/api/fleet/tracking"),
                                            ("install.html", "/api/fleet/discovery"),
                                            ("install.html", "/api/fleet/pairing/v1/pending"),
                                            ("index.html", "/api/vision/sources/camera/frame")])
@pytest.mark.parametrize("body", [False, True], ids=["fetch", "body"])
def test_hidden_document_cancels_reads_and_commands_and_restores_only_reads(console_url, document, held, body):
    from playwright.sync_api import sync_playwright

    base = console_url.rsplit("/", 1)[0]
    with sync_playwright() as playwright:
        browser, page, errors = open_page(playwright, 1440, 900)
        page.add_init_script(_held_fetch(held, body))
        def serve(route):
            path = urlparse(route.request.url).path
            if "/pairing/v1/" in held and path in _camera_api("fresh-role", "operator"):
                route.fulfill(status=200, json=_camera_api("fresh-role", "operator")[path])
            elif held.startswith("/api/vision/") and path == "/api/fleet/vision/sources":
                route.fulfill(status=200, json={"sources": ["camera"]})
            elif held.startswith("/api/vision/") and path == "/api/fleet/vision/lease":
                route.fulfill(status=200, json={"lease": "preview-token", "frame_path": held})
            else:
                _serve_api(route)
        page.route("**/api/**", serve)
        page.goto(f"{base}/{document}", wait_until="domcontentloaded")
        asset = "console.js" if document == "index.html" else "install.js"
        assert page.request.get(f"{base}/console/assets/{asset}").body() == (WEB / asset).read_bytes()
        if held.startswith("/api/vision/"):
            page.wait_for_function("document.querySelector('#vision-source').value === 'camera'")
            page.evaluate("() => { for (const tick of [...__polls.values()]) tick(); }")
        page.wait_for_function("window.__pending.length === 1")
        polls = page.evaluate("__polls.size")
        observers = page.evaluate("__observers.size")
        page.evaluate("window.__oldPolls = [...__polls.values()]")
        page.evaluate("dispatchEvent(new PageTransitionEvent('pagehide', {persisted: true}))")
        assert page.evaluate("__pending[0].signal?.aborted === true")
        assert page.evaluate("__polls.size") == 0
        assert page.evaluate("__observers.size") == 0
        before = page.locator("main").inner_html()
        count = page.evaluate("__requests.length")
        page.locator("#estop").dispatch_event("click")
        page.evaluate("() => { for (const tick of [...__polls.values()]) tick(); }")
        page.evaluate("__pending[0].release({fleet: {name: 'late'}, robots: [], devices: []})")
        page.evaluate("() => new Promise(resolve => setTimeout(resolve, 0))")
        assert page.evaluate("__requests.length") == count
        assert page.locator("main").inner_html() == before

        page.evaluate("dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true}))")
        page.wait_for_function("document.querySelector('#user-role').textContent.includes('fresh-role')")
        assert page.evaluate("__requests.length") > count
        assert page.evaluate("__polls.size") == polls
        assert page.evaluate("__observers.size") == observers
        page.evaluate("() => new Promise(resolve => setTimeout(resolve, 0))")
        fresh_count = page.evaluate("__requests.length")
        page.evaluate("() => { for (const tick of __oldPolls) tick(); }")
        assert page.evaluate("__requests.length") == fresh_count
        assert page.evaluate("__requests.every(row => row.method === 'GET' || row.path === '/api/fleet/vision/lease')")
        assert not errors
        browser.close()


@pytest.mark.parametrize("document", ["index.html", "install.html"])
def test_old_401_cannot_lock_a_reauthenticated_document(console_url, document):
    from playwright.sync_api import sync_playwright

    base = console_url.rsplit("/", 1)[0]
    with sync_playwright() as playwright:
        browser, page, errors = open_page(playwright, 1440, 900)
        page.add_init_script(_held_fetch("/api/fleet/session"))
        page.route("**/api/**", _serve_api)
        page.goto(f"{base}/{document}", wait_until="domcontentloaded")
        page.wait_for_function("window.__pending.length === 1")
        if not page.locator("#console-token").is_visible():
            page.locator("#topbar-more").click()
        page.fill("#console-token", "fleet-lifetime-b")
        page.locator("#token-save").click()
        page.wait_for_function("document.querySelector('#user-role').textContent.includes('fresh-role')")
        assert page.evaluate("__pending[0].signal?.aborted === true")
        page.evaluate("__pending[0].release({detail: 'old token expired'}, 401)")
        page.evaluate("() => new Promise(resolve => setTimeout(resolve, 0))")
        assert "fresh-role" in page.locator("#user-role").inner_text()
        assert page.locator("#console-token").get_attribute("aria-invalid") is None
        assert page.evaluate("__requests.every(row => row.method === 'GET')")
        assert not errors
        browser.close()


def test_pending_confirmation_is_cancelled_and_cannot_submit_after_restore(console_url):
    from playwright.sync_api import sync_playwright

    base = console_url.rsplit("/", 1)[0]
    with sync_playwright() as playwright:
        browser, page, errors = open_page(playwright, 1440, 900)
        page.add_init_script(_held_fetch("/never-held"))
        camera = _camera_api("fresh-role", "operator")
        def serve(route):
            path = urlparse(route.request.url).path
            if path in camera:
                route.fulfill(status=200, json=camera[path])
            else:
                _serve_api(route)
        page.route("**/api/**", serve)
        page.goto(f"{base}/install.html", wait_until="domcontentloaded")
        page.locator('#camera-requests ui-button[data-action="reject"]').first.click()
        page.locator("dialog.ui-confirm").wait_for()
        page.evaluate("window.__oldConfirmation = document.querySelector('dialog.ui-confirm ui-button[kind=irreversible]')")
        page.evaluate("dispatchEvent(new PageTransitionEvent('pagehide', {persisted: true}))")
        page.wait_for_function("!document.querySelector('dialog.ui-confirm')")
        page.evaluate("dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true}))")
        page.wait_for_function("document.querySelector('#user-role').textContent.includes('fresh-role')")
        page.evaluate("__oldConfirmation.dispatchEvent(new MouseEvent('click'))")
        page.evaluate("() => new Promise(resolve => setTimeout(resolve, 0))")
        assert page.evaluate("__requests.every(row => row.method === 'GET')")
        assert not errors
        browser.close()
