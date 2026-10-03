import { DOCK_STATE_LABEL, HeadlessState, enumLabel } from "/common/core_ui_logic.js";
import { poseUnavailableReason } from "./pose-evidence.js";
// D-359 §5.3 — 끌 때 이유를 같이 준다. 켜거나 짧은 요청 중 잠금이면 이유를 지운다.
function setOff(control, off, reason = "") { control.disabled = Boolean(off); if (off && reason) control.setAttribute("reason", reason); else control.removeAttribute("reason"); }

// Setup owns dock inventory and teach-by-docking; operational docking lives in /console.
function el(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; }
function setText(node, value) { if (node.textContent !== value) node.textContent = value; }

export function mount(root, ctx) {
  const head = el("ui-head", "", "도크 위치 준비");
  const status = el("ui-status", "", "현재 로봇 위치와 도크 실행 상태를 불러오는 중입니다.");
  const facts = el("dl", "ui-readout");
  const listStatus = el("ui-status", "", "");
  listStatus.setAttribute("role", "status"); listStatus.setAttribute("aria-live", "polite");
  const list = el("ul", "waypoint-list"); list.setAttribute("aria-label", "등록된 도크 위치");
  // D-359 US-009 — 빈 목록은 목록 밖의 ui-empty 한 줄이다(웨이포인트·도크 관리와 같은 모양).
  const emptyNote = el("ui-empty", "", "등록된 도크가 없습니다."); emptyNote.hidden = true;
  const actionStatus = el("ui-status", "", "");
  actionStatus.setAttribute("role", "status"); actionStatus.setAttribute("aria-live", "polite");
  root.append(head, status, facts, listStatus, list, emptyNote, actionStatus);

  let poseFresh = false;
  let docks = [];
  let docksLoaded = false;
  const pendingTeaches = new Set();
  let dockingSupported = null;
  function renderDocks() {
    list.replaceChildren();
    list.hidden = !docksLoaded || !docks.length;
    emptyNote.hidden = !docksLoaded || docks.length > 0;
    if (!docksLoaded) return;
    for (const dock of docks) {
      const row = el("li", ""); row.dataset.dockId = dock.id;
      const detail = el("span", "", `${dock.id} · ${dock.type || "유형 없음"} · 맵 ${dock.map_id || "미지정"}`);
      const recording = pendingTeaches.has(dock.id);
      const teach = el("ui-button", "", recording ? "위치 기록 요청 중…" : "현재 위치 기록");
      teach.setAttribute("kind", "primary"); teach.type = "button"; setOff(teach, !poseFresh || recording, recording ? "" : "위치 증거 확인 필요");
      teach.setAttribute("aria-label", recording ? `${dock.id} 위치 기록 요청 중` : `${dock.id}에 현재 로봇 위치 기록`);
      teach.addEventListener("click", async () => {
        if (!poseFresh || pendingTeaches.has(dock.id) || !docksLoaded
            || !window.confirm(`현재 위치를 ${dock.id} 도크 포즈로 기록할까요? 실제 도킹 위치에 로봇을 맞춘 뒤 진행하세요.`)) return;
        pendingTeaches.add(dock.id);
        setText(actionStatus, `${dock.id} 위치 기록 요청을 처리하고 있습니다.`);
        renderDocks();
        try { await ctx.api(`/api/v1/docking/docks/${encodeURIComponent(dock.id)}/teach`, {method: "POST"}); setText(actionStatus, `${dock.id}의 위치 기록 요청을 전달했습니다.`); }
        catch (error) { setText(actionStatus, `위치 기록 실패: ${error.message}`); }
        finally { pendingTeaches.delete(dock.id); renderDocks(); }
      });
      row.append(detail, teach); list.append(row);
    }
  }
  const stopState = ctx.store.poll("/api/v1/robot/state", 1_000, (state) => {
    poseFresh = new HeadlessState(state).isFresh("pose");
    status.textContent = poseFresh ? "위치를 읽었습니다. 실제 도크 위치에서 현재 위치 기록을 사용할 수 있습니다."
      : `${poseUnavailableReason(state)} · 현재 위치가 최신이 아니어서 도크 위치 기록을 막았습니다.`;
    renderDocks();
  }, (error) => { poseFresh = false; status.textContent = `현재 pose를 읽지 못했습니다: ${error.message}`; renderDocks(); });
  const stopStatus = ctx.store.poll("/api/v1/docking/status", 5_000, (data) => {
    dockingSupported = data.supported === true;
    facts.replaceChildren(el("dt", "", "도킹 기능"), el("dd", "", dockingSupported ? "사용 가능" : "미지원 또는 제한"),
      el("dt", "", "현재 상태"), Object.assign(el("dd", "", enumLabel(DOCK_STATE_LABEL, data.state)), {title: data.state || ""}),
      el("dt", "", "대상 도크"), el("dd", "", data.dock_id || "—"),
      el("dt", "", "오류"), el("dd", "", data.error || "없음"));
  }, (error) => { dockingSupported = false; facts.replaceChildren(el("dd", "", `도킹 상태를 읽지 못했습니다: ${error.message}`)); });
  const stopDocks = ctx.store.poll("/api/v1/docking/docks", 10_000, (data) => {
    docks = data.docks || []; docksLoaded = true; renderDocks();
    setText(listStatus, "");
  }, (error) => {
    docks = []; docksLoaded = false;
    renderDocks();
    setText(listStatus, `도크 목록을 읽지 못했습니다: ${error.message} · 복구될 때까지 위치 기록 조작을 숨겼습니다. 다시 확인 중입니다.`);
  });
  return () => { stopState(); stopStatus(); stopDocks(); };
}
