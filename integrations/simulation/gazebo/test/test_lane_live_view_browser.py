"""Opt-in browser contract for the read-only Gazebo viewer tabs (D-306)."""

import importlib.util
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from browser_harness import browser_tests_enabled


pytestmark = pytest.mark.skipif(
    not browser_tests_enabled(),
    reason="set ROSY_RUN_BROWSER_TESTS=1 for the Chromium accessibility check",
)

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture()
def viewer_url():
    spec = importlib.util.spec_from_file_location("lane_live_view_browser", SCRIPTS / "lane_live_view.py")
    viewer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(viewer)
    root = SCRIPTS.parents[3]
    viewer.COMMON = root / "shared" / "web"
    viewer.COMMON_ASSETS = json.loads((viewer.COMMON / "shared-assets.json").read_text())["shared_assets"]
    graph = root / "middleware/perception/map/map_v2_fleet/lane_graph.yaml"

    class Handler(viewer.make_handler(viewer.ViewerState(viewer.load_graph(graph)))):
        def _stream_mjpeg(self, stream):
            self.send_error(503)  # Synthetic fixture has no camera and must not retain stream threads.

        def log_message(self, *args):
            pass

    for port in range(40100, 40200):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        except OSError:
            continue
        break
    else:
        raise RuntimeError("could not allocate a browser-safe local port")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/lane_live_view.html"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def test_view_tabs_have_keyboard_and_panel_contract(viewer_url):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(viewer_url, wait_until="domcontentloaded")
        page.locator("#tab-live").focus()
        page.keyboard.press("ArrowRight")
        assert page.evaluate("document.activeElement?.id") == "tab-results"
        assert page.locator("#tab-results").get_attribute("aria-selected") == "true"
        assert page.locator("#tab-results").get_attribute("aria-controls") == "results"
        assert page.locator("#results").get_attribute("role") == "tabpanel"
        assert page.locator("#results").is_visible()
        assert not page.locator("#live").is_visible()
        page.keyboard.press("Home")
        assert page.evaluate("document.activeElement?.id") == "tab-live"
        assert page.locator("#tab-live").get_attribute("aria-selected") == "true"
        assert page.locator("#live").is_visible()
        browser.close()


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("width", [320, 390, 1280, 2000])
def test_shared_assets_responsive_layout_and_tab_targets(viewer_url, theme, width):
    from playwright.sync_api import sync_playwright, expect

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 900})
        page.add_init_script("localStorage.setItem('rosy.theme', " + json.dumps(theme) + ")")
        page.goto(viewer_url, wait_until="domcontentloaded")
        page.wait_for_function("customElements.get('ui-button') !== undefined")
        page.evaluate("document.documentElement.dataset.theme = " + json.dumps(theme))
        for asset in ["tokens.css", "components.css", "ui.js"]:
            response = page.request.get(viewer_url.rsplit("/", 1)[0] + "/common/" + asset)
            assert response.status == 200, asset
        expect(page.locator("#offline")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        tab = page.locator("#tab-live")
        assert tab.bounding_box()["height"] >= 48
        tab.focus()
        page.keyboard.press("ArrowRight")
        expect(page.locator("#tab-results")).to_be_focused()
        expect(page.locator("#results")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.keyboard.press("Home")
        expect(tab).to_be_focused()
        expect(page.locator("#live")).to_be_visible()
        browser.close()


def test_route_progress_waits_for_data_and_clears_last_measurement(viewer_url):
    from playwright.sync_api import sync_playwright, expect
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.route('**/status.json', lambda route: route.fulfill(status=503, json={}))
        page.goto(viewer_url, wait_until='domcontentloaded')
        expect(page.locator('#meters')).to_have_text('— / — m')
        route = {'total_unique': 8, 'done_unique': 0, 'progress_m': 0, 'length_m': 4,
                 'fraction': 0, 'key_states': [], 'finished': False, 'segment_index': 0,
                 'keys': ['a'], 'current_key': 'a'}
        page.evaluate('route=>renderProgress(route)', route)
        expect(page.locator('#meters')).to_have_text('0.0 / 4.0 m')
        route.update(progress_m=2, fraction=.5)
        page.evaluate('route=>renderProgress(route)', route)
        expect(page.locator('#meters')).to_have_text('2.0 / 4.0 m')
        page.evaluate('renderProgress(null)')
        expect(page.locator('#meters')).to_have_text('— / — m')
        assert page.locator('#progressBar').evaluate('node=>node.style.width') == '0%'
        expect(page.locator('#curKey')).to_have_text('')
        browser.close()
