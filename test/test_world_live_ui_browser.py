"""Browser coverage for the real-site factory on the standalone World server."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import re
import shutil
import struct
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit
import zlib

import pytest

from browser_harness import browser_tests_enabled, free_port, launch_options

ROOT = Path(__file__).resolve().parents[1]
WORLD = ROOT / "applications" / "world"
sys.path.insert(0, str(WORLD))

import bridge_real_fleet  # noqa: E402
import build_bundle  # noqa: E402
import serve  # noqa: E402

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium scenario")


def _tiny_png() -> bytes:
    chunk = lambda tag, data: struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff\xff"))
    return b"\x89PNG\r\n\x1a\n" + ihdr + idat + chunk(b"IEND", b"")


def _write_bundle(bundle: Path) -> Path:
    for base, files in ((bundle, build_bundle.WEB_FILES), (bundle / "common", build_bundle.COMMON_FILES)):
        source = WORLD / "web" if base == bundle else ROOT / "shared" / "web"
        for name in files:
            target = base / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, target)

    # Observe the real scene graph without replacing the renderer or actor layer.
    index = bundle / "index.html"
    html = index.read_text(encoding="utf-8").replace('src="./app.js"', 'src="./probe.js"')
    index.write_text(html, encoding="utf-8")
    (bundle / "probe.js").write_text("""
