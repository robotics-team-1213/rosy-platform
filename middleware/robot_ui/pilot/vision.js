// 전방 카메라 미리보기 폴링(D-323 T7). dashboard vision.js 팩토리 패턴:
// 자격·전송은 주입받고, 주기·시퀀스·중단 상태는 이 모듈이 가진다.
// 409(시퀀스 진행)는 오류가 아니라 다음 틱에서 재시도한다 — 프레임을 숨기지 않는다.
// 주기는 CORE 계약의 하한(vision.preview_min_pull_interval_s ≥ 0.4s)보다 짧으면 안 된다.
// 더 자주 당기면 429 만 늘고, 그 요청들이 teleop 과 같은 브라우저 연결 풀을 잡아먹는다.

import {fetchCameraPair} from "/common/evidence.js";

export const MIN_PULL_INTERVAL_MS = 420;

// ---------------------------------------------------------------------------
// D-368 운전자 MJPEG 스트림 — 폴링 대체. 같은 자격(Authorization 헤더, D-193)으로
// 연결 하나를 열어 새 시퀀스만 받는다. 서버가 409하면(운전자 아님·이미 열림) 폴링에
// 머문다. 토큰은 URL에 두지 않는다.
// ---------------------------------------------------------------------------
export const STREAM_PATH = "/api/v1/vision/front/stream";
export const STREAM_STALE_WARN_MS = 1000;   // HUD 경고전환선(D-368 §5)
const STATS_INTERVAL_MS = 250;
const BOUNDARY = "--frame";
const _encoder = new TextEncoder();
const _decoder = new TextDecoder();

// multipart 증분 파서 — 순수 함수 모음. Node 시험이 이 부분만 읽는다.
export function createMultipartParser({boundary = BOUNDARY, onPart}) {
  const marker = _encoder.encode(boundary);
  let buffer = new Uint8Array(0);

  function find(hay, needle, from) {
    const limit = hay.length - needle.length;
    for (let i = from; i <= limit; i += 1) {
      let hit = true;
      for (let j = 0; j < needle.length; j += 1) {
        if (hay[i + j] !== needle[j]) { hit = false; break; }
      }
      if (hit) return i;
    }
    return -1;
  }

  function push(chunk) {
    const incoming = chunk instanceof Uint8Array ? chunk : new Uint8Array(chunk);
    if (!incoming.length) return;
    const merged = new Uint8Array(buffer.length + incoming.length);
    merged.set(buffer); merged.set(incoming, buffer.length);
    buffer = merged;
    for (;;) {
      const start = find(buffer, marker, 0);
      if (start < 0) { trim(); return; }
      const headEnd = find(buffer, _encoder.encode("\r\n\r\n"), start);
      if (headEnd < 0) { trim(); return; }
      const headText = _decoder.decode(buffer.slice(start, headEnd));
      const headers = {};
      for (const line of headText.split("\r\n").slice(1)) {
        const at = line.indexOf(":");
        if (at > 0) headers[line.slice(0, at).trim().toLowerCase()] = line.slice(at + 1).trim();
      }
      const length = Number(headers["content-length"] ?? NaN);
      if (!Number.isFinite(length)) { buffer = buffer.slice(headEnd + 4); continue; }
      const bodyStart = headEnd + 4;
      if (buffer.length < bodyStart + length) { trim(); return; }
      onPart({headers, body: buffer.slice(bodyStart, bodyStart + length)});
      buffer = buffer.slice(bodyStart + length);
    }
  }

  // 헤더 시작 전 잔여 바이트는 어차피 버린다 — 경계 앞 청크만 유지.
  function trim() {
    const start = find(buffer, marker, 0);
    if (start > 0) buffer = buffer.slice(start);
    if (buffer.length > 1_500_000) buffer = new Uint8Array(0);   // 거부된 흐름 방어
  }

  return {push};
}

