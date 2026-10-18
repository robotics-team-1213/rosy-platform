"""D-789 T4: drive screen transport choice — WebRTC default, JPEG-only fallback, never two at once.

drive-video.js with its imports replaced by recorded fakes (Node subprocess). Real playback in
Chromium is test/test_webrtc_loopback.py; tablet/Android playback is DEVICE and unverified.
"""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

MODULE = Path(__file__).resolve().parents[1] / "screens/drive-video.js"

HARNESS = r"""
const log = [];
const vision = {running: true, start() { if (!this.running) log.push("poll:start"); this.running = true; },
                stop() { if (this.running) log.push("poll:stop"); this.running = false; }};
let grantStatus = 201, openResult = "ok", onState = null, closed = [];
const node = () => ({hidden: false, textContent: "", dataset: {}, after() {}, remove() {}, append() {}});
globalThis.deps = {
  api: async (path, init) => { log.push(`api:${init.method}`); return {status: 204}; },
  connectionOffer: async () => ({robotId: "rosy_01"}),
  postJson: async () => ({status: 200, body: {}}),
  authHeaders: () => ({}),
  createDriverStream: () => ({start: () => log.push("mjpeg:start"), stop: () => {}}),
  MIN_PULL_INTERVAL_MS: 420, STREAM_STALE_WARN_MS: 1000, MEDIA_GRANT_PATH: "/api/v1/vision/media/grants",
  requestMediaGrant: async () => grantStatus === 503 ? null : {grant_id: "g", token: "t"},
  openCamera: async (options) => {
    log.push(vision.running ? "webrtc:open-while-polling" : "webrtc:open");
    onState = options.onState;
    if (openResult !== "ok") throw new Error("ICE timeout");
    return {close: (reason) => { closed.push(reason); options.onState({state: "closed", reason}); }};
  },
  el: () => node(),
};
const element = {frame: node(), empty: node()};
const capture = {mode: "raw", state() { return {previewMode: this.mode}; }, unavailable() {}, acceptFrame() {}};
const root = {querySelector: () => node()};
const settle = async () => { for (let i = 0; i < 10; i += 1) await new Promise((r) => setImmediate(r)); };
"""


def run_js(body, setup=""):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is unavailable")
    script = f"""
import fs from 'node:fs';
let source = fs.readFileSync({json.dumps(str(MODULE))}, 'utf8').replace(/^import .*$/gm, "");
source = "const {{api, connectionOffer, postJson, authHeaders, createDriverStream, MIN_PULL_INTERVAL_MS, "
  + "STREAM_STALE_WARN_MS, MEDIA_GRANT_PATH, openCamera, requestMediaGrant, el}} = globalThis.deps;" + source;
{HARNESS}
{setup}
const drive = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const video = drive.mountDriveVideo({{root, element, capture, vision, acceptPreview: () => {{}}}});
await settle();
{body}
video.stop();
console.log(JSON.stringify({{log, closed}}));
"""
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True,
                            text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def test_site_media_robot_stops_polling_before_webrtc_opens():
    result = run_js("")
    assert result["log"][:2] == ["poll:stop", "webrtc:open"]
    assert "mjpeg:start" not in result["log"]


def test_lost_webrtc_falls_back_to_jpeg_poll_never_mjpeg():
    result = run_js('onState({state: "lost", reason: "ice"}); await settle();')
    assert result["log"] == ["poll:stop", "webrtc:open", "poll:start"]


def test_failed_webrtc_open_polls_jpeg_only():
    result = run_js("", setup='openResult = "fail";')
    assert result["log"] == ["poll:stop", "webrtc:open", "poll:start"]


def test_robot_without_site_media_keeps_the_existing_d368_path():
    result = run_js("", setup="grantStatus = 503;")
    assert result["log"] == ["mjpeg:start"]


def test_annotated_mode_closes_webrtc_and_polls_pairs():
    result = run_js('capture.mode = "annotated"; video.previewModeChanged("annotated"); await settle();')
    assert result["closed"] == ["stopped"]
    assert result["log"] == ["poll:stop", "webrtc:open", "poll:start"]
    assert "mjpeg:start" not in result["log"]


def test_repeated_webrtc_failure_backs_off_to_five_minutes_and_online_resets():
    setup = ('openResult = "fail"; const timers = [], bus = new EventTarget();'
             'globalThis.addEventListener = bus.addEventListener.bind(bus);'
             'globalThis.removeEventListener = bus.removeEventListener.bind(bus);'
             'globalThis.dispatchEvent = bus.dispatchEvent.bind(bus);'
             'globalThis.setTimeout = (fn, ms) => { timers.push(fn); log.push(`retry:${ms}`); return timers.length; };'
             'globalThis.clearTimeout = () => {};')
    body = ("for (let i = 0; i < 6; i += 1) { timers.at(-1)(); await settle(); }"
            "globalThis.dispatchEvent(new Event('online')); await settle();")
    result = run_js(body, setup=setup)
    delays = [int(item.split(":")[1]) for item in result["log"] if item.startswith("retry:")]
    assert delays == [15000, 30000, 60000, 120000, 240000, 300000, 300000, 500]
