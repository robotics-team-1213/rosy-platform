// D-789 robot camera over WHEP from the site media service. One shared client for every viewer:
// CORE issues a short read grant, the site authority turns it into viewer demand, and the browser
// plays MediaMTX's WHEP answer in a <video>. Tokens go only in the Authorization header, never a URL.
// Freshness comes from the capture watermark in the rendered pixels (rosy_media_edge/watermark.py),
// never from a heartbeat: an unreadable or unchanging frame turns stale after 1 s and hidden after 2 s.

export const MEDIA_GRANT_PATH = "/api/v1/vision/media/grants";
export const STALE_WARN_MS = 1000;
export const STALE_HIDE_MS = 2000;
export const RENEW_MS = 20000;
const ICE_TIMEOUT_MS = 8000;
const READY_TIMEOUT_MS = 9000;      // inside the authority's 10 s startup demand
const READY_RETRY_MS = 500;
const CHECK_MS = 250;

// Watermark v1: 4x4 luma cells, 32 per row in a 128x24 strip; magic "RM", version 1,
// uint32 epoch, uint32 sequence, uint64 capture ms (network order), CRC32 of those 19 bytes.
const CELL = 4, COLS = 32, SIZE = 23;
export const WATERMARK_WIDTH = 128, WATERMARK_HEIGHT = 24;

function crc32(bytes) {
  let crc = ~0;
  for (const byte of bytes) {
    crc ^= byte;
    for (let k = 0; k < 8; k += 1) crc = (crc >>> 1) ^ (0xEDB88320 & -(crc & 1));
  }
  return (~crc) >>> 0;
}

export function readWatermark(rgba, width = WATERMARK_WIDTH) {
  const packet = new Uint8Array(SIZE);
  for (let bit = 0; bit < SIZE * 8; bit += 1) {
    const x = (bit % COLS) * CELL + 1, y = Math.floor(bit / COLS) * CELL + 1;
    let sum = 0;
    for (let row = 0; row < 2; row += 1) {
      for (let col = 0; col < 2; col += 1) {
        const at = ((y + row) * width + x + col) * 4;
        sum += rgba[at] + rgba[at + 1] + rgba[at + 2];
      }
    }
    const value = sum / 12;
    if (value > 80 && value < 175) return null;       // ambiguous cell: identity unknown
    if (value >= 175) packet[bit >> 3] |= 1 << (7 - (bit % 8));
  }
  const view = new DataView(packet.buffer);
  if (crc32(packet.subarray(0, SIZE - 4)) !== view.getUint32(SIZE - 4)) return null;
  if (packet[0] !== 0x52 || packet[1] !== 0x4d || packet[2] !== 1) return null;
  return {epoch: view.getUint32(3), sequence: view.getUint32(7), capturedMs: Number(view.getBigUint64(11))};
}

function canvasReader() {
  let canvas = null;
  return (video) => {
    if (!video.videoWidth) return null;
    canvas ??= Object.assign(document.createElement("canvas"), {width: WATERMARK_WIDTH, height: WATERMARK_HEIGHT});
    const context = canvas.getContext("2d", {willReadFrequently: true});
    context.drawImage(video, 0, 0, WATERMARK_WIDTH, WATERMARK_HEIGHT, 0, 0, WATERMARK_WIDTH, WATERMARK_HEIGHT);
    return readWatermark(context.getImageData(0, 0, WATERMARK_WIDTH, WATERMARK_HEIGHT).data);
  };
}

// → grant receipt, or null when this robot has no site media (503 MEDIA_UNAVAILABLE, or 404 from a CORE
// without the route): stay on JPEG.
export async function requestMediaGrant(postJson, robotId) {
  const result = await postJson(MEDIA_GRANT_PATH, {robot_id: robotId});
  if (result.status === 201) return result.body;
  if (result.status === 503 || result.status === 404) return null;
  throw Object.assign(new Error(`영상 권한 거절 (${result.status})`), {status: result.status});
}

function siteOrigin(grant) {
  const site = new URL(grant.site_url);
  if (site.protocol !== "https:" || site.username || site.password || site.search || site.hash
      || !/^robots\/[A-Za-z0-9._-]{1,96}\/front$/.test(grant.path)) {
    throw new Error("영상 서버 주소를 확인하세요.");
  }
  return site.origin;
}

