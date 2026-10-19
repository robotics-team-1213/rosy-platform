// 전방 카메라 미리보기 (D-262 첫 분해). 자격·전송은 셸의 api 를 빌리고,
// 주기·시퀀스·중단 상태는 이 모듈이 가진다. map.js 와 같은 팩토리 모양이다.
// D-398 — 증거 말·나이 뒤처리는 공용 어휘 표에서 온다.
import { EVIDENCE_LABEL, evidenceAgeText } from "/common/core_ui_logic.js";
import {fetchCameraPair} from "/common/evidence.js";
import {MEDIA_GRANT_PATH, openCamera, requestMediaGrant} from "/common/webrtc.js";

const WEBRTC_RETRY_MS = 15000, WEBRTC_RETRY_MAX_MS = 300000, GRAB_MS = 420;

export function createVisionPreview({
  elements, setText, api, authHeaders, hasToken, isHidden, onFrame, onUnavailable, onQuality,
  previewMode = () => "raw",
}) {
  const hasNumber = (value) => typeof value === "number" && Number.isFinite(value);
  let pending = false;
  let visionSequence = null;
  let objectUrl = null;
  let timer = null;
  let generation = 0;
  let aborter = null;
  // D-789: raw 보기는 사이트 영상 서비스가 있으면 WHEP <video>다. 없거나 실패하면 아래 순번 확인 JPEG(500ms)만 돈다.
  let camera = null, opening = false, video = null, siteMedia = true, failures = 0, retry = null, grabbedAt = 0;

  function releaseObjectUrl() {
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = null;
  }

  // D-359 US-009 — 상태 태그는 운용자 말과 증거 상태다. 옛 열거값(LIVE/WAITING/STALE)은 title에만.
  function renderEvidence(evidence, text, legacy) {
    setText("vision-status", text);
    const node = elements["vision-status"];
    node.dataset.evidence = evidence;
    node.title = legacy;
    node.setAttribute("status", evidence === "delayed" ? "warn" : "neutral");
  }

  function renderUnavailable(status = {}, message = "카메라 프레임 수신 대기") {
    onQuality?.(null);
    onUnavailable?.(message);
    const stale = status.stale === true;
    elements["vision-stage"].dataset.state = stale ? "stale" : "waiting";
    elements["vision-frame"].hidden = true;
    elements["vision-empty"].hidden = false;
    setText("vision-empty", message);
    if (stale) {
      renderEvidence("delayed", hasNumber(status.age_ms)
        ? `${EVIDENCE_LABEL.delayed}${evidenceAgeText(Math.max(0, Number(status.age_ms) / 1000))}` : EVIDENCE_LABEL.delayed, "STALE");
    } else renderEvidence("unavailable", "수신 대기", "WAITING");
    setText("vision-source", status.source || "—");
    setText("vision-resolution", status.width && status.height
      ? `${status.width}×${status.height}` : "—");
    setText("vision-age", hasNumber(status.age_ms)
      ? `${Math.round(Number(status.age_ms))} ms` : "—");
    setText("vision-captured", hasNumber(status.captured_at)
      ? `${Number(status.captured_at).toFixed(3)} s` : "—");
  }

  async function refresh() {
    if (pending || !hasToken() || camera) return;
    pending = true;
    const gen = generation;
    const controller = new AbortController();
    aborter = controller;
    try {
      const status = await api("/api/v1/vision/front/status", {
        signal: controller.signal, cache: "no-store",
      });
      if (gen !== generation || !hasToken() || camera) return;
      onQuality?.(status.available === true ? status.quality ?? null : null);
      if (!status.available) {
        visionSequence = null;
        releaseObjectUrl();
        renderUnavailable(
          status, status.stale ? "카메라 프레임 만료 · HOLD" : "카메라 프레임 수신 대기");
        return;
      }
      const mode = previewMode();
      const key = `${status.sequence}:${mode}`;
      if (visionSequence !== key) {
        const pair = await fetchCameraPair(status, {previewMode: mode,
          fetchFrame: (path) => fetch(path, {headers: authHeaders(), cache: "no-store", signal: controller.signal})});
        const blob = pair.blob;
        const nextUrl = URL.createObjectURL(blob);
        const candidate = new Image();
        candidate.src = nextUrl;
        try {
          await candidate.decode();
        } catch (error) {
          URL.revokeObjectURL(nextUrl);
          throw error;
        }
        if (gen !== generation || !hasToken() || camera) {
          URL.revokeObjectURL(nextUrl);
          return;
        }
        let rawImage = candidate;
        if (mode === "annotated") {
          const rawUrl = URL.createObjectURL(pair.rawBlob);
          rawImage = new Image(); rawImage.src = rawUrl;
          try { await rawImage.decode(); }
          catch (error) { URL.revokeObjectURL(nextUrl); throw error; }
          finally { URL.revokeObjectURL(rawUrl); }
        }
        if (gen !== generation || !hasToken() || camera) {
          URL.revokeObjectURL(nextUrl); return;
        }
        elements["vision-frame"].src = nextUrl;
        releaseObjectUrl();
        objectUrl = nextUrl;
        visionSequence = key;
        try {
          onFrame?.({...pair, image: candidate, rawImage, blob});
        } catch (_error) { /* Recording cannot interrupt the live preview. */ }
      }
      if (gen !== generation || !hasToken() || camera) return;
      setText("vision-source", status.source || "UNKNOWN");
      setText("vision-resolution", `${status.width || 0}×${status.height || 0}`);
      setText("vision-age", hasNumber(status.age_ms)
        ? `${Math.round(status.age_ms)} ms` : "—");
      setText("vision-captured", hasNumber(status.captured_at)
        ? `${Number(status.captured_at).toFixed(3)} s` : "—");
      elements["vision-frame"].hidden = false;
      elements["vision-empty"].hidden = true;
      elements["vision-stage"].dataset.state = "live";
      renderEvidence("fresh", "실시간", "LIVE");
    } catch (error) {
      if (error.name === "AbortError" || gen !== generation) return;
      onQuality?.(null);
      visionSequence = null;
      releaseObjectUrl();
      renderUnavailable({}, `카메라 연결 확인 · ${error.message}`);
    } finally {
      if (aborter === controller) {
        aborter = null;
        pending = false;
      }
    }
  }

  function stop(message = "카메라 인증 대기") {
    generation += 1;
    clearTimeout(retry);
    camera?.close("stopped");
    camera = null;
    if (video) video.hidden = true;
    aborter?.abort();
    aborter = null;
    clearInterval(timer);
    timer = null;
    pending = false;
    visionSequence = null;
    onQuality?.(null);
    releaseObjectUrl();
    renderUnavailable({}, message);
  }

  function pollJpeg() {
    if (timer || !hasToken() || isHidden()) return;
    refresh();
    timer = setInterval(refresh, 500);
  }

  async function postJson(path, body) {
    const response = await fetch(path, {method: "POST", cache: "no-store", body: JSON.stringify(body),
      headers: {...authHeaders(), "Content-Type": "application/json"}});
    return {status: response.status, body: response.ok ? await response.json() : null};
  }

  function videoElement() {
    if (video) return video;
    const frame = elements["vision-frame"];
    video = Object.assign(document.createElement("video"), {muted: true, autoplay: true, playsInline: true,
      className: frame.className, hidden: true});
    video.dataset.visionVideo = "";
    frame.after(video);
    return video;
  }

  // Recording keeps its JPEG input: one canvas grab per GRAB_MS from the rendered WebRTC frame.
  async function grab(state) {
    if (!onFrame || performance.now() - grabbedAt < GRAB_MS || !video.videoWidth) return;
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
      onFrame({image, rawImage: image, blob, rawBlob: blob, sequence: state.sequence, source: "WEBRTC",
               capturedAt: state.capturedMs / 1000, previewMode: "raw"});
    } catch (_error) { /* next grab */ } finally { URL.revokeObjectURL(url); }
  }

  function onWebrtc(state, gen) {
    if (gen !== generation) return;
    if (state.state === "live" || state.state === "stale") {
      failures = 0;
      video.hidden = false;
      elements["vision-frame"].hidden = true;
      elements["vision-empty"].hidden = true;
      elements["vision-stage"].dataset.state = state.state === "live" ? "live" : "stale";
      renderEvidence(state.state === "live" ? "fresh" : "delayed",
        state.state === "live" ? "실시간" : EVIDENCE_LABEL.delayed, state.state === "live" ? "LIVE" : "STALE");
      setText("vision-source", `WEBRTC ${state.fps}fps`);
      setText("vision-resolution", `${video.videoWidth || 0}×${video.videoHeight || 0}`);
      setText("vision-age", hasNumber(state.ageMs) ? `${Math.round(state.ageMs)} ms` : "—");
      setText("vision-captured", hasNumber(state.capturedMs) ? `${(state.capturedMs / 1000).toFixed(3)} s` : "—");
      if (state.state === "live") grab(state).catch(() => {});
    } else if (state.state === "hidden") {
      video.hidden = true;
      renderUnavailable({stale: true}, "영상 지연 · 2초 넘게 새 화면 없음");
    } else if ((state.state === "lost" || state.state === "closed") && state.reason !== "stopped") {
      camera = null;
      video.hidden = true;
      pollJpeg();
      retryLater(gen);
    }
  }

  function retryLater(gen) {
    clearTimeout(retry);
    retry = setTimeout(() => { if (gen === generation) tryWebrtc(gen); },
      Math.min(WEBRTC_RETRY_MS * 2 ** failures++, WEBRTC_RETRY_MAX_MS));
  }

  async function tryWebrtc(gen) {
    if (!siteMedia || camera || opening || previewMode() !== "raw" || !hasToken() || isHidden()) return;
    opening = true;
    try {
      const info = await api("/api/v1/system/info");
      const grant = info?.robot_id ? await requestMediaGrant(postJson, info.robot_id) : null;
      if (!grant) { siteMedia = false; return; }          // no site media on this robot: JPEG only
      if (gen !== generation) { revoke(grant.grant_id).catch(() => {}); return; }
      clearInterval(timer); timer = null;                  // never two transports at once
      camera = await openCamera({grant, video: videoElement(), onState: (state) => onWebrtc(state, gen),
        renewGrant: async (id) => {
          const result = await postJson(`${MEDIA_GRANT_PATH}/${id}/renew`, {});
          if (result.status !== 200) throw new Error("영상 권한 갱신 거절");
          return result.body;
        },
        revokeGrant: revoke});
      if (gen !== generation) { camera.close("stopped"); camera = null; }
    } catch (_error) {
      camera = null;
      if (gen === generation) { pollJpeg(); retryLater(gen); }
    } finally { opening = false; }
  }

  function revoke(id) {
    return fetch(`${MEDIA_GRANT_PATH}/${id}`, {method: "DELETE", headers: authHeaders()});
  }

  function start() {
    stop("카메라 프레임 수신 대기");
    failures = 0;
    if (!hasToken() || isHidden()) return;
    pollJpeg();
    tryWebrtc(generation);
  }

  return { start, stop, refresh };
}
