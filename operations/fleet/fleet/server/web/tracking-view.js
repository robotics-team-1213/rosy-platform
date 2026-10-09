// D-457 관제 카메라 추적 상태줄. "배경 다시 학습"은 설치·보정 문서의 tracking-relearn.js 다(D-540 5). 그림은 map-view.js 가 view.cameraTracking 으로 그린다.
// 표시 전용 — 목표·교통정리·미션에 넘기지 않는다.

import { classifyTracking, trackingStatusLine, positionRows, displayLeaseMs,
  trackingDriftSample, calibrationDriftVerdict, rememberTrackingPoses, CALIBRATION_DRIFT_POLLS,
} from "./tracking-layer.js";
import { isRouteAbsent } from "/console/assets/poll-gate.js";

export function createTrackingView({ scope, el, view, call, auth, onChanged = () => {} }) {
  const line = el("tracking-state");
  const legend = el("legend-tracking");
  const positions = el("tracking-positions");
  const positionBody = el("tracking-position-rows");
  let inFlight = false;
  let unavailable = false; // 라우트 없음(404) — 이 Fleet 에 추적이 설정되지 않았다(카메라 source 없음)
  let cancelExpiry = () => {};
  let driftHistory = [];        // 폴링별 trackingDriftSample 결과 — 교정 낡음 판정 재료
  let previousPoses = new Map(); // 직전 폴링의 MATCHED 자세(정지 로봇 가림)

  // 응답이 없으면 빈 층이다 — 지난 고리·선·상태를 남기지 않는다. 그림이 바뀌었을 때만 지도를 다시 그린다.
  function show(body, elapsedMs = 0) {
    cancelExpiry();
    cancelExpiry = () => {};
    const remaining = displayLeaseMs(body, elapsedMs);
    const next = classifyTracking(remaining > 0 ? body : null);
    const changed = JSON.stringify(next) !== JSON.stringify(view.cameraTracking);
    view.cameraTracking = next;
    // 교정 낡음 표본은 실제 폴링 응답마다 한 번만 쌓는다. 수명 만료 show(null)은 연속을
    // 끊지 않는다 — 만료는 데이터 신선도이지 교정 상태가 아니기 때문이다.
    if (body) {
      driftHistory.push(trackingDriftSample(next, previousPoses));
      driftHistory = driftHistory.slice(-CALIBRATION_DRIFT_POLLS);
      previousPoses = rememberTrackingPoses(next);
      view.trackingDrift = calibrationDriftVerdict(driftHistory);
    }
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
    } else {
      const status = body ? trackingStatusLine(body)
        : { state: "warn", text: "관제 카메라 추적 상태를 읽지 못했습니다" };
      line.hidden = false;
      line.dataset.state = status.state;
      line.textContent = status.text;
    }
  }

  function reset() {
    unavailable = false;
    driftHistory = [];
    previousPoses = new Map();
    view.trackingDrift = null;
    show(null);
    line.hidden = true;
  }

  return { refresh, reset };
}
