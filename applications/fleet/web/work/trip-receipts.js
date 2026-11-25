import {tripErrorText} from "/console/assets/trip-display.js";

const PHASE = {preview: "경로 계산 완료 · 출발 전", plan_refused: "경로 계산 거절",
  start_refused: "출발 거절", start_accepted: "Fleet 출발 접수"};

function receiptText(row) {
  const dest = typeof row.to === "string" ? row.to : row.to ? `(${row.to.x}, ${row.to.y})` : "";
  const reason = row.code ? `${tripErrorText(row.code, row.detail || {})} [${row.code}${row.detail?.error ? " / " + row.detail.error : ""}]` : "";
  return [dest, PHASE[row.stage], reason].filter(Boolean).join(" · ");
}

export function selectedTripText(view, robotId) {
  const g = view.selectedGoal;
  if (g?.robotId !== robotId || !g.statusText || Date.now() - g.at > 120000) return "";
  const phase = g.status === "BLOCKED" ? "출발 보류" : g.status === "PREVIEW" ? "출발 전" : "";
  return [g.placeId || g.label, phase, g.statusText].filter(Boolean).join(" · ");
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
