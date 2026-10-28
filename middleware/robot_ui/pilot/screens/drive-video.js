// 주행 화면 영상 전송(D-789 T4). 사이트 영상 서비스가 설정된 로봇은 WebRTC(WHEP <video>)가 기본이다.
// CORE가 503(사이트 미디어 없음)이면 기존 D-368 경로(JPEG 폴링 + 운전자 MJPEG)를 그대로 쓴다.
// WebRTC가 실패하면 JPEG 폴링(≥420ms)으로만 돌아가고 고속 MJPEG를 자동으로 열지 않는다.
// 한 번에 한 전송만 돈다: WebRTC를 시작하기 전에 폴링을 멈추고, 끝난 뒤에만 폴링을 연다.

import {api, connectionOffer, postJson, authHeaders} from "../client.js";
import {createDriverStream, MIN_PULL_INTERVAL_MS, STREAM_STALE_WARN_MS} from "../vision.js";
import {MEDIA_GRANT_PATH, openCamera, requestMediaGrant} from "/common/webrtc.js";
import {el} from "./drive-view.js";

export const WEBRTC_RETRY_MS = 15000;
// 계속 실패하면(예: 웹뷰 정책 거절) 15s→30s→…→5분으로 늦춰 권한 발급·회수 반복을 줄인다.
// 화면이 한 번 뜨거나, 네트워크가 바뀌거나(online), 사용자가 보기 방식을 바꾸면 처음 주기로 돌아간다.
export const WEBRTC_RETRY_MAX_MS = 300000;
const HIDDEN_GIVE_UP_MS = 5000;     // 2초 넘게 숨긴 영상이 5초 더 안 돌아오면 폴링으로 내린다

