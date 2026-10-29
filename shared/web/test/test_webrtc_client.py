"""D-789 T4: the shared WHEP client — header-only tokens, real teardown, render-based freshness.

Node subprocess with fake fetch/RTCPeerConnection/timers. Real Chromium WHEP playback is
test/test_webrtc_loopback.py on the prepared media host; Android stays DEVICE (unverified).
"""

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[3]
MODULE = REPO / "shared/web/webrtc.js"

HARNESS = r"""
const timers = [];
let clock = 0;
const schedule = (fn, ms) => { const t = {at: clock + ms, fn, every: 0}; timers.push(t); return () => t.dead = true; };
const repeat = (fn, ms) => { const t = {at: clock + ms, fn, every: ms}; timers.push(t); return () => t.dead = true; };
async function advance(ms) {
  const end = clock + ms;
  for (;;) {
    await new Promise((resolve) => setImmediate(resolve));   // let pending awaits register timers
    const due = timers.filter((t) => !t.dead && t.at <= end).sort((a, b) => a.at - b.at)[0];
    if (!due) break;
    clock = due.at;
    if (due.every) due.at += due.every; else due.dead = true;
    await due.fn();
  }
  clock = end;
}
const calls = [];
let whep404 = 1, renewStatus = 200, intentStatus = 201;
async function fetchImpl(url, init) {
  calls.push({url, method: init.method, auth: init.headers.Authorization, credentials: init.credentials});
  const reply = (status, body = "", headers = {}) => ({status, ok: status < 300,
    headers: {get: (name) => headers[name] ?? null}, text: async () => body});
  if (url.endsWith("/v1/intents")) return reply(intentStatus);
  if (url.endsWith("/whep")) return whep404-- > 0 ? reply(404) : reply(201, "v=0 answer", {Location: "/robots/rosy_01/front/whep/abc"});
  if (url.endsWith("/v1/session/renew")) return reply(renewStatus);
  return reply(200);
}
class Peer {
  constructor() { Peer.last = this; this.closed = false; this.iceGatheringState = "complete"; }
  addTransceiver(kind, init) { this.transceiver = [kind, init.direction]; }
  async createOffer() { return {type: "offer", sdp: "v=0 offer"}; }
  async setLocalDescription(d) { this.localDescription = d; }
  async setRemoteDescription(d) { this.remote = d; this.ontrack({streams: ["received-stream"]}); }
  addEventListener() {}
  close() { this.closed = true; }
}
let playError = null;
const video = {srcObject: null, hidden: true, paused: true,
  async play() {
    if (!this.srcObject) throw new Error("play before stream");
    if (playError) throw playError;
    this.paused = false;
  },
  getVideoPlaybackQuality: () => ({totalVideoFrames: Math.floor(clock / 66)})};
let frame = null;
const states = [], revoked = [];
const grant = {grant_id: "a".repeat(32), token: "read-1", site_url: "https://media.site.example",
               path: "robots/rosy_01/front"};
const options = (extra = {}) => ({grant, video, fetchImpl, Peer, schedule, repeat, now: () => clock,
  readFrame: () => frame, onState: (s) => states.push(s),
  renewGrant: async (id) => ({...grant, token: "read-2"}), revokeGrant: async (id) => revoked.push(id), ...extra});
"""


def run_js(body):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is unavailable")
    script = f"""
import fs from 'node:fs';
const source = fs.readFileSync({json.dumps(str(MODULE))}, 'utf8');
const media = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
{HARNESS}
{body}
"""
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True,
                            text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def stamped_rgba(**identity):
    sys.path.insert(0, str(REPO / "middleware/media/src"))
    from rosy_media_edge.watermark import stamp_rgb
    rgb = bytearray(128 * 24 * 3)
    stamp_rgb(rgb, 128, 24, **identity)
    return [value for index in range(0, len(rgb), 3) for value in (*rgb[index:index + 3], 255)]


def test_watermark_matches_the_robot_encoder_and_rejects_corruption():
    rgba = stamped_rgba(epoch=17, sequence=4242, captured_ms=1_760_000_000_123)
    broken = list(rgba)
    for at in range(0, 4 * 128 * 4, 4):   # invert the first row of cells: magic and CRC must fail
        broken[at:at + 3] = [255 - value for value in broken[at:at + 3]]
    result = run_js(f"""
    console.log(JSON.stringify([media.readWatermark(new Uint8Array({json.dumps(rgba)})),
                                media.readWatermark(new Uint8Array({json.dumps(broken)})),
                                media.readWatermark(new Uint8Array(128 * 24 * 4).fill(128))]));
    """)
    assert result[0] == {"epoch": 17, "sequence": 4242, "capturedMs": 1_760_000_000_123}
    assert result[1] is None and result[2] is None


def test_grant_request_keeps_jpeg_for_robots_without_site_media():
    result = run_js("""
    const post = (status) => async () => ({status, body: {grant_id: "x"}});
    const out = [await media.requestMediaGrant(post(201), "rosy_01"), await media.requestMediaGrant(post(503), "rosy_01"),
                 await media.requestMediaGrant(post(404), "rosy_01")];
    try { await media.requestMediaGrant(post(403), "rosy_01"); } catch (e) { out.push(e.status); }
    console.log(JSON.stringify(out));
    """)
    assert result == [{"grant_id": "x"}, None, None, 403]


