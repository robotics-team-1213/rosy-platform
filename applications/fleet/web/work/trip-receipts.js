import {tripEndText, tripErrorText, tripWaitText} from "/console/assets/trip-display.js";

const PHASE = {preview: "경로 계산 완료 · 출발 전", plan_refused: "경로 계산 거절",
  start_refused: "출발 거절", start_accepted: "Fleet 출발 접수"};

function outcomeText(trip) {
  if (trip?.state === "canceled")
    return trip.detail?.stop_sent === true ? "운행 취소 · 기체 정지 명령 수락" : "운행 취소 · 기체 정지 응답 미확인";
  if (trip?.state === "arrived") return "Fleet 도착 판정";
  return tripEndText(trip) || tripWaitText(trip);
}

function receiptText(row) {
  const dest = typeof row.to === "string" ? row.to : row.to ? `(${row.to.x}, ${row.to.y})` : "";
  const reason = row.code ? `${tripErrorText(row.code, row.detail || {})} [${row.code}${row.detail?.error ? " / " + row.detail.error : ""}]` : "";
  return [dest, PHASE[row.stage], reason, outcomeText(row.outcome)].filter(Boolean).join(" · ");
}

export function selectedTripText(view, robotId) {
  const g = view.selectedGoal;
  if (g?.robotId !== robotId || !g.statusText || Date.now() - g.at > 120000) return "";
  const phase = g.status === "BLOCKED" ? "출발 보류" : g.status === "PREVIEW" ? "출발 전" : "";
  return [g.placeId || g.label, phase, g.statusText].filter(Boolean).join(" · ");
}

export function updateSelectedTrip(view, trips) {
  const goal = view.selectedGoal;
  if (!goal?.tripId) return false;
  const trip = [...(trips.open || []), ...(trips.trips || [])].find(
    row => row.trip_id === goal.tripId && row.robot_id === goal.robotId);
  if (!trip) return false;

  let status = "ACCEPTED", text = "Fleet 접수 · 기체 실행 확인 중";
  if (["failed", "stopped", "canceled"].includes(trip.state)) {
    status = "BLOCKED";
    text = outcomeText(trip);
  } else if (trip.state === "arrived") {
    status = "ARRIVED";
    text = "Fleet 도착 판정";
  } else if (trip.detail?.peer_wait) {
    text = tripWaitText(trip);
  } else if (trip.hold) {
    text = `관제 대기 · ${trip.hold.reason || "통행 확인 중"}`;
  } else if (trip.state === "running") {
    text = "운행 처리 중";
  }
  if (goal.status === status && goal.statusText === text) return false;
  Object.assign(goal, {status, statusText: text, at: Date.now()});
  return true;
}

export function installTripReceiptHistory(el, call) {
  const panel = el("trip-receipt-history");
  if (!panel) return;
  let seq = 0;
  const refresh = async () => {
    const id = ++seq, list = el("trip-receipt-rows");
    list.textContent = "운행 기록 조회 중";
    try {
      const {requests} = await call("/api/fleet/trip-requests");
      if (id !== seq || !panel.open) return;
      list.replaceChildren(...requests.map(row => {
        const item = document.createElement("li");
        const when = new Date(row.at * 1000).toLocaleString("ko-KR", {hour12: false});
        item.textContent = `${when} · ${row.robot_id} · ${receiptText(row)} · ${row.plan_id}`;
        return item;
      }));
      if (!requests.length) list.textContent = "운행 요청 기록 없음";
    } catch (err) {
      if (id === seq) list.textContent = `운행 기록 조회 실패 · ${err.message}`;
    }
  };
  panel.addEventListener("toggle", () => { if (panel.open) refresh(); else ++seq; });
  el("trip-receipt-refresh").addEventListener("click", refresh);
}

export async function cancelTripReceipt(call, tripId, life) {
  try {
    return await call(`/api/fleet/trips/${encodeURIComponent(tripId)}/cancel`, {method: "POST"});
  } catch (err) {
    if (err.name === "AbortError") throw err;
    life.check();
    return call(`/api/fleet/trips/${encodeURIComponent(tripId)}`);
  }
}
