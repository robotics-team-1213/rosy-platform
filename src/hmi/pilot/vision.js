// 전방 카메라 미리보기 폴링(D-323 T7). dashboard vision.js 팩토리 패턴:
// 자격·전송은 주입받고, 주기·시퀀스·중단 상태는 이 모듈이 가진다.
// 409(시퀀스 진행)는 오류가 아니라 다음 틱에서 재시도한다 — 프레임을 숨기지 않는다.
// 주기는 CORE 계약의 하한(vision.preview_min_pull_interval_s ≥ 0.4s)보다 짧으면 안 된다.
// 더 자주 당기면 429 만 늘고, 그 요청들이 teleop 과 같은 브라우저 연결 풀을 잡아먹는다.

export const MIN_PULL_INTERVAL_MS = 420;

export function createVisionPreview({
  apiGet,               // (path) => Promise<{status, body}> — JSON
  fetchFrame,           // (path) => Promise<Blob>
  intervalMs = MIN_PULL_INTERVAL_MS,
  onFrame,              // (blobUrl, meta) => void
  onUnavailable,        // (message) => void
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
      if (status.status !== 200 || status.body?.available !== true) {
        seq = null;
        release();
        hasFrame = false;
        onUnavailable(status.body?.stale === true ? "프레임 지연(STALE)" : "카메라 프레임 수신 대기");
        return;
      }
      if (status.body.sequence === seq) {
        return;   // 같은 프레임 — 마지막 영상을 유지하고 건너뛴다(숨기지 않는다).
      }
      if (now() - lastPullAt < MIN_PULL_INTERVAL_MS) return;   // 다음 틱에 — 429 를 부르지 않는다
      lastPullAt = now();
      const frame = await fetchFrame(`/api/v1/vision/front/frame?sequence=${status.body.sequence}`);
      if (gen !== generation) return;
      seq = status.body.sequence;
      release();
      objectUrl = URL.createObjectURL(frame);
      hasFrame = true;
      onFrame?.(objectUrl, {
        width: status.body.width, height: status.body.height,
        age_ms: status.body.age_ms,
        at: now(),
        seq: status.body.sequence,
        blob: frame,
      });
    } catch (error) {
      // 409(시퀀스 진행)·네트워크 일시 오류는 프레임을 숨기지 않고 다음 틱에서 재시도.
      if (gen === generation && !hasFrame) {
        onUnavailable("카메라 프레임 수신 대기");
      }
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
      onUnavailable("카메라 중지");
    },
  };
}
