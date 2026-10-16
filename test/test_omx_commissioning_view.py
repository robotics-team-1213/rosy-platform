"""Read-only camera monitor refuses stale/replayed observations and remote hosts."""
import threading
import os
import time
import importlib.util
from pathlib import Path
import urllib.error
import urllib.request

import pytest

_spec = importlib.util.spec_from_file_location(
    "commissioning_view", Path(__file__).parents[1] / "deploy" / "robot" / "omx" / "commissioning_view.py")
_viewer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_viewer)
ObservationStore, make_server = _viewer.ObservationStore, _viewer.make_server


def test_repeated_source_stamp_does_not_refresh_picture():
    store = ObservationStore()
    store.put("top", 100.0, b"jpeg", received=10.0)
    assert not store.put("top", 100.0, b"replay", received=11.9)
    assert store.snapshot(now=12.1, wall=102.1)["top"]["fresh"] is False
    assert store.image("top", now=12.1, wall=102.1) is None


@pytest.mark.parametrize("stamp", [float("nan"), float("inf"), 0, -1])
def test_bad_source_clock_is_rejected(stamp):
    with pytest.raises(ValueError):
        ObservationStore().put("top", stamp, b"jpeg", received=10)


def test_both_source_and_receipt_clocks_must_be_fresh():
    store = ObservationStore()
    store.put("front", 90, b"jpeg", received=10)
    assert not store.snapshot(now=10.1, wall=100)["front"]["fresh"]
    store.put("front", 110, b"future", received=11)
    assert not store.snapshot(now=11.1, wall=100)["front"]["fresh"]


def test_future_sample_cannot_poison_subsequent_live_stream():
    store = ObservationStore()
    with pytest.raises(ValueError):
        store.put("top", time.time() + 3600, b"future")
    assert store.put("top", time.time(), b"live")
    assert store.snapshot()["top"]["fresh"]


def test_read_only_http_hides_stale_frame_and_rejects_foreign_host():
    server = make_server(ObservationStore(), port=0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urllib.request.urlopen(base + "/") as response:
            assert "상단" in response.read().decode()
            assert response.headers["Cache-Control"] == "no-store"
        for path, method, host, expected in [
            ("/frame/top.jpg", "GET", None, 503),
            ("/state.json", "POST", None, 405),
            ("/state.json", "GET", "attacker.example", 403),
            ("/../../private", "GET", None, 404),
        ]:
            req = urllib.request.Request(base + path, method=method)
            if host:
                req.add_header("Host", host)
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(req)
            assert error.value.code == expected
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1", reason="opt-in real Chromium")
def test_browser_displays_and_removes_disconnected_observations():
    from playwright.sync_api import expect, sync_playwright
    store = ObservationStore()
    server = make_server(store, port=0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 390, "height": 844})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}/")
            stamp = time.time()
            store.put("top", stamp, b"not-an-image")
            store.put("joints", stamp, {"joint1": 0.25})
            expect(page.locator("#joints")).to_contain_text("0.25")
            expect(page.locator("#top")).to_be_hidden()
            page.route("**/state.json", lambda route: None)
            expect(page.locator("#joints")).to_contain_text("피드백 없음", timeout=2400)
            page.unroute_all(behavior="ignoreErrors")
            store.put("joints", stamp + 0.001, {"joint1": 9}, received=time.monotonic() - 3)
            expect(page.locator("#joints")).to_contain_text("피드백 없음")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1", reason="opt-in real Chromium")
def test_browser_expires_old_image_when_download_stalls_but_metadata_advances():
    from io import BytesIO
    from PIL import Image
    from playwright.sync_api import expect, sync_playwright
    encoded = BytesIO()
    Image.new("RGB", (4, 4)).save(encoded, format="JPEG")
    store = ObservationStore()
    stop = threading.Event()
    def feed():
        while not stop.is_set():
            store.put("top", time.time(), encoded.getvalue())
            stop.wait(0.1)
    producer = threading.Thread(target=feed)
    producer.start()
    server = make_server(store, port=0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_port}/")
            expect(page.locator("#top")).to_be_visible()
            page.route("**/frame/top.jpg*", lambda route: None)
            expect(page.locator("#top")).to_be_hidden(timeout=4000)
            browser.close()
    finally:
        stop.set()
        producer.join()
        server.shutdown()
        server.server_close()
        worker.join()
