// 전방 카메라 미리보기 (D-262 첫 분해). 자격·전송은 셸의 api 를 빌리고,
// 주기·시퀀스·중단 상태는 이 모듈이 가진다. map.js 와 같은 팩토리 모양이다.

export function createVisionPreview({
  elements, setText, api, authHeaders, hasToken, isHidden,
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

  function renderUnavailable(status = {}, message = "카메라 프레임 수신 대기") {
    const stale = status.stale === true;
    elements["vision-stage"].dataset.state = stale ? "stale" : "waiting";
    elements["vision-frame"].hidden = true;
    elements["vision-empty"].hidden = false;
    setText("vision-empty", message);
    setText("vision-status", stale ? "STALE" : "WAITING");
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
      if (!status.available) {
        visionSequence = null;
        releaseObjectUrl();
        renderUnavailable(
          status, status.stale ? "카메라 프레임 만료 · HOLD" : "카메라 프레임 수신 대기");
        return;
      }
      if (visionSequence !== status.sequence) {
        const response = await fetch(
          `/api/v1/vision/front/frame?sequence=${encodeURIComponent(status.sequence)}`,
          {
            headers: authHeaders(), cache: "no-store", signal: controller.signal,
          },
        );
        if (response.status === 409 || response.status === 429) {
          visionSequence = null;
          releaseObjectUrl();
          renderUnavailable(
            status,
            response.status === 429
              ? "카메라 속도 제한 · 재동기화 대기"
              : "카메라 프레임 변경 · 재동기화 대기",
          );
          return;
        }
        if (!response.ok) throw new Error(`camera frame ${response.status}`);
        if (response.headers.get("X-Rosy-Camera-Sequence") !== String(status.sequence)) {
          return;
        }
        const nextUrl = URL.createObjectURL(await response.blob());
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
        elements["vision-frame"].src = nextUrl;
        releaseObjectUrl();
        objectUrl = nextUrl;
        visionSequence = status.sequence;
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
      setText("vision-status", "LIVE");
    } catch (error) {
      if (error.name === "AbortError" || gen !== generation) return;
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