def test_open_waits_for_publisher_and_sends_token_only_in_header():
    result = run_js("""
    const opening = media.openCamera(options());
    await advance(600);
    await opening;
    console.log(JSON.stringify({calls, transceiver: Peer.last.transceiver, remote: Peer.last.remote}));
    """)
    urls = [call["url"] for call in result["calls"]]
    assert urls == ["https://media.site.example/v1/intents",
                    "https://media.site.example/robots/rosy_01/front/whep",
                    "https://media.site.example/robots/rosy_01/front/whep"]
    assert all(call["auth"] == "Bearer read-1" and call["credentials"] == "omit" for call in result["calls"])
    assert all("read-1" not in url for url in urls)
    assert result["transceiver"] == ["video", "recvonly"]
    assert result["remote"] == {"type": "answer", "sdp": "v=0 answer"}


def test_hidden_video_starts_playback_before_waiting_for_rendered_freshness():
    result = run_js("""
    const opening = media.openCamera(options()); await advance(600); const camera = await opening;
    console.log(JSON.stringify({stream: video.srcObject, paused: video.paused, hidden: video.hidden}));
    camera.close();
    """)
    assert result == {"stream": "received-stream", "paused": False, "hidden": True}


def test_playback_rejection_closes_peer_session_and_revokes_grant():
    result = run_js("""
    playError = new Error("playback denied");
    const opening = media.openCamera(options()).catch(e => e.message);
    await advance(600); const error = await opening;
    await advance(0);
    console.log(JSON.stringify({error, closed: Peer.last.closed, video: video.srcObject, revoked,
      deletes: calls.filter(c => c.method === "DELETE").length}));
    """)
    assert result == {"error": "playback denied", "closed": True, "video": None,
                      "revoked": ["a" * 32], "deletes": 1}


def test_playback_that_never_starts_releases_session_within_ice_timeout():
    result = run_js("""
    const opening = media.openCamera(options({video: {...video, play: () => new Promise(() => {})}}))
      .catch(e => e.message);
    await advance(9000); const error = await opening;
    console.log(JSON.stringify({error, closed: Peer.last.closed, revoked}));
    """)
    assert result == {"error": "영상 재생 시작 시간 초과", "closed": True, "revoked": ["a" * 32]}


def test_refused_intent_releases_peer_and_grant():
    result = run_js("""
    intentStatus = 403;
    let error = null;
    try { await media.openCamera(options()); } catch (e) { error = e.status; }
    console.log(JSON.stringify({error, revoked, peer: Peer.last ?? null, states: states.map((s) => s.state)}));
    """)
    assert result["error"] == 403
    assert result["revoked"] == ["a" * 32] and result["peer"] is None
    assert result["states"] == ["connecting", "closed"]


def test_publisher_never_ready_fails_inside_the_startup_demand():
    result = run_js("""
    whep404 = 1000;
    const opening = media.openCamera(options()).catch((e) => ({status: e.status}));
    await advance(10000);
    const error = await opening;
    console.log(JSON.stringify({error, closed: Peer.last.closed, video: video.srcObject}));
    """)
    assert result == {"error": {"status": 404}, "closed": True, "video": None}


def test_renewal_refusal_tears_down_the_real_session():
    result = run_js("""
    const opening = media.openCamera(options()); await advance(600); await opening;
    renewStatus = 403;
    await advance(20000);
    const tail = calls.slice(-2).map((c) => [c.method, c.url, c.auth]);
    console.log(JSON.stringify({tail, revoked, closed: Peer.last.closed,
                                lost: states.find((s) => s.state === "lost")?.reason}));
    """)
    assert result["tail"] == [["POST", "https://media.site.example/v1/session/renew", "Bearer read-2"],
                              ["DELETE", "https://media.site.example/robots/rosy_01/front/whep/abc", "Bearer read-2"]]
    assert result["revoked"] == ["a" * 32] and result["closed"] is True
    assert result["lost"] == "revoked"


def test_freshness_comes_from_rendered_watermark_sequence():
    result = run_js("""
    const opening = media.openCamera(options()); await advance(600); await opening;
    const at = () => states[states.length - 1];
    const seen = [];
    await advance(250); seen.push(at().state);                 // no readable frame yet: waiting for IDR
    frame = {epoch: 1, sequence: 1, capturedMs: 5};
    await advance(250); seen.push(at().state);
    frame = {epoch: 1, sequence: 2, capturedMs: 6};
    await advance(250); seen.push(at().state, at().sequence);
    await advance(1250); seen.push(at().state);                // same frame for >1 s: stale warning
    frame = null;                                              // unreadable never refreshes
    await advance(1000); seen.push(at().state);                // >2 s: hidden
    frame = {epoch: 2, sequence: 1, capturedMs: 7};            // producer restart resets sequence
    await advance(250); seen.push(at().state, at().fps > 0);
    console.log(JSON.stringify(seen));
    """)
    assert result == ["waiting", "live", "live", 2, "stale", "hidden", "live", True]


def test_close_is_idempotent_and_releases_everything():
    result = run_js("""
    const opening = media.openCamera(options()); await advance(600); const camera = await opening;
    camera.close(); camera.close();
    const before = calls.length;
    await advance(60000);
    console.log(JSON.stringify({deletes: calls.filter((c) => c.method === "DELETE").length,
                                after: calls.length - before, revoked, closed: Peer.last.closed}));
    """)
    assert result == {"deletes": 1, "after": 0, "revoked": ["a" * 32], "closed": True}


def test_site_origin_must_be_https_without_credentials():
    result = run_js("""
    const out = [];
    for (const site_url of ["http://media.site.example", "https://u:p@media.site.example"]) {
      try { await media.openCamera(options({grant: {...grant, site_url}})); out.push("opened"); }
      catch (e) { out.push("refused"); }
    }
    console.log(JSON.stringify({out, calls: calls.length}));
    """)
    assert result == {"out": ["refused", "refused"], "calls": 0}
