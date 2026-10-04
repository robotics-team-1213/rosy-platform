// 전방 카메라 미리보기 (D-262 첫 분해). 자격·전송은 셸의 api 를 빌리고,
// 주기·시퀀스·중단 상태는 이 모듈이 가진다. map.js 와 같은 팩토리 모양이다.
// D-398 — 증거 말·나이 뒤처리는 공용 어휘 표에서 온다.
import { EVIDENCE_LABEL, evidenceAgeText } from "/common/core_ui_logic.js";
import {fetchCameraPair} from "/common/evidence.js";

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
    if (pending || !hasToken()) return;
    pending = true;
    const gen = generation;
    const controller = new AbortController();
    aborter = controller;
    try {
      const status = await api("/api/v1/vision/front/status", {
        signal: controller.signal, cache: "no-store",
      });
      if (gen !== generation || !hasToken()) return;
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
        if (gen !== generation || !hasToken()) {
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
        if (gen !== generation || !hasToken()) {
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
      if (gen !== generation || !hasToken()) return;
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

  function start() {
    stop("카메라 프레임 수신 대기");
    if (!hasToken() || isHidden()) return;
    refresh();
    timer = setInterval(refresh, 500);
  }

  return { start, stop, refresh };
}