import { Scene } from "./common/vendor/three.module.min.js";
const add = Scene.prototype.add;
Scene.prototype.add = function (...children) {
  const result = add.apply(this, children);
  const cargo = this.getObjectByName("factory-active-cargo");
  if (cargo) window.factoryCargo = cargo;
  return result;
};
await import("./app.js");
""", encoding="utf-8")

    (bundle / "manifest.json").write_text("{}", encoding="utf-8")
    data = bundle / "data"
    data.mkdir()
    (data / "r2s-calibration.json").write_text("{}", encoding="utf-8")
    (data / "site-map.json").write_text(json.dumps({
        "sha256": "ab" * 32, "version": 7,
        "map": {"map_id": "track", "places": [{"id": "S3", "x": 0.69, "y": -0.246}], "edges": []},
    }), encoding="utf-8")
    (data / "recording.json").write_text(json.dumps({
        "schema": "rosy.world.recording.v1",
        "source": "test",
        "map_version": 7,
        "captured_at": "2026-11-24T00:00:00Z",
        "samples": [{"offset_ms": 0, "frame_id": "track", "positions": [{"id": "rosy_45", "x_m": 0.0, "y_m": 0.0}]}],
    }), encoding="utf-8")
    pixel = _tiny_png()
    for name in ("site-map.png", "cell-render.png", "cell-photo.jpg"):
        (data / name).write_bytes(pixel)
    return data / "worlds" / "real-site.json"


def test_direct_real_site_renders_live_then_dims_on_idle(tmp_path: Path) -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    snapshot = _write_bundle(tmp_path)
    frame = bridge_real_fleet.fleet_state_to_world_state(
        {"robots": [{"robot_id": "rosy_45", "online": True, "state_age_s": 5,
                     "state": {"pose": {"x": 0.745, "y": -0.207, "yaw": 0}}}]},
        site_map_sha256="cd" * 32,
        active_map={"sha256": "cd" * 32, "version": 8},
    )
    assert frame is not None
    # A conflicting carry flag ensures only confirmed cargo can make the mesh visible.
    frame["pinky"]["has_cargo"] = True
    frame["pinkys"][1]["has_cargo"] = True
    serve._atomic_write_json(snapshot, frame)
    with serve.make_server(tmp_path, "127.0.0.1", free_port()) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_port}"
        try:
            with playwright.sync_playwright() as pw:
                browser = pw.chromium.launch(**launch_options(), args=["--enable-unsafe-swiftshader"])
                try:
                    page = browser.new_page()
                    failures, requests = [], []
                    page.on("console", lambda msg: failures.append(msg.text) if msg.type == "error" else None)
                    page.on("pageerror", lambda exc: failures.append(str(exc)))
                    page.on("response", lambda res: failures.append(res.url) if res.status == 404 else None)
                    page.on("request", lambda req: requests.append(urlsplit(req.url)))
                    page.goto(f"{origin}/?view=factory&adapter=real")
                    expect = playwright.expect
                    expect(page.locator('[data-adapter="real"]').first).to_have_attribute("aria-pressed", "true")
                    expect(page.locator('[data-world-id="real-site"]')).to_have_attribute("aria-pressed", "true")
                    expect(page.locator("#factory-stream-status")).to_contain_text("실시간 현장")
                    expect(page.locator("#factory-parity")).to_have_text("지도 버전 차이 (번들 v7 / 현장 v8)")
                    expect(page.locator("#factory-scrubber")).to_be_disabled()
                    expect(page.locator("#factory-stages [data-stage][disabled]")).to_have_count(9)
                    page.wait_for_function("window.factoryCargo?.parent.visible && !window.factoryCargo.visible")
                    streams = [parse_qs(req.query) for req in requests if req.path == "/sim/stream"]
                    assert len(streams) == 1 and streams[0]["world"] == ["real-site"] and streams[0]["hz"] == ["5"]
                    paths = [req.path for req in requests]
                    assert paths.index("/sim/stream") < paths.index("/common/meshes/pinky-tray.stl")
                    assert "/data/site-cad.stl.gz" not in paths
                    assert failures == []

                    snapshot.unlink()
                    expect(page.locator("#factory-stream-status")).to_contain_text("데이터 지연")
                    expect(page.locator("#factory-canvas")).to_have_css("opacity", "0.45")
                    expect(page.locator("#factory-canvas")).to_have_attribute("data-stream-state", "idle")

                    page.locator("#factory-adapters [data-adapter=isaac]").click()
                    expect(page.locator("#factory-worlds")).to_have_text("연결된 월드가 없습니다")
                    expect(page.locator("#factory-scrubber")).to_be_enabled()
                    page.wait_for_function("!window.factoryCargo.parent.visible")
                    assert failures == []

                    cache = snapshot.parent / serve.ACTIVE_SITE_MAP_FILE
                    live_map = {
                        "version": 8, "sha256": "cd" * 32, "activated_at": frame["observed_at_ms"] / 1000,
                        "observed_at_ms": frame["observed_at_ms"],
                        "map": {"map_id": "track", "view_turn_deg": 90,
                                "places": [{"id": "S3", "name": "적재 3", "x": 0.745, "y": -0.207},
                                           {"id": "S4", "x": 0.9, "y": -0.2}], "edges": []},
                    }
                    serve._atomic_write_json(cache, live_map)
                    page.locator("#tab-map").click()
                    page.clock.install()
                    page.locator("#map-mode-active").click()
                    expect(page.locator("#map-active-canvas")).to_be_visible()
                    expect(page.locator("#map-readout")).to_contain_text("위치2")
                    received = page.locator("#map-evidence")
                    expect(received).to_have_text(re.compile(r"^지도 v8 · 수신 \d\d:\d\d:\d\d · Fleet 활성 지도$"))
                    expect(received).to_have_attribute("title", re.compile(r"^수신 \S+Z \(UTC\) · 활성 \S+Z \(UTC\)$"))
                    received_v8 = received.inner_text()
                    # D-513 7: the map's view turn reaches World's N mark too; a scale bar is drawn.
                    datum = page.locator("#map-active-canvas + svg.world-map-datum")
                    expect(datum).to_be_visible()
                    expect(datum.locator(".world-map-datum-north")).to_have_attribute("transform", "rotate(90)")
                    expect(datum.locator("text").last).to_have_text(re.compile(r"^0?\.?\d+ m$"))
                    place = page.get_by_label("지도 위치")
                    expect(place.locator("option")).to_have_text(["전체 위치", "적재 3 (S3)", "S4"])
                    canvas = page.locator("#map-active-canvas")
                    canvas.press("ArrowRight")
                    expect(place).to_have_value("S3")
                    expect(canvas).to_have_attribute("aria-label", "Fleet 활성 지도 · 적재 3 (S3)")
                    canvas.press("ArrowLeft")
                    expect(place).to_have_value("")
                    canvas.press("ArrowLeft")
                    expect(place).to_have_value("S4")
                    canvas.press("Home")
                    expect(place).to_have_value("")
                    place.select_option("S4")
                    expect(page.locator("#map-active-canvas")).to_have_attribute("aria-label", "Fleet 활성 지도 · S4")
                    serve._atomic_write_json(cache, {**live_map, "observed_at_ms": live_map["observed_at_ms"] + 1000})
                    page.clock.fast_forward(10_100)
                    expect(received).not_to_have_text(received_v8)
                    expect(place).to_have_value("S4")
                    serve._atomic_write_json(cache, {
                        **live_map, "version": 9, "sha256": "ef" * 32,
                        "observed_at_ms": live_map["observed_at_ms"] + 2000,
                        "map": {**live_map["map"], "places": live_map["map"]["places"][:1]},
                    })
                    page.clock.fast_forward(10_100)
                    expect(received).to_contain_text("지도 v9 · 수신 ")
                    expect(page.locator("#map-readout")).to_contain_text("위치1")
                    expect(place.locator("option")).to_have_text(["전체 위치", "적재 3 (S3)"])
                    expect(place).to_have_value("")
                    page.evaluate("""() => {
                      Object.defineProperty(document, "hidden", { value: true, configurable: true });
                      document.dispatchEvent(new Event("visibilitychange"));
                    }""")
                    expect(page.locator("#map-active-canvas")).to_be_hidden()
                    cache.unlink()
                    held = []
                    route_pattern = "**/api/worlds/real-site/site-map"
                    page.route(route_pattern, lambda route: held.append(route))
                    with page.expect_request(route_pattern):
                        page.evaluate("""() => {
                          delete document.hidden;
                          document.dispatchEvent(new Event("visibilitychange"));
                        }""")
                    expect(page.locator("#map-active-canvas")).to_be_hidden()
                    expect(page.locator("#map-status")).to_have_attribute("state", "pending")
                    held[0].continue_()
                    page.unroute(route_pattern)
                    expect(page.locator("#map-status")).to_have_text("현장 활성 지도 미수신")
                    page.locator("#map-mode-vector").click()
                    expect(page.locator("#map-canvas")).to_be_visible()
                    expect(received).to_have_text(re.compile(r"^지도 v7 · 활성 .+ · Fleet 활성 지도 보관본$"))
                    expect(page.locator("#map-canvas + svg.world-map-datum")).to_be_visible()

                    serve._atomic_write_json(cache, {
                        **live_map, "observed_at_ms": time.time_ns() // 1_000_000 - 38_000,
                    })
                    page.clock.set_system_time(4_102_444_800_000)
                    page.locator("#map-mode-active").click()
                    expect(page.locator("#map-active-canvas")).to_be_visible()
                    page.clock.fast_forward(8_000)
                    assert page.locator("#map-active-canvas").is_hidden()
                    assert place.is_hidden()

                    page.locator("#map-mode-vector").click()
                    held.clear()
                    page.route(route_pattern, lambda route: held.append(route))
                    with page.expect_request(route_pattern):
                        page.locator("#map-mode-active").click()
                    page.clock.fast_forward(2_000)
                    held[0].fulfill(json={"site_map": live_map, "fresh_for_ms": 1_000})
                    page.unroute(route_pattern)
                    expect(page.locator("#map-status")).to_have_text("현장 활성 지도 미수신")
                    assert page.locator("#map-active-canvas").is_hidden()
                    assert failures == []
                finally:
                    browser.close()
        finally:
            server.stop_event.set()
            server.shutdown()
            thread.join()


def test_isaac_freshness_follows_server_age_not_browser_clock(tmp_path: Path) -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    _write_bundle(tmp_path)
    live = tmp_path / "data/isaac-live.json"
    sample = {
        "schema": "rosy.world.isaac-state.v1", "run_id": "run-1", "scene": "conformance", "layout_sha256": None,
        "sim_time_s": 1.0, "reset_count": 0, "state": "running",
        "joints": [{"name": "joint1", "position_rad": 0.1}],
        "objects": [{"id": "box", "frame_id": "world", "position_m": [0, 0, 0], "orientation_xyzw": [0, 0, 0, 1]}],
    }
    writing = threading.Event()
    writing.set()

    def keep_fresh() -> None:
        while writing.is_set():
            serve._atomic_write_json(live, {**sample, "observed_at_ms": time.time_ns() // 1_000_000})
            time.sleep(0.2)

    writer = threading.Thread(target=keep_fresh, daemon=True)
    writer.start()
    with serve.make_server(tmp_path, "127.0.0.1", free_port()) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with playwright.sync_playwright() as pw:
                browser = pw.chromium.launch(**launch_options(), args=["--enable-unsafe-swiftshader"])
                try:
                    page = browser.new_page()
                    # A browser clock a day ahead used to mark every SIM sample as expired.
                    page.clock.install(time=int((time.time() + 86_400) * 1000))
                    page.goto(f"http://127.0.0.1:{server.server_port}/")
                    page.locator("#tab-cell").click()
                    page.locator("#isaac-status-toggle").click()
                    health = page.locator("#isaac-health")
                    playwright.expect(health).to_have_text("Isaac · 최신")
                    writing.clear()
                    writer.join()
                    serve._atomic_write_json(live, {**sample, "observed_at_ms": time.time_ns() // 1_000_000 - 10_000})
                    playwright.expect(health).to_have_text("Isaac · 지연")
                    playwright.expect(page.locator("#isaac-status")).to_have_text(
                        re.compile(r"^지연 · 1\d초 전 · 최근 SIM 관측이 없습니다\.$"))
                    live.unlink()
                    playwright.expect(health).to_have_text("Isaac · 정보 없음")
                finally:
                    browser.close()
        finally:
            writing.clear()
            server.stop_event.set()
            server.shutdown()
            thread.join()


def test_recording_return_restores_matching_record_paused(tmp_path: Path) -> None:
    playwright = pytest.importorskip("playwright.sync_api")
    _write_bundle(tmp_path)
    path = tmp_path / "data/recording.json"
    recording = json.loads(path.read_text(encoding="utf-8"))
    recording["samples"].append({**recording["samples"][0], "offset_ms": 100_000})
    serve._atomic_write_json(path, recording)

    with serve.make_server(tmp_path, "127.0.0.1", free_port()) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_port}"
        try:
            with playwright.sync_playwright() as pw:
                browser = pw.chromium.launch(**launch_options(), args=["--enable-unsafe-swiftshader"])
                page = browser.new_page()
                play = page.locator("#rec-play")
                slider = page.locator("#rec-range")
                page.goto(origin + "/?view=run")
                playwright.expect(play).to_have_attribute("aria-pressed", "true")
                slider.evaluate("el => { el.value = 15000; el.dispatchEvent(new Event('input')); }")
                page.reload()
                playwright.expect(play).to_have_attribute("aria-pressed", "false")
                playwright.expect(slider).to_have_value("15000")
                page.locator("#tab-rec").press("Home")
                page.reload()
                playwright.expect(page.locator("#tab-map")).to_have_attribute("aria-selected", "true")
                page.goto(origin + "/")
                page.locator("#tab-rec").click()
                playwright.expect(slider).to_be_visible()
                slider.evaluate("el => { el.value = 21000; el.dispatchEvent(new Event('input')); }")
                page.goto(origin + "/manifest.json")
                page.go_back()
                playwright.expect(slider).to_be_visible()
                playwright.expect(slider).to_have_value("21000")
                playwright.expect(play).to_have_attribute("aria-pressed", "false")
                serve._atomic_write_json(path, {**recording, "source": "replacement"})
                page.reload()
                playwright.expect(slider).to_be_visible()
                playwright.expect(slider).to_have_value("0")
                page.route("**/data/recording.json", lambda route: route.abort())
                page.reload()
                playwright.expect(page.locator("#tab-rec")).to_have_attribute("aria-selected", "true")
                page.locator("#tab-map").click()
                page.reload()
                playwright.expect(page.locator("#tab-map")).to_have_attribute("aria-selected", "true")
                browser.close()
        finally:
            server.stop_event.set()
            server.shutdown()
            thread.join()
