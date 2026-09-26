import { HeadlessState } from "/common/core_ui_logic.js";

// Setup owns dock inventory and teach-by-docking; operational docking lives in /console.
function el(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; }

export function mount(root, ctx) {
  const head = el("ui-head", "", "도크 위치 준비");
  const status = el("p", "surface-message", "로봇 pose와 도크 목록을 불러오는 중입니다."); status.setAttribute("role", "status");
  const facts = el("dl", "ui-readout");
  const list = el("ul", "waypoint-list"); list.setAttribute("aria-label", "등록된 도크 위치");
  root.append(head, status, facts, list);

  let poseFresh = false;
  let docks = [];
  let dockingSupported = null;
  function renderDocks() {
    list.replaceChildren();
    if (!docks.length) { list.append(el("li", "", "등록된 도크가 없습니다.")); return; }
    for (const dock of docks) {
      const row = el("li", ""); row.dataset.dockId = dock.id;
      const detail = el("span", "", `${dock.id} · ${dock.type || "유형 없음"} · 맵 ${dock.map_id || "미지정"}`);
      const teach = el("ui-button", "", "현재 위치 기록"); teach.setAttribute("kind", "primary"); teach.type = "button"; teach.disabled = !poseFresh;
      teach.setAttribute("aria-label", `${dock.id}에 현재 로봇 위치 기록`);
      teach.addEventListener("click", async () => {
        if (!poseFresh || !window.confirm(`현재 위치를 ${dock.id} 도크 포즈로 기록할까요? 실제 도킹 위치에 로봇을 맞춘 뒤 진행하세요.`)) return;
        teach.disabled = true;
        try { await ctx.api(`/api/v1/docking/docks/${encodeURIComponent(dock.id)}/teach`, {method: "POST"}); status.textContent = `${dock.id}의 위치 기록 요청을 전달했습니다.`; }
        catch (error) { status.textContent = `위치 기록 실패: ${error.message}`; }
        finally { teach.disabled = !poseFresh; }
      });
      row.append(detail, teach); list.append(row);
    }
  }
  const stopState = ctx.store.poll("/api/v1/robot/state", 1_000, (state) => {
    poseFresh = new HeadlessState(state).isFresh("pose");
    status.textContent = poseFresh ? "위치를 읽었습니다. 실제 도크 위치에서 현재 위치 기록을 사용할 수 있습니다." : "pose 상태가 최신이 아니어서 도크 위치 기록을 막았습니다.";
    renderDocks();
  }, (error) => { poseFresh = false; status.textContent = `현재 pose를 읽지 못했습니다: ${error.message}`; renderDocks(); });
  const stopStatus = ctx.store.poll("/api/v1/docking/status", 5_000, (data) => {
    dockingSupported = data.supported === true;
    facts.replaceChildren(el("dt", "", "도킹 capability"), el("dd", "", dockingSupported ? "사용 가능" : "미지원 또는 제한"),
      el("dt", "", "현재 상태"), el("dd", "", data.state || "—"),
      el("dt", "", "대상 도크"), el("dd", "", data.dock_id || "—"),
      el("dt", "", "오류"), el("dd", "", data.error || "없음"));
  }, (error) => { dockingSupported = false; facts.replaceChildren(el("dd", "", `도킹 상태를 읽지 못했습니다: ${error.message}`)); });
  const stopDocks = ctx.store.poll("/api/v1/docking/docks", 10_000, (data) => { docks = data.docks || []; renderDocks(); }, (error) => { status.textContent = `등록된 도크를 읽지 못했습니다: ${error.message}`; });
  return () => { stopState(); stopStatus(); stopDocks(); };
}
