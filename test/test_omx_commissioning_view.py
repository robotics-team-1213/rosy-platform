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


def test_dual_arm_samples_keep_identical_joint_names_and_freshness_separate():
    store = ObservationStore(arms={"arm_a": "/omx_commissioning/arm_a/joint_states",
                                   "arm_b": "/omx_commissioning/arm_b/joint_states"})
    assert store.put("arm:arm_a", 100, {"joint1": 0.25}, received=10)
    assert store.put("arm:arm_b", 100, {"joint1": 0.75}, received=10)
    assert not store.put("arm:arm_b", 99, {"joint1": 9}, received=11.9)
    store.put("arm:arm_a", 102, {"joint1": 0.5}, received=12)
    state = store.snapshot(now=12.1, wall=102.1)
    assert state["arms"]["arm_a"]["fresh"]
    assert state["arms"]["arm_a"]["values"] == {"joint1": 0.5}
    assert state["arms"]["arm_a"]["sequence"] == 2
    assert not state["arms"]["arm_b"]["fresh"]
    assert state["arms"]["arm_b"]["values"] is None
    assert state["arms"]["arm_b"]["sequence"] == 1
    assert state["joint_topic"] is None
    assert not state["joints"]["fresh"]


@pytest.mark.parametrize("entries", [
    ["arm_a=/omx_commissioning/arm_a/joint_states", "arm_a=/omx_commissioning/arm_b/joint_states"],
    ["arm_a=/omx_commissioning/arm_a/joint_states", "arm_b=/omx_commissioning/arm_a/joint_states"],
    ["arm_a=/joint_states"], ["arm_a=/omx/arm_a/joint_states"],
    ["arm_a=/omx_commissioning/arm_a/command"], ["bad<label=/omx_commissioning/arm_a/joint_states"],
])
def test_dual_arm_configuration_rejects_ambiguous_or_noncommissioning_sources(entries):
    with pytest.raises(ValueError):
        _viewer.parse_arm_topics(entries)


def test_dual_arm_three_cameras_keep_each_wrist_independent_of_the_shared_top():
    topics = {"top": "/top_camera/image_raw", "arm_a_wrist": "/arm_a_wrist_camera/image_raw",
              "arm_b_wrist": "/arm_b_wrist_camera/image_raw"}
    store = ObservationStore(cameras=topics)
    for key, image in [("top", b"top"), ("arm_a_wrist", b"wrist-a"), ("arm_b_wrist", b"wrist-b")]:
        store.put(key, 100, image, received=10)
    assert store.image("arm_a_wrist", now=10.1, wall=100.1) == b"wrist-a"
    assert store.image("arm_b_wrist", now=10.1, wall=100.1) == b"wrist-b"
    store.put("top", 102, b"top-new", received=12)
    store.put("arm_a_wrist", 102, b"a-new", received=12)
    state = store.snapshot(now=12.1, wall=102.1)
    assert state["cameras"]["top"]["fresh"]
    assert state["cameras"]["arm_a_wrist"]["fresh"]
    assert not state["cameras"]["arm_b_wrist"]["fresh"]
    assert state["cameras"]["arm_b_wrist"]["sequence"] == 1
    assert state["cameras"]["arm_b_wrist"]["topic"] == topics["arm_b_wrist"]
    assert store.image("arm_b_wrist", now=12.1, wall=102.1) is None


@pytest.mark.parametrize("entries", [
    ["top=/top_camera/image_raw", "top=/arm_a_wrist_camera/image_raw"],
    ["arm_a_wrist=/wrist_camera/image_raw", "arm_b_wrist=/wrist_camera/image_raw"],
    ["joints=/camera/image_raw"], ["arms=/camera/image_raw"],
    ["bad<label=/camera/image_raw"], ["top=/top_camera/command"],
])
def test_dual_arm_camera_configuration_rejects_aliases_and_invalid_sources(entries):
    with pytest.raises(ValueError):
        _viewer.parse_camera_topics(entries)


@pytest.mark.skipif(os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1", reason="opt-in real Chromium")
def test_dual_arm_browser_expires_one_arm_while_the_other_keeps_updating():
    from playwright.sync_api import expect, sync_playwright
    store = ObservationStore(arms={"arm_a": "/omx_commissioning/arm_a/joint_states",
                                   "arm_b": "/omx_commissioning/arm_b/joint_states"})
    stop = threading.Event()
    def feed():
        while not stop.is_set():
            store.put("arm:arm_a", time.time(), {"joint1": 0.25})
            stop.wait(0.1)
    producer = threading.Thread(target=feed)
    producer.start()
    store.put("arm:arm_b", time.time(), {"joint1": 0.75})
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
            expect(page.locator("#arm-arm_a")).to_contain_text("0.25")
            expect(page.locator("#arm-arm_b")).to_contain_text("0.75")
            expect(page.locator("#arm-arm_b")).to_contain_text("피드백 없음", timeout=3000)
            expect(page.locator("#arm-arm_a")).to_contain_text("0.25")
            page.route("**/state.json", lambda route: None)
            expect(page.locator("#arm-arm_a")).to_contain_text("피드백 없음", timeout=2400)
            page.unroute_all(behavior="ignoreErrors")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not errors
            browser.close()
    finally:
        stop.set()
        producer.join()
        server.shutdown()
        server.server_close()
        worker.join()


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
