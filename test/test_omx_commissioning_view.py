"""Read-only camera monitor refuses stale/replayed observations and remote hosts."""
import json
import re
import shutil
import subprocess
import threading
import time
import importlib.util
from pathlib import Path
import urllib.error
import urllib.request

import pytest
from browser_harness import browser_tests_enabled, free_port

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


@pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium")
def test_browser_three_camera_panels_expire_only_the_disconnected_wrist():
    from io import BytesIO
    from PIL import Image
    from playwright.sync_api import expect, sync_playwright
    topics = {"top": "/top_camera/image_raw", "arm_a_wrist": "/arm_a_wrist_camera/image_raw",
              "arm_b_wrist": "/arm_b_wrist_camera/image_raw"}
    store = ObservationStore(cameras=topics)
    frames = {}
    for key, color in zip(topics, ("red", "green", "blue")):
        encoded = BytesIO()
        Image.new("RGB", (4, 4), color=color).save(encoded, format="JPEG")
        frames[key] = encoded.getvalue()
    stop, disconnect = threading.Event(), threading.Event()

    def feed():
        while not stop.is_set():
            for key, frame in frames.items():
                if key != "arm_b_wrist" or not disconnect.is_set():
                    store.put(key, time.time(), frame)
            stop.wait(0.1)

    producer = threading.Thread(target=feed)
    producer.start()
    server = make_server(store, port=free_port())
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 390, "height": 844})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}/")
            expect(page.locator("img[data-camera]")).to_have_count(3)
            for key in topics:
                expect(page.locator(f"#{key}")).to_be_visible()
            disconnect.set()
            expect(page.locator("#arm_b_wrist")).to_be_hidden(timeout=3500)
            expect(page.locator("#top")).to_be_visible()
            expect(page.locator("#arm_a_wrist")).to_be_visible()
            page.route("**/state.json", lambda route: None)
            expect(page.locator("#top")).to_be_hidden(timeout=2400)
            expect(page.locator("#arm_a_wrist")).to_be_hidden()
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


@pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium")
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
    server = make_server(store, port=free_port())
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


@pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium")
def test_browser_displays_and_removes_disconnected_observations():
    from playwright.sync_api import expect, sync_playwright
    store = ObservationStore()
    server = make_server(store, port=free_port())
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


@pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium")
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
    server = make_server(store, port=free_port())
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


def test_commissioning_gate_panel_is_read_only_and_names_missing_items(tmp_path):
    gates = _viewer.gate_reader(tmp_path, ["arm_a=omx-1/omx-1-control", "arm_b=omx-2/omx-2-control"])
    from omx_adapter.real.commissioning_record import CommissioningStore
    store = CommissioningStore(tmp_path, workcell_id="omx-1", instance_id="omx-1-control")
    store.save({"gripper": {"open_rad": 0.5, "close_rad": -0.2}}, by="kim",
               config_revision="cal-1", joint_names=["joint1", "joint2"], expected_revision=None)
    server = make_server(ObservationStore(gates=gates), port=0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urllib.request.urlopen(base + "/state.json") as response:
            state = json.loads(response.read())
        arm_a, arm_b = state["gates"]["arm_a"], state["gates"]["arm_b"]
        assert arm_a["revision"] == store.revision()
        assert arm_a["items"]["gripper"]["measured_by"] == "kim" and arm_a["items"]["stop_test"] is None
        assert any("missing: joint_limits, workspace" in b for b in arm_a["blockers"])
        assert arm_b["revision"] is None and "no commissioning record for this arm" in arm_b["blockers"]
        with pytest.raises(urllib.error.HTTPError) as error:  # still no write path
            urllib.request.urlopen(urllib.request.Request(base + "/state.json", method="POST"))
        assert error.value.code == 405
        with urllib.request.urlopen(base + "/") as response:
            assert 'id="gates"' in response.read().decode()
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
    with pytest.raises(ValueError):
        _viewer.gate_reader(tmp_path, ["arm_a=../x"])
    assert _viewer.gate_reader(None, []) is None


def _unbalanced_quote_lines(script):
    """Lines whose ``"`` strings do not close on the same line (a JS string cannot hold a newline)."""
    return [line for line in script.splitlines() if len(re.findall(r'(?<!\\)"', line)) % 2]


def test_viewer_script_parses_even_when_browser_tests_skip(tmp_path):
    assert _unbalanced_quote_lines(_viewer.SCRIPT) == []
    assert _unbalanced_quote_lines('const a = "x\n";')  # the check sees a broken literal
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable; the quote check above still ran")
    script = tmp_path / "viewer.js"
    script.write_text(_viewer.SCRIPT, encoding="utf-8")
    checked = subprocess.run([node, "--check", str(script)], capture_output=True, text=True)
    assert checked.returncode == 0, checked.stderr