export function mountDriveVideo({root, element, capture, vision, acceptPreview}) {
  const fact = el("span", "영상 폴링", {"data-drive-fact": "video"});
  root.querySelector("[data-drive-facts]")?.append(fact);
  const video = el("video", null, {"data-drive-video": "", hidden: ""});
  Object.assign(video, {muted: true, autoplay: true, playsInline: true});
  element.frame.after(video);     // styles.css가 이미지 프레임과 같은 자리·비율로 그린다

  let alive = true, legacy = false, streaming = false;
  let camera = null, opening = false, robotId = null, retry = null, hiddenAt = null, grabbedAt = 0, failures = 0;
  const later = (fn, ms) => { clearTimeout(retry); if (alive) retry = setTimeout(fn, ms); };
  const raw = () => capture.state().previewMode === "raw";
  const retryLater = () => later(tryWebrtc, Math.min(WEBRTC_RETRY_MS * 2 ** failures++, WEBRTC_RETRY_MAX_MS));
  const online = () => { failures = 0; if (!legacy && !camera && raw()) later(tryWebrtc, 500); };
  globalThis.addEventListener?.("online", online);

  function poll(text, reason = "") {
    video.hidden = true;
    fact.textContent = text;
    fact.dataset.reason = reason;      // HUD text stays short; the cause is an attribute
    fact.dataset.stale = "false";
    vision.start();     // 이미 돌면 아무것도 하지 않는다
  }

  // --- 사이트 미디어 없는 로봇: D-368 운전자 MJPEG(변경 없음) ---------------
  const stream = createDriverStream({
    headers: () => authHeaders(),
    onFrame: (url, meta) => {
      if (!streaming) { streaming = true; vision.stop(); }
      acceptPreview(url, {blob: meta.blob, rawBlob: meta.blob, sequence: meta.seq,
                          source: meta.source, capturedAt: meta.capturedAt, previewMode: "raw"});
    },
    onStats: ({fps, ageMs}) => {
      fact.textContent = `영상 ${fps}fps${ageMs == null ? "" : ` · ${Math.round(ageMs)}ms`}`;
      fact.dataset.stale = String(ageMs != null && ageMs > STREAM_STALE_WARN_MS);
    },
    onLost: ({status}) => {
      streaming = false;
      poll(status === 409 ? "영상 폴링 · 운전자 아님" : "영상 폴링");
      later(tryStream, 3000);
    },
  });
  function tryStream() { if (alive && legacy && !streaming && raw()) stream.start(false); }

  // --- 녹화: WebRTC 화면을 폴링과 같은 주기의 JPEG로 기존 녹화 경로에 넣는다 --------
  async function grab(state) {
    if (!raw() || performance.now() - grabbedAt < MIN_PULL_INTERVAL_MS || !video.videoWidth) return;
    grabbedAt = performance.now();
    const canvas = Object.assign(document.createElement("canvas"), {width: video.videoWidth, height: video.videoHeight});
    canvas.getContext("2d").drawImage(video, 0, 0);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.85));
    if (!blob || !camera) return;
    const url = URL.createObjectURL(blob);
    const image = new Image();
    image.src = url;
    try {
      await image.decode();
      capture.acceptFrame({image, blob, rawBlob: blob, sequence: state.sequence, source: "WEBRTC",
                           capturedAt: state.capturedMs / 1000, previewMode: "raw"});
    } catch (_error) { /* 다음 주기에 다시 */ } finally { URL.revokeObjectURL(url); }
  }

  function onState(state) {
    if (state.state === "live" || state.state === "stale") {
      hiddenAt = null;
      failures = 0;
      video.hidden = false;
      element.frame.hidden = true;
      element.empty.hidden = true;
      fact.textContent = `영상 WebRTC ${state.fps}fps · ${Math.round(state.ageMs)}ms`;
      fact.dataset.stale = String(state.state === "stale");   // 1초 초과: 정지 프레임 경고
      if (state.state === "live") grab(state);
    } else if (state.state === "waiting") {
      fact.textContent = "영상 WebRTC · 첫 화면 대기";
    } else if (state.state === "hidden") {                   // 2초 초과: 영상을 숨긴다
      video.hidden = true;
      element.empty.hidden = false;
      element.empty.textContent = "영상 지연 · 2초 넘게 새 화면 없음";
      fact.dataset.stale = "true";
      capture.unavailable("영상이 지연되었습니다.");
      hiddenAt ??= performance.now();
      if (performance.now() - hiddenAt > HIDDEN_GIVE_UP_MS) camera?.close("stale");
    } else if (state.state === "lost" || state.state === "closed") {
      if (state.reason === "replaced") return;
      camera = null;
      hiddenAt = null;
      if (!alive || state.reason === "stopped") return;
      poll("영상 폴링", `webrtc-${state.reason}`);
      if (raw() && !opening) retryLater();     // 여는 중의 실패는 tryWebrtc의 catch가 한 번만 센다
    }
  }

  async function tryWebrtc() {
    if (!alive || legacy || camera || opening || !raw()) return;
    opening = true;
    try {
      robotId ??= (await connectionOffer())?.robotId ?? null;
      const grant = robotId ? await requestMediaGrant(postJson, robotId) : null;
      if (grant === null) { legacy = true; tryStream(); return; }   // 사이트 미디어 없음: 기존 경로
      if (!alive || !raw()) { api(`${MEDIA_GRANT_PATH}/${grant.grant_id}`, {method: "DELETE"}).catch(() => {}); return; }
      vision.stop();       // 두 전송을 겹치지 않는다
      fact.textContent = "영상 WebRTC 연결 중";
      camera = await openCamera({
        grant, video, onState,
        renewGrant: async (id) => {
          const result = await postJson(`${MEDIA_GRANT_PATH}/${id}/renew`, {});
          if (result.status !== 200) throw new Error("영상 권한 갱신 거절");
          return result.body;
        },
        revokeGrant: (id) => api(`${MEDIA_GRANT_PATH}/${id}`, {method: "DELETE"}),
      });
      if (!alive || !raw()) camera.close("stopped");
    } catch (_error) {
      camera = null;
      if (alive) poll("영상 폴링", "webrtc-failed");
      if (raw()) retryLater();
    } finally {
      opening = false;
    }
  }

  tryWebrtc();
  return {
    // 주석 쌍(annotated)은 원본 짝이 필요해 폴링만 섬긴다. raw로 돌아오면 원래 전송을 다시 시도한다.
    previewModeChanged(mode) {
      clearTimeout(retry);
      failures = 0;
      camera?.close("stopped");
      camera = null;
      streaming = false;
      stream.stop();
      vision.stop(); vision.start();
      fact.textContent = "영상 폴링";
      if (mode === "raw") later(legacy ? tryStream : tryWebrtc, 500);
    },
    stop() {
      alive = false;
      clearTimeout(retry);
      globalThis.removeEventListener?.("online", online);
      camera?.close("stopped");
      stream.stop();
      video.remove();
    },
  };
}
