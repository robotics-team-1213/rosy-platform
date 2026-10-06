"""D-488 M1 site map page in real Chromium (opt-in, ROSY_BROWSER_TESTS=1). No robot moves."""

import os
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from test_site_map_trip import _app, _on_ring_s

pytestmark = pytest.mark.skipif(os.environ.get("ROSY_BROWSER_TESTS") != "1",
                                reason="opt-in real Chromium browser scenario")
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def page_site(tmp_path):
    from playwright.sync_api import sync_playwright

    client, tasks, store, robot = _app(tmp_path)
    robot._state = _on_ring_s(store)
    client.app.state.web_common = ROOT / "shared" / "web"
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(client.app, log_level="error", timeout_graceful_shutdown=3))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        with sync_playwright() as toolkit:
            browser = toolkit.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                page.goto(origin + "/console/site-map")
                yield page, store, robot
            finally:
                browser.close()
    finally:
        server.should_exit = True
        worker.join(timeout=20)
        listener.close()


def test_view_edit_activate_and_preview_a_trip(page_site):
    from playwright.sync_api import expect

    page, store, robot = page_site
    expect(page).to_have_title("Rosy Fleet · 현장 지도")
    expect(page.locator("ui-brand")).to_contain_text("Rosy Fleet")
    page.locator("#credential input").fill("operator-token")
    page.locator("#connect").click()
    expect(page.locator("#session")).to_contain_text("bob")
    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1")
    expect(page.locator("#site-map-svg [data-place]")).to_have_count(4)
    expect(page.locator("#site-map-svg .arrow")).to_have_count(8)  # 4 one-way + 2 two-way edges

    page.select_option("#trip-place", "NW")
    page.locator("#trip-plan").click()
    expect(page.locator("#trip-summary")).to_contain_text("3개 차로")
    expect(page.locator("#site-map-svg .plan")).to_have_count(3)
    expect(page.locator("#trip-actions li").last).to_contain_text("정지")
    assert not [call for call in robot.calls if call[0] == "navigation_goal"]

    page.locator('#site-map-svg [data-place="NW"]').click()
    page.locator("#place-name").fill("A동 입구")
    page.select_option("#place-kind", "stop")
    page.locator("#apply-edit").click()
    page.locator('#site-map-svg [data-edge="ring_n"]').dispatch_event("click")  # a thin arc stroke
    page.select_option("#edge-direction", "two_way")
    page.locator("#apply-edit").click()
    page.locator("#save-draft").click()
    expect(page.locator("#draft-status")).to_contain_text("저장된 초안")
    page.locator("#activate").click()
    page.locator("dialog.ui-confirm ui-button[kind=irreversible]").click()
    expect(page.locator("#notice")).to_contain_text("활성 지도 v2")
    active = store.active()[1]
    assert next(p for p in active.places if p.id == "NW").name == "A동 입구"
    assert next(e for e in active.edges if e.id == "ring_n").direction == "two_way"

    page.locator("#trip-pick").check()
    page.locator("#site-map-svg").click(position={"x": 5, "y": 5})
    expect(page.locator("#trip-point")).to_contain_text("찍은 좌표 x")
    page.locator("#trip-plan").click()
    expect(page.locator("#trip-summary")).to_contain_text("차로 폭 두 배 안에 차로가 없습니다")


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_site_map_fits_declared_widths(page_site, width, height):
    page, _, _ = page_site
    page.set_viewport_size({"width": width, "height": height})
    page.locator("#credential input").fill("operator-token")
    page.locator("#connect").click()
    from playwright.sync_api import expect

    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1")
    sizes = page.evaluate("""() => ({
      overflow: document.documentElement.scrollWidth - innerWidth,
      map: document.querySelector('#site-map-svg').getBoundingClientRect().width,
      edit: document.querySelector('[aria-labelledby=edit-heading]').getBoundingClientRect().width,
      trip: document.querySelector('[aria-labelledby=trip-heading]').getBoundingClientRect().width,
      stop: document.querySelector('#estop').getBoundingClientRect().right
    })""")
    assert sizes["overflow"] <= 0, sizes
    assert abs(sizes["edit"] - sizes["trip"]) <= 1, sizes
    assert sizes["stop"] <= width, sizes