export async function openCamera({
  grant, video, onState = () => {},
  renewGrant,                           // (grant_id) => Promise<grant>  — CORE re-authorises
  revokeGrant = async () => {},         // (grant_id) => Promise          — best effort on close
  fetchImpl = (...args) => fetch(...args),
  Peer = globalThis.RTCPeerConnection,
  readFrame = canvasReader(),
  schedule = (fn, ms) => { const id = setTimeout(fn, ms); return () => clearTimeout(id); },
  repeat = (fn, ms) => { const id = setInterval(fn, ms); return () => clearInterval(id); },
  now = () => Date.now(),
}) {
  const origin = siteOrigin(grant);
  let current = grant, closed = false, resource = null, pc = null;
  const cancels = [];
  const wait = (ms) => new Promise((resolve) => cancels.push(schedule(resolve, ms)));
  const call = (path, init = {}) => fetchImpl(path.startsWith("http") ? path : origin + path, {
    credentials: "omit", redirect: "error", cache: "no-store", ...init,
    headers: {...(init.headers ?? {}), Authorization: `Bearer ${current.token}`},
  });
  const emit = (state) => { if (!closed) onState({transport: "webrtc", ...state}); };

  function close(reason = "closed") {
    if (closed) return;
    emit({state: "closed", reason, fps: 0, ageMs: null});
    closed = true;
    cancels.splice(0).forEach((cancel) => cancel());
    if (resource) call(resource, {method: "DELETE"}).catch(() => {});
    revokeGrant(current.grant_id).catch(() => {});
    pc?.close();
    video.srcObject = null;
  }
  function lose(reason) { emit({state: "lost", reason, fps: 0, ageMs: null}); close(reason); }

  try {
    emit({state: "connecting", fps: 0, ageMs: null});
    const intent = await call("/v1/intents", {method: "POST"});
    if (intent.status !== 201) throw Object.assign(new Error("영상 시작 거절"), {status: intent.status});
    pc = new Peer({iceServers: []});
    pc.addTransceiver("video", {direction: "recvonly"});
    pc.ontrack = (event) => { video.srcObject = event.streams?.[0] ?? new MediaStream([event.track]); };
    await pc.setLocalDescription(await pc.createOffer());
    if (pc.iceGatheringState !== "complete") {
      await Promise.race([
        new Promise((resolve) => pc.addEventListener("icegatheringstatechange", () => {
          if (pc.iceGatheringState === "complete") resolve();
        })),
        wait(ICE_TIMEOUT_MS).then(() => { throw new Error("ICE 준비 시간 초과"); }),
      ]);
    }
    const until = now() + READY_TIMEOUT_MS;
    let answer = null;
    while (!closed) {
      // MediaMTX answers 404 until the robot publisher (started by our demand) is up.
      const response = await call(`/${current.path}/whep`, {
        method: "POST", headers: {"Content-Type": "application/sdp"}, body: pc.localDescription.sdp});
      if (response.status === 201) {
        const location = new URL(response.headers.get("Location"), origin + "/");
        if (location.origin !== origin) throw new Error("영상 세션 주소가 바뀌었습니다.");
        resource = location.href;
        answer = await response.text();
        break;
      }
      if (![404, 503].includes(response.status) || now() >= until) {
        throw Object.assign(new Error("영상 연결 거절"), {status: response.status});
      }
      await wait(READY_RETRY_MS);
    }
    if (closed) return {close};
    await pc.setRemoteDescription({type: "answer", sdp: answer});
  } catch (error) {
    close("failed");
    throw error;
  }

  pc.onconnectionstatechange = () => {
    if (["failed", "closed", "disconnected"].includes(pc.connectionState)) lose("ice");
  };
  cancels.push(repeat(async () => {
    try {
      current = await renewGrant(current.grant_id);
      const renewed = await call("/v1/session/renew", {method: "POST"});
      if (!renewed.ok) lose("revoked");
    } catch (_error) { lose("revoked"); }
  }, RENEW_MS));

  let epoch = null, sequence = null, advancedAt = null, identity = null;
  const rendered = [];
  cancels.push(repeat(() => {
    const t = now();
    let seen = null;
    try { seen = readFrame(video); } catch (_error) { seen = null; }
    if (seen && (epoch !== seen.epoch || sequence === null || seen.sequence > sequence)) {
      ({epoch, sequence} = seen);
      advancedAt = t;
      identity = seen;
    }
    const total = video.getVideoPlaybackQuality?.().totalVideoFrames ?? 0;
    rendered.push([t, total]);
    while (rendered.length > 1 && t - rendered[0][0] > 1000) rendered.shift();
    const span = t - rendered[0][0];
    const fps = span > 0 ? Math.round(((total - rendered[0][1]) * 1000) / span) : 0;
    const ageMs = advancedAt === null ? null : t - advancedAt;
    const state = advancedAt === null ? "waiting"            // first/reconnect IDR not rendered yet
      : ageMs > STALE_HIDE_MS ? "hidden" : ageMs > STALE_WARN_MS ? "stale" : "live";
    emit({state, fps, ageMs, readable: seen !== null, sequence: identity?.sequence ?? null,
          capturedMs: identity?.capturedMs ?? null});
  }, CHECK_MS));
  return {close};
}
