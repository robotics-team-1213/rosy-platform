// D-457 관제 카메라 추적 상태줄·"배경 다시 학습". 그림은 map-view.js 가 view.cameraTracking 으로 그린다.
// 표시 전용 — 목표·교통정리·미션에 넘기지 않는다.

import { classifyTracking, trackingStatusLine, positionRows, displayLeaseMs } from "./tracking-layer.js";
import { isRouteAbsent } from "./poll-gate.js";

const RELEARN_WARNING = "배경을 다시 학습합니다. 트랙 위의 로봇과 물건을 모두 치운 뒤 진행하세요 — "
  + "남아 있으면 배경으로 굳어 추적되지 않습니다(약 10초). 계속할까요?";

export function createTrackingView({ scope, el, view, call, auth, onChanged = () => {},
  confirm = (text) => window.confirm(text) }) {
  const line = el("tracking-state");
  const relearn = el("tracking-relearn");
  const legend = el("legend-tracking");
  const positions = el("tracking-positions");
  const positionBody = el("tracking-position-rows");
  let inFlight = false;
  let relearning = false;
  let unavailable = false; // 라우트 없음(404) — 이 Fleet 에 추적이 설정되지 않았다(카메라 source 없음)
  let sources = [];
  let cancelExpiry = () => {};

  // 응답이 없으면 빈 층이다 — 지난 고리·선·상태를 남기지 않는다. 그림이 바뀌었을 때만 지도를 다시 그린다.
  function show(body, elapsedMs = 0) {
    cancelExpiry();
    cancelExpiry = () => {};
    const remaining = displayLeaseMs(body, elapsedMs);
    const next = classifyTracking(remaining > 0 ? body : null);
    const changed = JSON.stringify(next) !== JSON.stringify(view.cameraTracking);
    view.cameraTracking = next;
    sources = (body?.sources || []).map((source) => source.source_id);
    legend.hidden = !(next.robots.length || next.unknown.length);
    if (positions && positionBody) {
      const rows = positionRows(next);
      positionBody.replaceChildren(...rows.map(row => {
        const tr = document.createElement("tr");
        for (const value of [row.name, row.x, row.y, row.basis]) {
          const td = document.createElement("td");
          td.textContent = value;
          tr.append(td);
        }
        return tr;
      }));
      positions.hidden = !rows.length;
    }
    if (changed) onChanged();
    if (next.robots.length || next.unknown.length) {
      cancelExpiry = scope.timeout(() => {
        show(null);
        line.dataset.state = "warn";
        line.textContent = "관제 카메라 추적: 위치 수명 만료 — 새 관측을 기다립니다";
      }, remaining);
    }
  }

  async function refresh() {
    const life = scope.capture();
    life.check();
    if (inFlight || unavailable) return;
    if (auth.locked) {
      show(null);
      line.hidden = true;
      relearn.hidden = true;
      return;
    }
    inFlight = true;
    const started = performance.now();
    let body = null;
    try {
      body = await call("/api/fleet/tracking", { signals: [life.signal] });
      life.check();
    } catch (error) {
      if (error.name === "AbortError") return;
      if (isRouteAbsent(error.status, error.code)) unavailable = true;
    } finally {
      inFlight = false;
    }
    show(body, performance.now() - started);
    if (unavailable || auth.locked) {
      line.hidden = true;
      relearn.hidden = true;
    } else {
      const status = body ? trackingStatusLine(body)
        : { state: "warn", text: "관제 카메라 추적 상태를 읽지 못했습니다" };
      line.hidden = false;
      line.dataset.state = status.state;
      line.textContent = status.text;
      relearn.hidden = !sources.length;
    }
  }

  scope.listen(relearn, "click", async () => {
    const life = scope.capture();
    life.check();
    if (auth.locked || auth.role !== "operator" || !sources.length || relearning
        || !confirm(RELEARN_WARNING)) return;
    relearning = true;
    try {
      for (const sourceId of sources) {
        await call("/api/fleet/tracking/relearn", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source_id: sourceId }),
          signals: [life.signal],
        });
        life.check();
      }
      line.dataset.state = "warn";
      line.textContent = "배경을 다시 학습합니다 — 트랙을 비워 두세요(약 10초).";
    } catch (error) {
      if (error.name === "AbortError") return;
      line.dataset.state = "warn";
      line.textContent = `배경 다시 학습 실패: ${error.message || error}`;
    } finally {
      relearning = false;
    }
  });

  function reset() {
    unavailable = false;
    sources = [];
    show(null);
    line.hidden = true;
    relearn.hidden = true;
  }

  return { refresh, reset };
}