export function createDriverStream({
  fetchImpl = (...args) => fetch(...args),
  headers,                       // () => headers object (Authorization 포함)
  onFrame,                       // (blobUrl, meta{seq, source, capturedAt}) => void
  onStats,                       // ({fps, ageMs}) => void — HUD
  onLost,                        // (detail{status?, reason}) => void — 폴백 신호
  schedule = (fn, ms) => { const id = setTimeout(fn, ms); return () => clearTimeout(id); },
  now = () => Date.now(),
}) {
  let controller = null;
  let stopped = false;
  let objectUrl = null;
  let frameTimes = [];
  let lastFrameAt = null;
  let statsAt = -Infinity;
  let statsTimer = null;

  function release() { if (objectUrl) URL.revokeObjectURL(objectUrl); objectUrl = null; }

  function emitStats() {
    if (!onStats) return;
    const t = now();
    if (t - statsAt < STATS_INTERVAL_MS) return;
    statsAt = t;
    frameTimes = frameTimes.filter((at) => t - at <= 1000);
    onStats({fps: frameTimes.length, ageMs: lastFrameAt == null ? null : t - lastFrameAt});
  }

  function teardown(reason, status) {
    if (statsTimer) { statsTimer(); statsTimer = null; }
    release();
    lastFrameAt = null;
    frameTimes = [];
    if (onStats) onStats({fps: 0, ageMs: null});
    if (!stopped && onLost) onLost({reason, status});
  }

  async function connect(overlay) {
    controller = new AbortController();
    try {
      const response = await fetchImpl(`${STREAM_PATH}?overlay=${overlay === true}`, {
        headers: headers(), cache: "no-store", signal: controller.signal,
      });
      if (!response.ok || !response.body) {
        teardown("refused", response.status);
        return;
      }
      const parser = createMultipartParser({
        onPart: ({headers: part, body}) => {
          const blob = new Blob([body], {type: "image/jpeg"});
          release();
          objectUrl = URL.createObjectURL(blob);
          lastFrameAt = now();
          frameTimes.push(lastFrameAt);
          emitStats();
          onFrame?.(objectUrl, {
            blob,
            seq: Number(part["x-rosy-camera-sequence"] ?? 0),
            source: part["x-rosy-camera-source"] ?? "UNKNOWN",
            capturedAt: Number(part["x-rosy-camera-captured-at"] ?? NaN),
          });
        },
      });
      const reader = response.body.getReader();
      statsTimer = schedule(emitStats, STATS_INTERVAL_MS);
      for (;;) {
        const {done, value} = await reader.read();
        if (done) break;
        parser.push(value);
      }
      teardown("ended");
    } catch (error) {
      if (controller?.signal.aborted) { stopped || teardown("aborted"); return; }
      teardown("error");
    }
  }

  return {
    start(overlay = true) { stopped = false; connect(overlay); },
    stop() {
      stopped = true;
      if (statsTimer) { statsTimer(); statsTimer = null; }
      controller?.abort();
      release();
    },
  };
}

export function createVisionPreview({
  apiGet,               // (path) => Promise<{status, body}> — JSON
  fetchFrame,           // (path) => Promise<Blob>
  intervalMs = MIN_PULL_INTERVAL_MS,
  onFrame,              // (blobUrl, meta) => void
  onUnavailable,        // (message) => void
  onQuality,            // optional raw observation quality; JPEG freshness is separate
  previewMode = () => "raw",
  now = () => Date.now(),
}) {
  let running = false;
  let pending = false;
  let timer = null;
  let seq = null;
  let objectUrl = null;
  let generation = 0;
  let hasFrame = false;
  let lastPullAt = -Infinity;   // 마지막 프레임 요청 시각 — 타이머 간격이 아니라 요청 간격을 지킨다

  function release() {
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = null;
  }

  async function tick() {
    if (!running || pending) return;
    pending = true;
    const gen = generation;
    try {
      const status = await apiGet("/api/v1/vision/front/status");
      if (gen !== generation) return;
      onQuality?.(status.status === 200 && status.body?.available === true ? status.body?.quality ?? null : null);
      if (status.status !== 200 || status.body?.available !== true) {
        seq = null;
        release();
        hasFrame = false;
        onUnavailable(status.body?.stale === true ? "카메라 프레임 지연" : "카메라 프레임 수신 대기");
        return;
      }
      const mode = previewMode();
      const key = `${status.body.sequence}:${mode}`;
      if (key === seq) {
        return;   // 같은 프레임 — 마지막 영상을 유지하고 건너뛴다(숨기지 않는다).
      }
      if (now() - lastPullAt < MIN_PULL_INTERVAL_MS) return;   // 다음 틱에 — 429 를 부르지 않는다
      lastPullAt = now();
      const pair = await fetchCameraPair(status.body, {fetchFrame, previewMode: mode});
      if (gen !== generation) return;
      seq = key;
      release();
      objectUrl = URL.createObjectURL(pair.blob);
      hasFrame = true;
      onFrame?.(objectUrl, {
        width: status.body.width, height: status.body.height,
        age_ms: status.body.age_ms,
        at: now(),
        seq: status.body.sequence,
        ...pair,
      });
    } catch (error) {
      // 409(시퀀스 진행)·네트워크 일시 오류는 프레임을 숨기지 않고 다음 틱에서 재시도.
      if (gen === generation) {
        seq = null; hasFrame = false; release();
        onUnavailable(error.message || "카메라 프레임 수신 대기");
      }
      if (gen === generation) onQuality?.(null);
    } finally {
      pending = false;
    }
  }

  return {
    start() {
      if (running) return;
      running = true;
      generation += 1;
      timer = setInterval(tick, Math.max(intervalMs, MIN_PULL_INTERVAL_MS));
      tick();
    },
    stop() {
      running = false;
      if (timer) clearInterval(timer);
      timer = null;
      generation += 1;
      release();
      hasFrame = false;
      onQuality?.(null);
      onUnavailable("카메라 중지");
    },
  };
}
