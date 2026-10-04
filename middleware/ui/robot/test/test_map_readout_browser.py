"""Browser checks for the keyboard map target readout."""

from __future__ import annotations

import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[2]
pytestmark = pytest.mark.skipif(
    os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
    reason="set ROSY_RUN_BROWSER_TESTS=1 to run the optional Chromium regression",
)


class _Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(REPO_ROOT), **kwargs)

    def translate_path(self, path):
        if path == "/assets/map.js":
            return str(ROOT / "map.js")
        if path.startswith("/common/"):
            return str(REPO_ROOT / "shared" / "web" / path.removeprefix("/common/"))
        return super().translate_path(path)

    def do_GET(self):
        if self.path == "/__maptest":
            body = """<!doctype html><html><head><meta charset='utf-8'></head><body>
              <canvas id='map' width='100' height='100' style='width:100px;height:100px'></canvas>
              <p id='readout' role='status' aria-live='polite'></p>
              <script type='module' src='/common/ui.js'></script>
              <script type='module'>
                import {createFieldMap} from '/assets/map.js';
                const canvas = document.getElementById('map');
                window.__calls = [];
                window.__map = createFieldMap({
                  canvas, canGoal:() => true, getPose:() => null, getNavigation:() => null,
                  onTargetReadout:(target) => {
                    document.getElementById('readout').textContent = target.inside
                      ? `X ${target.x.toFixed(2)} m · Y ${target.y.toFixed(2)} m`
                      : '지도 영역 밖';
                  },
                  api:async (path) => { window.__calls.push(path); return {}; },
                  apiMaybe:async (path) => path === '/api/v1/map'
                    ? {width:100,height:100,resolution:0.1,origin:{x:-5,y:-5},data:Array(10000).fill(0)}
                    : path === '/api/v1/navigation/path' ? {poses:[]} : null,
                });
                await window.__map.refresh();
                window.__ready = true;
              </script>
            </body></html>""".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, _format, *_args):
        pass


def test_map_keyboard_crosshair_announces_world_coordinates_and_outside_map_without_sending():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_port}/__maptest", wait_until="load")
            page.wait_for_function("window.__ready === true")
            canvas = page.locator("#map")
            canvas.focus()
            page.keyboard.press("ArrowRight")
            page.wait_for_function("document.getElementById('readout').textContent !== ''")
            assert page.locator("#readout").inner_text() == "X 1.20 m · Y 0.00 m"
            for _ in range(5):
                page.keyboard.press("ArrowRight")
            page.wait_for_function("document.getElementById('readout').textContent === '지도 영역 밖'")
            assert page.locator("#readout").inner_text() == "지도 영역 밖"
            canvas.click(position={"x": 50, "y": 50})
            page.wait_for_function("document.getElementById('readout').textContent === 'X 0.00 m · Y 0.00 m'")
            assert page.evaluate("window.__calls.filter((path) => path.includes('/goal') || path.includes('initialpose'))") == []
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
