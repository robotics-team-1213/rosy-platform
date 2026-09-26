"""Actual Chromium recording from the authenticated preview's JPEG shape."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from browser_harness import open_page


CAPTURE_JS = Path(__file__).resolve().parents[1] / "src/hmi/dashboard/camera-capture.js"
pytestmark = pytest.mark.skipif(
    os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
    reason="set ROSY_RUN_BROWSER_TESTS=1 to run Chromium capture",
)


def test_chromium_records_real_webm_jpeg_and_operation_manifest():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser, page, errors = open_page(playwright, 640, 480)
        try:
            page.route("http://rosy.test/", lambda route: route.fulfill(
                status=200, content_type="text/html", body="<!doctype html><body></body>"))
            page.route("http://rosy.test/assets/camera-capture.js", lambda route: route.fulfill(
                status=200, content_type="application/javascript",
                body=CAPTURE_JS.read_text(encoding="utf-8")))
            page.goto("http://rosy.test/", wait_until="load")
            result = page.evaluate("""async () => {
              const module = await import('/assets/camera-capture.js');
              const source = document.createElement('canvas');
              source.width = 64; source.height = 48;
              const context = source.getContext('2d');
              context.fillStyle = 'red'; context.fillRect(0, 0, 64, 48);
              const jpeg = await new Promise(resolve => source.toBlob(resolve, 'image/jpeg'));
              const image = new Image();
              image.src = URL.createObjectURL(jpeg); await image.decode();
              const saved = [];
              let resolveDone;
              const done = new Promise(resolve => { resolveDone = resolve; });
              const capture = module.createCameraCapture({
                save: (media, name) => saved.push({media, name}),
                onComplete: () => resolveDone(),
              });
              capture.acceptFrame({image, blob: jpeg, sequence: 1, source: 'PINKY'});
              await capture.screenshot('pc');
              const started = capture.start();
              capture.recordAction(module.classifyOperation('POST', '/api/v1/teleop', 200));
              await new Promise(resolve => setTimeout(resolve, 1200));
              capture.stop();
              await Promise.race([done, new Promise((_resolve, reject) =>
                setTimeout(() => reject(new Error('recorder did not stop')), 5000))]);
              await capture.saveVideo('pc'); capture.saveOperations();
              const imageBytes = new Uint8Array(await saved[0].media.arrayBuffer());
              const videoBytes = new Uint8Array(await saved[1].media.arrayBuffer());
              const operations = JSON.parse(await saved[2].media.text()).operations;
              return {started, names: saved.map(item => item.name),
                imageStart: Array.from(imageBytes.slice(0, 2)),
                videoStart: Array.from(videoBytes.slice(0, 4)),
                videoBytes: videoBytes.length, operations};
            }""")
            assert result["started"] is True
            assert [name.rsplit(".", 1)[-1] for name in result["names"]] == ["jpg", "webm", "json"]
            assert result["imageStart"] == [255, 216]
            assert result["videoStart"] == [26, 69, 223, 163]
            assert result["videoBytes"] > 100
            assert result["operations"][0]["action"] == "수동 운전"
            assert result["operations"][0]["result"] == "accepted"
            assert errors == []
        finally:
            browser.close()
