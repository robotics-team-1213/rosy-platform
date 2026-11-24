"""Browser coverage for the real-site factory on the standalone World server."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import shutil
import struct
import sys
import threading
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
    (data / "site-map.json").write_text(json.dumps({"sha256": "ab" * 32, "version": 7}), encoding="utf-8")
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
                finally:
                    browser.close()
        finally:
            server.stop_event.set()
            server.shutdown()
            thread.join()
